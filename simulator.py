import time
import random
import os
import requests
import logging
import pandas as pd
from pathlib import Path
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ===================== CONFIG ======================
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "demo_token_please_change")
INFLUX_ORG = os.getenv("INFLUX_ORG", "demo_org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "demo_bucket")

ELECTRICITY_MAPS_API_KEY = os.getenv("ELECTRICITY_MAPS_API_KEY", "")
ELECTRICITY_MAPS_ZONE = os.getenv("ELECTRICITY_MAPS_ZONE", "US-CAL-CISO") 

print(f"Connecting to InfluxDB at {INFLUX_URL}...")
client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = client.write_api(write_options=SYNCHRONOUS)

# =================== FIXED VALUES ===================
# Assumed parameters hardcoded for formulas
ASSUMED_VALUES = {
    "P_core_w": 25.0,
    "P_mem_w": 10.0,
    "P_storage_w": 5.0,
    "E_network_mj_gb": 1.0,
    "P_GPU_w": 0.0,
    "P_Proc_w": 15.0,
    "P_active_w": 0.005,
    "P_idle_w": 0.0001,
    "C_mem_gb": 1024.0,
    # Grid_emission_factor_gCO2_kwh is fetched dynamically
    "PUE": 1.5,
    "N_inv": 1000.0,
    "S_upload_mb": 1.2,
}

# ================== METRICS FILE PATHS ====================
METRICS_BASE_PATH = Path(__file__).parent / "Final Serverless Metrics"
METRIC_FILES = {
    "Lambda": {
        "DoorbellLambda": METRICS_BASE_PATH / "Lambda" / "DoorbellLambda.xlsx",
        "FaceRecognitionLambda": METRICS_BASE_PATH / "Lambda" / "FaceRecognitionLambda.xlsx",
        "FetchWebsiteFromS3": METRICS_BASE_PATH / "Lambda" / "FetchWebsiteFromS3.xlsx",
        "PINVerificationLambda": METRICS_BASE_PATH / "Lambda" / "PINVerificationLambda.xlsx",
        "UploadLambda": METRICS_BASE_PATH / "Lambda" / "UploadLambda.xlsx",
    },
    "S3": {
        "mhm-home-security-img": METRICS_BASE_PATH / "S3" / "mhm-home-security-img.xlsx",
        "mhm-home-security-ui": METRICS_BASE_PATH / "S3" / "mhm-home-security-ui.xlsx",
    },
    "DynamoDB": {
        "Events": METRICS_BASE_PATH / "DynamoDB" / "Events.xlsx",
        "Users": METRICS_BASE_PATH / "DynamoDB" / "Users.xlsx",
    },
    "API": {
        "API": METRICS_BASE_PATH / "API Gateway" / "API.xlsx",
    },
    "Rekognition": {
        "Rekognition": METRICS_BASE_PATH / "Rekognition" / "Rekognition.xlsx",
    }
}

# Cache for Grid Emission Factor
_cached_grid_emission_factor = 350.0
_last_fetch_time = 0

def get_grid_emission_factor():
    """
    Fetches the latest grid emission factor from Electricity Maps.
    """
    global _cached_grid_emission_factor, _last_fetch_time
    
    # Cache for 15 minutes (900 seconds)
    if time.time() - _last_fetch_time < 900 and _last_fetch_time != 0:
        return _cached_grid_emission_factor

    if not ELECTRICITY_MAPS_API_KEY:
        # logging.warning("No ELECTRICITY_MAPS_API_KEY set. Using default value.")
        return 350.0

    url = "https://api.electricitymap.org/v3/carbon-intensity/latest"
    headers = {"auth-token": ELECTRICITY_MAPS_API_KEY}
    params = {"zone": ELECTRICITY_MAPS_ZONE}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        carbon_intensity = data.get("carbonIntensity")
        if carbon_intensity:
            _cached_grid_emission_factor = float(carbon_intensity)
            _last_fetch_time = time.time()
            logging.info(f"Updated Grid Emission Factor: {_cached_grid_emission_factor} gCO2/kWh")
    except Exception as e:
        logging.error(f"Failed to fetch grid emission factor: {e}")
    
    return _cached_grid_emission_factor

def lp_timestamp():
    return str(time.time_ns())

def read_excel_metrics(file_path):
    """
    Read metrics from an Excel file.
    Expected format: Column A has metric names, Column B has values.
    Returns a dictionary of {metric_name: value}
    """
    try:
        if not os.path.exists(file_path):
            logging.warning(f"Metrics file not found: {file_path}")
            return {}
        
        df = pd.read_excel(file_path, header=None)
        metrics = {}
        for idx, row in df.iterrows():
            if len(row) >= 2:
                metric_name = str(row[0]).strip()
                try:
                    metric_value = float(row[1])
                    metrics[metric_name] = metric_value
                except (ValueError, TypeError):
                    logging.warning(f"Could not convert metric value for {metric_name}: {row[1]}")
        return metrics
    except Exception as e:
        logging.error(f"Error reading Excel file {file_path}: {e}")
        return {}

def read_all_component_metrics():
    """
    Read all measured metrics from Final Serverless Metrics folder.
    Returns a dictionary with component aggregations and individual metrics.
    """
    all_metrics = {}
    component_energies = {}
    
    # Read Lambda metrics
    lambda_metrics = []
    for lambda_name, file_path in METRIC_FILES["Lambda"].items():
        metrics = read_excel_metrics(file_path)
        if metrics:
            lambda_metrics.append({lambda_name: metrics})
            all_metrics[f"lambda_{lambda_name}"] = metrics
    
    # Read S3 metrics
    s3_metrics = []
    for bucket_name, file_path in METRIC_FILES["S3"].items():
        metrics = read_excel_metrics(file_path)
        if metrics:
            s3_metrics.append({bucket_name: metrics})
            all_metrics[f"s3_{bucket_name}"] = metrics
    
    # Read DynamoDB metrics
    dynamodb_metrics = []
    for table_name, file_path in METRIC_FILES["DynamoDB"].items():
        metrics = read_excel_metrics(file_path)
        if metrics:
            dynamodb_metrics.append({table_name: metrics})
            all_metrics[f"dynamodb_{table_name}"] = metrics
    
    # Read API Gateway metrics
    for api_name, file_path in METRIC_FILES["API"].items():
        metrics = read_excel_metrics(file_path)
        if metrics:
            all_metrics[f"api_{api_name}"] = metrics
    
    # Read Rekognition metrics
    for rekog_name, file_path in METRIC_FILES["Rekognition"].items():
        metrics = read_excel_metrics(file_path)
        if metrics:
            all_metrics[f"rekognition_{rekog_name}"] = metrics
    
    return all_metrics

def simulate_measured():
    """
    Load measured metrics from Excel files.
    Flattens the nested structure into a flat dictionary for InfluxDB.
    """
    out = {}
    all_component_metrics = read_all_component_metrics()
    
    # Flatten all component metrics
    for component_key, metrics in all_component_metrics.items():
        for metric_name, metric_value in metrics.items():
            # Create flattened key like: lambda_DoorbellLambda_Tinit
            flat_key = f"{component_key}_{metric_name}"
            out[flat_key] = metric_value
    
    return out



def write_metrics():
    timestamp = lp_timestamp()
    
    # Measured Data
    measured = simulate_measured()
    
    # Assumed / Dynamic Data
    grid_emission_factor = get_grid_emission_factor()
    
    # Add Grid Factor and Assumed Values to measured data
    measured["grid_emission_factor"] = grid_emission_factor
    for key, value in ASSUMED_VALUES.items():
        measured[f"assumed_{key}"] = value

    # Write Measured
    fields_meas = ",".join([f"{k}={v}" for k, v in measured.items()])
    lp_measured = f"measured_metrics {fields_meas} {timestamp}"
    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=lp_measured)

    print(f"[{timestamp}] Wrote metrics. GridFactor={grid_emission_factor}")


if __name__ == "__main__":
    print("🚀 Writing metrics to InfluxDB...")
    try:
        write_metrics()
        print("✅ Metrics successfully written to InfluxDB. Exiting.")
        client.close()
    except Exception as e:
        logging.error(f"Error writing metrics: {e}")
        client.close()
        exit(1)


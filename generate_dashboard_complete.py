#!/usr/bin/env python3
"""
Complete Dynamic Dashboard Generator
Generates dashboard.json based on discovered Excel files
Updates all panel queries with dynamic component discovery
"""

import json
import copy
from pathlib import Path
from simulator import METRIC_FILES

# ============================================================================
# FLUX QUERY BUILDERS
# ============================================================================

def generate_combined_energy_query(lambda_comp, s3_comp, dynamodb_comp, api_comp, rekognition_comp):
    """Generate the complete Flux query that calculates all energy types"""
    
    # Lambda components sum
    lambda_tcpu_malloc = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Tcpu\"] then r[\"lambda_{name}_Tcpu\"] else 0.0) * (if exists r[\"lambda_{name}_Malloc\"] then r[\"lambda_{name}_Malloc\"] else 0.0)"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_mused_texec_tinit = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Mused\"] then r[\"lambda_{name}_Mused\"] else 0.0) * ((if exists r[\"lambda_{name}_Texec\"] then r[\"lambda_{name}_Texec\"] else 0.0) + (if exists r[\"lambda_{name}_Tinit\"] then r[\"lambda_{name}_Tinit\"] else 0.0))"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_sused_texec_tinit = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Sused\"] then r[\"lambda_{name}_Sused\"] else 0.0) * ((if exists r[\"lambda_{name}_Texec\"] then r[\"lambda_{name}_Texec\"] else 0.0) + (if exists r[\"lambda_{name}_Tinit\"] then r[\"lambda_{name}_Tinit\"] else 0.0))"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_dnetwork = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Dnetwork\"] then r[\"lambda_{name}_Dnetwork\"] else 0.0)"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    # S3 components
    s3_active_sum = (
        "(" + " + ".join([
            f"(if exists r[\"s3_{name}_Rtotal\"] then r[\"s3_{name}_Rtotal\"] else 0.0) * (if exists r[\"s3_{name}_Dlatency\"] then r[\"s3_{name}_Dlatency\"] else 0.0)"
            for name in s3_comp
        ]) + ")"
    ) if s3_comp else "0.0"
    
    s3_B_sum = (
        "(" + " + ".join([
            f"(if exists r[\"s3_{name}_B\"] then r[\"s3_{name}_B\"] else 0.0)"
            for name in s3_comp
        ]) + ")"
    ) if s3_comp else "0.0"
    
    s3_upload_multiplier = len(s3_comp)
    
    # DynamoDB
    dynamodb_lsuccess = (
        "(" + " + ".join([
            f"(if exists r[\"dynamodb_{name}_Lsuccess\"] then r[\"dynamodb_{name}_Lsuccess\"] else 0.0)"
            for name in dynamodb_comp
        ]) + ")"
    ) if dynamodb_comp else "0.0"
    
    # API
    api_lapi = (
        "(" + " + ".join([
            f"(if exists r[\"api_{name}_LAPI\"] then r[\"api_{name}_LAPI\"] else 0.0)"
            for name in api_comp
        ]) + ")"
    ) if api_comp else "0.0"
    
    # Rekognition
    rekognition_tresponse = (
        "(" + " + ".join([
            f"(if exists r[\"rekognition_{name}_Tresponse\"] then r[\"rekognition_{name}_Tresponse\"] else 0.0)"
            for name in rekognition_comp
        ]) + ")"
    ) if rekognition_comp else "0.0"
    
    # Build complete query
    query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        "  |> map(fn: (r) => ({\n"
        "      r with\n"
        f"      ELcompute: ({lambda_tcpu_malloc}) * (if exists r[\"assumed_P_core_w\"] then r[\"assumed_P_core_w\"] else 95.0) / ((1000.0 * 3600.0 * 1000.0) * 1769.0),\n"
        f"      ELmemory:  ({lambda_mused_texec_tinit}) * (if exists r[\"assumed_P_mem_w\"] then r[\"assumed_P_mem_w\"] else 0.392) / (1024.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        f"      ELstorage: ({lambda_sused_texec_tinit}) * (if exists r[\"assumed_P_storage_w\"] then r[\"assumed_P_storage_w\"] else 0.0012) / (1073741824.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        f"      Enetwork:  ({lambda_dnetwork}) * (if exists r[\"assumed_E_network_kwh_gb\"] then r[\"assumed_E_network_kwh_gb\"] else 0.001) / 1073741824.0,\n"
        f"      ES3active: ({s3_active_sum}) * (if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / (1000.0 * 3600.0 * 1000.0),\n"
        f"      ES3idle:   ((({s3_B_sum}) + ((if exists r[\"assumed_N_inv\"] then r[\"assumed_N_inv\"] else 4.0) * (if exists r[\"assumed_S_upload_mb\"] then r[\"assumed_S_upload_mb\"] else 32666.0) )) / 1073741824.0) * ((if exists r[\"assumed_P_idle_w\"] then r[\"assumed_P_idle_w\"] else 18.5) / ((if exists r[\"assumed_C_mem_gb\"] then r[\"assumed_C_mem_gb\"] else 5120.0) * 1000.0)),\n"
        f"      EDB: ({dynamodb_lsuccess}) * (if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / (1000.0 * 3600.0 * 1000.0),\n"
        f"      EAPI: ({api_lapi}) * (if exists r[\"assumed_P_Proc_w\"] then r[\"assumed_P_Proc_w\"] else 95.0) / (1000.0 * 3600.0 * 1000.0),\n"
        f"      ERekog: ({rekognition_tresponse}) * (if exists r[\"assumed_P_GPU_w\"] then (if r[\"assumed_P_GPU_w\"] > 0.0 then r[\"assumed_P_GPU_w\"] else 70.0) else 70.0) / (1000.0 * 3600.0 * 1000.0),\n"
        "      PUE: (if exists r[\"assumed_PUE\"] then r[\"assumed_PUE\"] else 1.15),\n"
        "      GEF: (if exists r[\"grid_emission_factor\"] then r[\"grid_emission_factor\"] else 541.0)\n"
        "  }))\n"
        "  |> map(fn: (r) => ({ r with _value: (r.ELcompute + r.ELmemory + r.ELstorage + r.Enetwork + r.ES3active + r.ES3idle + r.EDB + r.EAPI + r.ERekog) * r.PUE * r.GEF / 1000.0 }))\n"
        "  \n"
        "  |> keep(columns: [\"_time\", \"_value\"])"
    )
    
    return query

def generate_lambda_panel_query(lambda_comp):
    """Generate query for Lambda Energy panel"""
    lambda_tcpu_malloc = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Tcpu\"] then r[\"lambda_{name}_Tcpu\"] else 0.0) * (if exists r[\"lambda_{name}_Malloc\"] then r[\"lambda_{name}_Malloc\"] else 0.0)"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_mused_texec_tinit = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Mused\"] then r[\"lambda_{name}_Mused\"] else 0.0) * ((if exists r[\"lambda_{name}_Texec\"] then r[\"lambda_{name}_Texec\"] else 0.0) + (if exists r[\"lambda_{name}_Tinit\"] then r[\"lambda_{name}_Tinit\"] else 0.0))"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_sused_texec_tinit = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Sused\"] then r[\"lambda_{name}_Sused\"] else 0.0) * ((if exists r[\"lambda_{name}_Texec\"] then r[\"lambda_{name}_Texec\"] else 0.0) + (if exists r[\"lambda_{name}_Tinit\"] then r[\"lambda_{name}_Tinit\"] else 0.0))"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_dnetwork = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Dnetwork\"] then r[\"lambda_{name}_Dnetwork\"] else 0.0)"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        "  |> map(fn: (r) => ({\n"
        "      r with\n"
        f"      ELcompute: ({lambda_tcpu_malloc}) * (if exists r[\"assumed_P_core_w\"] then r[\"assumed_P_core_w\"] else 95.0) / ((1000.0 * 3600.0 * 1000.0) * 1769.0),\n"
        f"      ELmemory:  ({lambda_mused_texec_tinit}) * (if exists r[\"assumed_P_mem_w\"] then r[\"assumed_P_mem_w\"] else 0.392) / (1024.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        f"      ELstorage: ({lambda_sused_texec_tinit}) * (if exists r[\"assumed_P_storage_w\"] then r[\"assumed_P_storage_w\"] else 0.0012) / (1073741824.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        f"      Enetwork:  ({lambda_dnetwork}) * (if exists r[\"assumed_E_network_kwh_gb\"] then r[\"assumed_E_network_kwh_gb\"] else 0.001) / 1073741824.0\n"
        "  }))\n"
        "  |> map(fn: (r) => ({ r with _value: r.ELcompute + r.ELmemory + r.ELstorage + r.Enetwork }))\n"
        "  \n"
        "  |> keep(columns: [\"_time\", \"_value\"])"
    )
    
    return query

def generate_s3_panel_query(s3_comp):
    """Generate query for S3 Energy panel"""
    s3_active_sum = (
        "(" + " + ".join([
            f"(if exists r[\"s3_{name}_Rtotal\"] then r[\"s3_{name}_Rtotal\"] else 0.0) * (if exists r[\"s3_{name}_Dlatency\"] then r[\"s3_{name}_Dlatency\"] else 0.0)"
            for name in s3_comp
        ]) + ")"
    ) if s3_comp else "0.0"
    
    s3_B_sum = (
        "(" + " + ".join([
            f"(if exists r[\"s3_{name}_B\"] then r[\"s3_{name}_B\"] else 0.0)"
            for name in s3_comp
        ]) + ")"
    ) if s3_comp else "0.0"
    
    query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        "  |> map(fn: (r) => ({\n"
        "      r with\n"
        f"      ES3active: ({s3_active_sum}) * (if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / (1000.0 * 3600.0 * 1000.0),\n"
        f"      ES3idle:   ((({s3_B_sum}) + ((if exists r[\"assumed_N_inv\"] then r[\"assumed_N_inv\"] else 4.0) * (if exists r[\"assumed_S_upload_mb\"] then r[\"assumed_S_upload_mb\"] else 32666.0) )) / 1073741824.0) * ((if exists r[\"assumed_P_idle_w\"] then r[\"assumed_P_idle_w\"] else 18.5) / ((if exists r[\"assumed_C_mem_gb\"] then r[\"assumed_C_mem_gb\"] else 5120.0) * 1000.0))\n"
        "  }))\n"
        "  |> map(fn: (r) => ({ r with _value: r.ES3active + r.ES3idle }))\n"
        "  \n"
        "  |> keep(columns: [\"_time\", \"_value\"])"
    )
    
    return query

def generate_dynamodb_panel_query(dynamodb_comp):
    """Generate query for DynamoDB Energy panel"""
    dynamodb_lsuccess = (
        "(" + " + ".join([
            f"(if exists r[\"dynamodb_{name}_Lsuccess\"] then r[\"dynamodb_{name}_Lsuccess\"] else 0.0)"
            for name in dynamodb_comp
        ]) + ")"
    ) if dynamodb_comp else "0.0"
    
    query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        "  |> map(fn: (r) => ({\n"
        "      r with\n"
        f"      EDB: ({dynamodb_lsuccess}) * (if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / (1000.0 * 3600.0 * 1000.0)\n"
        "  }))\n"
        "  |> map(fn: (r) => ({ r with _value: r.EDB }))\n"
        "  \n"
        "  |> keep(columns: [\"_time\", \"_value\"])"
    )
    
    return query

def generate_api_panel_query(api_comp):
    """Generate query for API Gateway Energy panel"""
    api_lapi = (
        "(" + " + ".join([
            f"(if exists r[\"api_{name}_LAPI\"] then r[\"api_{name}_LAPI\"] else 0.0)"
            for name in api_comp
        ]) + ")"
    ) if api_comp else "0.0"
    
    query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        "  |> map(fn: (r) => ({\n"
        "      r with\n"
        f"      EAPI: ({api_lapi}) * (if exists r[\"assumed_P_Proc_w\"] then r[\"assumed_P_Proc_w\"] else 95.0) / (1000.0 * 3600.0 * 1000.0)\n"
        "  }))\n"
        "  |> map(fn: (r) => ({ r with _value: r.EAPI }))\n"
        "  \n"
        "  |> keep(columns: [\"_time\", \"_value\"])"
    )
    
    return query

def generate_rekognition_panel_query(rekognition_comp):
    """Generate query for Rekognition Energy panel"""
    rekognition_tresponse = (
        "(" + " + ".join([
            f"(if exists r[\"rekognition_{name}_Tresponse\"] then r[\"rekognition_{name}_Tresponse\"] else 0.0)"
            for name in rekognition_comp
        ]) + ")"
    ) if rekognition_comp else "0.0"
    
    query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        "  |> map(fn: (r) => ({\n"
        "      r with\n"
        f"      ERekog: ({rekognition_tresponse}) * (if exists r[\"assumed_P_GPU_w\"] then (if r[\"assumed_P_GPU_w\"] > 0.0 then r[\"assumed_P_GPU_w\"] else 70.0) else 70.0) / (1000.0 * 3600.0 * 1000.0)\n"
        "  }))\n"
        "  |> map(fn: (r) => ({ r with _value: r.ERekog }))\n"
        "  \n"
        "  |> keep(columns: [\"_time\", \"_value\"])"
    )
    
    return query

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def generate_and_update_dashboard():
    """Load, update, and save dashboard.json with dynamic components"""
    
    lambda_comp = list(METRIC_FILES.get("Lambda", {}).keys())
    s3_comp = list(METRIC_FILES.get("S3", {}).keys())
    dynamodb_comp = list(METRIC_FILES.get("DynamoDB", {}).keys())
    api_comp = list(METRIC_FILES.get("API", {}).keys())
    rekognition_comp = list(METRIC_FILES.get("Rekognition", {}).keys())
    
    print("Discovered Components:")
    print(f"  Lambda: {lambda_comp}")
    print(f"  S3: {s3_comp}")
    print(f"  DynamoDB: {dynamodb_comp}")
    print(f"  API: {api_comp}")
    print(f"  Rekognition: {rekognition_comp}")
    print()
    
    # Load existing dashboard
    dashboard_path = Path("grafana-dashboards/dashboard.json")
    with open(dashboard_path, "r") as f:
        dashboard = json.load(f)
    
    # Generate new queries
    combined_query = generate_combined_energy_query(lambda_comp, s3_comp, dynamodb_comp, api_comp, rekognition_comp)
    lambda_query = generate_lambda_panel_query(lambda_comp)
    s3_query = generate_s3_panel_query(s3_comp)
    dynamodb_query = generate_dynamodb_panel_query(dynamodb_comp)
    api_query = generate_api_panel_query(api_comp)
    rekognition_query = generate_rekognition_panel_query(rekognition_comp)
    
    # Generate component sums for breakdown query
    lambda_tcpu_malloc = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Tcpu\"] then r[\"lambda_{name}_Tcpu\"] else 0.0) * (if exists r[\"lambda_{name}_Malloc\"] then r[\"lambda_{name}_Malloc\"] else 0.0)"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_mused_texec_tinit = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Mused\"] then r[\"lambda_{name}_Mused\"] else 0.0) * ((if exists r[\"lambda_{name}_Texec\"] then r[\"lambda_{name}_Texec\"] else 0.0) + (if exists r[\"lambda_{name}_Tinit\"] then r[\"lambda_{name}_Tinit\"] else 0.0))"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_sused_texec_tinit = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Sused\"] then r[\"lambda_{name}_Sused\"] else 0.0) * ((if exists r[\"lambda_{name}_Texec\"] then r[\"lambda_{name}_Texec\"] else 0.0) + (if exists r[\"lambda_{name}_Tinit\"] then r[\"lambda_{name}_Tinit\"] else 0.0))"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    lambda_dnetwork = (
        "(" + " + ".join([
            f"(if exists r[\"lambda_{name}_Dnetwork\"] then r[\"lambda_{name}_Dnetwork\"] else 0.0)"
            for name in lambda_comp
        ]) + ")"
    ) if lambda_comp else "0.0"
    
    s3_active_sum = (
        "(" + " + ".join([
            f"(if exists r[\"s3_{name}_Rtotal\"] then r[\"s3_{name}_Rtotal\"] else 0.0) * (if exists r[\"s3_{name}_Dlatency\"] then r[\"s3_{name}_Dlatency\"] else 0.0)"
            for name in s3_comp
        ]) + ")"
    ) if s3_comp else "0.0"
    
    s3_B_sum = (
        "(" + " + ".join([
            f"(if exists r[\"s3_{name}_B\"] then r[\"s3_{name}_B\"] else 0.0)"
            for name in s3_comp
        ]) + ")"
    ) if s3_comp else "0.0"
    
    dynamodb_lsuccess = (
        "(" + " + ".join([
            f"(if exists r[\"dynamodb_{name}_Lsuccess\"] then r[\"dynamodb_{name}_Lsuccess\"] else 0.0)"
            for name in dynamodb_comp
        ]) + ")"
    ) if dynamodb_comp else "0.0"
    
    api_lapi = (
        "(" + " + ".join([
            f"(if exists r[\"api_{name}_LAPI\"] then r[\"api_{name}_LAPI\"] else 0.0)"
            for name in api_comp
        ]) + ")"
    ) if api_comp else "0.0"
    
    rekognition_tresponse = (
        "(" + " + ".join([
            f"(if exists r[\"rekognition_{name}_Tresponse\"] then r[\"rekognition_{name}_Tresponse\"] else 0.0)"
            for name in rekognition_comp
        ]) + ")"
    ) if rekognition_comp else "0.0"
    
    # Update panel queries by title
    query_map = {
        "Lambda Energy": lambda_query,
        "S3 Energy": s3_query,
        "DynamoDB Energy": dynamodb_query,
        "API Gateway Energy": api_query,
        "Rekognition Energy": rekognition_query,
        "Total SCI": combined_query,
        "Software Carbon Intensity (SCI)": combined_query,
    }
    
    # Generate special query for Total Energy Breakdown that returns each component as a separate value
    breakdown_query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        "  |> map(fn: (r) => ({\n"
        "      r with\n"
        f"      ELcompute: ({lambda_tcpu_malloc}) * (if exists r[\"assumed_P_core_w\"] then r[\"assumed_P_core_w\"] else 95.0) / ((1000.0 * 3600.0 * 1000.0) * 1769.0),\n"
        f"      ELmemory:  ({lambda_mused_texec_tinit}) * (if exists r[\"assumed_P_mem_w\"] then r[\"assumed_P_mem_w\"] else 0.392) / (1024.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        f"      ELstorage: ({lambda_sused_texec_tinit}) * (if exists r[\"assumed_P_storage_w\"] then r[\"assumed_P_storage_w\"] else 0.0012) / (1073741824.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        f"      Enetwork:  ({lambda_dnetwork}) * (if exists r[\"assumed_E_network_kwh_gb\"] then r[\"assumed_E_network_kwh_gb\"] else 0.001) / 1073741824.0,\n"
        f"      ES3active: ({s3_active_sum}) * (if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / (1000.0 * 3600.0 * 1000.0),\n"
        f"      ES3idle:   ((({s3_B_sum}) + ((if exists r[\"assumed_N_inv\"] then r[\"assumed_N_inv\"] else 4.0) * (if exists r[\"assumed_S_upload_mb\"] then r[\"assumed_S_upload_mb\"] else 32666.0) )) / 1073741824.0) * ((if exists r[\"assumed_P_idle_w\"] then r[\"assumed_P_idle_w\"] else 18.5) / ((if exists r[\"assumed_C_mem_gb\"] then r[\"assumed_C_mem_gb\"] else 5120.0) * 1000.0)),\n"
        f"      EDB: ({dynamodb_lsuccess}) * (if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / (1000.0 * 3600.0 * 1000.0),\n"
        f"      EAPI: ({api_lapi}) * (if exists r[\"assumed_P_Proc_w\"] then r[\"assumed_P_Proc_w\"] else 95.0) / (1000.0 * 3600.0 * 1000.0),\n"
        f"      ERekog: ({rekognition_tresponse}) * (if exists r[\"assumed_P_GPU_w\"] then (if r[\"assumed_P_GPU_w\"] > 0.0 then r[\"assumed_P_GPU_w\"] else 70.0) else 70.0) / (1000.0 * 3600.0 * 1000.0)\n"
        "  }))\n"
        "  |> map(fn: (r) => ({ r with Lambda_Compute: r.ELcompute, Lambda_Memory: r.ELmemory, Lambda_Storage: r.ELstorage, Lambda_Network: r.Enetwork, S3_Active: r.ES3active, S3_Idle: r.ES3idle, DynamoDB: r.EDB, API: r.EAPI, Rekognition: r.ERekog }))\n"
        "  |> keep(columns: [\"_time\", \"Lambda_Compute\", \"Lambda_Memory\", \"Lambda_Storage\", \"Lambda_Network\", \"S3_Active\", \"S3_Idle\", \"DynamoDB\", \"API\", \"Rekognition\"])\n"
    )
    
    query_map["Total Energy Breakdown (kWh)"] = breakdown_query
    
    updated_count = 0
    for panel in dashboard.get("panels", []):
        panel_title = panel.get("title", "")
        if panel_title in query_map:
            # Update all targets with the new query
            for target in panel.get("targets", []):
                target["query"] = query_map[panel_title]
            updated_count += 1
            print(f"✓ Updated panel: {panel_title}")
    
    print(f"\nUpdated {updated_count} panels")
    
    # Save updated dashboard
    with open(dashboard_path, "w") as f:
        json.dump(dashboard, f, indent=2)
    
    print(f"\nDashboard saved to {dashboard_path}")
    print(f"Dashboard version: {dashboard.get('version', 'unknown')}")
    
    return dashboard

if __name__ == "__main__":
    generate_and_update_dashboard()

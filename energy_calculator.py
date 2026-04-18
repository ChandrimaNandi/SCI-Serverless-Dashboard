#!/usr/bin/env python3
"""
Energy Calculator for Serverless Application
Cross-checks energy calculations against Grafana dashboard values
Does NOT insert data into InfluxDB or Grafana
"""

import pandas as pd
import os
from pathlib import Path
from typing import Dict, List, Tuple

# ============================================================================
# CONSTANTS & PARAMETERS
# ============================================================================
# These values MUST match ASSUMED_VALUES in simulator.py

# Lambda Compute Constants
PCORE = 95.0  # watts (power per CPU core)
MREF = 1769.0  # MB (reference memory for 1 vCPU)

# Lambda Memory Constants
PMEM = 0.392  # watts per GB (DRAM power rating)

# Lambda Storage Constants
PSTORAGE = 0.0012  # watts per GB (NVMe SSD power rating)

# Lambda Network Constants
ENETWORK_INTENSITY = 0.001  # kWh/GB (network energy intensity)

# S3 Constants
S3_PACTIVE = 18.5  # watts (active power consumption per request)
S3_PIDLE = 18.5  # watts (idle power consumption)
S3_CMEM = 5120.0  # GB (storage capacity)

# DynamoDB Constants
DYNAMODB_PACTIVE = 18.5  # watts (active power consumption)

# API Gateway Constants
API_PPROC = 95.0  # watts (processor power rating)

# Rekognition Constants
REKOGNITION_PGPU = 70.0  # watts (GPU power consumption)

# Assumed Parameters (not from Excel)
N_INV = 4  # number of invocations
S_UPLOAD = 32666  # MB (average upload size)

# Global Constants
PUE = 1.15  # Power Usage Effectiveness
GRID_EMISSION_FACTOR = 541.0  # gCO2/kWh (default, can vary by region)

# ============================================================================
# LAMBDA ENERGY CALCULATIONS
# ============================================================================

class LambdaEnergyCalculator:
    """Calculates individual components of Lambda energy consumption"""
    
    def __init__(self, data: Dict):
        """
        Initialize with Lambda metrics
        Expected keys: execution_time_ms, allocated_memory_mb, max_memory_used_mb,
                      init_duration_ms, storage_used_bytes, data_transferred_bytes
        """
        self.data = data
    
    def compute_energy(self) -> float:
        """
        Calculate Lambda Compute Energy
        ELcompute = (Tcpu × Pcore × Malloc) / (1000 × 3600 × 1000 × Mref)
        """
        tcpu = self.data.get('tcpu', self.data.get('execution_time_ms', 0.0))
        malloc = self.data.get('malloc', self.data.get('allocated_memory_mb', 0.0))
        
        if tcpu == 0 or malloc == 0:
            return 0.0
        
        energy = (tcpu * PCORE * malloc) / (1000.0 * 3600.0 * 1000.0 * MREF)
        return energy
    
    def memory_energy(self) -> float:
        """
        Calculate Lambda Memory Energy
        ELmemory = (Mused × Pmem × (Texec + Tinit)) / (1024 × 1000 × 1000 × 3600)
        """
        mused = self.data.get('mused', self.data.get('max_memory_used_mb', 0.0))
        texec = self.data.get('texec', self.data.get('execution_time_ms', 0.0))
        tinit = self.data.get('tinit', self.data.get('init_duration_ms', 0.0))
        
        if mused == 0 or (texec + tinit) == 0:
            return 0.0
        
        energy = (mused * PMEM * (texec + tinit)) / (1024.0* 1000.0 * 1000.0 * 3600.0)
        return energy
    
    def storage_energy(self) -> float:
        """
        Calculate Lambda Storage Energy (ephemeral storage)
        ELstorage = (Sused × Pstorage × (Texec + Tinit)) / (1024³ × 1000 × 1000 × 3600)
        """
        sused = self.data.get('sused', self.data.get('storage_used_bytes', 0.0))
        texec = self.data.get('texec', self.data.get('execution_time_ms', 0.0))
        tinit = self.data.get('tinit', self.data.get('init_duration_ms', 0.0))
        
        if sused == 0 or (texec + tinit) == 0:
            return 0.0
        
        energy = (sused * PSTORAGE * (texec + tinit)) / (1024.0 ** 3 * 1000.0 * 1000.0 * 3600.0)
        return energy
    
    def network_energy(self) -> float:
        """
        Calculate Lambda Network Energy
        Enetwork = (Dnetwork × εnetwork) / 1024³
        """
        dnetwork = self.data.get('dnetwork', self.data.get('data_transferred_bytes', 0.0))
        
        if dnetwork == 0:
            return 0.0
        
        energy = (dnetwork * ENETWORK_INTENSITY) / (1024.0 ** 3)
        return energy
    
    def total_energy(self) -> float:
        """Calculate total Lambda energy"""
        return self.compute_energy() + self.memory_energy() + self.storage_energy() + self.network_energy()
    
    def breakdown(self) -> Dict[str, float]:
        """Return energy breakdown"""
        return {
            'compute': self.compute_energy(),
            'memory': self.memory_energy(),
            'storage': self.storage_energy(),
            'network': self.network_energy(),
            'total': self.total_energy()
        }


class S3EnergyCalculator:
    """Calculates S3 energy consumption"""
    
    def __init__(self, data: Dict):
        """
        Initialize with S3 metrics
        Expected keys: total_requests, total_latency_ms, bucket_size_bytes,
                      num_invocations, avg_upload_size_bytes
        """
        self.data = data
    
    def active_energy(self) -> float:
        """
        Calculate S3 Active Energy
        ES3active = (Rtotal × Dlatency × Pactive) / (1000 × 3600 × 1000)
        """
        rtotal = self.data.get('rtotal', self.data.get('total_requests', 0.0))
        dlatency = self.data.get('dlatency', self.data.get('total_latency_ms', 0.0))
        
        if rtotal == 0 or dlatency == 0:
            return 0.0
        
        energy = (rtotal * dlatency * S3_PACTIVE) / (1000.0 * 3600.0 * 1000.0)
        return energy
    
    def idle_energy(self) -> float:
        """
        Calculate S3 Idle Energy
        ES3idle = ((B + (Ninv × Supload)) / 1024³) × (Pidle / (Cmem × 1000)) × 1
        """
        b = self.data.get('b', self.data.get('bucket_size_bytes', 0.0))
        # Use assumed parameters instead of Excel values
        ninv = N_INV
        supload_bytes = S_UPLOAD # Convert MB to bytes
        
        total_data = (b + (ninv * supload_bytes)) / (1024.0 ** 3)  # Convert to GB
        
        if total_data == 0:
            return 0.0
        
        energy = total_data * (S3_PIDLE / (S3_CMEM * 1000.0)) * 1.0
        return energy
    
    def total_energy(self) -> float:
        """Calculate total S3 energy"""
        return self.active_energy() + self.idle_energy()
    
    def breakdown(self) -> Dict[str, float]:
        """Return energy breakdown"""
        return {
            'active': self.active_energy(),
            'idle': self.idle_energy(),
            'total': self.total_energy()
        }


class DynamoDBEnergyCalculator:
    """Calculates DynamoDB energy consumption"""
    
    def __init__(self, data: Dict):
        """
        Initialize with DynamoDB metrics
        Expected keys: latency_success_ms
        """
        self.data = data
    
    def active_energy(self) -> float:
        """
        Calculate DynamoDB Active Energy
        EDB = (Lsuccess × Pactive) / (1000 × 3600 × 1000)
        """
        lsuccess = self.data.get('lsuccess', self.data.get('latency_success_ms', 0.0))
        
        if lsuccess == 0:
            return 0.0
        
        energy = (lsuccess * DYNAMODB_PACTIVE) / (1000.0 * 3600.0 * 1000.0)
        return energy
    
    def total_energy(self) -> float:
        """Calculate total DynamoDB energy"""
        return self.active_energy()


class APIGatewayEnergyCalculator:
    """Calculates API Gateway energy consumption"""
    
    def __init__(self, data: Dict):
        """
        Initialize with API Gateway metrics
        Expected keys: latency_ms
        """
        self.data = data
    
    def energy(self) -> float:
        """
        Calculate API Gateway Energy
        EAPI = (LAPI × PProc) / (1000 × 3600 × 1000)
        """
        lapi = self.data.get('lapi', self.data.get('latency_ms', 0.0))
        
        if lapi == 0:
            return 0.0
        
        energy = (lapi * API_PPROC) / (1000.0 * 3600.0 * 1000.0)
        return energy


class RekognitionEnergyCalculator:
    """Calculates Rekognition energy consumption"""
    
    def __init__(self, data: Dict):
        """
        Initialize with Rekognition metrics
        Expected keys: response_time_ms
        """
        self.data = data
    
    def energy(self) -> float:
        """
        Calculate Rekognition Energy
        ERekog = (Tresponse × PGPU) / (1000 × 3600 × 1000)
        """
        tresponse = self.data.get('tresponse', self.data.get('response_time_ms', 0.0))
        
        if tresponse == 0:
            return 0.0
        
        energy = (tresponse * REKOGNITION_PGPU) / (1000.0 * 3600.0 * 1000.0)
        return energy


# ============================================================================
# DATA LOADER
# ============================================================================

class DataLoader:
    """Loads data from Excel files"""
    
    def __init__(self, base_path: str = "Final Serverless Metrics"):
        self.base_path = Path(base_path)
    
    def load_lambda_data(self) -> Dict[str, Dict]:
        """Load all Lambda function data"""
        lambda_path = self.base_path / "Lambda"
        lambda_data = {}
        
        if not lambda_path.exists():
            print(f"Warning: Lambda path not found: {lambda_path}")
            return lambda_data
        
        for excel_file in lambda_path.glob("*.xlsx"):
            func_name = excel_file.stem
            try:
                df = pd.read_excel(excel_file, header=None)
                # Excel format: Column 0 = parameter names, Column 1 = values
                metrics = {}
                for idx, row in df.iterrows():
                    param_name = str(row[0]).lower()  # Parameter name
                    value = row[1]  # Value
                    metrics[param_name] = float(value) if pd.notna(value) else 0.0
                
                if metrics:
                    lambda_data[func_name] = metrics
                    print(f"✓ Loaded Lambda: {func_name}")
            except Exception as e:
                print(f"✗ Error loading {func_name}: {e}")
        
        return lambda_data
    
    def load_s3_data(self) -> Dict[str, Dict]:
        """Load all S3 bucket data"""
        s3_path = self.base_path / "S3"
        s3_data = {}
        
        if not s3_path.exists():
            print(f"Warning: S3 path not found: {s3_path}")
            return s3_data
        
        for excel_file in s3_path.glob("*.xlsx"):
            bucket_name = excel_file.stem
            try:
                df = pd.read_excel(excel_file, header=None)
                # Excel format: Column 0 = parameter names, Column 1 = values
                metrics = {}
                for idx, row in df.iterrows():
                    param_name = str(row[0]).lower()  # Parameter name
                    value = row[1]  # Value
                    metrics[param_name] = float(value) if pd.notna(value) else 0.0
                
                if metrics:
                    s3_data[bucket_name] = metrics
                    print(f"✓ Loaded S3: {bucket_name}")
            except Exception as e:
                print(f"✗ Error loading {bucket_name}: {e}")
        
        return s3_data
    
    def load_dynamodb_data(self) -> Dict[str, Dict]:
        """Load all DynamoDB table data"""
        db_path = self.base_path / "DynamoDB"
        db_data = {}
        
        if not db_path.exists():
            print(f"Warning: DynamoDB path not found: {db_path}")
            return db_data
        
        for excel_file in db_path.glob("*.xlsx"):
            table_name = excel_file.stem
            try:
                df = pd.read_excel(excel_file, header=None)
                # Excel format: Column 0 = parameter names, Column 1 = values
                metrics = {}
                for idx, row in df.iterrows():
                    param_name = str(row[0]).lower()  # Parameter name
                    value = row[1]  # Value
                    metrics[param_name] = float(value) if pd.notna(value) else 0.0
                
                if metrics:
                    db_data[table_name] = metrics
                    print(f"✓ Loaded DynamoDB: {table_name}")
            except Exception as e:
                print(f"✗ Error loading {table_name}: {e}")
        
        return db_data
    
    def load_api_data(self) -> Dict:
        """Load API Gateway data"""
        api_path = self.base_path / "API Gateway" / "API.xlsx"
        
        if not api_path.exists():
            print(f"Warning: API Gateway path not found: {api_path}")
            return {}
        
        try:
            df = pd.read_excel(api_path, header=None)
            # Excel format: Column 0 = parameter names, Column 1 = values
            metrics = {}
            for idx, row in df.iterrows():
                param_name = str(row[0]).lower()  # Parameter name
                value = row[1]  # Value
                metrics[param_name] = float(value) if pd.notna(value) else 0.0
            
            if metrics:
                print(f"✓ Loaded API Gateway")
                return metrics
        except Exception as e:
            print(f"✗ Error loading API Gateway: {e}")
        
        return {}
    
    def load_rekognition_data(self) -> Dict:
        """Load Rekognition data"""
        rekog_path = self.base_path / "Rekognition" / "Rekognition.xlsx"
        
        if not rekog_path.exists():
            print(f"Warning: Rekognition path not found: {rekog_path}")
            return {}
        
        try:
            df = pd.read_excel(rekog_path, header=None)
            # Excel format: Column 0 = parameter names, Column 1 = values
            metrics = {}
            for idx, row in df.iterrows():
                param_name = str(row[0]).lower()  # Parameter name
                value = row[1]  # Value
                metrics[param_name] = float(value) if pd.notna(value) else 0.0
            
            if metrics:
                print(f"✓ Loaded Rekognition")
                return metrics
        except Exception as e:
            print(f"✗ Error loading Rekognition: {e}")
        
        return {}


# ============================================================================
# REPORT GENERATOR
# ============================================================================

class EnergyReport:
    """Generates and displays energy calculations"""
    
    def __init__(self):
        self.lambda_energy = {}
        self.s3_energy = {}
        self.dynamodb_energy = {}
        self.api_energy = 0.0
        self.rekognition_energy = 0.0
    
    def calculate_all(self, loader: DataLoader):
        """Calculate energy for all components"""
        print("\n" + "="*80)
        print("CALCULATING LAMBDA ENERGY")
        print("="*80)
        lambda_data = loader.load_lambda_data()
        for func_name, metrics in lambda_data.items():
            try:
                calc = LambdaEnergyCalculator(metrics)
                breakdown = calc.breakdown()
                self.lambda_energy[func_name] = breakdown
                self._print_lambda_breakdown(func_name, breakdown)
            except Exception as e:
                print(f"✗ Error calculating {func_name}: {e}")
        
        print("\n" + "="*80)
        print("CALCULATING S3 ENERGY")
        print("="*80)
        s3_data = loader.load_s3_data()
        for bucket_name, metrics in s3_data.items():
            try:
                calc = S3EnergyCalculator(metrics)
                breakdown = calc.breakdown()
                self.s3_energy[bucket_name] = breakdown
                self._print_s3_breakdown(bucket_name, breakdown)
            except Exception as e:
                print(f"✗ Error calculating {bucket_name}: {e}")
        
        print("\n" + "="*80)
        print("CALCULATING DYNAMODB ENERGY")
        print("="*80)
        db_data = loader.load_dynamodb_data()
        for table_name, metrics in db_data.items():
            try:
                calc = DynamoDBEnergyCalculator(metrics)
                energy = calc.total_energy()
                self.dynamodb_energy[table_name] = energy
                self._print_dynamodb_energy(table_name, energy)
            except Exception as e:
                print(f"✗ Error calculating {table_name}: {e}")
        
        print("\n" + "="*80)
        print("CALCULATING API GATEWAY ENERGY")
        print("="*80)
        api_data = loader.load_api_data()
        if api_data:
            try:
                calc = APIGatewayEnergyCalculator(api_data)
                self.api_energy = calc.energy()
                self._print_api_energy(self.api_energy)
            except Exception as e:
                print(f"✗ Error calculating API Gateway: {e}")
        
        print("\n" + "="*80)
        print("CALCULATING REKOGNITION ENERGY")
        print("="*80)
        rekog_data = loader.load_rekognition_data()
        if rekog_data:
            try:
                calc = RekognitionEnergyCalculator(rekog_data)
                self.rekognition_energy = calc.energy()
                self._print_rekognition_energy(self.rekognition_energy)
            except Exception as e:
                print(f"✗ Error calculating Rekognition: {e}")
    
    def _print_lambda_breakdown(self, func_name: str, breakdown: Dict[str, float]):
        """Print Lambda energy breakdown"""
        print(f"\n{func_name}:")
        print(f"  Compute Energy:   {breakdown['compute']:.2e} kWh")
        print(f"  Memory Energy:    {breakdown['memory']:.2e} kWh")
        print(f"  Storage Energy:   {breakdown['storage']:.2e} kWh")
        print(f"  Network Energy:   {breakdown['network']:.2e} kWh")
        print(f"  ─────────────────────────────────")
        print(f"  TOTAL:            {breakdown['total']:.2e} kWh")
    
    def _print_s3_breakdown(self, bucket_name: str, breakdown: Dict[str, float]):
        """Print S3 energy breakdown"""
        print(f"\n{bucket_name}:")
        print(f"  Active Energy:    {breakdown['active']:.2e} kWh")
        print(f"  Idle Energy:      {breakdown['idle']:.2e} kWh")
        print(f"  ─────────────────────────────────")
        print(f"  TOTAL:            {breakdown['total']:.2e} kWh")
    
    def _print_dynamodb_energy(self, table_name: str, energy: float):
        """Print DynamoDB energy"""
        print(f"\n{table_name}: {energy:.2e} kWh")
    
    def _print_api_energy(self, energy: float):
        """Print API Gateway energy"""
        print(f"\nAPI Gateway: {energy:.2e} kWh")
    
    def _print_rekognition_energy(self, energy: float):
        """Print Rekognition energy"""
        print(f"\nRekognition: {energy:.2e} kWh")
    
    def print_summary(self):
        """Print final summary"""
        print("\n" + "="*80)
        print("SUMMARY - TOTAL ENERGY BY COMPONENT")
        print("="*80)
        
        # Lambda Total
        lambda_total = sum(energy['total'] for energy in self.lambda_energy.values())
        print(f"\nLambda Functions:     {lambda_total:.2e} kWh")
        for func_name, energy in self.lambda_energy.items():
            print(f"  - {func_name}: {energy['total']:.2e} kWh")
        
        # S3 Total
        s3_total = sum(energy['total'] for energy in self.s3_energy.values())
        print(f"\nS3 Buckets:           {s3_total:.2e} kWh")
        for bucket_name, energy in self.s3_energy.items():
            print(f"  - {bucket_name}: {energy['total']:.2e} kWh")
        
        # DynamoDB Total
        db_total = sum(self.dynamodb_energy.values())
        print(f"\nDynamoDB Tables:      {db_total:.2e} kWh")
        for table_name, energy in self.dynamodb_energy.items():
            print(f"  - {table_name}: {energy:.2e} kWh")
        
        # API Gateway
        print(f"\nAPI Gateway:          {self.api_energy:.2e} kWh")
        
        # Rekognition
        print(f"\nRekognition:          {self.rekognition_energy:.2e} kWh")
        
        # Grand Total
        grand_total = lambda_total + s3_total + db_total + self.api_energy + self.rekognition_energy
        print("\n" + "="*80)
        print(f"TOTAL ENERGY:         {grand_total:.2e} kWh")
        print("="*80)
        
        # SCI Calculation
        sci = grand_total * PUE * GRID_EMISSION_FACTOR
        print(f"\nSoftware Carbon Intensity (SCI):")
        print(f"  Total Energy (kWh):   {grand_total:.2e}")
        print(f"  PUE:                  {PUE}")
        print(f"  Grid Emission Factor: {GRID_EMISSION_FACTOR} gCO2/kWh")
        print(f"  ─────────────────────────────────")
        print(f"  SCI:                  {sci:.2e} gCO2e")
        print("="*80)
        
        return {
            'lambda_total': lambda_total,
            's3_total': s3_total,
            'dynamodb_total': db_total,
            'api_total': self.api_energy,
            'rekognition_total': self.rekognition_energy,
            'total_energy': grand_total,
            'sci': sci
        }


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*80)
    print("SERVERLESS ENERGY CALCULATOR")
    print("Cross-check tool for Grafana Dashboard")
    print("="*80)
    
    # Create loader and report
    loader = DataLoader("Final Serverless Metrics")
    report = EnergyReport()
    
    # Calculate all energies
    report.calculate_all(loader)
    
    # Print summary
    summary = report.print_summary()
    
    # Save to file
    save_report(summary)


def save_report(summary: Dict) -> None:
    """Save summary to text file"""
    output_file = "energy_calculation_results.txt"
    with open(output_file, 'w') as f:
        f.write("="*80 + "\n")
        f.write("ENERGY CALCULATION RESULTS - CROSS CHECK\n")
        f.write("="*80 + "\n\n")
        
        f.write("Component Breakdown:\n")
        f.write(f"  Lambda Total:        {summary['lambda_total']:.2e} kWh\n")
        f.write(f"  S3 Total:            {summary['s3_total']:.2e} kWh\n")
        f.write(f"  DynamoDB Total:      {summary['dynamodb_total']:.2e} kWh\n")
        f.write(f"  API Gateway Total:   {summary['api_total']:.2e} kWh\n")
        f.write(f"  Rekognition Total:   {summary['rekognition_total']:.2e} kWh\n\n")
        
        f.write(f"TOTAL ENERGY:         {summary['total_energy']:.2e} kWh\n")
        f.write(f"SCI:                  {summary['sci']:.2e} gCO2e\n")
        f.write("="*80 + "\n")
    
    print(f"\n✓ Results saved to {output_file}")


if __name__ == "__main__":
    main()

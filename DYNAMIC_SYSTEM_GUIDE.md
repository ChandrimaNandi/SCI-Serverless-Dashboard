# Dynamic Serverless Energy Dashboard System

## Overview

This system automatically discovers serverless components (Lambda functions, S3 buckets, DynamoDB tables, API endpoints, Rekognition services) from Excel files and generates dynamic Grafana dashboard queries.

## Architecture

```
Final Serverless Metrics/
├── Lambda/
│   ├── DoorbellLambda.xlsx
│   ├── FaceRecognitionLambda.xlsx
│   ├── FetchWebsiteFromS3.xlsx
│   ├── PINVerificationLambda.xlsx
│   └── UploadLambda.xlsx
├── S3/
│   ├── mhm-home-security-img.xlsx
│   └── mhm-home-security-ui.xlsx
├── DynamoDB/
│   ├── Events.xlsx
│   └── Users.xlsx
├── API Gateway/
│   └── API.xlsx
└── Rekognition/
    └── Rekognition.xlsx
```

## Components

### 1. simulator.py (Dynamic Discovery)
- **Purpose**: Read Excel metrics files and write to InfluxDB
- **Dynamic Feature**: Automatically discovers all `.xlsx` files in each category folder
- **How to add new components**: Simply add a new Excel file to the appropriate folder:
  - Lambda functions: `Final Serverless Metrics/Lambda/[FunctionName].xlsx`
  - S3 buckets: `Final Serverless Metrics/S3/[BucketName].xlsx`
  - DynamoDB tables: `Final Serverless Metrics/DynamoDB/[TableName].xlsx`
  - API endpoints: `Final Serverless Metrics/API Gateway/[APIName].xlsx`
  - Rekognition services: `Final Serverless Metrics/Rekognition/[ServiceName].xlsx`

### 2. generate_dashboard_complete.py (Dashboard Generation)
- **Purpose**: Generate `dashboard.json` based on discovered components
- **Input**: Reads from `METRIC_FILES` discovered by `simulator.py`
- **Output**: Updates `grafana-dashboards/dashboard.json` with dynamic queries

### 3. generate_dashboard.py (Query Preview)
- **Purpose**: Preview generated Flux queries without modifying dashboard
- **Useful for**: Testing queries before applying changes

## Usage Workflow

### Step 1: Add New Component
Add a new Excel file to the appropriate folder:
```bash
# Example: Add a new Lambda function
cp NewLambdaFunction.xlsx Final Serverless Metrics/Lambda/

# Example: Add a new S3 bucket
cp NewBucket.xlsx Final Serverless Metrics/S3/
```

### Step 2: Run Simulator
The simulator automatically discovers new files:
```bash
python3 simulator.py
```

### Step 3: Regenerate Dashboard (When Adding/Removing Components)
After adding or removing component files, regenerate the dashboard:
```bash
python3 generate_dashboard_complete.py
```

### Step 4: Restart Grafana (If Needed)
If the dashboard doesn't auto-refresh:
1. Reload Grafana dashboard in browser (Ctrl+Shift+R)
2. Or restart Grafana container if using Docker

## Excel File Format

Each Excel file must follow this format:

| Column A | Column B |
|----------|----------|
| Metric Name (lowercase) | Value |
| metric1 | value1 |
| metric2 | value2 |

### Lambda Metrics
- `tinit`: Initialization time (ms)
- `mused`: Memory used (MB)
- `dnetwork`: Data network transfer (bytes)
- `tcpu`: CPU time (ms)
- `malloc`: Allocated memory (MB)
- `sused`: Storage used (bytes)
- `texec`: Execution time (ms)

### S3 Metrics
- `dlatency`: Data latency (ms)
- `rtotal`: Request total count
- `b`: Storage size (bytes)

### DynamoDB Metrics
- `lsuccess`: Successful requests count

### API Gateway Metrics
- `lapi`: API latency (ms)

### Rekognition Metrics
- `tresponse`: Response time (ms)

## Field Naming Convention

Discovered components are automatically named using this convention in InfluxDB:

```
{category}_{component_name}_{metric}
```

Examples:
- `lambda_DoorbellLambda_Tcpu`
- `s3_mhm-home-security-img_B`
- `dynamodb_Events_Lsuccess`
- `api_API_LAPI`
- `rekognition_Rekognition_Tresponse`

## Energy Formulas

The Flux queries implement the following energy calculations:

### Lambda Compute Energy
```
ELcompute = (Tcpu × Malloc × P_core) / (1000 × 3600 × 1000 × Mref)
```

### Lambda Memory Energy
```
ELmemory = (Mused × P_mem × (Texec + Tinit)) / (1024 × 1000 × 3600 × 1000)
```

### Lambda Storage Energy
```
ELstorage = (Sused × P_storage × (Texec + Tinit)) / (1024³ × 1000 × 3600 × 1000)
```

### Lambda Network Energy
```
Enetwork = (Dnetwork × E_network_intensity) / 1024³
```

### S3 Active Energy
```
ES3active = Σ(Rtotal_i × Dlatency_i) × P_active / (1000 × 3600 × 1000)
```

### S3 Idle Energy
```
ES3idle = ((ΣB_i + N_inv × S_upload) / 1024³) × (P_idle / (C_mem × 1000))
```

### DynamoDB Energy
```
EDB = ΣLsuccess_i × P_active / (1000 × 3600 × 1000)
```

### API Gateway Energy
```
EAPI = ΣLAPI_i × P_proc / (1000 × 3600 × 1000)
```

### Rekognition Energy
```
ERekog = ΣTresponse_i × P_GPU / (1000 × 3600 × 1000)
```

## Assumed Parameters

Default values (defined in `ASSUMED_VALUES` in `simulator.py`):

```python
P_core_w = 95.0          # watts (CPU power)
P_mem_w = 0.392          # watts per GB (memory power)
P_storage_w = 0.0012     # watts per GB (storage power)
E_network_kwh_gb = 0.001 # kWh/GB (network intensity)
P_active_w = 18.5        # watts (S3 active)
P_idle_w = 18.5          # watts (S3 idle)
C_mem_gb = 5120          # GB (storage capacity)
P_GPU_w = 70             # watts (Rekognition GPU)
P_Proc_w = 95            # watts (API processor)
PUE = 1.15               # Power Usage Effectiveness
N_inv = 4                # Number of invocations
S_upload_mb = 32666      # MB (average upload size)
```

## Dashboard Panels

### Individual Component Panels
1. **Lambda Energy** - Total Lambda compute, memory, storage, and network energy
2. **S3 Energy** - S3 active and idle energy
3. **DynamoDB Energy** - DynamoDB request energy
4. **API Gateway Energy** - API processing energy
5. **Rekognition Energy** - Rekognition service energy

### Aggregated Panels
6. **Total SCI** - Sum of all energy components (stat)
7. **Software Carbon Intensity (SCI)** - Energy × GEF / 1000 (stat)
8. **Total Energy Breakdown** - Stacked bar chart of all components

## Regenerating Dashboard

To regenerate the dashboard with new component discovery:

```bash
# Option 1: Update dashboard with new components
python3 generate_dashboard_complete.py

# Option 2: Preview new queries without modifying dashboard
python3 generate_dashboard.py
```

### What Gets Updated
- All Flux queries in all 8 panels
- Field name summations automatically adapted to discovered components
- Energy calculations remain identical

### What Doesn't Get Updated
- Panel layouts, colors, thresholds
- Dashboard metadata (UIDs, versions)
- Data source configurations

## Troubleshooting

### Problem: Dashboard shows no data
**Solution**: 
1. Verify Excel files exist in correct folders
2. Run `python3 simulator.py` to write metrics to InfluxDB
3. Check InfluxDB contains `measured_metrics` field

### Problem: Errors when regenerating dashboard
**Solution**:
1. Verify all Excel files have correct format
2. Check folder names exactly match:
   - `Lambda`, `S3`, `DynamoDB`, `API Gateway`, `Rekognition`
3. Ensure .xlsx file extensions are lowercase

### Problem: New components not appearing in dashboard
**Solution**:
1. Run `python3 generate_dashboard_complete.py` to regenerate
2. Reload Grafana dashboard (Ctrl+Shift+R or Cmd+Shift+R)
3. Clear browser cache if needed

## Adding Components During Runtime

1. Add Excel file to appropriate folder
2. Run `python3 simulator.py` (it auto-discovers new files)
3. Wait for InfluxDB to receive new data
4. Run `python3 generate_dashboard_complete.py`
5. Reload Grafana dashboard

The system is now fully dynamic and supports adding unlimited components!

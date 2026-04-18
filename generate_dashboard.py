#!/usr/bin/env python3
"""
Dynamic Dashboard Generator for Serverless Energy Metrics
Generates dashboard.json based on discovered Excel files in Final Serverless Metrics folder
"""

import json
import sys
from pathlib import Path
from simulator import METRIC_FILES

# ============================================================================
# FLUX QUERY TEMPLATES & GENERATORS
# ============================================================================

def generate_lambda_queries(lambda_components):
    """Generate Flux query components for Lambda energy calculations"""
    if not lambda_components:
        return {}
    
    # Build dynamic component checks for each metric type
    def make_component_sum(metric_suffix):
        """Create sum of metric across all lambda components"""
        parts = []
        for name in lambda_components:
            parts.append(f"(if exists r[\"lambda_{name}_{metric_suffix}\"] then r[\"lambda_{name}_{metric_suffix}\"] else 0.0)")
        return f" + ".join(parts)
    
    return {
        "tcpu_malloc": make_component_sum("Tcpu") + " * " + make_component_sum("Malloc"),
        "mused": make_component_sum("Mused"),
        "texec_tinit": make_component_sum("Texec") + " + " + make_component_sum("Tinit"),
        "sused": make_component_sum("Sused"),
        "dnetwork": make_component_sum("Dnetwork"),
    }

def generate_s3_queries(s3_components):
    """Generate Flux query components for S3 energy calculations"""
    if not s3_components:
        return {}
    
    # S3 active energy: sum of (Rtotal * Dlatency) for all buckets
    active_parts = []
    for name in s3_components:
        active_parts.append(f"(if exists r[\"s3_{name}_Rtotal\"] then r[\"s3_{name}_Rtotal\"] else 0.0) * (if exists r[\"s3_{name}_Dlatency\"] then r[\"s3_{name}_Dlatency\"] else 0.0)")
    s3_active = " + ".join(active_parts)
    
    # S3 idle energy: (sum(B) + N_inv * S_upload) / 1024^3 * ...
    # Note: S_upload is applied to TOTAL B, not per-bucket
    B_parts = []
    for name in s3_components:
        B_parts.append(f"(if exists r[\"s3_{name}_B\"] then r[\"s3_{name}_B\"] else 0.0)")
    s3_B_sum = " + ".join(B_parts)
    
    # For S3 idle: multiply S_upload by number of buckets (each bucket has its own active/idle cycle)
    s3_upload_multiplier = len(s3_components)
    
    return {
        "active": s3_active,
        "B_sum": s3_B_sum,
        "upload_multiplier": s3_upload_multiplier
    }

def generate_dynamodb_queries(dynamodb_components):
    """Generate Flux query components for DynamoDB energy calculations"""
    if not dynamodb_components:
        return {}
    
    # DynamoDB: sum of Lsuccess for all tables
    parts = []
    for name in dynamodb_components:
        parts.append(f"(if exists r[\"dynamodb_{name}_Lsuccess\"] then r[\"dynamodb_{name}_Lsuccess\"] else 0.0)")
    lsuccess = " + ".join(parts)
    
    return {"lsuccess": lsuccess}

def generate_api_queries(api_components):
    """Generate Flux query components for API Gateway energy calculations"""
    if not api_components:
        return {}
    
    # API: sum of LAPI for all APIs
    parts = []
    for name in api_components:
        parts.append(f"(if exists r[\"api_{name}_LAPI\"] then r[\"api_{name}_LAPI\"] else 0.0)")
    lapi = " + ".join(parts)
    
    return {"lapi": lapi}

def generate_rekognition_queries(rekognition_components):
    """Generate Flux query components for Rekognition energy calculations"""
    if not rekognition_components:
        return {}
    
    # Rekognition: sum of Tresponse for all services
    parts = []
    for name in rekognition_components:
        parts.append(f"(if exists r[\"rekognition_{name}_Tresponse\"] then r[\"rekognition_{name}_Tresponse\"] else 0.0)")
    tresponse = " + ".join(parts)
    
    return {"tresponse": tresponse}

def build_full_flux_query(lambda_comp, s3_comp, dynamodb_comp, api_comp, rekognition_comp):
    """Build complete Flux query for all energy calculations"""
    
    lambda_q = generate_lambda_queries(lambda_comp)
    s3_q = generate_s3_queries(s3_comp)
    dynamodb_q = generate_dynamodb_queries(dynamodb_comp)
    api_q = generate_api_queries(api_comp)
    rekognition_q = generate_rekognition_queries(rekognition_comp)
    
    # Build the map function with all energy calculations
    map_fn = (
        "map(fn: (r) => ({\n"
        "    r with\n"
    )
    
    # ELcompute: (Tcpu × Malloc × P_core) / (1000 × 3600 × 1000 × Mref)
    if lambda_q:
        map_fn += (
            f"    ELcompute: ({lambda_q['tcpu_malloc']}) * "
            f"(if exists r[\"assumed_P_core_w\"] then r[\"assumed_P_core_w\"] else 95.0) / "
            f"((1000.0 * 3600.0 * 1000.0) * 1769.0),\n"
        )
    else:
        map_fn += "    ELcompute: 0.0,\n"
    
    # ELmemory: (Mused × P_mem × (Texec + Tinit)) / (1024 × 1000 × 3600 × 1000)
    if lambda_q:
        map_fn += (
            f"    ELmemory: ({lambda_q['mused']}) * ({lambda_q['texec_tinit']}) * "
            f"(if exists r[\"assumed_P_mem_w\"] then r[\"assumed_P_mem_w\"] else 0.392) / "
            f"(1024.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        )
    else:
        map_fn += "    ELmemory: 0.0,\n"
    
    # ELstorage: (Sused × P_storage × (Texec + Tinit)) / (1024³ × 1000 × 3600 × 1000)
    if lambda_q:
        map_fn += (
            f"    ELstorage: ({lambda_q['sused']}) * ({lambda_q['texec_tinit']}) * "
            f"(if exists r[\"assumed_P_storage_w\"] then r[\"assumed_P_storage_w\"] else 0.0012) / "
            f"(1073741824.0 * (1000.0 * 3600.0 * 1000.0)),\n"
        )
    else:
        map_fn += "    ELstorage: 0.0,\n"
    
    # Enetwork: (Dnetwork × E_network_intensity) / 1024³
    if lambda_q:
        map_fn += (
            f"    Enetwork: ({lambda_q['dnetwork']}) * "
            f"(if exists r[\"assumed_E_network_kwh_gb\"] then r[\"assumed_E_network_kwh_gb\"] else 0.001) / "
            f"1073741824.0,\n"
        )
    else:
        map_fn += "    Enetwork: 0.0,\n"
    
    # ES3active: sum(Rtotal × Dlatency) × P_active / (1000 × 3600 × 1000)
    if s3_q:
        map_fn += (
            f"    ES3active: ({s3_q['active']}) * "
            f"(if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / "
            f"(1000.0 * 3600.0 * 1000.0),\n"
        )
    else:
        map_fn += "    ES3active: 0.0,\n"
    
    # ES3idle: (sum(B) + N_inv × S_upload × num_buckets) / 1024³ × (P_idle / (C_mem × 1000))
    if s3_q:
        s3_upload_multiplier = s3_q['upload_multiplier']
        map_fn += (
            f"    ES3idle: ((({s3_q['B_sum']}) + "
            f"((if exists r[\"assumed_N_inv\"] then r[\"assumed_N_inv\"] else 4.0) * "
            f"(if exists r[\"assumed_S_upload_mb\"] then r[\"assumed_S_upload_mb\"] else 32666.0) * {s3_upload_multiplier})) / 1073741824.0) * "
            f"((if exists r[\"assumed_P_idle_w\"] then r[\"assumed_P_idle_w\"] else 18.5) / "
            f"((if exists r[\"assumed_C_mem_gb\"] then r[\"assumed_C_mem_gb\"] else 5120.0) * 1000.0)),\n"
        )
    else:
        map_fn += "    ES3idle: 0.0,\n"
    
    # EDB: sum(Lsuccess) × P_active / (1000 × 3600 × 1000)
    if dynamodb_q:
        map_fn += (
            f"    EDB: ({dynamodb_q['lsuccess']}) * "
            f"(if exists r[\"assumed_P_active_w\"] then r[\"assumed_P_active_w\"] else 18.5) / "
            f"(1000.0 * 3600.0 * 1000.0),\n"
        )
    else:
        map_fn += "    EDB: 0.0,\n"
    
    # EAPI: sum(LAPI) × P_Proc / (1000 × 3600 × 1000)
    if api_q:
        map_fn += (
            f"    EAPI: ({api_q['lapi']}) * "
            f"(if exists r[\"assumed_P_Proc_w\"] then r[\"assumed_P_Proc_w\"] else 95.0) / "
            f"(1000.0 * 3600.0 * 1000.0),\n"
        )
    else:
        map_fn += "    EAPI: 0.0,\n"
    
    # ERekog: sum(Tresponse) × P_GPU / (1000 × 3600 × 1000)
    if rekognition_q:
        map_fn += (
            f"    ERekog: ({rekognition_q['tresponse']}) * "
            f"(if exists r[\"assumed_P_GPU_w\"] then (if r[\"assumed_P_GPU_w\"] > 0.0 then r[\"assumed_P_GPU_w\"] else 70.0) else 70.0) / "
            f"(1000.0 * 3600.0 * 1000.0),\n"
        )
    else:
        map_fn += "    ERekog: 0.0,\n"
    
    # Add PUE and GEF
    map_fn += (
        "    PUE: (if exists r[\"assumed_PUE\"] then r[\"assumed_PUE\"] else 1.15),\n"
        "    GEF: (if exists r[\"grid_emission_factor\"] then r[\"grid_emission_factor\"] else 541.0)\n"
        "}))\n"
    )
    
    # Complete query
    query = (
        "from(bucket: \"demo_bucket\")\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        "  |> filter(fn: (r) => r[\"_measurement\"] == \"measured_metrics\")\n"
        "  |> last()\n"
        "  |> pivot(rowKey:[\"_time\"], columnKey:[\"_field\"], valueColumn:\"_value\")\n"
        + map_fn +
        "  |> map(fn: (r) => ({ r with _value: r.ELcompute + r.ELmemory + r.ELstorage + r.Enetwork }))\n"
        "  \n"
        "  |> keep(columns: [\"_time\", \"_value\"])"
    )
    
    return query

# ============================================================================
# MAIN SCRIPT
# ============================================================================

if __name__ == "__main__":
    # Discover components
    lambda_components = list(METRIC_FILES.get("Lambda", {}).keys())
    s3_components = list(METRIC_FILES.get("S3", {}).keys())
    dynamodb_components = list(METRIC_FILES.get("DynamoDB", {}).keys())
    api_components = list(METRIC_FILES.get("API", {}).keys())
    rekognition_components = list(METRIC_FILES.get("Rekognition", {}).keys())
    
    print("Discovered Components:")
    print(f"  Lambda: {lambda_components}")
    print(f"  S3: {s3_components}")
    print(f"  DynamoDB: {dynamodb_components}")
    print(f"  API: {api_components}")
    print(f"  Rekognition: {rekognition_components}")
    print()
    
    # Generate main query
    query = build_full_flux_query(
        lambda_components, s3_components, dynamodb_components, 
        api_components, rekognition_components
    )
    
    print("Generated Flux Query Preview (first 500 chars):")
    print(query[:500] + "...")
    print()
    print("Full query length:", len(query), "characters")

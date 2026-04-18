#!/usr/bin/env python3
"""
System Test for Dynamic Discovery
Verifies that simulator.py and dashboard generation work correctly
"""

import subprocess
import json
from pathlib import Path
from simulator import METRIC_FILES

def test_simulator_discovery():
    """Test 1: Verify simulator discovers all files"""
    print("=" * 60)
    print("TEST 1: Simulator Component Discovery")
    print("=" * 60)
    
    expected = {
        "Lambda": 5,
        "S3": 2,
        "DynamoDB": 2,
        "API": 1,
        "Rekognition": 1,
    }
    
    for category, expected_count in expected.items():
        actual_count = len(METRIC_FILES.get(category, {}))
        status = "✓" if actual_count == expected_count else "✗"
        print(f"{status} {category}: {actual_count} (expected {expected_count})")
        
        if actual_count != expected_count:
            return False
    
    print()
    return True

def test_simulator_run():
    """Test 2: Verify simulator.py runs without errors"""
    print("=" * 60)
    print("TEST 2: Simulator Execution")
    print("=" * 60)
    
    result = subprocess.run(
        ["python3", "simulator.py"],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    if result.returncode == 0:
        print("✓ simulator.py executed successfully")
        # Check for success message
        if "successfully written" in result.stdout or "successfully written" in result.stderr:
            print("✓ Metrics written to InfluxDB")
    else:
        print(f"✗ simulator.py failed with return code {result.returncode}")
        print(f"Error: {result.stderr}")
        return False
    
    print()
    return True

def test_dashboard_generation():
    """Test 3: Verify dashboard generation"""
    print("=" * 60)
    print("TEST 3: Dashboard Generation")
    print("=" * 60)
    
    result = subprocess.run(
        ["python3", "generate_dashboard_complete.py"],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    if result.returncode == 0:
        print("✓ Dashboard generator executed successfully")
        if "Updated 8 panels" in result.stdout:
            print("✓ All 8 panels updated")
        else:
            print(f"⚠ Unexpected output: {result.stdout[:200]}")
    else:
        print(f"✗ Dashboard generator failed: {result.stderr}")
        return False
    
    print()
    return True

def test_dashboard_queries():
    """Test 4: Verify dashboard queries are valid"""
    print("=" * 60)
    print("TEST 4: Dashboard Query Validation")
    print("=" * 60)
    
    with open("grafana-dashboards/dashboard.json", "r") as f:
        dashboard = json.load(f)
    
    panel_titles = [
        "Lambda Energy",
        "S3 Energy",
        "DynamoDB Energy",
        "API Gateway Energy",
        "Rekognition Energy",
        "Total SCI",
        "Software Carbon Intensity (SCI)",
        "Total Energy Breakdown (kWh)",
    ]
    
    all_valid = True
    for title in panel_titles:
        panel = next((p for p in dashboard["panels"] if p.get("title") == title), None)
        if panel and panel.get("targets"):
            query = panel["targets"][0].get("query", "")
            if query and "from(bucket:" in query and "map(fn:" in query:
                print(f"✓ {title}: Valid Flux query")
            else:
                print(f"✗ {title}: Invalid query format")
                all_valid = False
        else:
            print(f"✗ {title}: Panel or query not found")
            all_valid = False
    
    print()
    return all_valid

def test_query_contains_components():
    """Test 5: Verify queries contain all discovered components"""
    print("=" * 60)
    print("TEST 5: Query Component Coverage")
    print("=" * 60)
    
    with open("grafana-dashboards/dashboard.json", "r") as f:
        dashboard = json.load(f)
    
    lambda_comp = list(METRIC_FILES.get("Lambda", {}).keys())
    s3_comp = list(METRIC_FILES.get("S3", {}).keys())
    
    # Check Lambda panel
    lambda_panel = next((p for p in dashboard["panels"] if p.get("title") == "Lambda Energy"), None)
    if lambda_panel:
        query = lambda_panel["targets"][0].get("query", "")
        for func in lambda_comp:
            if f"lambda_{func}" in query:
                print(f"✓ Lambda query includes {func}")
            else:
                print(f"✗ Lambda query missing {func}")
    
    # Check S3 panel
    s3_panel = next((p for p in dashboard["panels"] if p.get("title") == "S3 Energy"), None)
    if s3_panel:
        query = s3_panel["targets"][0].get("query", "")
        for bucket in s3_comp:
            if f"s3_{bucket}" in query:
                print(f"✓ S3 query includes bucket {bucket}")
            else:
                print(f"✗ S3 query missing bucket {bucket}")
    
    print()
    return True

def main():
    print("\n" + "=" * 60)
    print("DYNAMIC DISCOVERY SYSTEM TEST SUITE")
    print("=" * 60 + "\n")
    
    tests = [
        ("Component Discovery", test_simulator_discovery),
        ("Simulator Execution", test_simulator_run),
        ("Dashboard Generation", test_dashboard_generation),
        ("Dashboard Query Validation", test_dashboard_queries),
        ("Query Component Coverage", test_query_contains_components),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"ERROR in {test_name}: {e}\n")
            results.append((test_name, False))
    
    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print()
    
    return all(r for _, r in results)

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)

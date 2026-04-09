#!/usr/bin/env python
"""Comprehensive test for IQF remarks endpoint - Multiple scenarios"""
import os
import sys
import django
import json

# Setup Django FIRST
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
sys.path.insert(0, 'a:\\Workspace\\Watchcase\\TTT-Jan2026')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from modelmasterapp.models import TotalStockModel

def test_scenario(name, lot_id, remark, expected_status, should_save=True):
    """Test a specific scenario"""
    print(f"\n{'='*60}")
    print(f"Scenario: {name}")
    print(f"{'='*60}")
    
    # Get test user
    user = User.objects.first()
    
    # Get before state
    try:
        ts_before = TotalStockModel.objects.get(lot_id=lot_id)
        before_value = ts_before.IQF_pick_remarks
        print(f"Before: '{before_value}'")
    except TotalStockModel.DoesNotExist:
        print(f"❌ Lot not found: {lot_id}")
        return False
    
    # Create client and login
    client = Client()
    client.force_login(user)
    
    # Make request
    payload = {
        'lot_id': lot_id,
        'remark': remark
    }
    
    response = client.post(
        '/iqf/iqf_save_pick_remark/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"Response Status: {response.status_code} (expected {expected_status})")
    
    try:
        resp_data = response.json()
        print(f"Response: {resp_data.get('message') or resp_data.get('error')}")
    except:
        print(f"Response: {response.content}")
        return False
    
    # Verify
    ts_after = TotalStockModel.objects.get(lot_id=lot_id)
    after_value = ts_after.IQF_pick_remarks
    print(f"After: '{after_value}'")
    
    if response.status_code != expected_status:
        print(f"❌ FAILED: Status mismatch")
        return False
    
    if should_save:
        if after_value == remark:
            print(f"✅ PASSED: Remark saved correctly")
            return True
        else:
            print(f"❌ FAILED: Remark not saved (expected '{remark}', got '{after_value}')")
            return False
    else:
        if after_value == before_value:
            print(f"✅ PASSED: Remark not changed as expected")
            return True
        else:
            print(f"❌ FAILED: Remark should not have changed")
            return False

def get_second_lot():
    """Find a second lot for testing (different from the first one)"""
    first_lot = "LID080420261235220016"
    second = TotalStockModel.objects.exclude(lot_id=first_lot).first()
    if second:
        return second.lot_id
    return None

def run_all_tests():
    """Run all test scenarios"""
    tests_passed = 0
    tests_total = 0
    
    print("\n" + "="*60)
    print("IQF REMARKS ENDPOINT - COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    # Test 1: Original test case
    tests_total += 1
    if test_scenario(
        "Test 1: Original user report data",
        "LID080420261235220016",
        "sdfwe",
        expected_status=200,
        should_save=True
    ):
        tests_passed += 1
    
    # Test 2: Different remark text
    tests_total += 1
    if test_scenario(
        "Test 2: Updated remark on same lot",
        "LID080420261235220016",
        "Complete inspection - OK",
        expected_status=200,
        should_save=True
    ):
        tests_passed += 1
    
    # Test 3: Empty remark (should save empty string)
    tests_total += 1
    if test_scenario(
        "Test 3: Clear remark (empty string)",
        "LID080420261235220016",
        "",
        expected_status=200,
        should_save=True
    ):
        tests_passed += 1
    
    # Test 4: Long remark (should truncate at 100 chars)
    tests_total += 1
    long_remark = "a" * 150
    print(f"\n{'='*60}")
    print(f"Scenario: Test 4: Long remark (should truncate at 100)")
    print(f"{'='*60}")
    user = User.objects.first()
    client = Client()
    client.force_login(user)
    
    ts_before = TotalStockModel.objects.get(lot_id="LID080420261235220016")
    payload = {'lot_id': "LID080420261235220016", 'remark': long_remark}
    response = client.post(
        '/iqf/iqf_save_pick_remark/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    if response.status_code == 200:
        ts_after = TotalStockModel.objects.get(lot_id="LID080420261235220016")
        if len(ts_after.IQF_pick_remarks) == 100 and ts_after.IQF_pick_remarks == "a" * 100:
            print(f"✅ PASSED: Long remark correctly truncated to 100 chars")
            tests_passed += 1
        else:
            print(f"❌ FAILED: Truncation not working correctly")
            print(f"   Length: {len(ts_after.IQF_pick_remarks)} (expected 100)")
    else:
        print(f"❌ FAILED: Got status {response.status_code}")

    
    # Test 5: Second lot - dynamic validation
    second_lot = get_second_lot()
    if second_lot:
        tests_total += 1
        if test_scenario(
            f"Test 5: Different lot (dynamic validation) - {second_lot}",
            second_lot,
            "Test remark for second lot",
            expected_status=200,
            should_save=True
        ):
            tests_passed += 1
    else:
        print("\n⚠️  Test 5 SKIPPED: No second lot found in database")
    
    # Test 6: Non-existent lot
    tests_total += 1
    print(f"\n{'='*60}")
    print(f"Scenario: Test 6: Non-existent lot")
    print(f"{'='*60}")
    user = User.objects.first()
    client = Client()
    client.force_login(user)
    response = client.post(
        '/iqf/iqf_save_pick_remark/',
        data=json.dumps({'lot_id': 'INVALID_LOT_ID', 'remark': 'test'}),
        content_type='application/json'
    )
    if response.status_code == 404:
        print(f"✅ PASSED: Correctly returned 404 for non-existent lot")
        tests_passed += 1
    else:
        print(f"❌ FAILED: Expected 404, got {response.status_code}")
    
    # Test 7: Missing lot_id
    tests_total += 1
    print(f"\n{'='*60}")
    print(f"Scenario: Test 7: Missing lot_id parameter")
    print(f"{'='*60}")
    response = client.post(
        '/iqf/iqf_save_pick_remark/',
        data=json.dumps({'remark': 'test'}),
        content_type='application/json'
    )
    if response.status_code == 400:
        print(f"✅ PASSED: Correctly returned 400 for missing lot_id")
        tests_passed += 1
    else:
        print(f"❌ FAILED: Expected 400, got {response.status_code}")
    
    # Summary
    print("\n" + "="*80)
    print(f"TEST SUMMARY: {tests_passed}/{tests_total} passed")
    print("="*80)
    
    if tests_passed == tests_total:
        print("✅ ALL TESTS PASSED")
        return True
    else:
        print(f"❌ {tests_total - tests_passed} TEST(S) FAILED")
        return False

if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)

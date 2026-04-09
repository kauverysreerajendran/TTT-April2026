#!/usr/bin/env python
"""Test script for IQF remarks endpoint"""
import os
import sys
import django
import json

# Setup Django FIRST before any other imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
sys.path.insert(0, 'a:\\Workspace\\Watchcase\\TTT-Jan2026')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from modelmasterapp.models import TotalStockModel

def test_iqf_save_pick_remark():
    """Test the iqf_save_pick_remark endpoint with real data"""
    
    # Get a test user
    user = User.objects.first()
    if not user:
        print("❌ No user found in database")
        return False
    
    print(f"✅ Test user: {user.username}")
    
    # Test data from user report
    lot_id = "LID080420261235220016"
    remark_text = "sdfwe"
    
    # Check lot exists
    try:
        ts = TotalStockModel.objects.get(lot_id=lot_id)
        print(f"✅ Lot found: {lot_id}")
    except TotalStockModel.DoesNotExist:
        print(f"❌ Lot not found: {lot_id}")
        return False
    
    # Get value before
    print(f"\n📊 Before API call:")
    print(f"   IQF_pick_remarks = '{ts.IQF_pick_remarks}'")
    
    # Create test client and login
    client = Client()
    client.force_login(user)
    print(f"✅ Client authenticated as {user.username}")
    
    # Prepare payload
    payload = {
        'lot_id': lot_id,
        'remark': remark_text
    }
    print(f"\n📨 Sending POST request to /iqf/iqf_save_pick_remark/")
    print(f"   Payload: {payload}")
    
    # Make API call
    response = client.post(
        '/iqf/iqf_save_pick_remark/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"\n📤 Response:")
    print(f"   Status Code: {response.status_code}")
    
    try:
        response_data = response.json()
        print(f"   Response Body: {response_data}")
        
        if response.status_code == 200 and response_data.get('success'):
            print(f"   ✅ Got success response")
        else:
            print(f"   ❌ Error: {response_data.get('error', 'Unknown error')}")
            return False
    except json.JSONDecodeError:
        print(f"   ❌ Invalid JSON response: {response.content}")
        return False
    
    # Verify database update
    ts_after = TotalStockModel.objects.get(lot_id=lot_id)
    print(f"\n📊 After API call:")
    print(f"   IQF_pick_remarks = '{ts_after.IQF_pick_remarks}'")
    
    if ts_after.IQF_pick_remarks == remark_text:
        print(f"\n✅ SUCCESS: Remark saved correctly to database!")
        return True
    else:
        print(f"\n❌ FAILURE: Remark not saved to database")
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("Testing IQF Remarks Endpoint")
    print("=" * 60)
    success = test_iqf_save_pick_remark()
    print("\n" + "=" * 60)
    if success:
        print("✅ TEST PASSED")
        print("=" * 60)
        exit(0)
    else:
        print("❌ TEST FAILED")
        print("=" * 60)
        exit(1)

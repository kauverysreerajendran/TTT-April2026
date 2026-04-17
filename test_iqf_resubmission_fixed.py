#!/usr/bin/env python
"""
Test: IQF-Returned Lot Resubmission to Brass QC
Validates that lots flagged with send_brass_qc=True can resubmit despite existing submission records.
"""
import os
import sys
import django
from django.test import TestCase, Client
# from django.contrib.auth.models import User
from datetime import datetime
from django.contrib.auth.models import User

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import (
    TotalStockModel, ModelMasterCreation, Plating_Color, Version, 
    Category, Vendor, Location, TrayType
)
from Brass_QC.models import Brass_QC_Submission, BrassTrayId
from IQF.models import IQFTrayId
from DayPlanning.models import Tray as DPTray


def setup_test_data():
    """Create minimal test data for testing."""
    # Create test user
    user, _ = User.objects.get_or_create(
        username='testuser',
        defaults={'email': 'test@example.com', 'is_staff': True}
    )
    
    # Create master data
    plating, _ = Plating_Color.objects.get_or_create(
        plating_color='Test_Black',
        defaults={'plating_color_internal': 'B'}
    )
    
    version, _ = Version.objects.get_or_create(
        version_name='Test_V1',
        defaults={'version_internal': 'V1'}
    )
    
    category, _ = Category.objects.get_or_create(category_name='Test_Cat')
    vendor, _ = Vendor.objects.get_or_create(
        vendor_name='Test_Vendor',
        defaults={'vendor_internal': 'TV'}
    )
    location, _ = Location.objects.get_or_create(location_name='Test_Loc')
    tray_type, _ = TrayType.objects.get_or_create(
        tray_type='TestTray',
        defaults={'tray_capacity': 12}
    )
    
    # Create ModelMaster
    model_master, _ = ModelMasterCreation.objects.get_or_create(
        model_no='TEST-001',
        batch_id='BATCH-001',
        defaults={
            'plating_color': plating,
            'version': version,
            'category': category,
            'vendor_internal': vendor.vendor_internal,
            'location': location,
            'tray_type': tray_type.tray_type,
            'tray_capacity': tray_type.tray_capacity,
            'date_time': datetime.now(),
            'createdby': user,
            'accepted_Ip_stock': True,
        }
    )
    
    return user, model_master


def test_iqf_resubmission_scenario():
    """
    Test Scenario:
    1. Create a lot in Brass QC
    2. Submit it (creates submission record with is_completed=True)
    3. Mark it as send_brass_qc=True (simulating IQF acceptance)
    4. Try to submit again - should SUCCEED (not blocked)
    """
    print("\n" + "="*80)
    print("TEST: IQF-Returned Lot Resubmission to Brass QC")
    print("="*80)
    
    user, model_master = setup_test_data()
    client = Client()
    
    # Authenticate
    client.force_login(user)
    
    # Step 1: Create test lot
    test_lot_id = "LID_TEST_IQF_RETURN"
    print(f"\n[Step 1] Creating test lot: {test_lot_id}")
    
    stock = TotalStockModel.objects.create(
        lot_id=test_lot_id,
        batch_id=model_master,
        total_stock=100,
        accepted_Ip_stock=True,
        total_IP_accpeted_quantity=100,
        brass_physical_qty=100,
        brass_qc_accepted_qty=0,
        brass_qc_rejection=False,
        brass_qc_accptance=False,
        next_process_module='Brass QC',
        last_process_module='Input Screening'
    )
    print(f"✓ Lot created: {stock.lot_id}")
    print(f"  - send_brass_qc initial: {stock.send_brass_qc}")
    
    # Step 2: Create tray data
    print(f"\n[Step 2] Creating tray data")
    tray = BrassTrayId.objects.create(
        lot_id=test_lot_id,
        tray_id='TRAY-TEST-001',
        tray_quantity=100,
        batch_id=model_master,
        top_tray=True
    )
    print(f"✓ Tray created: {tray.tray_id} (qty={tray.tray_quantity})")
    
    # Step 3: Initial submission to Brass QC
    print(f"\n[Step 3] Initial submission (FULL_ACCEPT)")
    response = client.post(
        '/brass_qc/api/action/',
        {
            'lot_id': test_lot_id,
            'action': 'FULL_ACCEPT',
            'accepted_tray_ids': ['TRAY-TEST-001'],
            'rejected_tray_ids': [],
            'remarks': 'Initial submission'
        },
        content_type='application/json'
    )
    print(f"Response status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code in [200, 201]:
        print(f"✓ Initial submission successful")
        submission = Brass_QC_Submission.objects.filter(lot_id=test_lot_id).first()
        print(f"  - Submission record created: id={submission.id}, is_completed={submission.is_completed}")
    else:
        print(f"✗ Initial submission FAILED: {response.json()}")
        return False
    
    # Step 4: Simulate IQF return by flagging send_brass_qc=True
    print(f"\n[Step 4] Simulating IQF return (send_brass_qc=True)")
    stock.refresh_from_db()
    stock.send_brass_qc = True
    stock.iqf_acceptance = True
    stock.brass_qc_accptance = False
    stock.brass_qc_rejection = False
    stock.next_process_module = 'Brass QC'
    stock.save(update_fields=['send_brass_qc', 'iqf_acceptance', 'brass_qc_accptance', 'brass_qc_rejection', 'next_process_module'])
    print(f"✓ Lot marked for IQF reentry: send_brass_qc={stock.send_brass_qc}")
    
    # Step 5: Try to resubmit - should NOW SUCCEED (IQF exception enabled)
    print(f"\n[Step 5] Attempting resubmission (IQF reentry with send_brass_qc=True)")
    response = client.post(
        '/brass_qc/api/action/',
        {
            'lot_id': test_lot_id,
            'action': 'FULL_ACCEPT',
            'accepted_tray_ids': ['TRAY-TEST-001'],
            'rejected_tray_ids': [],
            'remarks': 'IQF reentry resubmission'
        },
        content_type='application/json'
    )
    print(f"Response status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 409:
        print(f"✗ FAILED: Resubmission blocked (409 Conflict)")
        print(f"  This indicates the IQF reentry exception is NOT working")
        return False
    elif response.status_code in [200, 201]:
        print(f"✓ PASSED: Resubmission successful!")
        print(f"  Old submission record was cleared and new submission created")
        
        # Verify new submission
        new_submission = Brass_QC_Submission.objects.filter(lot_id=test_lot_id).first()
        print(f"  - New submission record: id={new_submission.id}, is_completed={new_submission.is_completed}")
        return True
    else:
        print(f"✗ Unexpected status code: {response.status_code}")
        return False


def test_normal_duplicate_blocking():
    """
    Test Scenario:
    1. Create a lot WITHOUT send_brass_qc flag
    2. Submit it
    3. Try to submit again - should FAIL (blocked as duplicate)
    """
    print("\n" + "="*80)
    print("TEST: Normal Duplicate Submission Blocking (Safety Check)")
    print("="*80)
    
    user, model_master = setup_test_data()
    client = Client()
    client.force_login(user)
    
    # Create test lot
    test_lot_id = "LID_TEST_NORMAL_DUP"
    print(f"\n[Step 1] Creating test lot: {test_lot_id}")
    
    stock = TotalStockModel.objects.create(
        lot_id=test_lot_id,
        batch_id=model_master,
        total_stock=100,
        accepted_Ip_stock=True,
        total_IP_accpeted_quantity=100,
        brass_physical_qty=100,
        brass_qc_accepted_qty=0,
        send_brass_qc=False,  # NOT from IQF
        next_process_module='Brass QC',
        last_process_module='Input Screening'
    )
    print(f"✓ Lot created: send_brass_qc={stock.send_brass_qc}")
    
    # Create tray
    BrassTrayId.objects.create(
        lot_id=test_lot_id,
        tray_id='TRAY-DUP-001',
        tray_quantity=100,
        batch_id=model_master,
        top_tray=True
    )
    
    # First submission
    print(f"\n[Step 2] First submission")
    response1 = client.post(
        '/brass_qc/api/action/',
        {
            'lot_id': test_lot_id,
            'action': 'FULL_ACCEPT',
            'accepted_tray_ids': ['TRAY-DUP-001'],
            'rejected_tray_ids': [],
        },
        content_type='application/json'
    )
    print(f"Status: {response1.status_code} - {'✓ Success' if response1.status_code in [200, 201] else '✗ Failed'}")
    
    # Second submission attempt - should be blocked
    print(f"\n[Step 3] Duplicate submission attempt (should be blocked)")
    response2 = client.post(
        '/brass_qc/api/action/',
        {
            'lot_id': test_lot_id,
            'action': 'FULL_ACCEPT',
            'accepted_tray_ids': ['TRAY-DUP-001'],
            'rejected_tray_ids': [],
        },
        content_type='application/json'
    )
    print(f"Status: {response2.status_code}")
    print(f"Response: {response2.json()}")
    
    if response2.status_code == 409:
        print(f"✓ PASSED: Duplicate submission correctly blocked (409 Conflict)")
        return True
    else:
        print(f"✗ FAILED: Duplicate submission should have been blocked")
        print(f"  Got status {response2.status_code} instead of 409")
        return False


if __name__ == '__main__':
    print("\n" + "="*80)
    print("IQF RESUBMISSION TEST SUITE")
    print("="*80)
    
    # Run tests
    test1_pass = test_iqf_resubmission_scenario()
    test2_pass = test_normal_duplicate_blocking()
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Test 1 (IQF Resubmission):        {'✓ PASS' if test1_pass else '✗ FAIL'}")
    print(f"Test 2 (Normal Duplicate Block):  {'✓ PASS' if test2_pass else '✗ FAIL'}")
    print(f"\nOverall Result: {'✓ ALL TESTS PASSED' if test1_pass and test2_pass else '✗ SOME TESTS FAILED'}")
    print("="*80 + "\n")
    
    sys.exit(0 if test1_pass and test2_pass else 1)

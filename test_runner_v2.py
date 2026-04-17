import os
import sys
import django
from datetime import datetime

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from modelmasterapp.models import (
    TotalStockModel, ModelMasterCreation, Plating_Color, Version, 
    Category, Vendor, Location, TrayType
)
from Brass_QC.models import Brass_QC_Submission, BrassTrayId

def setup_test_data():
    user, _ = User.objects.get_or_create(
        username='testuser_unique',
        defaults={'email': 'test_unique@example.com', 'is_staff': True}
    )
    plating, _ = Plating_Color.objects.get_or_create(plating_color_internal='B_UNIQ', defaults={'plating_color': 'Test_Black_Unique'})
    version, _ = Version.objects.get_or_create(version_internal='V_UNIQ', defaults={'version_name': 'Test_V_Unique'})
    category, _ = Category.objects.get_or_create(category_name='Test_Cat_Unique')
    vendor, _ = Vendor.objects.get_or_create(vendor_internal='TV_U', defaults={'vendor_name': 'Test_Vendor_Unique'})
    location, _ = Location.objects.get_or_create(location_name='Test_Loc_Unique')
    tray_type, _ = TrayType.objects.get_or_create(tray_type='TestTrayUnique', defaults={'tray_capacity': 12})
    model_master, _ = ModelMasterCreation.objects.get_or_create(
        model_no='TEST-UNIQ-001', batch_id='BATCH-UNIQ-001',
        defaults={
            'plating_color': plating, 'version': version, 'category': category,
            'vendor_internal': vendor.vendor_internal, 'location': location,
            'tray_type': tray_type.tray_type, 'tray_capacity': tray_type.tray_capacity,
            'date_time': datetime.now(), 'createdby': user, 'accepted_Ip_stock': True,
        }
    )
    return user, model_master

def test_iqf_resubmission_scenario():
    print("\n" + "="*80)
    print("TEST: IQF-Returned Lot Resubmission to Brass QC")
    print("="*80)
    user, model_master = setup_test_data()
    client = Client()
    client.force_login(user)
    test_lot_id = "LID_TEST_IQF_RETURN"
    TotalStockModel.objects.filter(lot_id=test_lot_id).delete()
    stock = TotalStockModel.objects.create(
        lot_id=test_lot_id, batch_id=model_master, total_stock=100, accepted_Ip_stock=True,
        total_IP_accpeted_quantity=100, brass_physical_qty=100, next_process_module='Brass QC', last_process_module='Input Screening'
    )
    Brass_QC_Submission.objects.filter(lot_id=test_lot_id).delete()
    BrassTrayId.objects.filter(lot_id=test_lot_id).delete()
    BrassTrayId.objects.create(lot_id=test_lot_id, tray_id='TRAY-TEST-001', tray_quantity=100, batch_id=model_master, top_tray=True)
    response = client.post('/brass_qc/api/action/', {'lot_id': test_lot_id, 'action': 'FULL_ACCEPT', 'accepted_tray_ids': ['TRAY-TEST-001'], 'rejected_tray_ids': [], 'remarks': 'Initial submission'}, content_type='application/json')
    print(f"Initial submission: {response.status_code}")
    stock.refresh_from_db()
    stock.send_brass_qc = True
    stock.iqf_acceptance = True
    stock.brass_qc_accptance = False
    stock.next_process_module = 'Brass QC'
    stock.save()
    response = client.post('/brass_qc/api/action/', {'lot_id': test_lot_id, 'action': 'FULL_ACCEPT', 'accepted_tray_ids': ['TRAY-TEST-001'], 'rejected_tray_ids': [], 'remarks': 'IQF reentry'}, content_type='application/json')
    print(f"Resubmission status: {response.status_code}")
    if response.status_code in [200, 201]:
        print("PASSED: Resubmission successful!")
        return True
    else:
        print(f"FAILED: Status {response.status_code}")
        return False

def test_normal_duplicate_blocking():
    print("\n" + "="*80)
    print("TEST: Normal Duplicate Submission Blocking")
    print("="*80)
    user, model_master = setup_test_data()
    client = Client()
    client.force_login(user)
    test_lot_id = "LID_TEST_NORMAL_DUP"
    TotalStockModel.objects.filter(lot_id=test_lot_id).delete()
    stock = TotalStockModel.objects.create(lot_id=test_lot_id, batch_id=model_master, total_stock=100, accepted_Ip_stock=True, total_IP_accpeted_quantity=100, brass_physical_qty=100, next_process_module='Brass QC', last_process_module='Input Screening')
    Brass_QC_Submission.objects.filter(lot_id=test_lot_id).delete()
    BrassTrayId.objects.filter(lot_id=test_lot_id).delete()
    BrassTrayId.objects.create(lot_id=test_lot_id, tray_id='TRAY-DUP-001', tray_quantity=100, batch_id=model_master, top_tray=True)
    client.post('/brass_qc/api/action/', {'lot_id': test_lot_id, 'action': 'FULL_ACCEPT', 'accepted_tray_ids': ['TRAY-DUP-001'], 'rejected_tray_ids': []}, content_type='application/json')
    response = client.post('/brass_qc/api/action/', {'lot_id': test_lot_id, 'action': 'FULL_ACCEPT', 'accepted_tray_ids': ['TRAY-DUP-001'], 'rejected_tray_ids': []}, content_type='application/json')
    print(f"Duplicate status: {response.status_code} ")
    if response.status_code == 409:
        print("PASSED: Duplicate correctly blocked")
        return True
    else:
        print(f"FAILED: Duplicate should have been blocked (got {response.status_code})")
        return False

if __name__ == '__main__':
    t1 = test_iqf_resubmission_scenario()
    t2 = test_normal_duplicate_blocking()
    sys.exit(0 if t1 and t2 else 1)

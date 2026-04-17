"""
Test file for Brass QC Raw Submission API
Tests the new POST /brass_qc/api/submission/ endpoint

Usage:
    python manage.py shell
    exec(open('test_brass_qc_raw_api.py').read())
"""

import json
import requests
from django.contrib.auth.models import User
from django.test import Client
from Brass_QC.models import Brass_QC_RawSubmission
from modelmasterapp.models import TotalStockModel, TrayId

# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: DRAFT Submission (SAVE)
# ══════════════════════════════════════════════════════════════════════════════
def test_draft_submission():
    print("\n" + "="*80)
    print("TEST 1: DRAFT Submission")
    print("="*80)
    
    client = Client()
    # Get a test user (create if needed)
    user = User.objects.first()
    if not user:
        user = User.objects.create_user(username='testuser', password='test123')
    client.force_login(user)
    
    payload = {
        "lot_id": "DRAFT_TEST_001",
        "batch_id": "BATCH_TEST_001",
        "plating_stk_no": "1805NAR02",
        "total_lot_qty": 100,
        "rejection_reasons": [
            {"reason": "DENT", "qty": 0},
            {"reason": "BUFFING COMPOUND", "qty": 20}
        ],
        "reject_trays": [
            {"tray_id": "TEST-TRAY-001", "qty": 10, "type": "NEW", "is_top": True},
            {"tray_id": "TEST-TRAY-002", "qty": 10, "type": "REUSED"}
        ],
        "accept_trays": [
            {"tray_id": "TEST-TRAY-003", "qty": 12, "type": "REUSED"},
            {"tray_id": "TEST-TRAY-004", "qty": 12, "type": "REUSED", "is_top": True},
            {"tray_id": "TEST-TRAY-005", "qty": 12, "type": "REUSED"},
            {"tray_id": "TEST-TRAY-006", "qty": 12, "type": "REUSED"},
            {"tray_id": "TEST-TRAY-007", "qty": 12, "type": "REUSED"}
        ],
        "delink_trays": [],
        "summary": {
            "accepted": 60,
            "rejected": 20,
            "delinked": 0
        },
        "remarks": "Pending review",
        "submission_type": "DRAFT"
    }
    
    response = client.post(
        '/brass_qc/api/submission/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 201, f"Expected 201, got {response.status_code}"
    data = response.json()
    assert data['status'] == 'success'
    assert data['submission_type'] == 'DRAFT'
    assert data['lot_id'] == 'DRAFT_TEST_001'
    
    # Verify in DB
    draft = Brass_QC_RawSubmission.objects.get(lot_id='DRAFT_TEST_001', submission_type='DRAFT')
    print(f"✅ Draft stored in DB: id={draft.id}")
    print(f"Payload keys: {list(draft.payload.keys())}")
    
    return draft.id


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2: SUBMIT (Full Accept)
# ══════════════════════════════════════════════════════════════════════════════
def test_full_accept_submission():
    print("\n" + "="*80)
    print("TEST 2: SUBMIT - Full Accept (60 accepted, 0 rejected)")
    print("="*80)
    
    client = Client()
    user = User.objects.first()
    client.force_login(user)
    
    # First, create a lot in TotalStockModel for testing
    # This is necessary for the API to move the stage
    from modelmasterapp.models import ModelMasterCreation
    
    try:
        lot = TotalStockModel.objects.get(lot_id='ACCEPT_TEST_001')
    except TotalStockModel.DoesNotExist:
        # Create minimal batch and lot for testing
        print("Creating test lot...")
        batch = ModelMasterCreation.objects.first()
        if not batch:
            print("⚠️  No batch found. Skipping stage movement verification.")
            lot = None
        else:
            lot = TotalStockModel.objects.create(
                lot_id='ACCEPT_TEST_001',
                batch_id=batch,
                total_batch_quantity=60
            )
            print(f"Created test lot: {lot.id}")
    
    payload = {
        "lot_id": "ACCEPT_TEST_001",
        "batch_id": "BATCH_TEST_002",
        "plating_stk_no": "1805NAR03",
        "total_lot_qty": 60,
        "rejection_reasons": [],
        "reject_trays": [],
        "accept_trays": [
            {"tray_id": "ACCEPT-001", "qty": 12, "type": "REUSED", "is_top": True},
            {"tray_id": "ACCEPT-002", "qty": 12, "type": "REUSED"},
            {"tray_id": "ACCEPT-003", "qty": 12, "type": "REUSED"},
            {"tray_id": "ACCEPT-004", "qty": 12, "type": "REUSED"},
            {"tray_id": "ACCEPT-005", "qty": 12, "type": "REUSED"}
        ],
        "delink_trays": [],
        "summary": {
            "accepted": 60,
            "rejected": 0,
            "delinked": 0
        },
        "remarks": "All passed quality check",
        "submission_type": "SUBMIT"
    }
    
    response = client.post(
        '/brass_qc/api/submission/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'success'
    assert data['submission_type'] == 'SUBMIT'
    assert data['next_module'] == 'Brass Audit'
    
    # Verify in DB
    submission = Brass_QC_RawSubmission.objects.get(lot_id='ACCEPT_TEST_001', submission_type='SUBMIT')
    print(f"✅ Submission stored in DB: id={submission.id}")
    
    # Verify trays were created
    trays = TrayId.objects.filter(lot_id='ACCEPT_TEST_001')
    print(f"✅ Trays created: {trays.count()}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3: SUBMIT (Full Reject)
# ══════════════════════════════════════════════════════════════════════════════
def test_full_reject_submission():
    print("\n" + "="*80)
    print("TEST 3: SUBMIT - Full Reject (0 accepted, 50 rejected)")
    print("="*80)
    
    client = Client()
    user = User.objects.first()
    client.force_login(user)
    
    # Create test lot
    from modelmasterapp.models import ModelMasterCreation
    try:
        batch = ModelMasterCreation.objects.first()
        lot = TotalStockModel.objects.create(
            lot_id='REJECT_TEST_001',
            batch_id=batch,
            total_batch_quantity=50
        )
    except:
        print("⚠️  Could not create test lot for verification")
    
    payload = {
        "lot_id": "REJECT_TEST_001",
        "batch_id": "BATCH_TEST_003",
        "plating_stk_no": "1805NAR04",
        "total_lot_qty": 50,
        "rejection_reasons": [
            {"reason": "CORROSION", "qty": 50}
        ],
        "reject_trays": [
            {"tray_id": "REJECT-001", "qty": 12, "type": "NEW", "is_top": True},
            {"tray_id": "REJECT-002", "qty": 12, "type": "REUSED"},
            {"tray_id": "REJECT-003", "qty": 12, "type": "REUSED"},
            {"tray_id": "REJECT-004", "qty": 14, "type": "REUSED"}
        ],
        "accept_trays": [],
        "delink_trays": [],
        "summary": {
            "accepted": 0,
            "rejected": 50,
            "delinked": 0
        },
        "remarks": "Severe corrosion detected. Send to rework.",
        "submission_type": "SUBMIT"
    }
    
    response = client.post(
        '/brass_qc/api/submission/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'success'
    assert data['submission_type'] == 'SUBMIT'
    assert data['next_module'] == 'IQF'
    
    print(f"✅ Full Reject submission created, moved to IQF")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: SUBMIT (Partial - Accept + Reject)
# ══════════════════════════════════════════════════════════════════════════════
def test_partial_submission():
    print("\n" + "="*80)
    print("TEST 4: SUBMIT - Partial (75 accepted, 25 rejected)")
    print("="*80)
    
    client = Client()
    user = User.objects.first()
    client.force_login(user)
    
    payload = {
        "lot_id": "PARTIAL_TEST_001",
        "batch_id": "BATCH_TEST_004",
        "plating_stk_no": "1805NAR05",
        "total_lot_qty": 100,
        "rejection_reasons": [
            {"reason": "DENT", "qty": 10},
            {"reason": "SCRATCH", "qty": 15}
        ],
        "reject_trays": [
            {"tray_id": "PARTIAL-R-001", "qty": 12, "type": "NEW", "is_top": True},
            {"tray_id": "PARTIAL-R-002", "qty": 13, "type": "REUSED"}
        ],
        "accept_trays": [
            {"tray_id": "PARTIAL-A-001", "qty": 12, "type": "REUSED"},
            {"tray_id": "PARTIAL-A-002", "qty": 12, "type": "REUSED"},
            {"tray_id": "PARTIAL-A-003", "qty": 12, "type": "REUSED"},
            {"tray_id": "PARTIAL-A-004", "qty": 12, "type": "REUSED"},
            {"tray_id": "PARTIAL-A-005", "qty": 12, "type": "REUSED", "is_top": True},
            {"tray_id": "PARTIAL-A-006", "qty": 3, "type": "REUSED"}
        ],
        "delink_trays": [],
        "summary": {
            "accepted": 75,
            "rejected": 25,
            "delinked": 0
        },
        "remarks": "Mixed results, investigating cause",
        "submission_type": "SUBMIT"
    }
    
    response = client.post(
        '/brass_qc/api/submission/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 201
    data = response.json()
    assert data['status'] == 'success'
    assert data['next_module'] == 'Brass Audit'  # Primary destination
    
    print(f"✅ Partial submission created, primary route to Brass Audit")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5: Validation Error - Qty Mismatch
# ══════════════════════════════════════════════════════════════════════════════
def test_validation_qty_mismatch():
    print("\n" + "="*80)
    print("TEST 5: Validation Error - Qty Mismatch")
    print("="*80)
    
    client = Client()
    user = User.objects.first()
    client.force_login(user)
    
    payload = {
        "lot_id": "INVALID_001",
        "batch_id": "BATCH_TEST_005",
        "plating_stk_no": "1805NAR06",
        "total_lot_qty": 100,
        "rejection_reasons": [],
        "reject_trays": [
            {"tray_id": "INVALID-R-001", "qty": 20, "type": "NEW", "is_top": True}
        ],
        "accept_trays": [
            {"tray_id": "INVALID-A-001", "qty": 60, "type": "REUSED", "is_top": True}
        ],
        "delink_trays": [],
        "summary": {
            "accepted": 60,
            "rejected": 20,
            "delinked": 0
        },
        "remarks": "Test validation",
        "submission_type": "SUBMIT"
    }
    
    response = client.post(
        '/brass_qc/api/submission/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 400, "Expected validation error (400)"
    data = response.json()
    assert data['status'] == 'error'
    assert 'Qty mismatch' in data['message']
    
    print(f"✅ Validation correctly caught qty mismatch")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6: Validation Error - Missing Remarks for Full Reject
# ══════════════════════════════════════════════════════════════════════════════
def test_validation_missing_remarks():
    print("\n" + "="*80)
    print("TEST 6: Validation Error - Missing Remarks for Full Reject")
    print("="*80)
    
    client = Client()
    user = User.objects.first()
    client.force_login(user)
    
    payload = {
        "lot_id": "INVALID_002",
        "batch_id": "BATCH_TEST_006",
        "plating_stk_no": "1805NAR07",
        "total_lot_qty": 50,
        "rejection_reasons": [
            {"reason": "DEFECT", "qty": 50}
        ],
        "reject_trays": [
            {"tray_id": "INVALID-R-002", "qty": 12, "type": "NEW", "is_top": True},
            {"tray_id": "INVALID-R-003", "qty": 12, "type": "REUSED"},
            {"tray_id": "INVALID-R-004", "qty": 12, "type": "REUSED"},
            {"tray_id": "INVALID-R-005", "qty": 14, "type": "REUSED"}
        ],
        "accept_trays": [],
        "delink_trays": [],
        "summary": {
            "accepted": 0,
            "rejected": 50,
            "delinked": 0
        },
        "remarks": "",  # ❌ MISSING - Should fail for full reject
        "submission_type": "SUBMIT"
    }
    
    response = client.post(
        '/brass_qc/api/submission/',
        data=json.dumps(payload),
        content_type='application/json'
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 400
    data = response.json()
    assert 'Remarks mandatory' in str(data.get('errors', ''))
    
    print(f"✅ Validation correctly required remarks for full reject")


# ══════════════════════════════════════════════════════════════════════════════
# RUN ALL TESTS
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("\n" + "█"*80)
    print("BRASS QC RAW SUBMISSION API - TEST SUITE")
    print("█"*80)
    
    try:
        test_draft_submission()
        test_full_accept_submission()
        test_full_reject_submission()
        test_partial_submission()
        test_validation_qty_mismatch()
        test_validation_missing_remarks()
        
        print("\n" + "█"*80)
        print("✅ ALL TESTS PASSED!")
        print("█"*80 + "\n")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()

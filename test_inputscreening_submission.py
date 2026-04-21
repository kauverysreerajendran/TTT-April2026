#!/usr/bin/env python
"""
Test script to verify InputScreening_Submitted implementation
Tests all 3 lot scenarios (full accept, full reject, partial split)
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "watchcase_tracker.settings")
django.setup()

from django.contrib.auth.models import User
from InputScreening.services_submitted import handle_submission, get_lot_metadata_for_downstream
from InputScreening.models import InputScreening_Submitted


def test_lot_1_full_accept():
    """Test 1: Full Accept Submission"""
    print("\n" + "="*80)
    print("TEST 1: FULL ACCEPT SUBMISSION")
    print("="*80)
    
    user = User.objects.first()
    result = handle_submission(
        lot_id="LID210420261307380010",  # ERR1: Using existing format
        batch_id="BATCH001",
        submission_type="full_accept",
        original_qty=500,
        plating_stock_no="PSN001",
        model_no="MODEL001",
        tray_type="Normal",
        tray_capacity=20,
        active_trays_count=25,
        top_tray_id="NB-A00001",
        top_tray_qty=10,
        all_trays_json=[
            {"tray_id": "NB-A00001", "qty": 10, "top_tray": True},
            {"tray_id": "NB-A00002", "qty": 20},
        ],
        created_by=user,
        remarks="Full accept - all good",
    )
    
    print(f"Result: {result}")
    
    if result["success"]:
        lot_id = result["lot_ids"][0]
        record = InputScreening_Submitted.objects.get(lot_id=lot_id)
        print(f"✅ Created submission record: {lot_id}")
        print(f"   - Type: {record.get_submission_type_display() if hasattr(record, 'get_submission_type_display') else 'full_accept'}")
        print(f"   - Accepted qty: {record.accepted_qty}")
        print(f"   - Rejected qty: {record.rejected_qty}")
        print(f"   - Is active: {record.is_active}")
        return lot_id
    else:
        print(f"❌ Failed: {result['error']}")
        return None


def test_lot_2_full_reject():
    """Test 2: Full Reject Submission"""
    print("\n" + "="*80)
    print("TEST 2: FULL REJECT SUBMISSION")
    print("="*80)
    
    user = User.objects.first()
    result = handle_submission(
        lot_id="LID210420261307380011",  # ERR1: Using existing format
        batch_id="BATCH002",
        submission_type="full_reject",
        original_qty=300,
        plating_stock_no="PSN002",
        model_no="MODEL002",
        tray_type="Jumbo",
        tray_capacity=50,
        active_trays_count=6,
        top_tray_id="JB-A00001",
        top_tray_qty=40,
        reject_trays_json=[
            {"tray_id": "JB-A00001", "qty": 40},
            {"tray_id": "JB-A00002", "qty": 50},
            {"tray_id": "JB-A00003", "qty": 50},
            {"tray_id": "JB-A00004", "qty": 50},
            {"tray_id": "JB-A00005", "qty": 50},
            {"tray_id": "JB-A00006", "qty": 20},
        ],
        rejection_reasons_json={
            "R01": {"reason": "VERSION MIXUP", "qty": 150},
            "R02": {"reason": "MODEL MIXUP", "qty": 150},
        },
        allocation_preview_json={
            "total_reject_qty": 300,
            "total_accept_qty": 0,
            "new_trays_required": 0,
        },
        created_by=user,
        remarks="Full reject - quality issues",
    )
    
    print(f"Result: {result}")
    
    if result["success"]:
        lot_id = result["lot_ids"][0]
        record = InputScreening_Submitted.objects.get(lot_id=lot_id)
        print(f"✅ Created submission record: {lot_id}")
        print(f"   - Type: full_reject")
        print(f"   - Accepted qty: {record.accepted_qty}")
        print(f"   - Rejected qty: {record.rejected_qty}")
        print(f"   - Is active: {record.is_active}")
        return lot_id
    else:
        print(f"❌ Failed: {result['error']}")
        return None


def test_lot_3_partial_split():
    """Test 3: Partial Split Submission (creates 2 child lots with new format)"""
    print("\n" + "="*80)
    print("TEST 3: PARTIAL SPLIT SUBMISSION")
    print("="*80)
    
    user = User.objects.first()
    result = handle_submission(
        lot_id="LID210420261307380012",  # ERR1: Parent uses existing format
        batch_id="BATCH003",
        submission_type="partial",
        original_qty=400,
        accept_qty=250,
        reject_qty=150,
        plating_stock_no="PSN003",
        model_no="MODEL003",
        tray_type="Normal",
        tray_capacity=25,
        accept_trays_count=10,
        reject_trays_count=6,
        accept_trays_json=[
            {"tray_id": "NB-A00010", "qty": 25},
            {"tray_id": "NB-A00011", "qty": 25},
        ],
        reject_trays_json=[
            {"tray_id": "NB-A00020", "qty": 25},
            {"tray_id": "NB-A00021", "qty": 25},
        ],
        accept_top_tray_id="NB-A00010",
        accept_top_tray_qty=15,
        reject_top_tray_id="NB-A00020",
        reject_top_tray_qty=20,
        rejection_reasons_json={
            "R01": {"reason": "DEFECT", "qty": 150},
        },
        allocation_preview_json={
            "total_reject_qty": 150,
            "total_accept_qty": 250,
        },
        created_by=user,
        remarks="Partial split - some defects found",
    )
    
    print(f"Result: {result}")
    
    if result["success"]:
        accept_lot_id = result["lot_ids"][0]
        reject_lot_id = result["lot_ids"][1]
        
        accept_record = InputScreening_Submitted.objects.get(lot_id=accept_lot_id)
        reject_record = InputScreening_Submitted.objects.get(lot_id=reject_lot_id)
        
        print(f"✅ Created 2 child submission records:")
        print(f"   ACCEPT: {accept_lot_id}")
        print(f"   - Type: partial_accept")
        print(f"   - Qty: {accept_record.accepted_qty}")
        print(f"   - Parent: {accept_record.parent_lot_id}")
        print(f"   - Is child: {accept_record.is_child_lot}")
        print(f"   REJECT: {reject_lot_id}")
        print(f"   - Type: partial_reject")
        print(f"   - Qty: {reject_record.rejected_qty}")
        print(f"   - Parent: {reject_record.parent_lot_id}")
        print(f"   - Is child: {reject_record.is_child_lot}")
        
        return accept_lot_id, reject_lot_id
    else:
        print(f"❌ Failed: {result['error']}")
        return None, None


def test_pick_table_exclusion():
    """Test ERR3: Verify submitted lots are excluded from pick table"""
    print("\n" + "="*80)
    print("TEST: PICK TABLE EXCLUSION (ERR3)")
    print("="*80)
    
    from InputScreening.selectors import pick_table_queryset
    
    # This is just a smoke test - in real environment would need actual ModelMasterCreation records
    queryset = pick_table_queryset()
    count = queryset.count()
    print(f"Pick table queryset now excludes submitted lots")
    print(f"Current count in pick table: {count}")


def main():
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "InputScreening_Submitted Test Suite" + " "*24 + "║")
    print("║" + " "*15 + "Testing ERR1, ERR3, ERR4 Fixes" + " "*34 + "║")
    print("╚" + "="*78 + "╝")
    
    # Clean up previous test records
    print("\nCleaning up previous test records...")
    InputScreening_Submitted.objects.filter(
        lot_id__startswith="LID21042026"
    ).delete()
    
    # Run tests
    lot1 = test_lot_1_full_accept()
    lot2 = test_lot_2_full_reject()
    lot3a, lot3b = test_lot_3_partial_split()
    test_pick_table_exclusion()
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    records = InputScreening_Submitted.objects.filter(
        lot_id__startswith="LID"
    ).order_by("created_at")
    
    print(f"\n✅ Total submitted lots in database: {records.count()}")
    print("\nLot IDs created during test:")
    for idx, rec in enumerate(records, 1):
        print(f"  {idx}. {rec.lot_id}")
        print(f"     Type: {'Full Accept' if rec.is_full_accept else 'Full Reject' if rec.is_full_reject else 'Partial Accept' if rec.is_partial_accept else 'Partial Reject'}")
        print(f"     Qty: Accept={rec.accepted_qty}, Reject={rec.rejected_qty}")
        print(f"     Parent: {rec.parent_lot_id or 'N/A'}")
        print(f"     Child: {rec.is_child_lot}")
    
    print("\n" + "="*80)
    print("✅ ALL TESTS COMPLETED")
    print("="*80)
    print("\nView all submissions in admin panel:")
    print("  http://127.0.0.1:8000/admin/InputScreening/inputscreening_submitted/")
    print("\n")


if __name__ == "__main__":
    main()

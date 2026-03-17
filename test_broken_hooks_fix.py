"""
Validation script for Broken Hooks Half-Filled Tray Fix
Tests the scenario: Model 1805SAA02, Lot 98, Jig Cap 98, Broken Hooks 5
"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')

import django
django.setup()

from django.utils import timezone
from datetime import datetime
from Jig_Loading.models import JigCompleted, JigLoadTrayId
from modelmasterapp.models import TotalStockModel

def validate_broken_hooks_fix():
    """Validate the broken hooks fix by checking the most recent JigCompleted submission."""
    
    print("\n" + "="*80)
    print("BROKEN HOOKS FIX VALIDATION")
    print("="*80)
    
    # Get the most recent JigCompleted record
    latest_jig = JigCompleted.objects.order_by('-id').first()
    
    if not latest_jig:
        print("❌ No JigCompleted records found")
        return False
    
    print(f"\n📋 Latest JigCompleted Record:")
    print(f"   Lot ID: {latest_jig.lot_id}")
    print(f"   Batch ID: {latest_jig.batch_id}")
    print(f"   Original Lot Qty: {latest_jig.original_lot_qty}")
    print(f"   Updated (Effective) Qty: {latest_jig.updated_lot_qty}")
    print(f"   Jig Capacity: {latest_jig.jig_capacity}")
    print(f"   Broken Hooks: {latest_jig.broken_hooks}")
    
    # Validation 1: Effective lot qty = original - broken_hooks
    expected_effective = latest_jig.original_lot_qty - latest_jig.broken_hooks
    validation_1 = latest_jig.updated_lot_qty == expected_effective
    print(f"\n✅ Validation 1: Effective Qty Calculation")
    print(f"   Expected: {latest_jig.original_lot_qty} - {latest_jig.broken_hooks} = {expected_effective}")
    print(f"   Actual: {latest_jig.updated_lot_qty}")
    print(f"   Result: {'✅ PASS' if validation_1 else '❌ FAIL'}")
    
    # Validation 2: Delink tray qty matches effective qty
    delink_qty = sum(t.get('cases', 0) for t in (latest_jig.delink_tray_info or []))
    validation_2 = delink_qty == expected_effective
    print(f"\n✅ Validation 2: Delink Tray Qty")
    print(f"   Expected: {expected_effective} cases")
    print(f"   Actual: {delink_qty} cases from {len(latest_jig.delink_tray_info or [])} trays")
    print(f"   Result: {'✅ PASS' if validation_2 else '❌ FAIL'}")
    
    # Validation 3: Partial lot created if broken_hooks > 0
    partial_lot_id = latest_jig.partial_lot_id
    validation_3 = False
    partial_stock = None
    if latest_jig.broken_hooks > 0:
        if partial_lot_id:
            partial_stock = TotalStockModel.objects.filter(lot_id=partial_lot_id).first()
            validation_3 = partial_stock is not None
            print(f"\n✅ Validation 3: Partial Lot Creation")
            print(f"   Broken Hooks: {latest_jig.broken_hooks}")
            if partial_stock:
                print(f"   New Lot ID: {partial_lot_id}")
                print(f"   New Stock Qty: {partial_stock.total_stock}")
                print(f"   Expected: {latest_jig.broken_hooks} cases")
                print(f"   Result: ✅ PASS")
            else:
                print(f"   New Lot ID: {partial_lot_id} (NOT FOUND)")
                print(f"   Result: ❌ FAIL - Partial lot not created")
        else:
            print(f"\n❌ Validation 3: Partial Lot ID Not Set")
            print(f"   Broken Hooks: {latest_jig.broken_hooks}")
            print(f"   Partial Lot ID: {partial_lot_id} (None)")
            print(f"   Result: ❌ FAIL")
    else:
        print(f"\n✅ Validation 3: No Broken Hooks - Skipped")
        print(f"   Broken Hooks: {latest_jig.broken_hooks}")
        validation_3 = True  # Pass if no broken hooks
    
    # Validation 4: Check JigLoadTrayId records split
    if partial_lot_id and partial_stock:
        original_trays = JigLoadTrayId.objects.filter(lot_id=latest_jig.lot_id)
        partial_trays = JigLoadTrayId.objects.filter(lot_id=partial_lot_id)
        
        original_qty = sum(t.tray_quantity for t in original_trays)
        partial_qty = sum(t.tray_quantity for t in partial_trays)
        
        validation_4 = (original_qty <= expected_effective and partial_qty > 0)
        
        print(f"\n✅ Validation 4: Tray Records Split")
        print(f"   Original Lot JigLoadTrayId:")
        print(f"      Count: {original_trays.count()}")
        print(f"      Total Qty: {original_qty}")
        print(f"   Partial Lot JigLoadTrayId:")
        print(f"      Count: {partial_trays.count()}")
        print(f"      Total Qty: {partial_qty}")
        print(f"   Result: {'✅ PASS' if validation_4 else '❌ FAIL'}")
    else:
        validation_4 = True  # Pass if no partial lot
    
    # Validation 5: No duplicate tray records
    if partial_lot_id:
        original_trays = set(t.tray_id for t in JigLoadTrayId.objects.filter(lot_id=latest_jig.lot_id))
        partial_trays = set(t.tray_id for t in JigLoadTrayId.objects.filter(lot_id=partial_lot_id))
        
        overlap = original_trays & partial_trays
        validation_5 = len(overlap) == 0
        
        print(f"\n✅ Validation 5: No Duplicate Trays")
        print(f"   Original Lot Tray IDs: {original_trays}")
        print(f"   Partial Lot Tray IDs: {partial_trays}")
        if overlap:
            print(f"   ❌ Overlap Found: {overlap}")
            print(f"   Result: ❌ FAIL")
        else:
            print(f"   Result: ✅ PASS - No overlap")
    else:
        validation_5 = True
    
    # Final Result
    all_pass = validation_1 and validation_2 and validation_3 and validation_4 and validation_5
    
    print("\n" + "="*80)
    print("FINAL RESULT")
    print("="*80)
    print(f"Validation 1 (Effective Qty): {'✅ PASS' if validation_1 else '❌ FAIL'}")
    print(f"Validation 2 (Delink Qty): {'✅ PASS' if validation_2 else '❌ FAIL'}")
    print(f"Validation 3 (Partial Lot): {'✅ PASS' if validation_3 else '❌ FAIL'}")
    print(f"Validation 4 (Tray Split): {'✅ PASS' if validation_4 else '❌ FAIL'}")
    print(f"Validation 5 (No Duplicates): {'✅ PASS' if validation_5 else '❌ FAIL'}")
    print("="*80)
    print(f"🎯 Overall: {'✅ ALL VALIDATIONS PASSED' if all_pass else '❌ SOME VALIDATIONS FAILED'}")
    print("="*80 + "\n")
    
    return all_pass

if __name__ == '__main__':
    result = validate_broken_hooks_fix()
    exit(0 if result else 1)

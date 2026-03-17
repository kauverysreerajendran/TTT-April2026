"""
TEST REPORT: Broken Hooks Leftover Qty Fix (Multiple Scenarios)
Date: March 17, 2026
"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')

import django
django.setup()

from django.utils import timezone
from Jig_Loading.models import JigCompleted, JigLoadTrayId
from modelmasterapp.models import TotalStockModel

def test_broken_hooks_fix_scenarios():
    """Test multiple broken hooks scenarios."""
    
    print("\n" + "="*80)
    print("BROKEN HOOKS LEFTOVER QTY FIX - TEST REPORT")
    print("="*80)
    
    # Get recent JigCompleted records
    recent_jigsCompleted = JigCompleted.objects.order_by('-id')[:3]
    
    test_results = []
    
    for idx, jig_record in enumerate(recent_jigsCompleted, 1):
        print(f"\n{'─'*80}")
        print(f"TEST CASE #{idx}")
        print(f"{'─'*80}")
        
        print(f"JigCompleted Record:")
        print(f"  Batch ID: {jig_record.batch_id}")
        print(f"  Primary Lot ID: {jig_record.lot_id}")
        print(f"  Model: {jig_record.plating_stock_num}")
        print(f"  Original Qty: {jig_record.original_lot_qty}")
        print(f"  Updated (Delink) Qty: {jig_record.updated_lot_qty}")
        print(f"  Jig Capacity: {jig_record.jig_capacity}")
        print(f"  Broken Hooks: {jig_record.broken_hooks}")
        print(f"  Partial Lot ID: {jig_record.partial_lot_id}")
        
        # Validation 1: Check if partial lot was created when broken_hooks > 0
        validation_1 = "❌ FAIL"
        if jig_record.broken_hooks > 0:
            if jig_record.partial_lot_id:
                partial_stock = TotalStockModel.objects.filter(lot_id=jig_record.partial_lot_id).first()
                if partial_stock:
                    partial_qty = partial_stock.total_stock
                    expected_partial = jig_record.broken_hooks
                    if partial_qty == expected_partial:
                        validation_1 = "✅ PASS"
                    else:
                        validation_1 = f"⚠️ QTY MISMATCH: expected {expected_partial}, got {partial_qty}"
                else:
                    validation_1 = "❌ FAIL - Partial lot not found"
            else:
                validation_1 = "❌ FAIL - No partial_lot_id set"
                
        print(f"\n✅ Test 1: Partial Lot Creation")
        print(f"   Result: {validation_1}")
        
        # Validation 2: Check delink qty
        validation_2 = "❌ FAIL"
        delink_qty = sum(t.get('cases', 0) for t in (jig_record.delink_tray_info or []))
        expected_delink = jig_record.updated_lot_qty
        if delink_qty == expected_delink:
            validation_2 = "✅ PASS"
        else:
            validation_2 = f"❌ MISMATCH: expected {expected_delink}, got {delink_qty}"
        print(f"\n✅ Test 2: Delink Qty Validation")
        print(f"   Expected: {expected_delink}")
        print(f"   Actual: {delink_qty}")
        print(f"   Result: {validation_2}")
        
        # Validation 3: Check if original stock updated correctly
        validation_3 = "❌ FAIL"
        primary_stock = TotalStockModel.objects.filter(lot_id=jig_record.lot_id).first()
        if primary_stock:
            if jig_record.broken_hooks > 0 and jig_record.partial_lot_id:
                # Primary stock should be marked completed if leftover was created
                if primary_stock.Jig_Load_completed or primary_stock.total_stock == 0:
                    validation_3 = "✅ PASS"
                else:
                    validation_3 = f"⚠️ Primary stock still has {primary_stock.total_stock} cases"
            else:
                validation_3 = "✅ PASS (No partial lot created)"
        print(f"\n✅ Test 3: Primary Stock Status")
        print(f"   Result: {validation_3}")
        
        #Validation 4: Tray records correctly split
        validation_4 = "❌ FAIL"
        if jig_record.partial_lot_id:
            primary_trays = set(t.tray_id for t in JigLoadTrayId.objects.filter(lot_id=jig_record.lot_id))
            partial_trays = set(t.tray_id for t in JigLoadTrayId.objects.filter(lot_id=jig_record.partial_lot_id))
            overlap = primary_trays & partial_trays
            if len(overlap) == 0:
                validation_4 = "✅ PASS - No tray duplication"
            else:
                validation_4 = f"❌ FAIL - Duplicate trays: {overlap}"
        else:
            validation_4 = "✅ PASS (No partial lot)"
        print(f"\n✅ Test 4: No Tray Duplication")
        print(f"   Result: {validation_4}")
        
        # Summary
        all_pass = all(
            test.startswith("✅") 
            for test in [validation_1, validation_2, validation_3, validation_4]
        )
        
        test_results.append({
            'case': idx,
            'model': jig_record.plating_stock_num,
            'all_pass': all_pass,
            'test_1': validation_1,
            'test_2': validation_2,
            'test_3': validation_3,
            'test_4': validation_4,
        })
    
    # Final Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    for result in test_results:
        status = "✅ PASS" if result['all_pass'] else "❌ FAIL"
        print(f"\nTest Case #{result['case']} ({result['model']}): {status}")
        print(f"  1. Partial Lot: {result['test_1']}")
        print(f"  2. Delink Qty: {result['test_2']}")
        print(f"  3. Stock Status: {result['test_3']}")
        print(f"  4. Tray Split: {result['test_4']}")
    
    all_test_pass = all(r['all_pass'] for r in test_results)
    print("\n" + "="*80)
    print(f"OVERALL RESULT: {'✅ ALL TESTS PASSED' if all_test_pass else '❌ SOME TESTS FAILED'}")
    print("="*80 + "\n")
    
    return all_test_pass

if __name__ == '__main__':
    result = test_broken_hooks_fix_scenarios()
    exit(0 if result else 1)

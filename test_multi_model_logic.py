#!/usr/bin/env python
"""Test multi-model allocation logic"""
import json

def simulate_multi_model_allocation():
    """Test the allocation logic with sample data"""
    
    # PRIMARY MODEL TRAYS
    primary_trays = [
        {'tray_id': 'JB-A00001', 'qty': 2},
        {'tray_id': 'JB-A00002', 'qty': 12},
        {'tray_id': 'JB-A00003', 'qty': 12},
        {'tray_id': 'JB-A00004', 'qty': 12},
        {'tray_id': 'JB-A00005', 'qty': 12},
    ]
    
    # SECONDARY MODEL TRAYS
    secondary_trays = [
        {'tray_id': 'JB-A00006', 'qty': 12},
        {'tray_id': 'JB-A00007', 'qty': 12},
        {'tray_id': 'JB-A00008', 'qty': 12},
        {'tray_id': 'JB-A00009', 'qty': 12},
    ]
    
    primary_lot_qty = 50
    secondary_lot_qty = 48
    effective_jig_capacity = 98
    
    used_tray_ids = set()
    multi_model_allocation = []
    
    # PRIMARY ALLOCATION
    primary_allocated = []
    primary_total = 0
    for tray in primary_trays:
        tray_id = tray['tray_id']
        tray_qty = tray['qty']
        
        if tray_id in used_tray_ids:
            continue
        
        if primary_total >= primary_lot_qty:
            break
        
        if primary_total + tray_qty <= primary_lot_qty:
            primary_allocated.append({'tray_id': tray_id, 'qty': tray_qty})
            used_tray_ids.add(tray_id)
            primary_total += tray_qty
        else:
            remaining = primary_lot_qty - primary_total
            primary_allocated.append({'tray_id': tray_id, 'qty': remaining})
            used_tray_ids.add(tray_id)
            primary_total += remaining
            break
    
    multi_model_allocation.append({
        'model': '1805NAR02',
        'lot_id': 'LOT001',
        'sequence': 0,
        'allocated_qty': primary_total,
        'tray_info': primary_allocated
    })
    
    # SECONDARY ALLOCATION
    secondary_allocated = []
    secondary_total = 0
    for tray in secondary_trays:
        tray_id = tray['tray_id']
        tray_qty = tray['qty']
        
        if tray_id in used_tray_ids:
            continue
        
        if secondary_total >= secondary_lot_qty:
            break
        
        if secondary_total + tray_qty <= secondary_lot_qty:
            secondary_allocated.append({'tray_id': tray_id, 'qty': tray_qty})
            used_tray_ids.add(tray_id)
            secondary_total += tray_qty
        else:
            remaining = secondary_lot_qty - secondary_total
            secondary_allocated.append({'tray_id': tray_id, 'qty': remaining})
            used_tray_ids.add(tray_id)
            secondary_total += remaining
            break
    
    multi_model_allocation.append({
        'model': '1805QBK02/GUN',
        'lot_id': 'LOT002',
        'sequence': 1,
        'allocated_qty': secondary_total,
        'tray_info': secondary_allocated
    })
    
    # VALIDATION
    all_tray_ids = []
    for model_alloc in multi_model_allocation:
        for tray in model_alloc['tray_info']:
            all_tray_ids.append(tray['tray_id'])
    
    print("✅ MULTI-MODEL ALLOCATION OUTPUT:")
    print(json.dumps(multi_model_allocation, indent=2))
    print(f"\n✅ TOTAL CAPACITY USED: {primary_total + secondary_total} / {effective_jig_capacity}")
    print(f"✅ PRIMARY MODEL: {primary_total} qty in {len(primary_allocated)} trays")
    print(f"✅ SECONDARY MODEL: {secondary_total} qty in {len(secondary_allocated)} trays")
    print(f"✅ TOTAL TRAYS: {len(all_tray_ids)}")
    print(f"✅ DUPLICATE TRAYS: {len(all_tray_ids) != len(set(all_tray_ids))}")
    
    print("\n📋 DELINK OUTPUT FORMAT (grouped by model):")
    for model_alloc in multi_model_allocation:
        print(f"\n{model_alloc['model']}:")
        for tray in model_alloc['tray_info']:
            print(f"  {model_alloc['model']}  {tray['tray_id']}  {tray['qty']}")
    
    print("\n" + "="*60)
    print("✅ VALIDATION CHECKS:")
    print("="*60)
    
    # Check 1: Primary model qty
    print(f"✓ Primary model total: {primary_total} (expected: 50) - {'PASS' if primary_total == 50 else 'FAIL'}")
    
    # Check 2: Secondary model qty
    print(f"✓ Secondary model total: {secondary_total} (expected: 48) - {'PASS' if secondary_total == 48 else 'FAIL'}")
    
    # Check 3: Total capacity
    total_used = primary_total + secondary_total
    print(f"✓ Total capacity used: {total_used} (expected: 98) - {'PASS' if total_used == 98 else 'FAIL'}")
    
    # Check 4: No duplicate trays
    has_duplicates = len(all_tray_ids) != len(set(all_tray_ids))
    print(f"✓ No duplicate trays: {not has_duplicates} - {'PASS' if not has_duplicates else 'FAIL'}")
    
    # Check 5: Primary trays (order preserved)
    primary_tray_ids = [t['tray_id'] for t in multi_model_allocation[0]['tray_info']]
    expected_primary = ['JB-A00001', 'JB-A00002', 'JB-A00003', 'JB-A00004', 'JB-A00005']
    primary_match = primary_tray_ids == expected_primary
    print(f"✓ Primary tray order preserved: {primary_match} - {'PASS' if primary_match else 'FAIL'}")
    
    # Check 6: Secondary trays (order preserved)
    secondary_tray_ids = [t['tray_id'] for t in multi_model_allocation[1]['tray_info']]
    expected_secondary = ['JB-A00006', 'JB-A00007', 'JB-A00008', 'JB-A00009']
    secondary_match = secondary_tray_ids == expected_secondary
    print(f"✓ Secondary tray order preserved: {secondary_match} - {'PASS' if secondary_match else 'FAIL'}")


if __name__ == "__main__":
    simulate_multi_model_allocation()

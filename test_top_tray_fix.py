"""Quick test: verify top_tray DB flag is preserved through compute_jig_loading."""
import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'watchcase_tracker.settings'
django.setup()
from Jig_Loading.views import compute_jig_loading

trays = [
    {'tray_id': 'JB-A00001', 'qty': 11, 'top_tray': True},   # DB top tray
    {'tray_id': 'JB-A00002', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00003', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00004', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00005', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00006', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00007', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00008', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00009', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00010', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00011', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00012', 'qty': 12, 'top_tray': False},
    {'tray_id': 'JB-A00013', 'qty': 12, 'top_tray': False},
]

# Test 1: No BH, jig_capacity=98
result = compute_jig_loading(trays, 98, 0, 12)
print('=== No BH, capacity=98 ===')
for t in result['delink_tray_info']:
    flags = []
    if t['top_tray']: flags.append('TOP_TRAY')
    if t['is_partial']: flags.append('PARTIAL')
    flag_str = ' [' + ', '.join(flags) + ']' if flags else ''
    print(f"  {t['tray_id']}: qty={t['qty']}, original={t['original_qty']}{flag_str}")
print(f"Tray count: {result['tray_count']}, Loaded: {result['loaded_cases_qty']}")
print()

# Test 2: BH=5, jig_capacity=98
result2 = compute_jig_loading(trays, 98, 5, 12)
print('=== BH=5, capacity=98 ===')
for t in result2['delink_tray_info']:
    flags = []
    if t['top_tray']: flags.append('TOP_TRAY')
    if t['is_partial']: flags.append('PARTIAL')
    flag_str = ' [' + ', '.join(flags) + ']' if flags else ''
    print(f"  {t['tray_id']}: qty={t['qty']}, original={t['original_qty']}{flag_str}")
print(f"Tray count: {result2['tray_count']}, Loaded: {result2['loaded_cases_qty']}")
print()

# Verify: JB-A00001 should always have top_tray=True
for test_name, res in [('No BH', result), ('BH=5', result2)]:
    a1 = next((t for t in res['delink_tray_info'] if t['tray_id'] == 'JB-A00001'), None)
    if a1:
        assert a1['top_tray'] == True, f"FAIL [{test_name}]: JB-A00001 top_tray should be True"
        print(f"PASS [{test_name}]: JB-A00001 correctly marked as top_tray")
    else:
        print(f"INFO [{test_name}]: JB-A00001 not in delink (capacity may not reach it)")

# Verify: last tray with reduced qty should be is_partial=True, top_tray=False
last_tray_no_bh = result['delink_tray_info'][-1]
if last_tray_no_bh['is_partial']:
    assert last_tray_no_bh['top_tray'] == False or last_tray_no_bh['tray_id'] == 'JB-A00001', \
        f"FAIL: Partial tray {last_tray_no_bh['tray_id']} should NOT be top_tray unless it's JB-A00001"
    print(f"PASS: Last partial tray {last_tray_no_bh['tray_id']} correctly NOT marked as top_tray")

print("\nAll tests passed!")

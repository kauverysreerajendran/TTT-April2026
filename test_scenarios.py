import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()
from IQF.views import auto_allocate_iqf_rejection

# ============================================================
# DELINK SCENARIO TESTS
#
# The IQF rejection flow has two phases:
#   STEP 2b  - Pre-delinks existing lot trays for every NEW
#              acceptance tray the user scans (qty-based).
#              available_trays fed to auto_allocate is ALREADY
#              reduced to exactly the rejection-bound trays.
#   auto_allocate_iqf_rejection - consumes all remaining
#              available trays for rejection; delink_trays = []
#
# Scenario | Lot trays    | Accept scan          | STEP-2b delinks      | Avail after 2b  | Reject | From auto_alloc
#    1      | [1,12,12]    | Reuse A02 (existing) | none                 | [A01=1, A03=12] | 13     | delinks=[]
#    2      | [1,12,12]    | New JB-A00200 (12)   | A05 (qty 12->0)      | [A04=1, A06=12] | 13     | delinks=[]
#    3      | [1,12,12]    | New A300(12)+A301(3) | A08(12), A09(3->9)   | [A07=1, A09=9]  | 10     | delinks=[]
#    4      | [1,12,12]    | New A200(2)+Reuse A02| A03 (2->10 remain)   | [A01=1, A03=10] | 11     | delinks=[]
#    5      | [1,12,12]    | New A200(12)+A201(2) | A02(12), A03(2->10)  | [A01=1, A03=10] | 11     | delinks=[]
# ============================================================

# --- Scenario 1: Reuse existing tray - no STEP-2b delink ---
# A02 reused for acceptance so excluded from available.
# Available: [A01=1, A03=12] = 13 total, reject=13 -> all consumed.
available_trays_1 = [
    {'tray_id': 'JB-A00001', 'tray_quantity': 1,  'tray_capacity': 12},
    {'tray_id': 'JB-A00003', 'tray_quantity': 12, 'tray_capacity': 12},
]
result_1 = auto_allocate_iqf_rejection('LOT1', 13, available_trays_1)
print('Scenario 1 (Reuse existing - 0 extra delinks expected from auto_alloc):')
print(f'  Delink trays: {result_1["delink_trays"]}')
print(f'  Expected    : []')
print(f'  Match: {result_1["delink_trays"] == []}')

# --- Scenario 2: 1 new acceptance tray -> STEP-2b delinks A05 ---
# STEP-2b delinks A05 (qty=12) to provide for JB-A00200.
# After STEP-2b: [A04=1, A06=12] = 13, reject=13 -> all consumed.
available_trays_2 = [
    {'tray_id': 'JB-A00004', 'tray_quantity': 1,  'tray_capacity': 12},
    {'tray_id': 'JB-A00006', 'tray_quantity': 12, 'tray_capacity': 12},
]
result_2 = auto_allocate_iqf_rejection('LOT2', 13, available_trays_2)
print('Scenario 2 (1 new acceptance tray - 0 extra delinks from auto_alloc):')
print(f'  Delink trays: {result_2["delink_trays"]}')
print(f'  Expected    : []')
print(f'  Match: {result_2["delink_trays"] == []}')

# --- Scenario 3: 2 new acceptance trays -> STEP-2b delinks A08 + partial A09 ---
# New trays qty=15 total (A300=12 + A301=3).
# STEP-2b: delink A08(12 full), delink A09(3 of 12) -> A09.qty=9.
# After STEP-2b: [A07=1, A09=9] = 10, reject=10 -> all consumed.
available_trays_3 = [
    {'tray_id': 'JB-A00007', 'tray_quantity': 1, 'tray_capacity': 12},
    {'tray_id': 'JB-A00009', 'tray_quantity': 9, 'tray_capacity': 12},
]
result_3 = auto_allocate_iqf_rejection('LOT3', 10, available_trays_3)
print('Scenario 3 (2 new acceptance trays - 0 extra delinks from auto_alloc):')
print(f'  Delink trays: {result_3["delink_trays"]}')
print(f'  Expected    : []')
print(f'  Match: {result_3["delink_trays"] == []}')

# --- Scenario 4: 1 new + 1 reuse -> STEP-2b partial-delinks A03 ---
# New JB-A00200 qty=2; reuse A02 (excluded from available).
# STEP-2b: delink 2 from A03 -> A03.qty=10.
# After STEP-2b: [A01=1, A03=10] = 11, reject=11 -> all consumed.
available_trays_4 = [
    {'tray_id': 'JB-A00001', 'tray_quantity': 1,  'tray_capacity': 12},
    {'tray_id': 'JB-A00003', 'tray_quantity': 10, 'tray_capacity': 12},
]
result_4 = auto_allocate_iqf_rejection('LOT4', 11, available_trays_4)
print('Scenario 4 (1 new + 1 reuse - 0 extra delinks from auto_alloc):')
print(f'  Delink trays: {result_4["delink_trays"]}')
print(f'  Expected    : []')
print(f'  Match: {result_4["delink_trays"] == []}')

# --- Scenario 5: 2 new acceptance trays -> STEP-2b delinks A02 + partial A03 ---
# New A200 qty=12, new A201 qty=2; total_new=14.
# STEP-2b: delink A02(12 full) -> remaining=2; delink A03(2 of 12) -> A03.qty=10.
# After STEP-2b: [A01=1, A03=10] = 11, reject=11 -> all consumed.
available_trays_5 = [
    {'tray_id': 'JB-A00001', 'tray_quantity': 1,  'tray_capacity': 12},
    {'tray_id': 'JB-A00003', 'tray_quantity': 10, 'tray_capacity': 12},
]
result_5 = auto_allocate_iqf_rejection('LOT5', 11, available_trays_5)
print('Scenario 5 (2 new acceptance trays - 0 extra delinks from auto_alloc):')
print(f'  Delink trays: {result_5["delink_trays"]}')
print(f'  Expected    : []')
print(f'  Match: {result_5["delink_trays"] == []}')

all_pass = all([
    result_1["delink_trays"] == [],
    result_2["delink_trays"] == [],
    result_3["delink_trays"] == [],
    result_4["delink_trays"] == [],
    result_5["delink_trays"] == [],
])
print(f'\n{"ALL SCENARIOS PASS" if all_pass else "SOME SCENARIOS FAIL"}')

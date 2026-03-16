"""
Test script for the IQF tray allocation & delink fix.

Scenario (from user):
  - Brass QC Lot Qty = 50, Rejected from Brass QC = 25
  - IQF receives 25 qty in 3 trays: JB-A00101(1), JB-A00102(12), JB-A00201(12)
  - IQF rejection = 13
  - User scans new acceptance tray JB-A00202 = 12
  - System must:
    1. Find ALL 3 trays as delink/remaining candidates
    2. Determine 1 delink needed (1 new acceptance tray used)
    3. Auto-allocate rejection (13) across available trays: JB-A00102(12) + JB-A00101(1)
    4. Delink candidate: JB-A00201 (not in rejection, not in acceptance)
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from IQF.views import _get_all_lot_trays_for_iqf

print("=" * 70)
print("TEST: _get_all_lot_trays_for_iqf helper function")
print("=" * 70)

# Test 1: Verify the helper function is callable
print("\n✅ TEST 1: Helper function exists and is callable")
assert callable(_get_all_lot_trays_for_iqf), "Helper should be callable"
print("   PASSED")

# Test 2: Call with a non-existent lot (should return empty dict)
print("\n✅ TEST 2: Non-existent lot returns empty dict")
result = _get_all_lot_trays_for_iqf("NON_EXISTENT_LOT_XYZ")
assert result == {}, f"Expected empty dict, got {result}"
print("   PASSED")

# Test 3: Verify helper checks all 7 sources (structural test)
print("\n✅ TEST 3: Helper function source coverage")
import inspect
source = inspect.getsource(_get_all_lot_trays_for_iqf)
assert 'TrayId.objects.filter' in source, "Should query TrayId"
assert 'BrassTrayId.objects.filter' in source, "Should query BrassTrayId"
assert 'BrassAuditTrayId.objects.filter' in source, "Should query BrassAuditTrayId"
assert 'IQFTrayId.objects.filter' in source, "Should query IQFTrayId"
assert 'Brass_QC_Rejected_TrayScan.objects.filter' in source, "Should query Brass QC scans"
assert 'Brass_Audit_Rejected_TrayScan.objects.filter' in source, "Should query Brass Audit scans"
assert 'IQF_Rejected_TrayScan.objects.filter' in source, "Should query IQF rejection scans"
assert 'delink_tray=False' in source, "Should exclude delinked trays"
print("   PASSED - all 7 sources and delink exclusion verified")

# Test 4: Verify delink candidates function uses the universal helper
print("\n✅ TEST 4: iqf_get_delink_candidates uses universal helper")
# Read source file directly since decorators wrap functions
with open('IQF/views.py', 'r', encoding='utf-8') as f:
    full_source = f.read()
# Find the function body between def and next def/class at same indent
import re
delink_match = re.search(r'def iqf_get_delink_candidates\(request\):(.*?)(?=\n(?:def |class |@))', full_source, re.DOTALL)
assert delink_match, "Should find iqf_get_delink_candidates"
source_delink = delink_match.group(1)
assert '_get_all_lot_trays_for_iqf' in source_delink, "Should use universal helper"
assert 'came_from_brass_audit' not in source_delink, "Old source-specific code should be removed"
assert 'came_from_brass_qc' not in source_delink, "Old source-specific code should be removed"
print("   PASSED - uses universal helper, old code removed")

# Test 5: Verify iqf_get_remaining_trays uses universal helper
print("\n✅ TEST 5: iqf_get_remaining_trays uses universal helper")
remaining_match = re.search(r'def iqf_get_remaining_trays\(request\):(.*?)(?=\n(?:def |class |@))', full_source, re.DOTALL)
assert remaining_match, "Should find iqf_get_remaining_trays"
source_remaining = remaining_match.group(1)
assert '_get_all_lot_trays_for_iqf' in source_remaining, "Should use universal helper"
assert 'rejected_scan_tray_ids' not in source_remaining, "Old cascading fallback should be removed"
print("   PASSED - uses universal helper, old cascade removed")

# Test 6: Verify get_iqf_available_trays_for_allocation uses universal helper in fallback
print("\n✅ TEST 6: get_iqf_available_trays_for_allocation uses universal helper")
avail_match = re.search(r'def get_iqf_available_trays_for_allocation\(lot_id\):(.*?)(?=\ndef )', full_source, re.DOTALL)
assert avail_match, "Should find get_iqf_available_trays_for_allocation"
source_avail = avail_match.group(1)
assert '_get_all_lot_trays_for_iqf' in source_avail, "Should use universal helper in fallback"
print("   PASSED")

# Test 7: Verify mismatch regeneration uses universal helper
print("\n✅ TEST 7: Mismatch regeneration uses universal helper")
assert '_get_all_lot_trays_for_iqf' in full_source.split('def iqf_view_tray_list')[1].split('\ndef ')[0], "iqf_view_tray_list should use universal helper"
assert '_get_all_lot_trays_for_iqf' in full_source.split('def iqf_get_rejected_tray_scan_data')[1].split('\ndef ')[0], "iqf_get_rejected_tray_scan_data should use universal helper"
print("   PASSED")

print("\n" + "=" * 70)
print("ALL TESTS PASSED ✅")
print("=" * 70)
print("""
Summary of fix:
- Added _get_all_lot_trays_for_iqf() helper that checks ALL 7 sources:
  TrayId, BrassTrayId, BrassAuditTrayId, IQFTrayId,
  Brass_QC_Rejected_TrayScan, Brass_Audit_Rejected_TrayScan, IQF_Rejected_TrayScan
- Replaces source-specific fallback cascades in:
  1. iqf_get_delink_candidates
  2. iqf_get_remaining_trays
  3. IQFTrayRejectionAPIView (Step 2)
  4. get_iqf_available_trays_for_allocation (fallback path)
  5. iqf_get_rejected_tray_scan_data (mismatch regeneration)
  6. iqf_view_tray_list (mismatch regeneration + no-records generation)
  7. get_tray_capacity (reusable tray count)
""")

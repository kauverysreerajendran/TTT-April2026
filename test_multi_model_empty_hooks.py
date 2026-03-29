"""
Test Report: Multi-Model Empty Hooks Cumulative Calculation
============================================================
Tests the InitJigLoad endpoint for correct empty_hooks computation
when N models are added (no limit on model count).

Endpoint: GET /jig_loading/init-jig-load/
"""
import os
import sys
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from Jig_Loading.views import InitJigLoad
from Jig_Loading.models import JigLoadTrayId, JigLoadingManualDraft
from modelmasterapp.models import TotalStockModel, ModelMasterCreation, ModelMaster, TrayType, Version

PASS = "\u2705 PASS"
FAIL = "\u274c FAIL"


def setup_test_data():
    """Create minimal DB fixtures for testing."""
    user, _ = User.objects.get_or_create(username='test_mm_user', defaults={'password': 'test'})
    user.set_password('test')
    user.save()

    # Tray type and version (required FK)
    tray_type, _ = TrayType.objects.get_or_create(tray_type='TestTray', defaults={'tray_capacity': 12})
    version, _ = Version.objects.get_or_create(version_name='V1', defaults={'version_internal': 'v1'})

    # Model master (for FK)
    mm, _ = ModelMaster.objects.get_or_create(
        model_no='TEST-MM-001',
        defaults={
            'ep_bath_type': 'Bright',
            'tray_type': tray_type,
            'tray_capacity': 12,
            'version': 'V1',
            'plating_stk_no': 'PSN-001',
        }
    )

    # Helper to create a lot
    def create_lot(lot_id, batch_id, qty, tray_capacity=12):
        mmc, created = ModelMasterCreation.objects.get_or_create(
            batch_id=batch_id,
            defaults={
                'lot_id': lot_id,
                'model_stock_no': mm,
                'polish_finish': 'Mirror',
                'ep_bath_type': 'Bright',
                'plating_color': 'Gold',
                'tray_type': str(tray_type),
                'tray_capacity': tray_capacity,
                'version': version,
                'total_batch_quantity': qty,
            }
        )
        tsm, _ = TotalStockModel.objects.get_or_create(
            lot_id=lot_id,
            defaults={
                'batch_id': mmc,
                'model_stock_no': mm,
                'version': version,
                'total_stock': qty,
                'brass_audit_accepted_qty': qty,
            }
        )
        # Create tray records
        JigLoadTrayId.objects.filter(lot_id=lot_id).delete()
        remaining = qty
        counter = 1
        while remaining > 0:
            tray_qty = min(tray_capacity, remaining)
            JigLoadTrayId.objects.create(
                lot_id=lot_id,
                tray_id=f'{lot_id}-T{str(counter).zfill(3)}',
                tray_quantity=tray_qty,
                batch_id=mmc,
            )
            remaining -= tray_qty
            counter += 1
        return mmc

    # Create test lots
    create_lot('LOT-PRI-50', 'BATCH-PRI-50', 50)
    create_lot('LOT-SEC-35', 'BATCH-SEC-35', 35)
    create_lot('LOT-SEC-10', 'BATCH-SEC-10', 10)
    create_lot('LOT-SEC-20', 'BATCH-SEC-20', 20)
    create_lot('LOT-SEC-05', 'BATCH-SEC-05', 5)
    create_lot('LOT-FULL-98', 'BATCH-FULL-98', 98)
    create_lot('LOT-SMALL-3', 'BATCH-SMALL-3', 3)

    # Clean up any drafts from previous test runs
    JigLoadingManualDraft.objects.filter(lot_id__startswith='LOT-').delete()

    return user


def make_request(user, params):
    """Build a GET request to InitJigLoad."""
    factory = RequestFactory()
    qs = '&'.join(f'{k}={v}' for k, v in params.items())
    request = factory.get(f'/jig_loading/init-jig-load/?{qs}')
    request.user = user
    view = InitJigLoad.as_view()
    response = view(request)
    return response


def run_tests():
    user = setup_test_data()
    results = []
    jig_capacity = 98

    # =========================================================
    # TEST 1: Single model — correct empty hooks
    # =========================================================
    print("\n--- TEST 1: Single model (lot=50, cap=98) ---")
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    expected = 48  # 98 - 50
    status = PASS if empty == expected else FAIL
    print(f"  empty_hooks={empty}, expected={expected} {status}")
    results.append(('T1: Single model', empty == expected, f"empty_hooks={empty}, expected={expected}"))

    # =========================================================
    # TEST 2: Two models — cumulative empty hooks
    # Primary=50, Secondary=35 → total=85 → empty=13
    # =========================================================
    print("\n--- TEST 2: Two models (50+35=85, cap=98) ---")
    sec_lots = json.dumps([{'lot_id': 'LOT-SEC-35', 'batch_id': 'BATCH-SEC-35', 'qty': 35}])
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': sec_lots,
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    total_mm = data.get('total_multi_model_qty', -1)
    expected_total = 85
    expected_empty = 13  # 98 - 85
    s1 = PASS if total_mm == expected_total else FAIL
    s2 = PASS if empty == expected_empty else FAIL
    print(f"  total_multi_model_qty={total_mm}, expected={expected_total} {s1}")
    print(f"  empty_hooks={empty}, expected={expected_empty} {s2}")
    results.append(('T2: Two models total', total_mm == expected_total, f"total={total_mm}, expected={expected_total}"))
    results.append(('T2: Two models empty', empty == expected_empty, f"empty={empty}, expected={expected_empty}"))

    # =========================================================
    # TEST 3: Three models — Primary=50, Sec1=35, Sec2=10
    # total=95, empty=3
    # =========================================================
    print("\n--- TEST 3: Three models (50+35+10=95, cap=98) ---")
    sec_lots = json.dumps([
        {'lot_id': 'LOT-SEC-35', 'batch_id': 'BATCH-SEC-35', 'qty': 35},
        {'lot_id': 'LOT-SEC-10', 'batch_id': 'BATCH-SEC-10', 'qty': 10},
    ])
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': sec_lots,
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    total_mm = data.get('total_multi_model_qty', -1)
    expected_total = 95
    expected_empty = 3
    s1 = PASS if total_mm == expected_total else FAIL
    s2 = PASS if empty == expected_empty else FAIL
    print(f"  total_multi_model_qty={total_mm}, expected={expected_total} {s1}")
    print(f"  empty_hooks={empty}, expected={expected_empty} {s2}")
    results.append(('T3: Three models total', total_mm == expected_total, f"total={total_mm}, expected={expected_total}"))
    results.append(('T3: Three models empty', empty == expected_empty, f"empty={empty}, expected={expected_empty}"))

    # =========================================================
    # TEST 4: Four models — total exceeds jig capacity
    # 50+35+10+20=115, capped by jig at 98 → empty=0
    # =========================================================
    print("\n--- TEST 4: Four models, total exceeds capacity (50+35+10+20, cap=98) ---")
    sec_lots = json.dumps([
        {'lot_id': 'LOT-SEC-35', 'batch_id': 'BATCH-SEC-35', 'qty': 35},
        {'lot_id': 'LOT-SEC-10', 'batch_id': 'BATCH-SEC-10', 'qty': 10},
        {'lot_id': 'LOT-SEC-20', 'batch_id': 'BATCH-SEC-20', 'qty': 20},
    ])
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': sec_lots,
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    total_mm = data.get('total_multi_model_qty', -1)
    # Backend caps allocation to capacity, so total_mm <= 98
    s_empty = PASS if empty == 0 else FAIL
    print(f"  total_multi_model_qty={total_mm} (capped by allocation)")
    print(f"  empty_hooks={empty}, expected=0 {s_empty}")
    results.append(('T4: Exceeds capacity empty=0', empty == 0, f"empty={empty}"))

    # =========================================================
    # TEST 5: Five models — arbitrary count, no limit
    # =========================================================
    print("\n--- TEST 5: Five models (50+35+10+3+0, cap=98) ---")
    sec_lots = json.dumps([
        {'lot_id': 'LOT-SEC-35', 'batch_id': 'BATCH-SEC-35', 'qty': 35},
        {'lot_id': 'LOT-SEC-10', 'batch_id': 'BATCH-SEC-10', 'qty': 10},
        {'lot_id': 'LOT-SMALL-3', 'batch_id': 'BATCH-SMALL-3', 'qty': 3},
        {'lot_id': 'LOT-SEC-05', 'batch_id': 'BATCH-SEC-05', 'qty': 0},  # zero qty model
    ])
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': sec_lots,
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    total_mm = data.get('total_multi_model_qty', -1)
    # 50+35+10+3+0 = 98 → empty = 0
    expected_empty = 0
    s_empty = PASS if empty == expected_empty else FAIL
    print(f"  total_multi_model_qty={total_mm}")
    print(f"  empty_hooks={empty}, expected={expected_empty} {s_empty}")
    print(f"  model_count={len(data.get('multi_model_allocation', []))}")
    results.append(('T5: Five models', empty == expected_empty, f"empty={empty}, total={total_mm}"))

    # =========================================================
    # TEST 6: Zero secondary models → falls back to single model
    # =========================================================
    print("\n--- TEST 6: Multi-model flag but empty secondary list ---")
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': json.dumps([]),
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    expected = 48  # Same as single model
    status = PASS if empty == expected else FAIL
    print(f"  empty_hooks={empty}, expected={expected} {status}")
    results.append(('T6: Empty secondary list', empty == expected, f"empty={empty}"))

    # =========================================================
    # TEST 7: Broken hooks + multi-model
    # cap=98, broken=10 → effective=88, primary=50, sec=35 → total=85 → empty=3
    # =========================================================
    print("\n--- TEST 7: Broken hooks + multi-model (cap=98, broken=10, 50+35=85) ---")
    sec_lots = json.dumps([{'lot_id': 'LOT-SEC-35', 'batch_id': 'BATCH-SEC-35', 'qty': 35}])
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': sec_lots,
        'broken_hooks': 10,
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    eff_cap = data.get('effective_capacity', -1)
    total_mm = data.get('total_multi_model_qty', -1)
    # effective=88, allocated total should be <=88
    # Primary gets 50, secondary gets min(35, 88-50)=min(35,38)=35 → total=85
    # empty = 88 - 85 = 3
    expected_empty = 3
    s_empty = PASS if empty == expected_empty else FAIL
    print(f"  effective_capacity={eff_cap}, total_mm={total_mm}")
    print(f"  empty_hooks={empty}, expected={expected_empty} {s_empty}")
    results.append(('T7: Broken hooks + multi', empty == expected_empty, f"empty={empty}, eff={eff_cap}, total={total_mm}"))

    # =========================================================
    # TEST 8: Exact fit — total equals capacity → empty=0
    # =========================================================
    print("\n--- TEST 8: Exact fit (lot=98, cap=98, no multi) ---")
    resp = make_request(user, {
        'lot_id': 'LOT-FULL-98',
        'batch_id': 'BATCH-FULL-98',
        'jig_capacity': 98,
    })
    data = resp.data
    empty = data.get('empty_hooks', -1)
    expected = 0
    status = PASS if empty == expected else FAIL
    print(f"  empty_hooks={empty}, expected={expected} {status}")
    results.append(('T8: Exact fit single', empty == expected, f"empty={empty}"))

    # =========================================================
    # TEST 9: Verify no duplicate trays across models
    # =========================================================
    print("\n--- TEST 9: No duplicate trays across models ---")
    sec_lots = json.dumps([
        {'lot_id': 'LOT-SEC-35', 'batch_id': 'BATCH-SEC-35', 'qty': 35},
        {'lot_id': 'LOT-SEC-10', 'batch_id': 'BATCH-SEC-10', 'qty': 10},
    ])
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': sec_lots,
    })
    data = resp.data
    all_trays = []
    for m in data.get('multi_model_allocation', []):
        for t in m.get('tray_info', []):
            all_trays.append(t.get('tray_id'))
    unique_trays = set(all_trays)
    no_dupes = len(all_trays) == len(unique_trays)
    status = PASS if no_dupes else FAIL
    print(f"  total_trays={len(all_trays)}, unique={len(unique_trays)} {status}")
    results.append(('T9: No duplicate trays', no_dupes, f"total={len(all_trays)}, unique={len(unique_trays)}"))

    # =========================================================
    # TEST 10: Response structure completeness
    # =========================================================
    print("\n--- TEST 10: Response structure validation ---")
    required_keys = [
        'empty_hooks', 'total_multi_model_qty', 'effective_capacity',
        'loaded_cases_qty', 'broken_hooks', 'multi_model_allocation',
        'is_multi_model', 'secondary_lots',
    ]
    sec_lots = json.dumps([{'lot_id': 'LOT-SEC-35', 'batch_id': 'BATCH-SEC-35', 'qty': 35}])
    resp = make_request(user, {
        'lot_id': 'LOT-PRI-50',
        'batch_id': 'BATCH-PRI-50',
        'jig_capacity': jig_capacity,
        'multi_model': 'true',
        'secondary_lots': sec_lots,
    })
    data = resp.data
    missing = [k for k in required_keys if k not in data]
    status = PASS if not missing else FAIL
    print(f"  Missing keys: {missing or 'None'} {status}")
    results.append(('T10: Response keys', not missing, f"missing={missing}"))

    # =========================================================
    # SUMMARY
    # =========================================================
    print("\n" + "=" * 60)
    print("TEST REPORT SUMMARY")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    for name, ok, detail in results:
        icon = PASS if ok else FAIL
        print(f"  {icon} {name}: {detail}")
    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")
    print("=" * 60)
    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

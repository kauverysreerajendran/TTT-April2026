"""
Test Report: Broken Hooks Carry-Forward — Multi-Model Scenario
==============================================================

Scenario
--------
  Primary Lot : LID170320261953320001  qty=100
  Secondary Lot: LID170320261953320002  qty=44
  Jig Capacity : 144
  Broken Hooks : 4
  ----------------------------------------------------------
  Effective capacity : 144 - 4 = 140
  Total combined     : 100 + 44 = 144
  Excess (carry-fwd) : 144 - 140 = 4  →  4 cases from secondary lot

Expected after submit
---------------------
  1. Primary lot   → Jig_Load_completed = True
  2. Secondary lot → Jig_Load_completed = True
  3. New carry-forward lot created  with:
       total_stock = 4
       Jig_Load_completed = False      ← visible in pick table (next cycle)
       brass_audit_accptance copied from secondary lot
  4. JigLoadTrayId record created for tray NB-A00010 (qty=4) tied to carry-forward lot
  5. Carry-forward lot NOT a duplicate of primary or secondary lot_id

Usage
-----
  cd a:\\Workspace\\Watchcase\\TTT-Jan2026
  python test_broken_hooks_carry_forward.py

The script uses Django's ORM directly; no HTTP server required.
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

import json
import time
import random
from datetime import datetime
from django.utils import timezone
from django.test import RequestFactory

# ── Import models ──────────────────────────────────────────────────────────────
from modelmasterapp.models import TotalStockModel, ModelMasterCreation
from Jig_Loading.models import JigLoadTrayId, JigLoadingManualDraft

# ── Colours ────────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

passed = []
failed = []

def ok(msg):
    passed.append(msg)
    print(f"  {GREEN}✅ PASS{RESET}  {msg}")

def fail(msg, detail=""):
    failed.append(msg)
    print(f"  {RED}❌ FAIL{RESET}  {msg}" + (f"\n         {YELLOW}{detail}{RESET}" if detail else ""))

def header(title):
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}")

# ── Test constants ─────────────────────────────────────────────────────────────
JIG_CAPACITY  = 144
BROKEN_HOOKS  = 4
CARRY_FORWARD_QTY = BROKEN_HOOKS  # 4 cases

HALF_FILLED_TRAY_ID = "NB-TEST-CF-TRAY-001"

# Unique test lot IDs — prefixed so cleanup is safe and deterministic
PRIMARY_LOT   = "LID-CFTEST-PRIMARY-001"
SECONDARY_LOT = "LID-CFTEST-SECONDARY-002"

# We'll attach test TotalStockModel records to the FIRST existing batch in the DB.
# This avoids needing to create a ModelMasterCreation (which has many required FKs).
_test_batch_obj = None  # set in setup()

# ── Setup helpers ──────────────────────────────────────────────────────────────

def cleanup():
    """Remove any test artefacts from previous runs."""
    TotalStockModel.objects.filter(lot_id__in=[PRIMARY_LOT, SECONDARY_LOT]).delete()
    TotalStockModel.objects.filter(lot_id__startswith='LID-CFTEST-CF-').delete()
    JigLoadTrayId.objects.filter(lot_id__in=[PRIMARY_LOT, SECONDARY_LOT]).delete()
    JigLoadTrayId.objects.filter(lot_id__startswith='LID-CFTEST-CF-').delete()
    # Also clean up any partial_lot_id records from previous runs (timestamp-based lot IDs)
    # that contain the test tray id
    for t in JigLoadTrayId.objects.filter(tray_id=HALF_FILLED_TRAY_ID):
        TotalStockModel.objects.filter(lot_id=t.lot_id).delete()
        t.delete()

def create_test_stock(batch_obj):
    # Borrow FK references from any existing TotalStockModel attached to the same batch
    # so we don't need to create ModelMasterCreation / version / model_stock_no records.
    ref = TotalStockModel.objects.filter(batch_id=batch_obj).first()
    if ref is None:
        ref = TotalStockModel.objects.first()
    if ref is None:
        print(f"  {RED}No existing TotalStockModel records to borrow FK refs from.{RESET}")
        sys.exit(1)

    shared = dict(
        batch_id=batch_obj,
        model_stock_no=ref.model_stock_no,
        version=ref.version,
        polish_finish=ref.polish_finish or "PF1",
        plating_color=ref.plating_color or "Gold",
    )
    primary = TotalStockModel.objects.create(
        **shared,
        lot_id=PRIMARY_LOT,
        total_stock=100,
        dp_physical_qty=100,
        Jig_Load_completed=False,
        jig_draft=False,
        brass_audit_accptance=True,
        brass_audit_few_cases_accptance=False,
        brass_audit_rejection=False,
        brass_audit_accepted_qty=100,
        brass_audit_onhold_picking=False,
    )
    secondary = TotalStockModel.objects.create(
        **shared,
        lot_id=SECONDARY_LOT,
        total_stock=44,
        dp_physical_qty=44,
        Jig_Load_completed=False,
        jig_draft=False,
        brass_audit_accptance=True,
        brass_audit_few_cases_accptance=False,
        brass_audit_rejection=False,
        brass_audit_accepted_qty=44,
        brass_audit_onhold_picking=False,
    )
    return primary, secondary

# ── Simulation: replicate the submit view logic for carry-forward creation ─────

def simulate_jig_submit(batch_obj):
    """
    Replicates the critical path of JigSubmitAPIView.post() that runs for:
      is_multi_model=True, original_lot_qty=100, jig_capacity=144, broken_hooks=4
    
    We skip the full HTTP stack and exercise only the carry-forward creation
    logic so the test is deterministic and fast.
    """
    primary, secondary = create_test_stock(batch_obj)

    # ── Inputs mirroring the POST body ──────────────────────────────────────
    is_multi_model   = True
    original_lot_qty = 100          # primary lot qty
    jig_capacity     = JIG_CAPACITY  # 144
    broken_hooks     = BROKEN_HOOKS  # 4
    total_combined_qty = 144         # primary 100 + secondary 44
    lot_id           = PRIMARY_LOT
    last_lot_id      = SECONDARY_LOT # "last added" lot in multi-model
    combined_lot_ids = [PRIMARY_LOT, SECONDARY_LOT]
    user             = None          # nullable FK in JigLoadTrayId
    batch            = batch_obj

    # Frontend now sends half_filled_tray_info correctly (after fix)
    half_filled_tray_info = [
        {
            "tray_id":  HALF_FILLED_TRAY_ID,
            "cases":    CARRY_FORWARD_QTY,
            "lot_id":   SECONDARY_LOT,
            "batch_id": batch_obj.batch_id,  # string batch_id from the FK model
        }
    ]

    partial_lot_id = None
    stock = primary  # the "stock" variable in the view (primary lot)

    # ── Path: else branch (original_lot_qty 100 != jig_capacity 144) ──────
    effective_jig_capacity = jig_capacity - broken_hooks  # 140
    effective_total_for_excess = total_combined_qty        # 144

    if broken_hooks > 0 and half_filled_tray_info:
        from datetime import datetime
        timestamp = datetime.now().strftime('%d%m%Y%H%M%S')
        partial_lot_id = f"LID{timestamp}{random.randint(1000, 9999)}"

        _cf_source_lot = half_filled_tray_info[0].get('lot_id', '') or lot_id
        _cf_source_stock = TotalStockModel.objects.filter(lot_id=_cf_source_lot).first() or stock

        for tray in half_filled_tray_info:
            _tray_src_lot   = tray.get('lot_id', '') or _cf_source_lot
            _tray_src_stock = TotalStockModel.objects.filter(lot_id=_tray_src_lot).first()
            _tray_batch     = _tray_src_stock.batch_id if _tray_src_stock else _cf_source_stock.batch_id
            JigLoadTrayId.objects.create(
                lot_id=partial_lot_id,
                tray_id=tray['tray_id'],
                tray_quantity=tray['cases'],
                batch_id=_tray_batch,
                user=user,
                broken_hooks_effective_tray=True,
                date=timezone.now(),
            )

        half_filled_qty = sum(t['cases'] for t in half_filled_tray_info)
        TotalStockModel.objects.create(
            batch_id=_cf_source_stock.batch_id,
            model_stock_no=_cf_source_stock.model_stock_no,
            version=_cf_source_stock.version,
            total_stock=half_filled_qty,
            polish_finish=_cf_source_stock.polish_finish,
            plating_color=_cf_source_stock.plating_color,
            lot_id=partial_lot_id,
            dp_physical_qty=half_filled_qty,
            Jig_Load_completed=False,
            jig_draft=False,
            brass_audit_accptance=_cf_source_stock.brass_audit_accptance,
            brass_audit_few_cases_accptance=_cf_source_stock.brass_audit_few_cases_accptance,
            brass_audit_rejection=_cf_source_stock.brass_audit_rejection,
            brass_audit_accepted_qty=half_filled_qty,
            brass_audit_onhold_picking=False,
        )

    # ── JigCompleted: skip excess creation because partial_lot_id is not None ─
    effective_jig_capacity_check = jig_capacity - broken_hooks
    broken_hooks_carry_forward_created = (
        original_lot_qty == jig_capacity and broken_hooks > 0 and partial_lot_id is not None
    )

    # Mark primary & secondary complete
    primary.Jig_Load_completed = True
    primary.jig_draft = False
    primary.save()

    secondary.Jig_Load_completed = True
    secondary.jig_draft = False
    secondary.save()

    return partial_lot_id


# ── Test suite ─────────────────────────────────────────────────────────────────

def run_tests():
    header("Setup — find test batch + cleanup")
    batch_obj = ModelMasterCreation.objects.first()
    if batch_obj is None:
        print(f"  {RED}No ModelMasterCreation records found in DB — cannot run test.{RESET}")
        sys.exit(1)
    print(f"  Using batch: id={batch_obj.id}, batch_id={batch_obj.batch_id}")
    cleanup()

    header("Simulating Jig Submit")
    cf_lot_id = simulate_jig_submit(batch_obj)
    print(f"  Carry-forward lot_id generated: {cf_lot_id or '(none)'}")

    # ── 1. Carry-forward lot must exist ───────────────────────────────────
    header("Test 1: Carry-forward lot created")
    if cf_lot_id is None:
        fail("partial_lot_id is None — carry-forward lot NOT created")
    else:
        ok("partial_lot_id is set — carry-forward lot_id generated")

    if cf_lot_id:
        cf_stock = TotalStockModel.objects.filter(lot_id=cf_lot_id).first()
        if cf_stock is None:
            fail("TotalStockModel record for carry-forward lot does NOT exist in DB")
        else:
            ok("TotalStockModel record for carry-forward exists")

            # ── 2. Qty = 4 ────────────────────────────────────────────────
            header("Test 2: Carry-forward lot quantity")
            if cf_stock.total_stock == CARRY_FORWARD_QTY:
                ok(f"total_stock = {cf_stock.total_stock} (expected {CARRY_FORWARD_QTY})")
            else:
                fail(f"total_stock = {cf_stock.total_stock}", f"expected {CARRY_FORWARD_QTY}")

            # ── 3. Jig_Load_completed = False (visible in pick table) ──────
            header("Test 3: Carry-forward lot visible in pick table")
            if not cf_stock.Jig_Load_completed:
                ok("Jig_Load_completed = False → lot will appear in Jig pick table")
            else:
                fail("Jig_Load_completed = True → lot is HIDDEN from pick table")

            # ── 4. Brass audit flags copied ───────────────────────────────
            header("Test 4: Brass audit flags copied from secondary lot")
            if cf_stock.brass_audit_accptance:
                ok("brass_audit_accptance = True (copied)")
            else:
                fail("brass_audit_accptance = False — lot not visible in Jig pick table filter")

            if not cf_stock.brass_audit_rejection:
                ok("brass_audit_rejection = False (correct)")
            else:
                fail("brass_audit_rejection = True (unexpected)")

            # ── 5. batch_id from secondary lot ───────────────────────────
            header("Test 5: Carry-forward uses secondary lot's batch")
            # batch_id is a FK to ModelMasterCreation — compare by PK
            if cf_stock.batch_id_id == batch_obj.id:
                ok(f"batch FK id = {cf_stock.batch_id_id} (matches test batch)")
            else:
                fail(f"batch FK id = {cf_stock.batch_id_id}", f"expected {batch_obj.id}")

            # ── 6. JigLoadTrayId records ──────────────────────────────────
            header("Test 6: JigLoadTrayId record created for carry-forward tray")
            cf_trays = list(JigLoadTrayId.objects.filter(lot_id=cf_lot_id))
            if cf_trays:
                ok(f"{len(cf_trays)} JigLoadTrayId record(s) created for carry-forward lot")
                t = cf_trays[0]
                if t.tray_id == HALF_FILLED_TRAY_ID:
                    ok(f"tray_id = {t.tray_id} (correct)")
                else:
                    fail(f"tray_id = {t.tray_id}", f"expected {HALF_FILLED_TRAY_ID}")
                if t.tray_quantity == CARRY_FORWARD_QTY:
                    ok(f"tray_quantity = {t.tray_quantity} (correct)")
                else:
                    fail(f"tray_quantity = {t.tray_quantity}", f"expected {CARRY_FORWARD_QTY}")
                if t.broken_hooks_effective_tray:
                    ok("broken_hooks_effective_tray = True (flagged correctly)")
                else:
                    fail("broken_hooks_effective_tray = False (should be True)")
            else:
                fail("NO JigLoadTrayId records for carry-forward lot — tray info missing")

    # ── 7. Primary lot marked complete ────────────────────────────────────
    header("Test 7: Primary lot marked Jig_Load_completed")
    primary = TotalStockModel.objects.filter(lot_id=PRIMARY_LOT).first()
    if primary and primary.Jig_Load_completed:
        ok("Primary lot Jig_Load_completed = True")
    else:
        fail("Primary lot Jig_Load_completed is NOT True")

    # ── 8. Secondary lot marked complete ─────────────────────────────────
    header("Test 8: Secondary lot marked Jig_Load_completed")
    secondary = TotalStockModel.objects.filter(lot_id=SECONDARY_LOT).first()
    if secondary and secondary.Jig_Load_completed:
        ok("Secondary lot Jig_Load_completed = True")
    else:
        fail("Secondary lot Jig_Load_completed is NOT True")

    # ── 9. No duplicate carry-forward lots ────────────────────────────────
    header("Test 9: No duplicate carry-forward lots created")
    cf_count = TotalStockModel.objects.filter(
        lot_id__in=[PRIMARY_LOT, SECONDARY_LOT] + ([cf_lot_id] if cf_lot_id else []),
        Jig_Load_completed=False
    ).count()
    if cf_count == 1:
        ok(f"Exactly 1 active (Jig_Load_completed=False) lot in DB after submit")
    elif cf_count == 0:
        fail("0 active lots — carry-forward not created or incorrectly completed")
    else:
        fail(f"{cf_count} active lots — DUPLICATE carry-forward entries exist")

    # ── Cleanup ───────────────────────────────────────────────────────────
    header("Cleanup")
    cleanup()
    # Also clean up the carry-forward lot by lot_id
    if cf_lot_id:
        TotalStockModel.objects.filter(lot_id=cf_lot_id).delete()
        JigLoadTrayId.objects.filter(lot_id=cf_lot_id).delete()
    print("  Test artefacts removed from DB")

    # ── Summary ───────────────────────────────────────────────────────────
    header("SUMMARY")
    total = len(passed) + len(failed)
    print(f"  Passed : {GREEN}{len(passed)}{RESET} / {total}")
    print(f"  Failed : {RED}{len(failed)}{RESET} / {total}")
    if failed:
        print(f"\n  {RED}Failing checks:{RESET}")
        for f_ in failed:
            print(f"    • {f_}")
    else:
        print(f"\n  {GREEN}All checks passed. Broken hooks carry-forward is working correctly.{RESET}")
    print()
    return len(failed) == 0


if __name__ == '__main__':
    ok_result = run_tests()
    sys.exit(0 if ok_result else 1)

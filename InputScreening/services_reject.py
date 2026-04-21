"""Input Screening – Partial Accept / Partial Reject tray allocation engine.

Business rules enforced:
  - Backend is sole source of truth for all allocation calculations.
  - One rejection reason per reject tray (no mixing).
  - Tray qty cannot exceed tray capacity.
  - Existing active trays may be reused (delinked) for reject, up to delink_count.
  - New reject tray IDs are generated sequentially from the highest existing ID.
  - New accept tray IDs must be validated as free/unoccupied in TrayId master.
  - If no free accept tray is available, submission is blocked entirely.
  - All DB writes are wrapped in transaction.atomic().

Architecture:
  This module is the *engine layer* – it performs all calculations and DB writes.
  The views call these helpers; the frontend only renders the returned JSON.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SUBMISSION FLAGS — update on the correct master table
# ─────────────────────────────────────────────────────────────────────────────

def _mark_lot_submitted_flags(lot_id: str) -> None:
    """Flip the Input-Screening submission flags for ``lot_id``.

    Historically this was attempted on ``ModelMasterCreation`` but those
    columns live on ``TotalStockModel``. Using ``update()`` keeps the write
    cheap and atomic – no-op if the lot has no matching row.
    """
    from modelmasterapp.models import TotalStockModel

    TotalStockModel.objects.filter(lot_id=lot_id).update(
        rejected_ip_stock=False,
        few_cases_accepted_Ip_stock=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TRAY ID GENERATION
# ─────────────────────────────────────────────────────────────────────────────

_TRAY_ID_PATTERN = re.compile(r"^([A-Z]+-[A-Z]+)(\d+)$")


def _parse_tray_number(tray_id: str) -> Optional[Tuple[str, int]]:
    """Return (prefix, number) from a tray ID such as 'NB-A00300', or None."""
    m = _TRAY_ID_PATTERN.match(tray_id.strip().upper())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _generate_new_tray_ids(prefix: str, count: int, reserved: set) -> List[str]:
    """Generate ``count`` sequential new tray IDs with the given ``prefix``.

    Queries the TrayId master table to find the current maximum number for
    ``prefix``, then emits count IDs starting from max+1.  The ``reserved``
    set prevents collisions with IDs already consumed earlier in the same
    allocation session.

    Args:
        prefix:   e.g. ``"NB-A"``
        count:    how many IDs to generate
        reserved: set of IDs already allocated this session (mutated in place)

    Returns:
        List of new tray ID strings.
    """
    from modelmasterapp.models import TrayId

    existing_ids = TrayId.objects.filter(
        tray_id__startswith=prefix
    ).values_list("tray_id", flat=True)

    max_num = 0
    for tid in existing_ids:
        parsed = _parse_tray_number(tid)
        if parsed and parsed[0] == prefix:
            max_num = max(max_num, parsed[1])

    # Also honour already-reserved IDs from this session
    for tid in reserved:
        parsed = _parse_tray_number(tid)
        if parsed and parsed[0] == prefix:
            max_num = max(max_num, parsed[1])

    # Determine zero-pad width from existing IDs (default 5)
    pad_width = 5
    sample = next(
        (
            t
            for t in existing_ids
            if t.startswith(prefix)
        ),
        None,
    )
    if sample:
        parsed = _parse_tray_number(sample)
        if parsed:
            pad_width = len(sample) - len(parsed[0])

    generated: List[str] = []
    for i in range(1, count + 1):
        new_id = f"{prefix}{(max_num + i):0{pad_width}d}"
        generated.append(new_id)
        reserved.add(new_id)

    return generated


# ─────────────────────────────────────────────────────────────────────────────
# FREE ACCEPT TRAY VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_free_accept_tray_ids(
    tray_type: Optional[str],
    tray_capacity: Optional[int],
    needed: int,
    reserved: set,
) -> List[str]:
    """Fetch ``needed`` free tray IDs from the TrayId master that are:
      - not assigned to any lot (lot_id is null)
      - not linked to any batch (batch_id is null)
      - not delinked, rejected, or scanned
      - match tray_type and tray_capacity when provided

    Raises ValueError if fewer than ``needed`` free trays are available.
    """
    from modelmasterapp.models import TrayId

    qs = TrayId.objects.filter(
        lot_id__isnull=True,
        batch_id__isnull=True,
        delink_tray=False,
        rejected_tray=False,
        scanned=False,
    )
    if tray_type:
        qs = qs.filter(tray_type__iexact=tray_type)
    if tray_capacity:
        qs = qs.filter(tray_capacity=tray_capacity)

    free_ids = list(
        qs.exclude(tray_id__in=reserved)
        .order_by("id")
        .values_list("tray_id", flat=True)[: needed + len(reserved)]
    )

    # Exclude already-reserved from this session
    free_ids = [t for t in free_ids if t not in reserved]

    if len(free_ids) < needed:
        raise ValueError(
            f"Insufficient free trays available for accept allocation. "
            f"Need {needed}, found {len(free_ids)}. "
            f"Please register more free trays in the master before submitting."
        )

    result = free_ids[:needed]
    reserved.update(result)
    return result


def validate_accept_free_tray(tray_id: str) -> Dict[str, Any]:
    """Validate a single tray ID against the TrayId master for accept allocation.

    Returns a dict with 'valid' bool and 'reason' string.
    """
    from modelmasterapp.models import TrayId

    try:
        tray = TrayId.objects.get(tray_id=tray_id)
    except TrayId.DoesNotExist:
        return {"valid": False, "reason": "Tray ID not found in master"}

    if tray.lot_id:
        return {"valid": False, "reason": f"Tray occupied by lot {tray.lot_id}"}
    if tray.batch_id_id:
        return {"valid": False, "reason": "Tray linked to an active batch"}
    if tray.rejected_tray:
        return {"valid": False, "reason": "Tray is permanently rejected"}
    if tray.scanned:
        return {"valid": False, "reason": "Tray is currently scanned/in-use"}
    if tray.delink_tray:
        return {"valid": False, "reason": "Tray is in delinked state"}

    return {"valid": True, "reason": "Free and available"}


# ─────────────────────────────────────────────────────────────────────────────
# REJECT TRAY ALLOCATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _allocate_reject_trays(
    reasons: List[Dict[str, Any]],
    active_trays: List[Dict[str, Any]],
    delink_count: int,
    capacity: int,
    reserved_ids: set,
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """Allocate reject qty across trays, one reason per tray.

    Strategy:
      1. Build a delink pool: existing active trays sorted by qty ASC
         (prefer partial/smaller trays first to minimise waste).
      2. For each reason, pack into tray slots of ``capacity`` each.
         - While delink_pool has entries and delink budget allows → use
           existing tray (label 'reused').
         - Otherwise → generate new tray ID (label 'new').
      3. The engine does NOT mix reasons into the same tray.

    Returns:
        (allocations, delinked_tray_ids, new_tray_ids)
        - allocations: list of per-slot dicts with tray_id, reason, qty, source
        - delinked_tray_ids: IDs of existing active trays consumed by reject
        - new_tray_ids: IDs of brand-new tray IDs created for reject
    """
    # Sort active trays by qty ascending – prefer to delink partial trays
    delink_pool: List[Dict] = sorted(
        active_trays, key=lambda t: t.get("qty") or 0
    )[:delink_count]

    delink_available: List[Dict] = list(delink_pool)
    delinked_ids: List[str] = []
    new_tray_ids: List[str] = []
    allocations: List[Dict[str, Any]] = []

    # Pre-count how many new trays we might need (upper bound for generation)
    total_reject = sum(r.get("qty", 0) for r in reasons)
    max_new_needed = math.ceil(total_reject / capacity)

    # Generate a pool of new IDs upfront (avoids repeated DB scans)
    tray_prefix = _infer_prefix(active_trays)
    new_pool = _generate_new_tray_ids(tray_prefix, max_new_needed, reserved_ids)
    new_pool_idx = 0

    for reason in reasons:
        remaining = reason.get("qty", 0)
        if remaining <= 0:
            continue

        while remaining > 0:
            fill_qty = min(remaining, capacity)

            if delink_available:
                # Use an existing active tray
                tray = delink_available.pop(0)
                tid = tray["tray_id"]
                delinked_ids.append(tid)
                allocations.append(
                    {
                        "reason_id": reason["reason_id"],
                        "reason_text": reason["reason_text"],
                        "tray_id": tid,
                        "qty": fill_qty,
                        "source": "reused",
                    }
                )
            else:
                # Use a new tray from the generated pool
                tid = new_pool[new_pool_idx]
                new_pool_idx += 1
                new_tray_ids.append(tid)
                allocations.append(
                    {
                        "reason_id": reason["reason_id"],
                        "reason_text": reason["reason_text"],
                        "tray_id": tid,
                        "qty": fill_qty,
                        "source": "new",
                    }
                )

            remaining -= fill_qty

    return allocations, delinked_ids, new_tray_ids


def _infer_prefix(active_trays: List[Dict[str, Any]]) -> str:
    """Infer the tray ID prefix from the first active tray. Falls back to 'NB-A'."""
    for tray in active_trays:
        parsed = _parse_tray_number(tray.get("tray_id", ""))
        if parsed:
            return parsed[0]
    return "NB-A"


# ─────────────────────────────────────────────────────────────────────────────
# ACCEPT TRAY ALLOCATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _allocate_accept_trays(
    accept_qty: int,
    active_trays: List[Dict[str, Any]],
    delinked_ids: List[str],
    capacity: int,
    tray_type: Optional[str],
    reserved_ids: set,
) -> List[Dict[str, Any]]:
    """Distribute accept_qty items across accept tray containers.

    Uses remaining active trays (those NOT delinked for reject) first, then
    pulls free validated trays from the TrayId master if more capacity is
    needed.

    Raises:
        ValueError: if accept_qty > 0 and no free master trays are available.
    """
    delinked_set = set(delinked_ids)
    remaining_active = [t for t in active_trays if t["tray_id"] not in delinked_set]

    allocations: List[Dict[str, Any]] = []
    remaining = accept_qty

    for tray in remaining_active:
        if remaining <= 0:
            break
        fill_qty = min(remaining, capacity)
        allocations.append(
            {
                "tray_id": tray["tray_id"],
                "qty": fill_qty,
                "source": "existing",
            }
        )
        remaining -= fill_qty

    # If more accept qty than existing containers can hold, fetch free trays
    if remaining > 0:
        extra_slots_needed = math.ceil(remaining / capacity)
        free_accept_ids = _fetch_free_accept_tray_ids(
            tray_type=tray_type,
            tray_capacity=capacity,
            needed=extra_slots_needed,
            reserved=reserved_ids,
        )
        for new_tid in free_accept_ids:
            if remaining <= 0:
                break
            fill_qty = min(remaining, capacity)
            allocations.append(
                {
                    "tray_id": new_tid,
                    "qty": fill_qty,
                    "source": "new_free",
                }
            )
            remaining -= fill_qty

    if remaining > 0:
        raise ValueError(
            f"Accept allocation incomplete — {remaining} items could not be placed. "
            "Check free tray availability."
        )

    return allocations


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def validate_reason_single_tray_rule(allocations: List[Dict[str, Any]]) -> bool:
    """Confirm no tray holds more than one reason.  Returns True if valid."""
    tray_reasons: Dict[str, set] = {}
    for slot in allocations:
        tid = slot["tray_id"]
        rid = slot["reason_id"]
        tray_reasons.setdefault(tid, set()).add(rid)
    return all(len(v) == 1 for v in tray_reasons.values())


def _validate_reject_qty(total_reject_qty: int, lot_qty: int) -> None:
    if total_reject_qty <= 0:
        raise ValueError("Total reject quantity must be greater than 0.")
    if total_reject_qty >= lot_qty:
        raise ValueError(
            f"Reject qty ({total_reject_qty}) must be less than lot qty ({lot_qty}). "
            "Use Full Reject for total rejection."
        )


# ─────────────────────────────────────────────────────────────────────────────
# DRAIN ENGINE – real physical tray emptying from reject qty
# ─────────────────────────────────────────────────────────────────────────────

def calculate_emptied_trays(
    active_trays: List[Dict[str, Any]],
    reject_qty: int,
) -> Dict[str, Any]:
    """Simulate draining ``reject_qty`` units from the active trays and
    return which trays become fully empty vs partially drained.

    Drain policy:
        Smallest-qty trays first (prefer TOP partial so full capacity
        trays are preserved for accept).  Ties broken by original order.

    Returns:
        {
          "emptied_tray_ids":  [tray_id, ...],    # fully drained
          "partial_tray":      {tray_id, leftover_qty} | None,
          "emptied_count":     int,               # = len(emptied_tray_ids)
          "reject_qty":        int,
          "drain_plan":        [{tray_id, qty_used, qty_before, qty_after}, ...],
        }

    This is the single source of truth for how many trays can be
    reused (= emptied_count) and which tray IDs qualify.
    """
    trays_sorted = sorted(
        enumerate(active_trays),
        key=lambda p: (p[1].get("qty", 0), p[0]),
    )

    emptied_ids: List[str] = []
    drain_plan: List[Dict[str, Any]] = []
    partial: Optional[Dict[str, Any]] = None
    remaining = max(0, int(reject_qty or 0))

    for _, tray in trays_sorted:
        if remaining <= 0:
            break
        tid = tray.get("tray_id")
        qty = int(tray.get("qty") or 0)
        if qty <= 0:
            continue
        take = min(qty, remaining)
        drain_plan.append({
            "tray_id": tid,
            "qty_before": qty,
            "qty_used": take,
            "qty_after": qty - take,
        })
        if take == qty:
            emptied_ids.append(tid)
        else:
            partial = {"tray_id": tid, "leftover_qty": qty - take}
        remaining -= take

    return {
        "emptied_tray_ids": emptied_ids,
        "partial_tray": partial,
        "emptied_count": len(emptied_ids),
        "reject_qty": int(reject_qty or 0),
        "drain_plan": drain_plan,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LIVE PREVIEW BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_live_preview(
    lot_id: str,
    rejection_entries: List[Dict[str, Any]],
    delink_count: int,
) -> Dict[str, Any]:
    """Compute and return the tray allocation preview WITHOUT writing to the DB.

    Called by the live preview API each time the user updates reject quantities.
    Returns a serialisable dict ready to be sent as JSON.

    Args:
        lot_id:           Lot under inspection.
        rejection_entries: [{reason_id, reason_text, qty}, ...]
        delink_count:     Max existing trays to reuse for reject.

    Returns:
        {
          success: bool,
          lot_qty, tray_capacity, tray_type,
          total_reject_qty, total_accept_qty,
          reject_allocations: [...],
          accept_allocations: [...],
          delinked_tray_ids: [...],
          new_reject_tray_ids: [...],
          validation_errors: [...],
        }
    """
    from .selectors import get_lot_tray_context

    errors: List[str] = []

    ctx = get_lot_tray_context(lot_id)
    if not ctx["found"]:
        return {"success": False, "error": f"Lot {lot_id} not found."}

    lot_qty: int = ctx["lot_qty"]
    capacity: int = ctx["tray_capacity"]
    tray_type: Optional[str] = ctx["tray_type"]
    active_trays: List[Dict] = ctx["active_trays"]

    total_reject = sum(e.get("qty", 0) for e in rejection_entries)
    total_accept = lot_qty - total_reject

    # Basic validations
    if total_reject <= 0:
        errors.append("Total reject quantity must be > 0.")
    if total_reject >= lot_qty:
        errors.append(
            f"Reject qty ({total_reject}) must be less than lot qty ({lot_qty})."
        )
    if total_accept < 0:
        errors.append("Accept qty cannot be negative.")

    if errors:
        return {
            "success": False,
            "validation_errors": errors,
            "total_reject_qty": total_reject,
            "total_accept_qty": total_accept,
        }

    reserved: set = set()

    reject_alloc: List[Dict[str, Any]] = []
    accept_alloc: List[Dict[str, Any]] = []
    delinked_ids: List[str] = []
    new_reject_ids: List[str] = []

    try:
        reject_alloc, delinked_ids, new_reject_ids = _allocate_reject_trays(
            reasons=rejection_entries,
            active_trays=active_trays,
            delink_count=delink_count,
            capacity=capacity,
            reserved_ids=reserved,
        )

        if not validate_reason_single_tray_rule(reject_alloc):
            errors.append("Single-reason-per-tray rule violated in reject allocation.")

        accept_alloc = _allocate_accept_trays(
            accept_qty=total_accept,
            active_trays=active_trays,
            delinked_ids=delinked_ids,
            capacity=capacity,
            tray_type=tray_type,
            reserved_ids=reserved,
        )

    except ValueError as exc:
        # Engine is informational only in the manual-scan flow – record
        # the warning but still return the slot plan so the modal renders.
        errors.append(str(exc))

    return {
        "success": True,
        "lot_id": lot_id,
        "lot_qty": lot_qty,
        "tray_type": tray_type,
        "tray_capacity": capacity,
        "active_tray_count": len(active_trays),
        "active_trays": active_trays,
        "total_reject_qty": total_reject,
        "total_accept_qty": total_accept,
        "reject_allocations": reject_alloc,
        "accept_allocations": accept_alloc,
        "delinked_tray_ids": delinked_ids,
        "new_reject_tray_ids": new_reject_ids,
        "validation_errors": errors,
        # ── Manual scan flow additions ────────────────────────────────
        # Reuse cap is derived from the DRAIN ENGINE: only trays that
        # become physically empty after draining ``total_reject`` qty
        # may be reused.  One reason per tray (no mixing) is enforced
        # elsewhere in validate_scanned_tray().
        **_reuse_counters(
            reject_slots=_build_reject_slots(rejection_entries, capacity),
            accept_slots=_build_accept_slots(max(0, total_accept), capacity),
            active_trays=active_trays,
            total_reject=total_reject,
        ),
    }


def _reuse_counters(
    reject_slots: List[Dict[str, Any]],
    accept_slots: List[Dict[str, Any]],
    active_trays: List[Dict[str, Any]],
    total_reject: int,
) -> Dict[str, Any]:
    """Return the single source of truth for reuse / delink / new-tray
    counters, plus the raw drain plan for the UI.

    Emptied count comes from ``calculate_emptied_trays`` and is the hard
    cap on how many existing trays may be reused for reject.
    """
    drain = calculate_emptied_trays(active_trays, max(0, int(total_reject or 0)))
    emptied_count = drain["emptied_count"]
    reject_slot_count = len(reject_slots)
    reusable_count = min(reject_slot_count, emptied_count)
    new_required = max(0, reject_slot_count - reusable_count)
    return {
        "reject_slots": reject_slots,
        "accept_slots": accept_slots,
        "reusable_count": reusable_count,
        "new_required": new_required,
        "delink_available": emptied_count,
        "emptied_tray_ids": drain["emptied_tray_ids"],
        "emptied_count": emptied_count,
        "partial_tray": drain["partial_tray"],
        "drain_plan": drain["drain_plan"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# REJECT MODAL CONTEXT
# ─────────────────────────────────────────────────────────────────────────────

def get_reject_modal_context(lot_id: str) -> Dict[str, Any]:
    """Return all data needed to populate the reject modal popup.

    Fetches lot metadata, active trays, and the live rejection-reason list
    from the DB.  All data is read-only – no writes performed here.
    """
    from .selectors import get_lot_tray_context
    from .models import IP_Rejection_Table

    ctx = get_lot_tray_context(lot_id)
    if not ctx["found"]:
        return {"success": False, "error": f"Lot {lot_id} not found."}

    reasons = list(
        IP_Rejection_Table.objects.order_by("rejection_reason_id").values(
            "id",
            "rejection_reason_id",
            "rejection_reason",
        )
    )

    return {
        "success": True,
        "lot_id": lot_id,
        "lot_qty": ctx["lot_qty"],
        "tray_type": ctx["tray_type"],
        "tray_capacity": ctx["tray_capacity"],
        "active_tray_count": len(ctx["active_trays"]),
        "active_trays": ctx["active_trays"],
        "rejection_reasons": reasons,
        "batch_id": ctx.get("batch_id"),
        "model_no": ctx.get("model_no"),
        "plating_stk_no": ctx.get("plating_stk_no"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# FINALIZE SUBMISSION
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def finalize_submission(
    lot_id: str,
    rejection_entries: List[Dict[str, Any]],
    delink_count: int,
    remarks: str,
    user,
) -> Dict[str, Any]:
    """Persist the partial accept / partial reject submission.

    Steps:
      1. Re-run allocation engine (prevents stale preview attack).
      2. Validate single-reason-per-tray rule.
      3. Validate accept trays are genuinely free in master.
      4. Save InputScreening_Submitted snapshot.
      5. Flag ModelMasterCreation as submitted.

    All steps run inside a single atomic transaction – partial saves are
    impossible.

    Returns:
        {success, lot_id, submission_id, total_reject_qty, total_accept_qty}
    """
    from .selectors import get_lot_tray_context
    from .models import InputScreening_Submitted

    ctx = get_lot_tray_context(lot_id, lock=True)
    if not ctx["found"]:
        raise ValueError(f"Lot {lot_id} not found or already submitted.")

    lot_qty: int = ctx["lot_qty"]
    capacity: int = ctx["tray_capacity"]
    tray_type: Optional[str] = ctx["tray_type"]
    active_trays: List[Dict] = ctx["active_trays"]
    batch_id_val: str = ctx.get("batch_id", "")

    total_reject = sum(e.get("qty", 0) for e in rejection_entries)
    total_accept = lot_qty - total_reject

    _validate_reject_qty(total_reject, lot_qty)

    reserved: set = set()

    reject_alloc, delinked_ids, new_reject_ids = _allocate_reject_trays(
        reasons=rejection_entries,
        active_trays=active_trays,
        delink_count=delink_count,
        capacity=capacity,
        reserved_ids=reserved,
    )

    if not validate_reason_single_tray_rule(reject_alloc):
        raise ValueError(
            "Internal: single-reason-per-tray rule was violated during allocation."
        )

    accept_alloc = _allocate_accept_trays(
        accept_qty=total_accept,
        active_trays=active_trays,
        delinked_ids=delinked_ids,
        capacity=capacity,
        tray_type=tray_type,
        reserved_ids=reserved,
    )

    # Build JSON snapshots
    rejection_reasons_json = {
        e["reason_id"]: {
            "reason": e["reason_text"],
            "qty": e["qty"],
        }
        for e in rejection_entries
    }
    allocation_preview_json = {
        "total_reject_qty": total_reject,
        "total_accept_qty": total_accept,
        "delinked_tray_ids": delinked_ids,
        "new_reject_tray_ids": new_reject_ids,
        "reject_allocations": reject_alloc,
        "accept_allocations": accept_alloc,
    }

    reject_trays_json = [
        {"tray_id": s["tray_id"], "qty": s["qty"], "reason_id": s["reason_id"]}
        for s in reject_alloc
    ]
    accept_trays_json = [
        {"tray_id": s["tray_id"], "qty": s["qty"]}
        for s in accept_alloc
    ]
    all_trays_json = reject_trays_json + accept_trays_json

    submission = InputScreening_Submitted.objects.create(
        lot_id=lot_id,
        batch_id=batch_id_val,
        module_name="Input Screening",
        plating_stock_no=ctx.get("plating_stk_no"),
        model_no=ctx.get("model_no"),
        tray_type=tray_type,
        tray_capacity=capacity,
        original_lot_qty=lot_qty,
        submitted_lot_qty=lot_qty,
        accepted_qty=total_accept,
        rejected_qty=total_reject,
        active_trays_count=len(active_trays),
        reject_trays_count=len(reject_alloc),
        accept_trays_count=len(accept_alloc),
        remarks=remarks,
        is_partial_accept=True,
        is_partial_reject=True,
        is_full_accept=False,
        is_full_reject=False,
        is_active=True,
        is_submitted=True,
        submitted_at=timezone.now(),
        Draft_Saved=False,
        all_trays_json=all_trays_json,
        accepted_trays_json=accept_trays_json,
        rejected_trays_json=reject_trays_json,
        rejection_reasons_json=rejection_reasons_json,
        allocation_preview_json=allocation_preview_json,
        delink_trays_json=[{"tray_id": tid} for tid in delinked_ids],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )

    # Mark the lot as submitted in the master. The submission flags
    # (rejected_ip_stock / few_cases_accepted_Ip_stock) live on
    # TotalStockModel; ModelMasterCreation has no such columns.
    _mark_lot_submitted_flags(lot_id)

    logger.info(
        "[IS][PARTIAL_SUBMIT] lot=%s submission_id=%s reject=%d accept=%d user=%s",
        lot_id,
        submission.id,
        total_reject,
        total_accept,
        getattr(user, "username", "anonymous"),
    )

    return {
        "success": True,
        "lot_id": lot_id,
        "submission_id": submission.id,
        "total_reject_qty": total_reject,
        "total_accept_qty": total_accept,
        "reject_trays": len(reject_alloc),
        "accept_trays": len(accept_alloc),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SLOT PLAN COMPUTATION (manual scan flow)
# ─────────────────────────────────────────────────────────────────────────────

def _build_reject_slots(
    rejection_entries: List[Dict[str, Any]],
    capacity: int,
) -> List[Dict[str, Any]]:
    """Pack each rejection reason into capacity-bound slots (one reason per tray)."""
    slots: List[Dict[str, Any]] = []
    idx = 0
    for entry in rejection_entries:
        qty = int(entry.get("qty") or 0)
        if qty <= 0:
            continue
        rid = entry.get("reason_id")
        rtext = entry.get("reason_text", "")
        remaining = qty
        while remaining > 0:
            fill = min(remaining, capacity)
            slots.append({
                "slot_idx": idx,
                "reason_id": rid,
                "reason_text": rtext,
                "qty": fill,
            })
            idx += 1
            remaining -= fill
    return slots


def _build_accept_slots(accept_qty: int, capacity: int) -> List[Dict[str, Any]]:
    """Distribute accept_qty into capacity-bound slots."""
    slots: List[Dict[str, Any]] = []
    if accept_qty <= 0 or capacity <= 0:
        return slots
    remaining = accept_qty
    idx = 0
    while remaining > 0:
        fill = min(remaining, capacity)
        slots.append({"slot_idx": idx, "qty": fill})
        idx += 1
        remaining -= fill
    return slots


def compute_slot_plan(
    lot_id: str,
    rejection_entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return a pure-planning view (no tray IDs assigned).

    The frontend renders empty SCAN inputs based on this plan; the user
    fills them by scanning.  ``validate_scanned_tray`` enforces eligibility
    per scan.
    """
    from .selectors import get_lot_tray_context

    ctx = get_lot_tray_context(lot_id)
    if not ctx["found"]:
        return {"success": False, "error": f"Lot {lot_id} not found."}

    lot_qty = ctx["lot_qty"]
    capacity = ctx["tray_capacity"] or 1
    active_trays = ctx["active_trays"]
    active_count = len(active_trays)

    total_reject = sum(int(e.get("qty") or 0) for e in rejection_entries)
    total_accept = lot_qty - total_reject

    errors: List[str] = []
    if total_reject < 0:
        errors.append("Reject qty cannot be negative.")
    if total_reject > lot_qty:
        errors.append(
            f"Reject qty ({total_reject}) cannot exceed lot qty ({lot_qty})."
        )

    reject_slots = _build_reject_slots(rejection_entries, capacity)
    accept_slots = _build_accept_slots(max(0, total_accept), capacity)

    # Reuse policy is derived from the DRAIN ENGINE: only trays that
    # become physically empty after draining ``total_reject`` qty may
    # be reused.  ``delink_available`` exposes these emptied trays so
    # the user can optionally delink any not consumed by reject scans.
    counters = _reuse_counters(
        reject_slots=reject_slots,
        accept_slots=accept_slots,
        active_trays=active_trays,
        total_reject=total_reject,
    )

    return {
        "success": not errors,
        "lot_id": lot_id,
        "lot_qty": lot_qty,
        "tray_type": ctx["tray_type"],
        "tray_capacity": capacity,
        "active_trays": active_trays,
        "active_tray_count": active_count,
        "total_reject_qty": total_reject,
        "total_accept_qty": max(0, total_accept),
        "reject_slots": reject_slots,
        "accept_slots": accept_slots,
        "reusable_count": counters["reusable_count"],
        "new_required": counters["new_required"],
        "delink_available": counters["delink_available"],
        "emptied_tray_ids": counters["emptied_tray_ids"],
        "emptied_count": counters["emptied_count"],
        "partial_tray": counters["partial_tray"],
        "drain_plan": counters["drain_plan"],
        "validation_errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PER-SCAN TRAY VALIDATION (manual scan flow)
# ─────────────────────────────────────────────────────────────────────────────

def _norm(tid: str) -> str:
    return (tid or "").strip().upper()


def validate_scanned_tray(
    lot_id: str,
    slot_type: str,
    tray_id: str,
    used_tray_ids: List[str],
    reject_qty: int = 0,
) -> Dict[str, Any]:
    """Validate a single user-scanned tray ID for the given slot type.

    slot_type:
        ``reject``  – tray may be (a) an EMPTIED active tray of this lot
                      (physically drained by reject qty, will be reused
                      without further delink) or (b) a free master tray
                      (will be created new).  Active trays that are NOT
                      in the emptied set are blocked – they still hold
                      stock and cannot be reassigned.
        ``delink``  – tray must be an EMPTIED active tray of this lot.
                      Non-emptied active trays cannot be delinked in
                      this flow because they still hold production qty.
        ``accept``  – tray may be (a) active for this lot (existing) or
                      (b) a free master tray.

    used_tray_ids: tray IDs already consumed elsewhere in this scan session
                   (so the same tray cannot be assigned twice).
    reject_qty:    total reject qty the user has entered.  Used to compute
                   which active trays are physically emptied.
    """
    from .selectors import get_lot_tray_context
    from modelmasterapp.models import TrayId

    tid = _norm(tray_id)
    if not tid:
        return {"valid": False, "reason": "Tray ID is required."}

    used = {_norm(t) for t in (used_tray_ids or [])}
    if tid in used:
        return {"valid": False, "reason": f"Tray {tid} is already used in this session."}

    ctx = get_lot_tray_context(lot_id)
    if not ctx["found"]:
        return {"valid": False, "reason": f"Lot {lot_id} not found."}

    capacity = ctx["tray_capacity"]
    tray_type = ctx["tray_type"]
    active_trays = ctx["active_trays"]
    active_by_id = {_norm(t["tray_id"]): t for t in active_trays}
    active_match = active_by_id.get(tid)

    # Drain engine caps how many active trays may be reused for reject /
    # delinked.  The CAP is on COUNT, not on tray identity – the user is
    # free to scan any original active tray as long as the total reused
    # count does not exceed ``emptied_count``.
    drain = calculate_emptied_trays(active_trays, max(0, int(reject_qty or 0)))
    emptied_count = drain["emptied_count"]
    # How many active trays has the user already consumed in this session?
    already_reused_count = sum(
        1 for t in used if t in active_by_id and t != tid
    )

    slot_type = (slot_type or "").lower().strip()

    if slot_type == "delink":
        if not active_match:
            return {
                "valid": False,
                "reason": f"Tray {tid} is not an active tray of this lot – cannot delink.",
            }
        if emptied_count and already_reused_count >= emptied_count:
            return {
                "valid": False,
                "reason": (
                    f"Reuse / delink quota reached "
                    f"({already_reused_count}/{emptied_count}). "
                    "Remove an existing scan before picking another active tray."
                ),
            }
        return {
            "valid": True,
            "source": "delinked",
            "tray_qty": active_match.get("qty", 0),
            "top_tray": active_match.get("top_tray", False),
            "tray_id": tid,
            "reason": "Eligible for delink.",
        }

    if slot_type in ("reject", "accept"):
        if active_match:
            # Count-based cap: reject can reuse at most ``emptied_count``
            # active trays.  Any specific tray is allowed, the constraint
            # is on the total count of reused trays.
            if slot_type == "reject" and emptied_count and already_reused_count >= emptied_count:
                return {
                    "valid": False,
                    "reason": (
                        f"Reuse quota reached ({already_reused_count}/{emptied_count}). "
                        "Only as many active trays may be reused as are emptied "
                        "by the current reject qty."
                    ),
                }
            return {
                "valid": True,
                "source": "reused" if slot_type == "reject" else "existing",
                "tray_qty": active_match.get("qty", 0),
                "top_tray": active_match.get("top_tray", False),
                "tray_id": tid,
                "reason": "Existing active tray – will be reused.",
            }

        # Otherwise must be a free master tray.
        try:
            master = TrayId.objects.get(tray_id=tid)
        except TrayId.DoesNotExist:
            return {"valid": False, "reason": f"Tray {tid} not found in master."}
        if master.lot_id:
            return {"valid": False, "reason": f"Tray {tid} occupied by lot {master.lot_id}."}
        if master.batch_id_id:
            return {"valid": False, "reason": f"Tray {tid} linked to an active batch."}
        if master.rejected_tray:
            return {"valid": False, "reason": f"Tray {tid} is permanently rejected."}
        if master.scanned:
            return {"valid": False, "reason": f"Tray {tid} is currently in-use."}
        if master.delink_tray:
            return {"valid": False, "reason": f"Tray {tid} is in delinked state."}
        if tray_type and master.tray_type and master.tray_type.lower() != tray_type.lower():
            return {
                "valid": False,
                "reason": f"Tray type mismatch: expected {tray_type}, got {master.tray_type}.",
            }
        if capacity and master.tray_capacity and master.tray_capacity != capacity:
            return {
                "valid": False,
                "reason": f"Capacity mismatch: expected {capacity}, got {master.tray_capacity}.",
            }
        return {
            "valid": True,
            "source": "new" if slot_type == "reject" else "free",
            "tray_qty": 0,
            "top_tray": False,
            "tray_id": tid,
            "reason": "Free master tray – will be allocated.",
        }

    return {"valid": False, "reason": f"Unknown slot type: {slot_type}"}


# ─────────────────────────────────────────────────────────────────────────────
# FINAL SUBMIT V2 – uses user-scanned tray assignments
# ─────────────────────────────────────────────────────────────────────────────

def _validate_assignments_against_plan(
    plan_slots: List[Dict[str, Any]],
    assignments: List[Dict[str, Any]],
    label: str,
) -> None:
    if len(assignments) != len(plan_slots):
        raise ValueError(
            f"{label} tray count mismatch: plan needs {len(plan_slots)}, "
            f"received {len(assignments)}."
        )
    seen: set = set()
    for a in assignments:
        tid = _norm(a.get("tray_id"))
        if not tid:
            raise ValueError(f"{label} contains an empty tray ID.")
        if tid in seen:
            raise ValueError(f"{label} contains duplicate tray ID {tid}.")
        seen.add(tid)


@transaction.atomic
def finalize_submission_v2(
    lot_id: str,
    rejection_entries: List[Dict[str, Any]],
    reject_assignments: List[Dict[str, Any]],
    delink_tray_ids: List[str],
    accept_assignments: List[Dict[str, Any]],
    remarks: str,
    user,
) -> Dict[str, Any]:
    """Persist a partial reject submission using USER-SCANNED tray IDs.

    All allocations are derived from the user's manual scans.  Server
    re-validates every scan to prevent payload tampering.
    """
    from .selectors import get_lot_tray_context
    from .models import InputScreening_Submitted

    ctx = get_lot_tray_context(lot_id, lock=True)
    if not ctx["found"]:
        raise ValueError(f"Lot {lot_id} not found or already submitted.")

    lot_qty: int = ctx["lot_qty"]
    capacity: int = ctx["tray_capacity"] or 1
    tray_type: Optional[str] = ctx["tray_type"]
    active_trays: List[Dict] = ctx["active_trays"]
    batch_id_val: str = ctx.get("batch_id", "")

    total_reject = sum(int(e.get("qty") or 0) for e in rejection_entries)
    total_accept = lot_qty - total_reject

    _validate_reject_qty(total_reject, lot_qty)

    # Any prior draft for this lot is superseded by the final submit.
    # lot_id is UNIQUE on InputScreening_Submitted, so the draft row must
    # be removed before we create the finalized row.
    InputScreening_Submitted.objects.filter(
        lot_id=lot_id, Draft_Saved=True, is_submitted=False
    ).delete()

    # Re-derive the slot plan and validate user assignments against it.
    reject_slots = _build_reject_slots(rejection_entries, capacity)
    accept_slots = _build_accept_slots(max(0, total_accept), capacity)

    _validate_assignments_against_plan(reject_slots, reject_assignments, "Reject")
    _validate_assignments_against_plan(accept_slots, accept_assignments, "Accept")

    # Cross-bucket duplicate check
    used_global: set = set()
    for a in reject_assignments + accept_assignments + [
        {"tray_id": t} for t in (delink_tray_ids or [])
    ]:
        tid = _norm(a.get("tray_id"))
        if tid in used_global:
            raise ValueError(f"Tray {tid} is used in more than one bucket.")
        used_global.add(tid)

    # Re-validate each scan server-side.
    seen: List[str] = []
    for a in reject_assignments:
        v = validate_scanned_tray(lot_id, "reject", a["tray_id"], seen)
        if not v["valid"]:
            raise ValueError(v["reason"])
        a["_source"] = v["source"]
        seen.append(v["tray_id"])
    for tid in delink_tray_ids or []:
        v = validate_scanned_tray(lot_id, "delink", tid, seen)
        if not v["valid"]:
            raise ValueError(v["reason"])
        seen.append(v["tray_id"])
    for a in accept_assignments:
        v = validate_scanned_tray(lot_id, "accept", a["tray_id"], seen)
        if not v["valid"]:
            raise ValueError(v["reason"])
        a["_source"] = v["source"]
        seen.append(v["tray_id"])

    # Build allocation snapshots (slot order = plan order).
    reject_alloc = [
        {
            "tray_id": _norm(a["tray_id"]),
            "qty": slot["qty"],
            "reason_id": slot["reason_id"],
            "reason_text": slot["reason_text"],
            "source": a.get("_source", "reused"),
        }
        for slot, a in zip(reject_slots, reject_assignments)
    ]
    accept_alloc = [
        {
            "tray_id": _norm(a["tray_id"]),
            "qty": slot["qty"],
            "source": a.get("_source", "existing"),
        }
        for slot, a in zip(accept_slots, accept_assignments)
    ]

    if not validate_reason_single_tray_rule(reject_alloc):
        raise ValueError("Single-reason-per-tray rule violated.")

    delinked_ids = [_norm(t) for t in (delink_tray_ids or [])]

    rejection_reasons_json = {
        e["reason_id"]: {"reason": e.get("reason_text", ""), "qty": e["qty"]}
        for e in rejection_entries
        if int(e.get("qty") or 0) > 0
    }
    allocation_preview_json = {
        "total_reject_qty": total_reject,
        "total_accept_qty": total_accept,
        "delinked_tray_ids": delinked_ids,
        "reject_allocations": reject_alloc,
        "accept_allocations": accept_alloc,
    }
    reject_trays_json = [
        {"tray_id": s["tray_id"], "qty": s["qty"], "reason_id": s["reason_id"]}
        for s in reject_alloc
    ]
    accept_trays_json = [
        {"tray_id": s["tray_id"], "qty": s["qty"]}
        for s in accept_alloc
    ]
    all_trays_json = reject_trays_json + accept_trays_json

    submission = InputScreening_Submitted.objects.create(
        lot_id=lot_id,
        batch_id=batch_id_val,
        module_name="Input Screening",
        plating_stock_no=ctx.get("plating_stk_no"),
        model_no=ctx.get("model_no"),
        tray_type=tray_type,
        tray_capacity=capacity,
        original_lot_qty=lot_qty,
        submitted_lot_qty=lot_qty,
        accepted_qty=total_accept,
        rejected_qty=total_reject,
        active_trays_count=len(active_trays),
        reject_trays_count=len(reject_alloc),
        accept_trays_count=len(accept_alloc),
        remarks=remarks,
        is_partial_accept=True,
        is_partial_reject=True,
        is_full_accept=False,
        is_full_reject=False,
        is_active=True,
        is_submitted=True,
        submitted_at=timezone.now(),
        Draft_Saved=False,
        all_trays_json=all_trays_json,
        accepted_trays_json=accept_trays_json,
        rejected_trays_json=reject_trays_json,
        rejection_reasons_json=rejection_reasons_json,
        allocation_preview_json=allocation_preview_json,
        delink_trays_json=[{"tray_id": tid} for tid in delinked_ids],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )

    _mark_lot_submitted_flags(lot_id)

    logger.info(
        "[IS][PARTIAL_SUBMIT_V2] lot=%s sub=%s reject=%d accept=%d delink=%d user=%s",
        lot_id, submission.id, total_reject, total_accept, len(delinked_ids),
        getattr(user, "username", "anonymous"),
    )

    return {
        "success": True,
        "lot_id": lot_id,
        "submission_id": submission.id,
        "total_reject_qty": total_reject,
        "total_accept_qty": total_accept,
        "reject_trays": len(reject_alloc),
        "accept_trays": len(accept_alloc),
        "delink_trays": len(delinked_ids),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SAVE DRAFT – persist modal state "as is" without allocation validation
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def save_draft_partial_reject(
    lot_id: str,
    rejection_entries: List[Dict[str, Any]],
    reject_assignments: List[Dict[str, Any]],
    delink_tray_ids: List[str],
    accept_assignments: List[Dict[str, Any]],
    remarks: str,
    user,
) -> Dict[str, Any]:
    """Persist the current Rejection-Window state as a draft.

    Unlike ``finalize_submission_v2`` this helper performs **no** tray-scan
    re-validation and **no** allocation math. It stores the payload exactly
    as the operator left it so the modal can be re-opened later and the
    user can resume where they stopped.

    Uniqueness: ``InputScreening_Submitted.lot_id`` is UNIQUE, so a single
    draft row per lot is kept.  If a draft already exists it is
    overwritten; if a finalized row exists, saving a draft is rejected.
    """
    from .selectors import get_lot_tray_context
    from .models import InputScreening_Submitted

    ctx = get_lot_tray_context(lot_id, lock=True)
    if not ctx["found"]:
        raise ValueError(f"Lot {lot_id} not found.")

    lot_qty: int = ctx["lot_qty"]
    capacity: int = ctx["tray_capacity"] or 1
    tray_type: Optional[str] = ctx["tray_type"]
    active_trays: List[Dict] = ctx["active_trays"]
    batch_id_val: str = ctx.get("batch_id", "")

    # Block draft if this lot is already finalized.
    existing = InputScreening_Submitted.objects.select_for_update().filter(
        lot_id=lot_id
    ).first()
    if existing and existing.is_submitted:
        raise ValueError(f"Lot {lot_id} is already submitted – cannot save draft.")

    total_reject = sum(int(e.get("qty") or 0) for e in rejection_entries)
    total_accept = max(0, lot_qty - total_reject)

    # Build snapshots "as is" – no re-validation, no ID generation.
    reject_trays_json = [
        {
            "tray_id": _norm(a.get("tray_id")),
            "reason_id": a.get("reason_id") or "",
        }
        for a in (reject_assignments or [])
        if _norm(a.get("tray_id"))
    ]
    accept_trays_json = [
        {"tray_id": _norm(a.get("tray_id"))}
        for a in (accept_assignments or [])
        if _norm(a.get("tray_id"))
    ]
    delinked_ids = [_norm(t) for t in (delink_tray_ids or []) if _norm(t)]

    rejection_reasons_json = {
        e["reason_id"]: {
            "reason": e.get("reason_text", ""),
            "qty": int(e.get("qty") or 0),
        }
        for e in rejection_entries
        if e.get("reason_id")
    }

    allocation_preview_json = {
        "total_reject_qty": total_reject,
        "total_accept_qty": total_accept,
        "delinked_tray_ids": delinked_ids,
        "reject_assignments": reject_trays_json,
        "accept_assignments": accept_trays_json,
    }

    defaults = {
        "batch_id": batch_id_val,
        "module_name": "Input Screening",
        "plating_stock_no": ctx.get("plating_stk_no"),
        "model_no": ctx.get("model_no"),
        "tray_type": tray_type,
        "tray_capacity": capacity,
        "original_lot_qty": lot_qty,
        "submitted_lot_qty": lot_qty,
        "accepted_qty": total_accept,
        "rejected_qty": total_reject,
        "active_trays_count": len(active_trays),
        "reject_trays_count": len(reject_trays_json),
        "accept_trays_count": len(accept_trays_json),
        "remarks": remarks or "",
        "is_partial_accept": False,
        "is_partial_reject": False,
        "is_full_accept": False,
        "is_full_reject": False,
        "is_active": True,
        "is_submitted": False,
        "Draft_Saved": True,
        "submitted_at": None,
        "all_trays_json": reject_trays_json + accept_trays_json,
        "accepted_trays_json": accept_trays_json,
        "rejected_trays_json": reject_trays_json,
        "rejection_reasons_json": rejection_reasons_json,
        "allocation_preview_json": allocation_preview_json,
        "delink_trays_json": [{"tray_id": tid} for tid in delinked_ids],
        "created_by": user if getattr(user, "is_authenticated", False) else None,
    }

    submission, created = InputScreening_Submitted.objects.update_or_create(
        lot_id=lot_id,
        defaults=defaults,
    )

    logger.info(
        "[IS][SAVE_DRAFT] lot=%s sub=%s created=%s reject=%d accept=%d user=%s",
        lot_id, submission.id, created, total_reject, total_accept,
        getattr(user, "username", "anonymous"),
    )

    return {
        "success": True,
        "lot_id": lot_id,
        "submission_id": submission.id,
        "created": created,
        "total_reject_qty": total_reject,
        "total_accept_qty": total_accept,
        "reject_trays": len(reject_trays_json),
        "accept_trays": len(accept_trays_json),
        "delink_trays": len(delinked_ids),
    }

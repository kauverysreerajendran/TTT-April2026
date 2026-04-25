"""
Brass QC Validators — input validation only.

All submission and tray scan validation lives here.
Returns (is_valid: bool, error_str: str | None).

Rule: No DB writes. No HTTP layer. Pure validation functions.
"""

import logging

from modelmasterapp.models import TrayId
from InputScreening.models import IPTrayId, IP_Rejected_TrayScan, IS_PartialRejectLot

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Submission validators
# ─────────────────────────────────────────────────────────────────────────────

def validate_not_duplicate_submit(lot_id, is_iqf_reentry=False):
    """
    Returns (existing_submission | None, error_str | None).

    IQF reentry lots (send_brass_qc=True) are allowed to re-submit.
    For all other lots, duplicate submission is blocked.
    """
    from ..models import Brass_QC_Submission
    existing = Brass_QC_Submission.objects.filter(lot_id=lot_id, is_completed=True).first()
    if existing and not is_iqf_reentry:
        return existing, (
            f"This lot has already been submitted "
            f"(submission_id={existing.id}, type={existing.submission_type})"
        )
    return existing, None


def validate_full_reject_reasons(rejection_reasons, total_qty):
    """
    For FULL_REJECT: rejection reasons qty can be partial or zero.
    Backend auto-fills missing qty as "FULL LOT REJECTED".
    
    Returns error string or None.
    """
    if not rejection_reasons:
        return None  # ✅ Allow empty — backend will auto-fill
    
    total = sum(int(r.get("qty", 0)) for r in rejection_reasons)
    
    # ✅ FIX: Allow reasons to sum to <= total_qty (not must equal)
    # Missing qty will be auto-filled by backend
    if total > total_qty:
        return (
            f"Rejection reasons qty ({total}) exceeds total lot qty ({total_qty})"
        )
    
    return None


def validate_partial_reject_reasons(rejection_reasons, total_qty):
    """
    For PARTIAL: rejection reasons qty must be >0 and <total_qty.
    Returns (rejected_qty, error_str | None).
    """
    if not rejection_reasons:
        return 0, "Rejection reasons are required for partial reject"
    total = sum(int(r.get("qty", 0)) for r in rejection_reasons)
    if total <= 0:
        return 0, "Rejection qty must be greater than 0"
    if total >= total_qty:
        return 0, "Partial reject qty must be less than total lot qty"
    return total, None


def validate_process_tray_actions(tray_actions, active_trays, stock, lot_id):
    """
    For PROCESS action: validates tray_actions list.
    Returns (accepted_trays, rejected_trays, error_str | None).

    Also handles:
    - New reject trays not in this lot (validates against TrayId master)
    - IS-rejected tray blocking
    - Delink actions (writes BrassTrayId, TrayId delink flags — side effect only here)
    """
    from ..models import BrassTrayId
    if not tray_actions:
        return [], [], "tray_actions required for PROCESS action"

    active_tray_map = {t["tray_id"]: t for t in active_trays}
    accepted_trays = []
    rejected_trays = []

    for ta in tray_actions:
        tid = ta.get("tray_id")
        ta_action = ta.get("action")
        is_top = bool(ta.get("is_top", False))

        if ta_action not in ("ACCEPT", "REJECT", "DELINK"):
            return [], [], f"Invalid tray action '{ta_action}' for tray {tid}"

        tray_match = active_tray_map.get(tid)

        if not tray_match:
            if ta_action == "REJECT":
                # New tray (not in this lot) scanned into a reject slot — validate master
                if not TrayId.objects.filter(tray_id=tid).exists():
                    return [], [], f"Reject tray '{tid}' not found in master tray list"

                # Block trays rejected in Input Screening
                if IPTrayId.objects.filter(tray_id=tid, rejected_tray=True).exists():
                    return [], [], (
                        f"Tray '{tid}' was rejected in Input Screening — "
                        f"permanently ineligible for reuse"
                    )
                if IP_Rejected_TrayScan.objects.filter(rejected_tray_id=tid).exists():
                    return [], [], (
                        f"Tray '{tid}' was rejected in Input Screening — "
                        f"permanently ineligible for reuse"
                    )
                if IS_PartialRejectLot.objects.filter(
                    trays_snapshot__contains=[{"tray_id": tid}]
                ).exists():
                    return [], [], (
                        f"Tray '{tid}' was rejected in Input Screening — "
                        f"permanently ineligible for reuse"
                    )

                slot_qty = int(ta.get("qty") or 0)
                if slot_qty <= 0:
                    slot_qty = (stock.batch_id.tray_capacity if stock.batch_id else 0) or 0
                rejected_trays.append({"tray_id": tid, "qty": slot_qty, "is_top": False})
                logger.info(
                    f"[validators] New reject tray: lot_id={lot_id}, "
                    f"tray_id={tid}, qty={slot_qty}"
                )
                continue
            return [], [], f"Tray {tid} not found in lot"

        if ta_action == "ACCEPT":
            accepted_trays.append({"tray_id": tid, "qty": tray_match["qty"], "is_top": is_top})

        elif ta_action == "REJECT":
            slot_qty = int(ta.get("qty") or tray_match["qty"])
            rejected_trays.append({"tray_id": tid, "qty": slot_qty, "is_top": is_top})

        elif ta_action == "DELINK":
            # Write delink flags — this is the only write in validators (necessary side effect)
            BrassTrayId.objects.filter(lot_id=lot_id, tray_id=tid).update(delink_tray=True)
            TrayId.objects.filter(lot_id=lot_id, tray_id=tid).update(delink_tray=True)

    # Validate exactly one top tray in accepted list
    if accepted_trays:
        top_count = sum(1 for t in accepted_trays if t["is_top"])
        if top_count != 1:
            return [], [], (
                f"Exactly one accepted tray must be marked as top (found {top_count})"
            )

    return accepted_trays, rejected_trays, None


# ─────────────────────────────────────────────────────────────────────────────
# Tray scan validators
# ─────────────────────────────────────────────────────────────────────────────

def validate_tray_not_rejected_in_is(tray_id):
    """
    Returns error string if tray was rejected in Input Screening.
    Returns None if tray is eligible.

    Covers:
    - IPTrayId.rejected_tray flag (set by IS services)
    - IS_PartialRejectLot.trays_snapshot (historical rejections)
    """
    if IPTrayId.objects.filter(tray_id=tray_id, rejected_tray=True).exists():
        return (
            "Tray was rejected in Input Screening - permanently ineligible for reuse"
        )
    if IS_PartialRejectLot.objects.filter(
        trays_snapshot__contains=[{"tray_id": tray_id}]
    ).exists():
        return (
            "Tray was rejected in Input Screening - permanently ineligible for reuse"
        )
    return None


def validate_tray_cross_module_occupancy(tray_id, lot_id):
    """
    Checks tray occupancy across IS, Brass QC, and IQF modules.
    Returns (module_name, error_str) if occupied, or (None, None) if free.
    """
    from ..models import BrassTrayId
    from IQF.models import IQFTrayId

    checks = [
        (
            IPTrayId.objects.filter(
                tray_id=tray_id, rejected_tray=False,
                delink_tray=False, lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "Input Screening",
        ),
        (
            BrassTrayId.objects.filter(
                tray_id=tray_id, rejected_tray=False,
                delink_tray=False, lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "Brass QC",
        ),
        (
            IQFTrayId.objects.filter(
                tray_id=tray_id, rejected_tray=False,
                delink_tray=False, lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "IQF",
        ),
    ]

    for qs, module_name in checks:
        if qs.exists():
            return module_name, f"Tray is currently occupied in {module_name}"

    return None, None

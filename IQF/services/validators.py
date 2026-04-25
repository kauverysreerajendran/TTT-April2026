"""
IQF Validators — input validation only.

All submission and tray scan validation lives here.
Returns (is_valid: bool, error_str: str | None).

Rule: No DB writes. No HTTP layer. Pure validation functions.
"""

import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Submission validators
# ─────────────────────────────────────────────────────────────────────────────

def validate_not_duplicate_submit(lot_id):
    """
    Returns (existing_submission | None, error_str | None).

    IQF allows re-submission for the same lot (iteration).
    No blocking — just return existing record if found.
    """
    from ..models import IQF_Submitted

    existing = IQF_Submitted.objects.filter(
        lot_id=lot_id,
        is_completed=True
    ).order_by('-created_at').first()

    return existing, None


def validate_accepted_qty_positive(accepted_qty):
    """
    Validates that accepted qty is positive.
    Returns error string or None.
    """
    if accepted_qty is None or accepted_qty <= 0:
        return "Accepted qty must be positive"
    return None


def validate_rejected_qty_positive(rejected_qty):
    """
    Validates that rejected qty is positive.
    Returns error string or None.
    """
    if rejected_qty is None or rejected_qty <= 0:
        return "Rejected qty must be positive"
    return None


def validate_qty_sum_equals_total(accepted_qty, rejected_qty, total_qty):
    """
    Validates that accepted + rejected = total for PARTIAL split.
    Returns error string or None.
    """
    actual_sum = (accepted_qty or 0) + (rejected_qty or 0)
    if actual_sum != total_qty:
        return (
            f"Accepted qty ({accepted_qty}) + Rejected qty ({rejected_qty}) "
            f"must equal total qty ({total_qty})"
        )
    return None


def validate_rejection_reasons(rejection_reasons, rejected_qty):
    """
    For FULL_REJECT and PARTIAL: rejection reasons qty must match rejected qty.
    Returns (reason_qty, error_str | None).
    """
    if not rejection_reasons:
        return 0, None

    total = sum(int(r.get("qty", 0)) for r in rejection_reasons if r.get("qty"))

    if total != rejected_qty:
        return total, (
            f"Rejection reasons qty ({total}) must equal rejected qty ({rejected_qty})"
        )

    return total, None


def validate_tray_cross_module_occupancy(tray_id, lot_id):
    """
    Checks tray occupancy across IS, Brass QC, Brass Audit, and IQF modules.
    Returns (module_name, error_str) if occupied in other lot, or (None, None) if free.
    """
    from modelmasterapp.models import TrayId
    from InputScreening.models import IPTrayId
    from Brass_QC.models import BrassTrayId
    from BrassAudit.models import BrassAuditTrayId
    from ..models import IQFTrayId

    checks = [
        (
            IPTrayId.objects.filter(
                tray_id=tray_id,
                rejected_tray=False,
                delink_tray=False,
                lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "Input Screening",
        ),
        (
            BrassTrayId.objects.filter(
                tray_id=tray_id,
                rejected_tray=False,
                delink_tray=False,
                lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "Brass QC",
        ),
        (
            BrassAuditTrayId.objects.filter(
                tray_id=tray_id,
                rejected_tray=False,
                delink_tray=False,
                lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "Brass Audit",
        ),
        (
            IQFTrayId.objects.filter(
                tray_id=tray_id,
                rejected_tray=False,
                delink_tray=False,
                lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "IQF",
        ),
        (
            TrayId.objects.filter(
                tray_id=tray_id,
                rejected_tray=False,
                delink_tray=False,
                lot_id__isnull=False,
            ).exclude(lot_id=lot_id),
            "Global TrayId",
        ),
    ]

    for qs, module_name in checks:
        if qs.exists():
            return module_name, f"Tray {tray_id} already occupied in {module_name}"

    return None, None

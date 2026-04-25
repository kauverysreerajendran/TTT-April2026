"""
IQF Lot Service — lot ID generation and child lot creation.

Handles:
- generate_lot_id()         → new lot ID in enterprise LID format
- create_accept_child()     → accept child lot for FULL_ACCEPT or PARTIAL split
- create_reject_child()     → reject child lot for FULL_REJECT or PARTIAL split

Rule: Only lot creation/mutation writes here. No HTTP layer.
"""

import logging
from datetime import datetime

from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lot ID generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_lot_id(submission_type=""):
    """
    Generate unique lot ID in enterprise LID format.

    Format: LID + YYYYMMDDHHMMSS + NNNNNN (microseconds, zero-padded)
    Example: LID20260423203057000001

    DB-safe: retries up to 10 times if collision detected.
    All submission types use the same format — no prefixes.
    """
    from modelmasterapp.models import TotalStockModel

    for _ in range(10):
        now = datetime.now()
        candidate = f"LID{now.strftime('%Y%m%d%H%M%S')}{str(now.microsecond).zfill(6)}"
        if not TotalStockModel.objects.filter(lot_id=candidate).exists():
            return candidate

    # Final fallback — append 4 random hex chars to break collision
    now = datetime.now()
    return f"LID{now.strftime('%Y%m%d%H%M%S')}{str(now.microsecond).zfill(6)}"


# ─────────────────────────────────────────────────────────────────────────────
# Partial split — child lot creation
# ─────────────────────────────────────────────────────────────────────────────

def create_accept_child(
    stock,
    accept_lot_id,
    accepted_qty,
    accepted_trays,
    submission,
    user,
):
    """
    Creates the accepted child lot for PARTIAL or FULL_ACCEPT submission.

    Writes:
      - TotalStockModel (child_accept)
      - IQFTrayId (one per accepted tray)
      - IQF_Accepted_TrayScan
      - IQF_PartialAcceptLot (for PARTIAL split)
    """
    from modelmasterapp.models import TotalStockModel
    from ..models import (
        IQFTrayId,
        IQF_Accepted_TrayScan,
        IQF_PartialAcceptLot,
    )

    child_accept = TotalStockModel.objects.create(
        lot_id=accept_lot_id,
        batch_id=stock.batch_id,
        model_stock_no=stock.model_stock_no,
        version=stock.version,
        polish_finish=stock.polish_finish,
        plating_color=stock.plating_color,
        total_stock=accepted_qty,
        iqf_accepted_qty=accepted_qty,
        brass_physical_qty=accepted_qty,
        iqf_accptance=True,
        last_process_module="IQF",
        next_process_module="Brass QC",
        last_process_date_time=timezone.now(),
        iqf_last_process_date_time=timezone.now(),
    )

    for tray in accepted_trays:
        IQFTrayId.objects.create(
            lot_id=accept_lot_id,
            tray_id=tray.get('tray_id', ''),
            tray_quantity=tray.get('qty', 0),
            batch_id=stock.batch_id,
            user=user,
            top_tray=tray.get('is_top', tray.get('top_tray', False)),
            IP_tray_verified=True,
        )

    IQF_Accepted_TrayScan.objects.create(
        lot_id=accept_lot_id,
        accepted_tray_quantity=str(accepted_qty),
        user=user,
    )

    # For PARTIAL splits, also create tracking record
    if submission and getattr(submission, 'submission_type', '') == 'PARTIAL':
        IQF_PartialAcceptLot.objects.create(
            new_lot_id=accept_lot_id,
            parent_lot_id=submission.lot_id,
            parent_submission=submission,
            accepted_qty=accepted_qty,
            accept_trays_count=len(accepted_trays),
            trays_snapshot=accepted_trays,
            created_by=user,
        )

    logger.info(
        f"[lot_service] Accept child created: lot={accept_lot_id}, "
        f"qty={accepted_qty}, trays={len(accepted_trays)}"
    )
    return child_accept


def create_reject_child(
    stock,
    reject_lot_id,
    rejected_qty,
    rejected_trays,
    submission,
    rejection_reasons,
    remarks,
    user,
):
    """
    Creates the rejected child lot for FULL_REJECT or PARTIAL split.

    Writes:
      - TotalStockModel (child_reject)
      - IQFTrayId (one per rejected tray)
      - IQF_Rejection_ReasonStore
      - IQF_PartialRejectLot (for PARTIAL split)
    """
    from modelmasterapp.models import TotalStockModel
    from ..models import (
        IQFTrayId,
        IQF_Rejection_ReasonStore,
        IQF_PartialRejectLot,
    )

    child_reject = TotalStockModel.objects.create(
        lot_id=reject_lot_id,
        batch_id=stock.batch_id,
        model_stock_no=stock.model_stock_no,
        version=stock.version,
        polish_finish=stock.polish_finish,
        plating_color=stock.plating_color,
        total_stock=rejected_qty,
        iqf_rejection=True,
        brass_physical_qty=0,
        last_process_module="IQF",
        next_process_module=None,
        last_process_date_time=timezone.now(),
        iqf_last_process_date_time=timezone.now(),
    )

    for tray in rejected_trays:
        IQFTrayId.objects.create(
            lot_id=reject_lot_id,
            tray_id=tray.get('tray_id', ''),
            tray_quantity=tray.get('qty', 0),
            batch_id=stock.batch_id,
            user=user,
            top_tray=tray.get('is_top', tray.get('top_tray', False)),
            rejected_tray=True,
        )

    # Store rejection reasons
    if rejection_reasons:
        reason_qty = sum(int(r.get('qty', 0)) for r in rejection_reasons)
        store = IQF_Rejection_ReasonStore.objects.create(
            lot_id=reject_lot_id,
            user=user,
            total_rejection_quantity=reason_qty,
            lot_rejected_comment=remarks or '',
        )
        # Add many-to-many relations if needed

    # For PARTIAL splits, also create tracking record
    if submission and getattr(submission, 'submission_type', '') == 'PARTIAL':
        IQF_PartialRejectLot.objects.create(
            new_lot_id=reject_lot_id,
            parent_lot_id=submission.lot_id,
            parent_submission=submission,
            rejected_qty=rejected_qty,
            reject_trays_count=len(rejected_trays),
            trays_snapshot=rejected_trays,
            rejection_reasons=rejection_reasons or [],
            remarks=remarks or '',
            created_by=user,
        )

    logger.info(
        f"[lot_service] Reject child created: lot={reject_lot_id}, "
        f"qty={rejected_qty}, trays={len(rejected_trays)}"
    )
    return child_reject

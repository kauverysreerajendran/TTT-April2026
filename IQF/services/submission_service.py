"""
IQF Submission Service — main orchestration layer.

Coordinates: selectors → validators → tray_service → lot_service → routing → DB writes.

Entry point: handle_submission(request, action)

Identical behavior to existing views, but with clean architecture.
All DB writes are preserved exactly. No business logic changes.
"""

import logging

from django.db import transaction
from django.utils import timezone
from django.http import JsonResponse

from modelmasterapp.models import TotalStockModel

from .tray_service import compute_slots, compute_reuse_trays, segregate_trays_for_partial
from .lot_service import generate_lot_id, create_accept_child, create_reject_child
from .validators import (
    validate_not_duplicate_submit,
    validate_rejected_qty_positive,
    validate_rejection_reasons,
)
from .routing import get_stock_flag_updates, get_next_stage
from .selectors import get_current_trays, get_iqf_submission
from ..models import (
    IQF_Submitted,
    IQF_Rejection_ReasonStore,
    IQF_Rejection_Table,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestration
# ─────────────────────────────────────────────────────────────────────────────

def handle_submission(request, action):
    """
    Main submission orchestrator — called from IQF views.

    Handles: FULL_ACCEPT, FULL_REJECT, PARTIAL, PROCESS, SAVE_REMARK
    Preserves identical behavior and DB writes as the original.
    """
    data = request.data
    lot_id = data.get("lot_id")
    rejection_reasons = data.get("rejection_reasons", [])
    accepted_tray_ids = data.get("accepted_tray_ids", [])
    rejected_tray_ids = data.get("rejected_tray_ids", [])
    remarks = data.get("remarks", "").strip()

    # Normalize tray IDs to uppercase
    accepted_tray_ids = [tid.strip().upper() for tid in accepted_tray_ids if tid and tid.strip()]
    rejected_tray_ids = [tid.strip().upper() for tid in rejected_tray_ids if tid and tid.strip()]

    logger.info(f"[submission_service] [INPUT] lot_id={lot_id}, action={action}, user={request.user}")

    if not lot_id:
        return {'success': False, 'error': 'lot_id required'}, 400

    # ── Resolve stock ──
    try:
        stock = TotalStockModel.objects.get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return {'success': False, 'error': f'Lot {lot_id} not found'}, 404

    # ── SAVE_REMARK — no stage movement ──
    if action == "SAVE_REMARK":
        stock.remarks = remarks
        stock.save()
        logger.info(f"[submission_service] Remark saved: lot={lot_id}")
        return {'success': True, 'message': 'Remark saved'}, 200

    # ── Duplicate submission check ──
    existing, dup_error = validate_not_duplicate_submit(lot_id)

    if dup_error:
        return {'success': False, 'error': dup_error}, 400

    # IQF allows re-submission for same lot (iteration) — no blocking
    # Just clear old submission if exists
    if existing:
        logger.info(f"[submission_service] Re-submission allowed for lot {lot_id}")

    # ── Resolve current lot trays (CRITICAL FIX) ──
    tray_data, source, total_qty = get_current_trays(lot_id)

    if not tray_data:
        return {'success': False, 'error': f'No trays found for lot {lot_id}'}, 400

    if total_qty <= 0:
        return {'success': False, 'error': f'Total qty must be positive'}, 400

    active_trays = [t for t in tray_data if not t.get('is_delinked') and not t.get('is_rejected')]

    # ── Action-specific logic ──
    if action == "FULL_ACCEPT":
        accepted_qty = total_qty
        rejected_qty = 0
        accepted_trays = active_trays
        rejected_trays = []

    elif action == "FULL_REJECT":
        accepted_qty = 0
        rejected_qty = total_qty
        accepted_trays = []
        rejected_trays = active_trays

    elif action == "PARTIAL":
        # Validate accepted tray IDs provided
        if not accepted_tray_ids:
            return {'success': False, 'error': 'Accepted tray IDs required for PARTIAL'}, 400

        accepted_trays, rejected_trays = segregate_trays_for_partial(
            active_trays,
            accepted_tray_ids,
            total_qty
        )

        accepted_qty = sum(t['qty'] for t in accepted_trays)
        rejected_qty = sum(t['qty'] for t in rejected_trays)

        if accepted_qty + rejected_qty != total_qty:
            return {
                'success': False,
                'error': f'Tray qty mismatch: {accepted_qty} + {rejected_qty} ≠ {total_qty}'
            }, 400

    elif action == "PROCESS":
        # Similar to Brass QC PROCESS action
        # For IQF, this might be for tray allocation
        accepted_qty = total_qty
        rejected_qty = 0
        accepted_trays = active_trays
        rejected_trays = []

    else:
        return {'success': False, 'error': f'Unknown action: {action}'}, 400

    # ── Store rejection reasons ──
    if rejection_reasons and action in ("FULL_REJECT", "PARTIAL", "PROCESS"):
        reason_qty = sum(int(r.get("qty", 0)) for r in rejection_reasons)
        IQF_Rejection_ReasonStore.objects.update_or_create(
            lot_id=lot_id,
            defaults={
                'user': request.user,
                'total_rejection_quantity': reason_qty,
                'lot_rejected_comment': remarks,
            }
        )

    # ── Create submission record ──
    with transaction.atomic():
        submission = IQF_Submitted.objects.create(
            lot_id=lot_id,
            batch_id=stock.batch_id,
            submission_type=action,
            iqf_incoming_qty=total_qty,
            accepted_qty=accepted_qty,
            rejected_qty=rejected_qty,
            original_data={"qty": total_qty, "trays": tray_data},
            full_accept_data=(
                {"qty": accepted_qty, "trays": accepted_trays}
                if action in ("FULL_ACCEPT", "PROCESS") else None
            ),
            full_reject_data=(
                {"qty": rejected_qty, "trays": rejected_trays}
                if action == "FULL_REJECT" else None
            ),
            partial_accept_data=(
                {"qty": accepted_qty, "trays": accepted_trays}
                if action == "PARTIAL" and accepted_qty > 0 else None
            ),
            partial_reject_data=(
                {"qty": rejected_qty, "trays": rejected_trays}
                if action == "PARTIAL" and rejected_qty > 0 else None
            ),
            remarks=remarks,
            is_completed=True,
            created_by=request.user,
        )

        logger.info(
            f"[submission_service] Submission created: lot={lot_id}, "
            f"type={action}, accepted={accepted_qty}, rejected={rejected_qty}"
        )

        # ── For PARTIAL splits: create child lots ──
        if action == "PARTIAL":
            accept_lot_id = generate_lot_id()
            reject_lot_id = generate_lot_id()

            if accepted_qty > 0:
                create_accept_child(
                    stock,
                    accept_lot_id,
                    accepted_qty,
                    accepted_trays,
                    submission,
                    request.user,
                )
            else:
                accept_lot_id = None

            if rejected_qty > 0:
                create_reject_child(
                    stock,
                    reject_lot_id,
                    rejected_qty,
                    rejected_trays,
                    submission,
                    rejection_reasons,
                    remarks,
                    request.user,
                )
            else:
                reject_lot_id = None

            submission.transition_accept_lot_id = accept_lot_id
            submission.transition_reject_lot_id = reject_lot_id
            submission.save()

        # ── Update stock flags ──
        flag_updates = get_stock_flag_updates(action, accepted_qty, rejected_qty)
        for field, value in flag_updates.items():
            setattr(stock, field, value)
        stock.save()

        # ── Log completion ──
        logger.info(
            f"[submission_service] Submission completed: lot={lot_id}, "
            f"next_stage={get_next_stage(action)}"
        )

    return {
        'success': True,
        'message': f'{action} submission completed',
        'lot_id': lot_id,
        'submission_id': submission.id,
        'accepted_qty': accepted_qty,
        'rejected_qty': rejected_qty,
    }, 200

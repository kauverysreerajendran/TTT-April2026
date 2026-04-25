"""
Brass QC Submission Service — main orchestration layer.

Coordinates: selectors → validators → tray_service → lot_service → routing → DB writes.

Entry point: handle_submission(request, action)

Identical behavior to the existing _handle_submission in views.py.
All DB writes are preserved exactly. No business logic changes.
"""

import logging

from django.db import transaction
from django.utils import timezone
from django.http import JsonResponse

from modelmasterapp.models import TotalStockModel
from InputScreening.models import IP_Rejection_ReasonStore

from .tray_service import resolve_lot_trays, adjust_total_qty_for_is_partial, segregate_trays_for_partial
from .lot_service import generate_lot_id, create_partial_accept_child, create_partial_reject_child, create_full_reject_child
from .validators import validate_not_duplicate_submit, validate_full_reject_reasons, validate_partial_reject_reasons, validate_process_tray_actions
from .routing import get_stock_flag_updates, get_next_stage
from ..models import (
    Brass_QC_Submission,
    Brass_QC_Draft_Store,
    Brass_QC_Rejection_ReasonStore,
    Brass_QC_Rejection_Table,
    Brass_QC_Rejected_TrayScan,
    BrassTrayId,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestration
# ─────────────────────────────────────────────────────────────────────────────


def handle_submission(request, action):
    """
    Main submission orchestrator — called from brass_qc_action and submit_brass_qc.

    Handles: FULL_ACCEPT, FULL_REJECT, PARTIAL, PROCESS, SAVE_REMARK
    Preserves identical behavior and DB writes as the original _handle_submission.
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
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)

    # ── Resolve stock (with split-child fallback) ──
    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        from django.db.models import Q
        parent_stock = TotalStockModel.objects.filter(
            Q(brass_audit_transition_accept_lot_id=lot_id) |
            Q(brass_audit_transition_reject_lot_id=lot_id) |
            Q(brass_audit_transition_lot_id=lot_id)
        ).first()
        if parent_stock:
            stock = parent_stock
            logger.info(
                f"[submission_service] Mapped child lot_id={lot_id} → "
                f"parent lot_id={parent_stock.lot_id}"
            )
        else:
            return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    # ── SAVE_REMARK — no stage movement ──
    if action == "SAVE_REMARK":
        if not remarks:
            return JsonResponse({"success": False, "error": "Remark text is required"}, status=400)
        if len(remarks) > 100:
            return JsonResponse({"success": False, "error": "Remark must be 100 characters or less"}, status=400)

        stock.Bq_pick_remarks = remarks
        stock.save(update_fields=['Bq_pick_remarks'])

        logger.info(f"[submission_service] [REMARK] lot_id={lot_id}, saved by {request.user}")

        return JsonResponse({
            "success": True,
            "lot_id": lot_id,
            "message": "Remark saved successfully",
            "has_remark": True
        })

    # ── Duplicate submission check ──
    is_iqf_reentry = bool(stock.send_brass_qc)

    existing, dup_error = validate_not_duplicate_submit(lot_id, is_iqf_reentry)

    if dup_error:
        logger.warning(f"[submission_service] Duplicate blocked: lot_id={lot_id}")
        return JsonResponse({
            "success": False,
            "error": "This lot has already been submitted",
            "existing_submission_id": existing.id,
            "existing_type": existing.submission_type,
        }, status=409)

    # IQF reentry: clear old submission to allow fresh submit
    if existing and is_iqf_reentry:
        logger.info(
            f"[submission_service] IQF reentry for lot_id={lot_id}, "
            f"clearing old submission id={existing.id}"
        )
        existing.delete()
        existing = None

    # ── Resolve trays ──
    tray_data, source, total_qty = resolve_lot_trays(lot_id)

    if not tray_data:
        return JsonResponse({"success": False, "error": "No tray data found for this lot"}, status=400)

    total_qty = adjust_total_qty_for_is_partial(lot_id, source, stock, total_qty)

    if total_qty <= 0:
        return JsonResponse({"success": False, "error": "Total lot quantity is zero"}, status=400)

    active_trays = [
        t for t in tray_data
        if not t["is_delinked"] and not t.get("is_rejected")
    ]

    # ── Action-specific logic ──
    if action == "FULL_ACCEPT":
        submission_type = "FULL_ACCEPT"
        accepted_qty = total_qty
        rejected_qty = 0

        accepted_trays = [
            {
                "tray_id": t["tray_id"],
                "qty": t["qty"],
                "is_top": t["is_top"]
            }
            for t in active_trays
        ]

        rejected_trays = []

    elif action == "FULL_REJECT":
        submission_type = "FULL_REJECT"

        # =====================================================
        # FIX:
        # If checkbox full lot reject selected and no reasons
        # sent from frontend, auto allow full reject.
        # =====================================================
        if not rejection_reasons:
            rejection_reasons = [{
                "reason_id": None,
                "reason": "FULL LOT REJECTED",
                "qty": total_qty
            }]

        error = validate_full_reject_reasons(rejection_reasons, total_qty)

        if error:
            return JsonResponse({"success": False, "error": error}, status=400)

        accepted_qty = 0
        rejected_qty = total_qty
        accepted_trays = []

        if rejected_tray_ids:
            active_tray_map = {t["tray_id"]: t for t in active_trays}

            rejected_trays = [
                {
                    "tray_id": tid,
                    "qty": active_tray_map[tid]["qty"],
                    "is_top": active_tray_map[tid]["is_top"]
                }
                for tid in rejected_tray_ids
                if tid in active_tray_map
            ]
        else:
            rejected_trays = [
                {
                    "tray_id": t["tray_id"],
                    "qty": t["qty"],
                    "is_top": t["is_top"]
                }
                for t in active_trays
            ]

    elif action == "PARTIAL":
        submission_type = "PARTIAL"

        rejected_qty, error = validate_partial_reject_reasons(
            rejection_reasons,
            total_qty
        )

        if error:
            return JsonResponse({"success": False, "error": error}, status=400)

        accepted_qty = total_qty - rejected_qty

        accepted_trays, rejected_trays, seg_error = segregate_trays_for_partial(
            active_trays,
            rejected_tray_ids,
            rejected_qty
        )

        if seg_error:
            return JsonResponse({"success": False, "error": seg_error}, status=400)

    elif action == "PROCESS":
        tray_actions = data.get("tray_actions", [])

        accepted_trays, rejected_trays, proc_error = validate_process_tray_actions(
            tray_actions,
            active_trays,
            stock,
            lot_id
        )

        if proc_error:
            return JsonResponse({"success": False, "error": proc_error}, status=400)

        rejected_qty = sum(
            int(r.get("qty", 0))
            for r in rejection_reasons
        ) if rejection_reasons else 0

        accepted_qty = total_qty - rejected_qty

        if rejected_qty < 0 or rejected_qty > total_qty:
            return JsonResponse({"success": False, "error": "Invalid rejection quantity"}, status=400)

        # Adjust accept top tray qty so accepted trays sum = accepted_qty
        if accepted_trays and accepted_qty > 0:
            non_top_total = sum(
                t["qty"]
                for t in accepted_trays
                if not t["is_top"]
            )

            for t in accepted_trays:
                if t["is_top"]:
                    t["qty"] = accepted_qty - non_top_total
                    break

        if rejected_qty == 0:
            submission_type = "FULL_ACCEPT"
        elif accepted_qty == 0:
            submission_type = "FULL_REJECT"
        else:
            submission_type = "PARTIAL"

        if rejected_qty > 0 and not rejection_reasons:
            return JsonResponse({
                "success": False,
                "error": "Rejection reasons required when rejecting trays"
            }, status=400)

    else:
        return JsonResponse({
            "success": False,
            "error": f"Unknown action: {action}"
        }, status=400)

    # ── Store rejection reasons ──
    if rejection_reasons and action in ("FULL_REJECT", "PARTIAL", "PROCESS"):
        _store_rejection_reasons(
            lot_id,
            rejection_reasons,
            rejected_qty,
            action,
            remarks,
            request.user
        )

    # ── Save submission record ──
    accept_snapshot = {"qty": accepted_qty, "trays": accepted_trays} if accepted_trays else None
    reject_snapshot = {"qty": rejected_qty, "trays": rejected_trays} if rejected_trays else None

    submission = Brass_QC_Submission.objects.create(
        lot_id=lot_id,
        batch_id=stock.batch_id.batch_id if stock.batch_id else "",
        submission_type=submission_type,
        total_lot_qty=total_qty,
        accepted_qty=accepted_qty,
        rejected_qty=rejected_qty,
        full_accept_data=accept_snapshot if submission_type == "FULL_ACCEPT" else None,
        full_reject_data=reject_snapshot if submission_type == "FULL_REJECT" else None,
        partial_accept_data=accept_snapshot if submission_type == "PARTIAL" else None,
        partial_reject_data=reject_snapshot if submission_type == "PARTIAL" else None,
        snapshot_data={
            "lot_qty": total_qty,
            "accepted": accepted_trays,
            "rejected": rejected_trays,
            "rejection_reasons": rejection_reasons if rejection_reasons else [],
            "remarks": remarks,
        },
        is_completed=True,
        created_by=request.user,
    )

    # ── Generate transition lot IDs and create child lots (PARTIAL) ──
    if submission_type == "FULL_ACCEPT":
        t_lot_id = generate_lot_id("FULL_ACCEPT")
        t_label = "full accept from brass qc to brass audit"

        submission.transition_lot_id = t_lot_id
        submission.transition_label = t_label
        submission.save(update_fields=['transition_lot_id', 'transition_label'])

        stock.brass_qc_transition_lot_id = t_lot_id
        stock.brass_qc_transition_label = t_label

        logger.info(f"[submission_service] FULL_ACCEPT lot_id={lot_id} → transition={t_lot_id}")

    elif submission_type == "FULL_REJECT":
        t_lot_id = generate_lot_id("FULL_REJECT")
        t_label = "full reject from brass qc to iqf"

        submission.transition_lot_id = t_lot_id
        submission.transition_label = t_label
        submission.save(update_fields=['transition_lot_id', 'transition_label'])

        stock.brass_qc_transition_lot_id = t_lot_id
        stock.brass_qc_transition_label = t_label

        logger.info(f"[submission_service] FULL_REJECT lot_id={lot_id} → transition={t_lot_id}")

        # ── Create new TotalStockModel + IQFTrayId + BrassTrayId + RejectionLedger
        # under t_lot_id so IQF receives a clean, fully-populated child lot.
        # Parent stock is closed below via get_stock_flag_updates(FULL_REJECT)
        # which sets is_split=True, remove_lot=True (mirrors PARTIAL pattern).
        with transaction.atomic():
            create_full_reject_child(
                stock=stock,
                t_lot_id=t_lot_id,
                rejected_qty=rejected_qty,
                rejected_trays=rejected_trays,
                submission=submission,
                rejection_reasons=rejection_reasons,
                remarks=remarks,
                user=request.user,
            )

            # Delink parent BrassTrayId records — they belong to the closed parent
            BrassTrayId.objects.filter(lot_id=lot_id).update(delink_tray=True)

            logger.info(
                f"[submission_service] Parent={lot_id} closed → reject child={t_lot_id} (IQF)"
            )

    elif submission_type == "PARTIAL":
        t_accept_lot_id = generate_lot_id("PARTIAL")
        t_reject_lot_id = generate_lot_id("PARTIAL")

        t_label = "partial accept from brass qc to brass audit | partial reject from brass qc to iqf"

        submission.transition_accept_lot_id = t_accept_lot_id
        submission.transition_reject_lot_id = t_reject_lot_id
        submission.transition_label = t_label

        submission.save(update_fields=[
            'transition_accept_lot_id',
            'transition_reject_lot_id',
            'transition_label'
        ])

        stock.brass_qc_transition_accept_lot_id = t_accept_lot_id
        stock.brass_qc_transition_reject_lot_id = t_reject_lot_id
        stock.brass_qc_transition_label = t_label

        logger.info(
            f"[submission_service] PARTIAL lot_id={lot_id} → "
            f"accept={t_accept_lot_id}, reject={t_reject_lot_id}"
        )

        with transaction.atomic():
            create_partial_accept_child(
                stock=stock,
                t_accept_lot_id=t_accept_lot_id,
                accepted_qty=accepted_qty,
                accepted_trays=accepted_trays,
                submission=submission,
                user=request.user,
            )

            create_partial_reject_child(
                stock=stock,
                t_reject_lot_id=t_reject_lot_id,
                rejected_qty=rejected_qty,
                rejected_trays=rejected_trays,
                submission=submission,
                rejection_reasons=rejection_reasons,
                remarks=remarks,
                user=request.user,
            )

            BrassTrayId.objects.filter(lot_id=lot_id).update(delink_tray=True)

            logger.info(
                f"[submission_service] Parent={lot_id} closed → "
                f"accept={t_accept_lot_id} (BA), reject={t_reject_lot_id} (IQF)"
            )

    # ── Apply stage flags to stock ──
    flag_updates = get_stock_flag_updates(
        submission_type,
        accepted_qty,
        rejected_qty
    )

    for field, value in flag_updates.items():
        setattr(stock, field, value)

    Brass_QC_Draft_Store.objects.filter(
        lot_id=lot_id,
        draft_type='rejection_draft'
    ).delete()

    stock.brass_draft = False
    stock.brass_onhold_picking = False
    stock.send_brass_qc = False

    if is_iqf_reentry:
        stock.remove_lot = True
        logger.info(
            f"[submission_service] IQF re-entry lot {lot_id} marked remove_lot=True after {submission_type}"
        )

    stock.last_process_date_time = timezone.now()
    stock.bq_last_process_date_time = timezone.now()

    stock.save(update_fields=[
        'brass_qc_accptance',
        'brass_qc_rejection',
        'brass_qc_few_cases_accptance',
        'brass_physical_qty',
        'brass_qc_accepted_qty',
        'brass_qc_after_rejection_qty',
        'next_process_module',
        'last_process_module',
        'last_process_date_time',
        'bq_last_process_date_time',
        'brass_draft',
        'brass_onhold_picking',
        'send_brass_audit_to_iqf',
        'brass_qc_transition_lot_id',
        'brass_qc_transition_accept_lot_id',
        'brass_qc_transition_reject_lot_id',
        'brass_qc_transition_label',
        'is_split',
        'remove_lot',
        'send_brass_qc',
    ])

    logger.info(
        f"[submission_service] [DONE] type={submission_type}, lot_id={lot_id}, "
        f"moved_to={stock.next_process_module}"
    )

    if submission_type == "PARTIAL":
        return JsonResponse({
            "success": True,
            "message": "Partial lots created successfully",
            "lot_id": lot_id,
            "submission_id": submission.id,
            "submission_type": submission_type,
            "accepted_qty": accepted_qty,
            "rejected_qty": rejected_qty,
            "status": "LOT_SPLIT_COMPLETED",
            "accepted_lot_id": submission.transition_accept_lot_id,
            "rejected_lot_id": submission.transition_reject_lot_id,
            "accept_lot_id": submission.transition_accept_lot_id,
            "reject_lot_id": submission.transition_reject_lot_id,
            "transition_accept_lot_id": submission.transition_accept_lot_id,
            "transition_reject_lot_id": submission.transition_reject_lot_id,
            "transition_label": submission.transition_label,
        })

    next_module = get_next_stage(submission_type) or stock.next_process_module or "UNKNOWN"

    status_value = f"MOVED_TO_{next_module.upper().replace(' ', '_')}"

    return JsonResponse({
        "success": True,
        "message": f"Lot {submission_type.replace('_', ' ').lower()} and moved to {next_module}",
        "lot_id": lot_id,
        "submission_id": submission.id,
        "submission_type": submission_type,
        "accepted_qty": accepted_qty,
        "rejected_qty": rejected_qty,
        "status": status_value,
        "trays": accepted_trays if submission_type != "FULL_REJECT" else rejected_trays,
        "transition_lot_id": submission.transition_lot_id,
        "transition_accept_lot_id": submission.transition_accept_lot_id,
        "transition_reject_lot_id": submission.transition_reject_lot_id,
        "transition_label": submission.transition_label,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _store_rejection_reasons(lot_id, rejection_reasons, rejected_qty, action, remarks, user):
    """
    Writes Brass_QC_Rejection_ReasonStore and Brass_QC_Rejected_TrayScan records.
    Called for FULL_REJECT, PARTIAL, PROCESS actions.
    """
    try:
        reason_store = Brass_QC_Rejection_ReasonStore.objects.create(
            lot_id=lot_id,
            user=user,
            total_rejection_quantity=rejected_qty,
            batch_rejection=(action == "FULL_REJECT"),
            lot_rejected_comment=remarks or None,
        )
        reason_ids = []
        for r in rejection_reasons:
            reason_id = r.get("reason_id")
            qty = int(r.get("qty", 0))
            if qty > 0 and reason_id:
                try:
                    reason_obj = Brass_QC_Rejection_Table.objects.get(id=reason_id)
                    reason_ids.append(reason_obj.id)
                    Brass_QC_Rejected_TrayScan.objects.create(
                        lot_id=lot_id,
                        rejected_tray_quantity=str(qty),
                        rejected_tray_id=None,
                        rejection_reason=reason_obj,
                        user=user,
                    )
                except Brass_QC_Rejection_Table.DoesNotExist:
                    logger.warning(f"[submission_service] Rejection reason not found: id={reason_id}")
        if reason_ids:
            reason_store.rejection_reason.set(reason_ids)
    except Exception as e:
        logger.error(f"[submission_service] Error storing rejection reasons: {e}")

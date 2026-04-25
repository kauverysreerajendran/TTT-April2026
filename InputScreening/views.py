"""Input Screening - HTTP layer.

Thin views that delegate to selectors/services/validators. URL paths and
response payloads are byte-compatible with the previous implementation.
"""
from __future__ import annotations

import logging
from django.core.paginator import Paginator
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import IP_Rejection_Table
from .selectors import (
    PICK_TABLE_COLUMNS,
    get_completed_table_rows,
    get_accept_table_rows,
    get_reject_table_rows,
    get_submitted_detail,
    pick_table_queryset,
)
from .services import (
    enrich_pick_table_rows,
    get_dp_tray_panel,
    record_tray_verification,
    unverify_tray,
)
from .services_reject import (
    build_live_preview,
    get_reject_modal_context,
    finalize_submission,
    finalize_submission_v2,
    save_draft_partial_reject,
    validate_scanned_tray,
)
from .services_submitted import (
    submit_full_accept,
    submit_full_reject,
)
from .validators import (
    ValidationError,
    parse_draft_payload,
    parse_lot_tray,
    parse_manual_submit_payload,
    parse_preview_payload,
    parse_reject_submit_payload,
    parse_scan_payload,
    require_lot_id,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 10

def _is_admin(user):
    if not getattr(user, "is_authenticated", False):
        return False
    return user.groups.filter(name="Admin").exists()

def _empty_table_context(user):
    return {
        "master_data": [],
        "page_obj": None,
        "paginator": None,
        "user": user,
        "ip_rejection_reasons": IP_Rejection_Table.objects.all(),
        "is_admin": _is_admin(user),
    }
# Input Screening - Pick Table
class IS_PickTable(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_PickTable.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        queryset = pick_table_queryset()
        page_number = request.GET.get("page", 1)
        paginator = Paginator(queryset, PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
        master_data = list(page_obj.object_list.values(*PICK_TABLE_COLUMNS))
        master_data = enrich_pick_table_rows(master_data)
        context = {
            "master_data": master_data,
            "page_obj": page_obj,
            "paginator": paginator,
            "user": user,
            "ip_rejection_reasons": IP_Rejection_Table.objects.all(),
            "is_admin": _is_admin(user),
        }
        return Response(context, template_name=self.template_name)

# Input Screening - Accept Table
class IS_AcceptTable(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_AcceptTable.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from_date = request.GET.get("from_date") or None
        to_date = request.GET.get("to_date") or None
        rows = get_accept_table_rows(from_date=from_date, to_date=to_date)
        page_number = request.GET.get("page", 1)
        paginator = Paginator(rows, PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
        context = {
            "master_data": list(page_obj.object_list),
            "page_obj": page_obj,
            "paginator": paginator,
            "user": request.user,
            "ip_rejection_reasons": IP_Rejection_Table.objects.all(),
            "is_admin": _is_admin(request.user),
            "from_date": from_date or "",
            "to_date": to_date or "",
        }
        return Response(context, template_name=self.template_name)

# Input Screening - Completed Table
class IS_Completed_Table(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_Completed_Table.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from_date = request.GET.get("from_date") or None
        to_date = request.GET.get("to_date") or None
        rows = get_completed_table_rows(from_date=from_date, to_date=to_date)
        page_number = request.GET.get("page", 1)
        paginator = Paginator(rows, PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
        context = {
            "master_data": list(page_obj.object_list),
            "page_obj": page_obj,
            "paginator": paginator,
            "user": request.user,
            "ip_rejection_reasons": IP_Rejection_Table.objects.all(),
            "is_admin": _is_admin(request.user),
            "from_date": from_date or "",
            "to_date": to_date or "",
        }
        return Response(context, template_name=self.template_name)

# Input Screening - Reject Table
class IS_RejectTable(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_RejectTable.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from_date = request.GET.get("from_date") or None
        to_date = request.GET.get("to_date") or None
        rows = get_reject_table_rows(from_date=from_date, to_date=to_date)
        page_number = request.GET.get("page", 1)
        paginator = Paginator(rows, PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
        context = {
            "master_data": list(page_obj.object_list),
            "page_obj": page_obj,
            "paginator": paginator,
            "user": request.user,
            "ip_rejection_reasons": IP_Rejection_Table.objects.all(),
            "is_admin": _is_admin(request.user),
            "from_date": from_date or "",
            "to_date": to_date or "",
        }
        return Response(context, template_name=self.template_name)

class IS_GetDPTraysAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            lot_id = require_lot_id(request.GET.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(get_dp_tray_panel(lot_id))

class IS_VerifyTrayAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id, tray_id = parse_lot_tray(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "status": "error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload, http_status = record_tray_verification(lot_id, tray_id, request.user)
        return Response(payload, status=http_status)


# ─────────────────────────────────────────────────────────────────────────────
# PARTIAL ACCEPT / PARTIAL REJECT — THREE NEW API VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class IS_RejectModalContextAPI(APIView):
    """GET: Return all data needed to open the Reject modal popup.

    Query params:
        lot_id (required)

    Response:
        {
            success, lot_id, lot_qty, tray_type, tray_capacity,
            active_tray_count, active_trays, rejection_reasons,
            batch_id, model_no, plating_stk_no
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            lot_id = require_lot_id(request.GET.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = get_reject_modal_context(lot_id)
        if not payload.get("success"):
            return Response(payload, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class IS_AllocationPreviewAPI(APIView):
    """POST: Compute live tray allocation preview without writing to DB.

    Called each time the user updates reject quantities in the modal.
    Frontend renders the returned preview – no business logic in JS.

    Body (JSON):
        {
            "lot_id": "LID...",
            "rejection_entries": [
                {"reason_id": "R01", "reason_text": "SCRATCH", "qty": 17}
            ],
            "delink_count": 2
        }

    Response:
        {
            success, lot_id, lot_qty, tray_capacity,
            total_reject_qty, total_accept_qty,
            reject_allocations, accept_allocations,
            delinked_tray_ids, new_reject_tray_ids,
            validation_errors
        }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            parsed = parse_preview_payload(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = build_live_preview(
            lot_id=parsed["lot_id"],
            rejection_entries=parsed["rejection_entries"],
            delink_count=parsed["delink_count"],
        )
        # Return 200 even with validation_errors – the frontend displays them
        return Response(payload)


class IS_PartialSubmitAPI(APIView):
    """POST: Finalise and persist a partial accept / partial reject submission.

    Re-runs the allocation engine server-side (prevents stale-preview abuse).
    All DB writes are atomic – no partial saves possible.

    Body (JSON):
        {
            "lot_id": "LID...",
            "rejection_entries": [
                {"reason_id": "R01", "reason_text": "SCRATCH", "qty": 17},
                {"reason_id": "R04", "reason_text": "DAMAGE", "qty": 5}
            ],
            "delink_count": 2,
            "remarks": "Optional operator note"
        }

    Response (success):
        {
            success: true,
            lot_id, submission_id,
            total_reject_qty, total_accept_qty,
            reject_trays, accept_trays
        }

    Response (error):
        { success: false, error: "..." }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            parsed = parse_reject_submit_payload(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = finalize_submission(
                lot_id=parsed["lot_id"],
                rejection_entries=parsed["rejection_entries"],
                delink_count=parsed["delink_count"],
                remarks=parsed["remarks"],
                user=request.user,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception:
            logger.exception(
                "[IS][PARTIAL_SUBMIT] Unexpected error for lot=%s",
                parsed.get("lot_id"),
            )
            return Response(
                {"success": False, "error": "Submission failed due to an internal error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(result, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL SCAN FLOW — VALIDATE A SINGLE TRAY SCAN
# ─────────────────────────────────────────────────────────────────────────────

class IS_ValidateScanAPI(APIView):
    """POST: validate a single user-scanned tray ID for a slot.

    Body:
        {
            "lot_id": "...",
            "slot_type": "reject" | "delink" | "accept",
            "tray_id": "...",
            "used_tray_ids": ["...", ...]
        }

    Response: see ``services_reject.validate_scanned_tray``.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            parsed = parse_scan_payload(request.data)
        except ValidationError as exc:
            return Response(
                {"valid": False, "reason": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = validate_scanned_tray(
            lot_id=parsed["lot_id"],
            slot_type=parsed["slot_type"],
            tray_id=parsed["tray_id"],
            used_tray_ids=parsed["used_tray_ids"],
            reject_qty=parsed.get("reject_qty", 0),
        )
        return Response(result)


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL SCAN FLOW — FINAL SUBMIT WITH USER-SCANNED IDS
# ─────────────────────────────────────────────────────────────────────────────

class IS_PartialSubmitV2API(APIView):
    """POST: persist partial reject using USER-SCANNED tray assignments.

    Body:
        {
            "lot_id": "...",
            "rejection_entries": [{reason_id, reason_text, qty}, ...],
            "reject_assignments": [{tray_id, reason_id?}, ...],
            "delink_tray_ids": ["...", ...],
            "accept_assignments": [{tray_id}, ...],
            "remarks": "..."
        }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            parsed = parse_manual_submit_payload(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = finalize_submission_v2(
                lot_id=parsed["lot_id"],
                rejection_entries=parsed["rejection_entries"],
                reject_assignments=parsed["reject_assignments"],
                delink_tray_ids=parsed["delink_tray_ids"],
                accept_assignments=parsed["accept_assignments"],
                remarks=parsed["remarks"],
                user=request.user,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception:
            logger.exception(
                "[IS][PARTIAL_SUBMIT_V2] Unexpected error for lot=%s",
                parsed.get("lot_id"),
            )
            return Response(
                {"success": False, "error": "Submission failed due to an internal error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        
        # ✅ ENHANCED LOGGING FOR SUCCESSFUL SUBMISSION
        log_msg = (
            f"[IS][PARTIAL_SUBMIT_V2] ✅ SUCCESS: "
            f"parent_lot={parsed.get('lot_id')}, "
            f"accept_lot={result.get('accept_lot_id')} (qty={result.get('total_accept_qty', 0)}), "
            f"reject_lot={result.get('reject_lot_id')} (qty={result.get('total_reject_qty', 0)}), "
            f"user={getattr(request.user, 'username', 'anonymous')}"
        )
        logger.info(log_msg)
        print(log_msg)  # visible in Django runserver console
        
        return Response(result, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# SAVE DRAFT — PERSIST MODAL STATE "AS IS"
# ─────────────────────────────────────────────────────────────────────────────

class IS_SaveDraftAPI(APIView):
    """POST: persist the current Rejection Window state as a draft.

    Same payload shape as ``IS_PartialSubmitV2API``, but every field other
    than ``lot_id`` is optional. No tray-scan re-validation is performed –
    the draft is stored exactly as submitted so the modal can be resumed.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            parsed = parse_draft_payload(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = save_draft_partial_reject(
                lot_id=parsed["lot_id"],
                rejection_entries=parsed["rejection_entries"],
                reject_assignments=parsed["reject_assignments"],
                delink_tray_ids=parsed["delink_tray_ids"],
                accept_assignments=parsed["accept_assignments"],
                remarks=parsed["remarks"],
                user=request.user,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception:
            logger.exception(
                "[IS][SAVE_DRAFT] Unexpected error for lot=%s",
                parsed.get("lot_id"),
            )
            return Response(
                {"success": False, "error": "Draft save failed due to an internal error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(result, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────────────────────
# SUBMITTED DETAIL API — view-icon data for IS Completed Table
# ─────────────────────────────────────────────────────────────────────────────

class IS_SubmittedDetailAPI(APIView):
    """GET: Return accept/reject/delink tray details for a submitted lot.

    Query params:
        lot_id (required) — the parent lot ID

    Response:
        {
            success, lot_id, original_lot_qty, plating_stock_no, model_no,
            is_full_accept, is_full_reject, is_partial_accept, is_partial_reject,
            accept_lots: [{new_lot_id, accepted_qty, accept_trays_count, trays:[...]}],
            reject_lots: [{new_lot_id, rejected_qty, rejection_reasons, trays:[...],
                           delinked_tray_ids, delink_count}]
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            lot_id = require_lot_id(request.GET.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = get_submitted_detail(lot_id)
        if not payload.get("success"):
            return Response(payload, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


# ─────────────────────────────────────────────────────────────────────────────
# FULL ACCEPT / FULL REJECT — single-click finalization from pick table
# ─────────────────────────────────────────────────────────────────────────────

class IS_FullAcceptAPI(APIView):
    """POST: Mark the entire lot as accepted and forward it to Brass QC.

    Body: {"lot_id": "...", "remarks": "..."}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id = require_lot_id(request.data.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        remarks = (request.data.get("remarks") or "").strip()
        try:
            result = submit_full_accept(
                lot_id=lot_id,
                remarks=remarks,
                user=request.user,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception:
            logger.exception("[IS][FULL_ACCEPT] Unexpected error for lot=%s", lot_id)
            return Response(
                {"success": False, "error": "Full accept failed due to an internal error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(result, status=status.HTTP_201_CREATED)


class IS_FullRejectAPI(APIView):
    """POST: Mark the entire lot as rejected.

    Body: {"lot_id": "...", "remarks": "..."}
    Remarks are mandatory for full rejection.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id = require_lot_id(request.data.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        remarks = (request.data.get("remarks") or "").strip()
        if not remarks:
            return Response(
                {"success": False, "error": "Lot rejection remarks are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = submit_full_reject(
                lot_id=lot_id,
                remarks=remarks,
                user=request.user,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception:
            logger.exception("[IS][FULL_REJECT] Unexpected error for lot=%s", lot_id)
            return Response(
                {"success": False, "error": "Full reject failed due to an internal error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(result, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# DELINK SELECTED TRAYS — DELINK REJECTED TRAYS FROM SELECTED LOTS
# ─────────────────────────────────────────────────────────────────────────────

class IS_DelinkSelectedTraysAPI(APIView):
    """POST: Delink all rejected trays from selected lots in the reject table.
    
    The frontend sends stock_lot_ids from checked rows in the reject table.
    This endpoint will find all rejected trays from those lots and mark them
    as delinked (delink_tray=True) so they become available for reuse.
    
    Body: {"stock_lot_ids": ["LID123", "LID456", ...]}
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        from django.db import transaction
        from .models import IPTrayId
        from modelmasterapp.models import TrayId
        import logging
        
        logger = logging.getLogger(__name__)
        
        stock_lot_ids = request.data.get("stock_lot_ids", [])
        if not stock_lot_ids or not isinstance(stock_lot_ids, list):
            return Response(
                {"success": False, "error": "stock_lot_ids is required and must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        try:
            with transaction.atomic():
                from .models import IS_PartialRejectLot
                updated_trays = 0
                lots_processed = 0
                
                for lot_id in stock_lot_ids:
                    lot_id = lot_id.strip()
                    if not lot_id:
                        continue
                    
                    # Collect tray IDs from IS_PartialRejectLot (the correct source)
                    tray_ids_to_free = set()
                    
                    reject_lots = IS_PartialRejectLot.objects.filter(
                        parent_lot_id=lot_id
                    ).prefetch_related("allocation_trays")
                    
                    for rl in reject_lots:
                        # Primary source: IS_AllocationTray records linked to this reject lot
                        for alloc_tray in rl.allocation_trays.all():
                            tray_ids_to_free.add(alloc_tray.tray_id)
                        # Secondary source: trays_snapshot JSON (for older records)
                        for snap in (rl.trays_snapshot or []):
                            if snap.get("tray_id"):
                                tray_ids_to_free.add(snap["tray_id"])
                    
                    # Fallback: IPTrayId table (legacy path)
                    if not tray_ids_to_free:
                        for tray_rec in IPTrayId.objects.filter(
                            lot_id=lot_id, rejected_tray=True, delink_tray=False
                        ):
                            tray_ids_to_free.add(tray_rec.tray_id)
                            tray_rec.delink_tray = True
                            tray_rec.save()
                    
                    if not tray_ids_to_free:
                        continue
                    
                    # Free all collected trays in the master TrayId table
                    freed = TrayId.objects.filter(tray_id__in=tray_ids_to_free).update(
                        lot_id=None,
                        batch_id=None,
                        delink_tray=False,
                        rejected_tray=False,
                        scanned=False,
                    )
                    
                    updated_trays += freed
                    lots_processed += 1
                    logger.info(
                        f"[DELINK] Processed lot {lot_id}: freed {freed} trays "
                        f"(tray_ids={list(tray_ids_to_free)})"
                    )
                
                logger.info(f"[DELINK] Total: {updated_trays} trays delinked from {lots_processed} lots")
                
                return Response({
                    "success": True,
                    "message": f"Successfully delinked {updated_trays} rejected trays from {lots_processed} lots",
                    "updated": updated_trays,
                    "lots_processed": lots_processed
                }, status=status.HTTP_200_OK)
                
        except Exception as exc:
            logger.exception("[DELINK] Unexpected error during delink operation")
            return Response(
                {"success": False, "error": f"Delink operation failed: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ─────────────────────────────────────────────────────────────────────────────
# UNVERIFY TRAY — REDO OPTION IN TRAY VERIFICATION PANEL
# ─────────────────────────────────────────────────────────────────────────────

class IS_UnverifyTrayAPI(APIView):
    """POST: Revert a verified tray back to unverified state.

    Body: {"lot_id": "...", "tray_id": "..."}

    Response on success:
        {
            success, status, message, tray_id,
            verified, total, pending, all_verified,
            enable_actions, total_qty, verified_qty
        }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id, tray_id = parse_lot_tray(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload, http_status = unverify_tray(lot_id, tray_id)
        return Response(payload, status=http_status)


# ─────────────────────────────────────────────────────────────────────────────
# SAVE TVM DRAFT — MARK LOT AS IN-PROGRESS TRAY VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

class IS_SaveTVMDraftAPI(APIView):
    """POST: Mark the lot as TVM-draft (tray verification in progress).

    Sets draft_tray_verify = True on TotalStockModel so the pick table
    row shows the "Draft" badge and the Q circle is half-green.

    Body: {"lot_id": "..."}

    Response: {success, message, lot_id}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id = require_lot_id(request.data.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from modelmasterapp.models import TotalStockModel
            updated = TotalStockModel.objects.filter(lot_id=lot_id).update(
                draft_tray_verify=True
            )
            if not updated:
                return Response(
                    {"success": False, "error": "Lot not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            logger.info("IS TVM draft saved for lot_id=%s by user=%s", lot_id, request.user)
            return Response(
                {"success": True, "message": "TVM draft saved.", "lot_id": lot_id},
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            logger.exception("IS_SaveTVMDraftAPI error for lot_id=%s", lot_id)
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ─────────────────────────────────────────────────────────────────────────────
# CLEAR ALL VERIFICATIONS — REVERT ALL TRAYS TO UNVERIFIED FOR A LOT
# ─────────────────────────────────────────────────────────────────────────────

class IS_ClearAllVerificationsAPI(APIView):
    """POST: Reset all IP_TrayVerificationStatus rows for a lot to is_verified=False.

    Used by the Clear button in the Tray Verification Panel.
    Also resets ip_person_qty_verified on TotalStockModel so the pick table
    Q circle reverts to grey.

    Body: {"lot_id": "..."}
    Response: {success, message, lot_id, cleared}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id = require_lot_id(request.data.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from django.db import transaction
            from .models import IP_TrayVerificationStatus
            from modelmasterapp.models import TotalStockModel

            with transaction.atomic():
                cleared = IP_TrayVerificationStatus.objects.filter(
                    lot_id=lot_id
                ).update(is_verified=False)

                TotalStockModel.objects.filter(lot_id=lot_id).update(
                    ip_person_qty_verified=False,
                    draft_tray_verify=False,
                )

            logger.info(
                "IS clear-all-verifications for lot_id=%s by user=%s: %d rows reset",
                lot_id, request.user, cleared,
            )
            return Response(
                {
                    "success": True,
                    "message": f"All {cleared} tray verifications cleared.",
                    "lot_id": lot_id,
                    "cleared": cleared,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            logger.exception("IS_ClearAllVerificationsAPI error for lot_id=%s", lot_id)
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ─────────────────────────────────────────────────────────────────────────────
# HOLD / UNHOLD A LOT IN THE PICK TABLE
# ─────────────────────────────────────────────────────────────────────────────

class IS_SaveHoldUnholdAPI(APIView):
    """POST: Hold or unhold a lot in the IS pick table.

    Body: {"lot_id": "...", "remark": "...", "action": "hold"|"unhold"}
    Response: {success, message}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id = require_lot_id(request.data.get("lot_id"))
        except ValidationError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from modelmasterapp.models import TotalStockModel

            remark = (request.data.get("remark") or "").strip()
            action = (request.data.get("action") or "").strip().lower()

            if not remark:
                return Response({"success": False, "error": "Remark is required."}, status=status.HTTP_400_BAD_REQUEST)
            if action not in ("hold", "unhold"):
                return Response({"success": False, "error": "Invalid action. Must be 'hold' or 'unhold'."}, status=status.HTTP_400_BAD_REQUEST)

            obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
            if not obj:
                return Response({"success": False, "error": "Lot not found."}, status=status.HTTP_404_NOT_FOUND)

            if action == "hold":
                obj.ip_hold_lot = True
                obj.ip_holding_reason = remark
                obj.ip_release_lot = False
                obj.ip_release_reason = ""
            else:
                obj.ip_hold_lot = False
                obj.ip_release_lot = True
                obj.ip_release_reason = remark

            obj.save(update_fields=["ip_hold_lot", "ip_holding_reason", "ip_release_lot", "ip_release_reason"])

            logger.info(
                "IS pick table lot_id=%s %s by user=%s with remark: %s",
                lot_id, action, request.user, remark,
            )
            return Response({"success": True, "message": f"Lot {action} successful."}, status=status.HTTP_200_OK)

        except Exception as exc:
            logger.exception("IS_SaveHoldUnholdAPI error for lot_id=%s", lot_id)
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─────────────────────────────────────────────────────────────────────────────
# SAVE PICK-TABLE REMARK FOR A LOT
# ─────────────────────────────────────────────────────────────────────────────

class IS_SaveIPRemarkAPI(APIView):
    """POST: Save the operator remark for a lot in the IS pick table.

    Stores the remark in TotalStockModel.IP_pick_remarks.
    Once saved, the remark cannot be edited (read-only in UI).

    Body: {"lot_id": "...", "remark": "..."}
    Response: {success, message}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id = require_lot_id(request.data.get("lot_id"))
        except ValidationError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from modelmasterapp.models import TotalStockModel

            remark = (request.data.get("remark") or "").strip()
            if not remark:
                return Response({"success": False, "error": "Remark cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
            if len(remark) > 100:
                return Response({"success": False, "error": "Remark must be 100 characters or less."}, status=status.HTTP_400_BAD_REQUEST)

            updated = TotalStockModel.objects.filter(lot_id=lot_id, IP_pick_remarks__isnull=True).update(
                IP_pick_remarks=remark
            )
            if not updated:
                # Either lot not found or remark already saved
                exists = TotalStockModel.objects.filter(lot_id=lot_id).exists()
                if not exists:
                    return Response({"success": False, "error": "Lot not found."}, status=status.HTTP_404_NOT_FOUND)
                return Response({"success": False, "error": "Remark already saved and cannot be edited."}, status=status.HTTP_400_BAD_REQUEST)

            logger.info("IS pick remark saved for lot_id=%s by user=%s", lot_id, request.user)
            return Response({"success": True, "message": "Remark saved.", "remark": remark}, status=status.HTTP_200_OK)

        except Exception as exc:
            logger.exception("IS_SaveIPRemarkAPI error for lot_id=%s", lot_id)
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─────────────────────────────────────────────────────────────────────────────
# DELETE BATCH — ADMIN ONLY: HARD DELETE A BATCH FROM IS PICK TABLE
# ─────────────────────────────────────────────────────────────────────────────

class IS_DeleteBatchAPI(APIView):
    """POST: Admin-only hard delete of a batch from the IS Pick Table.

    Deletes all TotalStockModel records for the batch. This removes the
    lot from the pick table. Only available to Admin group users.

    Body: {"batch_id": "...", "stock_lot_id": "..."}
    Response: {success, message}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_admin(request.user):
            return Response({"success": False, "error": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        try:
            import json as _json
            data = request.data if hasattr(request, "data") else _json.loads(request.body.decode("utf-8"))
            batch_id = (data.get("batch_id") or "").strip()
            stock_lot_id = (data.get("stock_lot_id") or "").strip()

            if not batch_id and not stock_lot_id:
                return Response({"success": False, "error": "Missing batch_id or stock_lot_id."}, status=status.HTTP_400_BAD_REQUEST)

            from modelmasterapp.models import ModelMasterCreation, TotalStockModel

            if batch_id:
                batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
                if not batch_obj:
                    return Response({"success": False, "error": "Batch not found."}, status=status.HTTP_404_NOT_FOUND)
                deleted_count, _ = TotalStockModel.objects.filter(batch_id=batch_obj).delete()
                if deleted_count == 0:
                    return Response({"success": False, "error": "No stock records found for this batch."}, status=status.HTTP_404_NOT_FOUND)
                logger.info("IS Delete Batch: batch_id=%s deleted %d records by user=%s", batch_id, deleted_count, request.user)
                return Response({"success": True, "message": f"{deleted_count} stock record(s) deleted."}, status=status.HTTP_200_OK)
            else:
                obj = TotalStockModel.objects.filter(lot_id=stock_lot_id).first()
                if not obj:
                    return Response({"success": False, "error": "Stock lot not found."}, status=status.HTTP_404_NOT_FOUND)
                TotalStockModel.objects.filter(batch_id=obj.batch_id).delete()
                logger.info("IS Delete Batch: stock_lot_id=%s deleted by user=%s", stock_lot_id, request.user)
                return Response({"success": True, "message": "Stock lot deleted."}, status=status.HTTP_200_OK)

        except Exception as exc:
            logger.exception("IS_DeleteBatchAPI error")
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

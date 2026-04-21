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
    pick_table_queryset,
)
from .services import (
    enrich_pick_table_rows,
    get_dp_tray_panel,
    record_tray_verification,
)
from .services_reject import (
    build_live_preview,
    get_reject_modal_context,
    finalize_submission,
    finalize_submission_v2,
    validate_scanned_tray,
)
from .validators import (
    ValidationError,
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

class IS_AcceptTable(APIView):
    """Deprecated - Accept functionality removed. Kept for URL routing compatibility."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_AcceptTable.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_empty_table_context(request.user), template_name=self.template_name)

class IS_Completed_Table(APIView):
    """Deprecated - Reject/Accept flow removed. Kept for URL routing compatibility."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_Completed_Table.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_empty_table_context(request.user), template_name=self.template_name)

class IS_RejectTable(APIView):
    """Deprecated - Reject functionality removed. Kept for URL routing compatibility."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_RejectTable.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_empty_table_context(request.user), template_name=self.template_name)

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
        return Response(result, status=status.HTTP_201_CREATED)

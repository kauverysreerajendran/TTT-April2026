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
    get_lot_reject_context,
    get_rejection_reasons,
    pick_table_queryset,
)
from .services import (
    compute_reject_allocation,
    enrich_pick_table_rows,
    get_dp_tray_panel,
    record_tray_verification,
    submit_partial_reject,
)
from .validators import (
    ValidationError,
    parse_lot_tray,
    parse_reject_allocation_payload,
    parse_reject_submit_payload,
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
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_AcceptTable.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_empty_table_context(request.user), template_name=self.template_name)


class IS_Completed_Table(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "Input_Screening/IS_Completed_Table.html"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_empty_table_context(request.user), template_name=self.template_name)


class IS_RejectTable(APIView):
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


# ---------------------------------------------------------------------------
# Reject window APIs (thin)
# ---------------------------------------------------------------------------


class IS_RejectionReasonsAPI(APIView):
    """Return the master list of rejection reasons rendered in the modal."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"success": True, "reasons": get_rejection_reasons()})


class IS_RejectContextAPI(APIView):
    """Return lot meta (qty, capacity, model) for the reject modal header."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            lot_id = require_lot_id(request.GET.get("lot_id"))
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ctx = get_lot_reject_context(lot_id)
        if ctx is None:
            return Response(
                {"success": False, "error": "Lot not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, **ctx})


class IS_RejectAllocateAPI(APIView):
    """Live allocation preview — called as the operator types reject qty."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            lot_id, reject_qty, reasons = parse_reject_allocation_payload(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = compute_reject_allocation(lot_id, reject_qty, reasons=reasons)
        http = status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST
        return Response(result, status=http)


class IS_ValidateTrayAPI(APIView):
    """Real-time tray ID validation for rejection workflow.

    Called by the modal as the operator scans/types tray IDs so invalid
    trays are surfaced immediately (before submit attempt).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .services import validate_tray_availability
        tray_id = request.GET.get("tray_id", "").strip()
        lot_id = request.GET.get("lot_id", "").strip()
        if not tray_id or not lot_id:
            return Response(
                {"valid": False, "error": "tray_id and lot_id required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = validate_tray_availability(tray_id, lot_id)
        return Response(result)


class IS_RejectSubmitAPI(APIView):
    """Atomic submit of the reject decision (idempotent per lot)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            payload = parse_reject_submit_payload(request.data)
        except ValidationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result, http = submit_partial_reject(payload, request.user)
        return Response(result, status=http)
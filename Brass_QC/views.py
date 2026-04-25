from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.db.models import OuterRef, Subquery, Exists, F, Count
from django.core.paginator import Paginator
from django.templatetags.static import static
import math
import uuid
from modelmasterapp.models import *
from DayPlanning.models import *
from InputScreening.models import *
from .models import *
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
import traceback
from rest_framework import status
from django.http import JsonResponse
import json
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.http import require_GET
from math import ceil
from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from IQF.models import *
from BrassAudit.models import *
from django.utils import timezone
from datetime import timedelta
import datetime
import pytz
from django.contrib.auth.decorators import login_required

# ── Service layer imports ──
from .services.selectors import (
    get_picktable_base_queryset,
    get_completed_base_queryset,
    get_is_rejection_qty,
    get_is_partial_accept_lot,
    get_iqf_submission,
    get_iqf_tray_count,
    get_iqf_active_tray_count,
    get_model_images,
    get_rejection_reasons_qs,
    get_completed_submission,
    get_submission_by_child_lot,
)
from .services.tray_service import (
    resolve_lot_trays,
    adjust_total_qty_for_is_partial,
    compute_slots,
    compute_reuse_trays as _svc_compute_reuse_trays,
)
from .services.lot_service import generate_lot_id
from .services.submission_service import handle_submission

# Brass QC Pick Table View
@method_decorator(login_required, name='dispatch')
class BrassPickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Brass_Qc/Brass_PickTable.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False

        # Handle sorting parameters
        sort = request.GET.get('sort')
        order = request.GET.get('order', 'asc')  # Default to ascending
        
        # Field mapping for proper model field references
        sort_field_mapping = {
            'serial_number': 'lot_id',
            'date_time': 'last_process_date_time',
            'plating_stk_no': 'batch_id__plating_stk_no',
            'polishing_stk_no': 'batch_id__polishing_stk_no',
            'plating_color': 'batch_id__plating_color',
            'category': 'batch_id__category',
            'polish_finish': 'batch_id__polish_finish',
            'tray_capacity': 'batch_id__tray_capacity',
            'vendor_location': 'batch_id__vendor_internal',
            'no_of_trays': 'batch_id__no_of_trays',
            'total_ip_accepted_qty': 'total_IP_accpeted_quantity',
            'process_status': 'last_process_module',
            'lot_status': 'last_process_module',
            'current_stage': 'next_process_module',
            'remarks': 'Bq_pick_remarks'
        }

        brass_rejection_reasons = Brass_QC_Rejection_Table.objects.all()

        # ── Queryset delegated to selectors layer ──
        queryset = get_picktable_base_queryset()

        # Apply sorting
        if sort and sort in sort_field_mapping:
            field = sort_field_mapping[sort]
            if order == 'desc':
                field = '-' + field
            queryset = queryset.order_by(field)
        else:
            queryset = queryset.order_by('-last_process_date_time', '-lot_id')

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            
            data = {
                'batch_id': batch.batch_id,
                'lot_id': stock_obj.lot_id,
                'date_time': batch.date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no,
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'wiping_required': stock_obj.wiping_required,
                'brass_audit_rejection': stock_obj.brass_audit_rejection,
                'stock_lot_id': stock_obj.lot_id,
                'total_IP_accpeted_quantity': stock_obj.total_IP_accpeted_quantity,
                'brass_qc_accepted_qty_verified': stock_obj.brass_qc_accepted_qty_verified,
                'brass_qc_accepted_qty': stock_obj.brass_qc_accepted_qty,
                'brass_missing_qty': stock_obj.brass_missing_qty,
                'brass_physical_qty': stock_obj.brass_physical_qty,
                'brass_physical_qty_edited': stock_obj.brass_physical_qty_edited,
                'accepted_Ip_stock': stock_obj.accepted_Ip_stock,
                'rejected_ip_stock': stock_obj.rejected_ip_stock,
                'few_cases_accepted_Ip_stock': stock_obj.few_cases_accepted_Ip_stock,
                'accepted_tray_scan_status': stock_obj.accepted_tray_scan_status,
                'Bq_pick_remarks': stock_obj.Bq_pick_remarks,
                'IP_pick_remarks': stock_obj.IP_pick_remarks,
                'brass_qc_accptance': stock_obj.brass_qc_accptance,
                'brass_accepted_tray_scan_status': stock_obj.brass_accepted_tray_scan_status,
                'brass_qc_rejection': stock_obj.brass_qc_rejection,
                'brass_qc_few_cases_accptance': stock_obj.brass_qc_few_cases_accptance,
                'brass_onhold_picking': stock_obj.brass_onhold_picking,
                'brass_draft': stock_obj.brass_draft,
                'iqf_acceptance': stock_obj.iqf_acceptance,
                'send_brass_qc': stock_obj.send_brass_qc,
                'send_brass_audit_to_qc': stock_obj.send_brass_audit_to_qc,
                'last_process_date_time': stock_obj.last_process_date_time,
                'iqf_last_process_date_time': stock_obj.iqf_last_process_date_time,
                'brass_hold_lot': stock_obj.brass_hold_lot,
                'brass_holding_reason': stock_obj.brass_holding_reason,
                'brass_release_lot': stock_obj.brass_release_lot,
                'brass_release_reason': stock_obj.brass_release_reason,
                'has_draft': stock_obj.has_draft,
                'draft_type': stock_obj.draft_type,
                'brass_rejection_total_qty': stock_obj.brass_rejection_total_qty,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                'last_process_module': stock_obj.last_process_module,
            }
            master_data.append(data)

        for data in master_data:   
            total_IP_accpeted_quantity = data.get('total_IP_accpeted_quantity', 0)
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            
            lot_id = data.get('stock_lot_id')
            
            if total_IP_accpeted_quantity and total_IP_accpeted_quantity > 0:
                # Bug fix: When IS did partial rejection, subtract IS rejection qty
                if data.get('few_cases_accepted_Ip_stock'):
                    is_rejection_qty = 0
                    is_rejection_store = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
                    if is_rejection_store and is_rejection_store.total_rejection_quantity:
                        is_rejection_qty = is_rejection_store.total_rejection_quantity
                    data['display_accepted_qty'] = max(total_IP_accpeted_quantity - is_rejection_qty, 0)
                else:
                    data['display_accepted_qty'] = total_IP_accpeted_quantity
            else:
                total_rejection_qty = 0
                rejection_store = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
                if rejection_store and rejection_store.total_rejection_quantity:
                    total_rejection_qty = rejection_store.total_rejection_quantity

                total_stock_obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
                
                if total_stock_obj and total_rejection_qty > 0:
                    data['display_accepted_qty'] = max(total_stock_obj.total_stock - total_rejection_qty, 0)
                else:
                    data['display_accepted_qty'] = 0

            brass_physical_qty = data.get('brass_physical_qty') or 0
            brass_rejection_total_qty = data.get('brass_rejection_total_qty') or 0
            is_delink_only = (brass_physical_qty > 0 and 
                              brass_rejection_total_qty >= brass_physical_qty and 
                              data.get('brass_onhold_picking', False))
            data['is_delink_only'] = is_delink_only

            display_qty = data.get('display_accepted_qty', 0)
            if tray_capacity > 0 and display_qty > 0:
                data['no_of_trays'] = math.ceil(display_qty / tray_capacity)
            else:
                data['no_of_trays'] = 0
            
            if data.get('send_brass_qc'):
                data['brass_qc_rejection'] = False
                data['brass_physical_qty'] = 0
                data['brass_rejection_total_qty'] = 0
                data['brass_qc_accepted_qty'] = 0

                from IQF.models import IQF_Submitted
                iqf_record = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()
                iqf_tray_count = 0

                if iqf_record and iqf_record.submission_type in ('FULL_ACCEPT', 'PARTIAL'):
                    iqf_accepted = iqf_record.accepted_qty or 0
                    if iqf_accepted > 0:
                        data['display_accepted_qty'] = iqf_accepted
                        data['total_IP_accpeted_quantity'] = iqf_accepted
                        if tray_capacity > 0:
                            data['no_of_trays'] = math.ceil(iqf_accepted / tray_capacity)

                    if iqf_record.submission_type == 'FULL_ACCEPT' and iqf_record.full_accept_data:
                        iqf_tray_count = len([t for t in iqf_record.full_accept_data.get('trays', []) if int(t.get('qty', 0)) > 0])
                    elif iqf_record.submission_type == 'PARTIAL' and iqf_record.partial_accept_data:
                        iqf_tray_count = len([t for t in iqf_record.partial_accept_data.get('trays', []) if int(t.get('qty', 0)) > 0])

                if iqf_tray_count > 0:
                    data['no_of_trays'] = iqf_tray_count
                else:
                    actual_tray_count = IQFTrayId.objects.filter(
                        lot_id=lot_id,
                        IP_tray_verified=True,
                        rejected_tray=False,
                        delink_tray=False
                    ).count()
                    if actual_tray_count > 0:
                        data['no_of_trays'] = actual_tray_count
                    else:
                        store_count = IQF_Accepted_TrayID_Store.objects.filter(lot_id=lot_id, is_save=True).count()
                        if store_count > 0:
                            data['no_of_trays'] = store_count
        
            # Get model images
            data['model_images'] = get_model_images(data['batch_id'])
        
            data['available_qty'] = data.get('brass_qc_accepted_qty') if data.get('brass_qc_accepted_qty') and data.get('brass_qc_accepted_qty') > 0 else (data.get('brass_physical_qty') if data.get('brass_physical_qty') and data.get('brass_physical_qty') > 0 else data.get('display_accepted_qty', 0))

            # ── Backend-computed flags — move ALL decision logic here ──
            # Delete button: only when lot has no acceptance/rejection yet and qty is verified
            data['can_delete'] = (
                not data.get('brass_qc_accptance') and
                not data.get('brass_qc_rejection') and
                not data.get('brass_accepted_tray_scan_status') and
                not data.get('brass_qc_few_cases_accptance') and
                data.get('brass_qc_accepted_qty_verified', False)
            )

            # QC circle status: determines background color
            if data.get('brass_onhold_picking') or data.get('brass_draft'):
                data['qc_circle'] = 'HALF'
            elif data.get('brass_qc_rejection') or data.get('brass_qc_accptance') or data.get('brass_qc_few_cases_accptance'):
                data['qc_circle'] = 'GREEN'
            else:
                data['qc_circle'] = 'GRAY'

            # Action state: determines which buttons to show
            if data.get('iqf_acceptance'):
                data['action_state'] = 'IQF_RETURN'
            elif data.get('brass_onhold_picking') and data.get('is_delink_only'):
                data['action_state'] = 'ONHOLD_DELINK'
            elif data.get('brass_onhold_picking') and not data.get('is_delink_only'):
                data['action_state'] = 'ONHOLD_TOPTRAY'
            elif data.get('send_brass_qc'):
                data['action_state'] = 'SEND_BRASS_QC'
            elif data.get('send_brass_audit_to_qc'):
                data['action_state'] = 'AUDIT_RETURN'
            elif data.get('brass_qc_rejection') or data.get('brass_qc_few_cases_accptance'):
                data['action_state'] = 'REJECTED'
            else:
                data['action_state'] = 'DEFAULT'

            # Lot status pill
            if data.get('brass_onhold_picking') or data.get('brass_draft'):
                data['lot_status'] = 'Draft'
            elif data.get('brass_hold_lot'):
                data['lot_status'] = 'On Hold'
            elif data.get('brass_qc_rejection') or data.get('brass_qc_few_cases_accptance') or data.get('brass_qc_accptance'):
                data['lot_status'] = 'Yet to Release'
            elif data.get('brass_qc_accepted_qty_verified'):
                data['lot_status'] = 'Released'
            else:
                data['lot_status'] = 'Yet to Start'

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
            'brass_rejection_reasons': brass_rejection_reasons,
            'pick_table_count': len(master_data),
        }
        return Response(context, template_name=self.template_name)

# Brass 
@method_decorator(login_required, name='dispatch')
class BrassCompletedView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Brass_Qc/Brass_Completed.html'

    def get(self, request):
        user = request.user
        
        sort = request.GET.get('sort')
        order = request.GET.get('order', 'asc')
        
        sort_field_mapping = {
            'serial_number': 'lot_id',
            'date_time': 'bq_last_process_date_time',
            'plating_stk_no': 'batch_id__plating_stk_no',
            'polishing_stk_no': 'batch_id__polishing_stk_no',
            'plating_color': 'batch_id__plating_color',
            'category': 'batch_id__category',
            'polish_finish': 'batch_id__polish_finish',
            'tray_capacity': 'batch_id__tray_capacity',
            'vendor_location': 'batch_id__vendor_internal',
            'no_of_trays': 'batch_id__no_of_trays',
            'total_ip_accepted_qty': 'total_IP_accpeted_quantity',
            'accepted_qty': 'brass_qc_accepted_qty',
            'rejected_qty': 'brass_rejection_qty',
            'process_status': 'last_process_module',
            'lot_status': 'last_process_module',
            'current_stage': 'next_process_module',
            'remarks': 'Bq_pick_remarks',
        }
        
        tz = pytz.timezone("Asia/Kolkata")
        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')

        if from_date_str and to_date_str:
            try:
                from_date = datetime.datetime.strptime(from_date_str, '%Y-%m-%d').date()
                to_date = datetime.datetime.strptime(to_date_str, '%Y-%m-%d').date()
            except ValueError:
                from_date = yesterday
                to_date = today
        else:
            from_date = yesterday
            to_date = today

        from_datetime = timezone.make_aware(datetime.datetime.combine(from_date, datetime.datetime.min.time()))
        to_datetime = timezone.make_aware(datetime.datetime.combine(to_date, datetime.datetime.max.time()))

        # ── Queryset delegated to selectors layer ──
        queryset = get_completed_base_queryset(from_datetime, to_datetime)

        if sort and sort in sort_field_mapping:
            field = sort_field_mapping[sort]
            if order == 'desc':
                field = '-' + field
            queryset = queryset.order_by(field)
        else:
            queryset = queryset.order_by('-bq_last_process_date_time', '-lot_id')

        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            
            data = {
                'batch_id': batch.batch_id,
                'lot_id': stock_obj.lot_id,
                'date_time': batch.date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no if batch.model_stock_no else '',
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'stock_lot_id': stock_obj.lot_id,
                'last_process_module': stock_obj.last_process_module,
                'next_process_module': stock_obj.next_process_module,
                'brass_qc_accepted_qty_verified': stock_obj.brass_qc_accepted_qty_verified,
                'brass_qc_accepted_qty': stock_obj.brass_qc_accepted_qty,
                'brass_rejection_qty': stock_obj.brass_rejection_qty,
                'brass_missing_qty': stock_obj.brass_missing_qty,
                'brass_physical_qty': stock_obj.brass_physical_qty,
                'accepted_Ip_stock': stock_obj.accepted_Ip_stock,
                'rejected_ip_stock': stock_obj.rejected_ip_stock,
                'few_cases_accepted_Ip_stock': stock_obj.few_cases_accepted_Ip_stock,
                'accepted_tray_scan_status': stock_obj.accepted_tray_scan_status,
                'Bq_pick_remarks': stock_obj.Bq_pick_remarks,
                'brass_qc_accptance': stock_obj.brass_qc_accptance,
                'brass_accepted_tray_scan_status': stock_obj.brass_accepted_tray_scan_status,
                'brass_qc_rejection': stock_obj.brass_qc_rejection,
                'brass_qc_few_cases_accptance': stock_obj.brass_qc_few_cases_accptance,
                'brass_onhold_picking': stock_obj.brass_onhold_picking,
                'total_IP_accpeted_quantity': stock_obj.total_IP_accpeted_quantity,
                'bq_last_process_date_time': stock_obj.bq_last_process_date_time,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                'no_of_trays': 0,
            }
            master_data.append(data)

        for data in master_data:
            total_IP_accpeted_quantity = data.get('total_IP_accpeted_quantity', 0)
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            lot_id = data.get('stock_lot_id')
            
            if total_IP_accpeted_quantity and total_IP_accpeted_quantity > 0:
                data['display_accepted_qty'] = total_IP_accpeted_quantity
            else:
                data['display_accepted_qty'] = 0

            display_qty = data.get('display_accepted_qty', 0)
            if tray_capacity > 0 and display_qty > 0:
                data['no_of_trays'] = math.ceil(display_qty / tray_capacity)
            else:
                data['no_of_trays'] = 0
                
            data['model_images'] = get_model_images(data['batch_id'])

            if data.get('brass_physical_qty') and data.get('brass_physical_qty') > 0:
                data['available_qty'] = data['brass_physical_qty']
            else:
                data['available_qty'] = data.get('display_accepted_qty', 0)

            data['lot_remarks'] = ''
            
        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'from_date': from_date.strftime('%Y-%m-%d'),
            'to_date': to_date.strftime('%Y-%m-%d'),
            'date_filter_applied': bool(from_date_str and to_date_str),
        }
        return Response(context, template_name=self.template_name)


import logging
logger = logging.getLogger(__name__)

# Shared function to resolve tray data for a lot_id across multiple sources
def _resolve_lot_trays(lot_id):
    """
    Shared tray resolver — delegates to tray_service.resolve_lot_trays.
    Kept here for backward compatibility with legacy endpoints.
    Returns (tray_data_list, source_name, total_qty).
    """
    return resolve_lot_trays(lot_id)


# Lot Qty - Verification Toggle
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_qc_toggle_verified(request):
    """Toggle brass_qc_accepted_qty_verified flag (checkbox persistence)."""
    lot_id = request.data.get('lot_id')
    verified = request.data.get('verified', False)

    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)

    ts = TotalStockModel.objects.filter(lot_id=lot_id).first()
    if not ts:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    ts.brass_qc_accepted_qty_verified = bool(verified)
    update_fields = ['brass_qc_accepted_qty_verified']

    # ── ERR1: On verification, move stage to Brass QC ──
    if bool(verified) and ts.last_process_module != 'Brass QC':
        ts.last_process_module = 'Brass QC'
        update_fields.append('last_process_module')
        logger.info(f"[BrassQC] [STATUS UPDATE] lot_id={lot_id} moved {ts.last_process_module} → Brass QC")

    ts.save(update_fields=update_fields)

    logger.info(f"[BrassQC] Toggle verified: lot_id={lot_id}, verified={ts.brass_qc_accepted_qty_verified}")

    return JsonResponse({
        "success": True,
        "lot_id": lot_id,
        "brass_qc_accepted_qty_verified": ts.brass_qc_accepted_qty_verified,
        "last_process_module": ts.last_process_module,
    })


# Hold / Unhold Toggle with Remark
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_qc_hold_unhold(request):
    """Toggle brass hold/unhold status with a remark."""
    lot_id = request.data.get('lot_id')
    action = request.data.get('action')  # 'hold' or 'unhold'
    remark = request.data.get('remark', '').strip()

    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
    if action not in ('hold', 'unhold'):
        return JsonResponse({"success": False, "error": "action must be 'hold' or 'unhold'"}, status=400)
    if not remark:
        return JsonResponse({"success": False, "error": "Remark is required"}, status=400)
    if len(remark) > 50:
        return JsonResponse({"success": False, "error": "Remark must be 50 characters or less"}, status=400)

    ts = TotalStockModel.objects.filter(lot_id=lot_id).first()
    if not ts:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    if action == 'hold':
        ts.brass_hold_lot = True
        ts.brass_holding_reason = remark
        ts.brass_release_lot = False
        ts.brass_release_reason = ''
    else:
        ts.brass_hold_lot = False
        ts.brass_release_reason = remark
        ts.brass_release_lot = True

    ts.save(update_fields=[
        'brass_hold_lot', 'brass_holding_reason',
        'brass_release_lot', 'brass_release_reason',
    ])

    logger.info(f"[BrassQC] Hold/Unhold: lot_id={lot_id}, action={action}, remark={remark}")

    return JsonResponse({
        "success": True,
        "lot_id": lot_id,
        "action": action,
        "message": f"Lot {'held' if action == 'hold' else 'released'} successfully.",
    })


# Rejection Reasons - Dynamic Fetch
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_rejection_reasons(request):
    """Fetch all active rejection reasons from Brass_QC_Rejection_Table."""
    reasons = Brass_QC_Rejection_Table.objects.all().order_by('rejection_reason_id')
    data = [
        {"id": r.id, "reason_id": r.rejection_reason_id, "reason": r.rejection_reason}
        for r in reasons
    ]
    return JsonResponse({"success": True, "reasons": data})

# Tray Reuse Logic — delegates to tray_service
def compute_reuse_trays(trays, reject_qty):
    """
    Deterministic tray reuse logic — delegates to tray_service.compute_reuse_trays.
    Kept here for backward compatibility with legacy calls inside brass_qc_action.
    """
    return _svc_compute_reuse_trays(trays, reject_qty)

# Brass QC Unified API Endpoint
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_qc_action(request):
    """
    UNIFIED Brass QC API — single entry point for all actions.
    Routes by 'action' parameter to appropriate logic.
    Actions:
      GET_TRAYS       — fetch tray details for a lot
      ALLOCATE        — compute accept/reject slot allocation
      VALIDATE_TRAY   — validate a scanned tray ID
      FULL_ACCEPT     — submit full acceptance
      FULL_REJECT     — submit full rejection
      PARTIAL         — submit partial acceptance
      PROCESS         — submit with tray actions
      SAVE_REMARK     — save remark only
    """
    action = request.data.get('action', '').strip()

    if action == 'GET_TRAYS':
        lot_id = request.data.get('lot_id')
        if not lot_id:
            return JsonResponse({"error": "lot_id is required"}, status=400)
        try:
            stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return JsonResponse({"error": "Lot not found"}, status=404)

        is_iqf = bool(stock.send_brass_qc)

        # IQF lot: use current IQF tray data — do NOT fall back to stale BrassTrayId history
        if is_iqf:
            from IQF.models import IQFTrayId as _IQFTrayId
            iqf_trays = _IQFTrayId.objects.filter(
                lot_id=lot_id, rejected_tray=False, delink_tray=False
            ).order_by('-top_tray', 'tray_id')
            if iqf_trays.exists():
                tray_data = [
                    {"tray_id": t.tray_id, "qty": t.tray_quantity or 0,
                     "is_rejected": False, "is_top": bool(t.top_tray), "is_delinked": False,
                     "status": "ACCEPT_TOP" if t.top_tray else "ACCEPT"}
                    for t in iqf_trays
                ]
                total_qty = sum(t['qty'] for t in tray_data)
                source = "IQFTrayId"
            else:
                tray_data, source, total_qty = _resolve_lot_trays(lot_id)
        else:
            tray_data, source, total_qty = _resolve_lot_trays(lot_id)

        # Adjust total_qty when IS did partial rejection (original tray qtys are not reduced by IS)
        # Skip when source=IPTrayId — those quantities are already post-IS-rejection adjusted
        if not is_iqf and source != "IPTrayId" and getattr(stock, 'few_cases_accepted_Ip_stock', False):
            _is_rej_store = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            _is_rej_qty = (_is_rej_store.total_rejection_quantity if _is_rej_store and _is_rej_store.total_rejection_quantity else 0)
            _ip_acc_qty = stock.total_IP_accpeted_quantity or 0
            if _ip_acc_qty > 0:
                total_qty = max(_ip_acc_qty - _is_rej_qty, 0)
            elif _is_rej_qty > 0:
                total_qty = max(total_qty - _is_rej_qty, 0)

        tray_capacity = 0
        if stock.batch_id:
            tray_capacity = stock.batch_id.tray_capacity or 0

        # Filter out delinked and rejected trays for view icon display
        active_trays = [t for t in tray_data if not t.get('is_delinked') and not t.get('is_rejected')]

        # ── ERR3 FIX: When this Brass QC row originates from an IS Partial
        # Accept submission, the parent TotalStockModel still carries the
        # original lot_id and qty (e.g. 100), but the *real* accept lot is a
        # child IS_PartialAcceptLot row (new_lot_id, accepted_qty, snapshot).
        # The view icon must surface that child data dynamically. We do NOT
        # mutate any other module state — only the response payload for this
        # single endpoint is enriched.
        display_lot_id = lot_id
        child_created_at_str = None
        accept_trays_count = 0
        if not is_iqf and getattr(stock, 'few_cases_accepted_Ip_stock', False):
            from InputScreening.models import IS_PartialAcceptLot
            child = (
                IS_PartialAcceptLot.objects
                .filter(parent_lot_id=lot_id)
                .order_by('-created_at')
                .first()
            )
            if child:
                snapshot = child.trays_snapshot or []
                snap_trays = [
                    {
                        "tray_id": t.get("tray_id", ""),
                        "qty": int(t.get("qty") or 0),
                        "is_rejected": False,
                        "is_top": bool(t.get("top_tray", False)),
                        "is_delinked": False,
                        "status": "ACCEPT_TOP" if t.get("top_tray") else "ACCEPT",
                    }
                    for t in snapshot
                    if t.get("tray_id") and int(t.get("qty") or 0) > 0
                ]
                if snap_trays:
                    active_trays = snap_trays
                    total_qty = int(child.accepted_qty or 0)
                    display_lot_id = child.new_lot_id
                    source = "IS_PartialAcceptLot"
                    accept_trays_count = len(snap_trays)
                    if child.created_at:
                        from django.utils import timezone
                        local_dt = timezone.localtime(child.created_at)
                        child_created_at_str = local_dt.strftime("%B %d, %Y, %I:%M %p").lstrip("0")

        logger.info(f"[ACTION:GET_TRAYS] lot_id={lot_id}, is_iqf={is_iqf}, source={source}, trays={len(active_trays)}, total_qty={total_qty}")
        return JsonResponse({
            "success": True,
            "lot_id": display_lot_id,
            "parent_lot_id": lot_id,
            "batch_id": stock.batch_id.batch_id if stock.batch_id else "",
            "total_qty": total_qty,
            "tray_capacity": tray_capacity,
            "is_iqf": is_iqf,
            "source": source,
            "trays": active_trays,
            "child_created_at": child_created_at_str,
            "accept_trays_count": accept_trays_count,
        })

    elif action == 'GET_SUBMISSION_TRAYS':
        # Read tray data from Brass_QC_Submission — used by Brass_Completed.html view icon
        lot_id = request.data.get('lot_id')
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        
        # ✅ FIX: Handle both parent lot_id AND child lot_id (from partial accept/reject splits)
        # First try direct parent lookup
        submission = Brass_QC_Submission.objects.filter(lot_id=lot_id, is_completed=True).order_by('-created_at').first()
        
        # If not found, check if this lot_id matches a child lot from a partial split
        if not submission:
            from django.db.models import Q
            submission = Brass_QC_Submission.objects.filter(
                Q(transition_accept_lot_id=lot_id) | Q(transition_reject_lot_id=lot_id),
                is_completed=True
            ).order_by('-created_at').first()
            
            # Track which child lot this is so we know which data to use
            is_child_accept = submission and submission.transition_accept_lot_id == lot_id
            is_child_reject = submission and submission.transition_reject_lot_id == lot_id
        else:
            is_child_accept = False
            is_child_reject = False
        
        if not submission:
            logger.warning(f"[ACTION:GET_SUBMISSION_TRAYS] No completed submission for lot_id={lot_id}")
            return JsonResponse({"success": True, "lot_id": lot_id, "trays": [],
                                 "accepted_qty": 0, "rejected_qty": 0, "total_lot_qty": 0, "submission_type": ""})
        trays = []
        
        # ✅ FIX: For child lots from partial splits, use only the relevant child data
        if is_child_accept:
            # Child accept lot: use ONLY partial_accept_data, ignore reject data
            accept_data = submission.partial_accept_data or {}
            reject_data = {}
        elif is_child_reject:
            # Child reject lot: use ONLY partial_reject_data, ignore accept data
            accept_data = {}
            reject_data = submission.partial_reject_data or {}
        else:
            # Parent lot: use full or partial data as available
            accept_data = submission.full_accept_data or submission.partial_accept_data or {}
            reject_data = submission.full_reject_data or submission.partial_reject_data or {}

        # Build per-tray qty maps from submission snapshots
        # These hold the qty USED per tray_id in each stream
        accept_qty_map = {}   # tray_id → accepted qty
        accept_top_map = {}   # tray_id → is_top
        # Normalise accept_data: stored as {"trays": [...]} or as [...] directly
        _accept_trays = (
            accept_data if isinstance(accept_data, list)
            else (accept_data.get('trays') or [])
        ) if accept_data else []
        for t in _accept_trays:
            tid = t.get("tray_id", "")
            if tid:
                accept_qty_map[tid] = int(t.get("qty") or 0)
                accept_top_map[tid] = bool(t.get("is_top", False))

        reject_qty_map = {}   # tray_id → rejected qty
        # Normalise reject_data: stored as {"trays": [...]} or as [...] directly
        _reject_trays = (
            reject_data if isinstance(reject_data, list)
            else (reject_data.get('trays') or [])
        ) if reject_data else []
        for t in _reject_trays:
            tid = t.get("tray_id", "")
            if tid:
                reject_qty_map[tid] = int(t.get("qty") or 0)

        # Build delinked trays: original trays whose full qty was not consumed
        # Source: BrassTrayId (all, including any previously delinked) → fallback TrayId
        # ✅ FIX: Use parent lot_id for original tray lookups when dealing with child lots
        parent_lot_id = submission.lot_id if (is_child_accept or is_child_reject) else lot_id
        
        original_qty_map = {}  # tray_id → original qty
        for bt in BrassTrayId.objects.filter(lot_id=parent_lot_id):
            if bt.tray_id:
                original_qty_map[bt.tray_id] = int(bt.tray_quantity or 0)
        if not original_qty_map:
            for ti in TrayId.objects.filter(lot_id=parent_lot_id, tray_quantity__gt=0):
                original_qty_map[ti.tray_id] = int(ti.tray_quantity or 0)

        delink_trays = []
        for orig_tid, orig_qty in original_qty_map.items():
            if orig_qty <= 0:
                continue
            # Tray consumed (fully or partially) in accept/reject → NOT delinked
            if orig_tid in accept_qty_map or orig_tid in reject_qty_map:
                continue
            delink_trays.append({
                "tray_id": orig_tid,
                "tray_quantity": orig_qty,
                "rejected_tray": False,
                "delink_tray": True,
                "top_tray": False,
                "is_top_tray": False,
            })

        for tid, qty in accept_qty_map.items():
            trays.append({
                "tray_id": tid,
                "tray_quantity": qty,
                "rejected_tray": False,
                "delink_tray": False,
                "top_tray": accept_top_map.get(tid, False),
                "is_top_tray": accept_top_map.get(tid, False),
            })
        for tid, qty in reject_qty_map.items():
            trays.append({
                "tray_id": tid,
                "tray_quantity": qty,
                "rejected_tray": True,
                "delink_tray": False,
                "top_tray": False,
                "is_top_tray": False,
            })
        trays.extend(delink_trays)

        logger.info(f"[ACTION:GET_SUBMISSION_TRAYS] lot_id={lot_id}, type={submission.submission_type}, "
                    f"accepted={len(accept_qty_map)}, rejected={len(reject_qty_map)}, delinked={len(delink_trays)}")
        return JsonResponse({
            "success": True,
            "lot_id": lot_id,
            "submission_type": submission.submission_type,
            "accepted_qty": submission.accepted_qty,
            "rejected_qty": submission.rejected_qty,
            "total_lot_qty": submission.total_lot_qty,
            "trays": trays,
        })

    elif action == 'ALLOCATE':
        lot_id = request.data.get('lot_id')
        rejected_qty = int(request.data.get('rejected_qty', 0))
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        try:
            stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return JsonResponse({"success": False, "error": "Lot not found"}, status=404)
        tray_data, source, total_qty = _resolve_lot_trays(lot_id)
        active_trays = [t for t in tray_data if not t.get('is_delinked') and not t.get('is_rejected')]
        # Adjust total_qty when IS did partial rejection (original tray qtys are not reduced by IS)
        # Skip when source=IPTrayId — those quantities are already post-IS-rejection adjusted
        if source != "IPTrayId" and getattr(stock, 'few_cases_accepted_Ip_stock', False):
            _is_rej_store = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            _is_rej_qty = (_is_rej_store.total_rejection_quantity if _is_rej_store and _is_rej_store.total_rejection_quantity else 0)
            _ip_acc_qty = stock.total_IP_accpeted_quantity or 0
            if _ip_acc_qty > 0:
                total_qty = max(_ip_acc_qty - _is_rej_qty, 0)
            elif _is_rej_qty > 0:
                total_qty = max(total_qty - _is_rej_qty, 0)

        # ── IS Partial Accept: use child snapshot trays, not parent's raw trays ──
        # When IS did a partial accept the parent lot still holds the original trays
        # (all 7 etc.). We must surface only the child-accepted trays from
        # IS_PartialAcceptLot.trays_snapshot so the allocation chips match reality.
        if getattr(stock, 'few_cases_accepted_Ip_stock', False):
            from InputScreening.models import IS_PartialAcceptLot
            _is_child = IS_PartialAcceptLot.objects.filter(
                parent_lot_id=lot_id
            ).order_by('-created_at').first()
            if _is_child and _is_child.trays_snapshot:
                _snap_trays = [
                    {
                        "tray_id": t.get("tray_id", ""),
                        "qty": int(t.get("qty") or 0),
                        "is_top": bool(t.get("top_tray", False)),
                        "is_rejected": False,
                        "is_delinked": False,
                    }
                    for t in _is_child.trays_snapshot
                    if t.get("tray_id") and int(t.get("qty") or 0) > 0
                ]
                if _snap_trays:
                    active_trays = _snap_trays
                    total_qty = int(_is_child.accepted_qty or total_qty)
                    logger.info(
                        f"[ACTION:ALLOCATE] IS-partial-accept lot {lot_id}: "
                        f"overriding active_trays with {len(active_trays)} snapshot trays, qty={total_qty}"
                    )

        tray_capacity = 0
        if stock.batch_id:
            tray_capacity = stock.batch_id.tray_capacity or 0
        if rejected_qty < 0 or rejected_qty > total_qty:
            return JsonResponse({"success": False, "error": "Invalid rejected_qty"}, status=400)
        accepted_qty = total_qty - rejected_qty

        def compute_slots(qty, capacity):
            if qty <= 0 or capacity <= 0:
                return []
            full_trays = qty // capacity
            remainder = qty % capacity
            slots = []
            if remainder > 0:
                # Has remainder: first slot is top with remainder qty
                slots.append({"qty": remainder, "is_top": True, "tray_id": None})
                # Then full capacity trays as non-top
                for i in range(full_trays):
                    slots.append({"qty": capacity, "is_top": False, "tray_id": None})
            else:
                # No remainder: first full capacity tray is top, rest are non-top
                slots.append({"qty": capacity, "is_top": True, "tray_id": None})
                for i in range(full_trays - 1):
                    slots.append({"qty": capacity, "is_top": False, "tray_id": None})
            return slots

        accept_slots = compute_slots(accepted_qty, tray_capacity) if accepted_qty > 0 else []
        reject_slots = compute_slots(rejected_qty, tray_capacity) if rejected_qty > 0 else []
        unmapped_trays = [t for t in active_trays]

        # Compute deterministic reuse eligibility
        reuse_result = compute_reuse_trays(
            [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in active_trays],
            rejected_qty
        )

        logger.info(f"[ACTION:ALLOCATE] lot_id={lot_id}, total={total_qty}, rej={rejected_qty}, acc={accepted_qty}, reuse={reuse_result['reuse_trays']}")
        return JsonResponse({
            "success": True,
            "lot_id": lot_id,
            "total_qty": total_qty,
            "tray_capacity": tray_capacity,
            "accepted_qty": accepted_qty,
            "rejected_qty": rejected_qty,
            "accept_slots": accept_slots,
            "reject_slots": reject_slots,
            "original_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in active_trays],
            "unmapped_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in unmapped_trays],
            "reuse_trays": reuse_result["reuse_trays"],
            "reuse_count": len(reuse_result["reuse_trays"]),
            "reuse_updated_trays": reuse_result["updated_trays"],
        })

    elif action == 'VALIDATE_TRAY':
        tray_id = request.data.get('tray_id', '').strip().upper()  # ✅ FIX: Convert to uppercase
        lot_id = request.data.get('lot_id', '').strip()
        if not tray_id:
            return JsonResponse({"valid": False, "error": "tray_id is required"}, status=400)
        
        # ✅ FIX: Check if tray was REJECTED in Input Screening (permanently ineligible)
        # Check 1: IPTrayId flag (set by our services_reject.py fix for new submissions)
        ip_rejected = IPTrayId.objects.filter(
            tray_id=tray_id, rejected_tray=True
        ).exists()
        if ip_rejected:
            return JsonResponse({"valid": False, "error": "Tray was rejected in Input Screening - permanently ineligible for reuse", "selected_tray_id": tray_id, "auto_selected": True})

        # ✅ ERR2 FIX: Check IS_PartialRejectLot.trays_snapshot directly — this covers
        # historical rejections where the rejected_tray flag was not set at the time.
        # trays_snapshot is a JSON list: [{tray_id, qty, reason_id, ...}, ...]
        is_partial_rejected = IS_PartialRejectLot.objects.filter(
            trays_snapshot__contains=[{"tray_id": tray_id}]
        ).exists()
        if is_partial_rejected:
            return JsonResponse({"valid": False, "error": "Tray was rejected in Input Screening - permanently ineligible for reuse", "selected_tray_id": tray_id, "auto_selected": True})
        
        # Check TrayId master table
        tray = TrayId.objects.filter(tray_id=tray_id).first()
        if not tray:
            # Attempt prefix-based auto-select when user types >=9 chars
            if len(tray_id) >= 9:
                prefix = tray_id[:9]
                candidates = list(TrayId.objects.filter(
                    tray_id__istartswith=prefix,
                ).values_list('tray_id', flat=True)[:10])
                if len(candidates) == 1:
                    # Single candidate found — evaluate eligibility
                    cand = TrayId.objects.filter(tray_id=candidates[0]).first()
                    if cand.rejected_tray:
                        return JsonResponse({"valid": False, "error": "Tray is permanently rejected in master table", "selected_tray_id": cand.tray_id, "auto_selected": True})
                    if cand.scanned:
                        return JsonResponse({"valid": False, "error": "Tray is currently scanned/in-use", "selected_tray_id": cand.tray_id, "auto_selected": True})
                    # Check cross-module occupancy
                    occ_found = False
                    for qs, module_name in [
                        (IPTrayId.objects.filter(tray_id=cand.tray_id, rejected_tray=False, delink_tray=False, lot_id__isnull=False).exclude(lot_id=lot_id), "Input Screening"),
                        (BrassTrayId.objects.filter(tray_id=cand.tray_id, rejected_tray=False, delink_tray=False, lot_id__isnull=False).exclude(lot_id=lot_id), "Brass QC"),
                        (IQFTrayId.objects.filter(tray_id=cand.tray_id, rejected_tray=False, delink_tray=False, lot_id__isnull=False).exclude(lot_id=lot_id), "IQF"),
                    ]:
                        if qs.exists():
                            occ_found = True
                            break
                    if occ_found:
                        return JsonResponse({"valid": False, "error": f"Tray is currently occupied in {module_name}", "selected_tray_id": cand.tray_id, "auto_selected": True})
                    return JsonResponse({"valid": True, "auto_selected": True, "selected_tray_id": cand.tray_id})
                if candidates:
                    return JsonResponse({"valid": False, "error": "Multiple matching trays found", "candidates": candidates}, status=400)

            return JsonResponse({"valid": False, "error": "Tray ID not found in system"}, status=404)

        if tray.lot_id and tray.lot_id != lot_id:
            return JsonResponse({"valid": False, "error": "Tray is currently occupied", "selected_tray_id": tray.tray_id, "auto_selected": True})
        if tray.rejected_tray:
            return JsonResponse({"valid": False, "error": "Tray is permanently rejected in master table", "selected_tray_id": tray.tray_id, "auto_selected": True})
        if tray.scanned:
            return JsonResponse({"valid": False, "error": "Tray is currently scanned/in-use", "selected_tray_id": tray.tray_id, "auto_selected": True})
        
        # ── Dynamic cross-module occupancy check ──
        # Each check returns the module name so the error is always accurate.
        occupancy_checks = [
            (IPTrayId.objects.filter(
                tray_id=tray_id, rejected_tray=False, delink_tray=False, lot_id__isnull=False
             ).exclude(lot_id=lot_id), "Input Screening"),
            (BrassTrayId.objects.filter(
                tray_id=tray_id, rejected_tray=False, delink_tray=False, lot_id__isnull=False
             ).exclude(lot_id=lot_id), "Brass QC"),
            (IQFTrayId.objects.filter(
                tray_id=tray_id, rejected_tray=False, delink_tray=False, lot_id__isnull=False
             ).exclude(lot_id=lot_id), "IQF"),
        ]
        for qs, module_name in occupancy_checks:
            # Only surface the module name to frontend; never expose lot IDs in HTML/UI
            if qs.exists():
                return JsonResponse({
                    "valid": False,
                    "error": f"Tray is currently occupied in {module_name}",
                    "selected_tray_id": tray_id,
                    "auto_selected": True,
                })

        return JsonResponse({"valid": True})

    elif action == 'GET_REASONS':
        reasons = Brass_QC_Rejection_Table.objects.all().order_by('rejection_reason_id')
        data = [
            {"id": r.id, "reason_id": r.rejection_reason_id, "reason": r.rejection_reason}
            for r in reasons
        ]
        logger.info(
            "[BRASS_QC][GET_REASONS] ✅ Returning %d rejection reasons",
            len(data)
        )
        return JsonResponse({"success": True, "reasons": data})

    elif action == 'SAVE_DRAFT':
        lot_id = request.data.get('lot_id')
        draft_payload = request.data.get('draft_data', {})
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        if not draft_payload:
            return JsonResponse({"success": False, "error": "draft_data is required"}, status=400)
        try:
            stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return JsonResponse({"success": False, "error": "Lot not found"}, status=404)
        # Prevent draft save if already fully submitted
        if Brass_QC_Submission.objects.filter(lot_id=lot_id, is_completed=True).exists():
            return JsonResponse({"success": False, "error": "Lot already submitted — cannot save draft"}, status=409)
        draft, created = Brass_QC_Draft_Store.objects.update_or_create(
            lot_id=lot_id,
            draft_type='rejection_draft',
            defaults={
                'batch_id': stock.batch_id.batch_id if stock.batch_id else '',
                'user': request.user,
                'draft_data': draft_payload,
            }
        )
        # Generate transition lot_id for draft
        if not draft.draft_transition_lot_id:
            draft.draft_transition_lot_id = generate_new_lot_id("DRAFT")
            draft.save(update_fields=['draft_transition_lot_id'])
            logger.info(f"[DRAFT TRANSITION] lot_id={lot_id} → draft_transition_lot_id={draft.draft_transition_lot_id}")
        stock.brass_draft = True
        stock.brass_onhold_picking = True
        stock.save(update_fields=['brass_draft', 'brass_onhold_picking'])
        logger.info(f"[DRAFT] Saved for lot_id={lot_id}, user={request.user}, created={created}")
        return JsonResponse({
            "success": True,
            "lot_id": lot_id,
            "draft_id": draft.id,
            "draft_transition_lot_id": draft.draft_transition_lot_id,
            "message": "Draft saved. Lot marked as Draft.",
            "lot_status": "Draft",
            "action_state": "ONHOLD_TOPTRAY",
        })

    elif action == 'GET_DRAFT':
        lot_id = request.data.get('lot_id')
        if not lot_id:
            return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)
        draft = Brass_QC_Draft_Store.objects.filter(lot_id=lot_id, draft_type='rejection_draft').first()
        if not draft:
            return JsonResponse({"success": True, "has_draft": False, "draft_data": None, "lot_id": lot_id})
        logger.info(f"[DRAFT] Fetched for lot_id={lot_id}, user={request.user}")
        return JsonResponse({
            "success": True,
            "has_draft": True,
            "draft_data": draft.draft_data,
            "lot_id": lot_id,
        })

    elif action in ('FULL_ACCEPT', 'FULL_REJECT', 'PARTIAL', 'PROCESS', 'SAVE_REMARK'):
        # Delegate to submission service
        return handle_submission(request, action)

    else:
        return JsonResponse({"success": False, "error": f"Unknown action: {action}"}, status=400)


# ═══════════════════════════════════════════════════════════════
# Transition Lot ID Generator — delegates to lot_service
# ═══════════════════════════════════════════════════════════════
def generate_new_lot_id(submission_type=""):
    """
    Generate unique lot ID — delegates to lot_service.generate_lot_id.
    Kept here for backward compatibility.
    """
    return generate_lot_id(submission_type)


def _handle_submission(request, action):
    """
    Internal submission handler — delegates to submission_service.handle_submission.
    Kept here for backward compatibility with legacy submit_brass_qc endpoint.
    """
    return handle_submission(request, action)



# ── Legacy endpoints (delegate to unified API) ──

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_tray_details(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return JsonResponse({"error": "lot_id is required"}, status=400)

    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return JsonResponse({"error": "Lot not found"}, status=404)

    tray_data, source, total_qty = _resolve_lot_trays(lot_id)

    # Include tray capacity from batch
    tray_capacity = 0
    if stock.batch_id:
        tray_capacity = stock.batch_id.tray_capacity or 0

    # Filter out delinked and rejected trays for display
    active_trays = [t for t in tray_data if not t.get('is_delinked') and not t.get('is_rejected')]

    logger.info(f"[TRAY DETAILS] lot_id={lot_id}, source={source}, trays={len(active_trays)}, total_qty={total_qty}, tray_capacity={tray_capacity}")

    return JsonResponse({
        "lot_id": lot_id,
        "batch_id": stock.batch_id.batch_id if stock.batch_id else "",
        "total_qty": total_qty,
        "tray_capacity": tray_capacity,
        "source": source,
        "trays": active_trays,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def validate_tray_id(request):
    """Validate a tray ID before assigning it to a slot.
    Checks: (1) tray exists in TrayId table, (2) not occupied by a different lot.
    """
    tray_id = request.GET.get('tray_id', '').strip()
    lot_id = request.GET.get('lot_id', '').strip()

    if not tray_id:
        return JsonResponse({"valid": False, "error": "tray_id is required"}, status=400)

    tray = TrayId.objects.filter(tray_id=tray_id).first()
    if not tray:
        # Attempt auto-selection when user has typed 9+ characters
        if len(tray_id) >= 9:
            prefix = tray_id[:9]
            candidates = list(TrayId.objects.filter(
                tray_id__istartswith=prefix,
                rejected_tray=False,
                delink_tray=False
            ).values_list('tray_id', flat=True)[:10])

            if len(candidates) == 1:
                return JsonResponse({"valid": True, "auto_selected": True, "selected_tray_id": candidates[0]})
            if candidates:
                return JsonResponse({"valid": False, "error": "Multiple matching trays found", "candidates": candidates}, status=400)

            # expand search to related tables
            other_candidates = []
            for m in (IPTrayId, BrassTrayId, IQFTrayId):
                other_candidates.extend(list(m.objects.filter(
                    tray_id__istartswith=prefix,
                    rejected_tray=False,
                    delink_tray=False
                ).values_list('tray_id', flat=True)[:10]))

            if len(other_candidates) == 1:
                return JsonResponse({"valid": True, "auto_selected": True, "selected_tray_id": other_candidates[0]})
            if other_candidates:
                return JsonResponse({"valid": False, "error": "Multiple matching trays found", "candidates": other_candidates}, status=400)

        return JsonResponse({"valid": False, "error": "Tray ID not found in system"}, status=404)

    if tray.lot_id and tray.lot_id != lot_id:
        return JsonResponse({"valid": False, "error": f"Tray belongs to lot {tray.lot_id}"})

    return JsonResponse({"valid": True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def allocate_trays(request):
    """
    Backend-driven tray allocation engine.
    Given lot_id and rejected_qty, computes how trays should be distributed
    between accept and reject groups based on tray_capacity.
    Returns slot structure for both accept and reject sections.
    """
    lot_id = request.data.get('lot_id')
    rejected_qty = int(request.data.get('rejected_qty', 0))

    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)

    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    tray_data, source, total_qty = _resolve_lot_trays(lot_id)
    active_trays = [t for t in tray_data if not t.get('is_delinked')]

    tray_capacity = 0
    if stock.batch_id:
        tray_capacity = stock.batch_id.tray_capacity or 0

    if rejected_qty < 0 or rejected_qty > total_qty:
        return JsonResponse({"success": False, "error": "Invalid rejected_qty"}, status=400)

    accepted_qty = total_qty - rejected_qty

    # ── Compute tray slot distribution ──
    # Pattern: top tray gets the remainder, other trays get full capacity
    # e.g. accept_qty=25, capacity=16 → slots: [9 (top), 16]
    # e.g. reject_qty=20, capacity=16 → slots: [4 (top), 16]

    def compute_slots(qty, capacity):
        """Compute tray slot quantities. Top tray gets remainder, or first full tray if no remainder."""
        if qty <= 0 or capacity <= 0:
            return []
        full_trays = qty // capacity
        remainder = qty % capacity
        slots = []
        if remainder > 0:
            # Has remainder: first slot is top with remainder qty
            slots.append({"qty": remainder, "is_top": True, "tray_id": None})
            # Then full capacity trays as non-top
            for i in range(full_trays):
                slots.append({"qty": capacity, "is_top": False, "tray_id": None})
        else:
            # No remainder: first full capacity tray is top, rest are non-top
            slots.append({"qty": capacity, "is_top": True, "tray_id": None})
            for i in range(full_trays - 1):
                slots.append({"qty": capacity, "is_top": False, "tray_id": None})
        return slots

    accept_slots = compute_slots(accepted_qty, tray_capacity) if accepted_qty > 0 else []
    reject_slots = compute_slots(rejected_qty, tray_capacity) if rejected_qty > 0 else []

    # ── Auto-map original trays to slots (best-fit by qty) ──
    sorted_originals = sorted(active_trays, key=lambda t: (not t.get('is_top'), t.get('tray_id', '')))

    used_tray_ids = set()

    def auto_map_slots(slots, originals, used_ids):
        """Try to map original trays to slots by matching qty."""
        for slot in slots:
            for orig in originals:
                if orig['tray_id'] in used_ids:
                    continue
                if orig['qty'] == slot['qty']:
                    slot['tray_id'] = orig['tray_id']
                    if slot['is_top']:
                        slot['is_top'] = True
                    used_ids.add(orig['tray_id'])
                    break

    # ERR2: Do not auto-map — user assigns trays manually
    # auto_map_slots(accept_slots, sorted_originals, used_tray_ids)
    # auto_map_slots(reject_slots, sorted_originals, used_tray_ids)

    unmapped_trays = [t for t in active_trays if t['tray_id'] not in used_tray_ids]

    logger.info(f"[ALLOCATE] lot_id={lot_id}, total={total_qty}, rej={rejected_qty}, acc={accepted_qty}, "
                f"accept_slots={len(accept_slots)}, reject_slots={len(reject_slots)}, unmapped={len(unmapped_trays)}")

    return JsonResponse({
        "success": True,
        "lot_id": lot_id,
        "total_qty": total_qty,
        "tray_capacity": tray_capacity,
        "accepted_qty": accepted_qty,
        "rejected_qty": rejected_qty,
        "accept_slots": accept_slots,
        "reject_slots": reject_slots,
        "original_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in active_trays],
        "unmapped_trays": [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t.get("is_top", False)} for t in unmapped_trays],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_brass_qc(request):
    """
    SINGLE unified submission API for Brass QC.
    Handles: FULL_ACCEPT, FULL_REJECT, PARTIAL
    Frontend sends: { lot_id, action, rejection_reasons?, accepted_tray_ids?, remarks? }
    Backend resolves trays, computes qty, stores submission, moves stage.
    """
    data = request.data
    lot_id = data.get("lot_id")
    action = data.get("action", "FULL_ACCEPT")  # FULL_ACCEPT | FULL_REJECT | PARTIAL
    rejection_reasons = data.get("rejection_reasons", [])  # [{reason_id, qty}]
    accepted_tray_ids = data.get("accepted_tray_ids", [])   # [tray_id, ...]
    rejected_tray_ids = data.get("rejected_tray_ids", [])   # [tray_id, ...]  user-selected
    remarks = data.get("remarks", "").strip()

    logger.info(f"[QC SUBMIT] [INPUT] lot_id={lot_id}, action={action}, user={request.user}, reasons={len(rejection_reasons)}")

    # ── Validation ──
    if not lot_id:
        return JsonResponse({"success": False, "error": "lot_id is required"}, status=400)

    if action not in ("FULL_ACCEPT", "FULL_REJECT", "PARTIAL", "SAVE_REMARK", "PROCESS"):
        return JsonResponse({"success": False, "error": f"Invalid action: {action}"}, status=400)

    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return JsonResponse({"success": False, "error": "Lot not found"}, status=404)

    # ── SAVE_REMARK action: just save remark, no stage movement ──
    if action == "SAVE_REMARK":
        remark_text = remarks
        if not remark_text:
            return JsonResponse({"success": False, "error": "Remark text is required"}, status=400)
        if len(remark_text) > 100:
            return JsonResponse({"success": False, "error": "Remark must be 100 characters or less"}, status=400)

        stock.Bq_pick_remarks = remark_text
        stock.save(update_fields=['Bq_pick_remarks'])
        logger.info(f"[QC SUBMIT] [REMARK] lot_id={lot_id}, remark saved by {request.user}")

        return JsonResponse({
            "success": True,
            "lot_id": lot_id,
            "message": "Remark saved successfully",
            "has_remark": True,
        })

    # ── Duplicate submission prevention ──
    from .models import Brass_QC_Submission
    existing = Brass_QC_Submission.objects.filter(lot_id=lot_id, is_completed=True).first()
    if existing:
        logger.warning(f"[QC SUBMIT] Duplicate blocked: lot_id={lot_id}, existing_id={existing.id}")
        return JsonResponse({
            "success": False,
            "error": "This lot has already been submitted",
            "existing_submission_id": existing.id,
            "existing_type": existing.submission_type,
        }, status=409)

    # ── Backend resolves trays (SINGLE query path) ──
    tray_data, source, total_qty = _resolve_lot_trays(lot_id)

    logger.info(f"[QC SUBMIT] [VALIDATION] action={action}, source={source}, trays_count={len(tray_data)}, total_qty={total_qty}")

    if not tray_data:
        return JsonResponse({"success": False, "error": "No tray data found for this lot"}, status=400)

    if total_qty <= 0:
        return JsonResponse({"success": False, "error": "Total lot quantity is zero"}, status=400)

    # ── Active (non-delinked) trays ──
    active_trays = [t for t in tray_data if not t["is_delinked"]]

    # ── Compute accepted/rejected based on action ──
    if action == "FULL_ACCEPT":
        submission_type = "FULL_ACCEPT"
        accepted_qty = total_qty
        rejected_qty = 0
        accepted_trays = [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]} for t in active_trays]
        rejected_trays = []

    elif action == "FULL_REJECT":
        submission_type = "FULL_REJECT"
        # Validate: rejection reasons must be provided
        if not rejection_reasons:
            return JsonResponse({"success": False, "error": "Rejection reasons are required for full reject"}, status=400)

        # Compute total reject qty from reasons
        total_reject_from_reasons = sum(int(r.get("qty", 0)) for r in rejection_reasons)
        logger.info(f"[QC SUBMIT] [CALC] total_reject_from_reasons={total_reject_from_reasons}, total_qty={total_qty}")

        if total_reject_from_reasons != total_qty:
            return JsonResponse({
                "success": False,
                "error": f"Rejection qty ({total_reject_from_reasons}) must equal total lot qty ({total_qty}) for full reject"
            }, status=400)

        accepted_qty = 0
        rejected_qty = total_qty
        accepted_trays = []
        # Use user-selected trays if provided, else all active trays
        if rejected_tray_ids:
            active_tray_map = {t["tray_id"]: t for t in active_trays}
            rejected_trays = [{"tray_id": tid, "qty": active_tray_map[tid]["qty"], "is_top": active_tray_map[tid]["is_top"]}
                              for tid in rejected_tray_ids if tid in active_tray_map]
        else:
            rejected_trays = [{"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]} for t in active_trays]

    elif action == "PARTIAL":
        submission_type = "PARTIAL"
        # Validate: rejection reasons must be provided
        if not rejection_reasons:
            return JsonResponse({"success": False, "error": "Rejection reasons are required for partial reject"}, status=400)

        # Compute total reject qty from reasons
        total_reject_from_reasons = sum(int(r.get("qty", 0)) for r in rejection_reasons)
        logger.info(f"[QC SUBMIT] [CALC] total_reject_from_reasons={total_reject_from_reasons}, total_qty={total_qty}")

        if total_reject_from_reasons <= 0:
            return JsonResponse({"success": False, "error": "Rejection qty must be greater than 0"}, status=400)

        if total_reject_from_reasons >= total_qty:
            return JsonResponse({"success": False, "error": "Partial reject qty must be less than total lot qty"}, status=400)

        rejected_qty = total_reject_from_reasons
        accepted_qty = total_qty - rejected_qty

        # Validate: accepted + rejected = total
        if accepted_qty + rejected_qty != total_qty:
            return JsonResponse({"success": False, "error": "Accepted + Rejected qty must equal total lot qty"}, status=400)

        # ── TRAY SEGREGATION (user-driven, backend validates) ──
        # User selects which trays carry rejected cases
        rejected_trays = []
        accepted_trays = []

        if rejected_tray_ids:
            # User-selected rejected trays
            active_tray_map = {t["tray_id"]: t for t in active_trays}
            invalid_reject_ids = [tid for tid in rejected_tray_ids if tid not in active_tray_map]
            if invalid_reject_ids:
                return JsonResponse({
                    "success": False,
                    "error": f"Invalid rejected tray IDs: {invalid_reject_ids}"
                }, status=400)

            for t in active_trays:
                if t["tray_id"] in rejected_tray_ids:
                    rejected_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
                else:
                    accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
        else:
            # Fallback: auto-segregation (top tray first) if no user selection
            remaining_reject = rejected_qty
            sorted_trays = sorted(active_trays, key=lambda t: (not t["is_top"]))

            for t in sorted_trays:
                if remaining_reject <= 0:
                    accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
                elif remaining_reject >= t["qty"]:
                    rejected_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
                    remaining_reject -= t["qty"]
                else:
                    rejected_trays.append({"tray_id": t["tray_id"], "qty": remaining_reject, "is_top": t["is_top"]})
                    accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"] - remaining_reject, "is_top": False})
                    remaining_reject = 0


# Raw Submission API - stores exact UI payload without transformation

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def brass_qc_raw_submission(request):
    """Raw submission API - stores exact UI payload without transformation."""
    data = request.data
    lot_id = data.get("lot_id", "").strip()
    batch_id = data.get("batch_id", "").strip()
    plating_stk_no = data.get("plating_stk_no", "").strip()
    submission_type = data.get("submission_type", "DRAFT").upper()
    
    logger.info(f"[RAW SUBMISSION] [INPUT] lot_id={lot_id}, type={submission_type}, user={request.user}")
    
    if not lot_id:
        logger.error("[RAW SUBMISSION] Missing lot_id")
        return JsonResponse({"status": "error", "message": "lot_id is required"}, status=400)
    
    if submission_type not in ("DRAFT", "SUBMIT"):
        logger.error(f"[RAW SUBMISSION] Invalid type: {submission_type}")
        return JsonResponse({"status": "error", "message": f"Invalid submission_type: {submission_type}"}, status=400)
    
    try:
        stock = TotalStockModel.objects.select_related('batch_id').get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        logger.error(f"[RAW SUBMISSION] Lot not found: {lot_id}")
        return JsonResponse({"status": "error", "message": "Lot not found"}, status=404)
    
    if submission_type == "SUBMIT":
        logger.info(f"[RAW SUBMISSION] Validating SUBMIT state for {lot_id}")
        total_lot_qty = data.get("total_lot_qty", 0)
        summary = data.get("summary", {})
        accepted = summary.get("accepted", 0)
        rejected = summary.get("rejected", 0)
        remarks = data.get("remarks", "").strip()
        
        if accepted + rejected != total_lot_qty:
            msg = f"Sum check failed: {accepted} + {rejected} != {total_lot_qty}"
            logger.error(f"[RAW SUBMISSION] {msg}")
            return JsonResponse({"status": "error", "message": msg}, status=400)
        
        accept_trays = data.get("accept_trays", [])
        accept_top_count = sum(1 for t in accept_trays if t.get("is_top", False))
        if accept_top_count != 1 and len(accept_trays) > 0:
            msg = f"Accept must have exactly ONE top tray (found {accept_top_count})"
            logger.error(f"[RAW SUBMISSION] {msg}")
            return JsonResponse({"status": "error", "message": msg}, status=400)
        
        reject_trays = data.get("reject_trays", [])
        if rejected > 0:
            reject_top_count = sum(1 for t in reject_trays if t.get("is_top", False))
            if reject_top_count > 1:
                msg = f"Reject cannot have more than ONE top tray (found {reject_top_count})"
                logger.error(f"[RAW SUBMISSION] {msg}")
                return JsonResponse({"status": "error", "message": msg}, status=400)
            
            if rejected == total_lot_qty and not remarks:
                msg = "Remarks are mandatory for full rejection"
                logger.error(f"[RAW SUBMISSION] {msg}")
                return JsonResponse({"status": "error", "message": msg}, status=400)
        
        logger.info(f"[RAW SUBMISSION] SUBMIT validation passed: accepted={accepted}, rejected={rejected}")
    
    all_trays_to_check = []
    for t in data.get("accept_trays", []):
        all_trays_to_check.append(t)
    for t in data.get("reject_trays", []):
        all_trays_to_check.append(t)
    for t in data.get("delink_trays", []):
        all_trays_to_check.append(t)
    
    created_trays = []
    for tray in all_trays_to_check:
        tray_id = tray.get("tray_id", "").strip()
        if not tray_id:
            continue
        
        existing = TrayId.objects.filter(tray_id=tray_id).first()
        if not existing:
            try:
                new_tray = TrayId.objects.create(
                    lot_id=lot_id,
                    tray_id=tray_id,
                    tray_quantity=tray.get("qty", 0),
                    top_tray=tray.get("is_top", False),
                    delink_tray=tray_id in [d.get("tray_id", "") for d in data.get("delink_trays", [])]
                )
                created_trays.append({
                    "tray_id": tray_id,
                    "qty": tray.get("qty", 0),
                    "type": tray.get("type", "NEW"),
                    "is_top": tray.get("is_top", False)
                })
                logger.info(f"[RAW SUBMISSION] Created tray: {tray_id}")
            except Exception as e:
                logger.error(f"[RAW SUBMISSION] Error creating tray {tray_id}: {e}")
    
    try:
        raw_submission = Brass_QC_RawSubmission.objects.create(
            lot_id=lot_id,
            batch_id=batch_id,
            plating_stk_no=plating_stk_no,
            payload=data,
            submission_type=submission_type,
            created_by=request.user
        )
        logger.info(f"[RAW SUBMISSION] Saved: id={raw_submission.id}, lot_id={lot_id}, type={submission_type}")
        logger.info(f"[RAW SUBMISSION] Created trays: {len(created_trays)}")
        logger.info(f"[RAW SUBMISSION] Summary - accepted: {data.get('summary', {}).get('accepted', 0)}, rejected: {data.get('summary', {}).get('rejected', 0)}")
        
        return JsonResponse({
            "status": "success",
            "submission_type": submission_type,
            "lot_id": lot_id,
            "message": f"Saved successfully ({submission_type})",
            "submission_id": raw_submission.id,
            "created_trays": created_trays
        })
    
    except Exception as e:
        logger.error(f"[RAW SUBMISSION] Error saving submission: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": f"Error saving submission: {str(e)}"}, status=500)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.shortcuts import redirect
from django.db.models import OuterRef, Subquery, Exists, F, Sum
from django.core.paginator import Paginator
from django.templatetags.static import static
import math
from Brass_QC.models import *
from BrassAudit.models import *
from InputScreening.models import *
from DayPlanning.models import *
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
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from math import ceil
from django.utils import timezone
from datetime import datetime, timedelta
import pytz
from django.db.models import Sum
from django.views.decorators.http import require_http_methods
from django.views import View
from django.db.models import Sum, F, Func, IntegerField
from django.db import transaction
from collections import OrderedDict



def generate_new_lot_id():
        from datetime import datetime
        timestamp = datetime.now().strftime("%d%m%Y%H%M%S")
        last_lot = TotalStockModel.objects.order_by('-id').first()
        if last_lot and last_lot.lot_id and last_lot.lot_id.startswith("LID"):
            last_seq_no = int(last_lot.lot_id[-4:])
            next_seq_no = last_seq_no + 1
        else:
            next_seq_no = 1
        seq_no = f"{next_seq_no:04d}"
        return f"LID{timestamp}{seq_no}"


def build_ui_state(data):
    """Compute ALL UI state for a single IQF pick table row.

    Frontend becomes pure render layer — zero business logic in templates.
    Backend is SINGLE SOURCE OF TRUTH for button states, labels, colors, permissions.

    Returns a dict that the template accesses via {{ data.ui.* }}
    """
    hold_lot = bool(data.get('iqf_hold_lot'))
    verified = bool(data.get('iqf_accepted_qty_verified'))
    acceptance = bool(data.get('iqf_acceptance'))
    rejection = bool(data.get('iqf_rejection'))
    few_cases = bool(data.get('iqf_few_cases_acceptance'))
    onhold = bool(data.get('iqf_onhold_picking'))
    draft = bool(data.get('Draft_Saved'))
    has_remarks = bool(data.get('IQF_pick_remarks'))
    holding_reason = data.get('iqf_holding_reason') or ''
    release_reason = data.get('iqf_release_reason') or ''
    release_lot = bool(data.get('iqf_release_lot'))
    last_module = data.get('last_process_module') or ''

    # ── Row CSS class ──
    row_blur = 'row-inactive-blur' if hold_lot else ''

    # ── Action state machine — ONE decision, backend-only ──
    if acceptance:
        action_type = 'ACCEPTED'
    elif onhold:
        action_type = 'VERIFY'
    elif rejection or few_cases:
        action_type = 'REJECTED'
    elif verified:
        action_type = 'AUDIT_ENABLED'
    else:
        action_type = 'AUDIT_DISABLED'

    # ── Lot status pill — pre-computed label + colors ──
    if hold_lot:
        status_pill = {'label': 'On Hold', 'border': '#dc3545', 'bg': '#f8d7da', 'text': '#721c24'}
    elif draft:
        status_pill = {'label': 'Draft', 'border': '#4997ac', 'bg': '#d1f2f3', 'text': '#03425d'}
    elif rejection or few_cases or acceptance:
        status_pill = {'label': 'Yet to Release', 'border': '#0d5d17', 'bg': '#c5f9c2', 'text': '#2f801b'}
    else:
        status_pill = {'label': 'Yet to Start', 'border': '#f9a825', 'bg': '#fff8e1', 'text': '#b26a00'}

    # ── Process status circles ──
    q_color = '#0c8249' if verified else '#bdbdbd'
    if rejection or acceptance or few_cases:
        qc_style = 'background-color: #0c8249'
    elif draft:
        qc_style = 'background: linear-gradient(to right, #0c8249 50%, #bdbdbd 50%)'
    else:
        qc_style = 'background-color: #bdbdbd'

    # ── Hold/release info ──
    show_hold_info = bool(hold_lot or release_lot or holding_reason or release_reason)
    tooltip_parts = []
    if holding_reason:
        tooltip_parts.append(f'Holding Reason: {holding_reason}')
    if release_reason:
        tooltip_parts.append(f'Release Reason: {release_reason}')
    hold_tooltip = '\n'.join(tooltip_parts)

    # ── Permissions ──
    can_delete = verified
    allow_remarks = not (acceptance or rejection or few_cases)

    # ── Current stage colors ──
    stage_map = {
        'Input screening': {'border': '#0d5d17', 'bg': '#c5f9c2', 'text': '#2f801b'},
        'IQF': {'border': '#f9a825', 'bg': '#fff8e1', 'text': '#b26a00'},
        'DayPlanning': {'border': '#1976d2', 'bg': '#d1eaff', 'text': '#033b5d'},
    }
    stage = stage_map.get(last_module, {'border': '#9adeed', 'bg': '#d1edf3', 'text': '#033b5d'})

    ui = {
        'row_blur': row_blur,
        'hold_lot': hold_lot,
        'action_type': action_type,
        'status_pill': status_pill,
        'q_color': q_color,
        'qc_style': qc_style,
        'show_hold_info': show_hold_info,
        'hold_tooltip': hold_tooltip,
        'can_delete': can_delete,
        'allow_remarks': allow_remarks,
        'qty_verified': verified,
        'remarks_saved': has_remarks,
        'stage': stage,
    }
    print(f"[UI_STATE] lot={data.get('stock_lot_id')}, action={action_type}, status={status_pill['label']}")
    return ui

    
@method_decorator(login_required, name='dispatch')    
class IQFPickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'IQF/Iqf_PickTable.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False

        lot_id = request.GET.get('lot_id')
        iqf_rejection_reasons = IQF_Rejection_Table.objects.all()

        # ✅ CHANGED: Query TotalStockModel directly instead of ModelMasterCreation
        brass_rejection_qty_subquery = Brass_QC_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        brass_audit_rejection_qty_subquery = Brass_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        iqf_rejection_qty_subquery = IQF_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = TotalStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            batch_id__total_batch_quantity__gt=0
        ).annotate(
            wiping_required=F('batch_id__model_stock_no__wiping_required'),
            brass_rejection_total_qty=brass_rejection_qty_subquery,
            brass_audit_rejection_qty=brass_audit_rejection_qty_subquery,
            iqf_rejection_qty=iqf_rejection_qty_subquery,
        ).filter(
            # ✅ Direct filtering on TotalStockModel fields (no more subquery filtering)
            Q(send_brass_audit_to_iqf=True)
        ).exclude(
            Q(brass_audit_accptance=True) |
            Q(iqf_acceptance=True) |
            Q(iqf_rejection=True) |
            Q(send_brass_audit_to_iqf=True, brass_audit_onhold_picking=True)|
            Q(iqf_few_cases_acceptance=True, iqf_onhold_picking=False)
        ).order_by('-bq_last_process_date_time', '-lot_id')

        print(f"📊 Found {queryset.count()} IQF pick records")
        print("All lot_ids in IQF pick queryset:", list(queryset.values_list('lot_id', flat=True)))

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        # ✅ UPDATED: Build master_data from TotalStockModel records
        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            
            # ✅ CHECK FOR IQF-SPECIFIC DRAFTS ONLY WHERE is_draft = True
            iqf_has_drafts = (
                IQF_Draft_Store.objects.filter(lot_id=stock_obj.lot_id, draft_data__is_draft=True).exists() or
                IQF_Accepted_TrayID_Store.objects.filter(lot_id=stock_obj.lot_id, is_draft=True).exists()
            )
            
            data = {
                # ✅ Batch fields from foreign key
                'batch_id': batch.batch_id,
                'bq_last_process_date_time': stock_obj.bq_last_process_date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no,
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'Moved_to_D_Picker': batch.Moved_to_D_Picker,
                'Draft_Saved': iqf_has_drafts,  # ✅ USE IQF-SPECIFIC DRAFTS INSTEAD OF GLOBAL Draft_Saved
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                
                # ✅ Stock-related fields from TotalStockModel
                'lot_id': stock_obj.lot_id,
                'stock_lot_id': stock_obj.lot_id,
                'last_process_module': stock_obj.last_process_module,
                'next_process_module': stock_obj.next_process_module,
                'wiping_required': stock_obj.wiping_required,
                'iqf_missing_qty': stock_obj.iqf_missing_qty,
                'iqf_physical_qty': stock_obj.iqf_physical_qty,
                'iqf_physical_qty_edited': stock_obj.iqf_physical_qty_edited,
                'accepted_tray_scan_status': stock_obj.accepted_tray_scan_status,
                'iqf_rejection_qty': stock_obj.iqf_rejection_qty,
                'iqf_accepted_qty': stock_obj.iqf_accepted_qty,
                'IQF_pick_remarks': stock_obj.IQF_pick_remarks,
                'Bq_pick_remarks': stock_obj.Bq_pick_remarks,
                'BA_pick_remarks': stock_obj.BA_pick_remarks,
                'brass_rejection_total_qty': stock_obj.brass_rejection_total_qty,
                'brass_audit_rejection_qty': stock_obj.brass_audit_rejection_qty,
                'brass_qc_few_cases_accptance': stock_obj.brass_qc_few_cases_accptance,
                'iqf_accepted_qty_verified': stock_obj.iqf_accepted_qty_verified,
                'iqf_acceptance': stock_obj.iqf_acceptance,
                'iqf_rejection': stock_obj.iqf_rejection,
                'brass_audit_few_cases_accptance': stock_obj.brass_audit_few_cases_accptance,
                'iqf_few_cases_acceptance': stock_obj.iqf_few_cases_acceptance,
                'iqf_onhold_picking': stock_obj.iqf_onhold_picking,
                'brass_onhold_picking': stock_obj.brass_onhold_picking,
                'iqf_hold_lot': stock_obj.iqf_hold_lot,
                'iqf_holding_reason': stock_obj.iqf_holding_reason,
                'iqf_release_lot': stock_obj.iqf_release_lot,
                'iqf_release_reason': stock_obj.iqf_release_reason,
                'brass_audit_onhold_picking': stock_obj.brass_audit_onhold_picking,
                'send_brass_audit_to_iqf': stock_obj.send_brass_audit_to_iqf,  # ✅ Direct access
                'total_IP_accpeted_quantity': stock_obj.total_IP_accpeted_quantity,
            }
            # Attach tray details from IQFTrayId as backend single source of truth
            try:
                # Use lot + batch as single-source filter (no cross-app calls)
                trays_qs = IQFTrayId.objects.filter(lot_id=stock_obj.lot_id, batch_id=batch)
                tray_list = []
                for t in trays_qs:
                    tray_list.append({
                        'id': t.tray_id,
                        'qty': t.tray_quantity
                    })
                data['tray_details'] = tray_list
                try:
                    data['tray_details_json'] = json.dumps(tray_list)
                except Exception:
                    data['tray_details_json'] = '[]'
            except Exception:
                data['tray_details'] = []
                data['tray_details_json'] = '[]'

            master_data.append(data)

        print(f"[IQFPickTableView] Total master_data records: {len(master_data)}")
        
        # ✅ Process the data (same logic as before)
        for data in master_data:
            print(data['batch_id'], data['brass_rejection_total_qty'])

        for data in master_data:
            brass_rejection_total_qty = data.get('brass_rejection_total_qty') or 0
            tray_capacity = data.get('tray_capacity') or 0
            brass_audit_rejection_qty = data.get('brass_audit_rejection_qty') or 0

            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            
            # Use total_IP_accpeted_quantity if brass_rejection_total_qty is zero
            qty_for_trays = brass_rejection_total_qty if brass_rejection_total_qty > 0 else brass_audit_rejection_qty
            
            if tray_capacity and tray_capacity > 0:
                data['no_of_trays'] = math.ceil(qty_for_trays / tray_capacity)
            else:
                data['no_of_trays'] = 0

            # Get model images
            batch_obj = ModelMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj:
                model_master = batch_obj.model_stock_no
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            # Add available_qty and RW qty for each row
            lot_id = data.get('stock_lot_id')
            total_stock_obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
            if total_stock_obj:
                # Do NOT persist any healed physical qty here. Instead expose the rejected
                # quantity as `rw_qty` and keep available_qty strictly from real physical qty.
                current_physical_qty = total_stock_obj.iqf_physical_qty or 0

                # Determine rejection total from appropriate reason store (do not save)
                use_audit = getattr(total_stock_obj, 'send_brass_audit_to_iqf', False)
                reason_store = None
                try:
                    # Prefer explicit reason stores to derive origin (audit vs qc)
                    # Prefer Brass Audit when present (some lots originate from audit)
                    if Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).exists():
                        reason_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                        inferred_origin = 'Audit'
                    elif Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).exists():
                        reason_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                        inferred_origin = 'QC'
                    else:
                        # Fallback to existing flag
                        inferred_origin = 'Audit' if use_audit else 'QC'
                        if use_audit:
                            reason_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                        else:
                            reason_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                except Exception:
                    reason_store = None
                # expose inferred origin for template use (explicit override of send_brass_audit_to_iqf)
                data['brass_origin'] = inferred_origin

                rw_qty = (reason_store.total_rejection_quantity if reason_store and getattr(reason_store, 'total_rejection_quantity', 0) else 0)

                # available_qty should reflect actual physical qty (if any). If none, leave 0
                if current_physical_qty and current_physical_qty > 0:
                    data['available_qty'] = current_physical_qty
                else:
                    data['available_qty'] = 0

                # expose RW qty separately
                data['rw_qty'] = rw_qty
            else:
                data['available_qty'] = 0
                data['rw_qty'] = 0

            # Add display_physical_qty for frontend (STRICT: only from iqf_physical_qty)
            iqf_physical_qty = data.get('iqf_physical_qty', 0)
            data['display_physical_qty'] = iqf_physical_qty if (iqf_physical_qty and iqf_physical_qty > 0) else 0

            # ── Re-flagged lot fix: override rw_qty and no_of_trays from IQF_Submitted ──
            # For lots previously processed by IQF (FULL_ACCEPT / PARTIAL) that return
            # via Brass QC rejection, the reason-store subquery picks stale values.
            # Use the same source of truth as the iqf_tray_details API endpoint.
            try:
                iqf_sub = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()
                if iqf_sub and iqf_sub.submission_type in ('FULL_ACCEPT', 'PARTIAL'):
                    if iqf_sub.submission_type == 'FULL_ACCEPT' and iqf_sub.full_accept_data:
                        src_trays = iqf_sub.full_accept_data.get('trays', [])
                    elif iqf_sub.submission_type == 'PARTIAL' and iqf_sub.partial_accept_data:
                        src_trays = iqf_sub.partial_accept_data.get('trays', [])
                    else:
                        src_trays = []
                    live_rw = sum(int(t.get('qty', 0)) for t in src_trays if int(t.get('qty', 0)) > 0)
                    live_trays = len([t for t in src_trays if int(t.get('qty', 0)) > 0])
                    if live_rw > 0:
                        data['rw_qty'] = live_rw
                        data['no_of_trays'] = live_trays
                        print(f"[IQF PICK] Re-flagged lot {lot_id}: rw_qty={live_rw}, no_of_trays={live_trays} from IQF_Submitted")
            except Exception:
                pass  # Keep existing values on error

        print("Processed lot_ids:", [data['stock_lot_id'] for data in master_data])

        # ── ATTACH UI STATE — Backend drives ALL UI decisions ──
        for data in master_data:
            data['ui'] = build_ui_state(data)

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
            'iqf_rejection_reasons': iqf_rejection_reasons,
        }
        return Response(context, template_name=self.template_name)

# Audit modal single-source API: RW Qty + rejection reason table
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def iqf_rejection_audit_iqf_reject(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

    try:
        print(f"[AUDIT API] Input lot_id: {lot_id}")

        # 1. Get RW Qty (SOURCE OF TRUTH)
        reason_store = (
            Brass_QC_Rejection_ReasonStore.objects
            .filter(lot_id=lot_id)
            .order_by('-id')
            .first()
        )

        rw_qty = reason_store.total_rejection_quantity if reason_store else 0

        # 2. UNIFIED source aggregation — merge Brass QC + Brass Audit + IQF rejected tray scans
        response_data = []
        try:
            brass_qc_rows = list(Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id).select_related('rejection_reason'))
        except Exception:
            brass_qc_rows = []
        try:
            brass_audit_rows = list(Brass_Audit_Rejected_TrayScan.objects.filter(lot_id=lot_id).select_related('rejection_reason'))
        except Exception:
            brass_audit_rows = []
        try:
            iqf_rows = list(IQF_Rejected_TrayScan.objects.filter(lot_id=lot_id).select_related('rejection_reason'))
        except Exception:
            iqf_rows = []

        all_rows = brass_qc_rows + brass_audit_rows + iqf_rows

        print(f"[AUDIT API] Total rows fetched: {len(all_rows)} (brass_qc={len(brass_qc_rows)}, brass_audit={len(brass_audit_rows)}, iqf={len(iqf_rows)})")

        # Aggregate quantities by reason text + id (preserve insertion order)
        reason_map = OrderedDict()
        for row in all_rows:
            try:
                reason_text = (row.rejection_reason.rejection_reason or '').strip()
            except Exception:
                reason_text = str(getattr(row, 'rejection_reason', ''))
            try:
                qty = int(row.rejected_tray_quantity or 0)
            except Exception:
                try:
                    qty = int(float(row.rejected_tray_quantity or 0))
                except Exception:
                    qty = 0
            r_id = getattr(row.rejection_reason, 'id', None) if hasattr(row, 'rejection_reason') else None
            if reason_text in reason_map:
                reason_map[reason_text]['qty'] += qty
            else:
                reason_map[reason_text] = {'qty': qty, 'reason_id': r_id}

        # Build response using master IQF reasons, filling quantities from unified reason_map
        reasons = IQF_Rejection_Table.objects.all().order_by('rejection_reason_id')
        print(f"[AUDIT API] Master reasons count: {reasons.count()}")

        if not reasons.exists():
            # DYNAMIC FALLBACK: no master table entries — derive reasons from actual data
            print("[AUDIT API] No master reasons found → using dynamic reasons from scan data")
            dynamic_reason_map = OrderedDict()
            for row in all_rows:
                try:
                    reason_text = (row.rejection_reason.rejection_reason or '').strip()
                except Exception:
                    reason_text = str(getattr(row, 'rejection_reason', ''))
                try:
                    qty = int(row.rejected_tray_quantity or 0)
                except Exception:
                    try:
                        qty = int(float(row.rejected_tray_quantity or 0))
                    except Exception:
                        qty = 0
                if reason_text in dynamic_reason_map:
                    dynamic_reason_map[reason_text] += qty
                else:
                    dynamic_reason_map[reason_text] = qty

            for idx, (reason_text, qty) in enumerate(dynamic_reason_map.items(), start=1):
                response_data.append({
                    "s_no": idx,
                    "reason_id": None,
                    "reason": reason_text,
                    "brass_qc_qty": qty,
                    "iqf_qty": 0,
                    "is_editable": True,
                })
        else:
            for index, reason in enumerate(reasons, start=1):
                reason_text = (reason.rejection_reason or '').strip()
                info = reason_map.get(reason_text)
                brass_qty = 0
                if info:
                    brass_qty = info.get('qty', 0) or 0
                else:
                    # id-based fallback match
                    for v in reason_map.values():
                        if v.get('reason_id') and reason.id and v.get('reason_id') == reason.id:
                            brass_qty = v.get('qty', 0) or 0
                            break

                print(f"[AUDIT API] lot_id={lot_id}, reason={reason_text}, brass_qty={brass_qty}")
                response_data.append({
                    "s_no": index,
                    "reason_id": reason.id,
                    "reason": reason_text,
                    "brass_qc_qty": brass_qty,
                    "iqf_qty": 0,
                    "is_editable": True,
                })

        print(f"[AUDIT API] Output count: {len(response_data)}")

        # If a draft exists for this lot, overlay its values into response_data and return total
        try:
            draft = IQF_Draft_Store.objects.filter(lot_id=lot_id, draft_type='batch_rejection').order_by('-updated_at').first()
            if draft and draft.draft_data:
                d_items = draft.draft_data.get('items') or []
                # map reason_id -> qty
                d_map = { (int(it.get('reason_id')) if it.get('reason_id') is not None else None): int(it.get('iqf_qty') or 0) for it in d_items }
                total_from_draft = int(draft.draft_data.get('total_iqf') or 0)
                # overlay
                for row in response_data:
                    rid = row.get('reason_id')
                    if rid in d_map:
                        row['iqf_qty'] = d_map[rid]
                # expose draft total as initial IQF total
                return Response({
                    "success": True,
                    "rw_qty": rw_qty,
                    "rejection_data": response_data,
                    "total_iqf_qty": total_from_draft
                })
        except Exception:
            pass

        return Response({
            "success": True,
            "rw_qty": rw_qty,
            "rejection_data": response_data,
            "total_iqf_qty": 0
        })

    except Exception as e:
        print("[AUDIT API ERROR]", str(e))
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)

# IQF - Proceed btn - Validation
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def iqf_submit_audit(request):
    """Accepts JSON payload to save draft or proceed with IQF rejection quantities.

    CORE RULE: IQF processes ONLY Brass QC rejection qty (rw_qty), NOT the full lot.
    iqf_incoming_qty = rw_qty (e.g. 55), NOT total_batch_quantity (e.g. 100).

    Expected JSON:
        {
            "lot_id": "LID...",
            "action": "draft" | "proceed",
            "items": [ {"reason_id": 1, "iqf_qty": 5}, ... ]
        }
    """
    data = request.data
    lot_id = data.get('lot_id')
    action = data.get('action')
    items = data.get('items') or []
    if not lot_id or not action or action not in ('draft', 'proceed'):
        return Response({'success': False, 'error': 'Missing or invalid parameters'}, status=400)

    try:
        # ─── 1. SINGLE SOURCE OF TRUTH: rw_qty from Brass QC/Audit rejection ───
        audit_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        qc_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        rw_qty = 0
        if audit_store and getattr(audit_store, 'total_rejection_quantity', None) is not None:
            rw_qty = audit_store.total_rejection_quantity
        elif qc_store and getattr(qc_store, 'total_rejection_quantity', None) is not None:
            rw_qty = qc_store.total_rejection_quantity

        iqf_incoming_qty = rw_qty  # THIS IS WHAT IQF PROCESSES — NEVER total_batch_quantity

        # Get TotalStockModel — MUST exist, hard fail otherwise
        try:
            ts = TotalStockModel.objects.get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return Response({'success': False, 'error': f'Lot {lot_id} not found in TotalStockModel'}, status=404)

        # ELIGIBILITY GUARD — lot must be pending IQF processing
        if not ts.send_brass_audit_to_iqf:
            return Response({'success': False, 'error': f'Lot {lot_id} is not eligible for IQF (send_brass_audit_to_iqf=False)'}, status=400)

        original_lot_qty = 0
        batch_id_val = ''
        if getattr(ts, 'batch_id', None):
            original_lot_qty = int(getattr(ts.batch_id, 'total_batch_quantity', 0) or 0)
            batch_id_val = ts.batch_id.batch_id

        print(f'[IQF INPUT] lot_id={lot_id}, original_qty={original_lot_qty}, iqf_incoming_qty={iqf_incoming_qty}')

        if iqf_incoming_qty <= 0:
            return Response({'success': False, 'error': 'No IQF incoming qty — rw_qty is 0. Nothing to process.'}, status=400)

        # ─── 2. PARSE & VALIDATE ITEMS ───
        total_iqf = 0
        parsed_items = []
        for it in items:
            try:
                rid = int(it.get('reason_id'))
            except Exception:
                rid = None
            try:
                qty = int(it.get('iqf_qty') or 0)
            except Exception:
                return Response({'success': False, 'error': 'Invalid IQF quantity provided; must be integer'}, status=400)
            if qty < 0:
                return Response({'success': False, 'error': 'IQF quantities must be non-negative'}, status=400)
            total_iqf += qty
            parsed_items.append({'reason_id': rid, 'iqf_qty': qty})

        print(f'[IQF TOTAL CALC] Inputs: {parsed_items}, Computed Total: {total_iqf}')

        # ─── 3. BUILD BRASS QTY MAP FOR PER-REASON VALIDATION ───
        by_id_map = {}
        try:
            brass_rows_qs = Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id)
            if not brass_rows_qs.exists():
                brass_rows_qs = Brass_Audit_Rejected_TrayScan.objects.filter(lot_id=lot_id)

            reason_map = OrderedDict()
            for row in brass_rows_qs:
                try:
                    reason_text = (row.rejection_reason.rejection_reason or '').strip()
                except Exception:
                    reason_text = str(getattr(row, 'rejection_reason', ''))
                try:
                    qty = int(row.rejected_tray_quantity or 0)
                except Exception:
                    try:
                        qty = int(float(row.rejected_tray_quantity or 0))
                    except Exception:
                        qty = 0
                if reason_text in reason_map:
                    reason_map[reason_text]['qty'] += qty
                else:
                    reason_map[reason_text] = {'qty': qty, 'reason_id': getattr(row, 'rejection_reason', 'None')}

            reasons = IQF_Rejection_Table.objects.all().order_by('rejection_reason_id')
            for reason in reasons:
                rtext = (reason.rejection_reason or '').strip()
                info = reason_map.get(rtext)
                brass_qty = 0
                if info:
                    brass_qty = info.get('qty', 0) or 0
                else:
                    for k, v in reason_map.items():
                        if v.get('reason_id') and reason.id and v.get('reason_id') == reason.id:
                            brass_qty = v.get('qty', 0) or 0
                            break
                by_id_map[reason.id] = int(brass_qty or 0)
            print(f'[IQF BRASS MAP] by_id_map: {by_id_map}')
        except Exception as e:
            print(f'[IQF BRASS MAP ERROR] {e}')

        # ─── 4. PER-ITEM AND TOTAL VALIDATION (STRICT) ───
        with transaction.atomic():
            for itm in parsed_items:
                rid = itm.get('reason_id')
                qty = itm.get('iqf_qty') or 0
                if rid is None:
                    if qty > 0:
                        return Response({'success': False, 'error': 'Missing reason_id for provided IQF qty; cannot validate'}, status=400)
                    continue
                allowed = by_id_map.get(rid, 0)
                print(f'[VALIDATION] reason_id={rid}, allowed={allowed}, entered={qty}')
                if allowed == 0 and qty > 0:
                    return Response({'success': False, 'error': f'Cannot accept IQF qty for reason_id {rid}: no Brass QC quantity available', 'reason_id': rid, 'allowed': allowed, 'entered': qty}, status=400)
                if qty > allowed:
                    return Response({'success': False, 'error': 'IQF Qty cannot exceed Brass QC Reject Qty', 'reason_id': rid, 'allowed': allowed, 'entered': qty}, status=400)

            if total_iqf > iqf_incoming_qty:
                return Response({'success': False, 'error': 'Submitted IQF total exceeds RW quantity', 'rw_qty': iqf_incoming_qty, 'submitted_total': total_iqf}, status=400)

            # ─── 5. DRAFT SAVE ───
            if action == 'draft':
                IQF_Draft_Store.objects.update_or_create(
                    lot_id=lot_id,
                    draft_type='batch_rejection',
                    defaults={
                        'batch_id': batch_id_val,
                        'user': request.user,
                        'draft_data': {'is_draft': True, 'items': parsed_items, 'total_iqf': total_iqf},
                    }
                )
                return Response({'success': True, 'draft': True, 'rw_qty': iqf_incoming_qty, 'rejection_rows': parsed_items, 'total_iqf_qty': total_iqf})

            # ─── 6. DECISION ENGINE (action == 'proceed') ───
            rejected_qty = int(total_iqf)
            accepted_qty = int(iqf_incoming_qty - rejected_qty)

            if rejected_qty == 0:
                submission_type = IQF_Submitted.SUB_FULL_ACCEPT
            elif rejected_qty == iqf_incoming_qty:
                submission_type = IQF_Submitted.SUB_FULL_REJECT
            else:
                submission_type = IQF_Submitted.SUB_PARTIAL

            print(f'[DECISION] {submission_type} — accepted={accepted_qty}, rejected={rejected_qty}')

            # ─── 7. TRAY DATA FROM DB (REAL DATA ONLY — IGNORE FRONTEND TRAYS) ───

            # 7a. ORIGINAL SNAPSHOT — full lot trays (tray_quantity) for reference
            # SOURCE OF TRUTH: IQFTrayId only — no BrassTrayId fallback
            all_trays_qs = IQFTrayId.objects.filter(lot_id=lot_id).order_by('id')
            original_tray_list = []
            original_tray_total = 0
            for t in all_trays_qs:
                raw_qty = int(getattr(t, 'tray_quantity', 0) or 0)
                if raw_qty <= 0:
                    continue
                original_tray_total += raw_qty
                original_tray_list.append({
                    'tray_id': getattr(t, 'tray_id', '') or '',
                    'qty': raw_qty,
                    'top_tray': bool(getattr(t, 'top_tray', False)),
                })
            original_data_snapshot = {
                'qty': original_lot_qty,
                'tray_total': original_tray_total,
                'total_trays': len(original_tray_list),
                'trays': original_tray_list,
            }
            print(f'[ORIGINAL] qty={original_lot_qty}, tray_total={original_tray_total}, trays={len(original_tray_list)}')

            # 7b. IQF WORKING SNAPSHOT — eligible trays, excluding delinked
            # SOURCE OF TRUTH: IQFTrayId for tray identifiers
            # QTY RESOLUTION: remaining_qty (post-processed) > BrassTrayId capacity (pre-processed) > tray_quantity (last resort)
            iqf_trays_qs = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).order_by('id')
            source_is_iqf = True

            tray_list = []
            for t in iqf_trays_qs:
                remaining = int(getattr(t, 'remaining_qty', 0) or 0)
                raw_qty = int(getattr(t, 'tray_quantity', 0) or 0)
                # ✅ FIX: IQF-only resolution — NO BrassTrayId dependency
                # Priority: remaining_qty (set by IQF submit) > IQFTrayId tray_quantity
                if remaining > 0:
                    tray_qty = remaining
                else:
                    tray_qty = raw_qty
                if tray_qty <= 0:
                    print(f'[TRAY WARNING] Tray {t.tray_id} has qty=0 (remaining={remaining}, raw={raw_qty}), skipping')
                    continue
                tray_list.append({
                    'obj': t,
                    'tray_id': getattr(t, 'tray_id', '') or '',
                    'qty': tray_qty,
                    'top_tray': bool(getattr(t, 'top_tray', False)),
                    'new_tray': bool(getattr(t, 'new_tray', False)),
                    'delink_flag': bool(getattr(t, 'delink_tray', False)),
                })

            iqf_tray_total = sum(tr['qty'] for tr in tray_list)
            iqf_data_snapshot = {
                'qty': iqf_incoming_qty,
                'tray_total': iqf_tray_total,
                'total_trays': len(tray_list),
                'trays': [
                    {'tray_id': tr['tray_id'], 'qty': tr['qty'], 'top_tray': tr['top_tray']}
                    for tr in tray_list
                ],
            }
            print(f'[IQF] qty={iqf_incoming_qty}, tray_total={iqf_tray_total}, trays={len(tray_list)}')
            if iqf_tray_total != iqf_incoming_qty:
                print(f'[WARNING] iqf_tray_total={iqf_tray_total} ≠ iqf_incoming_qty={iqf_incoming_qty} — tray data may be inconsistent')

            # ─── 8. TRAY VALIDATION ───
            # FULL_ACCEPT / FULL_REJECT: no tray validation needed here
            #   (FULL_ACCEPT has its own per-tray strict validation in section 10 below)
            # PARTIAL: iqf_tray_total must equal accepted_qty
            print(f'[TRAY VALIDATION] flow={submission_type}, iqf_tray_total={iqf_tray_total}, accepted_qty={accepted_qty}, iqf_incoming_qty={iqf_incoming_qty}')

            # PARTIAL tray validation removed — accept is user-driven, reject is system-computed.
            # Only lot-level conservation is enforced: accepted_qty + rejected_qty = iqf_incoming_qty

            # ─── 9. BUILD REJECTION DETAILS (when rejected_qty > 0) ───
            rejection_details = None
            if rejected_qty > 0 and parsed_items:
                rejection_details = []
                for itm in parsed_items:
                    if itm.get('iqf_qty', 0) > 0:
                        reason_obj = IQF_Rejection_Table.objects.filter(id=itm['reason_id']).first()
                        rejection_details.append({
                            'reason_id': itm['reason_id'],
                            'reason_text': reason_obj.rejection_reason if reason_obj else '',
                            'iqf_qty': itm['iqf_qty'],
                        })

            # ─── 10. BUILD LABELED FLOW SNAPSHOTS ───
            full_accept_data = None
            partial_accept_data = None
            full_reject_data = None
            partial_reject_data = None

            # ── Helper: resolve tray capacity for an IQFTrayId record ──
            def _resolve_tray_capacity(iqf_tray_obj):
                """Resolve the REAL capacity for a tray.
                Priority: IQFTrayId.tray_capacity → BrassTrayId → TrayId master → ModelMaster → 16
                """
                cap = getattr(iqf_tray_obj, 'tray_capacity', None)
                if cap and cap > 0:
                    return cap
                # BrassTrayId (same tray_id, any lot)
                brass = BrassTrayId.objects.filter(tray_id=iqf_tray_obj.tray_id).exclude(
                    tray_capacity__isnull=True).first()
                if brass and brass.tray_capacity and brass.tray_capacity > 0:
                    return brass.tray_capacity
                # TrayId master
                tray_master = TrayId.objects.filter(tray_id=iqf_tray_obj.tray_id).exclude(
                    tray_capacity__isnull=True).first()
                if tray_master and tray_master.tray_capacity and tray_master.tray_capacity > 0:
                    return tray_master.tray_capacity
                # ModelMasterCreation (via TotalStockModel.batch_id)
                try:
                    mmc_cap = ts.batch_id.tray_capacity if ts.batch_id else None
                    if mmc_cap and mmc_cap > 0:
                        return mmc_cap
                except Exception:
                    pass
                return 16  # safe default

            if submission_type == IQF_Submitted.SUB_FULL_ACCEPT:
                # ✅ FULL ACCEPT — DISTRIBUTE iqf_incoming_qty across IQFTrayId trays BY CAPACITY
                # IQFTrayId.tray_quantity is unreliable (contains per-scan rejection qty, NOT full capacity).
                # We MUST distribute the total accepted qty across trays using their real capacity.
                fa_trays_qs = list(IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).order_by('id'))

                if not fa_trays_qs:
                    return Response({
                        'success': False,
                        'error': f'No IQFTrayId records found for lot {lot_id}. Cannot build FULL ACCEPT snapshot.',
                    }, status=400)

                accepted_trays = []
                remaining = iqf_incoming_qty

                for t in fa_trays_qs:
                    if remaining <= 0:
                        break
                    cap = _resolve_tray_capacity(t)
                    qty = min(remaining, cap)
                    remaining -= qty
                    is_last = (remaining == 0)
                    is_top = is_last and qty < cap  # partial fill → top tray

                    # Persist remaining_qty to DB so downstream always reads it
                    t.remaining_qty = qty
                    t.top_tray = is_top
                    t.save(update_fields=['remaining_qty', 'top_tray'])

                    accepted_trays.append({'tray_id': t.tray_id, 'qty': qty, 'top_tray': is_top})
                    print(f'  [FA DISTRIBUTE] tray={t.tray_id}, cap={cap}, assigned={qty}, remaining={remaining}, top={is_top}')

                # If no tray was marked top_tray (all full fills), mark the last one
                if accepted_trays and not any(tr['top_tray'] for tr in accepted_trays):
                    accepted_trays[-1]['top_tray'] = True
                    # Also persist to DB
                    last_obj = fa_trays_qs[len(accepted_trays) - 1] if len(accepted_trays) <= len(fa_trays_qs) else None
                    if last_obj:
                        last_obj.top_tray = True
                        last_obj.save(update_fields=['top_tray'])

                fa_tray_total = sum(tr['qty'] for tr in accepted_trays)

                if fa_tray_total != iqf_incoming_qty:
                    return Response({
                        'success': False,
                        'error': (
                            f'Could not distribute all pieces: distributed {fa_tray_total} of {iqf_incoming_qty}. '
                            f'Available trays ({len(fa_trays_qs)}) have insufficient total capacity. '
                            f'Please verify tray records for lot {lot_id}.'
                        ),
                        'tray_total': fa_tray_total,
                        'iqf_incoming_qty': iqf_incoming_qty,
                    }, status=400)

                full_accept_data = {
                    'label': 'FULL_ACCEPT',
                    'qty': accepted_qty,
                    'total_trays': len(accepted_trays),
                    'trays': accepted_trays,
                }
                print(f'[FULL_ACCEPT] iqf_incoming={iqf_incoming_qty}, tray_total={fa_tray_total}, trays={len(accepted_trays)}, VALIDATED=OK')

            elif submission_type == IQF_Submitted.SUB_FULL_REJECT:
                # FULL REJECT — distribute rejected_qty across trays BY CAPACITY (same issue as FULL_ACCEPT)
                fr_trays_qs = list(IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).order_by('id'))
                distributed_trays = []
                remaining_to_distribute = rejected_qty

                for t in fr_trays_qs:
                    if remaining_to_distribute <= 0:
                        t.remaining_qty = 0
                        t.save(update_fields=['remaining_qty'])
                        continue
                    cap = _resolve_tray_capacity(t)
                    take = min(remaining_to_distribute, cap)
                    remaining_to_distribute -= take
                    # Persist remaining_qty to DB
                    t.remaining_qty = take
                    t.save(update_fields=['remaining_qty'])
                    if take > 0:
                        distributed_trays.append({'tray_id': t.tray_id, 'qty': take, 'top_tray': bool(t.top_tray)})

                full_reject_data = {
                    'label': 'FULL_REJECT',
                    'qty': rejected_qty,
                    'total_trays': len(distributed_trays),
                    'trays': distributed_trays,
                    'reasons': rejection_details,
                }
                print(f'[FULL_REJECT DISTRIBUTE] rejected={rejected_qty}, distributed to {len(distributed_trays)} trays')

            else:
                # PARTIAL — Accept is USER-DRIVEN (scanned trays), Reject is SYSTEM-COMPUTED (reverse order)
                #
                # GOLDEN RULES:
                # 1. Accept = user-scanned tray data → store as-is, NO modification/redistribution
                # 2. Reject = recomputed from original trays in REVERSE order
                # 3. Lot-level conservation: Accept + Reject = iqf_incoming_qty
                # 4. No tray-level conservation enforced
                # 5. No artificial redistribution, merging, or overflow correction
                # 6. Delink is only for tracking new trays, NOT for balancing qty

                # ── ACCEPT SIDE: user truth from frontend payload ──
                accepted_trays_payload = data.get('accepted_trays') or []
                accepted_trays = []
                for at in accepted_trays_payload:
                    tray_id = str(at.get('tray_id', '') or '').strip()
                    qty = 0
                    try:
                        qty = int(at.get('qty', 0) or 0)
                    except (ValueError, TypeError):
                        qty = 0
                    is_top = bool(at.get('is_top_tray', False))
                    if tray_id and qty > 0:
                        accepted_trays.append({
                            'tray_id': tray_id,
                            'qty': qty,
                            'is_top_tray': is_top,
                        })

                accept_total = sum(t['qty'] for t in accepted_trays)
                print(f'[PARTIAL ACCEPT] User-scanned: {len(accepted_trays)} trays, total={accept_total}, expected={accepted_qty}')

                if accept_total != accepted_qty:
                    return Response({
                        'success': False,
                        'error': f'Scanned accept tray total ({accept_total}) ≠ accepted qty ({accepted_qty}). Verify tray scans.',
                        'accept_total': accept_total,
                        'accepted_qty': accepted_qty,
                    }, status=400)

                # ── REJECT SIDE: system-computed from original trays in REVERSE order ──
                # Uses _resolve_tray_capacity (same resolution as FULL_ACCEPT/FULL_REJECT).
                # IQFTrayId.tray_quantity is unreliable (per-scan rejection qty), so capacity is used.
                all_orig_trays = list(IQFTrayId.objects.filter(
                    lot_id=lot_id, delink_tray=False
                ).order_by('id'))

                rejected_trays = []
                remaining_to_reject = rejected_qty

                for t in reversed(all_orig_trays):
                    if remaining_to_reject <= 0:
                        break
                    cap = _resolve_tray_capacity(t)
                    if cap <= 0:
                        continue
                    take = min(cap, remaining_to_reject)
                    rejected_trays.append({
                        'tray_id': t.tray_id or '',
                        'qty': take,
                    })
                    remaining_to_reject -= take

                rejected_trays.reverse()  # restore ascending order for display

                reject_total = sum(t['qty'] for t in rejected_trays)
                print(f'[PARTIAL REJECT] System-computed (reverse): {len(rejected_trays)} trays, total={reject_total}, expected={rejected_qty}')

                partial_accept_data = {
                    'label': 'PARTIAL_ACCEPT',
                    'qty': accepted_qty,
                    'total_trays': len(accepted_trays),
                    'trays': accepted_trays,
                }
                partial_reject_data = {
                    'label': 'PARTIAL_REJECT',
                    'qty': rejected_qty,
                    'total_trays': len(rejected_trays),
                    'trays': rejected_trays,
                    'reasons': rejection_details,
                }

            # ─── 11. CREATE REJECTION REASON STORE (only when rejected_qty > 0) ───
            if rejected_qty > 0:
                store = IQF_Rejection_ReasonStore.objects.create(
                    lot_id=lot_id,
                    user=request.user,
                    total_rejection_quantity=rejected_qty,
                    batch_rejection=False,
                )
                reason_ids = [p['reason_id'] for p in parsed_items if p['reason_id'] and p.get('iqf_qty', 0) > 0]
                if reason_ids:
                    reasons_qs = IQF_Rejection_Table.objects.filter(id__in=reason_ids)
                    store.rejection_reason.set(reasons_qs)

            # Save audit trail draft record
            IQF_Draft_Store.objects.update_or_create(
                lot_id=lot_id,
                draft_type='batch_rejection',
                defaults={
                    'batch_id': batch_id_val,
                    'user': request.user,
                    'draft_data': {'is_draft': False, 'items': parsed_items, 'total_iqf': total_iqf,
                                   'submission_type': submission_type},
                }
            )

            # ─── 12. SAVE IQF_Submitted — ONE LOT → ONE ROW → FULL TRACEABILITY ───
            IQF_Submitted.objects.update_or_create(
                lot_id=lot_id,
                defaults={
                    'batch_id': ts.batch_id,
                    'original_lot_qty': original_lot_qty,
                    'iqf_incoming_qty': iqf_incoming_qty,
                    'total_lot_qty': iqf_incoming_qty,  # backward compat — always = iqf_incoming_qty
                    'accepted_qty': accepted_qty,
                    'rejected_qty': rejected_qty,
                    'submission_type': submission_type,
                    'original_data': original_data_snapshot,
                    'iqf_data': iqf_data_snapshot,
                    'full_accept_data': full_accept_data,
                    'partial_accept_data': partial_accept_data,
                    'full_reject_data': full_reject_data,
                    'partial_reject_data': partial_reject_data,
                    'rejection_details': rejection_details,
                    'is_completed': True,
                    'created_by': request.user,
                }
            )

            print(f'[DB SAVE] ONE ROW: lot={lot_id}, type={submission_type}, '
                  f'original={original_lot_qty}, incoming={iqf_incoming_qty}, '
                  f'accepted={accepted_qty}, rejected={rejected_qty}')

            # ─── 13. MOVEMENT CONTROL — update TotalStockModel flags ───
            # FULL_ACCEPT / PARTIAL: accepted qty flows to Brass QC (send_brass_qc=True)
            # FULL_REJECT: nothing accepted, stays for rework
            if submission_type == IQF_Submitted.SUB_FULL_ACCEPT:
                ts.iqf_acceptance = True
                ts.iqf_rejection = False
                ts.iqf_few_cases_acceptance = False
                ts.send_brass_qc = True  # push lot to Brass QC
                ts.next_process_module = 'Brass QC'  # ✅ LOCK: downstream reads from IQF_Submitted
            elif submission_type == IQF_Submitted.SUB_FULL_REJECT:
                ts.iqf_rejection = True
                ts.iqf_acceptance = False
                ts.iqf_few_cases_acceptance = False
                ts.send_brass_qc = False  # nothing to send
            else:  # PARTIAL
                ts.iqf_few_cases_acceptance = True
                ts.iqf_acceptance = False
                ts.iqf_rejection = False
                ts.send_brass_qc = True  # accepted portion flows to Brass QC
                ts.next_process_module = 'Brass QC'  # ✅ LOCK: downstream reads from IQF_Submitted

            ts.iqf_accepted_qty = accepted_qty
            ts.iqf_after_rejection_qty = rejected_qty
            ts.last_process_module = 'IQF'
            ts.send_brass_audit_to_iqf = False
            ts.iqf_last_process_date_time = timezone.now()

            ts.save(update_fields=[
                'iqf_acceptance', 'iqf_rejection', 'iqf_few_cases_acceptance',
                'iqf_accepted_qty', 'iqf_after_rejection_qty',
                'last_process_module', 'send_brass_audit_to_iqf',
                'send_brass_qc', 'next_process_module',
                'iqf_last_process_date_time',
            ])

            print(f'[MOVEMENT] iqf_acceptance={ts.iqf_acceptance}, '
                  f'iqf_rejection={ts.iqf_rejection}, '
                  f'iqf_few_cases_acceptance={ts.iqf_few_cases_acceptance}, '
                  f'send_brass_audit_to_iqf={ts.send_brass_audit_to_iqf}, '
                  f'send_brass_qc={ts.send_brass_qc}')

            return Response({
                'success': True,
                'proceeded': True,
                'submission_type': submission_type,
                'original_lot_qty': original_lot_qty,
                'iqf_incoming_qty': iqf_incoming_qty,
                'accepted_qty': accepted_qty,
                'rejected_qty': rejected_qty,
                'rw_qty': iqf_incoming_qty,
                'total_iqf_qty': total_iqf,
            })

    except Exception as e:
        print(f'[IQF SUBMIT ERROR] {e}')
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)

# View Icon - Dynamic fetch
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def iqf_tray_details(request):
    """Return tray details for a lot. Single source of truth for tray modal.

    ARCHITECTURE RULE: Tray qty = SUM(rejected_tray_quantity) GROUP BY tray_id
    from Brass_QC_Rejected_TrayScan. Never trust stored tray_quantity or tray_capacity.

    Query params: ?lot_id=...
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'lot_id required'}, status=400)
    try:
        print(f"[IQF TRAY API] Checking IQF_Submitted first for lot: {lot_id}")

        # ✅ FIX: Check IQF_Submitted FIRST — SINGLE SOURCE OF TRUTH after IQF completes
        iqf_record = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()

        if iqf_record and iqf_record.submission_type in ('FULL_ACCEPT', 'PARTIAL'):
            if iqf_record.submission_type == 'FULL_ACCEPT' and iqf_record.full_accept_data:
                source_trays = iqf_record.full_accept_data.get('trays', [])
                label = 'FULL_ACCEPT'
            elif iqf_record.submission_type == 'PARTIAL' and iqf_record.partial_accept_data:
                source_trays = iqf_record.partial_accept_data.get('trays', [])
                label = 'PARTIAL_ACCEPT'
            else:
                source_trays = []
                label = 'EMPTY'

            tray_list = []
            total_qty = 0
            for tray in source_trays:
                qty = int(tray.get('qty', 0))
                if qty <= 0:
                    continue
                total_qty += qty
                tray_list.append({
                    'tray_id': tray.get('tray_id', ''),
                    'tray_qty': qty,
                    'top_tray': bool(tray.get('top_tray', False)),
                    'status': 'ACCEPTED',
                    'is_rejected': False,
                    'is_reusable': True,
                    'is_new': False,
                    'label': f'IQF {label}',
                })

            print(f"[IQF TRAY API] Using IQF_Submitted ({label}) for lot {lot_id}: {len(tray_list)} trays, total_qty={total_qty}")
            return Response({
                'success': True,
                'lot_id': lot_id,
                'total_qty': total_qty,
                'total_trays': len(tray_list),
                'trays': tray_list,
                'source': 'IQF_Submitted',
            })

        # FALLBACK: Dynamic aggregation from Brass_QC_Rejected_TrayScan (pre-IQF completion)
        print(f"[IQF TRAY API] Fallback: Dynamic aggregation from Brass_QC_Rejected_TrayScan for lot: {lot_id}")

        # SOURCE OF TRUTH: Aggregate rejected_tray_quantity per tray from rejection scan logs
        # rejected_tray_quantity is CharField, so aggregate in Python
        brass_reject_rows = Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id)

        # If no Brass QC rows, try Brass Audit as fallback
        if not brass_reject_rows.exists():
            brass_reject_rows = Brass_Audit_Rejected_TrayScan.objects.filter(lot_id=lot_id)

        # Aggregate per tray_id (field is rejected_tray_id in Brass_QC_Rejected_TrayScan)
        tray_qty_map = {}
        for row in brass_reject_rows:
            tray_id = getattr(row, 'rejected_tray_id', None) or getattr(row, 'tray_id', None) or ''
            if not tray_id:
                continue
            try:
                qty = int(row.rejected_tray_quantity or 0)
            except (ValueError, TypeError):
                qty = 0
            tray_qty_map[tray_id] = tray_qty_map.get(tray_id, 0) + qty

        tray_list = []
        total_qty = 0

        for tray_id in sorted(tray_qty_map.keys()):
            qty = tray_qty_map[tray_id]
            total_qty += qty
            is_new = not IQFTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).exists()
            tray_list.append({
                'tray_id': tray_id,
                'tray_qty': qty,
                'status': 'NEW' if is_new else 'NORMAL',
                'is_rejected': True,
                'is_reusable': False,
                'is_new': is_new,
                'label': 'New Tray Available' if is_new else 'Tray reuse allowed',
            })

        print(f"[IQF TRAY API] returning {len(tray_list)} trays (dynamic aggregation), total_qty={total_qty}")
        return Response({
            'success': True,
            'lot_id': lot_id,
            'total_qty': total_qty,
            'total_trays': len(tray_list),
            'trays': tray_list
        })
    except Exception as e:
        traceback.print_exc()
        print('[IQF TRAY API ERROR]', str(e))
        return Response({'success': False, 'error': str(e)}, status=500)

# IQF Completed Table API: returns all lots that have completed IQF processing (rejected, accepted, or few cases acceptance) but not yet sent back to Brass QC via pick table
@method_decorator(login_required, name='dispatch')
class IQFCompletedTableView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            print('[IQF COMPLETED API] Called')

            queryset = TotalStockModel.objects.select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).filter(
                send_brass_audit_to_iqf=False
            ).filter(
                Q(iqf_rejection=True) | Q(iqf_acceptance=True) | Q(iqf_few_cases_acceptance=True)
            ).order_by('-bq_last_process_date_time')

            data = []
            for obj in queryset:
                trays = IQFTrayId.objects.filter(lot_id=obj.lot_id, batch_id=obj.batch_id)
                tray_list = [{'tray_id': t.tray_id, 'tray_qty': t.tray_quantity} for t in trays]
                data.append({
                    'lot_id': obj.lot_id,
                    'batch_id': obj.batch_id.batch_id if obj.batch_id else '',
                    'model_no': getattr(obj.batch_id.model_stock_no, 'model_no', '') if obj.batch_id else '',
                    'location': getattr(obj.batch_id.location, 'location_name', '') if obj.batch_id and getattr(obj.batch_id, 'location', None) else '',
                    'iqf_rejection_qty': getattr(obj, 'iqf_rejection_qty', None),
                    'iqf_accepted_qty': getattr(obj, 'iqf_accepted_qty', None),
                    'status': 'REJECTED' if obj.iqf_rejection else ('ACCEPTED' if obj.iqf_acceptance else 'COMPLETED'),
                    'last_updated': obj.bq_last_process_date_time,
                    'tray_details': tray_list
                })

            print(f'[IQF COMPLETED API] Count: {len(data)}')
            return Response({'success': True, 'count': len(data), 'data': data})
        except Exception as e:
            print('[IQF COMPLETED ERROR]', str(e))
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)


@method_decorator(login_required, name='dispatch')
class IQFCompletedPageView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'IQF/Iqf_Completed.html'

    def get(self, request):
        # Page only — frontend will call `iqf_completed_api` to fetch data
        return Response({}, template_name=self.template_name)


# Redirect stub for legacy accept-table link
def iqf_accept_table_redirect(request):
    return redirect('iqf_picktable')


# Redirect stub for legacy rejection-table link
def iqf_rejection_table_redirect(request):
    return redirect('iqf_picktable')


# Persist UI 'lot verified' checkbox state so it survives page refresh
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def iqf_toggle_verified(request):
    """Toggle or set the `iqf_accepted_qty_verified` flag on TotalStockModel for a lot.

    Expects JSON: { "lot_id": "LID...", "verified": true }
    """
    try:
        data = request.data
        lot_id = data.get('lot_id')
        verified = data.get('verified')
        if not lot_id:
            return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

        ts = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if not ts:
            return Response({'success': False, 'error': 'Lot not found'}, status=404)

        # Only allow setting to True/False; coerce safely
        ts.iqf_accepted_qty_verified = bool(verified)
        ts.save(update_fields=['iqf_accepted_qty_verified'])

        return Response({'success': True, 'lot_id': lot_id, 'iqf_accepted_qty_verified': ts.iqf_accepted_qty_verified})
    except Exception as e:
        print('[IQF TOGGLE VERIFIED ERROR]', str(e))
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)


# ── IQF Accepted Tray Slots — Backend computes, frontend renders ──
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def iqf_accepted_tray_slots(request):
    """Compute accepted tray scan slots based on IQF rejection total.

    SINGLE SOURCE OF TRUTH: IQFTrayId for tray info, Brass QC/Audit for rw_qty.
    Frontend is pure render — zero calculations.

    Query params: ?lot_id=X&iqf_rejection_total=Y
    Returns: { success, rw_qty, accepted_qty, rejected_qty, tray_capacity, slots: [{slot_no, qty, is_top_tray}] }
    """
    lot_id = request.GET.get('lot_id')
    iqf_rejection_total = request.GET.get('iqf_rejection_total', '0')

    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

    try:
        iqf_rejection_total = int(iqf_rejection_total)
    except (ValueError, TypeError):
        return Response({'success': False, 'error': 'iqf_rejection_total must be integer'}, status=400)

    if iqf_rejection_total < 0:
        return Response({'success': False, 'error': 'iqf_rejection_total must be non-negative'}, status=400)

    try:
        # 1. Resolve rw_qty (IQF incoming) — SINGLE SOURCE OF TRUTH
        audit_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        qc_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        rw_qty = 0
        if audit_store and getattr(audit_store, 'total_rejection_quantity', None) is not None:
            rw_qty = audit_store.total_rejection_quantity
        elif qc_store and getattr(qc_store, 'total_rejection_quantity', None) is not None:
            rw_qty = qc_store.total_rejection_quantity

        if rw_qty <= 0:
            return Response({'success': True, 'rw_qty': 0, 'accepted_qty': 0, 'rejected_qty': 0, 'slots': []})

        if iqf_rejection_total > rw_qty:
            return Response({'success': False, 'error': 'Rejection total exceeds RW qty', 'rw_qty': rw_qty}, status=400)

        accepted_qty = rw_qty - iqf_rejection_total
        rejected_qty = iqf_rejection_total

        if accepted_qty <= 0:
            return Response({
                'success': True,
                'rw_qty': rw_qty,
                'accepted_qty': 0,
                'rejected_qty': rejected_qty,
                'slots': [],
            })

        # 2. Resolve tray capacity from IQFTrayId → BrassTrayId → ModelMaster
        ts = TotalStockModel.objects.filter(lot_id=lot_id).select_related('batch_id', 'batch_id__model_stock_no').first()
        if not ts:
            return Response({'success': False, 'error': 'Lot not found'}, status=404)

        def _resolve_capacity():
            """Resolve tray capacity: IQFTrayId.tray_capacity → BrassTrayId → ModelMaster → 16"""
            iqf_tray = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).exclude(tray_capacity__isnull=True).exclude(tray_capacity=0).first()
            if iqf_tray and iqf_tray.tray_capacity and iqf_tray.tray_capacity > 0:
                return iqf_tray.tray_capacity
            brass_tray = BrassTrayId.objects.filter(lot_id=lot_id, delink_tray=False).exclude(tray_capacity__isnull=True).exclude(tray_capacity=0).first()
            if brass_tray and brass_tray.tray_capacity and brass_tray.tray_capacity > 0:
                return brass_tray.tray_capacity
            if ts.batch_id and ts.batch_id.tray_capacity and ts.batch_id.tray_capacity > 0:
                return ts.batch_id.tray_capacity
            return 16  # safe default

        tray_capacity = _resolve_capacity()

        # 3. Compute accepted tray slots — distribute accepted_qty into capacity-sized trays
        #    Full trays first, top tray (remainder) last
        full_trays = accepted_qty // tray_capacity
        remainder = accepted_qty % tray_capacity

        slots = []
        slot_no = 1

        # Top tray first (partial fill) — shown at position 1 per factory convention
        if remainder > 0:
            slots.append({
                'slot_no': slot_no,
                'qty': remainder,
                'is_top_tray': True,
            })
            slot_no += 1

        # Full trays
        for _ in range(full_trays):
            slots.append({
                'slot_no': slot_no,
                'qty': tray_capacity,
                'is_top_tray': False,
            })
            slot_no += 1

        # Edge case: all trays perfectly full — mark last as top tray
        if remainder == 0 and slots:
            slots[0]['is_top_tray'] = True

        print(f'[IQF TRAY SLOTS] lot={lot_id}, rw={rw_qty}, rej={rejected_qty}, '
              f'acc={accepted_qty}, cap={tray_capacity}, slots={len(slots)}')

        return Response({
            'success': True,
            'rw_qty': rw_qty,
            'accepted_qty': accepted_qty,
            'rejected_qty': rejected_qty,
            'tray_capacity': tray_capacity,
            'slots': slots,
        })

    except Exception as e:
        print('[IQF TRAY SLOTS ERROR]', str(e))
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)


# ── IQF Validate Tray Scan — Backend decides, frontend renders ──
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def iqf_validate_tray_scan(request):
    """Validate a scanned tray ID against the current IQF lot.

    SINGLE SOURCE OF TRUTH: Backend checks format, lot membership, delink status.
    Frontend is pure render — zero validation logic.

    Query params: ?lot_id=X&tray_id=Y
    Returns: { success, status: 'valid'|'invalid_format'|'valid_lot'|'delink', message }
    """
    import re

    lot_id = request.GET.get('lot_id', '').strip()
    tray_id = request.GET.get('tray_id', '').strip()

    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    if not tray_id:
        return Response({'success': False, 'error': 'Missing tray_id'}, status=400)

    # ── RULE 1: Length check (frontend enforces 9-char trigger, backend double-checks) ──
    if len(tray_id) != 9:
        return Response({
            'success': True,
            'status': 'invalid_format',
            'message': 'Invalid Tray ID — must be 9 characters',
        })

    # ── RULE 2: Format validation [PREFIX]-[ALPHANUMERIC] e.g. NB-A00001 ──
    if not re.match(r'^[A-Z]{2}-[A-Z0-9]{6}$', tray_id, re.IGNORECASE):
        return Response({
            'success': True,
            'status': 'invalid_format',
            'message': 'Invalid Tray ID',
        })

    # ── RULE 3: Lot membership check ──
    # Check IQFTrayId first (primary), then BrassTrayId (fallback)
    iqf_match = IQFTrayId.objects.filter(lot_id=lot_id, tray_id=tray_id, delink_tray=False).first()
    if iqf_match:
        return Response({
            'success': True,
            'status': 'valid_lot',
            'message': 'Valid Tray',
            'tray_id': tray_id,
            'tray_qty': int(getattr(iqf_match, 'tray_quantity', 0) or 0),
            'top_tray': bool(getattr(iqf_match, 'top_tray', False)),
        })

    # Check BrassTrayId for the same lot
    brass_match = BrassTrayId.objects.filter(lot_id=lot_id, tray_id=tray_id, delink_tray=False).first()
    if brass_match:
        return Response({
            'success': True,
            'status': 'valid_lot',
            'message': 'Valid Tray',
            'tray_id': tray_id,
            'tray_qty': int(getattr(brass_match, 'tray_quantity', 0) or 0),
            'top_tray': bool(getattr(brass_match, 'top_tray', False)),
        })

    # ── RULE 4: Not in current lot — check if it exists anywhere (delink case) ──
    exists_elsewhere = (
        IQFTrayId.objects.filter(tray_id=tray_id).exists() or
        BrassTrayId.objects.filter(tray_id=tray_id).exists() or
        TrayId.objects.filter(tray_id=tray_id).exists()
    )

    if exists_elsewhere:
        # Tray exists in system but not in this lot → delink/new tray
        return Response({
            'success': True,
            'status': 'delink',
            'message': 'New Tray - Delink Mode',
            'tray_id': tray_id,
        })

    # Tray ID format valid but not found anywhere in the system
    return Response({
        'success': True,
        'status': 'delink',
        'message': 'New Tray - Delink Mode',
        'tray_id': tray_id,
    })

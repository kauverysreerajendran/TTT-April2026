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


# Generate Lot ID
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
    elif onhold:
        status_pill = {'label': 'Draft', 'border': '#4997ac', 'bg': '#e3f2fd', 'text': '#0d47a1'}
    elif rejection or few_cases or acceptance:
        status_pill = {'label': 'Yet to Release', 'border': '#0d5d17', 'bg': '#c5f9c2', 'text': '#2f801b'}
    else:
        status_pill = {'label': 'Yet to Start', 'border': '#f9a825', 'bg': '#fff8e1', 'text': '#b26a00'}

    # ── Process status circles ──
    q_color = '#0c8249' if verified else '#bdbdbd'
    if rejection or acceptance or few_cases:
        qc_style = 'background-color: #0c8249'
    elif onhold:
        qc_style = 'background: linear-gradient(to right, #0c8249 50%, #1565c0 50%)'
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

# IQF - Pick Table   
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

        # ── Detect Brass QC full lot rejection ──
        is_full_lot_reject = bool(reason_store and getattr(reason_store, 'batch_rejection', False))
        if not is_full_lot_reject:
            _audit_rs = (
                Brass_Audit_Rejection_ReasonStore.objects
                .filter(lot_id=lot_id)
                .order_by('-id')
                .first()
            )
            if _audit_rs and getattr(_audit_rs, 'batch_rejection', False):
                is_full_lot_reject = True
                if rw_qty == 0:
                    rw_qty = _audit_rs.total_rejection_quantity or 0

        # Fallback: if full lot reject and rw_qty is still 0, use lot qty from TotalStockModel
        if is_full_lot_reject and rw_qty == 0:
            try:
                _ts = TotalStockModel.objects.get(lot_id=lot_id)
                rw_qty = int(getattr(_ts.batch_id, 'total_batch_quantity', 0) or 0) if _ts.batch_id else 0
            except TotalStockModel.DoesNotExist:
                pass

        # ── Re-flagged lot: override rw_qty from IQF_Submitted (SINGLE SOURCE OF TRUTH) ──
        # When a lot travels Brass QC → IQF multiple times, the Brass QC reason store
        # may hold STALE rw_qty. IQF_Submitted has the latest processed state.
        try:
            _iqf_sub = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()
            if _iqf_sub:
                _override_rw = None
                if _iqf_sub.submission_type in ('FULL_ACCEPT', 'PARTIAL'):
                    if _iqf_sub.submission_type == 'FULL_ACCEPT' and _iqf_sub.full_accept_data:
                        _src = _iqf_sub.full_accept_data.get('trays', [])
                    elif _iqf_sub.submission_type == 'PARTIAL' and _iqf_sub.partial_accept_data:
                        _src = _iqf_sub.partial_accept_data.get('trays', [])
                    else:
                        _src = []
                    _live = sum(int(t.get('qty', 0)) for t in _src if int(t.get('qty', 0)) > 0)
                    if _live > 0:
                        _override_rw = _live
                elif _iqf_sub.submission_type == 'FULL_REJECT':
                    _override_rw = _iqf_sub.iqf_incoming_qty
                elif _iqf_sub.submission_type == 'LOT_REJECTION':
                    _override_rw = _iqf_sub.iqf_incoming_qty
                if _override_rw is not None and _override_rw > 0:
                    print(f"[AUDIT API] Re-flagged lot {lot_id}: overriding rw_qty from {rw_qty} to {_override_rw} (source: IQF_Submitted {_iqf_sub.submission_type})")
                    rw_qty = _override_rw
        except Exception as _e:
            print(f"[AUDIT API] Re-flagged lot override check failed: {_e}")

        print(f"[AUDIT API] is_full_lot_reject={is_full_lot_reject}, rw_qty={rw_qty}")

        # Check if this lot already has an active LOT_REJECTION submission
        _is_lot_rejection = IQF_Submitted.objects.filter(
            lot_id=lot_id, submission_type=IQF_Submitted.SUB_LOT_REJECT
        ).exists()

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
        # GUARD: skip stale drafts for re-flagged lots (lot returned from Brass QC after IQF completion)
        _has_completed_sub = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).exists()
        try:
            draft = IQF_Draft_Store.objects.filter(lot_id=lot_id, draft_type='batch_rejection').order_by('-updated_at').first()
            if draft and draft.draft_data and not _has_completed_sub:
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
                    "total_iqf_qty": total_from_draft,
                    "is_lot_rejection": _is_lot_rejection,
                })
        except Exception:
            pass

        return Response({
            "success": True,
            "rw_qty": rw_qty,
            "rejection_data": response_data,
            "total_iqf_qty": 0,
            "is_lot_rejection": _is_lot_rejection,
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
    remark = (data.get('remark') or '').strip()
    if not lot_id or not action or action not in ('draft', 'proceed'):
        return Response({'success': False, 'error': 'Missing or invalid parameters'}, status=400)

    # Remark is mandatory when proceeding
    if action == 'proceed' and not remark:
        return Response({'success': False, 'error': 'Remark is mandatory to proceed', 'remark_required': True}, status=400)

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

        # ── Re-flagged lot: override rw_qty from IQF_Submitted (SINGLE SOURCE OF TRUTH) ──
        # When a lot travels Brass QC → IQF multiple times, reason stores hold STALE data.
        try:
            _iqf_sub = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()
            if _iqf_sub:
                _override_rw = None
                # SKIP override for unfinalized PARTIAL — lot is still mid-flow in IQF
                # Override only applies to re-flagged lots (completed IQF cycle, came back)
                if _iqf_sub.submission_type == 'PARTIAL' and not _iqf_sub.partial_reject_data:
                    print(f'[IQF SUBMIT] Unfinalized PARTIAL for {lot_id} — skipping rw_qty override (using original {iqf_incoming_qty})')
                elif _iqf_sub.submission_type in ('FULL_ACCEPT', 'PARTIAL'):
                    if _iqf_sub.submission_type == 'FULL_ACCEPT' and _iqf_sub.full_accept_data:
                        _src = _iqf_sub.full_accept_data.get('trays', [])
                    elif _iqf_sub.submission_type == 'PARTIAL' and _iqf_sub.partial_accept_data:
                        _src = _iqf_sub.partial_accept_data.get('trays', [])
                    else:
                        _src = []
                    _live = sum(int(t.get('qty', 0)) for t in _src if int(t.get('qty', 0)) > 0)
                    if _live > 0:
                        _override_rw = _live
                elif _iqf_sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'):
                    _override_rw = _iqf_sub.iqf_incoming_qty
                if _override_rw is not None and _override_rw > 0:
                    print(f'[IQF SUBMIT] Re-flagged lot {lot_id}: overriding iqf_incoming_qty from {iqf_incoming_qty} to {_override_rw} (source: IQF_Submitted {_iqf_sub.submission_type})')
                    iqf_incoming_qty = _override_rw
                    rw_qty = _override_rw
        except Exception as _e:
            print(f'[IQF SUBMIT] Re-flagged lot override check failed: {_e}')

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

        # ── Detect Brass QC full lot rejection ──
        is_full_lot_reject = False
        if audit_store and getattr(audit_store, 'batch_rejection', False):
            is_full_lot_reject = True
        elif qc_store and getattr(qc_store, 'batch_rejection', False):
            is_full_lot_reject = True
        # Also detect via TotalStockModel flags (accepted_qty=0 + rejection=True)
        if not is_full_lot_reject:
            if getattr(ts, 'brass_qc_rejection', False) and int(getattr(ts, 'brass_qc_accepted_qty', 0) or 0) == 0:
                is_full_lot_reject = True

        # Full lot reject fallback: use lot qty when rw_qty is 0
        if is_full_lot_reject and iqf_incoming_qty <= 0:
            iqf_incoming_qty = original_lot_qty
            print(f'[IQF FULL LOT REJECT] Fallback: iqf_incoming_qty set to lot_qty={original_lot_qty}')

        print(f'[IQF VALIDATION START] lot_id={lot_id}, lot_qty={original_lot_qty}, is_full_lot_reject={is_full_lot_reject}, iqf_incoming_qty={iqf_incoming_qty}')

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
            if is_full_lot_reject:
                # FULL LOT REJECT: skip per-reason validation — only enforce total <= lot qty
                print(f'[IQF FULL LOT REJECT] Skipping per-reason validation. Total IQF={total_iqf}, limit={iqf_incoming_qty}')
                for itm in parsed_items:
                    rid = itm.get('reason_id')
                    qty = itm.get('iqf_qty') or 0
                    if rid is None and qty > 0:
                        return Response({'success': False, 'error': 'Missing reason_id for provided IQF qty; cannot validate'}, status=400)
                    print(f'[VALIDATION FULL_REJECT] reason_id={rid}, entered={qty}')
            else:
                # NORMAL FLOW: per-reason validation against Brass QC breakdown
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
                err_msg = f'IQF rejection ({total_iqf}) cannot exceed {"lot qty" if is_full_lot_reject else "RW quantity"} ({iqf_incoming_qty})'
                print(f'[IQF VALIDATION ERROR] {err_msg}')
                return Response({'success': False, 'error': err_msg, 'rw_qty': iqf_incoming_qty, 'submitted_total': total_iqf}, status=400)

            print(f'[IQF REJECTION COMPUTED] total_iqf_rejection={total_iqf}, is_full_lot_reject={is_full_lot_reject}')

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
                # PARTIAL — Accept is USER-DRIVEN (scanned trays), Reject handled by DELINK MODAL
                #
                # GOLDEN RULES:
                # 1. Accept = user-scanned tray data → store as-is
                # 2. Reject allocation is DEFERRED to delink modal (user picks delink trays first)
                # 3. IQF_Submitted stores accept data only initially (partial_reject_data = None)
                # 4. Delink modal confirm fills partial_reject_data and finalizes
                # 5. Top tray must NEVER be jumbled — preserve original top_tray flag

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
                accepted_tray_id_set = set(t['tray_id'] for t in accepted_trays)
                print(f'[PARTIAL ACCEPT] User-scanned: {len(accepted_trays)} trays, total={accept_total}, expected={accepted_qty}')
                print(f'[PARTIAL ACCEPT] Accepted tray IDs: {accepted_tray_id_set}')

                if accept_total != accepted_qty:
                    return Response({
                        'success': False,
                        'error': f'Scanned accept tray total ({accept_total}) ≠ accepted qty ({accepted_qty}). Verify tray scans.',
                        'accept_total': accept_total,
                        'accepted_qty': accepted_qty,
                    }, status=400)

                # ── Gather original trays for response (needed by delink modal) ──
                all_orig_trays = list(IQFTrayId.objects.filter(
                    lot_id=lot_id, delink_tray=False
                ).order_by('id'))

                # ── REJECT ALLOCATION DEFERRED — handled by delink modal ──
                # Do NOT allocate reject trays here. The delink modal will compute
                # reject allocation after user selects which trays to delink.
                reject_tray_id_set = set()
                print(f'[PARTIAL] Reject allocation DEFERRED to delink modal. rejected_qty={rejected_qty}')

                partial_accept_data = {
                    'label': 'PARTIAL_ACCEPT',
                    'qty': accepted_qty,
                    'total_trays': len(accepted_trays),
                    'trays': accepted_trays,
                }
                # partial_reject_data left None — filled by delink modal confirm

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
                    'remarks': remark,
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
            else:  # PARTIAL — Step 1: save data, set onhold for verification
                ts.iqf_onhold_picking = True  # Shows "Verify Trays" button
                ts.iqf_few_cases_acceptance = False  # Finalized on verify step
                ts.iqf_acceptance = False
                ts.iqf_rejection = False
                ts.send_brass_qc = False  # Don't move to Brass QC yet — pending verification

            ts.iqf_accepted_qty = accepted_qty
            ts.iqf_after_rejection_qty = rejected_qty
            ts.iqf_accepted_qty_verified = False  # Reset for fresh cycle on re-entry
            ts.last_process_module = 'IQF'
            # PARTIAL keeps send_brass_audit_to_iqf=True so lot stays in IQF pick table
            if submission_type != IQF_Submitted.SUB_PARTIAL:
                ts.send_brass_audit_to_iqf = False
            ts.iqf_last_process_date_time = timezone.now()

            ts.save(update_fields=[
                'iqf_acceptance', 'iqf_rejection', 'iqf_few_cases_acceptance',
                'iqf_onhold_picking',
                'iqf_accepted_qty', 'iqf_after_rejection_qty',
                'iqf_accepted_qty_verified',
                'last_process_module', 'send_brass_audit_to_iqf',
                'send_brass_qc', 'next_process_module',
                'iqf_last_process_date_time',
            ])

            print(f'[MOVEMENT] iqf_acceptance={ts.iqf_acceptance}, '
                  f'iqf_rejection={ts.iqf_rejection}, '
                  f'iqf_few_cases_acceptance={ts.iqf_few_cases_acceptance}, '
                  f'send_brass_audit_to_iqf={ts.send_brass_audit_to_iqf}, '
                  f'send_brass_qc={ts.send_brass_qc}')

            # ─── 14. BUILD RESPONSE — PARTIAL gets enriched reject/delink flags ───
            resp_data = {
                'success': True,
                'proceeded': True,
                'submission_type': submission_type,
                'original_lot_qty': original_lot_qty,
                'iqf_incoming_qty': iqf_incoming_qty,
                'accepted_qty': accepted_qty,
                'rejected_qty': rejected_qty,
                'rw_qty': iqf_incoming_qty,
                'total_iqf_qty': total_iqf,
            }

            if submission_type == IQF_Submitted.SUB_PARTIAL:
                # PARTIAL: Always open delink modal — user controls delink/reject tray selection
                resp_data['open_delink_modal'] = True
                resp_data['reject_required'] = rejected_qty > 0
                resp_data['lot_id'] = lot_id

                print(f'[PARTIAL RESPONSE] open_delink_modal=True, accepted={accepted_qty}, rejected={rejected_qty}')

            return Response(resp_data)

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

        if iqf_record and iqf_record.submission_type in ('FULL_ACCEPT', 'PARTIAL', 'FULL_REJECT', 'LOT_REJECTION'):
            if iqf_record.submission_type == 'FULL_ACCEPT' and iqf_record.full_accept_data:
                source_trays = iqf_record.full_accept_data.get('trays', [])
                label = 'FULL_ACCEPT'
                is_rejected = False
                tray_status = 'ACCEPTED'
            elif iqf_record.submission_type in ('FULL_REJECT', 'LOT_REJECTION') and iqf_record.full_reject_data:
                source_trays = iqf_record.full_reject_data.get('trays', [])
                label = 'FULL_REJECT'
                is_rejected = True
                tray_status = 'REJECTED'
            elif iqf_record.submission_type == 'PARTIAL' and iqf_record.partial_accept_data:
                source_trays = iqf_record.partial_accept_data.get('trays', [])
                label = 'PARTIAL_ACCEPT'
                is_rejected = False
                tray_status = 'ACCEPTED'
            else:
                source_trays = []
                label = 'EMPTY'
                is_rejected = False
                tray_status = 'ACCEPTED'

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
                    'status': tray_status,
                    'is_rejected': is_rejected,
                    'is_reusable': not is_rejected,
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

        # ✅ FINAL FALLBACK: If no Brass QC/Audit rejection rows, use IQFTrayId directly
        # Covers case: Brass QC full lot rejection → sent to IQF → IQF not yet completed
        if not tray_qty_map:
            iqf_tray_rows = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).order_by('id')
            for row in iqf_tray_rows:
                qty = row.tray_quantity or 0
                if qty > 0:
                    tray_qty_map[row.tray_id] = tray_qty_map.get(row.tray_id, 0) + qty
            if tray_qty_map:
                print(f"[IQF TRAY API] Using IQFTrayId fallback for lot {lot_id}: {len(tray_qty_map)} trays")

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

# IQF Completed Table API: returns all lots from IQF_Submitted (SINGLE SOURCE OF TRUTH)
@method_decorator(login_required, name='dispatch')
class IQFCompletedTableView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            print('[IQF COMPLETED API] Called — SOURCE: IQF_Submitted')

            # SINGLE SOURCE OF TRUTH: IQF_Submitted table
            submitted_qs = IQF_Submitted.objects.select_related(
                'batch_id', 'batch_id__model_stock_no', 'batch_id__version',
                'batch_id__location', 'created_by'
            ).filter(is_completed=True).order_by('-created_at')

            data = []
            for sub in submitted_qs:
                # Determine status label
                if sub.submission_type == 'FULL_ACCEPT':
                    status_label = 'ACCEPT'
                elif sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'):
                    status_label = 'REJECT'
                elif sub.submission_type == 'PARTIAL':
                    status_label = 'PARTIAL'
                else:
                    status_label = sub.submission_type

                # Extract tray data from stored snapshots
                accept_data = sub.partial_accept_data or sub.full_accept_data
                reject_data = sub.partial_reject_data or sub.full_reject_data

                accepted_trays = []
                if accept_data and accept_data.get('trays'):
                    accepted_trays = [{'tray_id': t.get('tray_id', ''), 'tray_qty': int(t.get('qty', 0))} for t in accept_data['trays'] if int(t.get('qty', 0)) > 0]

                rejected_trays = []
                if reject_data and reject_data.get('trays'):
                    rejected_trays = [{'tray_id': t.get('tray_id', ''), 'tray_qty': int(t.get('qty', 0))} for t in reject_data['trays'] if int(t.get('qty', 0)) > 0]

                # Compute delinked from original snapshot
                delinked_trays = []
                accept_ids = {t['tray_id'] for t in accepted_trays}
                reject_ids = {t['tray_id'] for t in rejected_trays}
                orig = sub.original_data or {}
                for t in orig.get('trays', []):
                    tid = t.get('tray_id', '')
                    if tid and tid not in accept_ids and tid not in reject_ids:
                        delinked_trays.append({'tray_id': tid, 'tray_qty': int(t.get('qty', 0))})

                data.append({
                    'lot_id': sub.lot_id,
                    'batch_id': sub.batch_id.batch_id if sub.batch_id else '',
                    'model_no': getattr(sub.batch_id.model_stock_no, 'model_no', '') if sub.batch_id and getattr(sub.batch_id, 'model_stock_no', None) else '',
                    'location': getattr(sub.batch_id.location, 'location_name', '') if sub.batch_id and getattr(sub.batch_id, 'location', None) else '',
                    'iqf_incoming_qty': sub.iqf_incoming_qty,
                    'iqf_accepted_qty': sub.accepted_qty,
                    'iqf_rejection_qty': sub.rejected_qty,
                    'delink_qty': sum(t['tray_qty'] for t in delinked_trays),
                    'submission_type': sub.submission_type,
                    'status_label': status_label,
                    'status': status_label,
                    'last_updated': sub.created_at,
                    'remarks': sub.remarks or '',
                    'created_by': sub.created_by.username if sub.created_by else '',
                    'tray_details': accepted_trays + rejected_trays + delinked_trays,
                    'accepted_trays': accepted_trays,
                    'rejected_trays': rejected_trays,
                    'delinked_trays': delinked_trays,
                })

            print(f'[IQF COMPLETED API] Count: {len(data)}, Source: IQF_Submitted')
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
        """IQF Completed Page — renders table data from IQF_Submitted (SINGLE SOURCE OF TRUTH)."""
        try:
            submitted_qs = IQF_Submitted.objects.select_related(
                'batch_id', 'batch_id__model_stock_no', 'batch_id__version',
                'batch_id__location', 'created_by'
            ).filter(is_completed=True).order_by('-created_at')

            master_data = []
            for sub in submitted_qs:
                batch = sub.batch_id
                if not batch:
                    continue

                # Status label
                if sub.submission_type == 'FULL_ACCEPT':
                    status_label = 'ACCEPT'
                elif sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'):
                    status_label = 'REJECT'
                elif sub.submission_type == 'PARTIAL':
                    status_label = 'PARTIAL'
                else:
                    status_label = sub.submission_type

                # Model images
                images = []
                if batch.model_stock_no:
                    for img in batch.model_stock_no.images.all():
                        if img.master_image:
                            images.append(img.master_image.url)
                if not images:
                    images = [static('assets/images/imagePlaceholder.jpg')]

                # Tray count from stored snapshot
                accept_data = sub.partial_accept_data or sub.full_accept_data
                reject_data = sub.partial_reject_data or sub.full_reject_data
                accept_trays = (accept_data or {}).get('trays', [])
                reject_trays = (reject_data or {}).get('trays', [])
                total_trays = len([t for t in accept_trays if int(t.get('qty', 0)) > 0]) + len([t for t in reject_trays if int(t.get('qty', 0)) > 0])

                master_data.append({
                    'batch_id': batch.batch_id,
                    'stock_lot_id': sub.lot_id,
                    'iqf_last_process_date_time': sub.created_at,
                    'plating_stk_no': batch.plating_stk_no or '',
                    'polishing_stk_no': batch.polishing_stk_no or '',
                    'plating_color': batch.plating_color or '',
                    'polish_finish': batch.polish_finish or '',
                    'location__location_name': batch.location.location_name if batch.location else '',
                    'tray_type': batch.tray_type or '',
                    'tray_capacity': batch.tray_capacity or 0,
                    'no_of_trays': total_trays,
                    'display_quantity': sub.iqf_incoming_qty,
                    'iqf_accepted_qty': sub.accepted_qty,
                    'iqf_rejection_qty': sub.rejected_qty,
                    'iqf_acceptance': sub.submission_type == 'FULL_ACCEPT',
                    'iqf_rejection': sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'),
                    'iqf_few_cases_acceptance': sub.submission_type == 'PARTIAL',
                    'iqf_accepted_qty_verified': True,
                    'iqf_missing_qty': 0,
                    'iqf_physical_qty': sub.iqf_incoming_qty,
                    'iqf_hold_lot': False,
                    'brass_rejection_total_qty': sub.iqf_incoming_qty,
                    'brass_onhold_picking': False,
                    'last_process_module': 'IQF',
                    'iqf_accepted_tray_scan_status': True,
                    'Moved_to_D_Picker': False,
                    'model_images': images,
                    'status_label': status_label,
                    'submission_type': sub.submission_type,
                    'remarks': sub.remarks or '',
                    'tray_qty_list': '',
                })

            return Response({'master_data': master_data}, template_name=self.template_name)
        except Exception as e:
            print(f'[IQF COMPLETED PAGE ERROR] {e}')
            traceback.print_exc()
            return Response({'master_data': []}, template_name=self.template_name)


# IQF Accept Table
@method_decorator(login_required, name='dispatch')
class IQFAcceptTablePageView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'IQF/Iqf_AcceptTable.html'

    def get(self, request):
        """IQF Accept Table — shows only ACCEPTED lots from IQF_Submitted."""
        try:
            submitted_qs = IQF_Submitted.objects.select_related(
                'batch_id', 'batch_id__model_stock_no', 'batch_id__version',
                'batch_id__location', 'created_by'
            ).filter(
                is_completed=True, accepted_qty__gt=0
            ).exclude(
                submission_type__in=['FULL_REJECT', 'LOT_REJECTION']
            ).order_by('-created_at')

            master_data = []
            for sub in submitted_qs:
                batch = sub.batch_id
                if not batch:
                    continue

                # Model images
                images = []
                if batch.model_stock_no:
                    for img in batch.model_stock_no.images.all():
                        if img.master_image:
                            images.append(img.master_image.url)
                if not images:
                    images = [static('assets/images/imagePlaceholder.jpg')]

                # Tray info from snapshot
                accept_data = sub.partial_accept_data or sub.full_accept_data
                accept_trays = (accept_data or {}).get('trays', [])
                total_trays = len([t for t in accept_trays if int(t.get('qty', 0)) > 0])

                # Accepted comment from IQF_Accepted_TrayID_Store
                comment_obj = IQF_Accepted_TrayID_Store.objects.filter(lot_id=sub.lot_id).first()
                accepted_comment = comment_obj.accepted_comment if comment_obj else ''

                master_data.append({
                    'batch_id': batch.batch_id,
                    'stock_lot_id': sub.lot_id,
                    'iqf_last_process_date_time': sub.created_at,
                    'plating_stk_no': batch.plating_stk_no or '',
                    'polishing_stk_no': batch.polishing_stk_no or '',
                    'plating_color': batch.plating_color or '',
                    'polish_finish': batch.polish_finish or '',
                    'location__location_name': batch.location.location_name if batch.location else '',
                    'tray_type': batch.tray_type or '',
                    'tray_capacity': batch.tray_capacity or 0,
                    'no_of_trays': total_trays,
                    'iqf_accepted_qty': sub.accepted_qty,
                    'iqf_rejection_qty': sub.rejected_qty,
                    'iqf_acceptance': sub.submission_type == 'FULL_ACCEPT',
                    'iqf_rejection': sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'),
                    'iqf_few_cases_acceptance': sub.submission_type == 'PARTIAL',
                    'iqf_accepted_qty_verified': True,
                    'iqf_missing_qty': 0,
                    'iqf_physical_qty': sub.iqf_incoming_qty,
                    'brass_onhold_picking': False,
                    'last_process_module': 'IQF',
                    'iqf_accepted_tray_scan_status': True,
                    'Moved_to_D_Picker': False,
                    'model_images': images,
                    'status_label': 'ACCEPT' if sub.submission_type == 'FULL_ACCEPT' else 'PARTIAL',
                    'submission_type': sub.submission_type,
                    'accepted_comment': accepted_comment or '',
                    'IQF_pick_remarks': sub.remarks or '',
                    'tray_qty_list': '',
                })

            return Response({'master_data': master_data}, template_name=self.template_name)
        except Exception as e:
            print(f'[IQF ACCEPT TABLE ERROR] {e}')
            traceback.print_exc()
            return Response({'master_data': []}, template_name=self.template_name)


# IQF - Reject table
@method_decorator(login_required, name='dispatch')
class IQFRejectionTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'IQF/Iqf_RejectTable.html'

    def get(self, request):
        """IQF Rejection Table — shows all lots with IQF rejections (partial or full).
        Backend computes everything, frontend is pure render.
        """
        try:
            submitted_qs = IQF_Submitted.objects.select_related(
                'batch_id', 'batch_id__model_stock_no', 'batch_id__version',
                'batch_id__location', 'created_by'
            ).filter(
                rejected_qty__gt=0, is_completed=True
            ).order_by('-created_at')

            # Pre-fetch lot IDs that have IQFTrayId records (for delink checkbox)
            all_lot_ids = list(submitted_qs.values_list('lot_id', flat=True))
            lots_with_trays = set(
                IQFTrayId.objects.filter(
                    lot_id__in=all_lot_ids, delink_tray=False
                ).values_list('lot_id', flat=True).distinct()
            )

            master_data = []
            for sub in submitted_qs:
                batch = sub.batch_id
                if not batch:
                    continue

                # Model images
                images = []
                if batch.model_stock_no:
                    for img in batch.model_stock_no.images.all():
                        if img.master_image:
                            images.append(img.master_image.url)
                if not images:
                    images = [static('assets/images/imagePlaceholder.jpg')]

                # Rejection reason letters (first char of each reason)
                rejection_reason_letters = []
                if sub.rejection_details:
                    for rd in sub.rejection_details:
                        reason_text = rd.get('reason_text', '')
                        if reason_text:
                            rejection_reason_letters.append(reason_text[0].upper())

                # Reject tray count from snapshot
                reject_data = sub.partial_reject_data or sub.full_reject_data
                reject_trays = (reject_data or {}).get('trays', [])
                no_of_trays = len([t for t in reject_trays if int(t.get('qty', 0)) > 0])

                # Lot rejection flag + comment
                is_lot_rejection = sub.submission_type in ('LOT_REJECTION',)

                # Status label
                if sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'):
                    status_label = 'REJECT'
                elif sub.submission_type == 'PARTIAL':
                    status_label = 'PARTIAL'
                else:
                    status_label = sub.submission_type

                master_data.append({
                    'batch_id': batch.batch_id,
                    'stock_lot_id': sub.lot_id,
                    'iqf_last_process_date_time': sub.created_at,
                    'plating_stk_no': batch.plating_stk_no or '',
                    'polishing_stk_no': batch.polishing_stk_no or '',
                    'plating_color': batch.plating_color or '',
                    'polish_finish': batch.polish_finish or '',
                    'location__location_name': batch.location.location_name if batch.location else '',
                    'tray_type': batch.tray_type or '',
                    'tray_capacity': batch.tray_capacity or 0,
                    'no_of_trays': no_of_trays,
                    'iqf_rejection_total_qty': sub.rejected_qty,
                    'brass_rejection_total_qty': sub.iqf_incoming_qty,
                    'iqf_missing_qty': 0,
                    'model_images': images,
                    'rejection_reason_letters': rejection_reason_letters,
                    'batch_rejection': is_lot_rejection,
                    'lot_rejected_comment': sub.remarks or '',
                    'dp_missing_qty': 0,
                    'tray_id_in_trayid': sub.lot_id in lots_with_trays,
                    'status_label': status_label,
                    'submission_type': sub.submission_type,
                })

            # Pagination
            page_number = request.GET.get('page', 1)
            paginator = Paginator(master_data, 20)
            page_obj = paginator.get_page(page_number)

            return Response({
                'master_data': page_obj.object_list,
                'page_obj': page_obj,
            }, template_name=self.template_name)
        except Exception as e:
            print(f'[IQF REJECTION TABLE ERROR] {e}')
            traceback.print_exc()
            return Response({'master_data': [], 'page_obj': None}, template_name=self.template_name)


# ── IQF Verify Trays Confirm — Step 2 of PARTIAL flow ──
# GET: returns saved IQF_Submitted data for confirmation popup
# POST: finalizes the submission — sets movement flags for Brass QC
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def iqf_verify_trays_confirm(request):
    lot_id = request.query_params.get('lot_id') if request.method == 'GET' else (request.data or {}).get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

    try:
        ts = TotalStockModel.objects.get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return Response({'success': False, 'error': f'Lot {lot_id} not found'}, status=404)

    # Guard: lot must be in onhold (VERIFY) state
    if not ts.iqf_onhold_picking:
        return Response({'success': False, 'error': f'Lot {lot_id} is not in IQF verification state'}, status=400)

    sub = IQF_Submitted.objects.filter(lot_id=lot_id).first()
    if not sub:
        return Response({'success': False, 'error': f'No IQF submission found for lot {lot_id}'}, status=404)

    if request.method == 'GET':
        # Return summary data for the confirmation popup
        reject_trays = []
        reject_data = sub.partial_reject_data or sub.full_reject_data
        if reject_data and reject_data.get('trays'):
            reject_trays = reject_data['trays']

        accept_trays = []
        accept_data = sub.partial_accept_data or sub.full_accept_data
        if accept_data and accept_data.get('trays'):
            accept_trays = accept_data['trays']

        # ── Compute freed (delinked) trays dynamically from stored snapshots ──
        freed_trays = []
        original_data = sub.original_data or {}
        original_trays = original_data.get('trays', [])
        if original_trays:
            accept_tray_ids = {t.get('tray_id', '') for t in accept_trays}
            reject_tray_ids = {t.get('tray_id', '') for t in reject_trays}
            for t in original_trays:
                tid = t.get('tray_id', '')
                if tid and tid not in accept_tray_ids and tid not in reject_tray_ids:
                    freed_trays.append({'tray_id': tid, 'qty': t.get('qty', 0)})

        return Response({
            'success': True,
            'lot_id': lot_id,
            'submission_type': sub.submission_type,
            'iqf_incoming_qty': sub.iqf_incoming_qty,
            'accepted_qty': sub.accepted_qty,
            'rejected_qty': sub.rejected_qty,
            'reject_trays': reject_trays,
            'accept_trays': accept_trays,
            'freed_trays': freed_trays,
            'rejection_details': sub.rejection_details or [],
        })

    # POST — finalize the submission
    with transaction.atomic():
        ts.iqf_few_cases_acceptance = True
        ts.iqf_onhold_picking = False
        ts.send_brass_qc = True
        ts.send_brass_audit_to_iqf = False  # Now remove from IQF pick table
        ts.iqf_accepted_qty_verified = False  # Reset for fresh cycle on re-entry
        ts.next_process_module = 'Brass QC'
        ts.save(update_fields=[
            'iqf_few_cases_acceptance', 'iqf_onhold_picking',
            'send_brass_qc', 'send_brass_audit_to_iqf', 'iqf_accepted_qty_verified', 'next_process_module',
        ])
        print(f'[IQF VERIFY CONFIRM] lot={lot_id} finalized: few_cases=True, onhold=False, send_brass_qc=True, send_brass_audit_to_iqf=False')

    return Response({
        'success': True,
        'message': 'IQF verification completed. Lot moved to Brass QC.',
        'lot_id': lot_id,
    })


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

        # ── Re-flagged lot: override rw_qty from IQF_Submitted (SINGLE SOURCE OF TRUTH) ──
        try:
            _iqf_sub = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()
            if _iqf_sub:
                _override_rw = None
                # SKIP override for unfinalized PARTIAL — lot is still mid-flow in IQF
                if _iqf_sub.submission_type == 'PARTIAL' and not _iqf_sub.partial_reject_data:
                    print(f'[IQF TRAY SLOTS] Unfinalized PARTIAL for {lot_id} — skipping rw_qty override')
                elif _iqf_sub.submission_type in ('FULL_ACCEPT', 'PARTIAL'):
                    if _iqf_sub.submission_type == 'FULL_ACCEPT' and _iqf_sub.full_accept_data:
                        _src = _iqf_sub.full_accept_data.get('trays', [])
                    elif _iqf_sub.submission_type == 'PARTIAL' and _iqf_sub.partial_accept_data:
                        _src = _iqf_sub.partial_accept_data.get('trays', [])
                    else:
                        _src = []
                    _live = sum(int(t.get('qty', 0)) for t in _src if int(t.get('qty', 0)) > 0)
                    if _live > 0:
                        _override_rw = _live
                elif _iqf_sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'):
                    _override_rw = _iqf_sub.iqf_incoming_qty
                if _override_rw is not None and _override_rw > 0:
                    print(f'[IQF TRAY SLOTS] Re-flagged lot {lot_id}: overriding rw_qty from {rw_qty} to {_override_rw}')
                    rw_qty = _override_rw
        except Exception as _e:
            print(f'[IQF TRAY SLOTS] Re-flagged lot override check failed: {_e}')

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

        # 4. Compute max reuse limit — reserve trays for rejection, remaining reusable
        #    FORMULA: max_reuse_limit = total_trays - ceil(rejection_qty / tray_capacity)
        #    Rejection reserves its trays first → remaining trays fully reusable for accept.
        max_reuse_limit = 0
        if iqf_rejection_total > 0:
            total_trays = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).count()
            if total_trays == 0:
                total_trays = BrassTrayId.objects.filter(lot_id=lot_id, delink_tray=False).count()
            rejection_trays = ceil(iqf_rejection_total / tray_capacity)
            max_reuse_limit = max(0, total_trays - rejection_trays)

        print(f'[IQF TRAY SLOTS] lot={lot_id}, rw={rw_qty}, rej={rejected_qty}, '
              f'acc={accepted_qty}, cap={tray_capacity}, slots={len(slots)}, max_reuse_limit={max_reuse_limit}')

        return Response({
            'success': True,
            'rw_qty': rw_qty,
            'accepted_qty': accepted_qty,
            'rejected_qty': rejected_qty,
            'tray_capacity': tray_capacity,
            'slots': slots,
            'max_reuse_limit': max_reuse_limit,
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

    # ── RULE 3a: Compute max reuse limit from rejection qty ──
    iqf_rej_str = request.GET.get('iqf_rejection_total', '')
    reuse_count_str = request.GET.get('reuse_count', '0')
    max_reuse_limit = 0   # 0 = no reuse restriction active
    reuse_count = 0
    if iqf_rej_str:
        try:
            iqf_rej = int(iqf_rej_str)
            if iqf_rej > 0:
                # Resolve tray capacity for this lot
                _cap = 16  # safe default
                iqf_cap_tray = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).exclude(tray_capacity__isnull=True).exclude(tray_capacity=0).first()
                if iqf_cap_tray and iqf_cap_tray.tray_capacity and iqf_cap_tray.tray_capacity > 0:
                    _cap = iqf_cap_tray.tray_capacity
                else:
                    brass_cap_tray = BrassTrayId.objects.filter(lot_id=lot_id, delink_tray=False).exclude(tray_capacity__isnull=True).exclude(tray_capacity=0).first()
                    if brass_cap_tray and brass_cap_tray.tray_capacity and brass_cap_tray.tray_capacity > 0:
                        _cap = brass_cap_tray.tray_capacity
                    else:
                        _ts = TotalStockModel.objects.filter(lot_id=lot_id).select_related('batch_id').first()
                        if _ts and _ts.batch_id and _ts.batch_id.tray_capacity and _ts.batch_id.tray_capacity > 0:
                            _cap = _ts.batch_id.tray_capacity
                _total_trays = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).count()
                if _total_trays == 0:
                    _total_trays = BrassTrayId.objects.filter(lot_id=lot_id, delink_tray=False).count()
                _rejection_trays = ceil(iqf_rej / _cap)
                max_reuse_limit = max(0, _total_trays - _rejection_trays)
                reuse_count = max(0, int(reuse_count_str))
        except (ValueError, TypeError):
            pass

    # ── RULE 3: Lot membership check ──
    # Check IQFTrayId first (primary), then BrassTrayId (fallback)
    iqf_match = IQFTrayId.objects.filter(lot_id=lot_id, tray_id=tray_id, delink_tray=False).first()
    if iqf_match:
        if max_reuse_limit > 0 and reuse_count >= max_reuse_limit:
            return Response({
                'success': True,
                'status': 'no_reuse',
                'message': 'Reuse limit reached. Please scan new trays.',
                'tray_id': tray_id,
            })
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
        if max_reuse_limit > 0 and reuse_count >= max_reuse_limit:
            return Response({
                'success': True,
                'status': 'no_reuse',
                'message': 'Reuse limit reached. Please scan new trays.',
                'tray_id': tray_id,
            })
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
            'message': 'New Tray',
            'tray_id': tray_id,
        })

    # Tray ID format valid but not found anywhere in the system
    return Response({
        'success': True,
        'status': 'delink',
        'message': 'New Tray',
        'tray_id': tray_id,
    })


# ── IQF Accept Table → Delink & Reject Allocation Modal — Backend SSOT ──
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def iqf_accept_delink_modal(request):
    """Compute tray allocation for the Accept → Delink & Reject Allocation modal.

    Backend is SINGLE SOURCE OF TRUTH — frontend is pure fetch + render.
    Uses the SAME allocation algorithm as iqf_submit_audit PARTIAL flow.

    GET:  ?lot_id=X&iqf_rejection_total=Y&accepted_tray_ids=NB-001,NB-002
    POST: { lot_id, iqf_rejection_total, accepted_tray_ids: [...], delinked_tray_ids: [...] }

    Returns: original_trays with status, max_delink_count, reject_allocation
    """
    # ── Parse parameters from GET or POST ──
    if request.method == 'GET':
        lot_id = request.GET.get('lot_id', '').strip()
        rej_total_str = request.GET.get('iqf_rejection_total', '0')
        acc_ids_raw = request.GET.get('accepted_tray_ids', '')
        del_ids_raw = request.GET.get('delinked_tray_ids', '')
        accepted_tray_ids = [x.strip() for x in acc_ids_raw.split(',') if x.strip()] if acc_ids_raw else []
        delinked_tray_ids = [x.strip() for x in del_ids_raw.split(',') if x.strip()] if del_ids_raw else []
    else:
        payload = request.data or {}
        lot_id = (payload.get('lot_id') or '').strip()
        rej_total_str = str(payload.get('iqf_rejection_total', '0'))
        accepted_tray_ids = payload.get('accepted_tray_ids') or []
        delinked_tray_ids = payload.get('delinked_tray_ids') or []

    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

    try:
        iqf_rejection_total = int(rej_total_str)
    except (ValueError, TypeError):
        return Response({'success': False, 'error': 'iqf_rejection_total must be integer'}, status=400)

    if iqf_rejection_total < 0:
        return Response({'success': False, 'error': 'iqf_rejection_total must be non-negative'}, status=400)

    try:
        ts = TotalStockModel.objects.filter(lot_id=lot_id).select_related('batch_id').first()
        if not ts:
            return Response({'success': False, 'error': 'Lot not found'}, status=404)

        # ── Resolve rw_qty — SINGLE SOURCE OF TRUTH (same as iqf_accepted_tray_slots) ──
        audit_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        qc_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        rw_qty = 0
        if audit_store and getattr(audit_store, 'total_rejection_quantity', None) is not None:
            rw_qty = audit_store.total_rejection_quantity
        elif qc_store and getattr(qc_store, 'total_rejection_quantity', None) is not None:
            rw_qty = qc_store.total_rejection_quantity

        # Re-flagged lot override from IQF_Submitted
        try:
            _iqf_sub = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()
            if _iqf_sub:
                _override = None
                # SKIP override for unfinalized PARTIAL — lot is still mid-flow in IQF
                if _iqf_sub.submission_type == 'PARTIAL' and not _iqf_sub.partial_reject_data:
                    pass  # Use original rw_qty
                elif _iqf_sub.submission_type in ('FULL_ACCEPT', 'PARTIAL'):
                    _src = (_iqf_sub.full_accept_data or {}).get('trays', []) if _iqf_sub.submission_type == 'FULL_ACCEPT' else (_iqf_sub.partial_accept_data or {}).get('trays', [])
                    _live = sum(int(t.get('qty', 0)) for t in _src if int(t.get('qty', 0)) > 0)
                    if _live > 0:
                        _override = _live
                elif _iqf_sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'):
                    _override = _iqf_sub.iqf_incoming_qty
                if _override and _override > 0:
                    rw_qty = _override
        except Exception:
            pass

        if rw_qty <= 0:
            return Response({'success': False, 'error': 'No IQF incoming qty — rw_qty is 0'}, status=400)

        accepted_qty = rw_qty - iqf_rejection_total
        rejected_qty = iqf_rejection_total

        if accepted_qty < 0:
            return Response({'success': False, 'error': 'Rejection total exceeds RW qty'}, status=400)

        # ── Resolve global tray capacity ──
        def _resolve_global_cap():
            iqf_t = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).exclude(
                tray_capacity__isnull=True).exclude(tray_capacity=0).first()
            if iqf_t and iqf_t.tray_capacity and iqf_t.tray_capacity > 0:
                return iqf_t.tray_capacity
            brass_t = BrassTrayId.objects.filter(lot_id=lot_id, delink_tray=False).exclude(
                tray_capacity__isnull=True).exclude(tray_capacity=0).first()
            if brass_t and brass_t.tray_capacity and brass_t.tray_capacity > 0:
                return brass_t.tray_capacity
            if ts.batch_id and ts.batch_id.tray_capacity and ts.batch_id.tray_capacity > 0:
                return ts.batch_id.tray_capacity
            return 16

        tray_capacity = _resolve_global_cap()

        # ── Resolve per-tray capacity (same as iqf_submit_audit) ──
        def _resolve_tray_cap(iqf_tray_obj):
            cap = getattr(iqf_tray_obj, 'tray_capacity', None)
            if cap and cap > 0:
                return cap
            brass = BrassTrayId.objects.filter(tray_id=iqf_tray_obj.tray_id).exclude(
                tray_capacity__isnull=True).first()
            if brass and brass.tray_capacity and brass.tray_capacity > 0:
                return brass.tray_capacity
            tray_master = TrayId.objects.filter(tray_id=iqf_tray_obj.tray_id).exclude(
                tray_capacity__isnull=True).first()
            if tray_master and tray_master.tray_capacity and tray_master.tray_capacity > 0:
                return tray_master.tray_capacity
            try:
                if ts.batch_id and ts.batch_id.tray_capacity and ts.batch_id.tray_capacity > 0:
                    return ts.batch_id.tray_capacity
            except Exception:
                pass
            return 16

        # ── Get all original lot trays (non-delinked) ──
        all_trays_qs = list(IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).order_by('id'))

        accepted_set = set(accepted_tray_ids)
        delinked_set = set(delinked_tray_ids) - accepted_set  # safety: accepted cannot be delinked

        # ── Compute max delink count ──
        non_accepted = [t for t in all_trays_qs if (t.tray_id or '') not in accepted_set]
        min_reject_trays_needed = ceil(rejected_qty / tray_capacity) if rejected_qty > 0 else 0
        max_delink_count = max(0, len(non_accepted) - min_reject_trays_needed)

        # Enforce delink limit — only valid original tray IDs, up to max
        all_tray_id_set = set(t.tray_id or '' for t in all_trays_qs)
        valid_delinked = [tid for tid in delinked_tray_ids if tid in all_tray_id_set and tid not in accepted_set]
        if len(valid_delinked) > max_delink_count:
            valid_delinked = valid_delinked[:max_delink_count]
        delinked_set = set(valid_delinked)

        # ── Show reject allocation only when delink selection is complete ──
        # Delink complete = user has selected max_delink_count trays (or no delinks possible)
        show_reject = len(valid_delinked) >= max_delink_count

        if show_reject:
            # ── Build reject pool = non-accepted, non-delinked ──
            reject_pool = [t for t in all_trays_qs
                           if (t.tray_id or '') not in accepted_set
                           and (t.tray_id or '') not in delinked_set]

            # ── Allocate rejected_qty in REVERSE order — same algo as iqf_submit_audit ──
            reject_allocation = []
            remaining_to_reject = rejected_qty
            for t in reversed(reject_pool):
                if remaining_to_reject <= 0:
                    break
                cap = _resolve_tray_cap(t)
                take = min(cap, remaining_to_reject)
                reject_allocation.append({
                    'tray_id': t.tray_id or '',
                    'qty': take,
                    'top_tray': bool(t.top_tray),
                })
                remaining_to_reject -= take
            reject_allocation.reverse()
        else:
            # Delink not fully selected — don't compute reject yet
            reject_pool = []
            reject_allocation = []
            remaining_to_reject = rejected_qty

        reject_tray_id_set = set(r['tray_id'] for r in reject_allocation)
        reject_qty_map = {r['tray_id']: r['qty'] for r in reject_allocation}

        # ── Build tray list with status ──
        original_trays = []
        for t in all_trays_qs:
            remaining = int(getattr(t, 'remaining_qty', 0) or 0)
            raw_qty = int(getattr(t, 'tray_quantity', 0) or 0)
            qty = remaining if remaining > 0 else raw_qty
            cap = _resolve_tray_cap(t)
            tid = t.tray_id or ''

            if tid in accepted_set:
                tray_status = 'ACCEPTED'
            elif tid in delinked_set:
                tray_status = 'DELINKED'
            elif show_reject and tid in reject_tray_id_set:
                tray_status = 'REJECT'
            else:
                tray_status = 'PENDING'

            entry = {
                'tray_id': tid,
                'original_qty': qty,
                'capacity': cap,
                'top_tray': bool(t.top_tray),
                'status': tray_status,
            }
            if tray_status == 'REJECT':
                entry['reject_qty'] = reject_qty_map.get(tid, 0)
            original_trays.append(entry)

        print(f'[IQF DELINK MODAL] lot={lot_id}, rw={rw_qty}, acc={accepted_qty}, rej={rejected_qty}, '
              f'trays={len(all_trays_qs)}, in_accept={len(accepted_set)}, delinked={len(delinked_set)}, '
              f'reject_pool={len(reject_pool)}, max_delink={max_delink_count}, '
              f'reject_fully_allocated={remaining_to_reject == 0}')

        # ── Compute reject pool total capacity for UI capacity bar ──
        reject_pool_capacity = 0
        for t in all_trays_qs:
            tid = t.tray_id or ''
            if tid not in accepted_set and tid not in delinked_set:
                reject_pool_capacity += _resolve_tray_cap(t)

        # ── CONFIRM MODE: Update IQF_Submitted and finalize ──
        if request.method == 'POST' and payload.get('confirm'):
            # CAPACITY SAFETY GUARD — reject pool must hold all rejected qty
            if reject_pool_capacity < rejected_qty:
                return Response({
                    'success': False,
                    'error': f'Selected trays cannot fulfill reject quantity. Pool capacity ({reject_pool_capacity}) < reject needed ({rejected_qty}). Please select fewer delinks.',
                    'reject_pool_capacity': reject_pool_capacity,
                    'rejected_qty': rejected_qty,
                }, status=400)

            if not show_reject or remaining_to_reject != 0:
                return Response({'success': False, 'error': 'Cannot confirm: reject allocation incomplete. Select all delink trays first.'}, status=400)

            with transaction.atomic():
                sub = IQF_Submitted.objects.filter(lot_id=lot_id).first()
                if not sub:
                    return Response({'success': False, 'error': 'No IQF submission found'}, status=404)

                # Update partial_reject_data with user's delink choices
                sub.partial_reject_data = {
                    'label': 'PARTIAL_REJECT',
                    'qty': rejected_qty,
                    'total_trays': len(reject_allocation),
                    'trays': reject_allocation,
                    'reasons': sub.rejection_details or [],
                }
                sub.save(update_fields=['partial_reject_data'])

                # Mark delinked trays in IQFTrayId
                if delinked_set:
                    IQFTrayId.objects.filter(lot_id=lot_id, tray_id__in=delinked_set).update(
                        delink_tray=True
                    )
                    print(f'[IQF DELINK CONFIRM] Marked {len(delinked_set)} trays as delinked in IQFTrayId')

                # Finalize TotalStockModel flags (same as iqf_verify_trays_confirm POST)
                ts.iqf_few_cases_acceptance = True
                ts.iqf_onhold_picking = False
                ts.send_brass_qc = True
                ts.send_brass_audit_to_iqf = False
                ts.iqf_accepted_qty_verified = False
                ts.next_process_module = 'Brass QC'
                ts.save(update_fields=[
                    'iqf_few_cases_acceptance', 'iqf_onhold_picking',
                    'send_brass_qc', 'send_brass_audit_to_iqf', 'iqf_accepted_qty_verified', 'next_process_module',
                ])

                print(f'[IQF DELINK CONFIRM] lot={lot_id} finalized: delinked={sorted(delinked_set)}, reject_trays={[r["tray_id"] for r in reject_allocation]}')

            return Response({
                'success': True,
                'confirmed': True,
                'message': 'IQF verification completed. Lot moved to Brass QC.',
                'lot_id': lot_id,
            })

        return Response({
            'success': True,
            'lot_id': lot_id,
            'rw_qty': rw_qty,
            'accepted_qty': accepted_qty,
            'rejected_qty': rejected_qty,
            'tray_capacity': tray_capacity,
            'original_trays': original_trays,
            'max_delink_count': max_delink_count,
            'reject_allocation': reject_allocation,
            'delinked_tray_ids': sorted(delinked_set),
            'reject_fully_allocated': remaining_to_reject == 0,
            'delink_complete': show_reject,
            'reject_pool_capacity': reject_pool_capacity,
        })

    except Exception as e:
        print(f'[IQF DELINK MODAL ERROR] {e}')
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)


# ── IQF Lot Rejection — One-click full lot rejection ──
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def iqf_lot_rejection(request):
    """Handle Lot Rejection checkbox toggle — backend single source of truth.

    POST JSON:
        { "lot_id": "LID...", "lot_rejection": true|false }

    When lot_rejection = true:
        - Treat 100% of IQF incoming qty as FULL REJECTION
        - Keep tray structure as-is (no recalculation / split)
        - Create IQF_Submitted with submission_type = LOT_REJECTION
        - Set TotalStockModel flags for rejection
        - Overrides any partial draft data

    When lot_rejection = false:
        - Clear IQF_Submitted for this lot (if LOT_REJECTION)
        - Clear IQF rejection reason store
        - Reset TotalStockModel flags to editable state
        - Restore normal audit flow
    """
    data = request.data
    lot_id = data.get('lot_id')
    lot_rejection = data.get('lot_rejection')
    remark = (data.get('remark') or '').strip()

    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    if lot_rejection is None:
        return Response({'success': False, 'error': 'Missing lot_rejection flag'}, status=400)

    # Remark is mandatory when activating lot rejection
    if bool(lot_rejection) and not remark:
        return Response({'success': False, 'error': 'Remark is mandatory for lot rejection', 'remark_required': True}, status=400)

    lot_rejection = bool(lot_rejection)

    try:
        ts = TotalStockModel.objects.get(lot_id=lot_id)
    except TotalStockModel.DoesNotExist:
        return Response({'success': False, 'error': f'Lot {lot_id} not found'}, status=404)

    if not ts.send_brass_audit_to_iqf:
        return Response({'success': False, 'error': f'Lot {lot_id} is not eligible for IQF'}, status=400)

    try:
        with transaction.atomic():
            if lot_rejection:
                # ── ACTIVATE LOT REJECTION ──

                # 1. Resolve iqf_incoming_qty (rw_qty) — same source as iqf_submit_audit
                audit_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                qc_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                rw_qty = 0
                if audit_store and getattr(audit_store, 'total_rejection_quantity', None) is not None:
                    rw_qty = audit_store.total_rejection_quantity
                elif qc_store and getattr(qc_store, 'total_rejection_quantity', None) is not None:
                    rw_qty = qc_store.total_rejection_quantity

                # Detect Brass QC full lot rejection
                is_full_lot_reject = False
                if audit_store and getattr(audit_store, 'batch_rejection', False):
                    is_full_lot_reject = True
                elif qc_store and getattr(qc_store, 'batch_rejection', False):
                    is_full_lot_reject = True
                if not is_full_lot_reject:
                    if getattr(ts, 'brass_qc_rejection', False) and int(getattr(ts, 'brass_qc_accepted_qty', 0) or 0) == 0:
                        is_full_lot_reject = True

                original_lot_qty = 0
                if getattr(ts, 'batch_id', None):
                    original_lot_qty = int(getattr(ts.batch_id, 'total_batch_quantity', 0) or 0)

                iqf_incoming_qty = rw_qty
                if is_full_lot_reject and iqf_incoming_qty <= 0:
                    iqf_incoming_qty = original_lot_qty

                if iqf_incoming_qty <= 0:
                    return Response({'success': False, 'error': 'No IQF incoming qty — rw_qty is 0'}, status=400)

                rejected_qty = iqf_incoming_qty
                accepted_qty = 0

                print(f'[IQF LOT REJECTION] ACTIVATE lot={lot_id}, iqf_incoming={iqf_incoming_qty}, rejected={rejected_qty}')

                # 2. Build tray snapshot — keep as-is, assign full quantities under rejection
                all_trays_qs = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False).order_by('id')
                original_tray_list = []
                reject_trays = []
                for t in all_trays_qs:
                    raw_qty = int(getattr(t, 'tray_quantity', 0) or 0)
                    remaining = int(getattr(t, 'remaining_qty', 0) or 0)
                    tray_qty = remaining if remaining > 0 else raw_qty
                    if tray_qty <= 0:
                        continue
                    tray_entry = {
                        'tray_id': getattr(t, 'tray_id', '') or '',
                        'qty': tray_qty,
                        'top_tray': bool(getattr(t, 'top_tray', False)),
                    }
                    original_tray_list.append(tray_entry)
                    reject_trays.append(tray_entry)

                original_data_snapshot = {
                    'qty': original_lot_qty,
                    'tray_total': sum(t['qty'] for t in original_tray_list),
                    'total_trays': len(original_tray_list),
                    'trays': original_tray_list,
                }
                iqf_data_snapshot = {
                    'qty': iqf_incoming_qty,
                    'tray_total': sum(t['qty'] for t in reject_trays),
                    'total_trays': len(reject_trays),
                    'trays': reject_trays,
                }

                full_reject_data = {
                    'label': 'LOT_REJECTION',
                    'qty': rejected_qty,
                    'total_trays': len(reject_trays),
                    'trays': reject_trays,
                }

                # 3. Create/update IQF_Submitted
                IQF_Submitted.objects.update_or_create(
                    lot_id=lot_id,
                    defaults={
                        'batch_id': ts.batch_id,
                        'original_lot_qty': original_lot_qty,
                        'iqf_incoming_qty': iqf_incoming_qty,
                        'total_lot_qty': iqf_incoming_qty,
                        'accepted_qty': accepted_qty,
                        'rejected_qty': rejected_qty,
                        'submission_type': IQF_Submitted.SUB_LOT_REJECT,
                        'original_data': original_data_snapshot,
                        'iqf_data': iqf_data_snapshot,
                        'full_accept_data': None,
                        'partial_accept_data': None,
                        'full_reject_data': full_reject_data,
                        'partial_reject_data': None,
                        'rejection_details': None,
                        'remarks': remark,
                        'is_completed': True,
                        'created_by': request.user,
                    }
                )

                # 4. Create rejection reason store (lot-level, no per-reason breakdown)
                store, _ = IQF_Rejection_ReasonStore.objects.update_or_create(
                    lot_id=lot_id,
                    defaults={
                        'user': request.user,
                        'total_rejection_quantity': rejected_qty,
                        'batch_rejection': True,
                        'lot_rejected_comment': 'Lot Rejection — full lot rejected via IQF',
                    }
                )

                # 5. Update TotalStockModel flags
                ts.iqf_rejection = True
                ts.iqf_acceptance = False
                ts.iqf_few_cases_acceptance = False
                ts.iqf_onhold_picking = False
                ts.iqf_accepted_qty = 0
                ts.iqf_after_rejection_qty = rejected_qty
                ts.last_process_module = 'IQF'
                ts.send_brass_audit_to_iqf = False
                ts.send_brass_qc = False
                ts.iqf_last_process_date_time = timezone.now()
                ts.save(update_fields=[
                    'iqf_rejection', 'iqf_acceptance', 'iqf_few_cases_acceptance',
                    'iqf_onhold_picking', 'iqf_accepted_qty', 'iqf_after_rejection_qty',
                    'last_process_module', 'send_brass_audit_to_iqf', 'send_brass_qc',
                    'iqf_last_process_date_time',
                ])

                # 6. Clear any existing drafts
                IQF_Draft_Store.objects.filter(lot_id=lot_id).delete()

                print(f'[IQF LOT REJECTION] SAVED lot={lot_id}, type=LOT_REJECTION, rejected={rejected_qty}')

                return Response({
                    'success': True,
                    'lot_rejection': True,
                    'lot_id': lot_id,
                    'submission_type': 'LOT_REJECTION',
                    'iqf_incoming_qty': iqf_incoming_qty,
                    'accepted_qty': accepted_qty,
                    'rejected_qty': rejected_qty,
                    'total_trays': len(reject_trays),
                    'trays': reject_trays,
                })

            else:
                # ── DEACTIVATE LOT REJECTION ──
                print(f'[IQF LOT REJECTION] DEACTIVATE lot={lot_id}')

                # Only clear if the existing submission is LOT_REJECTION
                existing_sub = IQF_Submitted.objects.filter(lot_id=lot_id).first()
                if existing_sub and existing_sub.submission_type == IQF_Submitted.SUB_LOT_REJECT:
                    existing_sub.delete()

                # Clear lot-level rejection reason store
                IQF_Rejection_ReasonStore.objects.filter(lot_id=lot_id, batch_rejection=True).delete()

                # Reset TotalStockModel to editable state
                ts.iqf_rejection = False
                ts.iqf_acceptance = False
                ts.iqf_few_cases_acceptance = False
                ts.iqf_onhold_picking = False
                ts.iqf_accepted_qty = 0
                ts.iqf_after_rejection_qty = 0
                ts.send_brass_audit_to_iqf = True  # Re-show in IQF pick table
                ts.send_brass_qc = False
                ts.save(update_fields=[
                    'iqf_rejection', 'iqf_acceptance', 'iqf_few_cases_acceptance',
                    'iqf_onhold_picking', 'iqf_accepted_qty', 'iqf_after_rejection_qty',
                    'send_brass_audit_to_iqf', 'send_brass_qc',
                ])

                print(f'[IQF LOT REJECTION] CLEARED lot={lot_id}, restored editable state')

                return Response({
                    'success': True,
                    'lot_rejection': False,
                    'lot_id': lot_id,
                    'message': 'Lot rejection cleared. Editable state restored.',
                })

    except Exception as e:
        print(f'[IQF LOT REJECTION ERROR] {e}')
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)


# ═══════════════════════════════════════════════════════════════════════════════
# ── CONSOLIDATED IQF LOT DETAILS API — SINGLE SOURCE OF TRUTH ──
# All IQF tables (Accept, Reject, Completed, View Icon) MUST use this endpoint.
# SOURCE: IQF_Submitted table ONLY. No duplicate storage, no secondary queries.
# ═══════════════════════════════════════════════════════════════════════════════
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def iqf_lot_details(request):
    """SINGLE consolidated API for ALL IQF lot data.

    SOURCE OF TRUTH: IQF_Submitted table ONLY.
    Returns accepted, rejected, delinked data + summary with status labels.

    Query params: ?lot_id=X&table=accept|reject|complete (optional filter)
    - table=accept  → only accepted trays returned
    - table=reject  → only rejected trays returned
    - table=complete → all trays, but delinked qty hidden (set to '')
    - omitted → full response (PickTable view icon)
    Response: { lot_id, accepted, rejected, delinked, rejection_reasons, summary }
    """
    lot_id = request.GET.get('lot_id')
    table_filter = request.GET.get('table', '').strip().lower()
    if not lot_id:
        return Response({'success': False, 'error': 'lot_id required'}, status=400)

    print(f"[IQF LOT DETAILS] Input lot_id: {lot_id}")

    try:
        sub = IQF_Submitted.objects.select_related(
            'batch_id', 'batch_id__model_stock_no', 'created_by'
        ).filter(lot_id=lot_id, is_completed=True).last()

        if not sub:
            print(f"[IQF LOT DETAILS] No IQF_Submitted record for lot {lot_id} — fallback to incoming trays")

            # ── FALLBACK: Lot not yet processed in IQF — show incoming trays ──
            # Same aggregation logic as iqf_tray_details fallback
            tray_qty_map = {}
            brass_reject_rows = Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id)
            if not brass_reject_rows.exists():
                brass_reject_rows = Brass_Audit_Rejected_TrayScan.objects.filter(lot_id=lot_id)
            for row in brass_reject_rows:
                tray_id = getattr(row, 'rejected_tray_id', None) or getattr(row, 'tray_id', None) or ''
                if not tray_id:
                    continue
                try:
                    qty = int(row.rejected_tray_quantity or 0)
                except (ValueError, TypeError):
                    qty = 0
                tray_qty_map[tray_id] = tray_qty_map.get(tray_id, 0) + qty

            # Final fallback: IQFTrayId records
            if not tray_qty_map:
                for row in IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=False):
                    qty = row.tray_quantity or 0
                    if qty > 0:
                        tray_qty_map[row.tray_id] = tray_qty_map.get(row.tray_id, 0) + qty

            incoming_trays = []
            incoming_total = 0
            for tid in sorted(tray_qty_map.keys()):
                qty = tray_qty_map[tid]
                incoming_total += qty
                incoming_trays.append({
                    'tray_id': tid,
                    'qty': qty,
                    'top_tray': False,
                    'status': 'INCOMING',
                })

            print(f"[IQF LOT DETAILS] Fallback: {len(incoming_trays)} incoming trays, total={incoming_total}")
            return Response({
                'success': True,
                'lot_id': lot_id,
                'accepted': incoming_trays,
                'rejected': [],
                'delinked': [],
                'rejection_reasons': [],
                'summary': {
                    'accepted_qty': 0,
                    'rejected_qty': 0,
                    'delink_qty': 0,
                    'iqf_incoming_qty': incoming_total,
                    'original_lot_qty': 0,
                    'submission_type': '',
                    'status_label': 'NOT_PROCESSED',
                    'remarks': '',
                    'created_by': '',
                    'created_at': '',
                },
                'source': 'dynamic_fallback',
            })

        print(f"[IQF LOT DETAILS] Found: type={sub.submission_type}, "
              f"accepted={sub.accepted_qty}, rejected={sub.rejected_qty}")

        # ── Extract ACCEPTED trays ──
        accepted = []
        accept_data = sub.partial_accept_data or sub.full_accept_data
        if accept_data and accept_data.get('trays'):
            for t in accept_data['trays']:
                qty = int(t.get('qty', 0))
                if qty <= 0:
                    continue
                accepted.append({
                    'tray_id': t.get('tray_id', ''),
                    'qty': qty,
                    'top_tray': bool(t.get('top_tray', t.get('is_top_tray', False))),
                    'status': 'ACCEPT',
                })

        # ── Extract REJECTED trays ──
        rejected = []
        reject_data = sub.partial_reject_data or sub.full_reject_data
        if reject_data and reject_data.get('trays'):
            for t in reject_data['trays']:
                qty = int(t.get('qty', 0))
                if qty <= 0:
                    continue
                rejected.append({
                    'tray_id': t.get('tray_id', ''),
                    'qty': qty,
                    'top_tray': bool(t.get('top_tray', False)),
                    'status': 'REJECT',
                })

        # ── Compute DELINKED trays from original snapshot ──
        delinked = []
        accept_tray_ids = {t['tray_id'] for t in accepted}
        reject_tray_ids = {t['tray_id'] for t in rejected}

        original_data = sub.original_data or {}
        original_trays = original_data.get('trays', [])
        if original_trays:
            for t in original_trays:
                tid = t.get('tray_id', '')
                if tid and tid not in accept_tray_ids and tid not in reject_tray_ids:
                    delinked.append({
                        'tray_id': tid,
                        'qty': int(t.get('qty', 0)),
                        'top_tray': bool(t.get('top_tray', False)),
                        'status': 'DELINK',
                    })

        # Fallback: check IQFTrayId for explicitly delinked trays
        if not delinked:
            delinked_qs = IQFTrayId.objects.filter(lot_id=lot_id, delink_tray=True)
            for t in delinked_qs:
                if t.tray_id not in accept_tray_ids and t.tray_id not in reject_tray_ids:
                    delinked.append({
                        'tray_id': t.tray_id,
                        'qty': int(t.tray_quantity or 0),
                        'top_tray': bool(t.top_tray),
                        'status': 'DELINK',
                    })

        # ── Determine status label ──
        if sub.submission_type == 'FULL_ACCEPT':
            status_label = 'ACCEPT'
        elif sub.submission_type in ('FULL_REJECT', 'LOT_REJECTION'):
            status_label = 'REJECT'
        elif sub.submission_type == 'PARTIAL':
            status_label = 'PARTIAL'
        else:
            status_label = sub.submission_type

        # ── Rejection reasons from stored details ──
        rejection_reasons = []
        if sub.rejection_details:
            for rd in sub.rejection_details:
                rejection_reasons.append({
                    'reason': rd.get('reason_text', ''),
                    'reason_id': rd.get('reason_id', ''),
                    'qty': rd.get('iqf_qty', 0),
                })

        delink_qty = sum(t['qty'] for t in delinked)
        delink_tray_count = len(delinked)

        # ── Table-specific filtering ──
        # Accept table: show ONLY accepted trays
        if table_filter == 'accept':
            rejected = []
            delinked = []
        # Reject table: show ONLY rejected trays
        elif table_filter == 'reject':
            accepted = []
            delinked = []
        # Complete table: show all, but hide delinked qty
        elif table_filter == 'complete':
            for t in delinked:
                t['qty'] = ''

        response = {
            'success': True,
            'lot_id': lot_id,
            'accepted': accepted,
            'rejected': rejected,
            'delinked': delinked,
            'rejection_reasons': rejection_reasons,
            'summary': {
                'accepted_qty': sub.accepted_qty,
                'rejected_qty': sub.rejected_qty,
                'delink_qty': delink_qty,
                'delink_tray_count': delink_tray_count,
                'iqf_incoming_qty': sub.iqf_incoming_qty,
                'original_lot_qty': sub.original_lot_qty,
                'submission_type': sub.submission_type,
                'status_label': status_label,
                'remarks': sub.remarks or '',
                'created_by': sub.created_by.username if sub.created_by else '',
                'created_at': sub.created_at.isoformat() if sub.created_at else '',
            },
            'source': 'IQF_Submitted',
        }

        print(f"[IQF LOT DETAILS] Response: accepted={len(accepted)}, "
              f"rejected={len(rejected)}, delinked={len(delinked)}, status={status_label}")
        return Response(response)

    except Exception as e:
        print(f"[IQF LOT DETAILS ERROR] {e}")
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)

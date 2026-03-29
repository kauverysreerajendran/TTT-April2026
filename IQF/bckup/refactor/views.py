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
# Create your views here.

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
                    if use_audit:
                        reason_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                    else:
                        reason_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                except Exception:
                    reason_store = None

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
        print("Processed lot_ids:", [data['stock_lot_id'] for data in master_data])

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
def iqf_get_audit_modal_data(request):
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

        # 2. Build per-reason data from Brass QC rejected tray scans (single source)
        # Prefer Brass QC rejected tray scan records; if none found, fall back to Brass Audit rejected tray scans.
        response_data = []
        try:
            brass_rows_qs = Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id).select_related('rejection_reason')
        except Exception:
            brass_rows_qs = Brass_QC_Rejected_TrayScan.objects.none()

        # fallback to audit rejected tray scans if brass qc rows not present
        if not brass_rows_qs.exists():
            try:
                brass_rows_qs = Brass_Audit_Rejected_TrayScan.objects.filter(lot_id=lot_id).select_related('rejection_reason')
            except Exception:
                brass_rows_qs = Brass_QC_Rejected_TrayScan.objects.none()

        # Aggregate quantities by reason text (preserve insertion order)
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
                reason_map[reason_text] = {'qty': qty, 'reason_id': getattr(row.rejection_reason, 'id', None)}

        # Build response using master IQF reasons but fill quantities from brass reason_map
        # This ensures all master reasons (including 'OTHERS') appear even if qty is 0
        reasons = IQF_Rejection_Table.objects.all().order_by('rejection_reason_id')
        for index, reason in enumerate(reasons, start=1):
            reason_text = (reason.rejection_reason or '').strip()
            # Prefer match by exact text; fall back to id-based lookup if available in map
            info = reason_map.get(reason_text)
            brass_qty = 0
            if info:
                brass_qty = info.get('qty', 0) or 0
            else:
                # attempt id-based match (in case texts differ)
                for k, v in reason_map.items():
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
                "is_editable": True if (brass_qty and int(brass_qty) > 0) else False
            })

        print(f"[AUDIT API] Output count: {len(response_data)}")

        return Response({
            "success": True,
            "rw_qty": rw_qty,
            "rejection_data": response_data
        })

    except Exception as e:
        print("[AUDIT API ERROR]", str(e))
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def iqf_submit_audit(request):
    """Accepts JSON payload to save draft or proceed with IQF rejection quantities.

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
        # compute RW qty from brass audit or brass qc stores (source of truth)
        audit_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        qc_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        rw_qty = 0
        if audit_store and getattr(audit_store, 'total_rejection_quantity', None) is not None:
            rw_qty = audit_store.total_rejection_quantity
        elif qc_store and getattr(qc_store, 'total_rejection_quantity', None) is not None:
            rw_qty = qc_store.total_rejection_quantity

        # Parse items into ints and prepare for validation
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
                qty = 0
            total_iqf += qty
            parsed_items.append({'reason_id': rid, 'iqf_qty': qty})

        # Helper: fetch brass QC qty for a given lot_id and IQF_Rejection_Table id
        def fetch_brass_qty_for_reason(lot_id, reason_obj_or_id):
            # Accept either reason id or IQF_Rejection_Table instance
            try:
                if isinstance(reason_obj_or_id, int):
                    reason_obj = IQF_Rejection_Table.objects.filter(id=reason_obj_or_id).first()
                else:
                    reason_obj = reason_obj_or_id
                if not reason_obj:
                    return 0

                # Use per-reason rejected tray scans as the source of truth for splits
                try:
                    qty = Brass_QC_Rejected_TrayScan.objects.filter(
                        lot_id=lot_id,
                        rejection_reason=reason_obj
                    ).aggregate(total=Sum('rejected_tray_quantity'))['total'] or 0
                    return qty
                except Exception:
                    pass

                # Fallback: match by reason text (case-insensitive)
                try:
                    qty = Brass_QC_Rejected_TrayScan.objects.filter(
                        lot_id=lot_id,
                        rejection_reason__rejection_reason__iexact=reason_obj.rejection_reason
                    ).aggregate(total=Sum('rejected_tray_quantity'))['total'] or 0
                    return qty
                except Exception:
                    pass

                # Last resort: partial text match
                qty = Brass_QC_Rejected_TrayScan.objects.filter(
                    lot_id=lot_id,
                    rejection_reason__rejection_reason__icontains=reason_obj.rejection_reason
                ).aggregate(total=Sum('rejected_tray_quantity'))['total'] or 0
                return qty
            except Exception:
                return 0

        # Validate per-item: IQF_entered_qty <= Brass_QC_qty (DB only)
        with transaction.atomic():
            for itm in parsed_items:
                rid = itm.get('reason_id')
                qty = itm.get('iqf_qty') or 0
                if rid is None:
                    # If reason id missing, skip per-reason validation (still included in total check)
                    continue
                reason_obj = IQF_Rejection_Table.objects.filter(id=rid).first()
                brass_qty = fetch_brass_qty_for_reason(lot_id, reason_obj)
                # Reject if there is no Brass QC qty but frontend sent a positive IQF value
                if (not brass_qty or int(brass_qty) == 0) and qty > 0:
                    reason_text = reason_obj.rejection_reason if reason_obj else f'id {rid}'
                    return Response({'success': False, 'error': f'Cannot accept IQF qty for {reason_text}: no Brass QC quantity available'}, status=400)
                if qty > brass_qty:
                    reason_text = reason_obj.rejection_reason if reason_obj else f'id {rid}'
                    return Response({'success': False, 'error': f'IQF qty cannot exceed Brass QC qty for {reason_text}'}, status=400)

            # Validate total against RW qty as previously
            if total_iqf > rw_qty:
                return Response({'success': False, 'error': 'Submitted IQF total exceeds RW quantity', 'rw_qty': rw_qty, 'submitted_total': total_iqf}, status=400)

            # find batch id for draft storage
            batch_id_val = ''
            ts = TotalStockModel.objects.filter(lot_id=lot_id).first()
            if ts and getattr(ts, 'batch_id', None):
                batch_id_val = ts.batch_id.batch_id

            if action == 'draft':
                # save/update IQF_Draft_Store
                draft_obj, created = IQF_Draft_Store.objects.update_or_create(
                    lot_id=lot_id,
                    draft_type='batch_rejection',
                    defaults={
                        'batch_id': batch_id_val,
                        'user': request.user,
                        'draft_data': {'is_draft': True, 'items': parsed_items, 'total_iqf': total_iqf},
                    }
                )
                return Response({'success': True, 'draft': True})

            # action == 'proceed'
            # Create IQF_Rejection_ReasonStore record to record final IQF rejection distribution
            store = IQF_Rejection_ReasonStore.objects.create(
                lot_id=lot_id,
                user=request.user,
                total_rejection_quantity=total_iqf,
                batch_rejection=False,
            )
            # Attach reason M2M using provided reason_ids (ignore missing ids)
            reason_ids = [p['reason_id'] for p in parsed_items if p['reason_id']]
            if reason_ids:
                reasons_qs = IQF_Rejection_Table.objects.filter(id__in=reason_ids)
                store.rejection_reason.set(reasons_qs)

            # Optionally save detailed items inside a draft record for auditing
            IQF_Draft_Store.objects.update_or_create(
                lot_id=lot_id,
                draft_type='batch_rejection',
                defaults={
                    'batch_id': batch_id_val,
                    'user': request.user,
                    'draft_data': {'is_draft': False, 'items': parsed_items, 'total_iqf': total_iqf},
                }
            )

            return Response({'success': True, 'proceeded': True})

    except Exception as e:
        print('[IQF SUBMIT ERROR]', str(e))
        traceback.print_exc()
        return Response({'success': False, 'error': 'Server error'}, status=500)


# Minimal redirect view for legacy nav link: resolves NoReverseMatch
def iqf_completed_table_redirect(request):
    # Redirect to the main pick table; template for completed table may be added later
    return redirect('iqf_picktable')


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
    

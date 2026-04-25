from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.db.models import OuterRef, Subquery, Exists, F
from django.core.paginator import Paginator
from django.templatetags.static import static
import math
from modelmasterapp.models import *
from DayPlanning.models import *
from InputScreening.models import *
from Brass_QC.models import *
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
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from IQF.models import *
from BrassAudit.models import *
from Nickel_Audit.models import *
from Nickel_Inspection.models import *
from Jig_Unloading.models import *
from Jig_Unloading.tray_utils import get_upstream_tray_distribution, get_model_master_tray_info
import logging
logger = logging.getLogger(__name__)
from Inprocess_Inspection.models import InprocessInspectionTrayCapacity


def _get_input_source(jig_unload_obj):
    """Return location names with fallback chain: M2M → TotalStockModel → TrayId → ModelMasterCreation."""
    names = [loc.location_name for loc in jig_unload_obj.location.all()]
    if not names:
        for raw_cid in (jig_unload_obj.combine_lot_ids or []):
            cid = raw_cid.rsplit('-', 1)[-1] if raw_cid and '-' in raw_cid else raw_cid
            if not cid:
                continue
            tsm = TotalStockModel.objects.filter(lot_id=cid).prefetch_related('location').select_related('batch_id__location').first()
            if tsm and tsm.location.exists():
                names = [loc.location_name for loc in tsm.location.all()]
                break
            if tsm and tsm.batch_id and tsm.batch_id.location:
                names = [tsm.batch_id.location.location_name]
                break
            tray = TrayId.objects.filter(lot_id=cid).select_related('batch_id__location').first()
            if tray and tray.batch_id and tray.batch_id.location:
                names = [tray.batch_id.location.location_name]
                break
    return ', '.join(names)


class NA_PickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Nickel_Audit/NickelAudit_PickTable.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False

        nq_rejection_reasons = Nickel_Audit_Rejection_Table.objects.all()

        # Get all plating_color IDs where jig_unload_zone_1 is True
        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_1=True
        ).values_list('id', flat=True)

        # ✅ CHANGED: Query JigUnloadAfterTable instead of TotalStockModel with zone filtering
        queryset = JigUnloadAfterTable.objects.select_related(
            'version',
            'plating_color',
            'polish_finish'
        ).prefetch_related(
            'location'  # ManyToManyField requires prefetch_related
        ).filter(
            total_case_qty__gt=0,  # Only show records with quantity > 0
            plating_color_id__in=allowed_color_ids  # Only show records for zone 1
        )

        # ✅ Add draft status subqueries for Nickel QC
        has_draft_subquery = Exists(
            Nickel_Audit_Draft_Store.objects.filter(
                lot_id=OuterRef('lot_id')  # Using the auto-generated lot_id
            )
        )
        
        draft_type_subquery = Nickel_Audit_Draft_Store.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('draft_type')[:1]

        brass_rejection_qty_subquery = Nickel_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        # ✅ Annotate with additional fields
        queryset = queryset.annotate(
            has_draft=has_draft_subquery,
            draft_type=draft_type_subquery,
            brass_rejection_total_qty=brass_rejection_qty_subquery,
        )

        # ✅ UPDATED: Filter logic using JigUnloadAfterTable fields
        queryset = queryset.filter(
            (
                (
                    Q(na_qc_accptance__isnull=True) | Q(na_qc_accptance=False)
                ) &
                (
                    Q(na_qc_rejection__isnull=True) | Q(na_qc_rejection=False)
                ) &
                ~Q(na_qc_few_cases_accptance=True, na_onhold_picking=False)
                &
                (
                    Q(nq_qc_accptance=True) | 
                    Q(nq_qc_few_cases_accptance=True, nq_onhold_picking=False)
                )
            )
            |
            Q(na_qc_rejection=True, na_onhold_picking=True)
        ).distinct().order_by('-nq_last_process_date_time', '-lot_id')

        print("All lot_ids in queryset:", list(queryset.values_list('lot_id', flat=True)))

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        # ✅ UPDATED: Get values from JigUnloadAfterTable
        master_data = []
        for jig_unload_obj in page_obj.object_list:
            
            data = {
                'batch_id': jig_unload_obj.unload_lot_id,  # Using unload_lot_id as batch identifier
                'lot_id': jig_unload_obj.lot_id,  # Auto-generated lot_id
                'date_time': jig_unload_obj.created_at,
                'model_stock_no__model_no': 'Combined Model',  # Since this combines multiple lots
                'plating_color': jig_unload_obj.plating_color.plating_color if jig_unload_obj.plating_color else '',
                'polish_finish': jig_unload_obj.polish_finish.polish_finish if jig_unload_obj.polish_finish else '',
                'version__version_name': jig_unload_obj.version.version_name if jig_unload_obj.version else '',
                'vendor_internal': '',  # Not available in JigUnloadAfterTable
                'location__location_name': _get_input_source(jig_unload_obj),
                'tray_type': get_model_master_tray_info(jig_unload_obj.plating_stk_no, jig_unload_obj.tray_type or '')[0],
                'tray_capacity': get_model_master_tray_info(jig_unload_obj.plating_stk_no, jig_unload_obj.tray_type or '', jig_unload_obj.tray_capacity or 0)[1],
                'wiping_required': False,  # Default value, can be enhanced later
                'brass_audit_rejection': False,  # Not applicable for nickel IP
                
                # ✅ Stock-related fields from JigUnloadAfterTable
                'stock_lot_id': jig_unload_obj.lot_id,
                'total_IP_accpeted_quantity': jig_unload_obj.total_case_qty,
                'na_ac_accepted_qty_verified': False,  # Not applicable
                'nq_qc_accepted_qty': jig_unload_obj.nq_qc_accepted_qty,  # Not applicable
                'na_missing_qty': jig_unload_obj.na_missing_qty,  # Not applicable
                'na_physical_qty': jig_unload_obj.na_physical_qty,
                'na_physical_qty_edited': False,
                'rejected_audit_nickle_ip_stock': jig_unload_obj.unload_accepted,
                'rejected_ip_stock': jig_unload_obj.rejected_audit_nickle_ip_stock,
                'accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,
                'na_pick_remarks': jig_unload_obj.na_pick_remarks,  # Not applicable for nickel
                'nq_qc_accptance': False,  # Not applicable
                'na_accepted_tray_scan_status': False,  # Not applicable
                'na_qc_rejection': jig_unload_obj.na_qc_rejection,
                'na_qc_few_cases_accptance': jig_unload_obj.na_qc_few_cases_accptance,
                'na_onhold_picking': jig_unload_obj.na_onhold_picking,
                'nq_draft': False,  # Not applicable
                'send_to_nickel_brass': jig_unload_obj.send_to_nickel_brass,
                'nq_last_process_date_time': jig_unload_obj.nq_last_process_date_time,
                'iqf_last_process_date_time': None,
                'na_hold_lot': jig_unload_obj.na_hold_lot,
                'na_holding_reason': jig_unload_obj.na_holding_reason,  # Not applicable
                'na_release_lot': jig_unload_obj.na_release_lot,
                'na_release_reason': jig_unload_obj.na_release_reason,
                'has_draft': jig_unload_obj.has_draft,
                'draft_type': jig_unload_obj.draft_type,
                'brass_rejection_total_qty': jig_unload_obj.brass_rejection_total_qty,
                'nq_qc_accptance': jig_unload_obj.nq_qc_accptance,
                # Additional fields from JigUnloadAfterTable
                'plating_stk_no': jig_unload_obj.plating_stk_no or '',
                'polishing_stk_no': jig_unload_obj.polish_stk_no or '',
                'category': jig_unload_obj.category or '',
                'last_process_module': jig_unload_obj.last_process_module or 'Jig Unload',
                'combine_lot_ids': jig_unload_obj.combine_lot_ids,  # Show which lots were combined
                'unload_lot_id': jig_unload_obj.unload_lot_id,  # Additional identifier
                # Nickel-specific fields
                'na_ac_accepted_qty_verified': jig_unload_obj.na_ac_accepted_qty_verified,
                'na_qc_acceptance': jig_unload_obj.na_qc_accptance,  # template uses na_qc_acceptance key
                'audit_check': jig_unload_obj.audit_check,
            }

            # *** ENHANCED MODEL IMAGES LOGIC (Same as other views) ***
            images = []
            model_master = None
            model_no = None

            # Priority 1: Get images from ModelMaster based on plating_stk_no
            if jig_unload_obj.plating_stk_no:
                plating_stk_no = str(jig_unload_obj.plating_stk_no)
                if len(plating_stk_no) >= 4:
                    model_no_prefix = plating_stk_no[:4]
                    print(f"🎯 NA Pick View - Extracted model_no: {model_no_prefix} from plating_stk_no: {plating_stk_no}")
                    
                    try:
                        # Find ModelMaster where model_no matches the prefix for images
                        model_master = ModelMaster.objects.filter(
                            model_no__startswith=model_no_prefix
                        ).prefetch_related('images').first()
                        
                        if model_master:
                            print(f"✅ NA Pick View - Found ModelMaster for images: {model_master.model_no}")
                            # Get images from ModelMaster
                            for img in model_master.images.all():
                                if img.master_image:
                                    images.append(img.master_image.url)
                                    print(f"📸 NA Pick View - Added image from ModelMaster: {img.master_image.url}")
                        else:
                            print(f"⚠️ NA Pick View - No ModelMaster found for model_no: {model_no_prefix}")
                    except Exception as e:
                        print(f"❌ NA Pick View - Error fetching ModelMaster: {e}")

            # Priority 2: Fallback to existing combine_lot_ids logic if no ModelMaster images
            if not images and data['combine_lot_ids']:
                print("🔄 NA Pick View - No ModelMaster images, trying combine_lot_ids fallback")
                first_lot_id = data['combine_lot_ids'][0] if data['combine_lot_ids'] else None
                if first_lot_id:
                    total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
                    if total_stock and total_stock.batch_id:
                        batch_obj = total_stock.batch_id
                        if batch_obj.model_stock_no:
                            for img in batch_obj.model_stock_no.images.all():
                                if img.master_image:
                                    images.append(img.master_image.url)
                                    print(f"📸 NA Pick View - Added image from TotalStockModel: {img.master_image.url}")

            # Priority 3: Use placeholder if no images found
            if not images:
                print("📷 NA Pick View - No images found, using placeholder")
                images = [static('assets/images/imagePlaceholder.jpg')]
            
            data['model_images'] = images
            print(f"📸 NA Pick View - Final images for lot {jig_unload_obj.lot_id}: {len(images)} images")

            master_data.append(data)

        # ✅ Process the data (similar logic but adapted for JigUnloadAfterTable)
        for data in master_data:   
            total_IP_accpeted_quantity = data.get('total_IP_accpeted_quantity', 0)
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            
            lot_id = data.get('stock_lot_id')
            
            # Calculate display_accepted_qty
            total_rejection_qty = 0
            rejection_store = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            if rejection_store and rejection_store.total_rejection_quantity:
                total_rejection_qty = rejection_store.total_rejection_quantity

            # Use total_case_qty from JigUnloadAfterTable instead of TotalStockModel
            jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            
            if jig_unload_obj and total_rejection_qty > 0:
                data['display_accepted_qty'] = max(jig_unload_obj.nq_qc_accepted_qty - total_rejection_qty, 0)
            else:
                data['display_accepted_qty'] = jig_unload_obj.nq_qc_accepted_qty if jig_unload_obj else 0

            # Delink logic adapted for nickel IP
            na_physical_qty = data.get('na_physical_qty') or 0
            brass_rejection_total_qty = data.get('brass_rejection_total_qty') or 0
            is_delink_only = (na_physical_qty > 0 and 
                              brass_rejection_total_qty >= na_physical_qty and 
                              data.get('na_onhold_picking', False))
            data['is_delink_only'] = is_delink_only

            # Calculate number of trays
            display_qty = data.get('display_accepted_qty', 0)
            if tray_capacity > 0 and display_qty > 0:
                data['no_of_trays'] = math.ceil(display_qty / tray_capacity)
            else:
                data['no_of_trays'] = 0
        
            # Add available_qty
            if data.get('na_physical_qty') and data.get('na_physical_qty') > 0:
                data['available_qty'] = data.get('na_physical_qty')
            else:
                data['available_qty'] = data.get('total_IP_accpeted_quantity', 0)
                
            # --- AQL Sampling Plan Calculation ---
            display_accepted_qty = data.get('display_accepted_qty', 0)
            aql_plan = AQLSamplingPlan.objects.filter(
                lot_qty_from__lte=display_accepted_qty,
                lot_qty_to__gte=display_accepted_qty
            ).first()
            if aql_plan:
                data['aql_limit'] = float(aql_plan.aql_limit)
                data['sample_qty'] = aql_plan.sample_qty
            else:
                data['aql_limit'] = None
                data['sample_qty'] = None

        print(f"[DEBUG] Master data loaded with {len(master_data)} entries from JigUnloadAfterTable.")
        print("All lot_ids in processed data:", [data['stock_lot_id'] for data in master_data])
        
        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
            'nq_rejection_reasons': nq_rejection_reasons,
            'pick_table_count': len(master_data),
        }
        return Response(context, template_name=self.template_name)


# ═══════════════════════════════════════════════════════════════
#  NA ACTION API  (mirrors nq_toggle_verified / nq_action / nq_delink_selected_trays)
# ═══════════════════════════════════════════════════════════════

def _na_tray_capacity(tray_type_name):
    """Return accept-tray capacity for a given tray_type string."""
    if not tray_type_name:
        return 0
    name = tray_type_name.strip().lower()
    if name.startswith('nr') or name.startswith('nb') or name in ['normal', 'normal tray']:
        return 20
    if name.startswith('jb') or 'jumbo' in name:
        return 12
    custom = InprocessInspectionTrayCapacity.objects.filter(
        tray_type__tray_type__iexact=tray_type_name, is_active=True
    ).first()
    if custom:
        return custom.custom_capacity
    tt = TrayType.objects.filter(tray_type__iexact=tray_type_name).first()
    return tt.tray_capacity if tt else 0


def _na_generate_lot_id():
    """Generate a unique LID-format lot ID for NA partial submission records."""
    from datetime import datetime
    import time
    for _ in range(10):
        now = datetime.now()
        lid = f"LID{now.strftime('%Y%m%d%H%M%S')}{str(now.microsecond).zfill(6)}"
        if not NickelAudit_PartialRejectLot.objects.filter(new_lot_id=lid).exists():
            return lid
        time.sleep(0.001)
    now = datetime.now()
    return f"LID{now.strftime('%Y%m%d%H%M%S')}{str(now.microsecond).zfill(6)}"


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def na_toggle_verified(request):
    """Toggle na_ac_accepted_qty_verified flag on JigUnloadAfterTable."""
    from django.db import transaction
    lot_id = request.data.get('lot_id', '').strip()
    if not lot_id:
        return Response({'success': False, 'error': 'lot_id required'}, status=400)
    try:
        with transaction.atomic():
            obj = JigUnloadAfterTable.objects.select_for_update().filter(lot_id=lot_id).first()
            if not obj:
                return Response({'success': False, 'error': 'Lot not found'}, status=404)
            obj.na_ac_accepted_qty_verified = True
            obj.save(update_fields=['na_ac_accepted_qty_verified'])
        logger.info("[na_toggle_verified] lot=%s user=%s", lot_id, request.user)
        return Response({'success': True, 'last_process_module': obj.last_process_module or ''})
    except Exception as e:
        logger.exception("[na_toggle_verified] error lot=%s", lot_id)
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def na_action(request):
    """Unified NA action handler: GET_REASONS, GET_TRAYS, ALLOCATE, SUBMIT_REJECT, SUBMIT_ACCEPT, FULL_ACCEPT."""
    from django.db import transaction
    action = request.data.get('action', '')
    lot_id = request.data.get('lot_id', '').strip()
    if not action:
        return Response({'success': False, 'error': 'action required'}, status=400)
    if action == 'GET_REASONS':
        reasons = list(
            Nickel_Audit_Rejection_Table.objects.all().order_by('id').values('id', 'rejection_reason')
        )
        return Response({'success': True, 'reasons': reasons})
    if action == 'CHECK_TRAY':
        from modelmasterapp.models import TrayId as TrayMaster
        tray_id_val = request.data.get('tray_id', '').strip().upper()
        if not tray_id_val:
            return Response({'success': False, 'valid': False, 'message': 'Tray ID required'})
        exists = TrayMaster.objects.filter(tray_id__iexact=tray_id_val).exists()
        return Response({'success': True, 'valid': exists, 'message': 'Valid tray' if exists else 'Tray not found in master'})
    if not lot_id:
        return Response({'success': False, 'error': 'lot_id required'}, status=400)
    juat = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
    if not juat:
        return Response({'success': False, 'error': 'Lot not found'}, status=404)
    if action == 'GET_TRAYS':
        trays_qs = Nickel_AuditTrayId.objects.filter(
            lot_id=lot_id, rejected_tray=False
        ).order_by('-top_tray', 'id')
        if trays_qs.exists():
            trays = [
                {
                    'tray_id': t.tray_id,
                    'qty': t.tray_quantity or 0,
                    'is_top': bool(t.top_tray),
                    'is_delinked': bool(t.delink_tray),
                }
                for t in trays_qs
            ]
        else:
            upstream, _ = get_upstream_tray_distribution(lot_id)
            if upstream:
                trays = [
                    {
                        'tray_id': t['tray_id'],
                        'qty': t['tray_quantity'] or 0,
                        'is_top': bool(t.get('top_tray', False)),
                        'is_delinked': bool(t.get('delink_tray', False)),
                    }
                    for t in upstream
                    if not t.get('rejected_tray', False)
                ]
            else:
                trays = []
        tray_type = (juat.tray_type or '').strip()
        tray_cap = _na_tray_capacity(tray_type) or juat.tray_capacity or 20
        return Response({
            'success': True,
            'trays': trays,
            'total_qty': juat.nq_qc_accepted_qty or juat.total_case_qty or 0,
            'tray_capacity': tray_cap,
            'tray_type': tray_type,
            'plating_stk_no': juat.plating_stk_no or '',
        })
    if action == 'ALLOCATE':
        try:
            rejected_qty = int(request.data.get('rejected_qty', 0))
        except (TypeError, ValueError):
            return Response({'success': False, 'error': 'Invalid rejected_qty'}, status=400)
        total_qty = juat.nq_qc_accepted_qty or juat.total_case_qty or 0
        if rejected_qty <= 0 or rejected_qty > total_qty:
            return Response({'success': False, 'error': 'rejected_qty out of range'}, status=400)
        accepted_qty = total_qty - rejected_qty
        tray_type = (juat.tray_type or '').strip().lower()
        orig_cap = _na_tray_capacity(juat.tray_type or '') or juat.tray_capacity or 20
        if tray_type.startswith('jb') or 'jumbo' in tray_type:
            rej_cap = 12
            rej_prefix = 'JB'
        else:
            rej_cap = 16
            rej_prefix = 'NB'
        trays_qs = Nickel_AuditTrayId.objects.filter(
            lot_id=lot_id, rejected_tray=False, delink_tray=False
        ).order_by('-top_tray', 'id')
        if trays_qs.exists():
            orig_trays = [
                {'tray_id': t.tray_id, 'qty': t.tray_quantity or 0, 'is_top': bool(t.top_tray)}
                for t in trays_qs
            ]
        else:
            upstream, _ = get_upstream_tray_distribution(lot_id)
            orig_trays = [
                {'tray_id': t['tray_id'], 'qty': t['tray_quantity'] or 0, 'is_top': bool(t.get('top_tray', False))}
                for t in (upstream or [])
                if not t.get('delink_tray') and not t.get('rejected_tray')
            ]
        reuse_trays = []
        auto_delink_tray_ids = []
        remaining_rej = rejected_qty
        for t in orig_trays:
            if remaining_rej <= 0:
                break
            if t['qty'] <= remaining_rej:
                auto_delink_tray_ids.append(t['tray_id'])
                remaining_rej -= t['qty']
            else:
                remaining_rej = 0
        reject_slots = []
        rem_rej = rejected_qty
        while rem_rej > 0:
            slot_qty = min(rem_rej, rej_cap)
            reject_slots.append({'qty': slot_qty, 'is_top': False})
            rem_rej -= slot_qty
        accept_slots = []
        if accepted_qty > 0:
            rem_acc = accepted_qty
            first = True
            while rem_acc > 0:
                slot_qty = min(rem_acc, orig_cap)
                accept_slots.append({'qty': slot_qty, 'is_top': first})
                first = False
                rem_acc -= slot_qty
        return Response({
            'success': True,
            'accepted_qty': accepted_qty,
            'rejected_qty': rejected_qty,
            'accept_slots': accept_slots,
            'reject_slots': reject_slots,
            'original_trays': orig_trays,
            'reuse_count': len(reuse_trays),
            'reuse_trays': reuse_trays,
            'auto_delink_tray_ids': auto_delink_tray_ids,
            'rej_prefix': rej_prefix,
            'rej_cap': rej_cap,
        })
    if action == 'SUBMIT_REJECT':
        try:
            return _na_do_submit_reject(request, lot_id, juat)
        except Exception as e:
            logger.exception("[na_action SUBMIT_REJECT] lot=%s", lot_id)
            return Response({'success': False, 'error': str(e)}, status=500)
    if action == 'SUBMIT_ACCEPT':
        try:
            return _na_do_submit_accept(request, lot_id, juat)
        except Exception as e:
            logger.exception("[na_action SUBMIT_ACCEPT] lot=%s", lot_id)
            return Response({'success': False, 'error': str(e)}, status=500)
    if action == 'FULL_ACCEPT':
        try:
            return _na_do_full_accept(request, lot_id, juat)
        except Exception as e:
            logger.exception("[na_action FULL_ACCEPT] lot=%s", lot_id)
            return Response({'success': False, 'error': str(e)}, status=500)
    return Response({'success': False, 'error': f'Unknown action: {action}'}, status=400)


def _na_do_full_accept(request, lot_id, juat):
    """Persist FULL acceptance for a NA lot."""
    from django.db import transaction
    import django.utils.timezone as tz
    total_qty = juat.nq_qc_accepted_qty or juat.total_case_qty or 0
    trays_qs = Nickel_AuditTrayId.objects.filter(
        lot_id=lot_id, rejected_tray=False, delink_tray=False
    ).order_by('-top_tray', 'id')
    if trays_qs.exists():
        trays = [
            {'tray_id': t.tray_id, 'qty': t.tray_quantity or 0, 'is_top': bool(t.top_tray)}
            for t in trays_qs
        ]
    else:
        upstream, _ = get_upstream_tray_distribution(lot_id)
        trays = [
            {'tray_id': t['tray_id'], 'qty': t['tray_quantity'] or 0, 'is_top': bool(t.get('top_tray', False))}
            for t in (upstream or [])
            if not t.get('rejected_tray') and not t.get('delink_tray')
        ]
    with transaction.atomic():
        for at in trays:
            tid = at['tray_id']
            Nickel_AuditTrayId.objects.update_or_create(
                lot_id=lot_id,
                tray_id=tid,
                defaults={
                    'tray_quantity': at['qty'],
                    'top_tray': at['is_top'],
                    'tray_type': juat.tray_type or '',
                    'tray_capacity': juat.tray_capacity or 20,
                },
            )
            Nickel_Audit_Accepted_TrayID_Store.objects.update_or_create(
                lot_id=lot_id,
                tray_id=tid,
                defaults={'tray_qty': at['qty'], 'user': request.user},
            )
        NickelAudit_Submission.objects.create(
            lot_id=lot_id,
            submission_type='FULL_ACCEPT',
            total_lot_qty=total_qty,
            accepted_qty=total_qty,
            rejected_qty=0,
            accept_trays_data=trays,
            created_by=request.user,
        )
        juat.na_qc_accptance = True
        juat.na_qc_accepted_qty = total_qty
        juat.na_last_process_date_time = tz.now()
        juat.last_process_module = 'Nickel Audit'
        juat.save(update_fields=[
            'na_qc_accptance', 'na_qc_accepted_qty',
            'na_last_process_date_time', 'last_process_module',
        ])
    logger.info("[na_full_accept] lot=%s user=%s qty=%d", lot_id, request.user, total_qty)
    return Response({'success': True})


def _na_do_submit_reject(request, lot_id, juat):
    """Persist rejection for a NA lot."""
    from django.db import transaction
    data = request.data
    reason_ids = data.get('reason_ids', [])
    rejected_qty = int(data.get('rejected_qty', 0))
    reject_trays = data.get('reject_trays', [])
    accept_trays = data.get('accept_trays', [])
    remarks = (data.get('remarks', '') or '').strip()
    if not reason_ids or rejected_qty <= 0:
        return Response({'success': False, 'error': 'reason_ids and rejected_qty required'}, status=400)
    total_qty = juat.nq_qc_accepted_qty or juat.total_case_qty or 0
    accepted_qty = total_qty - rejected_qty
    is_partial = accepted_qty > 0
    tray_type = (juat.tray_type or '').strip().lower()
    if tray_type.startswith('jb') or 'jumbo' in tray_type:
        allowed_prefix = 'JB'
        rej_cap = 12
    else:
        allowed_prefix = 'NB'
        rej_cap = 16
    for rt in reject_trays:
        tid = (rt.get('tray_id') or '').upper()
        if not tid.startswith(allowed_prefix):
            return Response(
                {'success': False, 'error': f'Reject tray {tid} must start with {allowed_prefix}'},
                status=400,
            )
        if int(rt.get('qty', 0)) > rej_cap:
            return Response(
                {'success': False, 'error': f'Reject tray {tid} qty exceeds max {rej_cap}'},
                status=400,
            )
    with transaction.atomic():
        reasons_qs = Nickel_Audit_Rejection_Table.objects.filter(id__in=reason_ids)
        reason_store, _ = Nickel_Audit_Rejection_ReasonStore.objects.update_or_create(
            lot_id=lot_id,
            defaults={
                'total_rejection_quantity': rejected_qty,
                'batch_rejection': not is_partial,
                'lot_rejected_comment': remarks,
                'user': request.user,
            },
        )
        reason_store.rejection_reason.set(reasons_qs)
        for rt in reject_trays:
            tid = rt.get('tray_id', '').strip()
            qty = int(rt.get('qty', 0))
            if not tid or qty <= 0:
                continue
            Nickel_Audit_Rejected_TrayScan.objects.update_or_create(
                lot_id=lot_id,
                rejected_tray_id=tid,
                defaults={
                    'rejected_tray_quantity': qty,
                    'rejection_reason': reasons_qs.first(),
                    'user': request.user,
                },
            )
        # Ensure NA tray records exist (create from upstream if needed)
        orig_trays_qs = Nickel_AuditTrayId.objects.filter(lot_id=lot_id, rejected_tray=False)
        if not orig_trays_qs.exists():
            upstream, _ = get_upstream_tray_distribution(lot_id)
            for t in (upstream or []):
                Nickel_AuditTrayId.objects.get_or_create(
                    lot_id=lot_id,
                    tray_id=t['tray_id'],
                    defaults={
                        'tray_quantity': t['tray_quantity'] or 0,
                        'top_tray': t.get('top_tray', False),
                        'tray_type': juat.tray_type or '',
                        'tray_capacity': juat.tray_capacity or 20,
                    },
                )
        orig_trays_qs = Nickel_AuditTrayId.objects.filter(lot_id=lot_id, rejected_tray=False)
        accept_tray_ids = {at['tray_id']: at for at in accept_trays if at.get('tray_id')}
        for tray_obj in orig_trays_qs:
            if tray_obj.tray_id in accept_tray_ids:
                at = accept_tray_ids[tray_obj.tray_id]
                tray_obj.tray_quantity = int(at.get('qty', 0))
                tray_obj.top_tray = bool(at.get('is_top', False))
                tray_obj.save(update_fields=['tray_quantity', 'top_tray'])
            else:
                tray_obj.delink_tray = True
                tray_obj.delink_tray_qty = str(tray_obj.tray_quantity)
                tray_obj.tray_quantity = 0
                tray_obj.save(update_fields=['delink_tray', 'delink_tray_qty', 'tray_quantity'])
        existing_ids = set(
            Nickel_AuditTrayId.objects.filter(lot_id=lot_id).values_list('tray_id', flat=True)
        )
        for at in accept_trays:
            tid = (at.get('tray_id') or '').strip()
            qty = int(at.get('qty', 0))
            if not tid or qty <= 0 or tid in existing_ids:
                continue
            Nickel_AuditTrayId.objects.create(
                lot_id=lot_id,
                tray_id=tid,
                tray_quantity=qty,
                top_tray=bool(at.get('is_top', False)),
                tray_type=juat.tray_type or '',
                tray_capacity=juat.tray_capacity or 20,
            )
        for at in accept_trays:
            tid = (at.get('tray_id') or '').strip()
            qty = int(at.get('qty', 0))
            if not tid or qty <= 0:
                continue
            Nickel_Audit_Accepted_TrayID_Store.objects.update_or_create(
                lot_id=lot_id,
                tray_id=tid,
                defaults={'tray_qty': qty, 'user': request.user},
            )
        import django.utils.timezone as tz
        juat.na_qc_rejection = not is_partial
        juat.na_qc_few_cases_accptance = is_partial
        juat.na_last_process_date_time = tz.now()
        juat.last_process_module = 'Nickel Audit'
        if is_partial:
            juat.na_qc_accepted_qty = accepted_qty
        juat.save(update_fields=[
            'na_qc_rejection', 'na_qc_few_cases_accptance',
            'na_last_process_date_time', 'last_process_module', 'na_qc_accepted_qty',
        ])
        submission_type = 'PARTIAL' if is_partial else 'FULL_REJECT'
        reason_data = {str(r.id): {'reason': r.rejection_reason} for r in reasons_qs}
        submission = NickelAudit_Submission.objects.create(
            lot_id=lot_id,
            submission_type=submission_type,
            total_lot_qty=total_qty,
            accepted_qty=accepted_qty,
            rejected_qty=rejected_qty,
            accept_trays_data=accept_trays,
            reject_trays_data=reject_trays,
            created_by=request.user,
        )
        if is_partial:
            child_juat = JigUnloadAfterTable(
                jig_qr_id=juat.jig_qr_id or '',
                combine_lot_ids=juat.combine_lot_ids or [],
                total_case_qty=accepted_qty,
                version=juat.version,
                plating_color=juat.plating_color,
                plating_stk_no=juat.plating_stk_no,
                polish_stk_no=juat.polish_stk_no,
                polish_finish=juat.polish_finish,
                plating_stk_no_list=juat.plating_stk_no_list or [],
                polish_stk_no_list=juat.polish_stk_no_list or [],
                version_list=juat.version_list or [],
                category=juat.category or '',
                tray_type=juat.tray_type or '',
                tray_capacity=juat.tray_capacity,
                nq_qc_accptance=True,
                nq_qc_accepted_qty=accepted_qty,
                na_qc_accptance=True,
                na_qc_accepted_qty=accepted_qty,
                na_last_process_date_time=tz.now(),
                last_process_module='Nickel Audit',
            )
            child_juat.save()
            for at in accept_trays:
                tid = (at.get('tray_id') or '').strip()
                qty = int(at.get('qty', 0))
                if tid and qty > 0:
                    Nickel_AuditTrayId.objects.update_or_create(
                        lot_id=child_juat.lot_id,
                        tray_id=tid,
                        defaults={
                            'tray_quantity': qty,
                            'top_tray': bool(at.get('is_top', False)),
                            'tray_type': juat.tray_type or '',
                            'tray_capacity': juat.tray_capacity or 20,
                        },
                    )
            NickelAudit_PartialAcceptLot.objects.create(
                new_lot_id=child_juat.lot_id,
                parent_lot_id=lot_id,
                parent_submission=submission,
                accepted_qty=accepted_qty,
                trays_snapshot=accept_trays,
                created_by=request.user,
            )
            NickelAudit_PartialRejectLot.objects.create(
                new_lot_id=_na_generate_lot_id(),
                parent_lot_id=lot_id,
                parent_submission=submission,
                rejected_qty=rejected_qty,
                rejection_reasons=reason_data,
                trays_snapshot=reject_trays,
                remarks=remarks,
                created_by=request.user,
            )
    logger.info(
        "[na_submit_reject] lot=%s rej_qty=%d partial=%s user=%s",
        lot_id, rejected_qty, is_partial, request.user,
    )
    return Response({'success': True, 'is_partial': is_partial})


def _na_do_submit_accept(request, lot_id, juat):
    """Persist full acceptance for a NA lot via tray scan."""
    from django.db import transaction
    import django.utils.timezone as tz
    accept_trays = request.data.get('accept_trays', [])
    if not accept_trays:
        return Response({'success': False, 'error': 'accept_trays required'}, status=400)
    with transaction.atomic():
        for at in accept_trays:
            tid = (at.get('tray_id') or '').strip()
            qty = int(at.get('qty', 0))
            if not tid or qty <= 0:
                continue
            Nickel_AuditTrayId.objects.update_or_create(
                lot_id=lot_id,
                tray_id=tid,
                defaults={
                    'tray_quantity': qty,
                    'top_tray': bool(at.get('is_top', False)),
                    'tray_type': juat.tray_type or '',
                    'tray_capacity': juat.tray_capacity or 20,
                },
            )
            Nickel_Audit_Accepted_TrayID_Store.objects.update_or_create(
                lot_id=lot_id,
                tray_id=tid,
                defaults={'tray_qty': qty, 'user': request.user},
            )
        total_qty = juat.nq_qc_accepted_qty or juat.total_case_qty or 0
        juat.na_qc_accptance = True
        juat.na_qc_accepted_qty = total_qty
        juat.na_last_process_date_time = tz.now()
        juat.last_process_module = 'Nickel Audit'
        juat.save(update_fields=[
            'na_qc_accptance', 'na_qc_accepted_qty',
            'na_last_process_date_time', 'last_process_module',
        ])
    logger.info("[na_submit_accept] lot=%s user=%s", lot_id, request.user)
    return Response({'success': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def na_delink_selected_trays(request):
    """Delink selected trays from NA lots."""
    from django.db import transaction
    from modelmasterapp.models import TrayId as TrayMaster
    stock_lot_ids = request.data.get('stock_lot_ids', [])
    if not stock_lot_ids:
        return Response({'success': False, 'error': 'stock_lot_ids required'}, status=400)
    updated = 0
    lots_processed = 0
    try:
        with transaction.atomic():
            for lot_id in stock_lot_ids:
                na_trays = Nickel_AuditTrayId.objects.filter(lot_id=lot_id, delink_tray=False)
                tray_ids = list(na_trays.values_list('tray_id', flat=True))
                na_trays.update(delink_tray=True)
                freed = TrayMaster.objects.filter(tray_id__in=tray_ids).update(
                    lot_id=None, delink_tray=True, tray_quantity=None
                )
                updated += freed
                lots_processed += 1
        logger.info("[na_delink_selected_trays] user=%s lots=%s freed=%d", request.user, stock_lot_ids, updated)
        return Response({'success': True, 'updated': updated, 'lots_processed': lots_processed})
    except Exception as e:
        logger.exception("[na_delink_selected_trays] error")
        return Response({'success': False, 'error': str(e)}, status=500)


# ═══════════════════════════════════════════════════════════════
#  END NA ACTION API
# ═══════════════════════════════════════════════════════════════

@method_decorator(login_required, name='dispatch')
class NACompletedView(APIView):
    """Nickel Audit Zone 1 Completed Table."""
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Nickel_Audit/NickelAudit_Completed.html'

    def get(self, request):
        from django.utils import timezone
        from datetime import datetime, timedelta
        import pytz

        user = request.user
        tz = pytz.timezone('Asia/Kolkata')
        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')
        if from_date_str and to_date_str:
            try:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            except ValueError:
                from_date = yesterday
                to_date = today
        else:
            from_date = yesterday
            to_date = today

        from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
        to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))

        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_1=True
        ).values_list('id', flat=True)

        na_rejection_qty_subquery = Nickel_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = (
            JigUnloadAfterTable.objects.select_related('version', 'plating_color', 'polish_finish')
            .prefetch_related('location')
            .filter(
                total_case_qty__gt=0,
                plating_color_id__in=allowed_color_ids,
            )
            .annotate(
                na_rejection_qty=na_rejection_qty_subquery,
            )
            .filter(
                Q(na_qc_accptance=True)
                | Q(na_qc_rejection=True)
                | Q(na_qc_few_cases_accptance=True, na_onhold_picking=False)
            )
            .filter(na_last_process_date_time__range=(from_datetime, to_datetime))
            .order_by('-na_last_process_date_time', '-lot_id')
        )

        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for jig_unload_obj in page_obj.object_list:
            data = {
                'batch_id': jig_unload_obj.unload_lot_id,
                'lot_id': jig_unload_obj.lot_id,
                'date_time': jig_unload_obj.created_at,
                'model_stock_no__model_no': 'Combined Model',
                'plating_color': jig_unload_obj.plating_color.plating_color if jig_unload_obj.plating_color else '',
                'polish_finish': jig_unload_obj.polish_finish.polish_finish if jig_unload_obj.polish_finish else '',
                'version__version_name': jig_unload_obj.version.version_name if jig_unload_obj.version else '',
                'vendor_internal': '',
                'location__location_name': ', '.join([loc.location_name for loc in jig_unload_obj.location.all()]),
                'tray_type': jig_unload_obj.tray_type or '',
                'tray_capacity': jig_unload_obj.tray_capacity or 0,
                'stock_lot_id': jig_unload_obj.lot_id,
                'last_process_module': jig_unload_obj.last_process_module or 'Jig Unload',
                'total_IP_accpeted_quantity': jig_unload_obj.total_case_qty,
                'na_qc_accptance': jig_unload_obj.na_qc_accptance,
                'na_qc_rejection': jig_unload_obj.na_qc_rejection,
                'na_qc_few_cases_accptance': jig_unload_obj.na_qc_few_cases_accptance,
                'na_onhold_picking': jig_unload_obj.na_onhold_picking,
                'na_hold_lot': jig_unload_obj.na_hold_lot,
                'na_holding_reason': jig_unload_obj.na_holding_reason,
                'na_release_lot': jig_unload_obj.na_release_lot,
                'na_release_reason': jig_unload_obj.na_release_reason,
                'na_physical_qty': jig_unload_obj.na_physical_qty,
                'na_missing_qty': jig_unload_obj.na_missing_qty or 0,
                'na_pick_remarks': jig_unload_obj.na_pick_remarks,
                'na_accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,
                'na_ac_accepted_qty_verified': jig_unload_obj.na_ac_accepted_qty_verified,
                'na_qc_accepted_qty': jig_unload_obj.na_qc_accepted_qty or 0,
                'na_last_process_date_time': jig_unload_obj.na_last_process_date_time,
                'plating_stk_no': jig_unload_obj.plating_stk_no or '',
                'polishing_stk_no': jig_unload_obj.polish_stk_no or '',
                'category': jig_unload_obj.category or '',
                'combine_lot_ids': jig_unload_obj.combine_lot_ids,
                'unload_lot_id': jig_unload_obj.unload_lot_id,
                'audit_check': jig_unload_obj.audit_check,
                'display_accepted_qty': jig_unload_obj.na_physical_qty or 0,
                'available_qty': jig_unload_obj.na_physical_qty or jig_unload_obj.total_case_qty or 0,
                'no_of_trays': 0,
            }

            tray_capacity = data['tray_capacity']
            display_qty = data['display_accepted_qty']
            if tray_capacity > 0 and display_qty > 0:
                data['no_of_trays'] = math.ceil(display_qty / tray_capacity)

            images = []
            if jig_unload_obj.plating_stk_no:
                plating_stk_no = str(jig_unload_obj.plating_stk_no)
                if len(plating_stk_no) >= 4:
                    model_no_prefix = plating_stk_no[:4]
                    model_master = (
                        ModelMaster.objects.filter(model_no__startswith=model_no_prefix)
                        .prefetch_related('images')
                        .first()
                    )
                    if model_master:
                        for img in model_master.images.all():
                            if img.master_image:
                                images.append(img.master_image.url)
            if not images and data['combine_lot_ids']:
                first_lot_id = data['combine_lot_ids'][0] if data['combine_lot_ids'] else None
                if first_lot_id:
                    total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
                    if total_stock and total_stock.batch_id and total_stock.batch_id.model_stock_no:
                        for img in total_stock.batch_id.model_stock_no.images.all():
                            if img.master_image:
                                images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images
            master_data.append(data)

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

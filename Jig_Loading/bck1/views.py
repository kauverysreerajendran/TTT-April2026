from django.views.generic import *
from modelmasterapp.models import *
from .models import Jig, JigLoadingMaster, JigLoadTrayId, JigLoadingManualDraft, JigCompleted
from rest_framework.decorators import *
from django.http import JsonResponse
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from math import ceil
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
import logging
import re
import json
from django.db import transaction
from django.core.paginator import Paginator
from datetime import datetime, timezone as dt_timezone
@method_decorator(login_required, name='dispatch') 
class JigView(TemplateView):
    template_name = "JigLoading/Jig_Picktable.html"
    
    # No of Trays Calculation
    def get_tray_capacity(stock):
        # Try batch first
        if stock.batch_id and getattr(stock.batch_id, 'tray_capacity', None):
            return stock.batch_id.tray_capacity
        # Try model_master
        if stock.model_stock_no and getattr(stock.model_stock_no, 'tray_capacity', None):
            return stock.model_stock_no.tray_capacity
        # Try tray_type
        if stock.batch_id and hasattr(stock.batch_id, 'tray_type') and stock.batch_id.tray_type:
            try:
                tray_type_obj = TrayType.objects.get(tray_type=stock.batch_id.tray_type)
                return tray_type_obj.tray_capacity
            except TrayType.DoesNotExist:
                pass
        # Try JigLoadingMaster
        jig_master = JigLoadingMaster.objects.filter(model_stock_no=stock.model_stock_no).first()
        if jig_master and getattr(jig_master, 'tray_capacity', None):
            return jig_master.tray_capacity
        return None
    
    
    

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Only show lots NOT completed (do not change row order), OR lots with half-filled trays from JigCompleted
        total_stock_qs = (
            TotalStockModel.objects.filter(brass_audit_accptance=True, Jig_Load_completed=False)
            # ✅ FIX: Only show partial-rejected lots that are released (onhold=False) — i.e. top tray scan done
            | TotalStockModel.objects.filter(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False, Jig_Load_completed=False)
            | TotalStockModel.objects.filter(brass_audit_rejection=True, Jig_Load_completed=False)
            | TotalStockModel.objects.filter(jig_draft=True, Jig_Load_completed=False)  # Include partial draft lots
        )
        
        # Include only excess lots (partial_lot_id exists) from completed lots with half-filled trays
        # Do NOT include original lots that have been split into excess lots
        excess_lots_only = JigCompleted.objects.filter(
            half_filled_tray_info__isnull=False,
            partial_lot_id__isnull=False
        ).exclude(
            half_filled_tray_info=[]
        ).values_list('partial_lot_id', flat=True)
        
        if excess_lots_only:
            # Use partial_lot_id as the lot_id for excess lots
            total_stock_qs |= TotalStockModel.objects.filter(
                lot_id__in=excess_lots_only,
                Jig_Load_completed=True
            )

        master_data = []
        # Build a set of lot_ids that are part of multi-model drafts (to show as Partial Draft)
        active_drafts = JigLoadingManualDraft.objects.filter(draft_status='active')
        combined_lot_ids_set = set()
        for d in active_drafts:
            try:
                ids = d.draft_data.get('combined_lot_ids', []) if isinstance(d.draft_data, dict) else []
                for cid in ids:
                    # If the combined id is different from the draft's own lot_id, mark it as partial
                    if cid and cid != d.lot_id:
                        combined_lot_ids_set.add(cid)
            except Exception:
                continue
        for stock in total_stock_qs:
            plating_stk_no = (
                getattr(stock.batch_id, 'plating_stk_no', None)
                or getattr(stock.model_stock_no, 'plating_stk_no', None)
            )
            polishing_stk_no = (
                getattr(stock.batch_id, 'polishing_stk_no', None)
                or getattr(stock.model_stock_no, 'polishing_stk_no', None)
            )

            tray_capacity = JigView.get_tray_capacity(stock)
            jig_type = ''
            jig_capacity = ''
            if plating_stk_no:
                jig_master = JigLoadingMaster.objects.filter(model_stock_no__plating_stk_no=plating_stk_no).first()
                if jig_master:
                    jig_type = f"{jig_master.jig_capacity}-Jig"
                    jig_capacity = jig_master.jig_capacity

            # ✅ FIX: For partial-rejected lots, display brass_audit_accepted_qty (not total_stock)
            if stock.brass_audit_few_cases_accptance and stock.brass_audit_accepted_qty and stock.brass_audit_accepted_qty > 0:
                lot_qty = stock.brass_audit_accepted_qty
            else:
                lot_qty = stock.total_stock or 0
            no_of_trays = 0
            if tray_capacity and tray_capacity > 0:
                no_of_trays = (lot_qty // tray_capacity) + (1 if lot_qty % tray_capacity else 0)

            # --- Fix: Use jig_draft for correct lot status ---
            if getattr(stock, 'released_flag', False):
                lot_status = 'Yet to Released'
                lot_status_class = 'lot-status-yet-released'
            elif getattr(stock, 'jig_draft', False):
                # If this lot is part of another draft's combined_lot_ids, show as Partial Draft
                if stock.lot_id in combined_lot_ids_set:
                    lot_status = 'Partial Draft'
                else:
                    lot_status = 'Draft'
                lot_status_class = 'lot-status-draft'
            else:
                # Check if this is an excess lot (partial_lot_id exists) or completed lot with half-filled trays
                jig_completed = JigCompleted.objects.filter(partial_lot_id=stock.lot_id).first()
                if jig_completed and jig_completed.half_filled_tray_info:
                    # This is an excess lot created from partial submission
                    lot_status = 'Partial Draft'
                    lot_status_class = 'lot-status-draft'
                    # Use sum of cases from half_filled_tray_info for excess lots
                    lot_qty = sum(t.get('cases', 0) for t in jig_completed.half_filled_tray_info)
                else:
                    # Check for regular completed lot with half-filled trays (original lot not split)
                    jig_completed = JigCompleted.objects.filter(lot_id=stock.lot_id).first()
                    if jig_completed and jig_completed.half_filled_tray_info and not jig_completed.partial_lot_id:
                        lot_status = 'Partial Draft'
                        lot_status_class = 'lot-status-draft'
                        # Update display_qty to show remaining broken hooks quantity
                        lot_qty = jig_completed.half_filled_tray_qty or sum(t.get('cases', 0) for t in jig_completed.half_filled_tray_info)
                    else:
                        lot_status = 'Yet to Start'
                        lot_status_class = 'lot-status-yet'

            # Recalculate no_of_trays after lot_qty may have been updated by lot status logic
            if tray_capacity and tray_capacity > 0:
                no_of_trays = (lot_qty // tray_capacity) + (1 if lot_qty % tray_capacity else 0)

            # ✅ FIX: Detect multi-model lots and extract model list for circle display
            is_multi_model = False
            model_list = []
            jig_completed = JigCompleted.objects.filter(lot_id=stock.lot_id).first()
            if jig_completed and getattr(jig_completed, 'is_multi_model', False):
                is_multi_model = True
                # Extract model numbers from no_of_model_cases if available (comma-separated list)
                if jig_completed.no_of_model_cases:
                    try:
                        model_list = [m.strip() for m in str(jig_completed.no_of_model_cases).split(',')]
                    except Exception:
                        model_list = [str(jig_completed.no_of_model_cases)]

            master_data.append({
                'batch_id': stock.batch_id.batch_id if stock.batch_id else '',
                'stock_lot_id': stock.lot_id,
                'plating_stk_no': plating_stk_no,
                'polishing_stk_no': polishing_stk_no,
                'plating_color': stock.plating_color.plating_color if stock.plating_color else '',
                'polish_finish': stock.polish_finish.polish_finish if stock.polish_finish else '',
                'version__version_internal': stock.version.version_internal if stock.version else '',
                'no_of_trays': no_of_trays,
                'display_qty': lot_qty,
                'jig_capacity': jig_capacity if jig_capacity else '',
                'jig_type': jig_type,
                'model_images': [img.master_image.url for img in stock.model_stock_no.images.all()] if stock.model_stock_no else [],
                'brass_audit_last_process_date_time': stock.brass_audit_last_process_date_time,
                'last_process_module': stock.last_process_module,
                'lot_status': lot_status,
                'lot_status_class': lot_status_class,
                'is_multi_model': is_multi_model,
                'model_list': model_list,
            })
        
        # Sort by Last Updated descending (newest first)
        master_data.sort(key=lambda x: x['brass_audit_last_process_date_time'] or datetime.min.replace(tzinfo=dt_timezone.utc), reverse=True)

        # Optional scan pinning: if a tray is scanned from any page, pin its row on page 1.
        scanned_tray = (self.request.GET.get('scanned_tray') or '').strip()
        context['scanned_tray_meta'] = {'exists': False}
        if scanned_tray:
            scanned_record = JigLoadTrayId.objects.filter(tray_id=scanned_tray).select_related('batch_id').first()
            if scanned_record and scanned_record.batch_id:
                match_idx = next(
                    (
                        idx for idx, row in enumerate(master_data)
                        if row.get('batch_id') == scanned_record.batch_id.batch_id
                        and row.get('stock_lot_id') == scanned_record.lot_id
                    ),
                    None
                )
                context['scanned_tray_meta'] = {
                    'exists': match_idx is not None,
                    'tray_id': scanned_record.tray_id,
                    'tray_qty': scanned_record.tray_quantity or scanned_record.tray_capacity or 0,
                    'batch_id': scanned_record.batch_id.batch_id,
                    'lot_id': scanned_record.lot_id,
                    'original_position': (match_idx + 1) if match_idx is not None else None,
                }
                if match_idx is not None:
                    pinned_row = master_data.pop(match_idx)
                    master_data.insert(0, pinned_row)
        
        context['master_data'] = master_data
        
        # Pagination: 10 rows per page
        paginator = Paginator(master_data, 10)
        page_number = self.request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        context['page_obj'] = page_obj
        context['master_data'] = page_obj.object_list
        
        return context 

# Tray Info API View
class TrayInfoView(APIView):
    def get(self, request, *args, **kwargs):
        logger = logging.getLogger(__name__)
        lot_id = request.GET.get('lot_id')
        batch_id = request.GET.get('batch_id')
        
        # Check if this lot is completed (either as original lot or as excess lot via partial_lot_id)
        jig_completed = JigCompleted.objects.filter(lot_id=lot_id, batch_id=batch_id).first()
        is_excess_lot = False
        if not jig_completed:
            # Check if this is an excess lot (partial_lot_id)
            jig_completed = JigCompleted.objects.filter(partial_lot_id=lot_id).first()
            is_excess_lot = True
        
        if jig_completed:
            # For excess lots (found via partial_lot_id): return only half_filled_tray_info
            # For regular completed lots: show delink_tray_info + half_filled_tray_info
            tray_list = []
            seen_tray_ids = set()
            
            if is_excess_lot:
                # EXCESS LOT: Only use half_filled_tray_info (already contains merged/allocated trays)
                for tray in (jig_completed.half_filled_tray_info or []):
                    tray_id = tray.get('tray_id')
                    if not tray_id or tray_id in seen_tray_ids:
                        continue
                    seen_tray_ids.add(tray_id)
                    tray_list.append({
                        'tray_id': tray_id,
                        'tray_quantity': tray.get('cases')
                    })
            else:
                # REGULAR COMPLETED LOT: Use delink_tray_info + half_filled_tray_info
                # Primary: delink_tray_info preserves the actual Jig Loading scan sequence
                for tray in (jig_completed.delink_tray_info or []):
                    tray_id = tray.get('tray_id')
                    if not tray_id or tray_id in seen_tray_ids:
                        continue
                    seen_tray_ids.add(tray_id)
                    tray_list.append({
                        'tray_id': tray_id,
                        'tray_quantity': tray.get('cases')
                    })
                # Secondary: half_filled_tray_info (overflow/pick trays not on jig)
                for tray in (jig_completed.half_filled_tray_info or []):
                    tray_id = tray.get('tray_id')
                    if not tray_id or tray_id in seen_tray_ids:
                        continue
                    seen_tray_ids.add(tray_id)
                    tray_list.append({
                        'tray_id': tray_id,
                        'tray_quantity': tray.get('cases')
                    })
        else:
            # For incomplete lots: check JigLoadingManualDraft first (preserves actual Jig Loading scan order).
            # BrassAudit rebuilds JigLoadTrayId with its own ordering (-top_tray, id), so we cannot
            # rely on JigLoadTrayId.id to reflect the Jig Loading scan sequence.
            draft = JigLoadingManualDraft.objects.filter(
                lot_id=lot_id, batch_id=batch_id
            ).first()
            draft_delink = (draft.delink_tray_info or []) if draft else []

            # ✅ FIX: For partial rejection lots, cap by brass_audit_accepted_qty
            stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
            if not stock:
                logger.warning(f"⚠️ TotalStockModel not found for lot_id={lot_id}")
                return Response({'trays': []})
            
            target_qty = (
                stock.brass_audit_accepted_qty
                if (stock and stock.brass_audit_few_cases_accptance
                    and stock.brass_audit_accepted_qty
                    and stock.brass_audit_accepted_qty > 0)
                else None
            )

            tray_list = []
            cumulative = 0
            seen_tray_ids = set()
            tray_sequence_rows = []

            if draft_delink:
                # Draft exists: use its delink_tray_info which has the Jig Loading scan order
                for tray in draft_delink:
                    tray_id = tray.get('tray_id')
                    if not tray_id or tray_id in seen_tray_ids:
                        continue
                    if target_qty is not None and cumulative >= target_qty:
                        break
                    seen_tray_ids.add(tray_id)
                    tray_qty = tray.get('cases') or 0
                    tray_list.append({'tray_id': tray_id, 'tray_quantity': tray_qty})
                    cumulative += tray_qty
            else:
                # No draft: Try querying JigLoadTrayId directly for this lot
                # This handles excess lots that don't have draft records
                jig_load_trays = list(
                    JigLoadTrayId.objects.filter(
                        lot_id=lot_id
                    ).order_by('id').values('tray_id', 'tray_quantity')
                )
                
                if jig_load_trays:
                    # Found trays directly linked to this lot_id
                    for tray in jig_load_trays:
                        if target_qty is not None and cumulative >= target_qty:
                            break
                        tray_id = tray['tray_id']
                        if not tray_id or tray_id in seen_tray_ids:
                            continue
                        seen_tray_ids.add(tray_id)
                        tray_qty = tray['tray_quantity'] or 0
                        tray_list.append({'tray_id': tray_id, 'tray_quantity': tray_qty})
                        cumulative += tray_qty
                    logger.info(f"✅ Found {len(tray_list)} trays directly for lot_id={lot_id} (excess lot case)")
                else:
                    # Fallback: use TrayId insertion order
                    tray_sequence_rows = list(
                        TrayId.objects.filter(
                            lot_id=lot_id,
                            batch_id__batch_id=batch_id
                        ).order_by('id').values('tray_id', 'tray_quantity')
                    )

                # Build latest quantity map from JigLoadTrayId (if duplicate rows exist,
                # the last saved quantity for a tray_id wins).
                latest_qty_by_tray_id = {}
                for t in JigLoadTrayId.objects.filter(
                    lot_id=lot_id,
                    batch_id__batch_id=batch_id
                ).order_by('id').values('tray_id', 'tray_quantity'):
                    if t['tray_id']:
                        latest_qty_by_tray_id[t['tray_id']] = t['tray_quantity']

                if tray_sequence_rows:
                    for t in tray_sequence_rows:
                        if target_qty is not None and cumulative >= target_qty:
                            break
                        tray_id = t['tray_id']
                        if not tray_id or tray_id in seen_tray_ids:
                            continue
                        seen_tray_ids.add(tray_id)
                        tray_qty = latest_qty_by_tray_id.get(tray_id, t['tray_quantity']) or 0
                        tray_list.append({'tray_id': tray_id, 'tray_quantity': tray_qty})
                        cumulative += tray_qty
                else:
                    # Last fallback: if TrayId is unavailable for this lot, use latest unique
                    # entries from JigLoadTrayId without tray_id sorting.
                    rows = list(
                        JigLoadTrayId.objects.filter(
                            lot_id=lot_id,
                            batch_id__batch_id=batch_id
                        ).order_by('id').values('tray_id', 'tray_quantity')
                    )
                    latest_rows_reversed = []
                    seen_latest = set()
                    for t in reversed(rows):
                        tray_id = t['tray_id']
                        if not tray_id or tray_id in seen_latest:
                            continue
                        seen_latest.add(tray_id)
                        latest_rows_reversed.append(t)

                    for t in reversed(latest_rows_reversed):
                        if target_qty is not None and cumulative >= target_qty:
                            break
                        tray_id = t['tray_id']
                        if not tray_id or tray_id in seen_tray_ids:
                            continue
                        seen_tray_ids.add(tray_id)
                        tray_qty = t['tray_quantity'] or 0
                        tray_list.append({'tray_id': tray_id, 'tray_quantity': tray_qty})
                        cumulative += tray_qty

        logger.info(
            "Jig TrayInfoView lot_id=%s batch_id=%s trays_returned=%s",
            lot_id,
            batch_id,
            len(tray_list)
        )
        # Ensure the top_tray (if any) remains at position 0 in the returned list
        try:
            top_tray_obj = JigLoadTrayId.objects.filter(
                lot_id=lot_id,
                batch_id__batch_id=batch_id,
                top_tray=True
            ).order_by('id').first()
            if top_tray_obj and top_tray_obj.tray_id and tray_list:
                top_id = top_tray_obj.tray_id
                # find current index
                idx = next((i for i, t in enumerate(tray_list) if t.get('tray_id') == top_id), None)
                if idx is not None and idx != 0:
                    item = tray_list.pop(idx)
                    tray_list.insert(0, item)
        except Exception:
            # Swallow any unexpected errors here to avoid breaking the API
            pass
        
        return Response({'trays': tray_list})
       
# Tray Validation API View   
class TrayValidateAPIView(APIView):
    def post(self, request, *args, **kwargs):
        batch_id = request.data.get('batch_id')
        lot_id = request.data.get('lot_id')
        tray_ids = request.data.get('tray_ids', [])
        if not batch_id or not lot_id:
            return Response({'validated': False, 'message': 'batch_id and lot_id required'}, status=status.HTTP_400_BAD_REQUEST)

        allocated_trays = JigLoadTrayId.objects.filter(
            lot_id=lot_id,
            batch_id__batch_id=batch_id
        ).values_list('tray_id', flat=True)
        allocated_tray_set = set(str(t) for t in allocated_trays)
        scanned_tray_set = set(str(t) for t in tray_ids)

        if not allocated_tray_set:
            return Response({'validated': False, 'message': 'No allocated trays found for this batch.'}, status=status.HTTP_400_BAD_REQUEST)

        if not scanned_tray_set.issubset(allocated_tray_set):
            invalid = scanned_tray_set - allocated_tray_set
            return Response({
                'validated': False,
                'message': f'Tray IDs not allocated: {", ".join(invalid)}',
                'allocated_trays': list(allocated_tray_set),
                'scanned_trays': list(scanned_tray_set)
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({'validated': True, 'message': 'Tray validation successful'}, status=status.HTTP_200_OK)


# Class for "Add Model" button data
class JigAddModalDataView(TemplateView):
    """
    Comprehensive modal data preparation for "Add Jig" functionality.
    Handles all data selection, calculation, and validation logic.
    """
    def get(self, request, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        
        batch_id = request.GET.get('batch_id')
        lot_id = request.GET.get('lot_id')
        jig_qr_id = request.GET.get('jig_qr_id')
        # --- FIX: Only restore from draft if not supplied by user ---
        broken_hooks_param = request.GET.get('broken_hooks', None)
        broken_hooks = int(broken_hooks_param) if broken_hooks_param not in [None, ''] else 0

        try:
            try:
                draft = JigLoadingManualDraft.objects.get(
                    batch_id=batch_id,
                    lot_id=lot_id,
                    user=request.user
                )
                # Only restore from draft if user did not supply a new value
                if (broken_hooks_param in [None, '']) and draft.draft_data.get('broken_buildup_hooks') is not None:
                    broken_hooks = int(draft.draft_data.get('broken_buildup_hooks', 0))
                    logger.info(f"🔄 Restored broken_hooks from draft: {broken_hooks}")
            except JigLoadingManualDraft.DoesNotExist:
                pass
            
            logger.info(f"🔍 JigAddModal: Processing batch_id={batch_id}, lot_id={lot_id}, jig_qr_id={jig_qr_id}, broken_hooks={broken_hooks}")
            
            # ✅ FIX: Handle excess lots (partial_lot_id) before normal TotalStockModel lookup
            jig_completed = JigCompleted.objects.filter(partial_lot_id=lot_id).first()
            if jig_completed:
                logger.info(f"🎯 EXCESS LOT DETECTED: partial_lot_id={lot_id}, using half_filled_tray_info")
                
                # Extract tray data from half_filled_tray_info
                tray_data = jig_completed.half_filled_tray_info or []
                if not tray_data:
                    logger.warning(f"⚠️ Empty half_filled_tray_info for excess lot {lot_id}")
                    return JsonResponse({
                        'success': True,
                        'total_qty': 0,
                        'trays': [],
                        'delink_table': [],
                        'tray_distribution': [],
                        'jig_capacity': 0,
                        'tray_capacity': 12,  # default
                        'message': 'Empty excess lot - no tray data available'
                    })
                
                # Calculate total quantity from tray data
                total_qty = sum(int(t.get('cases', 0)) for t in tray_data)
                
                # Get original batch/stock info for tray capacity resolution
                try:
                    original_stock = TotalStockModel.objects.get(lot_id=jig_completed.lot_id)
                    batch = original_stock.batch_id
                    model_master = batch.model_stock_no if batch else original_stock.model_stock_no
                    
                    # Get tray capacity from master table
                    tray_capacity = 12  # default
                    if batch and batch.tray_type:
                        try:
                            from modelmasterapp.models import TrayType
                            tray_type_obj = TrayType.objects.get(tray_type=batch.tray_type)
                            tray_capacity = tray_type_obj.tray_capacity
                        except:
                            pass
                    
                    # Get jig capacity
                    jig_capacity = 0
                    if model_master:
                        try:
                            jig_master = JigLoadingMaster.objects.filter(model_stock_no=model_master).first()
                            if jig_master:
                                jig_capacity = jig_master.jig_capacity
                        except:
                            pass
                    
                    # Build modal response for excess lot
                    plating_stk_no = batch.plating_stk_no if batch else ''
                    
                    # ✅ FIX: Create delink_table from half_filled_tray_info for excess lots
                    delink_table = []
                    for idx, tray in enumerate(tray_data):
                        delink_table.append({
                            'id': idx + 1,
                            'tray_id': tray.get('tray_id', f'TRAY-{idx+1:03d}'),
                            'cases': tray.get('cases', 0),
                            'status': 'pending',  # Ready for scanning
                            'lot_id': lot_id,
                            'is_excess': True
                        })
                    
                    logger.info(f"✅ EXCESS LOT RESPONSE: total_qty={total_qty}, tray_capacity={tray_capacity}, jig_capacity={jig_capacity}, delink_trays={len(delink_table)}")

                    # --- NEW: Split delink_table into jig_trays and excess_trays based on jig_capacity ---
                    try:
                        tray_capacity_val = int(tray_capacity) if tray_capacity else 1
                    except Exception:
                        tray_capacity_val = 1

                    try:
                        jig_capacity_val = int(jig_capacity) if jig_capacity else 0
                    except Exception:
                        jig_capacity_val = 0

                    # Split trays by cumulative cases so jig_trays sum up to jig_capacity
                    jig_trays = []
                    excess_trays = []
                    cumulative = 0
                    for tray in delink_table:
                        qty = int(tray.get('tray_quantity') or tray.get('cases') or 0)
                        if cumulative >= jig_capacity_val:
                            excess_trays.append(tray)
                            continue
                        if cumulative + qty <= jig_capacity_val:
                            jig_trays.append(tray)
                            cumulative += qty
                        else:
                            allowed = max(0, jig_capacity_val - cumulative)
                            if allowed > 0:
                                t_copy = tray.copy()
                                if 'tray_quantity' in t_copy:
                                    t_copy['tray_quantity'] = allowed
                                else:
                                    t_copy['cases'] = allowed
                                jig_trays.append(t_copy)
                            remainder = qty - allowed
                            if remainder > 0:
                                r_copy = tray.copy()
                                if 'tray_quantity' in r_copy:
                                    r_copy['tray_quantity'] = remainder
                                else:
                                    r_copy['cases'] = remainder
                                excess_trays.append(r_copy)
                            cumulative = jig_capacity_val

                    return JsonResponse({
                        'success': True,
                        'form_title': f"Jig Loading / Excess Lot: {plating_stk_no or 'N/A'}",
                        'jig_id': jig_qr_id,
                        'nickel_bath_type': None,
                        'tray_type': getattr(batch, 'tray_type', 'Normal'),
                        'broken_buildup_hooks': broken_hooks,
                        'empty_hooks': 0,
                        'loaded_cases_qty': 0,
                        'effective_loaded_cases': 0,
                        'lot_qty': total_qty,
                        'updated_lot_qty': 0,
                        'jig_capacity': jig_capacity,
                        'effective_jig_capacity': jig_capacity - broken_hooks,
                        'jig_type': None,
                        'loaded_hooks': 0,
                        'add_model_enabled': False,
                        'can_save': True,
                        'model_images': [],
                        # Only trays that fit into the jig should be used for delink scanning
                        'delink_table': jig_trays,
                        # Remaining trays are excess and should be handled separately by the UI
                        'excess_trays': excess_trays,
                        'logs': [],
                        'no_of_cycle': 1,
                        'plating_stk_no': plating_stk_no,
                        'modal_validation': {'max_broken_hooks': 5},
                        'ui_config': {},
                        'tray_distribution': tray_data,  # Use half_filled_tray_info as tray distribution
                        'half_filled_tray_cases': 0,
                        'remaining_cases': 0,
                        'excess_message': "",
                    })
                    
                except TotalStockModel.DoesNotExist:
                    logger.error(f"❌ Cannot find original TotalStockModel for excess lot, original_lot_id={jig_completed.lot_id}")
                    return JsonResponse({'success': False, 'error': 'Cannot resolve excess lot original data'}, status=404)
                except Exception as e:
                    logger.error(f"❌ Error processing excess lot: {str(e)}", exc_info=True)
                    return JsonResponse({'success': False, 'error': f'Error processing excess lot: {str(e)}'}, status=500)
            
            # Normal lot processing - fetch TotalStockModel for batch/lot
            try:
                stock = TotalStockModel.objects.get(lot_id=lot_id)
                logger.info(f"✅ Found TotalStockModel for lot_id={lot_id}: batch_id={stock.batch_id}, total_stock={stock.total_stock}")
            except TotalStockModel.DoesNotExist:
                logger.error(f"❌ TotalStockModel not found for lot_id={lot_id}")
                return JsonResponse({'success': False, 'error': f'Lot not found: {lot_id}'}, status=404)
            except Exception as e:
                logger.error(f"❌ Error fetching TotalStockModel: {str(e)}", exc_info=True)
                return JsonResponse({'success': False, 'error': f'Error fetching lot data: {str(e)}'}, status=500)
            
            # ✅ FIX: Add null checks before accessing batch properties
            batch = stock.batch_id
            if not batch:
                logger.error(f"❌ Batch is None for lot_id={lot_id}, stock={stock}")
                # Fallback: Try to find any batch for this lot
                try:
                    another_stock = TotalStockModel.objects.filter(lot_id=lot_id).exclude(batch_id__isnull=True).first()
                    if another_stock:
                        batch = another_stock.batch_id
                        logger.info(f"🔄 Found batch from another stock record: {batch}")
                    else:
                        return JsonResponse({'success': False, 'error': 'Batch data is missing, cannot determine jig capacity'}, status=400)
                except Exception as e:
                    logger.error(f"❌ Error finding batch fallback: {str(e)}")
                    return JsonResponse({'success': False, 'error': 'Batch data cannot be resolved'}, status=400)
            
            model_master = batch.model_stock_no if (batch and batch.model_stock_no) else stock.model_stock_no
            if not model_master:
                logger.error(f"❌ Model master is None for lot_id={lot_id}, batch={batch}")
                return JsonResponse({'success': False, 'error': 'Model data is missing'}, status=400)
            
            logger.info(f"✅ Resolved: batch_id={batch.batch_id}, model={getattr(model_master, 'model_no', 'unknown')}")

            # BUG 10 FIX: Plating colour compatibility check for "Add Model".
            # When a jig_qr_id is supplied and it already has a drafted lot, the new lot
            # must share the same plating colour — different plating colours mean a
            # different bath process, so mixing them on one jig is incorrect.
            if jig_qr_id:
                existing_draft = JigLoadingManualDraft.objects.filter(
                    jig_id=jig_qr_id,
                    draft_status='active'
                ).exclude(lot_id=lot_id).first()

                if existing_draft:
                    # Resolve plating colour of the already-drafted lot
                    try:
                        existing_stock = TotalStockModel.objects.get(lot_id=existing_draft.lot_id)
                        existing_color = (
                            existing_stock.plating_color.plating_color
                            if existing_stock.plating_color else None
                        )
                        new_color = (
                            stock.plating_color.plating_color
                            if stock.plating_color else None
                        )
                        if existing_color and new_color and existing_color != new_color:
                            logger.warning(
                                f"⛔ Plating colour mismatch: existing={existing_color}, new={new_color} "
                                f"for jig {jig_qr_id}"
                            )
                            return JsonResponse({
                                'success': False,
                                'error': (
                                    f"Plating colour mismatch: this jig already has a lot with "
                                    f"'{existing_color}' plating. Cannot add a lot with "
                                    f"'{new_color}' plating to the same jig."
                                )
                            }, status=400)
                    except TotalStockModel.DoesNotExist:
                        pass

            # Comprehensive plating_stk_no resolution logic
            plating_stk_no = self._resolve_plating_stock_number(batch, model_master)
            
            # Comprehensive data preparation with error handling
            try:
                modal_data = self._prepare_modal_data(request, batch, model_master, stock, jig_qr_id, lot_id, broken_hooks)
                if not modal_data or not isinstance(modal_data, dict):
                    logger.error(f"❌ Modal data is invalid: {type(modal_data)}")
                    return JsonResponse({'success': False, 'error': 'Failed to prepare modal data'}, status=500)
            except Exception as e:
                logger.error(f"❌ Exception in _prepare_modal_data: {str(e)}", exc_info=True)
                return JsonResponse({'success': False, 'error': f'Error preparing modal data: {str(e)}'}, status=500)

            # Load draft data if exists and override modal_data
            try:
                draft = JigLoadingManualDraft.objects.get(batch_id=batch_id, lot_id=lot_id, user=request.user)
                draft_data = draft.draft_data
                # Override with draft values
                modal_data['original_lot_qty'] = draft.original_lot_qty or modal_data.get('original_lot_qty')
                modal_data['updated_lot_qty'] = draft.updated_lot_qty or modal_data.get('updated_lot_qty')
                modal_data['delink_tray_info'] = draft.delink_tray_info or []
                modal_data['partial_tray_info'] = draft_data.get('partial_tray_info', [])
                modal_data['half_filled_tray_info'] = draft.half_filled_tray_info or []
                # NOTE: Do NOT override tray_distribution from draft.
                # The draft stores {delink, partial, half_filled} which lacks current_lot.tray_capacity.
                # The freshly computed tray_distribution (with current_lot.tray_capacity) must be preserved
                # so the frontend can read the correct tray capacity for Add Model.
                # modal_data['tray_distribution'] = draft_data.get('tray_distribution', modal_data.get('tray_distribution'))
                # Only restore broken hooks from draft if user didn't provide a new value
                if broken_hooks_param in [None, '']:
                    modal_data['broken_buildup_hooks'] = draft.broken_hooks or modal_data.get('broken_buildup_hooks')
                modal_data['jig_capacity'] = draft.jig_capacity or modal_data.get('jig_capacity')
                modal_data['loaded_cases_qty'] = draft.loaded_cases_qty or modal_data.get('loaded_cases_qty')
                logger.info(f"🔄 Restored draft data for batch_id={batch_id}, lot_id={lot_id}")
            except JigLoadingManualDraft.DoesNotExist:
                pass

            # Calculate excess message if lot qty exceeds jig capacity
            # Calculate excess message if lot qty exceeds jig capacity (no splitting)
            # Use the corrected original_lot_qty (may have been restored from JigCompleted for half-filled lots)
            lot_qty = modal_data.get('original_lot_qty') or stock.total_stock
            jig_capacity = modal_data.get('jig_capacity', 0)
            excess = max(0, lot_qty - jig_capacity)
            excess_message = f"{excess} cases are in excess" if excess > 0 else ""

            # Enhanced logging for debugging
            logger.info(f"📊 Modal data prepared: plating_stk_no={plating_stk_no}, jig_type={modal_data.get('jig_type')}, jig_capacity={modal_data.get('jig_capacity')}, broken_hooks={broken_hooks}")
            
            # ✅ FIX: Ensure all array/object fields have safe defaults (never None)
            safe_modal_data = {
                'model_images': modal_data.get('model_images') or [],
                'delink_table': modal_data.get('delink_table') or [],
                'modal_validation': modal_data.get('modal_validation') or {},
                'ui_config': modal_data.get('ui_config') or {},
                'tray_distribution': modal_data.get('tray_distribution') or [],
                'logs': modal_data.get('logs') or [],
            }

            # --- NEW: Split delink_table into jig_trays and excess_trays based on jig_capacity & tray_capacity ---
            tray_capacity_val = None
            try:
                # Try to read tray_capacity from prepared tray_distribution
                tray_dist = modal_data.get('tray_distribution') or {}
                if isinstance(tray_dist, dict):
                    current_lot_info = tray_dist.get('current_lot') or {}
                    tray_capacity_val = int(current_lot_info.get('tray_capacity')) if current_lot_info.get('tray_capacity') else None
            except Exception:
                tray_capacity_val = None

            if not tray_capacity_val:
                try:
                    from modelmasterapp.models import TrayType
                    if batch and getattr(batch, 'tray_type', None):
                        tt = TrayType.objects.filter(tray_type=batch.tray_type).first()
                        tray_capacity_val = int(tt.tray_capacity) if tt else None
                except Exception:
                    tray_capacity_val = None

            if not tray_capacity_val:
                tray_capacity_val = 1

            try:
                jig_capacity_val = int(modal_data.get('jig_capacity', 0) or 0)
            except Exception:
                jig_capacity_val = 0

            # Capacity-aware split: accumulate tray quantities until jig_capacity reached
            delink_list = safe_modal_data['delink_table'] or []
            jig_trays = []
            excess_trays = []
            cumulative = 0
            for tray in delink_list:
                qty = int(tray.get('tray_quantity') or tray.get('cases') or 0)
                if cumulative >= jig_capacity_val:
                    excess_trays.append(tray)
                    continue
                if cumulative + qty <= jig_capacity_val:
                    jig_trays.append(tray)
                    cumulative += qty
                else:
                    allowed = max(0, jig_capacity_val - cumulative)
                    if allowed > 0:
                        t_copy = tray.copy()
                        if 'tray_quantity' in t_copy:
                            t_copy['tray_quantity'] = allowed
                        else:
                            t_copy['cases'] = allowed
                        jig_trays.append(t_copy)
                    remainder = qty - allowed
                    if remainder > 0:
                        r_copy = tray.copy()
                        if 'tray_quantity' in r_copy:
                            r_copy['tray_quantity'] = remainder
                        else:
                            r_copy['cases'] = remainder
                        excess_trays.append(r_copy)
                    cumulative = jig_capacity_val

            return JsonResponse({
                'success': True,
                'form_title': f"Jig Loading / Plating Stock No: {plating_stk_no or 'N/A'}",
                'jig_id': jig_qr_id,
                'nickel_bath_type': modal_data.get('nickel_bath_type'),
                'tray_type': modal_data.get('tray_type'),
                'broken_buildup_hooks': modal_data.get('broken_buildup_hooks', 0),
                'empty_hooks': modal_data.get('empty_hooks', 0),
                'loaded_cases_qty': modal_data.get('loaded_cases_qty', 0),
                'effective_loaded_cases': modal_data.get('effective_loaded_cases', modal_data.get('loaded_cases_qty', 0)),
                'lot_qty': lot_qty or 0,
                'updated_lot_qty': modal_data.get('updated_lot_qty', 0),
                'jig_capacity': modal_data.get('jig_capacity', 0),
                'effective_jig_capacity': modal_data.get('effective_jig_capacity', 0),
                'jig_type': modal_data.get('jig_type'),
                'loaded_hooks': modal_data.get('loaded_hooks', 0),
                'add_model_enabled': modal_data.get('add_model_enabled', False),
                'can_save': modal_data.get('can_save', False),
                'model_images': safe_modal_data['model_images'],
                # Only trays that fit into the jig should be used for delink scanning
                'delink_table': jig_trays,
                # Remaining trays are excess and should be handled separately by the UI
                'excess_trays': excess_trays,
                'logs': safe_modal_data['logs'],
                'no_of_cycle': modal_data.get('no_of_cycle', 1),
                'plating_stk_no': plating_stk_no,
                'modal_validation': safe_modal_data['modal_validation'],
                'ui_config': safe_modal_data['ui_config'],
                'tray_distribution': safe_modal_data['tray_distribution'],
                'half_filled_tray_cases': modal_data.get('half_filled_tray_cases', 0),
                'remaining_cases': modal_data.get('remaining_cases', 0),
                'excess_message': excess_message,
            })

        except Exception as e:
            logger.error(f"💥 Exception in JigAddModalDataView: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to load modal data: {str(e)}'
            }, status=500)
    
    def _resolve_plating_stock_number(self, batch, model_master):
        """
        Centralized plating stock number resolution logic.
        Priority: ModelMasterCreation.plating_stk_no -> ModelMaster.plating_stk_no
        """
        plating_stk_no = ''
        if batch and batch.plating_stk_no:
            plating_stk_no = batch.plating_stk_no
        elif batch and batch.model_stock_no and batch.model_stock_no.plating_stk_no:
            plating_stk_no = batch.model_stock_no.plating_stk_no
        return plating_stk_no
# Comprehensive modal data preparation method    
    def _prepare_modal_data(self, request, batch, model_master, stock, jig_qr_id, lot_id, broken_hooks=0):
        """
        Comprehensive modal data preparation including all calculations and validations.
        """
        import logging
        import re
        logger = logging.getLogger(__name__)
        
        # Calculate max broken hooks based on jig ID prefix
        max_broken_hooks = 5  # default
        if jig_qr_id:
            match = re.match(r'J(\d+)-', jig_qr_id)
            if match:
                jig_capacity_from_id = int(match.group(1))
                max_broken_hooks = 10 if jig_capacity_from_id >= 144 else 5
                # Restrict broken_hooks to max allowed
                if broken_hooks > max_broken_hooks:
                    broken_hooks = max_broken_hooks
        
        # Initialize all modal data variables
        modal_data = {
            'nickel_bath_type': None,
            'tray_type': 'Normal',
            'broken_buildup_hooks': broken_hooks,
            'empty_hooks': 0,
            'loaded_cases_qty': 0,
            'jig_capacity': 0,
            'jig_type': None,
            'loaded_hooks': 0,
            'add_model_enabled': False,
            'model_images': [],
            'delink_table': [],
            'no_of_cycle': 1,
            'modal_validation': {},
            'ui_config': {},
            'can_save': False,
        }
        
        # Set max broken hooks in validation
        modal_data['modal_validation']['max_broken_hooks'] = max_broken_hooks
        
        # Set initial loaded_cases_qty to 0 (no trays scanned yet)
        modal_data['loaded_cases_qty'] = 0
        
        # Calculate effective_loaded_cases based on broken hooks
        # ✅ FIX: For partial-rejected lots (few_cases_accptance=True), use brass_audit_accepted_qty
        if stock.brass_audit_few_cases_accptance and stock.brass_audit_accepted_qty and stock.brass_audit_accepted_qty > 0:
            original_lot_qty = stock.brass_audit_accepted_qty
        else:
            original_lot_qty = stock.total_stock or 0

        # Fallback: For half-filled partial lots, stock.total_stock is 0 after the main jig
        # submission, but the real remaining quantity lives in JigCompleted.half_filled_tray_qty.
        # Detect this case and restore the correct quantity/tray distribution.
        _jig_partial_completed = None
        if original_lot_qty == 0:
            _jig_partial_completed = JigCompleted.objects.filter(lot_id=lot_id).first()
            if _jig_partial_completed and _jig_partial_completed.half_filled_tray_info:
                half_qty = _jig_partial_completed.half_filled_tray_qty or sum(
                    t.get('cases', 0) for t in (_jig_partial_completed.half_filled_tray_info or [])
                )
                if half_qty > 0:
                    original_lot_qty = half_qty
                    logger.info(f"📦 Half-filled partial lot {lot_id}: restored qty={original_lot_qty} from JigCompleted.half_filled_tray_qty")

        if broken_hooks > 0:
            # With broken hooks, effective quantity is original minus broken hooks
            modal_data['effective_loaded_cases'] = max(0, original_lot_qty - broken_hooks)
            logger.info(f"🔧 Broken hooks adjustment: original={original_lot_qty}, broken_hooks={broken_hooks}, effective={modal_data['effective_loaded_cases']}")
        else:
            # No broken hooks - use full lot quantity
            modal_data['effective_loaded_cases'] = original_lot_qty
        
        # Store original lot qty for reference
        modal_data['original_lot_qty'] = original_lot_qty
        
        # Resolve plating stock number
        plating_stk_no = self._resolve_plating_stock_number(batch, model_master)
        
        # Get tray capacity from TrayType master table (STRICT: Always from database)
        tray_capacity = None
        if batch and batch.tray_type:
            tray_type_obj = TrayType.objects.filter(tray_type=batch.tray_type).first()
            if tray_type_obj:
                tray_capacity = tray_type_obj.tray_capacity
            else:
                logger.error(f"❌ Tray type '{batch.tray_type}' not found in TrayType master table")
                tray_capacity = 16  # Fallback for Normal
        else:
            logger.warning(f"⚠️ No tray type found in batch, using default Normal tray capacity")
            tray_capacity = 16  # Default for Normal tray type
        
        print(f"💾 MASTER TABLE LOOKUP:")
        print(f"  Batch Tray Type: {batch.tray_type if batch else 'None'}")
        print(f"  Resolved Tray Capacity: {tray_capacity}")
        
        # Get jig capacity from JigLoadingMaster table (STRICT: Always from database)

        jig_master = JigLoadingMaster.objects.filter(model_stock_no=model_master).first()
        
        # Jig Capacity - Fetch from master as per the model number
        jig_master = JigLoadingMaster.objects.filter(model_stock_no=model_master).first()
        
        # Fallback: Try by model_no string if not found
        if not jig_master and hasattr(model_master, "model_no"):
            jig_master = JigLoadingMaster.objects.filter(model_stock_no__model_no=model_master.model_no).first()
        
        if jig_master:
            modal_data['jig_type'] = f"{jig_master.jig_capacity:03d}" if jig_master.jig_capacity else None
            modal_data['jig_capacity'] = jig_master.jig_capacity
            print(f"  Jig Master Found: {jig_master.jig_type} - Capacity: {jig_master.jig_capacity}")
        else:
            modal_data['jig_type'] = None
            modal_data['jig_capacity'] = 0
            logger.error(f"❌ No jig master found for model: {getattr(model_master, 'model_no', str(model_master))}. Please configure JigLoadingMaster.")
            print(f"  Jig Master Not Found: No capacity assigned.")
        # End of Jig Capacity - Fetch from master as per the model number

        
        print(f"  Final Jig Capacity: {modal_data['jig_capacity']}")
        print(f"  Final Jig Type: {modal_data['jig_type']}")
        
        # Calculate effective jig capacity (jig_capacity - broken_hooks)
        if broken_hooks > 0:
            modal_data['effective_jig_capacity'] = max(0, modal_data['jig_capacity'] - broken_hooks)
            logger.info(f"🔧 Effective jig capacity: {modal_data['jig_capacity']} - {broken_hooks} = {modal_data['effective_jig_capacity']}")
        else:
            modal_data['effective_jig_capacity'] = modal_data['jig_capacity']
        
        # Set tray type from batch
        modal_data['tray_type'] = batch.tray_type if batch else 'Normal'

        # Re-validate broken hooks based on actual jig capacity (fallback for when jig_qr_id is empty)
        if not jig_qr_id and modal_data['jig_capacity'] > 0:
            # Use actual jig capacity to determine max broken hooks
            max_broken_hooks = 10 if modal_data['jig_capacity'] >= 144 else 5
            # Restrict broken_hooks to max allowed
            if broken_hooks > max_broken_hooks:
                broken_hooks = max_broken_hooks
                modal_data['broken_buildup_hooks'] = broken_hooks
            # Update validation data
            modal_data['modal_validation']['max_broken_hooks'] = max_broken_hooks

        # Nickel Bath Type and jig calculations
        # Auto-fill with comprehensive defaults
        modal_data['nickel_bath_type'] = "Bright"  # Default
        modal_data['loaded_cases_qty'] = stock.total_stock
        modal_data['loaded_hooks'] = stock.total_stock
        # --- FIX: Only allow empty_hooks > 0 if lot qty < jig capacity, else always 0 ---
        if modal_data['loaded_cases_qty'] < modal_data['jig_capacity']:
            modal_data['empty_hooks'] = modal_data['jig_capacity'] - modal_data['loaded_cases_qty']
        else:
            modal_data['empty_hooks'] = 0

        # Apply broken hooks adjustment and half-filled tray logic
        if broken_hooks > 0:
            # Effective loaded cases already calculated above (original_qty - broken_hooks)
            modal_data['loaded_hooks'] = modal_data['effective_loaded_cases']
            modal_data['empty_hooks'] = 0  # No empty hooks when broken hooks present
            
            # For broken hooks scenario: broken hooks quantity goes to half-filled section
            # Delink table gets effective quantity, half-filled gets broken hooks
            modal_data['half_filled_tray_cases'] = broken_hooks
            modal_data['remaining_cases'] = 0  # All cases are distributed
            modal_data['no_of_cycle'] = 1
            
            logger.info(f"🔧 BROKEN HOOKS SETUP: effective_cases={modal_data['effective_loaded_cases']}, half_filled_cases={broken_hooks}")
        else:
            # No broken hooks - effective loaded cases is the lot qty
            modal_data['remaining_cases'] = 0
            modal_data['half_filled_tray_cases'] = 0

        # Delink Table preparation (existing tray data)
        # Pass _jig_partial_completed so the delink builder can use half_filled_tray_info
        # instead of stale JigLoadTrayId records from the prior main submission.
        # IMPORTANT: Use jig_capacity as the constraint for delink table 
        modal_data['delink_table'] = self._prepare_existing_delink_table(
            lot_id, 
            batch, 
            modal_data['effective_loaded_cases'], 
            tray_capacity, 
            broken_hooks, 
            modal_data['jig_capacity'],  # Pass jig_capacity as constraint
            half_filled_source=_jig_partial_completed
        )

        # If lot qty >= jig capacity, force empty_hooks to 0 regardless of broken hooks
        if modal_data['loaded_cases_qty'] >= modal_data['jig_capacity']:
            modal_data['empty_hooks'] = 0

        # Model Images preparation with validation
        modal_data['model_images'] = self._prepare_model_images(model_master)

        # Add Model button logic with validation
        modal_data['add_model_enabled'] = modal_data['empty_hooks'] > 0
        
        
        # Save button logic: Enable only if empty_hooks == 0
        modal_data['can_save'] = (modal_data['empty_hooks'] == 0)

        # Modal validation rules
        modal_data['modal_validation'] = self._prepare_modal_validation(modal_data)

        # Tray Distribution and Half-Filled Tray Calculation
        # For excess lots (lot_qty > jig_capacity), calculate both delink and excess distributions
        if modal_data['original_lot_qty'] > modal_data['jig_capacity']:
            # Calculate delink distribution (up to jig capacity)
            delink_qty = modal_data['jig_capacity'] - modal_data['broken_buildup_hooks']
            modal_data['tray_distribution'] = self._calculate_split_tray_distribution(
                modal_data['original_lot_qty'],
                delink_qty,
                modal_data['jig_capacity'], 
                modal_data['broken_buildup_hooks'],
                batch
            )
        else:
            # Use effective_loaded_cases which is already reduced by broken hooks
            modal_data['tray_distribution'] = self._calculate_tray_distribution(
                modal_data['effective_loaded_cases'], 
                modal_data['jig_capacity'], 
                modal_data['broken_buildup_hooks'],
                batch
            )

        # ✅ FIX: Ensure tray_distribution is properly structured
        if modal_data['tray_distribution'] is None:
            # Fallback: create basic structure for normal lots
            total_cases = modal_data['effective_loaded_cases']
            modal_data['tray_distribution'] = {
                'current_lot': {
                    'total_cases': total_cases,
                    'lot_id': lot_id,
                    'trays': self._distribute_cases_to_trays(total_cases, tray_capacity) if tray_capacity else []
                },
                'combined_models': [],
                'total_cases': total_cases,
                'delink_qty': total_cases,
                'excess_qty': 0
            }

        # Adjust loaded_cases_qty to reflect only the jig portion (not excess)
        if modal_data['original_lot_qty'] > modal_data['jig_capacity']:
            # For excess lots, loaded_cases_qty should be jig_capacity (what fits in jig)
            modal_data['loaded_cases_qty'] = modal_data['jig_capacity'] 
        else:
            # For normal lots, use the distribution total with safety check
            if modal_data['tray_distribution'] and 'current_lot' in modal_data['tray_distribution'] and modal_data['tray_distribution']['current_lot']:
                modal_data['loaded_cases_qty'] = modal_data['tray_distribution']['current_lot']['total_cases'] + modal_data['broken_buildup_hooks']
            else:
                # Fallback: use effective_loaded_cases directly
                modal_data['loaded_cases_qty'] = modal_data['effective_loaded_cases']

        # UI Configuration for frontend rendering
        modal_data['ui_config'] = self._prepare_ui_configuration(modal_data)

        # Comprehensive calculation logs
        modal_data['logs'] = {
            'batch_id': batch.batch_id if batch else None,
            'lot_id': lot_id,
            'jig_qr_id': jig_qr_id,
            'jig_type': modal_data['jig_type'],
            'jig_capacity': modal_data['jig_capacity'],
            'loaded_cases_qty': modal_data['loaded_cases_qty'],
            'loaded_hooks': modal_data['loaded_hooks'],
            'empty_hooks': modal_data['empty_hooks'],
            'broken_buildup_hooks': modal_data['broken_buildup_hooks'],
            'nickel_bath_type': modal_data['nickel_bath_type'],
            'delink_table': modal_data['delink_table'],
            'model_images': modal_data['model_images'],
            'add_model_enabled': modal_data['add_model_enabled'],
            'can_save': modal_data['can_save'],
            'user': request.user.username,
            'calculation_timestamp': timezone.now().isoformat(),
            'tray_type': modal_data['tray_type'],
            'tray_distribution': modal_data['tray_distribution']
        }

        logger.info(f"🎯 Modal data prepared with {len(modal_data['model_images'])} images, {len(modal_data['delink_table'])} existing trays")
        
        
        # --- Overflow Handling: Lot Qty > Jig Capacity ---
        if modal_data['original_lot_qty'] > modal_data['jig_capacity'] and modal_data['broken_buildup_hooks'] == 0:
            # For excess lots, calculate delink fresh based on full lot qty, not using old trays
            effective_loaded = modal_data['original_lot_qty']
            leftover_cases = 0
            
            # Build delink_table with fresh distribution for full lot qty
            modal_data['delink_table'] = self._prepare_existing_delink_table(lot_id, batch, effective_loaded, tray_capacity, broken_hooks, modal_data['jig_capacity'], force_fresh=True)
            
            # No half-filled tray for excess lots
            modal_data['tray_distribution']['half_filled_lot'] = {
                'total_cases': 0,
                'distribution': None,
                'total_trays': 0
            }
            
            # Update Current Lot distribution to match full lot qty
            delink_distribution = self._distribute_cases_to_trays(effective_loaded, tray_capacity)
            modal_data['tray_distribution']['current_lot'] = {
                'total_cases': effective_loaded,
                'effective_capacity': effective_loaded,
                'broken_hooks': 0,
                'tray_capacity': tray_capacity,
                'distribution': delink_distribution,
                'total_trays': delink_distribution.get('total_trays', 0)
            }
            
            modal_data['open_with_half_filled'] = False
            modal_data['loaded_cases_qty'] = f"0/{effective_loaded}"
            modal_data['excess_message'] = f"Excess lot: {effective_loaded} cases"
        else:
            modal_data['open_with_half_filled'] = False
            # BUG 11 FIX: When broken hooks exist, the display count should only reflect
            # the effective (scannable) cases — NOT the full original lot qty.
            # Showing "0/98" when 5 hooks are broken and only 93 cases can be scanned is
            # misleading. The half-filled tray's 5 cases are tracked separately.
            if modal_data['broken_buildup_hooks'] > 0:
                modal_data['loaded_cases_qty'] = f"0/{modal_data['effective_loaded_cases']}"
            else:
                modal_data['loaded_cases_qty'] = f"0/{modal_data['original_lot_qty']}"
            modal_data['excess_message'] = ""

        return modal_data

    def _prepare_model_images(self, model_master):
        """
        Prepare model images data with proper structure for frontend consumption.
        """
        model_image_data = []
        if model_master and model_master.images.exists():
            for image in model_master.images.all():
                model_image_data.append({
                    'url': image.master_image.url,
                    'model_no': model_master.model_no,
                    'image_id': image.id,
                    'alt_text': f"Model {model_master.model_no} Image"
                })
        return model_image_data
    
    def _prepare_existing_delink_table(self, lot_id, batch, effective_loaded_cases, tray_capacity, broken_hooks, jig_capacity=None, force_fresh=False, half_filled_source=None):
        """
        Prepare delink table data for scanning.
        Logic:
        - Calculate trays needed for JIG CAPACITY ONLY (not full lot)
        - Split trays when they exceed jig capacity limit
        - force_fresh=True (excess lots): always calculate fresh distribution from effective_loaded_cases
        - broken_hooks > 0: distribute using broken-hooks tray distribution
        - No broken hooks: calculate delink trays up to jig capacity, handle partial tray split
        """
        logger = logging.getLogger(__name__)
        delink_table = []

        try:
            # If tray_capacity is missing, do not abort — we can still return existing DB trays
            if not tray_capacity or tray_capacity <= 0:
                tray_capacity = None

            # Use effective_loaded_cases as the authoritative target_qty (do NOT cap by jig_capacity)
            target_qty = effective_loaded_cases
            
            if target_qty <= 0:
                return delink_table

            # --- Excess lots: always use fresh distribution ---
            if force_fresh:
                logger.info(f"🔀 FORCE FRESH DELINK: {lot_id} with {target_qty} cases (jig_capacity={jig_capacity})")
                return self._calculate_delink_trays_with_split(target_qty, tray_capacity)

            # --- Broken hooks path ---
            if broken_hooks > 0:
                effective_tray_data = self._calculate_broken_hooks_tray_distribution(lot_id, target_qty, broken_hooks, batch)
                lot_qty = target_qty + broken_hooks
                total_trays_needed = ceil(lot_qty / tray_capacity) if tray_capacity else 0
                if len(effective_tray_data) >= total_trays_needed:
                    effective_tray_data = effective_tray_data[:-1]  # Exclude last tray for broken hooks
                for tray_data in effective_tray_data:
                    delink_table.append({
                        'tray_id': tray_data['tray_id'],
                        'tray_quantity': tray_data['effective_qty'],
                        'model_bg': tray_data['model_bg'],
                        'original_quantity': tray_data['original_qty'],
                        'excluded_quantity': tray_data['excluded_qty']
                    })
                logger.info(f"📊 BROKEN HOOKS DELINK TABLE: {len(delink_table)} trays")
                return delink_table

            # --- No broken hooks ---

            # Half-filled partial lot: use planned tray distribution from JigCompleted,
            # not the stale JigLoadTrayId records from the prior main submission.
            if half_filled_source and half_filled_source.half_filled_tray_info:
                for i, tray_info in enumerate(half_filled_source.half_filled_tray_info):
                    delink_table.append({
                        'tray_id': tray_info.get('tray_id', ''),
                        'tray_quantity': tray_info.get('cases', 0),
                        'model_bg': self._get_model_bg(i + 1),
                        'original_quantity': tray_info.get('cases', 0),
                        'excluded_quantity': 0,
                    })
                logger.info(f"📦 HALF-FILLED PARTIAL DELINK TABLE: {len(delink_table)} trays from JigCompleted.half_filled_tray_info")
                return delink_table

            existing_trays = list(JigLoadTrayId.objects.filter(lot_id=lot_id, batch_id=batch).order_by('id'))

            if existing_trays:
                # Previously scanned trays exist — return them as-is (DB order).
                # IMPORTANT: Do NOT generate placeholder slots or cap by jig_capacity.
                seen_tray_ids = set()
                cumulative_qty = 0
                for tray in existing_trays:
                    tray_key = (tray.tray_id or '').strip()
                    if not tray_key or tray_key in seen_tray_ids:
                        continue
                    seen_tray_ids.add(tray_key)

                    qty = tray.tray_quantity or 0
                    delink_table.append({
                        'tray_id': tray.tray_id,
                        'tray_quantity': qty,
                        'model_bg': self._get_model_bg(len(delink_table) + 1),
                        'original_quantity': qty,
                        'excluded_quantity': 0,
                    })
                    cumulative_qty += qty

                logger.info(f"📊 EXISTING TRAYS DELINK TABLE: {len(delink_table)} trays for {cumulative_qty} cases (from DB)")
            else:
                # Fresh / partial lot with no prior records — calculate delink trays with split logic
                delink_table = self._calculate_delink_trays_with_split(target_qty, tray_capacity)
                logger.info(f"📊 FRESH DELINK TABLE: {len(delink_table)} trays for {target_qty} cases (tray_capacity={tray_capacity})")

            return delink_table

        except Exception as e:
            logger.error(f"❌ Error in _prepare_existing_delink_table: {str(e)}")
            logger.error(f"Parameters: lot_id={lot_id}, effective_loaded_cases={effective_loaded_cases}, tray_capacity={tray_capacity}, broken_hooks={broken_hooks}, jig_capacity={jig_capacity}")
            return []
    
    
    def _prepare_modal_validation(self, modal_data):
        """
        Prepare validation rules and constraints for modal data.
        """
        # Ensure `loaded_cases_qty` is treated as a numeric value for validation.
        # Some flows set `loaded_cases_qty` to a display string like "0/75";
        # parse the numeric part safely without changing other fields.
        loaded_qty_value = modal_data.get('loaded_cases_qty', 0)
        try:
            if isinstance(loaded_qty_value, str) and '/' in loaded_qty_value:
                # format like "0/75" -> take the right-hand side as total
                loaded_qty_numeric = int(loaded_qty_value.split('/')[-1])
            else:
                loaded_qty_numeric = int(loaded_qty_value)
        except Exception:
            loaded_qty_numeric = 0

        # Fix hooks balance calculation for half-filled tray scenarios
        if modal_data['broken_buildup_hooks'] > 0:
            # When broken hooks present: loaded_hooks should equal effective capacity
            expected_loaded = modal_data['jig_capacity'] - modal_data['broken_buildup_hooks']
            actual_loaded = modal_data['loaded_hooks'] + modal_data['empty_hooks']
            hooks_balance_valid = actual_loaded == expected_loaded
        else:
            # Standard calculation when no broken hooks
            hooks_balance_valid = modal_data['loaded_hooks'] + modal_data['empty_hooks'] == modal_data['jig_capacity']
        
        validation = {
            'jig_capacity_valid': modal_data['jig_capacity'] > 0,
            'loaded_cases_valid': loaded_qty_numeric > 0,
            'hooks_balance_valid': hooks_balance_valid,
            'broken_hooks_valid': modal_data['broken_buildup_hooks'] >= 0,
            'nickel_bath_valid': modal_data['nickel_bath_type'] in ['Bright', 'Satin', 'Matt'],
            'has_model_images': len(modal_data['model_images']) > 0,
            'can_add_model': modal_data['add_model_enabled'],
            'empty_hooks_zero': (modal_data['empty_hooks'] == 0),
            'has_half_filled_cases': modal_data.get('half_filled_tray_cases', 0) > 0,
        }
        
        validation['overall_valid'] = all([
            validation['jig_capacity_valid'],
            validation['broken_hooks_valid'],
            validation['nickel_bath_valid'],
            validation['empty_hooks_zero'],
        ])
        
        if not validation['empty_hooks_zero']:
            validation['empty_hooks_error'] = (
                "Loaded Cases Qty must equal Jig Capacity. Use 'Add Model' to fill empty hooks with relevant tray allocation."
        )
        
        return validation
    
    def _calculate_tray_distribution(self, loaded_cases_qty, jig_capacity, broken_hooks, batch):
        """
        Calculate tray distribution for cases considering broken hooks.
        Logic: Use loaded_cases_qty (which is effective quantity after broken hooks reduction)
        User example: original=98, broken_hooks=5, loaded_cases_qty=93
        Should distribute 93 cases across trays: (9,12,12,12,12,12,12,12)
        """
        # Get tray capacity from batch tray type (STRICT: Always from database)
        tray_capacity = None
        if batch and batch.tray_type:
            tray_type_obj = TrayType.objects.filter(tray_type=batch.tray_type).first()
            if tray_type_obj:
                tray_capacity = tray_type_obj.tray_capacity

        # STRICT: If tray_capacity is not found, raise error (do not fallback to hardcoded value)
        if not tray_capacity:
            raise ValueError(f"Tray capacity not configured for tray type '{getattr(batch, 'tray_type', None)}'. Please configure in admin.")

        print(f"🧮 TRAY DISTRIBUTION CALCULATION:")
        print(f"Original Jig Capacity: {jig_capacity}")
        print(f"Broken Hooks: {broken_hooks}")
        print(f"Effective Cases to Distribute: {loaded_cases_qty}")
        print(f"Tray Capacity: {tray_capacity}")
        
        # Use the _distribute_cases_to_trays method for proper distribution
        delink_distribution = self._distribute_cases_to_trays(loaded_cases_qty, tray_capacity)
        
        print(f"Delink Distribution: {len(delink_distribution.get('trays', []))} trays")
        for idx, tray in enumerate(delink_distribution.get('trays', [])):
            print(f"  Tray {tray['tray_number']}: {tray['cases']} cases")
        
        # Calculate half-filled tray for broken hooks (if any)
        half_filled_distribution = None
        if broken_hooks > 0:
            half_filled_distribution = {
                'total_cases': broken_hooks,
                'full_trays_count': 0,
                'partial_tray_cases': broken_hooks,
                'total_trays': 1,
                'trays': [{
                    'tray_number': 1,
                    'cases': broken_hooks,
                    'is_full': False,
                    'is_top_tray': True,
                    'scan_required': True
                }]
            }
            print(f"Half-Filled Tray: {broken_hooks} cases (1 tray)")
        
    def _calculate_split_tray_distribution(self, total_lot_qty, delink_qty, jig_capacity, broken_hooks, batch):
        """
        Calculate tray distribution for lots that exceed jig capacity.
        Splits into delink (jig) and excess (pick table) portions.
        
        Args:
            total_lot_qty: Total quantity in the lot (e.g., 220)
            delink_qty: Quantity going into jig (e.g., 98 - broken_hooks) 
            jig_capacity: Maximum jig capacity (e.g., 98)
            broken_hooks: Number of broken hooks
            batch: Batch object for tray capacity lookup
        """
        # Get tray capacity from batch tray type
        tray_capacity = None
        if batch and batch.tray_type:
            tray_type_obj = TrayType.objects.filter(tray_type=batch.tray_type).first()
            if tray_type_obj:
                tray_capacity = tray_type_obj.tray_capacity

        if not tray_capacity:
            raise ValueError(f"Tray capacity not configured for tray type '{getattr(batch, 'tray_type', None)}'")

        print(f"🔄 SPLIT TRAY DISTRIBUTION:")
        print(f"Total Lot Qty: {total_lot_qty}")
        print(f"Jig Capacity: {jig_capacity}")
        print(f"Delink Qty (for jig): {delink_qty}")
        print(f"Excess Qty (remaining): {total_lot_qty - jig_capacity}")
        print(f"Tray Capacity: {tray_capacity}")
        
        # Calculate delink distribution (what goes into jig)
        delink_distribution = self._distribute_cases_to_trays(delink_qty, tray_capacity)
        
        # Calculate excess distribution (what stays in pick table)
        excess_qty = total_lot_qty - jig_capacity
        excess_distribution = self._distribute_cases_to_trays(excess_qty, tray_capacity) if excess_qty > 0 else None
        
        print(f"Delink Distribution: {len(delink_distribution.get('trays', []))} trays for {delink_qty} cases")
        if excess_distribution:
            print(f"Excess Distribution: {len(excess_distribution.get('trays', []))} trays for {excess_qty} cases")
        
        return {
            'current_lot': {
                'total_cases': delink_qty,
                'effective_capacity': jig_capacity,
                'broken_hooks': broken_hooks,
                'tray_capacity': tray_capacity,
                'distribution': delink_distribution,
                'total_trays': delink_distribution.get('total_trays', 0)
            },
            'excess_lot': {
                'total_cases': excess_qty,
                'distribution': excess_distribution,
                'total_trays': excess_distribution.get('total_trays', 0) if excess_distribution else 0
            },
            'half_filled_lot': {
                'total_cases': broken_hooks,
                'distribution': {
                    'total_cases': broken_hooks,
                    'trays': [{
                        'tray_number': 1,
                        'cases': broken_hooks,
                        'is_full': False,
                        'is_top_tray': True,
                        'scan_required': True
                    }]
                } if broken_hooks > 0 else None,
                'total_trays': 1 if broken_hooks > 0 else 0
            },
            'accountability_info': {
                'original_lot_qty': total_lot_qty,
                'jig_capacity': jig_capacity,
                'delink_qty': delink_qty,
                'excess_qty': excess_qty,
                'broken_hooks': broken_hooks,
                'status': 'EXCESS_LOT_SPLIT'
            }
        }
    
    
    
    
    def _calculate_split_tray_distribution(self, total_lot_qty, delink_qty, jig_capacity, broken_hooks, batch):
        """
        Calculate tray distribution for lots that exceed jig capacity.
        Splits into delink (jig) and excess (pick table) portions.
        
        Args:
            total_lot_qty: Total quantity in the lot (e.g., 220)
            delink_qty: Quantity going into jig (e.g., 98 - broken_hooks) 
            jig_capacity: Maximum jig capacity (e.g., 98)
            broken_hooks: Number of broken hooks
            batch: Batch object for tray capacity lookup
        """
        # Get tray capacity from batch tray type
        tray_capacity = None
        if batch and batch.tray_type:
            tray_type_obj = TrayType.objects.filter(tray_type=batch.tray_type).first()
            if tray_type_obj:
                tray_capacity = tray_type_obj.tray_capacity

        if not tray_capacity:
            raise ValueError(f"Tray capacity not configured for tray type '{getattr(batch, 'tray_type', None)}'")

        print(f"🔄 SPLIT TRAY DISTRIBUTION:")
        print(f"Total Lot Qty: {total_lot_qty}")
        print(f"Jig Capacity: {jig_capacity}")
        print(f"Delink Qty (for jig): {delink_qty}")
        print(f"Excess Qty (remaining): {total_lot_qty - jig_capacity}")
        print(f"Tray Capacity: {tray_capacity}")
        
        # Calculate delink distribution (what goes into jig)
        delink_distribution = self._distribute_cases_to_trays(delink_qty, tray_capacity)
        
        # Calculate excess distribution (what stays in pick table)
        excess_qty = total_lot_qty - jig_capacity
        excess_distribution = self._distribute_cases_to_trays(excess_qty, tray_capacity) if excess_qty > 0 else None
        
        print(f"Delink Distribution: {len(delink_distribution.get('trays', []))} trays for {delink_qty} cases")
        if excess_distribution:
            print(f"Excess Distribution: {len(excess_distribution.get('trays', []))} trays for {excess_qty} cases")
        
        return {
            'current_lot': {
                'total_cases': delink_qty,
                'effective_capacity': jig_capacity,
                'broken_hooks': broken_hooks,
                'tray_capacity': tray_capacity,
                'distribution': delink_distribution,
                'total_trays': delink_distribution.get('total_trays', 0)
            },
            'excess_lot': {
                'total_cases': excess_qty,
                'distribution': excess_distribution,
                'total_trays': excess_distribution.get('total_trays', 0) if excess_distribution else 0
            },
            'half_filled_lot': {
                'total_cases': broken_hooks,
                'distribution': {
                    'total_cases': broken_hooks,
                    'trays': [{
                        'tray_number': 1,
                        'cases': broken_hooks,
                        'is_full': False,
                        'is_top_tray': True,
                        'scan_required': True
                    }]
                } if broken_hooks > 0 else None,
                'total_trays': 1 if broken_hooks > 0 else 0
            },
            'accountability_info': {
                'original_lot_qty': total_lot_qty,
                'jig_capacity': jig_capacity,
                'delink_qty': delink_qty,
                'excess_qty': excess_qty,
                'broken_hooks': broken_hooks,
                'status': 'EXCESS_LOT_SPLIT'
            }
        }
    
    
    def _calculate_delink_trays_with_split(self, target_qty, tray_capacity):
        """
        Calculate delink trays for scanning with proper tray split logic.
        This is used for preparing the delink table that represents trays going into the jig.
        """
        delink_table = []
        full_trays = target_qty // tray_capacity
        partial_qty = target_qty % tray_capacity
        tray_quantities = []

        if partial_qty > 0:
            tray_quantities.append(partial_qty)

        tray_quantities.extend([tray_capacity] * full_trays)

        for tray_idx, tray_qty in enumerate(tray_quantities):
            delink_table.append({
                'tray_id': '',  # Empty for scanning
                'tray_quantity': tray_qty,
                'model_bg': self._get_model_bg(tray_idx + 1),
                'original_quantity': tray_qty,
                'excluded_quantity': 0,
                'is_top_tray': tray_idx == 0 and tray_qty < tray_capacity,
                'scan_required': True  # All delink trays need scanning
            })

        return delink_table
    
    def _distribute_cases_to_trays(self, total_cases, tray_capacity):
        """
        Distribute cases into trays based on tray capacity.
        Returns distribution with full trays and partial tray details.
        For leftover lots, put partial tray first for scanning.
        """
        if total_cases <= 0 or not tray_capacity or tray_capacity <= 0:
            return {
                'total_cases': 0,
                'full_trays_count': 0,
                'partial_tray_cases': 0,
                'total_trays': 0,
                'trays': []
            }
            
        full_trays = total_cases // tray_capacity
        partial_cases = total_cases % tray_capacity
        
        trays = []
        
        # For leftover lots (when there are partial cases), put partial tray first
        if partial_cases > 0:
            trays.append({
                'tray_number': 1,
                'cases': partial_cases,
                'is_full': False,
                'is_top_tray': True,  # Mark as top tray for scanning
                'scan_required': True
            })
            # Then add full trays
            for i in range(full_trays):
                trays.append({
                    'tray_number': i + 2,  # Start from 2 since partial is 1
                    'cases': tray_capacity,
                    'is_full': True,
                    'scan_required': False
                })
        else:
            # For full trays only, add them in order
            for i in range(full_trays):
                trays.append({
                    'tray_number': i + 1,
                    'cases': tray_capacity,
                    'is_full': True,
                    'scan_required': False
                })
        
        return {
            'total_cases': total_cases,
            'full_trays_count': full_trays,
            'partial_tray_cases': partial_cases if partial_cases > 0 else 0,
            'total_trays': len(trays),
            'trays': trays
        }

    def _distribute_half_filled_trays(self, half_filled_cases, tray_capacity):
        """
        Distribute half-filled cases into trays with scan requirements.
        Partial trays require scanning, full trays can auto-assign existing tray IDs.
        For excess lots: put partial tray first (Scan Required), then full trays (Auto Assigned).
        Example for 22 cases (capacity 12): Tray 1 (10 cases, Scan), Tray 2 (12 cases, Auto).
        """
        if half_filled_cases <= 0 or not tray_capacity:
            return None
            
        full_trays = half_filled_cases // tray_capacity
        remainder_cases = half_filled_cases % tray_capacity
        
        trays = []
        tray_number = 1
        
        # Add partial tray FIRST (requires scanning, top tray for half-filled section)
        if remainder_cases > 0:
            trays.append({
                'tray_number': tray_number,
                'cases': remainder_cases,
                'is_full': False,
                'scan_required': True,
                'tray_type': 'partial',
                'placeholder': f'Scan Tray ID ({remainder_cases} pcs)'
            })
            tray_number += 1
            
        # Add full trays (auto-assignment from existing trays)
        for i in range(full_trays):
            trays.append({
                'tray_number': tray_number,
                'cases': tray_capacity,
                'is_full': True,
                'scan_required': False,
                'tray_type': 'full',
                'info': 'Auto Assigned'
            })
            tray_number += 1
        
        return {
            'total_cases': half_filled_cases,
            'full_trays_count': full_trays,
            'partial_tray_cases': remainder_cases,
            'total_trays': len(trays),
            'trays': trays,
            'scan_required_trays': len([t for t in trays if t.get('scan_required', False)])
        }

    def _generate_accountability_info(self, original_lot_qty, effective_loaded, leftover_cases, broken_hooks):
        """
        Generate accountability information text for user understanding.
        """
        info_lines = []
        
        if broken_hooks > 0:
            info_lines.append(f"Original Lot Qty: {original_lot_qty} cases")
            info_lines.append(f"Broken Hooks: {broken_hooks} (positions unavailable)")
            info_lines.append(f"Current Cycle: {effective_loaded} cases loaded")
            
            if leftover_cases > 0:
                info_lines.append(f"Next Cycle: {leftover_cases} cases remaining")
                info_lines.append("All cases accounted for - no quantities missing")
            else:
                info_lines.append("All cases loaded in current cycle")
        else:
            info_lines.append(f"Total cases: {original_lot_qty} - All loaded in current cycle")
            info_lines.append("No broken hooks - full capacity utilized")
        
        return " • ".join(info_lines)

    def _prepare_ui_configuration(self, modal_data):
        """
        Prepare UI configuration for optimal frontend rendering.
        """
        return {
            'show_model_images': len(modal_data['model_images']) > 0,
            'enable_add_model': modal_data['add_model_enabled'],
            'show_cycle_info': modal_data['no_of_cycle'] > 1,
            'highlight_empty_hooks': modal_data['empty_hooks'] > 0,
            'show_broken_hooks_warning': modal_data['broken_buildup_hooks'] > 0,
            'readonly_fields': ['empty_hooks', 'loaded_cases_qty', 'jig_capacity'],
            'required_fields': ['jig_id', 'nickel_bath_type'],
            'validation_enabled': True
        }

    def _calculate_broken_hooks_tray_distribution(self, lot_id, effective_qty, broken_hooks, batch):
        """
        Calculate how to distribute effective quantity across existing trays when broken hooks are present.
        This updates tray records with broken hooks calculation fields.
        
        User's calculation example:
        - Original lot: 98 cases across 9 trays (JB-A00020=2, JB-A00021=12, ..., JB-A00028=12)
        - Broken hooks: 39 cases  
        - Effective qty: 59 cases
        - Expected distribution: JB-A00020=11, JB-A00021=12, JB-A00022=12, JB-A00023=12, JB-A00024=12
        
        Logic: First tray gets remainder, subsequent trays get full capacity up to effective qty
        """
        logger = logging.getLogger(__name__)
        existing_trays = JigLoadTrayId.objects.filter(lot_id=lot_id, batch_id=batch).order_by('tray_id')
        
        if not existing_trays.exists():
            logger.warning(f"⚠️ No existing trays found for lot {lot_id} and batch {batch.batch_id if batch else 'None'}")
            return []
        
        logger.info(f"🔧 BROKEN HOOKS CALCULATION: lot={lot_id}, effective_qty={effective_qty}, broken_hooks={broken_hooks}")
        
        # Get tray capacity to determine proper distribution
        tray_capacity = 12  # Default fallback
        if existing_trays.exists():
            first_tray = existing_trays.first()
            if first_tray.tray_capacity:
                tray_capacity = first_tray.tray_capacity
            elif first_tray.batch_id and first_tray.batch_id.tray_capacity:
                tray_capacity = first_tray.batch_id.tray_capacity
        
        # Calculate how many full trays we need for effective qty
        full_trays_needed = effective_qty // tray_capacity
        remainder_qty = effective_qty % tray_capacity
        
        logger.info(f"📊 Distribution calculation: effective_qty={effective_qty}, tray_capacity={tray_capacity}, full_trays_needed={full_trays_needed}, remainder_qty={remainder_qty}")
        
        # Reset all trays first
        for tray in existing_trays:
            tray.broken_hooks_effective_tray = False
            tray.broken_hooks_excluded_qty = 0
            tray.effective_tray_qty = tray.tray_quantity  # Default to original quantity
            tray.save()
        
        # Distribute effective quantity: remainder tray first (if any), then full trays
        remaining_effective_qty = effective_qty
        effective_trays = []
        tray_index = 0
        
        # Handle remainder first (partial tray) - user's example: JB-A00020 gets 11 cases
        if remainder_qty > 0 and tray_index < existing_trays.count():
            tray = existing_trays[tray_index]
            tray_effective_qty = remainder_qty
            tray_excluded_qty = tray.tray_quantity - tray_effective_qty
            
            # Update tray with broken hooks fields
            tray.broken_hooks_effective_tray = True
            tray.broken_hooks_excluded_qty = tray_excluded_qty
            tray.effective_tray_qty = tray_effective_qty
            tray.save()
            
            effective_trays.append({
                'tray_id': tray.tray_id,
                'effective_qty': tray_effective_qty,
                'original_qty': tray.tray_quantity,
                'excluded_qty': tray_excluded_qty,
                'model_bg': self._get_model_bg(tray_index + 1)
            })
            
            remaining_effective_qty -= tray_effective_qty
            tray_index += 1
            logger.info(f"  Remainder tray {tray.tray_id}: effective={tray_effective_qty}, excluded={tray_excluded_qty}")
        
        # Handle full trays - user's example: JB-A00021, JB-A00022, JB-A00023, JB-A00024 each get 12 cases
        for i in range(full_trays_needed):
            if tray_index >= existing_trays.count():
                break
                
            tray = existing_trays[tray_index]
            tray_effective_qty = tray_capacity
            tray_excluded_qty = tray.tray_quantity - tray_effective_qty
            
            # Update tray with broken hooks fields
            tray.broken_hooks_effective_tray = True
            tray.broken_hooks_excluded_qty = tray_excluded_qty
            tray.effective_tray_qty = tray_effective_qty
            tray.save()
            
            effective_trays.append({
                'tray_id': tray.tray_id,
                'effective_qty': tray_effective_qty,
                'original_qty': tray.tray_quantity,
                'excluded_qty': tray_excluded_qty,
                'model_bg': self._get_model_bg(tray_index + 1)
            })
            
            remaining_effective_qty -= tray_effective_qty
            tray_index += 1
            logger.info(f"  Full tray {tray.tray_id}: effective={tray_effective_qty}, excluded={tray_excluded_qty}")
        
        # Mark remaining trays as excluded (not part of effective distribution)
        for i in range(tray_index, existing_trays.count()):
            tray = existing_trays[i]
            tray.broken_hooks_effective_tray = False
            tray.broken_hooks_excluded_qty = tray.tray_quantity
            tray.effective_tray_qty = 0
            tray.save()
            logger.info(f"  Excluded tray {tray.tray_id}: all {tray.tray_quantity} cases excluded")
        
        logger.info(f"✅ Broken hooks distribution complete: {len(effective_trays)} effective trays, remaining_qty={remaining_effective_qty}")
        return effective_trays
    
    
    
    def _get_model_bg(self, idx):
        return f"model-bg-{(idx - 1) % 5 + 1}"

# Tray ID Validation - Delink Table View
@api_view(['GET'])
def validate_tray_id(request):
    tray_id = request.GET.get('tray_id')
    batch_id = request.GET.get('batch_id')
    lot_id = request.GET.get('lot_id')  # <-- Add this line to get lot_id from request
    if not tray_id or not batch_id or not lot_id:
        return Response({'valid': False, 'message': 'Tray ID, Batch ID, and Lot ID required'}, status=400)
    # Only accept tray_id that belongs to this lot and batch
    tray = JigLoadTrayId.objects.filter(
        tray_id=tray_id,
        batch_id__batch_id=batch_id,
        lot_id=lot_id
    ).first()
    if tray:
        tray_quantity = tray.tray_quantity or tray.tray_capacity or 0
        return Response({'valid': True, 'tray_quantity': tray_quantity})
    else:
        # Do NOT allow new trays for delink table (only for half-filled section, handled elsewhere)
        return Response({'valid': False, 'message': 'Invalid Tray ID.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def scan_tray_lookup(request):
    """
    Validate a scanned tray id for Jig Loading pick table scan workflow.
    Returns row identity and original table position for temporary reordering.
    """
    tray_id = (request.GET.get('tray_id') or '').strip()
    if not tray_id:
        return Response({'exists': False}, status=status.HTTP_400_BAD_REQUEST)

    tray = JigLoadTrayId.objects.filter(tray_id=tray_id).select_related('batch_id').first()
    if not tray or not tray.batch_id:
        return Response({'exists': False}, status=status.HTTP_200_OK)

    # Build the same base lot pool used by JigView so original_position matches pick-table order.
    total_stock_qs = (
        TotalStockModel.objects.filter(brass_audit_accptance=True, Jig_Load_completed=False)
        | TotalStockModel.objects.filter(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False, Jig_Load_completed=False)
        | TotalStockModel.objects.filter(brass_audit_rejection=True, Jig_Load_completed=False)
        | TotalStockModel.objects.filter(jig_draft=True, Jig_Load_completed=False)
    )
    completed_with_half_filled = JigCompleted.objects.filter(
        half_filled_tray_info__isnull=False
    ).exclude(
        half_filled_tray_info=[]
    ).values_list('lot_id', flat=True)
    if completed_with_half_filled:
        total_stock_qs |= TotalStockModel.objects.filter(
            lot_id__in=completed_with_half_filled,
            Jig_Load_completed=True
        )

    order_rows = []
    for stock in total_stock_qs:
        order_rows.append({
            'batch_id': stock.batch_id.batch_id if stock.batch_id else '',
            'lot_id': stock.lot_id,
            'last_updated': stock.brass_audit_last_process_date_time,
            'jig_hold_lot': bool(getattr(stock, 'jig_hold_lot', False)),
            'released_flag': bool(getattr(stock, 'released_flag', False)),
        })
    order_rows.sort(key=lambda x: x['last_updated'] or datetime.min, reverse=True)

    match_idx = next(
        (
            idx for idx, row in enumerate(order_rows)
            if row['batch_id'] == tray.batch_id.batch_id and row['lot_id'] == tray.lot_id
        ),
        None
    )

    audit_enabled = True
    if match_idx is not None:
        matched_row = order_rows[match_idx]
        audit_enabled = not (matched_row['jig_hold_lot'] or matched_row['released_flag'])

    return Response({
        'tray_id': tray.tray_id,
        'tray_qty': tray.tray_quantity or tray.tray_capacity or 0,
        'original_position': (match_idx + 1) if match_idx is not None else None,
        'batch_id': tray.batch_id.batch_id,
        'lot_id': tray.lot_id,
        'exists': True,
        'audit_button_enabled': audit_enabled,
    }, status=status.HTTP_200_OK)

# Add Jig Btn - Delink Table View


class DelinkTableAPIView(APIView):
    """
    Returns tray rows for Delink Table based on tray type, lot qty, and jig capacity.
    Calculates number of trays needed for scanning based on loaded cases qty and tray capacity.
    """
    def get(self, request, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        
        batch_id = request.GET.get('batch_id')
        lot_id = request.GET.get('lot_id')
        jig_qr_id = request.GET.get('jig_qr_id', None)
        broken_hooks = int(request.GET.get('broken_hooks', 0))

        if not batch_id or not lot_id:
            logger.info("❌ Missing parameters: batch_id or lot_id")
            return Response({'error': 'batch_id and lot_id required'}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"🔍 Processing delink table for batch_id: {batch_id}, lot_id: {lot_id}, broken_hooks: {broken_hooks}")

        # Get TotalStockModel for loaded cases qty
        try:
            stock = TotalStockModel.objects.get(lot_id=lot_id)
            loaded_cases_qty = stock.total_stock or 0
            logger.info(f"📊 Loaded cases qty from TotalStockModel: {loaded_cases_qty}")
        except TotalStockModel.DoesNotExist:
            logger.error(f"❌ TotalStockModel not found for lot_id: {lot_id}")
            return Response({'error': 'Stock record not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get batch/model info for tray type and jig capacity
        try:
            batch = ModelMasterCreation.objects.get(batch_id=batch_id)
            model_master = batch.model_stock_no
            logger.info(f"📦 Found batch: {batch_id}, model: {model_master}")
        except ModelMasterCreation.DoesNotExist:
            logger.error(f"❌ ModelMasterCreation not found for batch_id: {batch_id}")
            return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get tray type and capacity
        tray_type_name = batch.tray_type or "Normal"  # Default to Normal if not set
        try:
            tray_type_obj = TrayType.objects.get(tray_type=tray_type_name)
            tray_capacity = tray_type_obj.tray_capacity
            logger.info(f"🗂️ Tray type: {tray_type_name}, capacity: {tray_capacity}")
        except TrayType.DoesNotExist:
            logger.warning(f"⚠️ TrayType '{tray_type_name}' not found, trying fallback options")
            fallback_types = ["Normal", "Jumbo"]
            tray_capacity = None
            for fallback_type in fallback_types:
                try:
                    fallback_tray_obj = TrayType.objects.get(tray_type=fallback_type)
                    tray_capacity = fallback_tray_obj.tray_capacity
                    logger.warning(f"⚠️ Using fallback TrayType '{fallback_type}' with capacity: {tray_capacity}")
                    break
                except TrayType.DoesNotExist:
                    continue
            if tray_capacity is None:
                logger.error(f"❌ No TrayType configurations found in database")
                return Response({'error': 'Tray type configuration missing. Please configure tray types in admin.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Get jig capacity from JigLoadingMaster
        jig_capacity = 0
        if model_master:
            try:
                jig_master = JigLoadingMaster.objects.get(model_stock_no=model_master)
                jig_capacity = jig_master.jig_capacity
                logger.info(f"🔧 Jig capacity from JigLoadingMaster: {jig_capacity}")
            except JigLoadingMaster.DoesNotExist:
                logger.warning(f"⚠️ JigLoadingMaster not found for model: {model_master}")
                jig_capacity = loaded_cases_qty  # Use loaded cases qty as fallback

        # Calculate effective capacity considering broken hooks
        effective_capacity = max(0, jig_capacity - broken_hooks) if jig_capacity > 0 else loaded_cases_qty
        actual_qty = min(loaded_cases_qty, effective_capacity)
        logger.info(f"🧮 Calculation: loaded_cases_qty={loaded_cases_qty}, jig_capacity={jig_capacity}, broken_hooks={broken_hooks}, effective_capacity={effective_capacity}, actual_qty={actual_qty}")

        # Check for existing tray IDs for this lot
        existing_trays = JigLoadTrayId.objects.filter(
            lot_id=lot_id, 
            batch_id=batch
        ).order_by('date').only('tray_id', 'tray_quantity')  # Optimization

        # --- NEW LOGIC: Conditional tray distribution based on broken_hooks ---
        half_filled_tray_data = None
        rows = []
        if tray_capacity > 0 and actual_qty > 0:
            if broken_hooks == 0:
                # When broken_hooks == 0, show all trays (full and partial) in delink table
                num_full_trays = actual_qty // tray_capacity
                remainder_qty = actual_qty % tray_capacity
                total_trays = num_full_trays + (1 if remainder_qty > 0 else 0)
                
                for i in range(total_trays):
                    s_no = i + 1
                    if i < num_full_trays:
                        tray_qty = tray_capacity
                    else:
                        tray_qty = remainder_qty
                    
                    # All trays are for scanning - empty inputs
                    tray_id = ""
                    tray_quantity = tray_qty
                    placeholder = "Scan Tray Id"
                    readonly = False
                    
                    rows.append({
                        's_no': s_no,
                        'tray_id': tray_id,
                        'tray_quantity': tray_quantity,
                        'placeholder': placeholder,
                        'readonly': readonly
                    })
                
                num_trays = total_trays
            else:
                # When broken_hooks > 0, show all trays (full and partial) in delink table
                num_full_trays = actual_qty // tray_capacity
                remainder_qty = actual_qty % tray_capacity
                total_trays = num_full_trays + (1 if remainder_qty > 0 else 0)
                
                for i in range(total_trays):
                    s_no = i + 1
                    if i < num_full_trays:
                        tray_qty = tray_capacity
                    else:
                        tray_qty = remainder_qty
                    
                    # All trays are for scanning - empty inputs
                    tray_id = ""
                    tray_quantity = tray_qty
                    placeholder = "Scan Tray Id"
                    readonly = False
                    
                    rows.append({
                        's_no': s_no,
                        'tray_id': tray_id,
                        'tray_quantity': tray_quantity,
                        'placeholder': placeholder,
                        'readonly': readonly
                    })
                
                # Half-filled tray for broken hooks
                if broken_hooks > 0:
                    half_filled_cases = broken_hooks
                    half_filled_num_trays = (half_filled_cases + tray_capacity - 1) // tray_capacity  # ceil division
                    half_filled_tray_data = {
                        'tray_count': half_filled_num_trays,
                        'message': f'Scan half filled tray ID with {half_filled_cases} pieces'
                    }
                
                num_trays = total_trays
        else:
            num_trays = 0

        logger.info(f"✅ Generated {len(rows)} delink table rows")
        logger.info(f"📊 Final calculation summary - tray_type: {tray_type_name}, tray_capacity: {tray_capacity}, actual_qty: {actual_qty}, num_full_trays: {num_full_trays}, half_filled_tray: {half_filled_tray_data}")

        return Response({
            'tray_rows': rows,
            'tray_type': tray_type_name,
            'tray_capacity': tray_capacity,
            'actual_qty': actual_qty,
            'loaded_cases_qty': loaded_cases_qty,
            'jig_capacity': jig_capacity,
            'effective_capacity': effective_capacity,
            'broken_hooks': broken_hooks,
            'num_trays': num_trays,
            'half_filled_tray_data': half_filled_tray_data,
            'calculation_details': {
                'formula': f'{actual_qty} pieces = {num_full_trays} full trays + {remainder_qty if remainder_qty > 0 else 0} remainder',
                'constraint': f'effective_capacity = jig_capacity({jig_capacity}) - broken_hooks({broken_hooks}) = {effective_capacity}',
                'tray_distribution': [row['tray_quantity'] for row in rows],
                'half_filled_info': half_filled_tray_data
            }
        }, status=status.HTTP_200_OK)



# Manual Draft - Save/Update View
class JigLoadingManualDraftAPIView(APIView):
    def post(self, request, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        
        batch_id = request.data.get('batch_id')
        lot_id = request.data.get('lot_id')
        draft_data = request.data.get('draft_data')
        user = request.user
        
        logger.info(f"🔍 Draft request: user={user.username}, batch_id={batch_id}, lot_id={lot_id}")

        if not batch_id or not lot_id or not draft_data:
            logger.error(f"❌ Missing required fields: batch_id={batch_id}, lot_id={lot_id}, draft_data present={bool(draft_data)}")
            return Response({'error': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)

        # Get stock to calculate original_lot_qty
        try:
            stock = TotalStockModel.objects.get(batch_id__batch_id=batch_id, lot_id=lot_id)
            original_lot_qty = stock.total_stock
        except TotalStockModel.DoesNotExist:
            logger.error(f"❌ No TotalStockModel for lot_id={lot_id}, batch_id={batch_id}")
            return Response({'error': 'Stock record not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get jig capacity
        jig_capacity = 0
        jig_id = draft_data.get('jig_id')
        plating_stock_num = ''
        if jig_id:
            try:
                jig = Jig.objects.get(jig_qr_id=jig_id)
                # Get jig capacity from JigLoadingMaster via batch
                batch = ModelMasterCreation.objects.get(batch_id=batch_id)
                jig_master = JigLoadingMaster.objects.filter(model_stock_no=batch.model_stock_no).first()
                if jig_master:
                    jig_capacity = jig_master.jig_capacity
                # Get plating stock number
                plating_stock_num = batch.plating_stk_no if batch.plating_stk_no else (batch.model_stock_no.plating_stk_no if batch.model_stock_no else '')
            except (Jig.DoesNotExist, ModelMasterCreation.DoesNotExist):
                pass

        # Calculate updated_lot_qty
        broken_hooks = int(draft_data.get('broken_buildup_hooks', 0))
        updated_lot_qty = original_lot_qty - broken_hooks if broken_hooks > 0 else original_lot_qty

        # Separate trays into delink, partial, half_filled
        trays = draft_data.get('trays', [])
        delink_tray_info = []
        partial_tray_info = []
        half_filled_tray_info = []

        for tray in trays:
            row_index = tray.get('row_index', '')
            tray_id = tray.get('tray_id', '')
            tray_qty = int(tray.get('tray_qty', 0))
            if row_index == 'half-filled' or str(row_index).startswith('half_'):
                half_filled_tray_info.append({'tray_id': tray_id, 'cases': tray_qty})
            else:
                delink_tray_info.append({'tray_id': tray_id, 'cases': tray_qty})

        # Update draft_data with calculated fields
        draft_data.update({
            'original_lot_qty': original_lot_qty,
            'updated_lot_qty': updated_lot_qty,
            'delink_tray_info': delink_tray_info,
            'partial_tray_info': partial_tray_info,
            'half_filled_tray_info': half_filled_tray_info,
            'tray_distribution': {'delink': delink_tray_info, 'partial': partial_tray_info, 'half_filled': half_filled_tray_info},
            'broken_hooks': broken_hooks,
            'jig_capacity': jig_capacity,
        })

        # Calculate totals
        delink_tray_qty = updated_lot_qty
        delink_tray_count = len(delink_tray_info)
        half_filled_tray_qty = sum(t['cases'] for t in half_filled_tray_info)
        loaded_cases_qty = 0  # No trays scanned yet

        # Calculate is_multi_model
        combined_lot_ids = draft_data.get('combined_lot_ids', [])
        is_multi_model = len(combined_lot_ids) > 1

        # Ensure all DB updates commit together so the subsequent GET sees the updated state
        try:
            with transaction.atomic():
                obj, created = JigLoadingManualDraft.objects.update_or_create(
                    batch_id=batch_id,
                    lot_id=lot_id,
                    user=user,
                    defaults={
                        'draft_data': draft_data,
                        'original_lot_qty': original_lot_qty,
                        'updated_lot_qty': updated_lot_qty,
                        'jig_id': jig_id,
                        'delink_tray_info': delink_tray_info,
                        'delink_tray_qty': delink_tray_qty,
                        'delink_tray_count': delink_tray_count,
                        'half_filled_tray_info': half_filled_tray_info,
                        'half_filled_tray_qty': half_filled_tray_qty,
                        'jig_capacity': jig_capacity,
                        'broken_hooks': broken_hooks,
                        'loaded_cases_qty': loaded_cases_qty,
                        'plating_stock_num': plating_stock_num,
                        'is_multi_model': is_multi_model,
                    }
                )

                # --- Update Jig table with draft info ---
                jig_id = draft_data.get('jig_id')
                if jig_id:
                    jig_obj, _ = Jig.objects.get_or_create(jig_qr_id=jig_id)
                    jig_obj.drafted = True
                    jig_obj.current_user = user
                    jig_obj.locked_at = timezone.now()
                    jig_obj.batch_id = batch_id
                    jig_obj.lot_id = lot_id
                    jig_obj.save()
                    logger.info(f"💾 Jig {jig_id} marked as drafted for batch {batch_id} by {user.username}")

                    # Update TotalStockModel to mark lot as drafted so UI shows "Draft" status
                    stock.jig_draft = True
                    stock.save(update_fields=['jig_draft'])
                    logger.info(f"💾 TotalStockModel.jig_draft set to True for lot_id={lot_id}, batch_id={batch_id}")

                    # Update combined lots to mark as drafted for "Partial Draft" status
                    for combined_lot_id in combined_lot_ids:
                        try:
                            combined_stock = TotalStockModel.objects.get(lot_id=combined_lot_id)
                            combined_stock.jig_draft = True
                            combined_stock.save(update_fields=['jig_draft'])
                            logger.info(f"💾 TotalStockModel.jig_draft set to True for combined lot_id={combined_lot_id}")
                        except TotalStockModel.DoesNotExist:
                            logger.warning(f"Combined lot {combined_lot_id} not found in TotalStockModel")
        except Exception:
            logger.exception(f"Failed to save draft or update jig/stock for lot_id={lot_id}, batch_id={batch_id}")
            return Response({'success': False, 'message': 'Failed to save draft'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # --- Draft should NOT split lots - only save form data ---
        logger.info(f"💾 Draft saved without lot splitting - form data saved for later submission")

        logger.info(f"✅ Draft saved successfully for batch_id={batch_id}, lot_id={lot_id}")
        return Response({'success': True, 'created': created, 'updated_at': obj.updated_at})

# Manual Draft - Retrieve View
class JigLoadingManualDraftFetchAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        batch_id = request.GET.get('batch_id')
        lot_id = request.GET.get('lot_id')
        user = request.user
        try:
            draft = JigLoadingManualDraft.objects.get(batch_id=batch_id, lot_id=lot_id, user=user)
            return Response({'success': True, 'draft_data': draft.draft_data})
        except JigLoadingManualDraft.DoesNotExist:
            return Response({'success': False, 'draft_data': None})
        


class JigSubmitAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _distribute_cases_to_trays(self, total_cases, tray_capacity):
        """
        Distribute cases into trays based on tray capacity.
        Returns distribution with full trays and partial tray details.
        For leftover lots, put partial tray first for scanning.
        """
        if total_cases <= 0 or not tray_capacity or tray_capacity <= 0:
            return None
            
        full_trays = total_cases // tray_capacity
        partial_cases = total_cases % tray_capacity
        
        trays = []
        
        # For leftover lots (when there are partial cases), put partial tray first
        if partial_cases > 0:
            trays.append({
                'tray_number': 1,
                'cases': partial_cases,
                'is_full': False,
                'is_top_tray': True,  # Mark as top tray for scanning
                'scan_required': True
            })
            # Then add full trays
            for i in range(full_trays):
                trays.append({
                    'tray_number': i + 2,  # Start from 2 since partial is 1
                    'cases': tray_capacity,
                    'is_full': True,
                    'scan_required': False
                })
        else:
            # For full trays only, add them in order
            for i in range(full_trays):
                trays.append({
                    'tray_number': i + 1,
                    'cases': tray_capacity,
                    'is_full': True,
                    'scan_required': False
                })
        
        return {
            'total_cases': total_cases,
            'full_trays_count': full_trays,
            'partial_tray_cases': partial_cases if partial_cases > 0 else 0,
            'total_trays': len(trays),
            'trays': trays
        }

    def post(self, request, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        
        data = request.data
        batch_id = data.get('batch_id')
        lot_id = data.get('lot_id')
        jig_qr_id = data.get('jig_qr_id')
        user = request.user
        
        # Initialize variables to prevent scope issues (moved to beginning)
        partial_lot_id = None
        effective_lot_qty = None
        
        # Handle combined lot IDs from Add Model functionality
        combined_lot_ids_raw = data.get('combined_lot_ids', '[]')
        if isinstance(combined_lot_ids_raw, (list, tuple)):
            combined_lot_ids = list(combined_lot_ids_raw)
        elif isinstance(combined_lot_ids_raw, str):
            try:
                combined_lot_ids = json.loads(combined_lot_ids_raw)
            except Exception:
                combined_lot_ids = []
        else:
            combined_lot_ids = []
        is_multi_model = len(combined_lot_ids) > 1
        
        logger.info(f"🚀 SUBMIT REQUEST: batch_id={batch_id}, lot_id={lot_id}, jig_qr_id={jig_qr_id}, user={user.username}")
        if combined_lot_ids:
            logger.info(f"🔀 MULTI-MODEL: Combined lot IDs: {combined_lot_ids}")

        # Basic validation
        if not batch_id or not lot_id or not jig_qr_id:
            logger.error(f"❌ Missing required fields: batch_id={batch_id}, lot_id={lot_id}, jig_qr_id={jig_qr_id}")
            return Response({'success': False, 'message': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Convert any potential string numbers to integers early
            try:
                # Handle broken_buildup_hooks from request data - ensure it's an integer
                raw_broken_hooks = data.get('broken_buildup_hooks', 0)
                if isinstance(raw_broken_hooks, str):
                    raw_broken_hooks = int(raw_broken_hooks) if raw_broken_hooks.strip() else 0
                logger.info(f"📊 Raw broken hooks from request: {raw_broken_hooks} (type: {type(raw_broken_hooks)})")
                
                # Handle jig_capacity from request data
                raw_jig_capacity = data.get('jig_capacity', 0)
                if isinstance(raw_jig_capacity, str):
                    raw_jig_capacity = int(raw_jig_capacity) if raw_jig_capacity.strip() else 0
                logger.info(f"📊 Raw jig capacity from request: {raw_jig_capacity} (type: {type(raw_jig_capacity)})")
                
            except (ValueError, TypeError) as e:
                logger.error(f"❌ Type conversion error: {e}")
                return Response({'success': False, 'message': 'Invalid numeric data in request'}, status=status.HTTP_400_BAD_REQUEST)

            # Get related objects with specific error handling FIRST
            try:
                batch = ModelMasterCreation.objects.get(batch_id=batch_id)
            except ModelMasterCreation.DoesNotExist:
                return Response({'success': False, 'message': 'Batch not found'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                stock = TotalStockModel.objects.get(batch_id=batch, lot_id=lot_id)
            except TotalStockModel.DoesNotExist:
                return Response({'success': False, 'message': 'Stock record not found'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                jig = Jig.objects.get(jig_qr_id=jig_qr_id)
            except Jig.DoesNotExist:
                return Response({'success': False, 'message': 'Jig not found'}, status=status.HTTP_400_BAD_REQUEST)

            # Check if jig is locked by user
            if jig.current_user is not None and jig.current_user != user:
                return Response({'success': False, 'message': 'Jig is locked by another user'}, status=status.HTTP_403_FORBIDDEN)

            # Get draft data after we have stock object
            try:
                draft = JigLoadingManualDraft.objects.get(batch_id=batch_id, lot_id=lot_id, user=user)
                draft_data = draft.draft_data
                original_lot_qty = int(draft_data.get('original_lot_qty', stock.total_stock))
                updated_lot_qty = int(draft_data.get('updated_lot_qty', stock.total_stock))
                jig_capacity = int(draft_data.get('jig_capacity', 0))
                broken_hooks = int(draft_data.get('broken_hooks', 0))
                delink_tray_info = list(data.get('delink_tray_info', []))  # copy – prevent in-place mutation from affecting _handle_excess_lot_submission
                partial_tray_info = draft_data.get('partial_tray_info', [])
                half_filled_tray_info = data.get('half_filled_tray_info', [])
            except JigLoadingManualDraft.DoesNotExist:
                # Fallback to old logic using pre-converted values
                original_lot_qty = stock.total_stock
                updated_lot_qty = stock.total_stock
                jig_capacity = raw_jig_capacity
                broken_hooks = raw_broken_hooks
                delink_tray_info = list(data.get('delink_tray_info', []))  # copy – prevent in-place mutation from affecting _handle_excess_lot_submission
                partial_tray_info = []
                half_filled_tray_info = data.get('half_filled_tray_info', [])
                draft = None
            
            # Final type safety check
            original_lot_qty = int(original_lot_qty)
            updated_lot_qty = int(updated_lot_qty) 
            jig_capacity = int(jig_capacity)
            broken_hooks = int(broken_hooks)
            
            logger.info(f"📊 Final values: original_lot_qty={original_lot_qty}, jig_capacity={jig_capacity}, broken_hooks={broken_hooks}")
            logger.info(f"📊 Types: original_lot_qty={type(original_lot_qty)}, jig_capacity={type(jig_capacity)}, broken_hooks={type(broken_hooks)}")

            # Get tray capacity from batch tray type
            tray_capacity = None
            if batch and batch.tray_type:
                tray_type_obj = TrayType.objects.filter(tray_type=batch.tray_type).first()
                if tray_type_obj:
                    tray_capacity = int(tray_type_obj.tray_capacity)

            # STRICT: If tray_capacity is not found, raise error
            if not tray_capacity:
                return Response({'success': False, 'message': f"Tray capacity not configured for tray type '{getattr(batch, 'tray_type', None)}'. Please configure in admin."}, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f"📊 Tray capacity: {tray_capacity} (type: {type(tray_capacity)})")

            # Compute total combined qty for multi-model excess detection
            total_combined_qty = original_lot_qty
            if is_multi_model and combined_lot_ids:
                for cid in combined_lot_ids:
                    if cid != lot_id:
                        cstock = TotalStockModel.objects.filter(lot_id=cid).first()
                        if cstock:
                            total_combined_qty += cstock.total_stock
                logger.info(f"📊 Multi-model total_combined_qty: {total_combined_qty} (primary={original_lot_qty}, added={total_combined_qty - original_lot_qty})")

            # Move partial tray from delink to half_filled if original_lot_qty > jig_capacity
            if original_lot_qty > jig_capacity:
                partial_tray = None
                for tray in delink_tray_info:
                    if tray['cases'] < tray_capacity:
                        partial_tray = tray
                        break
                if partial_tray:
                    half_filled_tray_info.append(partial_tray)
                    delink_tray_info.remove(partial_tray)
                    updated_lot_qty -= partial_tray['cases']
                    logger.info(f"🔄 Moved partial tray {partial_tray} from delink to half_filled")

            # NEW LOGIC: Handle excess lots (lot_qty > jig_capacity) with proper tray splitting
            is_excess_lot_case = False  # Initialize flag
            
            if original_lot_qty > jig_capacity:
                logger.info(f"🚨 EXCESS LOT DETECTED: {original_lot_qty} > {jig_capacity}")
                
                delink_tray_info, excess_tray_info, new_partial_lot_id = self._handle_excess_lot_submission(
                    data, batch, stock, jig_capacity, tray_capacity, user, logger
                )
                
                # Update variables for the rest of the submission logic
                partial_lot_id = new_partial_lot_id
                # ✅ FIX: Don't override half_filled_tray_info with excess_tray_info (which has placeholder TBD IDs)
                # Keep actual tray data from request; mark as excess lot for id assignment
                is_excess_lot_case = True
                
                # Update original stock to reflect only delink portion (account for broken hooks)
                delink_qty = jig_capacity - broken_hooks
                stock.total_stock = delink_qty
                
                logger.info(f"✅ EXCESS LOT SPLIT COMPLETE:")
                logger.info(f"  Delink trays: {len(delink_tray_info)} ({sum(t['cases'] for t in delink_tray_info)} cases)")
                logger.info(f"  Excess trays: {len(excess_tray_info)} ({sum(t['cases'] for t in excess_tray_info)} cases)")
                
                # ✅ FIX: Create TotalStockModel for excess portion
                excess_qty = original_lot_qty - delink_qty
                if excess_qty > 0:
                    new_stock = TotalStockModel.objects.create(
                        batch_id=stock.batch_id,
                        model_stock_no=stock.model_stock_no,
                        version=stock.version,
                        total_stock=excess_qty,
                        polish_finish=stock.polish_finish,
                        plating_color=stock.plating_color,
                        lot_id=partial_lot_id,
                        dp_physical_qty=excess_qty,
                        Jig_Load_completed=False,
                        jig_draft=False,
                        brass_audit_accptance=stock.brass_audit_accptance,
                        brass_audit_few_cases_accptance=stock.brass_audit_few_cases_accptance,
                        brass_audit_rejection=stock.brass_audit_rejection,
                        brass_audit_accepted_qty=excess_qty,
                        brass_audit_onhold_picking=False,
                        last_process_module='Jig Loading',
                        next_process_module='Jig Loading',
                        last_process_date_time=timezone.now(),
                        brass_audit_last_process_date_time=timezone.now(),
                        created_at=timezone.now(),
                    )
                    logger.info(f"✅ Created new pick table entry for excess: lot_id={partial_lot_id}, qty={excess_qty}")
                
            elif original_lot_qty == jig_capacity:
                # ✅ FIXED: Handle broken hooks by creating NEW lot for remaining qty
                if broken_hooks > 0:
                    # When broken hooks reduce capacity, split into two portions:
                    # 1. Effective qty (93) → remains in current lot for jig
                    # 2. Excluded qty (5) → goes to NEW pick table entry with NEW lot_id
                    
                    logger.info(f"🔀 BROKEN HOOKS SPLIT: original_qty={original_lot_qty}, jig_capacity={jig_capacity}, broken_hooks={broken_hooks}")
                    logger.info(f"   → Jig portion: {original_lot_qty - broken_hooks} cases (original lot_id)")
                    logger.info(f"   → Pick table portion: {broken_hooks} cases (NEW lot_id)")
                    
                    existing_trays = list(JigLoadTrayId.objects.filter(lot_id=lot_id, batch_id=batch).order_by('id'))
                    delink_tray_info = []
                    half_filled_tray_info = []
                    
                    if existing_trays:
                        effective_qty = original_lot_qty - broken_hooks
                        total_effective = 0
                        
                        # Distribute trays: some to delink (jig), rest to half_filled (pick table)
                        for tray in existing_trays:
                            if total_effective >= effective_qty:
                                # All remaining cases go to NEW pick table entry
                                half_filled_tray_info.append({'tray_id': tray.tray_id, 'cases': tray.tray_quantity})
                            else:
                                remaining = effective_qty - total_effective
                                effective_for_this = min(remaining, tray.tray_quantity)
                                
                                # Add to delink (jig portion)
                                delink_tray_info.append({'tray_id': tray.tray_id, 'cases': effective_for_this})
                                total_effective += effective_for_this
                                
                                # If this tray is split, remaining goes to half_filled (pick table)
                                excluded_for_this = tray.tray_quantity - effective_for_this
                                if excluded_for_this > 0:
                                    half_filled_tray_info.append({'tray_id': tray.tray_id, 'cases': excluded_for_this})
                    
                    logger.info(f"✅ Tray split: {len(delink_tray_info)} trays ({sum(t['cases'] for t in delink_tray_info)} cases) → JIG, {len(half_filled_tray_info)} trays ({sum(t['cases'] for t in half_filled_tray_info)} cases) → NEW PICK TABLE")
                    
                    # ✅ FIX: Generate NEW lot_id for remaining qty RIGHT HERE (don't wait for later)
                    from datetime import datetime
                    import random
                    timestamp = datetime.now().strftime('%d%m%Y%H%M%S')
                    partial_lot_id = f"LID{timestamp}{random.randint(1000, 9999)}"
                    
                    # Create JigLoadTrayId records for NEW pick table entry with partial_lot_id
                    for tray in half_filled_tray_info:
                        JigLoadTrayId.objects.create(
                            lot_id=partial_lot_id,
                            tray_id=tray['tray_id'],
                            tray_quantity=tray['cases'],
                            batch_id=batch,
                            user=user,
                            broken_hooks_effective_tray=True,
                            date=timezone.now()
                        )
                    
                    # Create NEW TotalStockModel entry for remaining qty
                    # Copy brass_audit flags so carry-forward lot is visible in Jig pick table
                    remaining_qty = broken_hooks
                    new_stock = TotalStockModel.objects.create(
                        batch_id=stock.batch_id,
                        model_stock_no=stock.model_stock_no,
                        version=stock.version,
                        total_stock=remaining_qty,
                        polish_finish=stock.polish_finish,
                        plating_color=stock.plating_color,
                        lot_id=partial_lot_id,
                        dp_physical_qty=remaining_qty,
                        Jig_Load_completed=False,
                        jig_draft=False,
                        brass_audit_accptance=stock.brass_audit_accptance,
                        brass_audit_few_cases_accptance=stock.brass_audit_few_cases_accptance,
                        brass_audit_rejection=stock.brass_audit_rejection,
                        brass_audit_accepted_qty=remaining_qty,
                        brass_audit_onhold_picking=False,
                        last_process_module='Jig Loading',
                        next_process_module='Jig Loading',
                        last_process_date_time=timezone.now(),
                        brass_audit_last_process_date_time=timezone.now(),
                        created_at=timezone.now(),
                    )
                    logger.info(f"✅ Created new pick table entry: lot_id={partial_lot_id}, qty={remaining_qty}, batch={stock.batch_id}")
                    
                else:
                    # No broken hooks, all existing trays are delink
                    logger.info(f"✅ No splitting: original_lot_qty ({original_lot_qty}) == jig_capacity ({jig_capacity})")
                    if not delink_tray_info:
                        existing_trays = JigLoadTrayId.objects.filter(lot_id=lot_id, batch_id=batch).order_by('id')
                        delink_tray_info = [{'tray_id': t.tray_id, 'cases': t.tray_quantity} for t in existing_trays]
                    half_filled_tray_info = []
            
            else:
                # Splitting needed: original_lot_qty > jig_capacity
                # delink_tray_info and half_filled_tray_info already prepared from above logic
                logger.info(f"✅ Splitting: original_lot_qty ({original_lot_qty}) > jig_capacity ({jig_capacity})")
                logger.info(f"   → Delink trays: {len(delink_tray_info)} ({sum(t['cases'] for t in delink_tray_info)} cases)")
                logger.info(f"   → Half-filled trays: {len(half_filled_tray_info)} ({sum(t['cases'] for t in half_filled_tray_info)} cases))")
                
                # Handle broken hooks in splitting scenario (original_qty > jig_capacity AND broken_hooks > 0)
                # In this case, remaining qty should create a NEW pick table entry instead of staying in original lot
                if broken_hooks > 0 and half_filled_tray_info:
                    logger.info(f"🔀 BROKEN HOOKS IN SPLITTING: broken_hooks={broken_hooks}, half_filled_qty={sum(t['cases'] for t in half_filled_tray_info)}")
                    
                    # Generate NEW lot_id for broken hooks excluded trays
                    from datetime import datetime
                    import random
                    timestamp = datetime.now().strftime('%d%m%Y%H%M%S')
                    partial_lot_id = f"LID{timestamp}{random.randint(1000, 9999)}"
                    
                    # Identify the source stock for carry-forward.
                    # In multi-model, the half-filled tray belongs to the secondary lot.
                    # The frontend sets data-lot-id on the half-filled input, sent in tray['lot_id'].
                    _cf_source_lot = half_filled_tray_info[0].get('lot_id', '') or lot_id
                    _cf_source_stock = TotalStockModel.objects.filter(lot_id=_cf_source_lot).first() or stock

                    # Create JigLoadTrayId records for half_filled (pick table) with NEW partial_lot_id
                    for tray in half_filled_tray_info:
                        _tray_src_lot = tray.get('lot_id', '') or _cf_source_lot
                        _tray_src_stock = TotalStockModel.objects.filter(lot_id=_tray_src_lot).first()
                        _tray_batch = _tray_src_stock.batch_id if _tray_src_stock else _cf_source_stock.batch_id
                        JigLoadTrayId.objects.create(
                            lot_id=partial_lot_id,
                            tray_id=tray['tray_id'],
                            tray_quantity=tray['cases'],
                            batch_id=_tray_batch,
                            user=user,
                            broken_hooks_effective_tray=True,
                            date=timezone.now()
                        )
                    
                    # Create NEW TotalStockModel entry for the half_filled portion with partial_lot_id.
                    # Use source stock (secondary lot) for correct batch and brass_audit visibility flags.
                    half_filled_qty = sum(t['cases'] for t in half_filled_tray_info)
                    new_stock = TotalStockModel.objects.create(
                        batch_id=_cf_source_stock.batch_id,
                        model_stock_no=_cf_source_stock.model_stock_no,
                        version=_cf_source_stock.version,
                        total_stock=half_filled_qty,
                        polish_finish=_cf_source_stock.polish_finish,
                        plating_color=_cf_source_stock.plating_color,
                        lot_id=partial_lot_id,
                        dp_physical_qty=half_filled_qty,
                        Jig_Load_completed=False,
                        jig_draft=False,
                        brass_audit_accptance=_cf_source_stock.brass_audit_accptance,
                        brass_audit_few_cases_accptance=_cf_source_stock.brass_audit_few_cases_accptance,
                        brass_audit_rejection=_cf_source_stock.brass_audit_rejection,
                        brass_audit_accepted_qty=half_filled_qty,
                        brass_audit_onhold_picking=False,
                        last_process_module='Jig Loading',
                        next_process_module='Jig Loading',
                        last_process_date_time=timezone.now(),
                        brass_audit_last_process_date_time=timezone.now(),
                        created_at=timezone.now(),
                    )
                    logger.info(f"✅ Created new pick table entry for broken hooks: lot_id={partial_lot_id}, qty={half_filled_qty}, source_lot={_cf_source_lot}")
                    
                    # Update original stock to reflect only delink portion remains
                    delink_qty = sum(t['cases'] for t in delink_tray_info)
                    if delink_qty != original_lot_qty:
                        stock.total_stock = delink_qty
                        logger.info(f"📊 Updated original stock qty from {original_lot_qty} to {delink_qty}")
                else:
                    # Normal splitting (no broken hooks or no half-filled trays)
                    logger.info(f"✅ Normal splitting: delink={sum(t['cases'] for t in delink_tray_info)}, half_filled={sum(t['cases'] for t in half_filled_tray_info)}")
                
                # Create JigLoadTrayId for delink_tray_info (update existing or create)
                for tray in delink_tray_info:
                    jig_tray, created = JigLoadTrayId.objects.get_or_create(
                        lot_id=lot_id,
                        tray_id=tray['tray_id'],
                        batch_id=batch,
                        defaults={
                            'tray_quantity': tray['cases'],
                            'user': user,
                            'date': timezone.now()
                        }
                    )
                    if not created:
                        jig_tray.tray_quantity = tray['cases']
                        jig_tray.save()
                
                # Create JigLoadTrayId for half_filled_tray_info (pick table) - only if NOT created with partial_lot_id above
                if not (broken_hooks > 0 and half_filled_tray_info):
                    for tray in half_filled_tray_info:
                        # ✅ FIX: Use partial_lot_id for excess lot cases, otherwise use tray's lot_id
                        if is_excess_lot_case:
                            tray_lot_id = partial_lot_id
                        else:
                            tray_lot_id = tray.get('lot_id', lot_id)  # Use tray's actual lot_id for multi-model
                        jig_tray, created = JigLoadTrayId.objects.get_or_create(
                            lot_id=tray_lot_id,
                            tray_id=tray['tray_id'],
                            batch_id=batch,
                            defaults={
                                'tray_quantity': tray['cases'],
                                'user': user,
                                'date': timezone.now()
                            }
                        )
                        if not created:
                            jig_tray.tray_quantity = tray['cases']
                            jig_tray.save()

            # Update Jig
            jig.is_loaded = True
            jig.batch_id = batch_id
            jig.lot_id = lot_id
            jig.current_user = None
            jig.locked_at = None
            jig.drafted = False
            jig.save()

            # Update original stock
            stock.Jig_Load_completed = True
            stock.jig_draft = False
            stock.save()

            # Mark all combined lots as completed so they disappear from pick table
            if is_multi_model and combined_lot_ids:
                logger.info(f"📌 Marking {len(combined_lot_ids)} combined lots as completed")
                for combined_lot in combined_lot_ids:
                    try:
                        combined_stock = TotalStockModel.objects.filter(lot_id=combined_lot).first()
                        if combined_stock:
                            combined_stock.Jig_Load_completed = True
                            combined_stock.jig_draft = False
                            combined_stock.save()
                            logger.info(f"✅ Marked combined lot {combined_lot} as completed")
                        else:
                            logger.warning(f"⚠️ Could not find TotalStockModel for combined lot {combined_lot}")
                    except Exception as e:
                        logger.error(f"❌ Error marking combined lot {combined_lot} as completed: {e}")

            # Mark draft as submitted
            if draft:
                draft.draft_status = 'submitted'
                draft.save()

            # Create JigCompleted record - This is what the user expects to see in "Complete table"
            # ✅ FIX: original_lot_qty should be the actual loaded cases qty (accounting for broken hooks)
            # Calculate effective loaded cases as: delink_qty (jig capacity - broken hooks)
            effective_loaded_qty = jig_capacity - broken_hooks
            
            # For excess lots, use excess_tray_info as half_filled_tray_info and save partial_lot_id
            if is_excess_lot_case and 'excess_tray_info' in locals():
                # Update tray IDs in excess_tray_info with actual allocated tray IDs
                updated_excess_tray_info = []
                for i, tray in enumerate(excess_tray_info):
                    # Find corresponding JigLoadTrayId record to get actual tray_id
                    jig_tray = JigLoadTrayId.objects.filter(
                        lot_id=partial_lot_id, 
                        tray_quantity=tray['cases']
                    ).first()
                    
                    if jig_tray:
                        updated_excess_tray_info.append({
                            'tray_id': jig_tray.tray_id, 
                            'cases': tray['cases']
                        })
                    else:
                        # Fallback: use calculated tray_id if JigLoadTrayId not found
                        updated_excess_tray_info.append({
                            'tray_id': tray.get('tray_id', f"EXCESS-{i+1:03d}"), 
                            'cases': tray['cases']
                        })
                
                logger.info(f"📝 Saving JigCompleted with partial_lot_id: {partial_lot_id}")
                logger.info(f"📝 Updated excess_tray_info: {updated_excess_tray_info}")
                
                completed_record = JigCompleted.objects.create(
                    lot_id=data.get('lot_id'),
                    batch_id=batch.batch_id,
                    user=user,
                    jig_id=jig_qr_id,
                    loaded_cases_qty=effective_loaded_qty,
                    broken_hooks=int(data.get('broken_buildup_hooks', 0) or 0),
                    original_lot_qty=effective_loaded_qty,  # Should match loaded_cases_qty
                    delink_tray_info=data.get('delink_tray_info', []),
                    delink_tray_count=len(data.get('delink_tray_info', [])),
                    half_filled_tray_info=updated_excess_tray_info,  # Use calculated excess trays
                    partial_lot_id=partial_lot_id,  # Save the new lot ID for excess portion
                    draft_status='submitted'
                )
            else:
                # Normal case (not excess lot)
                completed_record = JigCompleted.objects.create(
                    lot_id=data.get('lot_id'),
                    batch_id=batch.batch_id,
                    user=user,
                    jig_id=jig_qr_id,
                    loaded_cases_qty=effective_loaded_qty,
                    broken_hooks=int(data.get('broken_buildup_hooks', 0) or 0),
                    original_lot_qty=effective_loaded_qty,  # Should match loaded_cases_qty
                    delink_tray_info=data.get('delink_tray_info', []),
                    delink_tray_count=len(data.get('delink_tray_info', [])),
                    half_filled_tray_info=half_filled_tray_info if 'half_filled_tray_info' in locals() else data.get('half_filled_tray_info', []),
                    partial_lot_id=partial_lot_id if partial_lot_id else None,
                    draft_status='submitted'
                )
            
            return Response({
                'success': True,
                'message': 'Jig submitted successfully!',
                'jig_completed_id': completed_record.id
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"💥 Error submitting jig: {e}")
            return Response({'success': False, 'message': f'Internal server error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _handle_excess_lot_submission(self, data, batch, stock, jig_capacity, tray_capacity, user, logger):
        """
        Handle submission for lots that exceed jig capacity.
        Calculates proper delink trays (up to jig capacity) and excess trays (remainder).
        
        Business Logic:
        - Lot Qty (220) > Jig Capacity (98)
        - Delink: First 98 cases go into jig (sequential fill with tray split if needed)
        - Excess: Remaining 122 cases stay in pick table with new lot_id
        
        Returns:
        - delink_tray_info: Trays going into jig (validated tray IDs)
        - excess_tray_info: Trays staying in pick table
        - partial_lot_id: New lot ID for excess portion
        """
        lot_id = data.get('lot_id')
        # Use the full original delink list from the request (not the locally-mutated copy)
        delink_tray_info = list(data.get('delink_tray_info', []))
        broken_hooks = int(data.get('broken_buildup_hooks', 0) or 0)
        
        # Calculate quantities
        original_qty = stock.total_stock
        # Effective delink qty accounts for broken hooks reducing jig capacity
        delink_qty = jig_capacity - broken_hooks  # cases that actually fit in the jig
        excess_qty = original_qty - delink_qty  # Remainder stays in pick table (220 - 96 = 124, not 220 - 98 = 122)
        
        logger.info(f"🔄 EXCESS LOT SUBMISSION:")
        logger.info(f"  Original Qty: {original_qty}")
        logger.info(f"  Jig Capacity: {jig_capacity}")
        logger.info(f"  Broken Hooks: {broken_hooks}")
        logger.info(f"  Delink Qty (effective, to jig): {delink_qty}")
        logger.info(f"  Excess Qty (to pick table): {excess_qty}")
        
        # Validate delink trays match effective jig capacity
        scanned_delink_total = sum(int(tray.get('cases', 0)) for tray in delink_tray_info)
        if scanned_delink_total != delink_qty:
            logger.error(f"❌ DELINK QTY MISMATCH: scanned={scanned_delink_total}, expected={delink_qty}")
            raise ValueError(f"Delink quantity ({scanned_delink_total}) must equal effective jig capacity ({delink_qty})")
        
        # Calculate excess tray distribution using actual tray allocation
        excess_tray_info = []
        
        # Get existing trays from the original lot to allocate excess portion
        existing_trays = list(JigLoadTrayId.objects.filter(
            lot_id=lot_id, 
            batch_id=batch
        ).order_by('id'))
        
        if existing_trays:
            # Track which trays are allocated to delink vs excess
            cumulative_delink = 0
            cumulative_excess = 0
            
            for tray in existing_trays:
                # If we haven't filled delink quota, allocate to delink first
                if cumulative_delink < delink_qty:
                    remaining_delink = delink_qty - cumulative_delink
                    delink_portion = min(remaining_delink, tray.tray_quantity)
                    cumulative_delink += delink_portion
                    
                    # If this tray has remaining cases after delink allocation, put remainder in excess
                    if tray.tray_quantity > delink_portion:
                        excess_portion = tray.tray_quantity - delink_portion
                        excess_tray_info.append({
                            'tray_id': tray.tray_id,
                            'cases': excess_portion,
                            'is_excess': True,
                            'requires_future_scanning': True
                        })
                        cumulative_excess += excess_portion
                else:
                    # All remaining trays go to excess portion
                    excess_tray_info.append({
                        'tray_id': tray.tray_id,
                        'cases': tray.tray_quantity,
                        'is_excess': True,
                        'requires_future_scanning': True
                    })
                    cumulative_excess += tray.tray_quantity
                    
            logger.info(f"🎯 EXCESS ALLOCATION FROM EXISTING TRAYS:")
            logger.info(f"  Total existing trays: {len(existing_trays)}")
            logger.info(f"  Excess trays allocated: {len(excess_tray_info)} ({cumulative_excess} cases)")
                    
        else:
            # Fallback: generate theoretical tray distribution if no existing trays found
            logger.warning("⚠️ No existing trays found - generating theoretical excess distribution")
            cumulative = 0
            tray_index = 0
            
            while cumulative < excess_qty:
                remaining = excess_qty - cumulative
                tray_qty = min(remaining, tray_capacity)
                
                excess_tray_info.append({
                    'tray_id': f"EXCESS-{tray_index+1:03d}",  # Use EXCESS prefix for clarity
                    'cases': tray_qty,
                    'is_excess': True,
                    'requires_future_scanning': True
                })
                
                cumulative += tray_qty
                tray_index += 1
        
        # Generate new lot ID for excess portion
        from datetime import datetime
        import random
        timestamp = datetime.now().strftime('%d%m%Y%H%M%S')
        partial_lot_id = f"LID{timestamp}{random.randint(1000, 9999)}"
        
        logger.info(f"🎯 EXCESS TRAYS CALCULATED: {len(excess_tray_info)} trays for {excess_qty} cases")
        logger.info(f"🆔 NEW LOT ID: {partial_lot_id}")
        
        return delink_tray_info, excess_tray_info, partial_lot_id


# In validate_lock_jig_id, move capacity check before is_loaded check to show capacity mismatch for all jigs
@api_view(['POST'])
def validate_lock_jig_id(request):
    logger = logging.getLogger(__name__)
    try:
        # Check authentication first
        if not request.user.is_authenticated:
            return JsonResponse({'valid': False, 'message': 'User not authenticated'}, status=401)
        
        logger.info(f"🚀 API CALLED - validate_lock_jig_id by user: {request.user.username}")
        
        jig_id = request.data.get('jig_id', '').strip()
        batch_id = request.data.get('batch_id', '').strip()
        lot_id = request.data.get('lot_id', '').strip()
        user = request.user
        
        logger.info(f"📊 Request data: jig_id={jig_id}, batch_id={batch_id}, user={user.username}")

        # Basic validation - check if jig_id is provided
        if not jig_id or len(jig_id) > 9:
            return JsonResponse({'valid': False, 'message': 'Invalid Jig ID format'}, status=200)

        # Check if jig_id exists in database
        try:
            jig = Jig.objects.get(jig_qr_id=jig_id)
        except Jig.DoesNotExist:
            return JsonResponse({'valid': False, 'message': 'Invalid Jig ID format'}, status=200)

        # Get expected jig capacity for this batch/lot
        expected_capacity = None
        try:
            stock = TotalStockModel.objects.get(batch_id__batch_id=batch_id, lot_id=lot_id)
            batch = stock.batch_id
            model_master = batch.model_stock_no if batch else stock.model_stock_no
            if model_master:
                jig_master = JigLoadingMaster.objects.filter(model_stock_no=model_master).first()
                if jig_master:
                    expected_capacity = jig_master.jig_capacity
        except (TotalStockModel.DoesNotExist, AttributeError) as e:
            logger.warning(f"⚠️ Could not determine expected capacity: {e}")

        # Check if jig ID prefix matches expected capacity (if available) - do this for all existing jigs
        if expected_capacity is not None:
            match = re.match(r'J(\d+)-', jig_id)
            if match:
                jig_prefix_capacity = int(match.group(1))
                if jig_prefix_capacity != expected_capacity:
                    return JsonResponse({'valid': False, 'message': f'Jig ID capacity ({jig_prefix_capacity}) does not match expected ({expected_capacity})'}, status=200)

        # Check if jig is already submitted (loaded)
        if jig.is_loaded:
            return JsonResponse({'valid': False, 'message': 'Jig ID has been submitted and cannot be reused'}, status=200)

        # FIRST: Check for existing drafted jigs for current batch
        drafted_jig_current_batch = Jig.objects.filter(
            jig_qr_id=jig_id, drafted=True, batch_id=batch_id
        ).first()

        logger.info(f"🔍 Drafted jig current batch query result: {drafted_jig_current_batch}")

        if drafted_jig_current_batch:
            if drafted_jig_current_batch.current_user == user:
                return JsonResponse({'valid': True, 'message': 'Jig ID is drafted by you for this batch.'}, status=200)
            else:
                return JsonResponse({'valid': False, 'message': 'Jig ID is drafted by another user for this batch.'}, status=200)

        # If not drafted for this batch, check if drafted for any other batch
        drafted_jig_other_batch = Jig.objects.filter(
            jig_qr_id=jig_id, drafted=True
        ).exclude(batch_id=batch_id).first()

        logger.info(f"🔍 Drafted jig other batch query result: {drafted_jig_other_batch}")

        if drafted_jig_other_batch:
            return JsonResponse({'valid': False, 'message': 'Jig ID is drafted for another batch.'}, status=200)

        # If not drafted/locked and capacity matches, show available message
        logger.info("✅ Jig ID is available")
        return JsonResponse({'valid': True, 'message': 'Jig ID is available to use'}, status=200)
        
    except Exception as e:
        logger.error(f"💥 Exception in validate_lock_jig_id: {e}")
        return JsonResponse({'valid': False, 'message': 'Internal server error'}, status=200)




@api_view(['GET'])
def jig_tray_id_list(request):
    stock_lot_id = request.GET.get('stock_lot_id')
    if not stock_lot_id:
        return JsonResponse({'success': False, 'error': 'stock_lot_id required'}, status=400)
    
    # Check JigCompleted for completed jig loading
    jig_completed = JigCompleted.objects.filter(lot_id=stock_lot_id).first()
    if jig_completed and jig_completed.delink_tray_info:
        formatted_trays = []
        for tray in jig_completed.delink_tray_info:
            formatted_tray = {
                'tray_id': tray.get('tray_id', ''),
                'tray_quantity': tray.get('cases', ''),
                'row_index': '',
                'tray_status': "Delinked",
                'original_quantity': tray.get('cases', ''),
                'excluded_quantity': 0,
            }
            formatted_trays.append(formatted_tray)
        return JsonResponse({'success': True, 'trays': formatted_trays})
    
    # Fallback to JigLoadTrayId
    tray_objects = JigLoadTrayId.objects.filter(lot_id=stock_lot_id).order_by('date')
    
    if tray_objects.exists():
        formatted_trays = []
        for idx, tray_obj in enumerate(tray_objects):
            # Determine tray status based on broken_hooks_effective_tray field
            tray_status = "Delinked" if tray_obj.broken_hooks_effective_tray else "Partial Draft"
            
            formatted_tray = {
                'tray_id': tray_obj.tray_id,
                'tray_quantity': tray_obj.effective_tray_qty if tray_obj.broken_hooks_effective_tray else tray_obj.tray_quantity,  # Use effective quantity for delinked trays
                'row_index': str(idx),
                'tray_status': tray_status,
                'original_quantity': tray_obj.tray_quantity,  # For reference
                'excluded_quantity': max(0, tray_obj.broken_hooks_excluded_qty),  # Ensure non-negative values
            }
            formatted_trays.append(formatted_tray)
        
        return JsonResponse({'success': True, 'trays': formatted_trays})
    else:
        return JsonResponse({'success': True, 'trays': []})

                   
# Jig Loading Complete Table - Main View 
class JigCompletedTable(TemplateView):
    template_name = "JigLoading/Jig_CompletedTable.html"
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get completed lots from JigCompleted table instead of relying only on TotalStockModel
        completed_jig_records = JigCompleted.objects.all().order_by('-updated_at')
        completed_data = []
        
        for jig_completed in completed_jig_records:
            try:
                # Get the corresponding TotalStockModel record for this lot
                # For partial lots, the completed portion uses original lot_id
                stock = TotalStockModel.objects.filter(
                    batch_id__batch_id=jig_completed.batch_id,
                    lot_id=jig_completed.lot_id
                ).first()
                
                # If not found, try to get by batch_id (for partial lots that changed lot_id)
                if not stock:
                    stock = TotalStockModel.objects.filter(
                        batch_id__batch_id=jig_completed.batch_id
                    ).first()
                
                if not stock:
                    continue  # Skip if no corresponding stock record
                    
                plating_stk_nos = JigLoadTrayId.objects.filter(lot_id=jig_completed.lot_id).values_list('batch_id__plating_stk_no', flat=True).distinct()
                plating_stk_nos = [psn for psn in plating_stk_nos if psn]  # Filter out None/empty
                
                if plating_stk_nos:
                    lot_plating_stk_nos = plating_stk_nos
                else:
                    # Fallback to single plating_stk_no
                    plating_stk_no = (
                        getattr(stock.batch_id, 'plating_stk_no', None)
                        or getattr(stock.model_stock_no, 'plating_stk_no', None)
                    )
                    lot_plating_stk_nos = [plating_stk_no or 'No Plating Stock No']
                
                polishing_stk_no = (
                    getattr(stock.batch_id, 'polishing_stk_no', None)
                    or getattr(stock.model_stock_no, 'polishing_stk_no', None)
                )
                tray_capacity = JigView.get_tray_capacity(stock)
                jig_type = ''
                jig_capacity = ''
                if stock.model_stock_no:
                    jig_master = JigLoadingMaster.objects.filter(model_stock_no=stock.model_stock_no).first()
                    if jig_master:
                        jig_type = jig_master.jig_type
                        jig_capacity = jig_master.jig_capacity

                # Use JigCompleted.updated_lot_qty as the effective lot quantity
                lot_qty = jig_completed.updated_lot_qty

                # Use delink_tray_info from JigCompleted
                tray_info = []
                if getattr(jig_completed, 'delink_tray_info', None):
                    tray_info = jig_completed.delink_tray_info
                    # Set status for each tray
                    for i, tray in enumerate(tray_info):
                        if i == len(tray_info) - 1 and tray.get('tray_quantity', 0) < 12:
                            tray['status'] = 'Partial load'
                        else:
                            tray['status'] = 'Delinked'
                    no_of_trays = len(tray_info)
                else:
                    # Fallback to calculation
                    no_of_trays = 0
                    if tray_capacity and tray_capacity > 0 and lot_qty > 0:
                        no_of_trays = (lot_qty // tray_capacity) + (1 if lot_qty % tray_capacity else 0)

                completed_data.append({
                    'batch_id': jig_completed.batch_id,
                    'jig_loaded_date_time': jig_completed.updated_at,
                    'lot_id': jig_completed.lot_id,  # Use original lot_id for completed portion
                    'lot_plating_stk_nos': lot_plating_stk_nos,
                    'lot_polishing_stk_nos': polishing_stk_no or 'No Polishing Stock No',
                    'plating_color': stock.plating_color.plating_color if stock.plating_color else '',
                    'polish_finish': stock.polish_finish.polish_finish if stock.polish_finish else '',
                    'lot_version_names': stock.version.version_internal if stock.version else '',
                    'tray_type': getattr(stock.batch_id, 'tray_type', ''),
                    'tray_capacity': getattr(stock.batch_id, 'tray_capacity', ''),
                    'calculated_no_of_trays': no_of_trays,
                    'tray_info': tray_info,
                    'total_cases_loaded': jig_completed.loaded_cases_qty,
                    'jig_type': jig_type,
                    'jig_capacity': jig_capacity,
                    'jig_qr_id': jig_completed.jig_id,
                    'jig_loaded_date_time': jig_completed.updated_at,
                    'model_images': [img.master_image.url for img in stock.model_stock_no.images.all()] if stock.model_stock_no else [],
                    'is_multi_model': jig_completed.is_multi_model,
                    'no_of_model_cases': jig_completed.no_of_model_cases,
                })
            except Exception as e:
                print(f"Error processing JigCompleted record {jig_completed.id}: {e}")
                continue
        
        context['jig_details'] = completed_data
        
        # Pagination: 10 rows per page
        paginator = Paginator(completed_data, 10)
        page_number = self.request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        context['page_obj'] = page_obj
        context['jig_details'] = page_obj.object_list
        
        return context


class JigCompletedDataAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        batch_id = request.GET.get('batch_id')
        lot_id = request.GET.get('lot_id')
        
        if not batch_id or not lot_id:
            return Response({'error': 'batch_id and lot_id are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            jig_completed = JigCompleted.objects.filter(
                batch_id=batch_id,
                lot_id=lot_id
            ).first()
            
            if not jig_completed:
                return Response({'error': 'No data found for the given batch_id and lot_id'}, status=status.HTTP_404_NOT_FOUND)
            
            data = {
                'id': jig_completed.id,
                'batch_id': jig_completed.batch_id,
                'lot_id': jig_completed.lot_id,
                'user': jig_completed.user.username,
                'draft_data': jig_completed.draft_data,
                'updated_at': jig_completed.updated_at,
                'jig_cases_remaining_count': jig_completed.jig_cases_remaining_count,
                'updated_lot_qty': jig_completed.updated_lot_qty,
                'original_lot_qty': jig_completed.original_lot_qty,
                'jig_id': jig_completed.jig_id,
                'delink_tray_info': jig_completed.delink_tray_info,
                'delink_tray_qty': jig_completed.delink_tray_qty,
                'delink_tray_count': jig_completed.delink_tray_count,
                'half_filled_tray_info': jig_completed.half_filled_tray_info,
                'half_filled_tray_qty': jig_completed.half_filled_tray_qty,
                'jig_capacity': jig_completed.jig_capacity,
                'broken_hooks': jig_completed.broken_hooks,
                'loaded_cases_qty': jig_completed.loaded_cases_qty,
                'draft_status': jig_completed.draft_status,
                'hold_status': jig_completed.hold_status,
                'is_multi_model': jig_completed.is_multi_model,
            }
            
            return Response(data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─────────────────────────────────────────────────────────────────────────────
# Jig Composition View
# Shows a visual breakdown of how cases from each model/lot are arranged on
# the jig — one card per plating colour group with animated case badges.
# ─────────────────────────────────────────────────────────────────────────────
@method_decorator(login_required, name='dispatch')
class JigCompositionView(TemplateView):
    template_name = "JigLoading/Jig_Composition.html"

    # Colour palette for model cards — cycles if there are more than 8 models.
    CARD_COLORS = [
        "#028084", "#e67e22", "#8e44ad", "#2980b9",
        "#27ae60", "#c0392b", "#16a085", "#d35400",
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        lot_id   = self.request.GET.get('lot_id')
        batch_id = self.request.GET.get('batch_id')
        jig_id   = self.request.GET.get('jig_id')

        cards = []

        # ── Locate the completed jig record ──────────────────────────────────
        jig_completed = None
        if lot_id and batch_id:
            jig_completed = JigCompleted.objects.filter(
                lot_id=lot_id, batch_id=batch_id
            ).first()

        if not jig_completed and jig_id:
            jig_completed = JigCompleted.objects.filter(jig_id=jig_id).first()

        if jig_completed:
            # ── Build per-model data ──────────────────────────────────────────
            # For multi-model jigs the combined lot IDs are stored as
            # "PLT_STK_NO:qty,PLT_STK_NO:qty" in no_of_model_cases.
            if jig_completed.is_multi_model and jig_completed.no_of_model_cases:
                for idx, segment in enumerate(jig_completed.no_of_model_cases.split(',')):
                    segment = segment.strip()
                    if ':' not in segment:
                        continue
                    model_no, qty_str = segment.rsplit(':', 1)
                    try:
                        qty = int(qty_str)
                    except ValueError:
                        qty = 0

                    color = self.CARD_COLORS[idx % len(self.CARD_COLORS)]
                    cards.append({
                        'models': [{'model_no': model_no, 'case_qty': qty}],
                        'cases':  [{'color': color} for _ in range(qty)],
                        'color':  color,
                    })
            else:
                # Single-model jig — one card for the whole loaded quantity
                qty = jig_completed.loaded_cases_qty or 0
                try:
                    stock = TotalStockModel.objects.filter(
                        batch_id__batch_id=jig_completed.batch_id,
                        lot_id=jig_completed.lot_id
                    ).first()
                    model_no = (
                        getattr(stock.batch_id, 'plating_stk_no', None)
                        or getattr(stock.model_stock_no, 'model_no', 'N/A')
                        if stock else 'N/A'
                    )
                except Exception:
                    model_no = 'N/A'

                color = self.CARD_COLORS[0]
                cards.append({
                    'models': [{'model_no': model_no, 'case_qty': qty}],
                    'cases':  [{'color': color} for _ in range(qty)],
                    'color':  color,
                })

        context['cards']    = cards
        context['lot_id']   = lot_id
        context['batch_id'] = batch_id
        context['jig_id']   = jig_id
        return context


# ─────────────────────────────────────────────────────────────────────────────
# Hold / Unhold API — saves a hold or release reason against a lot
# ─────────────────────────────────────────────────────────────────────────────
class JigSaveHoldUnholdReasonAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        lot_id = request.data.get('lot_id')
        action = request.data.get('action')   # 'hold' | 'unhold'
        remark = request.data.get('remark', '')

        if not lot_id:
            return Response({'success': False, 'message': 'lot_id is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        if action not in ('hold', 'unhold'):
            return Response({'success': False, 'message': 'action must be "hold" or "unhold"'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            stock = TotalStockModel.objects.get(lot_id=lot_id)
        except TotalStockModel.DoesNotExist:
            return Response({'success': False, 'message': 'Lot not found'},
                            status=status.HTTP_404_NOT_FOUND)

        if action == 'hold':
            stock.jig_hold_lot       = True
            stock.jig_holding_reason = remark
            stock.jig_release_lot    = False
            stock.jig_release_reason = ''
        else:  # unhold
            stock.jig_hold_lot       = False
            stock.jig_release_lot    = True
            stock.jig_release_reason = remark

        stock.save()

        # Also update JigCompleted hold_status for the pick-table display
        JigCompleted.objects.filter(lot_id=lot_id).update(
            hold_status='hold' if action == 'hold' else 'normal'
        )

        return Response({'success': True, 'action': action},
                        status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────────────────────
# Pick Remark API — saves a pick/process remark on a completed jig record
# ─────────────────────────────────────────────────────────────────────────────
class JigSavePickRemarkAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        lot_id   = request.data.get('lot_id')
        batch_id = request.data.get('batch_id')
        remark   = request.data.get('remark', '')

        if not lot_id or not batch_id:
            return Response({'success': False, 'message': 'lot_id and batch_id are required'},
                            status=status.HTTP_400_BAD_REQUEST)

        updated = JigCompleted.objects.filter(
            lot_id=lot_id, batch_id=batch_id
        ).update(pick_remarks=remark)

        if updated:
            return Response({'success': True}, status=status.HTTP_200_OK)
        return Response({'success': False, 'message': 'Record not found'},
                        status=status.HTTP_404_NOT_FOUND)
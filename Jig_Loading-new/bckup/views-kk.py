from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.db.models import OuterRef, Subquery
from django.core.paginator import Paginator
import math
from IQF.models import IQFTrayId
from modelmasterapp.models import *
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods, require_POST
from django.http import JsonResponse
import json
import traceback
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.templatetags.static import static
from math import ceil
from django.db.models import Q
from django.views.generic import TemplateView, View
from rest_framework.decorators import api_view
from rest_framework.response import Response
from Brass_QC.models import *
from DayPlanning.models import *
from InputScreening.models import *
from BrassAudit.models import *
from Jig_Loading.models import *
from Jig_Unloading.models import *
from Recovery_DP.models import *
from Recovery_IS.models import *
from Recovery_Brass_QC.models import *
from Recovery_BrassAudit.models import *
from Recovery_IQF.models import *
import pytz
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.utils import timezone

import logging
 
# Configure logger for this module
logger = logging.getLogger("jig_loading")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(r"A:\Workspace\New_TTT_Sep\Jig_Loading\jig_loading.log")
formatter = logging.Formatter('[%(levelname)s] %(message)s')
file_handler.setFormatter(formatter)
if not logger.hasHandlers():
    logger.addHandler(file_handler)

@method_decorator(login_required, name='dispatch')

class JigPickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'JigLoading/Jig_Picktable.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False
        selected_lot_id = request.GET.get('lot_id') or None

        print("=== DEBUGGING: Starting data collection ===")
        
        # STEP 1: Get eligible stock models directly
        print("=== Getting eligible stock models ===")
        
        # Get eligible TotalStockModel records
        total_stock_eligible = TotalStockModel.objects.filter(
            (
                Q(brass_audit_accptance=True) |
                Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False)
            ) &
            Q(brass_audit_rejection=False)  # Exclude if brass_audit_rejection is True
        ).exclude(
            jig_hold_lot=True  # Exclude "On-Hold" records
        ).select_related('batch_id')
        
        print(f"TotalStockModel eligible count: {total_stock_eligible.count()}")
        
        # Get eligible RecoveryStockModel records
        recovery_stock_eligible = RecoveryStockModel.objects.filter(
            Q(brass_audit_accptance=True) |
            Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False)
        ).exclude(
            Jig_Load_completed=True
        ).exclude(
            jig_hold_lot=True  # Exclude "On-Hold" records
        ).select_related('batch_id')
        
        print(f"RecoveryStockModel eligible count: {recovery_stock_eligible.count()}")
        
        # STEP 2: Filter out "Yet to Release" lots
        print("=== Filtering out 'Yet to Release' lots ===")
        
        total_stock_filtered = []
        for stock in total_stock_eligible:
            status = self.calculate_batch_status(stock.lot_id)
            if status['status'] != 'Yet to Release':
                total_stock_filtered.append(stock)
        
        recovery_stock_filtered = []
        for stock in recovery_stock_eligible:
            status = self.calculate_batch_status(stock.lot_id)
            if status['status'] != 'Yet to Release':
                recovery_stock_filtered.append(stock)
        
        print(f"After filtering - TotalStock: {len(total_stock_filtered)}, RecoveryStock: {len(recovery_stock_filtered)}")
        
        # STEP 3: Get corresponding master creation records
        print("=== Getting master creation records ===")
        
        # Get batch_ids from filtered stock models
        total_batch_ids = [stock.batch_id_id for stock in total_stock_filtered if stock.batch_id_id]
        recovery_batch_ids = [stock.batch_id_id for stock in recovery_stock_filtered if stock.batch_id_id]
        
        # Get ModelMasterCreation records
        model_master_objects = []
        if total_batch_ids:
            model_master_objects = list(
                ModelMasterCreation.objects.filter(
                    pk__in=total_batch_ids,
                    total_batch_quantity__gt=0
                ).select_related(
                    'model_stock_no', 'version', 'location'
                ).prefetch_related(
                    'model_stock_no__images'
                )
            )
        
        # Get RecoveryMasterCreation records
        recovery_master_objects = []
        if recovery_batch_ids:
            recovery_master_objects = list(
                RecoveryMasterCreation.objects.filter(
                    pk__in=recovery_batch_ids,
                    total_batch_quantity__gt=0
                ).select_related(
                    'model_stock_no', 'version', 'location'
                ).prefetch_related(
                    'model_stock_no__images'
                )
            )
        
        print(f"ModelMaster count: {len(model_master_objects)}, RecoveryMaster count: {len(recovery_master_objects)}")
        
        # STEP 4: Create lookup dictionaries for efficient access
        print("=== Creating lookup dictionaries ===")
        
        # Stock model lookups
        total_stock_lookup = {stock.batch_id_id: stock for stock in total_stock_filtered}
        recovery_stock_lookup = {stock.batch_id_id: stock for stock in recovery_stock_filtered}
        
        # STEP 5: Combine and sort all master objects
        all_master_objects = model_master_objects + recovery_master_objects
        
        # Sort by brass_audit_last_process_date_time (most recent first), falling back to date_time
        def get_sort_key(obj):
            # Get the corresponding stock model
            if isinstance(obj, ModelMasterCreation):
                stock = total_stock_lookup.get(obj.pk)
            else:  # RecoveryMasterCreation
                stock = recovery_stock_lookup.get(obj.pk)
            
            if stock and stock.brass_audit_last_process_date_time:
                return stock.brass_audit_last_process_date_time
            return obj.date_time
        
        all_master_objects.sort(key=get_sort_key, reverse=True)
        
        print(f"Combined and sorted count: {len(all_master_objects)}")
        
        # STEP 6: Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(all_master_objects, 10)
        page_obj = paginator.get_page(page_number)
        
        # STEP 7: Get related data for the current page efficiently
        current_page_batch_ids = [obj.pk for obj in page_obj.object_list]
        
        # Get JigLoadingMaster data in bulk
        model_stock_nos = [obj.model_stock_no.pk for obj in page_obj.object_list if obj.model_stock_no]
        jig_loading_lookup = {}
        for jlm in JigLoadingMaster.objects.filter(model_stock_no_id__in=model_stock_nos):
            jig_loading_lookup[jlm.model_stock_no_id] = jlm
        
        # Get rejection quantities in bulk
        lot_ids = []
        for obj in page_obj.object_list:
            if isinstance(obj, ModelMasterCreation):
                stock = total_stock_lookup.get(obj.pk)
            else:  # RecoveryMasterCreation
                stock = recovery_stock_lookup.get(obj.pk)
            if stock and stock.lot_id:
                lot_ids.append(stock.lot_id)
        
        rejection_lookup = {}
        # Get rejections from both rejection tables
        for rejection in Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id__in=lot_ids):
            rejection_lookup[rejection.lot_id] = rejection.total_rejection_quantity
            
        for rejection in RecoveryBrass_Audit_Rejection_ReasonStore.objects.filter(lot_id__in=lot_ids):
            if rejection.lot_id not in rejection_lookup:  # Don't overwrite if already exists
                rejection_lookup[rejection.lot_id] = rejection.total_rejection_quantity
                print("=== FETCHING JIG DETAILS FOR DEBUGGING ===")
        
        
        # STEP 7.5: Fetch JigDetails for smart matching (latest IP_loaded_date_time)
        print("=== FETCHING JIG DETAILS FOR SMART MATCHING ===")
        jig_details_qs = JigDetails.objects.all().order_by('-IP_loaded_date_time')

        # Create lookup by plating_stk_no, keeping only latest IP_loaded_date_time
        jig_details_lookup = {}
        for jd in jig_details_qs:
            for model_case in jd.no_of_model_cases:
                # Only add if not exists or if this one is more recent
                if model_case not in jig_details_lookup:
                    jig_details_lookup[model_case] = jd
                elif jd.IP_loaded_date_time and jig_details_lookup[model_case].IP_loaded_date_time:
                    if jd.IP_loaded_date_time > jig_details_lookup[model_case].IP_loaded_date_time:
                        jig_details_lookup[model_case] = jd
                        print(f"  UPDATED: {model_case} -> newer record with remarks: '{jd.remarks}'")
                elif jd.IP_loaded_date_time and not jig_details_lookup[model_case].IP_loaded_date_time:
                    jig_details_lookup[model_case] = jd
                    print(f"  UPDATED: {model_case} -> record with date vs no date")
            
            print(f"JigDetail: no_of_model_cases: {jd.no_of_model_cases} | remarks: '{jd.remarks}' | IP_loaded: {jd.IP_loaded_date_time}")        # STEP 8: Build master_data efficiently
        master_data = []
        print(f"=== PROCESSING {len(page_obj.object_list)} RECORDS ===")
        
        for master_obj in page_obj.object_list:
            # Determine if this is ModelMasterCreation or RecoveryMasterCreation
            is_recovery_master = isinstance(master_obj, RecoveryMasterCreation)
            master_type = "RecoveryMasterCreation" if is_recovery_master else "ModelMasterCreation"
            
            print(f"\n--- Processing {master_type}: batch_id={master_obj.batch_id} (pk: {master_obj.pk}) ---")
            
            # Get the appropriate stock model
            if is_recovery_master:
                tsm = None
                rsm = recovery_stock_lookup.get(master_obj.pk)
            else:
                tsm = total_stock_lookup.get(master_obj.pk)
                rsm = None
            
            stock_model = tsm if tsm else rsm
            stock_model_type = 'total' if tsm else 'recovery' if rsm else None
            
            print(f"  Selected model: {stock_model_type}")
            print(f"  Stock model data: {stock_model.lot_id if stock_model else 'None'}")
            
            # Get JigLoadingMaster data
            jlm = jig_loading_lookup.get(master_obj.model_stock_no.pk) if master_obj.model_stock_no else None
            
            # Build data dict
            data = {
                'batch_id': master_obj.batch_id,
                'date_time': master_obj.date_time,
                'model_stock_no__model_no': master_obj.model_stock_no.model_no if master_obj.model_stock_no else None,
                'plating_color': master_obj.plating_color,
                'polish_finish': master_obj.polish_finish,
                'version__version_internal': master_obj.version.version_internal if master_obj.version else None,
                'vendor_internal': master_obj.vendor_internal,
                'location__location_name': master_obj.location.location_name if master_obj.location else None,
                'no_of_trays': master_obj.no_of_trays,
                'tray_type': master_obj.tray_type,
                'tray_capacity': master_obj.tray_capacity,
                'Moved_to_D_Picker': master_obj.Moved_to_D_Picker,
                'Draft_Saved': master_obj.Draft_Saved,
                'plating_stk_no': master_obj.plating_stk_no,
                'polishing_stk_no': master_obj.polishing_stk_no,
                'category': master_obj.category,
                'stock_model_type': stock_model_type,
                'master_type': master_type,
                
            }
            
            # Add stock model fields if available
            if stock_model:
                data.update({
                    'last_process_module': stock_model.last_process_module,
                    'next_process_module': stock_model.next_process_module,
                    'brass_audit_accepted_qty_verified': stock_model.brass_audit_accepted_qty_verified,
                    'brass_audit_accepted_qty': stock_model.brass_audit_accepted_qty,
                    'brass_audit_missing_qty': stock_model.brass_audit_missing_qty,
                    'brass_audit_physical_qty': stock_model.brass_audit_physical_qty,
                    'brass_audit_physical_qty_edited': stock_model.brass_audit_physical_qty_edited,
                    'brass_audit_accptance': stock_model.brass_audit_accptance,
                    'brass_audit_accepted_tray_scan_status': stock_model.brass_audit_accepted_tray_scan_status,
                    'brass_audit_rejection': stock_model.brass_audit_rejection,
                    'brass_audit_few_cases_accptance': stock_model.brass_audit_few_cases_accptance,
                    'brass_audit_onhold_picking': stock_model.brass_audit_onhold_picking,
                    'jig_physical_qty': stock_model.jig_physical_qty,
                    'jig_pick_remarks': stock_model.jig_pick_remarks,
                    'stock_lot_id': stock_model.lot_id,
                    'edited_quantity': stock_model.jig_physical_qty if stock_model else 0,
                    'brass_audit_last_process_date_time': stock_model.brass_audit_last_process_date_time,
                    'Jig_Load_completed': stock_model.Jig_Load_completed,
                    'jig_holding_reason': getattr(stock_model, 'jig_holding_reason', ''),
                    'jig_release_reason': getattr(stock_model, 'jig_release_reason', ''),
                    'jig_hold_lot': getattr(stock_model, 'jig_hold_lot', False),
                    'jig_release_lot': getattr(stock_model, 'jig_release_lot', False),
                })
                
                # Add rejection quantity
                data['brass_rejection_qty'] = rejection_lookup.get(stock_model.lot_id, 0)
            else:
                # Set default values if no stock model found
                data.update({
                    'last_process_module': None,
                    'next_process_module': None,
                    'brass_audit_accepted_qty_verified': None,
                    'brass_audit_accepted_qty': None,
                    'brass_audit_missing_qty': None,
                    'brass_audit_physical_qty': None,
                    'brass_audit_physical_qty_edited': None,
                    'brass_audit_accptance': None,
                    'brass_audit_accepted_tray_scan_status': None,
                    'brass_audit_rejection': None,
                    'brass_audit_few_cases_accptance': None,
                    'brass_audit_onhold_picking': None,
                    'jig_physical_qty': None,
                    'stock_lot_id': None,
                    'brass_audit_last_process_date_time': None,
                    'Jig_Load_completed': None,
                    'brass_rejection_qty': 0,
                    'jig_holding_reason': '',
                    'jig_release_reason': '',
                    'jig_hold_lot': False,
                    'jig_release_lot': False,
                })

            # Add JigLoadingMaster fields if available
            if jlm:
                data.update({
                    'jig_type': jlm.jig_type,
                    'jig_capacity': jlm.jig_capacity,
                })
            else:
                data.update({
                    'jig_type': None,
                    'jig_capacity': None,
                })
                
            # Add JigDetails data based on plating_stk_no matching
            jig_detail = jig_details_lookup.get(data.get('plating_stk_no'))
            if jig_detail:
                data.update({
                    'jig_remarks': jig_detail.remarks,
                    'jig_no_of_model_cases': jig_detail.no_of_model_cases,
                })
                print(f"  MATCH FOUND! plating_stk_no: {data.get('plating_stk_no')} -> remarks: '{jig_detail.remarks}'")
            else:
                data.update({
                    'jig_remarks': '',
                    'jig_no_of_model_cases': [],
                })
                print(f"  No match for plating_stk_no: {data.get('plating_stk_no')}")

            # Calculate display quantity
            jig_physical_qty = data.get('jig_physical_qty', 0)
            brass_audit_accepted_qty = data.get('brass_audit_accepted_qty', 0)
            
            if jig_physical_qty and jig_physical_qty > 0:
                data['display_qty'] = jig_physical_qty
            else:
                data['display_qty'] = brass_audit_accepted_qty

            # Get model images
            images = []
            if master_obj.model_stock_no:
                for img in master_obj.model_stock_no.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            # Calculate batch status using the efficient method
            batch_status = self.calculate_batch_status_efficient(stock_model)
            data['batch_status'] = batch_status

            # Add draft check with content validation - prioritize tray work
            has_draft = False
            if stock_model and stock_model.lot_id:
                jig_detail = JigDetails.objects.filter(
                    lot_id=stock_model.lot_id,
                    draft_save=True
                ).first()
                
                if jig_detail:
                    # Check if actual tray work has been done
                    has_tray_work = False
                    
                    print(f"  Checking draft content for lot {stock_model.lot_id}:")
                    
                    # Check delink tray data - must have actual non-empty tray IDs
                    filled_delink_trays = 0
                    if jig_detail.delink_tray_data:
                        for tray in jig_detail.delink_tray_data:
                            tray_id = tray.get('tray_id', '').strip()
                            if tray_id:  # Non-empty tray ID
                                filled_delink_trays += 1
                                has_tray_work = True
                        print(f"    Delink trays: {len(jig_detail.delink_tray_data)} total, {filled_delink_trays} with tray IDs")
                    
                    # Check half filled tray data - must have actual tray IDs or quantities > 0
                    filled_half_trays = 0
                    if jig_detail.half_filled_tray_data:
                        for tray in jig_detail.half_filled_tray_data:
                            tray_id = tray.get('tray_id', '').strip()
                            tray_qty = tray.get('tray_quantity', 0)
                            if tray_id or tray_qty > 0:
                                filled_half_trays += 1
                                has_tray_work = True
                        print(f"    Half-filled trays: {len(jig_detail.half_filled_tray_data)} total, {filled_half_trays} with content")
                    
                    # Check if multiple lots (only meaningful if more than 1 lot AND has tray work)
                    lot_count = len(jig_detail.lot_id_quantities or {})
                    if lot_count > 1 and has_tray_work:
                        print(f"    Multi-model with tray work: {lot_count} lots")
                    elif lot_count > 1:
                        print(f"    Multi-model but no tray work: {lot_count} lots - not meaningful")
                    
                    # Final decision: Only meaningful if actual tray work has been done
                    print(f"    JIG QR ID: {jig_detail.jig_qr_id or 'None'} (not considered without tray work)")
                    print(f"    Final decision: has_tray_work = {has_tray_work}")
                    has_draft = has_tray_work
                
            print(f"  Draft exists for lot {stock_model.lot_id if stock_model else 'N/A'}: {has_draft}")

            data['has_draft'] = has_draft
            # Calculate no_of_trays based on display_qty
            tray_capacity = data.get('tray_capacity', 0)
            if tray_capacity > 0:
                data['no_of_trays'] = math.ceil(data['display_qty'] / tray_capacity)
            else:
                data['no_of_trays'] = 0
            
            print(f"Lot ID: {data.get('stock_lot_id')}, Batch Status: {batch_status['status']}, Display Qty: {data['display_qty']}, No of Trays: {data['no_of_trays']}")
            
            master_data.append(data)

        # Final sort by brass_audit_last_process_date_time
        master_data.sort(
            key=lambda x: x.get('brass_audit_last_process_date_time') or x.get('date_time'),
            reverse=True
        )
        
        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
            
            
        }
        return Response(context, template_name=self.template_name)
    
    def calculate_batch_status_efficient(self, stock_model):
        """
        Efficient version of calculate_batch_status that works with already loaded stock_model
        """
        if not stock_model:
            return {
                'status': 'Yet to Start',
                'remaining_qty': 0,
                'color': '#856404',
                'bg_color': '#fff3cd',
                'border_color': '#ffc107'
            }
    
        # On-Hold status check
        if getattr(stock_model, 'jig_hold_lot', False):
            return {
                'status': 'On-Hold',
                'remaining_qty': stock_model.jig_physical_qty or 0,
                'color': '#856404',
                'bg_color': '#ffe6e6',
                'border_color': '#ff6666'
            }
    
        jig_physical_qty = stock_model.jig_physical_qty or 0
    
        # Check if all trays for this lot are delinked
        lot_id = stock_model.lot_id
        total_trays = 0
        delinked_trays = 0
    
        jig_tray_qs = JigLoadTrayId.objects.filter(lot_id=lot_id)
        jig_total = jig_tray_qs.count()
        jig_delinked = jig_tray_qs.filter(delink_tray=True).count()
        total_trays += jig_total
        delinked_trays += jig_delinked
    
        recovery_tray_qs = RecoveryBrassAuditTrayId.objects.filter(lot_id=lot_id)
        recovery_total = recovery_tray_qs.count()
        recovery_delinked = recovery_tray_qs.filter(delink_tray=True).count()
        total_trays += recovery_total
        delinked_trays += recovery_delinked
    
        if total_trays > 0 and total_trays == delinked_trays:
            return {
                'status': 'Yet to Release',
                'remaining_qty': 0,
                'color': '#721c24',
                'bg_color': '#f8d7da',
                'border_color': '#f5c6cb'
            }
            
        jig_detail = JigDetails.objects.filter(
            lot_id=stock_model.lot_id,
            draft_save=True
        ).first()
        
        if jig_detail:
            return {
                'status': 'Draft',
                'remaining_qty': stock_model.jig_physical_qty or 0,
                'color': '#0c5460',
                'bg_color': '#d1ecf1',
                'border_color': '#9adeed'
            }
        
    
        if jig_physical_qty > 0:
            return {
                'status': 'Draft',
                'remaining_qty': jig_physical_qty,
                'color': '#0c5460',
                'bg_color': '#d1ecf1',
                'border_color': '#9adeed'
            }
        else:
            return {
                'status': 'Yet to Start',
                'remaining_qty': 0,
                'color': '#856404',
                'bg_color': '#fff3cd',
                'border_color': '#ffc107'
            }

    def calculate_batch_status(self, lot_id):
        """
        Keep the original method for backward compatibility
        """
        # Check TotalStockModel first
        tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if not tsm:
            # Check RecoveryStockModel if not found in TotalStockModel
            tsm = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            
        return self.calculate_batch_status_efficient(tsm)


@method_decorator(login_required, name='dispatch')

class CheckMeaningfulDraftView(View):
    def get(self, request):
        lot_id = request.GET.get('lot_id')
        
        if not lot_id:
            return JsonResponse({
                'has_meaningful_draft': False,
                'reason': 'No lot ID provided'
            })
        
        # Get the JigDetails for this lot
        jig_detail = JigDetails.objects.filter(
            lot_id=lot_id,
            draft_save=True
        ).first()
        
        if not jig_detail:
            return JsonResponse({
                'has_meaningful_draft': False,
                'reason': 'No draft found for this lot'
            })
        
        # Check if actual tray work has been done (same logic as backend)
        has_tray_work = False
        reasons = []
        
        # Check delink tray data
        filled_delink_trays = 0
        if jig_detail.delink_tray_data:
            for tray in jig_detail.delink_tray_data:
                tray_id = tray.get('tray_id', '').strip()
                if tray_id:
                    filled_delink_trays += 1
                    has_tray_work = True
            reasons.append(f"Delink: {filled_delink_trays}/{len(jig_detail.delink_tray_data)} filled")
        
        # Check half filled tray data
        filled_half_trays = 0
        if jig_detail.half_filled_tray_data:
            for tray in jig_detail.half_filled_tray_data:
                tray_id = tray.get('tray_id', '').strip()
                tray_qty = tray.get('tray_quantity', 0)
                if tray_id or tray_qty > 0:
                    filled_half_trays += 1
                    has_tray_work = True
            reasons.append(f"Half-filled: {filled_half_trays}/{len(jig_detail.half_filled_tray_data)} filled")
        
        # Final decision
        reason = "No tray scanning work done" if not has_tray_work else f"Tray work found: {', '.join(reasons)}"
        
        return JsonResponse({
            'has_meaningful_draft': has_tray_work,
            'reason': reason,
            'jig_qr_id': jig_detail.jig_qr_id or 'None',
            'lot_count': len(jig_detail.lot_id_quantities or {})
        })
@method_decorator(login_required, name='dispatch')
class ClearSpecificLotDraftView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            lot_id = data.get('lot_id')
            
            if not lot_id:
                return JsonResponse({
                    'success': False,
                    'error': 'No lot ID provided'
                })
            
            # Find drafts that contain this specific lot_id
            drafts_to_update = JigDetails.objects.filter(
                draft_save=True
            )
            
            updated_count = 0
            
            for draft in drafts_to_update:
                # Check if this draft contains the lot_id
                if (draft.lot_id_quantities and 
                    lot_id in draft.lot_id_quantities):
                    
                    # Remove the lot_id from lot_id_quantities
                    updated_quantities = draft.lot_id_quantities.copy()
                    del updated_quantities[lot_id]
                    
                    # Remove from other related fields
                    updated_lot_ids = [lid for lid in (draft.new_lot_ids or []) if lid != lot_id]
                    
                    # Filter tray data to remove entries for this lot_id
                    updated_delink_data = []
                    if draft.delink_tray_data:
                        updated_delink_data = [
                            tray for tray in draft.delink_tray_data 
                            if tray.get('lot_id') != lot_id
                        ]
                    
                    updated_half_filled_data = []
                    if draft.half_filled_tray_data:
                        updated_half_filled_data = [
                            tray for tray in draft.half_filled_tray_data 
                            if tray.get('lot_id') != lot_id
                        ]
                    
                    # Check if draft still has meaningful content
                    if len(updated_quantities) == 0:
                        # No lots left - delete the entire draft
                        draft.delete()
                        updated_count += 1
                        print(f"Deleted entire draft - no lots remaining")
                    elif len(updated_quantities) == 1:
                        # Only one lot left - check if it has tray work
                        has_tray_work = False
                        
                        # Check delink tray data
                        for tray in updated_delink_data:
                            if tray.get('tray_id', '').strip():
                                has_tray_work = True
                                break
                        
                        # Check half filled tray data
                        if not has_tray_work:
                            for tray in updated_half_filled_data:
                                if (tray.get('tray_id', '').strip() or 
                                    tray.get('tray_quantity', 0) > 0):
                                    has_tray_work = True
                                    break
                        
                        if not has_tray_work and not draft.jig_qr_id:
                            # No meaningful content left - delete draft
                            draft.delete()
                            updated_count += 1
                            print(f"Deleted draft - single lot but no meaningful content")
                        else:
                            # Update the draft with remaining content
                            draft.lot_id_quantities = updated_quantities
                            draft.new_lot_ids = updated_lot_ids
                            draft.delink_tray_data = updated_delink_data
                            draft.half_filled_tray_data = updated_half_filled_data
                            
                            # Recalculate total cases loaded
                            draft.total_cases_loaded = sum(updated_quantities.values())
                            
                            draft.save()
                            updated_count += 1
                            print(f"Updated draft - single lot with meaningful content")
                    else:
                        # Multiple lots remain - update the draft
                        draft.lot_id_quantities = updated_quantities
                        draft.new_lot_ids = updated_lot_ids
                        draft.delink_tray_data = updated_delink_data
                        draft.half_filled_tray_data = updated_half_filled_data
                        
                        # Recalculate total cases loaded
                        draft.total_cases_loaded = sum(updated_quantities.values())
                        
                        draft.save()
                        updated_count += 1
                        print(f"Updated multi-model draft - {len(updated_quantities)} lots remaining")
            
            if updated_count > 0:
                return JsonResponse({
                    'success': True,
                    'message': f'Successfully removed lot {lot_id} from {updated_count} draft(s)'
                })
            else:
                return JsonResponse({
                    'success': True,
                    'message': f'No drafts found containing lot {lot_id}'
                })
                
        except Exception as e:
            print(f"Error clearing specific lot draft: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to clear draft: {str(e)}'
            })
            
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JIGSaveIPPickRemarkAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            remark = data.get('remark', '').strip()
            if not lot_id:
                return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)
            # Try TotalStockModel first
            stock_obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
            if not stock_obj:
                # If not found, try RecoveryStockModel
                stock_obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
                if not stock_obj:
                    return JsonResponse({'success': False, 'error': 'Lot not found in either model'}, status=404)
            stock_obj.jig_pick_remarks = remark
            stock_obj.save(update_fields=['jig_pick_remarks'])
            return JsonResponse({'success': True, 'message': 'Remark saved'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@require_POST
def save_jig_unload_draft(request):
    """Save draft data for Jig Unloading"""
    try:
        data = json.loads(request.body)
        
        # Extract main fields
        lot_id = data.get('lot_id', '').strip()
        model_number = data.get('model_number', '').strip()
        trays = data.get('trays', [])
        
        if not lot_id or not model_number:
            return JsonResponse({
                'success': False, 
                'error': 'lot_id and model_number are required'
            })
        
        if not trays:
            return JsonResponse({
                'success': False, 
                'error': 'Tray data is required'
            })
        
        # Prepare draft data JSON
        draft_json = {
            'model_number': model_number,
            'lot_id': lot_id,
            'quantity': data.get('quantity', 0),
            'tray_type': data.get('tray_type', ''),
            'tray_capacity': data.get('tray_capacity', 0),
            'combined_lot_ids': data.get('combined_lot_ids', []),
            'trays': trays,
            'metadata': {
                'total_trays': len(trays),
                'total_qty': sum(int(tray.get('tray_qty', 0)) for tray in trays),
                'saved_at': timezone.now().isoformat()
            }
        }
        
        # Update existing draft or create new one
        draft, created = JigUnloadDraft.objects.update_or_create(
            lot_id=lot_id,
            model_number=model_number,
            defaults={
                'draft_data': draft_json,
                'created_by': getattr(request.user, 'username', 'system')
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Draft {"created" if created else "updated"} successfully',
            'draft_id': draft.draft_id,
            'total_trays': len(trays),
            'created': created
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False, 
            'error': 'Invalid JSON data'
        })
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'error': str(e)
        })


@csrf_exempt  
@require_http_methods(["GET"])
def get_jig_unload_drafts(request):
    """Get all draft records for dropdown/selection"""
    try:
        drafts = JigUnloadDraft.objects.all()
        
        draft_list = []
        for draft in drafts:
            draft_info = {
                'draft_id': draft.draft_id,
                'lot_id': draft.lot_id,
                'model_number': draft.model_number,
                'created_at': draft.created_at.strftime('%d-M-y %H:%M'),
                'updated_at': draft.updated_at.strftime('%d-M-y %H:%M'),
                'total_trays': draft.draft_data.get('metadata', {}).get('total_trays', 0),
                'total_qty': draft.draft_data.get('metadata', {}).get('total_qty', 0),
                'tray_type': draft.draft_data.get('tray_type', 'N/A')
            }
            draft_list.append(draft_info)
            
        return JsonResponse({
            'success': True,
            'drafts': draft_list,
            'total_drafts': len(draft_list)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'error': str(e)
        })


@csrf_exempt
@require_http_methods(["GET"])  
def load_jig_unload_draft(request):
    """Load specific draft data by draft_id"""
    try:
        draft_id = request.GET.get('draft_id')
        
        if not draft_id:
            return JsonResponse({
                'success': False,
                'error': 'draft_id parameter is required'
            })
            
        draft = JigUnloadDraft.objects.filter(draft_id=draft_id).first()
        
        if not draft:
            return JsonResponse({
                'success': False,
                'error': 'Draft not found'
            })
            
        return JsonResponse({
            'success': True,
            'draft_data': draft.draft_data,
            'draft_id': draft.draft_id,
            'last_updated': draft.updated_at.strftime('%d-M-y %H:%M')
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JIGUpdateBatchQuantityAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            batch_id = data.get('batch_id')
            new_quantity = data.get('brass_audit_accepted_qty')
            if not batch_id or new_quantity is None:
                return JsonResponse({'success': False, 'error': 'Missing batch_id or quantity'}, status=400)
            # Find the TotalStockModel for this batch
            stock_obj = TotalStockModel.objects.filter(batch_id__batch_id=batch_id).first()
            if not stock_obj:
                return JsonResponse({'success': False, 'error': 'Stock not found for this batch'}, status=404)
            stock_obj.jig_physical_qty = new_quantity
            stock_obj.jig_physical_qty_edited = True  # <-- Set the flag here
            stock_obj.save(update_fields=['jig_physical_qty', 'jig_physical_qty_edited'])
            return JsonResponse({'success': True, 'message': 'Quantity updated'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class Jig_SaveHoldUnholdReasonAPIView(APIView):
    """
    POST with:
    {
        "remark": "Reason text",
        "action": "hold"  # or "unhold"
    }
    """
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            print("DEBUG: Received lot_id:", lot_id)

            remark = data.get('remark', '').strip()
            action = data.get('action', '').strip().lower()

            if not lot_id or not remark or action not in ['hold', 'unhold']:
                return JsonResponse({'success': False, 'error': 'Missing or invalid parameters.'}, status=400)

            # Try TotalStockModel first
            obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
            if not obj:
                # If not found, try RecoveryStockModel
                obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
                if not obj:
                    return JsonResponse({'success': False, 'error': 'LOT not found.'}, status=404)

            if action == 'hold':
                obj.jig_holding_reason = remark
                obj.jig_hold_lot = True
                obj.jig_release_reason = ''
                obj.jig_release_lot = False
            elif action == 'unhold':
                obj.jig_release_reason = remark
                obj.jig_hold_lot = False
                obj.jig_release_lot = True

            obj.save(update_fields=['jig_holding_reason', 'jig_release_reason', 'jig_hold_lot', 'jig_release_lot'])
            return JsonResponse({'success': True, 'message': 'Reason saved.'})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JIGDeleteBatchAPIView(APIView):
    """
    API endpoint for deleting stock lots from either TotalStockModel or RecoveryStockModel
    Updated to support both stock model types
    """
    
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            stock_lot_id = data.get('stock_lot_id')
            
            if not stock_lot_id:
                return JsonResponse({'success': False, 'error': 'Missing stock_lot_id'}, status=400)
            
            # Try to find the stock lot in TotalStockModel first
            tsm_obj = TotalStockModel.objects.filter(lot_id=stock_lot_id).first()
            
            if tsm_obj:
                print(f"🔍 Found lot_id {stock_lot_id} in TotalStockModel")
                tsm_obj.delete()
                return JsonResponse({
                    'success': True, 
                    'message': f'Stock lot {stock_lot_id} deleted from TotalStockModel',
                    'source': 'TotalStockModel'
                })
            
            # If not found in TotalStockModel, try RecoveryStockModel
            rsm_obj = RecoveryStockModel.objects.filter(lot_id=stock_lot_id).first()
            
            if rsm_obj:
                print(f"🔍 Found lot_id {stock_lot_id} in RecoveryStockModel")
                rsm_obj.delete()
                return JsonResponse({
                    'success': True, 
                    'message': f'Stock lot {stock_lot_id} deleted from RecoveryStockModel',
                    'source': 'RecoveryStockModel'
                })
            
            # Stock lot not found in either model
            print(f"❌ Stock lot {stock_lot_id} not found in either TotalStockModel or RecoveryStockModel")
            return JsonResponse({
                'success': False, 
                'error': f'Stock lot {stock_lot_id} not found in either TotalStockModel or RecoveryStockModel'
            }, status=404)
            
        except Exception as e:
            print(f"Error in JIGDeleteBatchAPIView: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


def get_stock_model_data(lot_id):
    """
    Helper function to get stock model data from either TotalStockModel or RecoveryStockModel
    Returns: (stock_model, is_recovery, original_qty, tray_capacity, model_stock_no)
    """
    try:
        # Try TotalStockModel first
        tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if tsm:
            if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                original_qty = tsm.jig_physical_qty
            else:
                original_qty = tsm.brass_audit_accepted_qty or 0
            
            batch_id = tsm.batch_id if hasattr(tsm, 'batch_id') and tsm.batch_id else None
            tray_capacity = batch_id.tray_capacity if batch_id and hasattr(batch_id, 'tray_capacity') else 9
            model_stock_no = tsm.model_stock_no if hasattr(tsm, 'model_stock_no') else None
            
            return tsm, False, original_qty, tray_capacity, model_stock_no
        
        # Try RecoveryStockModel if not found in TotalStockModel
        rsm = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
        if rsm:
            if hasattr(rsm, 'jig_physical_qty_edited') and rsm.jig_physical_qty_edited and hasattr(rsm, 'jig_physical_qty') and rsm.jig_physical_qty:
                original_qty = rsm.jig_physical_qty
            elif hasattr(rsm, 'brass_audit_accepted_qty'):
                original_qty = rsm.brass_audit_accepted_qty or 0
            else:
                original_qty = getattr(rsm, 'total_stock', 0)
            
            batch_id = rsm.batch_id if hasattr(rsm, 'batch_id') and rsm.batch_id else None
            tray_capacity = batch_id.tray_capacity if batch_id and hasattr(batch_id, 'tray_capacity') else 9
            model_stock_no = rsm.model_stock_no if hasattr(rsm, 'model_stock_no') else None
            
            return rsm, True, original_qty, tray_capacity, model_stock_no
        
        # No stock found in either model
        return None, False, 0, 9, None
        
    except Exception as e:
        print(f"Error in get_stock_model_data for lot {lot_id}: {e}")
        return None, False, 0, 9, None

def generate_optimal_tray_distribution_by_capacity(required_qty, tray_capacity, lot_id, available_tray_ids=None, force_original_qty=None):
    """
    Generate optimal tray distribution using ACTUAL tray quantities from database
    Smart logic: Only use trays where you can consume their full available quantity
    """
    trays_needed = []
    if required_qty <= 0 or tray_capacity <= 0:
        print(f"Invalid inputs: required_qty={required_qty}, tray_capacity={tray_capacity}")
        return trays_needed

    print(f"Generating optimal distribution for {required_qty} pieces using tray capacity {tray_capacity}")

    # Get original quantity to check if we're processing everything
    stock_model, is_recovery, original_qty, _, _ = get_stock_model_data(lot_id)
    is_processing_full_qty = (required_qty >= original_qty)
    
    print(f"Original qty: {original_qty}, Required qty: {required_qty}")
    print(f"Processing full quantity: {is_processing_full_qty}")

    # Get actual tray data with real quantities
    try:
        actual_trays = JigLoadTrayId.objects.filter(
            lot_id=lot_id,
            rejected_tray=False,
            delink_tray=False,
            tray_quantity__gt=0
        ).order_by('tray_id')
        
        actual_tray_data = [(tray.tray_id, tray.tray_quantity) for tray in actual_trays]
        print(f"Actual tray data: {actual_tray_data}")
        
    except Exception as e:
        print(f"Error fetching tray data: {e}")
        actual_tray_data = []

    if not actual_tray_data:
        print("No actual tray data found, using theoretical distribution")
        # Fallback to old logic if no tray data
        full_trays = required_qty // tray_capacity
        remainder = required_qty % tray_capacity
        
        for i in range(full_trays):
            tray_id = f"TRAY-{i+1:03d}"
            trays_needed.append({
                'tray_id': tray_id,
                'tray_quantity': tray_capacity,
                'used_quantity': tray_capacity,
                'original_tray_quantity': tray_capacity,
                'lot_id': lot_id,
                'is_complete': True,
                'is_top_tray': False,
                'theoretical': True,
                'rejected_tray': False,
                'delink_tray': False,
            })
            
        if remainder > 0 and is_processing_full_qty:
            tray_id = f"TRAY-{full_trays+1:03d}"
            trays_needed.append({
                'tray_id': tray_id,
                'tray_quantity': tray_capacity,
                'used_quantity': remainder,
                'original_tray_quantity': tray_capacity,
                'lot_id': lot_id,
                'is_complete': False,
                'is_top_tray': True,
                'theoretical': True,
                'rejected_tray': False,
                'delink_tray': False,
            })
        
        return trays_needed

   # Use actual tray quantities for distribution
    total_used = 0
    for i, (tray_id, actual_qty) in enumerate(actual_tray_data):
        if total_used >= required_qty:
            break
        remaining_needed = required_qty - total_used
        if actual_qty <= remaining_needed:
            # Use full tray
            used_qty = actual_qty
            is_complete = used_qty == tray_capacity
            is_top_tray = False
        else:
            # Use only what is needed from this tray (partial pick)
            used_qty = remaining_needed
            is_complete = False
            is_top_tray = True
        trays_needed.append({
            'tray_id': tray_id,
            'tray_quantity': tray_capacity,
            'used_quantity': used_qty,
            'original_tray_quantity': actual_qty,
            'lot_id': lot_id,
            'is_complete': is_complete,
            'is_top_tray': is_top_tray,
            'theoretical': True,
            'rejected_tray': False,
            'delink_tray': False,
        })
        total_used += used_qty
        status = "complete" if is_complete else "partial"
        print(f"✓ Delink tray {i+1}: {tray_id} using {used_qty}/{tray_capacity} pieces ({status})")

    # Calculate remaining after the loop
    remaining_not_used = required_qty - total_used
    if remaining_not_used > 0:
        print(f"✗ Remainder {remaining_not_used} to be handled manually (optimal: {total_used} pieces)")

    total_distributed = sum(tray['used_quantity'] for tray in trays_needed)
    print(f"Final delink distribution: {len(trays_needed)} trays totaling {total_distributed} pieces")

    return trays_needed


# Function of Half filled Trays
def calculate_half_filled_trays_by_capacity(stock_lot_id, display_qty, jig_capacity, tray_capacity, force_original_qty=None):
    """
    Calculate half filled trays:
    - Use actual tray distribution to find the leftover in the last tray after partial pick.
    """
    half_filled_trays = []
    try:
        print(f"HALF FILLED CALCULATION (USING ACTUAL TRAY DISTRIBUTION):")
        # Get the actual tray distribution for the display_qty
        trays_used = generate_optimal_tray_distribution_by_capacity(
            display_qty, tray_capacity, stock_lot_id
        )
        # Find the last tray used (if any)
        if trays_used:
            last_tray = trays_used[-1]
            tray_id = last_tray['tray_id']
            original_tray_quantity = last_tray['original_tray_quantity']
            used_quantity = last_tray['used_quantity']
            leftover = original_tray_quantity - used_quantity
            print(f"  Last tray: {tray_id}, original: {original_tray_quantity}, used: {used_quantity}, leftover: {leftover}")
            if leftover > 0:
                half_filled_trays.append({
                    'tray_id': tray_id,
                    'tray_quantity': leftover,
                    'original_tray_quantity': original_tray_quantity,
                    'is_top_tray': True,
                    'lot_id': stock_lot_id,
                    'theoretical': True
                })
                print(f"  ✓ HALF-FILLED TRAY: {leftover} pieces (actual leftover in tray)")
            else:
                print("  No leftover in last tray, no half-filled tray needed")
        else:
            print("  No trays used, no half-filled tray needed")
    except Exception as e:
        print(f"Error calculating half filled trays: {str(e)}")
    return half_filled_trays

def generate_multi_model_optimal_distribution(lot_quantities_dict, tray_capacity_dict):
    """
    Generate optimal tray distribution for multiple models/lots.
    TRUE GLOBAL OPTIMIZATION: Cross-lot optimization that may under-fulfill some lots.
    """
    result = {
        'delink_trays': [],
        'half_filled_trays': [],
        'total_delink_qty': 0,
        'lot_distributions': {}
    }
    
    try:
        print(f"=== TRUE GLOBAL CROSS-LOT OPTIMIZATION ===")
        print(f"Lot quantities: {lot_quantities_dict}")
        print(f"Tray capacities: {tray_capacity_dict}")
        
        # Step 1: Collect ALL tray data across ALL lots
        all_trays = []  # Global tray pool
        all_lot_data = {}
        total_required = sum(lot_quantities_dict.values())
        
        for lot_id, required_qty in lot_quantities_dict.items():
            if required_qty <= 0:
                continue
                
            # Get lot data
            stock_model, is_recovery, original_qty, _, model_stock_no = get_stock_model_data(lot_id)
            tray_capacity = tray_capacity_dict.get(lot_id, 12)
            
            # Get plating_stk_no
            plating_stk_no = 'Unknown'
            try:
                if stock_model and hasattr(stock_model, 'batch_id') and stock_model.batch_id:
                    if hasattr(stock_model.batch_id, 'plating_stk_no') and stock_model.batch_id.plating_stk_no:
                        plating_stk_no = stock_model.batch_id.plating_stk_no
                    elif hasattr(stock_model.batch_id, 'model_stock_no') and stock_model.batch_id.model_stock_no:
                        if hasattr(stock_model.batch_id.model_stock_no, 'model_no'):
                            plating_stk_no = stock_model.batch_id.model_stock_no.model_no
                elif model_stock_no and hasattr(model_stock_no, 'model_no'):
                    plating_stk_no = model_stock_no.model_no
                elif stock_model and hasattr(stock_model, 'model_stock_no') and stock_model.model_stock_no:
                    if hasattr(stock_model.model_stock_no, 'model_no'):
                        plating_stk_no = stock_model.model_stock_no.model_no
            except Exception as e:
                print(f"Error getting plating_stk_no for {lot_id}: {e}")
                plating_stk_no = f"LOT-{lot_id}"
            
            # Get actual tray data
            try:
                actual_trays = JigLoadTrayId.objects.filter(
                    lot_id=lot_id, rejected_tray=False, delink_tray=False, tray_quantity__gt=0
                ).order_by('tray_id')
                
                for tray in actual_trays:
                    usable_qty = min(tray.tray_quantity, tray_capacity)
                    all_trays.append({
                        'tray_id': tray.tray_id,
                        'actual_qty': tray.tray_quantity,
                        'usable_qty': usable_qty,
                        'lot_id': lot_id,
                        'tray_capacity': tray_capacity,
                        'plating_stk_no': plating_stk_no,
                        'is_partial': usable_qty < tray_capacity,
                        'priority': 1 if usable_qty < tray_capacity else 2  # Partials first
                    })
                    
            except Exception as e:
                print(f"Error fetching tray data for {lot_id}: {e}")
            
            # Store lot metadata
            all_lot_data[lot_id] = {
                'required_qty': required_qty,
                'original_qty': original_qty,
                'tray_capacity': tray_capacity,
                'plating_stk_no': plating_stk_no,
                'stock_model': stock_model,
                'is_recovery': is_recovery
            }
        
        # Step 2: Global tray selection algorithm
        # Sort all trays: partials first, then by lot order
        all_trays.sort(key=lambda x: (x['priority'], list(lot_quantities_dict.keys()).index(x['lot_id'])))
        
        total_available = sum(tray['usable_qty'] for tray in all_trays)
        print(f"Global pool: {len(all_trays)} trays, {total_available} pieces available")
        print(f"Total required: {total_required} pieces")
        
        # Step 3: Global tray allocation with aggressive early stopping
        selected_trays = []
        total_allocated = 0
        lot_allocations = {lot_id: 0 for lot_id in lot_quantities_dict.keys()}
        
        for tray in all_trays:
            if total_allocated >= total_required:
                print(f"✓ Global requirement satisfied: {total_allocated} >= {total_required}")
                break
            
            remaining_needed = total_required - total_allocated
            lot_remaining = lot_quantities_dict[tray['lot_id']] - lot_allocations[tray['lot_id']]
            
            # AGGRESSIVE STOPPING: Don't use complete trays if ANY lot would be over-satisfied
            if not tray['is_partial']:
                # Check if using this tray would over-satisfy this lot inefficiently
                if tray['usable_qty'] > lot_remaining:
                    waste_ratio = (tray['usable_qty'] - lot_remaining) / tray['usable_qty']
                    if waste_ratio > 0.25:  # Don't waste >25% of a complete tray
                        print(f"✗ Early stop: {tray['tray_id']} would waste {waste_ratio:.1%} ({tray['usable_qty'] - lot_remaining}/{tray['usable_qty']} pieces)")
                        continue
                
                # Also check global efficiency
                global_efficiency = remaining_needed / tray['usable_qty']
                if global_efficiency < 0.6:  # Don't use complete tray if we need <60% globally
                    print(f"✗ Global stop: {tray['tray_id']} global efficiency {global_efficiency:.1%} too low")
                    continue
            
            # Calculate allocation amount
            allocated_qty = min(tray['usable_qty'], lot_remaining, remaining_needed)
            
            # CRITICAL: Apply "no artificial partials" rule like single-model
            if not tray['is_partial']:
                # Don't create artificial partials from complete trays
                if allocated_qty < tray['usable_qty']:
                    print(f"✗ No artificial partial: {tray['tray_id']} would create {allocated_qty}/{tray['usable_qty']} artificial partial")
                    continue
            
            # Allocate this tray - only if we can use it completely OR it's already partial
            tray['allocated_qty'] = allocated_qty
            selected_trays.append(tray)
            total_allocated += allocated_qty
            lot_allocations[tray['lot_id']] += allocated_qty
            
            status = "partial" if tray['is_partial'] else "complete"
            print(f"✓ Global allocate: {tray['tray_id']} ({tray['lot_id']}) using {allocated_qty}/{tray['tray_capacity']} pieces ({status})")
        
        print(f"Global allocation complete: {total_allocated} pieces from {len(selected_trays)} trays")
        print(f"Under-allocated by: {total_required - total_allocated} pieces (by design)")

        # Step 4: Convert back to per-lot results
        for lot_id, lot_data in all_lot_data.items():
            lot_trays = [t for t in selected_trays if t['lot_id'] == lot_id]
            lot_allocated = sum(t['allocated_qty'] for t in lot_trays)
            original_required = lot_data['required_qty']
            
            # Convert to expected format
            lot_delink_trays = []
            for i, tray in enumerate(lot_trays):
                tray_data = {
                    'tray_id': f"{tray['plating_stk_no']}-{tray['tray_id']}",
                    'tray_quantity': tray['tray_capacity'],
                    'used_quantity': tray['allocated_qty'],
                    'original_tray_quantity': tray['actual_qty'],
                    'lot_id': lot_id,
                    'plating_stk_no': tray['plating_stk_no'],
                    'is_complete': tray['allocated_qty'] == tray['tray_capacity'],
                    'is_top_tray': tray['allocated_qty'] < tray['tray_capacity'],
                    'theoretical': True,
                    'actual_tray_id': tray['tray_id']
                }
                lot_delink_trays.append(tray_data)
            
            # Calculate remaining pieces for this lot
            lot_under_allocated = original_required - lot_allocated
            print(f"Lot {lot_id}: allocated {lot_allocated}/{original_required}, remaining {lot_under_allocated} pieces")
            
            # Calculate half-filled based on REQUIRED vs ALLOCATED (not original)
            lot_half_filled = []
            if lot_allocated < lot_data['required_qty']:
                remaining_unfulfilled = lot_data['required_qty'] - lot_allocated
                print(f"Half-filled for {lot_id}: {lot_allocated}/{lot_data['required_qty']} allocated, {remaining_unfulfilled} unfulfilled")
                
                if remaining_unfulfilled > 0:
                    lot_half_filled.append({
                        'tray_id': f"{lot_data['plating_stk_no']}-REMAINING",
                        'tray_quantity': remaining_unfulfilled,
                        'original_tray_quantity': lot_data['tray_capacity'],
                        'is_top_tray': True,
                        'lot_id': lot_id,
                        'plating_stk_no': lot_data['plating_stk_no'],
                        'theoretical': True,
                        'is_multi_model': True
                    })
                    print(f"✓ Half-filled tray created: {remaining_unfulfilled} pieces")
            else:
                print(f"No half-filled needed for {lot_id}: {lot_allocated}/{lot_data['required_qty']} (fully satisfied)")
            
            # Store lot results
            result['lot_distributions'][lot_id] = {
                'required_qty': lot_data['required_qty'],
                'original_qty': lot_data['original_qty'],
                'delink_qty': lot_allocated,
                'delink_trays': lot_delink_trays,
                'half_filled_trays': lot_half_filled,
                'tray_capacity': lot_data['tray_capacity'],
                'is_processing_full_qty': lot_allocated >= lot_data['original_qty'],
                'plating_stk_no': lot_data['plating_stk_no'],
                'global_under_fulfilled': lot_allocated < lot_data['required_qty'],
                'remaining_pieces': lot_under_allocated
            }
            
            # Add to combined results
            result['delink_trays'].extend(lot_delink_trays)
            result['half_filled_trays'].extend(lot_half_filled)
            result['total_delink_qty'] += lot_allocated
        
        return result
        
    except Exception as e:
        print(f"Error in multi-model distribution: {str(e)}")
        import traceback
        traceback.print_exc()
        return result

@api_view(['POST'])
def get_multi_model_distribution(request):
    """
    API endpoint for multi-model optimal tray distribution.
    Updated to support both TotalStockModel and RecoveryStockModel.
    """
    try:
        data = request.data
        lot_quantities = data.get('lot_quantities', {})
        
        if not lot_quantities:
            return Response({'error': 'lot_quantities is required'}, status=400)
        
        # Get tray capacities for each lot using helper function
        tray_capacities = {}
        for lot_id in lot_quantities.keys():
            try:
                stock_model, is_recovery, _, tray_capacity, _ = get_stock_model_data(lot_id)
                if stock_model:
                    tray_capacities[lot_id] = tray_capacity
                    print(f"Lot {lot_id} ({'Recovery' if is_recovery else 'Regular'}): tray_capacity = {tray_capacity}")
                else:
                    tray_capacities[lot_id] = 12  # Default
                    print(f"Lot {lot_id}: No stock found, using default tray_capacity = 12")
            except Exception as e:
                print(f"Error getting tray capacity for lot {lot_id}: {e}")
                tray_capacities[lot_id] = 12
        
        # Generate optimal distribution
        distribution = generate_multi_model_optimal_distribution(
            lot_quantities, 
            tray_capacities
        )
        
        return Response({
            'success': True,
            'distribution': distribution
        })
        
    except Exception as e:
        print(f"Error in get_multi_model_distribution: {str(e)}")
        return Response({'error': str(e)}, status=500)


@api_view(['GET'])
def fetch_jig_related_data(request):
    stock_lot_id = request.GET.get('stock_lot_id')
    adjusted_qty = request.GET.get('adjusted_qty') 
    
    if not stock_lot_id:
        print("No stock_lot_id provided")
        return Response({'error': 'stock_lot_id is required'}, status=400)

    try:
        # Try to fetch from TotalStockModel first
        tsm = TotalStockModel.objects.filter(lot_id=stock_lot_id).first()
        rsm = None  # RecoveryStockModel
        is_recovery = False
        
        # If not found in TotalStockModel, check RecoveryStockModel
        if not tsm:
            rsm = RecoveryStockModel.objects.filter(lot_id=stock_lot_id).first()
            if not rsm:
                print(f"No stock found for lot_id: {stock_lot_id} in both TotalStockModel and RecoveryStockModel")
                return Response({'error': 'No stock data found for this lot_id'}, status=404)
            is_recovery = True
            print(f"Found lot_id {stock_lot_id} in RecoveryStockModel")
        else:
            print(f"Found lot_id {stock_lot_id} in TotalStockModel")

        # Use the appropriate stock model
        stock_model = rsm if is_recovery else tsm
        
        # Fetch ModelMasterCreation or RecoveryMasterCreation
        if is_recovery:
            # For recovery, get the batch_id (which should be RecoveryMasterCreation)
            mmc = stock_model.batch_id if stock_model.batch_id else None
            # Get model_stock_no from RecoveryMasterCreation if available
            model_stock_no = stock_model.model_stock_no if hasattr(stock_model, 'model_stock_no') else None
        else:
            # For regular stock
            mmc = stock_model.batch_id if stock_model.batch_id else None
            model_stock_no = stock_model.model_stock_no if hasattr(stock_model, 'model_stock_no') else None
        
        # *** UPDATED: Get both model_no and plating_stk_no ***
        if mmc and hasattr(mmc, 'model_stock_no') and mmc.model_stock_no:
            model_no = mmc.model_stock_no.model_no
        elif model_stock_no:
            model_no = model_stock_no.model_no
        else:
            model_no = None
            
        # *** NEW: Get plating_stk_no from master creation object ***
        plating_stk_no = None
        if mmc and hasattr(mmc, 'plating_stk_no'):
            plating_stk_no = mmc.plating_stk_no
        
        print(f"Model No: {model_no}, Plating Stk No: {plating_stk_no}")
        
        # Get tray capacity from batch model
        tray_capacity = mmc.tray_capacity if mmc and hasattr(mmc, 'tray_capacity') else 9  # Default to 9 if not found
        
        # Get images for the model
        images = []
        image_source = None
        
        if mmc and hasattr(mmc, 'model_stock_no') and mmc.model_stock_no:
            image_source = mmc.model_stock_no
        elif model_stock_no:
            image_source = model_stock_no
            
        if image_source and hasattr(image_source, 'images'):
            for img in image_source.images.all():
                if hasattr(img, 'master_image') and img.master_image:
                    images.append(img.master_image.url)
                    
        if not images:
            images = [static('assets/images/imagePlaceholder.jpg')]

        # Fetch JigLoadingMaster - use the appropriate model_stock_no
        jig_model_stock_no = model_stock_no or (mmc.model_stock_no if mmc and hasattr(mmc, 'model_stock_no') else None)
        jig_master = JigLoadingMaster.objects.filter(model_stock_no=jig_model_stock_no).first() if jig_model_stock_no else None
        jig_capacity = jig_master.jig_capacity if jig_master else 0

        # Calculate remaining quantity - handle both stock types
        def calculate_remaining_quantity_enhanced(lot_id):
            try:
                # Get original quantity based on stock type
                if is_recovery:
                    # For recovery stock, use appropriate fields
                    if hasattr(stock_model, 'jig_physical_qty_edited') and stock_model.jig_physical_qty_edited and hasattr(stock_model, 'jig_physical_qty') and stock_model.jig_physical_qty:
                        original_qty = stock_model.jig_physical_qty
                    elif hasattr(stock_model, 'brass_audit_accepted_qty'):
                        original_qty = stock_model.brass_audit_accepted_qty or 0
                    else:
                        # Fallback to other quantity fields that might exist in RecoveryStockModel
                        original_qty = getattr(stock_model, 'total_stock', 0)
                else:
                    # For regular stock
                    if stock_model.jig_physical_qty_edited and stock_model.jig_physical_qty:
                        original_qty = stock_model.jig_physical_qty
                    else:
                        original_qty = stock_model.brass_audit_accepted_qty or 0

                if original_qty <= 0:
                    return 0

                jig_details = JigDetails.objects.filter(
                    Q(lot_id=lot_id) | Q(new_lot_ids__contains=[lot_id]),
                    draft_save=False
                )

                if not jig_details.exists():
                    return original_qty

                total_used_qty = 0
                for jig_detail in jig_details:
                    if jig_detail.lot_id_quantities and lot_id in jig_detail.lot_id_quantities:
                        used_qty = jig_detail.lot_id_quantities.get(lot_id, 0)
                        if isinstance(used_qty, (int, float)):
                            total_used_qty += int(used_qty)
                        elif isinstance(used_qty, str) and used_qty.isdigit():
                            total_used_qty += int(used_qty)

                return max(0, original_qty - total_used_qty)

            except Exception as e:
                print(f"Error calculating remaining quantity: {str(e)}")
                return 0

        # Calculate remaining quantity - handle both stock types
        remaining_qty = calculate_remaining_quantity_enhanced(stock_lot_id)

        # Determine base quantity to use
        if adjusted_qty and adjusted_qty.isdigit():
            # Use adjusted quantity if provided (from faulty slots calculation)
            base_qty = int(adjusted_qty)
            print(f"Using adjusted quantity: {base_qty}")
        elif hasattr(stock_model, 'jig_physical_qty') and stock_model.jig_physical_qty and stock_model.jig_physical_qty > 0:
            # Use edited physical quantity if available
            base_qty = stock_model.jig_physical_qty
            print(f"Using jig_physical_qty: {base_qty}")
        else:
            # Use remaining quantity as fallback
            base_qty = remaining_qty
            print(f"Using remaining quantity: {base_qty}")

        # CRITICAL: Always cap by jig capacity - this is the main fix
        if jig_capacity > 0:
            display_qty = min(base_qty, jig_capacity)
            if base_qty > jig_capacity:
                print(f"⚠️ Quantity capped: {base_qty} → {display_qty} (jig capacity: {jig_capacity})")
        else:
            display_qty = base_qty

        print(f"Final display_qty: {display_qty}, remaining_qty: {remaining_qty}, jig_capacity: {jig_capacity}")
        # Get available tray IDs for reference
        actual_trays_queryset = JigLoadTrayId.objects.filter(
            lot_id=stock_lot_id,
            rejected_tray=False,
            delink_tray=False,
            tray_quantity__gt=0
        ).order_by('tray_id')
        
        available_tray_ids = [tray.tray_id for tray in actual_trays_queryset]

        # Force override for adjusted quantity calculations
        force_qty = display_qty if adjusted_qty and adjusted_qty.isdigit() else None
        if force_qty:
            print(f"🔧 Forcing adjusted quantity {force_qty} for distribution calculations")

        # Use optimal distribution based on TRAY CAPACITY
        if display_qty > 0:
            current_trays_data = generate_optimal_tray_distribution_by_capacity(
                display_qty, 
                tray_capacity, 
                stock_lot_id, 
                available_tray_ids,
                force_original_qty=force_qty  # NEW: Pass adjusted qty
            )
        else:
            current_trays_data = []

        # Calculate actual delinked qty (sum of complete trays only)
        actual_delinked_qty = sum(tray['used_quantity'] for tray in current_trays_data)

        # Calculate half filled trays using actual delink qty
        half_filled_trays = calculate_half_filled_trays_by_capacity(
            stock_lot_id, 
            display_qty,  # Still pass display_qty for complete tray calculation
            jig_capacity, 
            tray_capacity,
            force_original_qty=force_qty
        )
        # Get original tray records for reference
        original_trays = JigLoadTrayId.objects.filter(lot_id=stock_lot_id)
        original_trays_data = [
            {
                'tray_id': tray.tray_id,
                'tray_quantity': tray.tray_quantity,
                'lot_id': tray.lot_id
            }
            for tray in original_trays
        ]

        # Check for showing half filled table - handle both stock types
        accepted_qty = 0
        if is_recovery:
            accepted_qty = getattr(stock_model, 'brass_audit_accepted_qty', 0) or getattr(stock_model, 'total_stock', 0)
        else:
            accepted_qty = stock_model.brass_audit_accepted_qty or 0
            
        show_half_filled_table = (
            len(half_filled_trays) > 0 and 
            display_qty < accepted_qty
        )

        # Handle draft data
        draft_data = {'has_draft': False}
        try:
            draft_jig = JigDetails.objects.filter(
                lot_id=stock_lot_id, 
                draft_save=True
            ).order_by('-id').first()
            
            if draft_jig:
                draft_half_filled_trays = draft_jig.half_filled_tray_data or []
                
                # Convert draft data to match expected format if needed
                formatted_draft_half_filled = []
                for item in draft_half_filled_trays:
                    formatted_item = {
                        'tray_id': item.get('tray_id', ''),
                        'tray_quantity': item.get('tray_quantity', 0),
                        'original_tray_quantity': item.get('original_tray_quantity', item.get('tray_quantity', 0)),
                        'is_top_tray': item.get('is_top_tray', False),
                        'lot_id': item.get('lot_id', stock_lot_id),
                        'model_no': item.get('model_no', ''),
                        'is_multi_model': item.get('is_multi_model', False),
                        'row_index': item.get('row_index', 1),
                        'from_draft': True
                    }
                    formatted_draft_half_filled.append(formatted_item)
                
                print(f"📄 Loading draft half_filled_tray_data: {len(formatted_draft_half_filled)} items")
                for item in formatted_draft_half_filled:
                    print(f"   - {item['tray_id']}: {item['tray_quantity']} pieces, top_tray: {item['is_top_tray']}")
                
                draft_data = {
                    'has_draft': True,
                    'jig_qr_id': draft_jig.jig_qr_id,
                    'faulty_slots': draft_jig.faulty_slots,
                    'total_cases_loaded': draft_jig.total_cases_loaded,
                    'empty_slots': draft_jig.empty_slots,
                    'no_of_model_cases': draft_jig.no_of_model_cases,
                    'new_lot_ids': draft_jig.new_lot_ids,
                    'lot_id_quantities': draft_jig.lot_id_quantities,
                    'no_of_cycle': draft_jig.no_of_cycle,
                    'draft_id': draft_jig.id,
                    'delink_tray_data': draft_jig.delink_tray_data or [],
                    'half_filled_tray_data': formatted_draft_half_filled,
                    'trays': current_trays_data,
                }
                # --- DO NOT override half_filled_trays here ---
                # if formatted_draft_half_filled:
                #     half_filled_trays = formatted_draft_half_filled
                #     print(f"✅ Using draft half_filled_tray_data instead of calculated data")
                
        except Exception as e:
            print(f"Error getting draft data: {str(e)}")

        print("==== OPTIMAL TRAY DISTRIBUTION SUMMARY ====")
        print(f"Stock type: {'Recovery' if is_recovery else 'Regular'}")
        print(f"Required qty: {display_qty}")
        print(f"Tray capacity: {tray_capacity}")
        
        if jig_capacity and jig_capacity > 0:
            original_display_qty = display_qty
            display_qty = min(display_qty, jig_capacity)
            if original_display_qty != display_qty:
                print(f"🔒 FINAL CAP APPLIED: {original_display_qty} → {display_qty} (jig_capacity: {jig_capacity})")
        else:
            print(f"⚠️ Warning: jig_capacity is {jig_capacity}, no capping applied")

        print(f"🎯 FINAL API RESPONSE display_qty: {display_qty}")

        return Response({
            'model_no': model_no,
            'plating_stk_no': plating_stk_no,  # *** NEW: Add plating_stk_no ***
            'model_images': images,
            'ep_bath_type': getattr(mmc, 'ep_bath_type', None) if mmc else None,
            'jig_capacity': jig_capacity,
            'tray_capacity': tray_capacity,
            'trays': current_trays_data,
            'original_trays': original_trays_data,
            'plating_color': getattr(mmc, 'plating_color', None) if mmc else None,
            'polish_finish': getattr(mmc, 'polish_finish', None) if mmc else None,
            'version': getattr(mmc.version, 'version_name', None) if mmc and hasattr(mmc, 'version') and mmc.version else None,
            'remaining_quantity': remaining_qty,
            'display_qty': display_qty,
            'original_quantity': accepted_qty,
            'edited_quantity': getattr(stock_model, 'jig_physical_qty', 0) if hasattr(stock_model, 'jig_physical_qty') else 0,
            'is_fully_processed': remaining_qty <= 0,
            'can_add_more_jigs': remaining_qty > 0,
            'draft_data': draft_data,
            'tray_distribution_method': 'optimal_by_physical_constraints',
            'half_filled_trays': half_filled_trays,
            'show_half_filled_table': show_half_filled_table,
            'jig_fully_utilized': display_qty >= accepted_qty,
            'is_recovery_stock': is_recovery,  # Add this flag to identify stock type in frontend
        })

    except Exception as e:
        print(f"Error in fetch_jig_related_data: {str(e)}")
        return Response({'error': f'Internal server error: {str(e)}'}, status=500)
   
       
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JigDetailsSaveAPIView(APIView):
    """
    API endpoint for saving JigDetails from the right side modal
    Updated to support both TotalStockModel and RecoveryStockModel
    Fixed to ensure draft saves contain exactly the same data as final saves
    """
    
    def get_stock_model_and_tray_models(self, lot_id):
        """
        Helper function to determine stock model type and corresponding tray models
        Returns: (stock_model, is_recovery, tray_models_dict)
        """
        # Try TotalStockModel first
        tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if tsm:
            tray_models = {
                'TrayId': TrayId,
                'IPTrayId': IPTrayId,
                'BrassTrayId': BrassTrayId,
                'BrassAuditTrayId': BrassAuditTrayId,
                'IQFTrayId': IQFTrayId,
                'DPTrayId_History': DPTrayId_History,
                'JigLoadTrayId': JigLoadTrayId
            }
            return tsm, False, tray_models
        
        # Try RecoveryStockModel if not found in TotalStockModel
        rsm = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
        if rsm:
            tray_models = {
                'TrayId': RecoveryTrayId,
                'IPTrayId': RecoveryIPTrayId,
                'BrassTrayId': RecoveryBrassTrayId,
                'BrassAuditTrayId': RecoveryBrassAuditTrayId,
                'IQFTrayId': RecoveryIQFTrayId,
                'DPTrayId_History': DPTrayId_History,
                'JigLoadTrayId': JigLoadTrayId
            }
            return rsm, True, tray_models
        
        return None, False, {}

    def calculate_lot_quantities_and_filter_lots(self, lot_ids, lot_id_quantities, delink_tray_data, half_filled_tray_data, is_draft, primary_lot_id):
        """
        Unified method to calculate lot quantities and filter lots consistently for both draft and final saves
        Returns: (filtered_lot_ids, filtered_lot_id_quantities, filtered_model_numbers, recalculated_total_cases_loaded)
        """
        print(f"🔧 Starting lot calculation - is_draft: {is_draft}")
        print(f"📊 Original lot_ids: {lot_ids}")
        print(f"📊 Original lot_id_quantities: {lot_id_quantities}")
        
        # *** STEP 1: RECALCULATE lot_id_quantities BASED ON DELINK_TRAY_DATA ***
        recalculated_lot_id_quantities = {}
        recalculated_total_cases_loaded = 0
        
        if delink_tray_data:
            print(f"🔄 Recalculating quantities based on delink_tray_data: {delink_tray_data}")
            
            for delink_entry in delink_tray_data:
                lot_id = delink_entry.get('lot_id', '').strip()
                expected_usage = int(delink_entry.get('expected_usage', 0))
                
                if lot_id and expected_usage > 0:
                    if lot_id not in recalculated_lot_id_quantities:
                        recalculated_lot_id_quantities[lot_id] = 0
                    recalculated_lot_id_quantities[lot_id] += expected_usage
                    recalculated_total_cases_loaded += expected_usage
            
            print(f"✅ Recalculated lot_id_quantities: {recalculated_lot_id_quantities}")
            print(f"✅ Recalculated total_cases_loaded: {recalculated_total_cases_loaded}")
            
            # Update the variables with recalculated values
            lot_id_quantities = recalculated_lot_id_quantities
            total_cases_loaded = recalculated_total_cases_loaded
            lot_ids = list(recalculated_lot_id_quantities.keys())

            # PATCH: Also include lots from half_filled_tray_data
            half_filled_lot_ids = set(entry.get('lot_id', '').strip() for entry in half_filled_tray_data if entry.get('lot_id', '').strip())
            for lot_id in half_filled_lot_ids:
                if lot_id and lot_id not in lot_ids:
                    lot_ids.append(lot_id)
                    # Optionally, set quantity to 0 or sum from half_filled_tray_data
                    recalculated_lot_id_quantities[lot_id] = sum(int(entry.get('tray_quantity', 0)) for entry in half_filled_tray_data if entry.get('lot_id', '').strip() == lot_id)

            
        else:
            print(f"⚠️ No delink_tray_data found, using original quantities")
            total_cases_loaded = sum(int(qty) for qty in lot_id_quantities.values())

        # *** STEP 2: FILTER LOTS BASED ON AVAILABILITY (SAME LOGIC FOR BOTH DRAFT AND FINAL) ***
        filtered_lot_ids = []
        filtered_lot_id_quantities = {}
        
        for lot_id in lot_ids:
            stock_model, is_recovery, _ = self.get_stock_model_and_tray_models(lot_id)
            
            if not stock_model:
                print(f"⚠️ No stock model found for lot_id: {lot_id}")
                continue
            
            # Calculate original qty based on stock type
            if is_recovery:
                if hasattr(stock_model, 'jig_physical_qty_edited') and stock_model.jig_physical_qty_edited and hasattr(stock_model, 'jig_physical_qty') and stock_model.jig_physical_qty:
                    original_qty = stock_model.jig_physical_qty
                elif hasattr(stock_model, 'brass_audit_accepted_qty'):
                    original_qty = stock_model.brass_audit_accepted_qty or 0
                else:
                    original_qty = getattr(stock_model, 'total_stock', 0)
            else:
                if stock_model.jig_physical_qty_edited and stock_model.jig_physical_qty:
                    original_qty = stock_model.jig_physical_qty
                else:
                    original_qty = stock_model.brass_audit_accepted_qty or 0
            
            # Calculate used qty (exclude current draft if updating)
            from django.db.models import Q
            jig_details = JigDetails.objects.filter(
                Q(lot_id=lot_id) | Q(new_lot_ids__contains=[lot_id]),
                draft_save=False
            )
            
            # If we're updating a draft, exclude it from used quantity calculation
            draft_id = getattr(self, '_current_draft_id', None)
            if draft_id:
                jig_details = jig_details.exclude(id=draft_id)
            
            total_used_qty = 0
            for jig_detail in jig_details:
                if jig_detail.lot_id_quantities and lot_id in jig_detail.lot_id_quantities:
                    used_qty = jig_detail.lot_id_quantities.get(lot_id, 0)
                    if isinstance(used_qty, (int, float)):
                        total_used_qty += int(used_qty)
                    elif isinstance(used_qty, str) and used_qty.isdigit():
                        total_used_qty += int(used_qty)
                        
            remaining_qty = max(0, original_qty - total_used_qty)
            
            print(f"Lot {lot_id} ({'Recovery' if is_recovery else 'Regular'}): original={original_qty}, used={total_used_qty}, remaining={remaining_qty}")
            
            # *** CONSISTENT FILTERING: Only include lots with remaining quantity > 0 OR if it's in current request ***
            if remaining_qty > 0 or lot_id in lot_id_quantities:
                filtered_lot_ids.append(lot_id)
                if lot_id in lot_id_quantities:
                    filtered_lot_id_quantities[lot_id] = lot_id_quantities[lot_id]
            else:
                print(f"⚠️ Excluding lot {lot_id} - no remaining quantity and not in current request")
        
        # Update primary_lot_id if needed
        if filtered_lot_ids and (primary_lot_id not in filtered_lot_ids):
            primary_lot_id = filtered_lot_ids[0] if filtered_lot_ids else ''
        
        print(f"🔄 Final filtered lot_ids: {filtered_lot_ids}")
        print(f"🔄 Final filtered lot_id_quantities: {filtered_lot_id_quantities}")
        
        return filtered_lot_ids, filtered_lot_id_quantities, recalculated_total_cases_loaded, primary_lot_id

    def calculate_actual_lot_quantities(self, lot_id_quantities, total_cases_loaded, faulty_slots, empty_slots, primary_lot_id, is_draft):
        """
        Calculate actual lot quantities consistently for both draft and final saves
        """
        print(f"🧮 Calculating actual lot quantities - is_draft: {is_draft}")
        print(f"📊 Input: lot_id_quantities={lot_id_quantities}, total_cases_loaded={total_cases_loaded}")
        print(f"📊 Input: faulty_slots={faulty_slots}, empty_slots={empty_slots}")
        
        # Calculate total original quantity
        total_original_qty = sum(int(qty) for qty in lot_id_quantities.values())
        
        # *** SAME LOGIC FOR BOTH DRAFT AND FINAL SAVES ***
        actual_lot_id_quantities = {}
        
        if total_original_qty > 0 and total_cases_loaded > 0:
            # If total_cases_loaded is less than total_original_qty, use first-fill approach
            if total_cases_loaded < total_original_qty:
                remaining_to_distribute = total_cases_loaded
                
                # Sort lot_ids to ensure consistent order (use primary lot first)
                sorted_lot_ids = sorted(lot_id_quantities.keys())
                if primary_lot_id in sorted_lot_ids:
                    sorted_lot_ids.remove(primary_lot_id)
                    sorted_lot_ids.insert(0, primary_lot_id)
                
                print(f"📋 Distribution order: {sorted_lot_ids}")
                print(f"📋 Total to distribute: {remaining_to_distribute}")
                
                for lot_id in sorted_lot_ids:
                    original_qty = int(lot_id_quantities[lot_id])
                    
                    if remaining_to_distribute > 0:
                        used_qty = min(original_qty, remaining_to_distribute)
                        
                        if used_qty > 0:
                            actual_lot_id_quantities[lot_id] = used_qty
                            remaining_to_distribute -= used_qty
                            print(f"📊 Lot {lot_id}: allocated {used_qty}, remaining to distribute: {remaining_to_distribute}")
                    
                    if remaining_to_distribute <= 0:
                        break
                
                # Handle faulty slots reduction (only if no empty slots)
                if faulty_slots > 0 and empty_slots == 0:
                    reduction_needed = faulty_slots
                    print(f"⚠️ Reducing {reduction_needed} for faulty slots")
                    
                    # Reduce from the last lot first (LIFO approach)
                    for lot_id in reversed(sorted_lot_ids):
                        if lot_id in actual_lot_id_quantities and reduction_needed > 0:
                            current_qty = actual_lot_id_quantities[lot_id]
                            reduction = min(current_qty, reduction_needed)
                            
                            actual_lot_id_quantities[lot_id] -= reduction
                            reduction_needed -= reduction
                            print(f"📊 Reduced {reduction} from lot {lot_id}, new qty: {actual_lot_id_quantities[lot_id]}")
                            
                            # Remove lot if quantity becomes 0
                            if actual_lot_id_quantities[lot_id] <= 0:
                                del actual_lot_id_quantities[lot_id]
                                print(f"📊 Removed lot {lot_id} (quantity became 0)")
                            
                            if reduction_needed <= 0:
                                break
            else:
                # If total_cases_loaded >= total_original_qty, use original quantities
                actual_lot_id_quantities = {k: int(v) for k, v in lot_id_quantities.items()}
                print(f"📊 Using original quantities (total_cases_loaded >= total_original_qty)")
        else:
            # Fallback to original quantities
            actual_lot_id_quantities = {k: int(v) for k, v in lot_id_quantities.items()}
            print(f"📊 Using fallback original quantities")
        
        print(f"✅ Final actual_lot_id_quantities: {actual_lot_id_quantities}")
        return actual_lot_id_quantities

    def post(self, request):
        
        
        try:
            # Parse request data
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            half_filled_tray_data = data.get('half_filled_tray_data', [])

            # Validation: Only block final save if half-filled tray section is shown but tray_id is missing
            if half_filled_tray_data:
                missing_tray_ids = [entry for entry in half_filled_tray_data if not entry.get('tray_id')]
                if missing_tray_ids and not data.get('is_draft', False):
                    return JsonResponse({
                        'success': False,
                        'error': 'Please enter Tray ID for all half-filled trays before saving.'
                    }, status=400)
            # Check if this is a draft save
            is_draft = data.get('is_draft', False)
            
            # Extract required fields from request
            jig_qr_id = data.get('jig_qr_id', '').strip()
            faulty_slots = int(data.get('faulty_slots', 0))
            empty_slots = int(data.get('empty_slots', 0))
            total_cases_loaded = int(data.get('total_cases_loaded', 0))
            
            # Extract model and lot information
            plating_stock_numbers = data.get('plating_stock_numbers', [])  # Changed from model_numbers
            lot_ids = data.get('lot_ids', [])
            lot_id_quantities = data.get('lot_id_quantities', {})
            primary_lot_id = data.get('primary_lot_id', '')
            
            # Extract tray data
            delink_tray_data = data.get('delink_tray_data', [])
            half_filled_tray_data = data.get('half_filled_tray_data', [])
            
            # Validate tray data for duplicates
            tray_pairs = [(entry.get('tray_id', '').strip(), entry.get('lot_id', '').strip()) 
                         for entry in delink_tray_data if entry.get('tray_id', '').strip()]
            duplicates = set([pair for pair in tray_pairs if tray_pairs.count(pair) > 1])
            if duplicates:
                dup_ids = [pair[0] for pair in duplicates]
                return JsonResponse({
                    'success': False,
                    'error': f'Duplicate Tray ID(s) not allowed for same Lot: {", ".join(dup_ids)}'
                }, status=400)

            # Validate half filled tray data
            half_tray_ids = [entry.get('tray_id', '').strip() for entry in half_filled_tray_data if entry.get('tray_id', '').strip()]
            half_duplicates = set([tid for tid in half_tray_ids if half_tray_ids.count(tid) > 1])
            if half_duplicates:
                return JsonResponse({
                    'success': False,
                    'error': f'Duplicate Half Filled Tray ID(s) not allowed: {", ".join(half_duplicates)}'
                }, status=400)
            
            # Check for overlap between delink and half filled tray IDs
            delink_pairs = set((entry.get('tray_id', '').strip(), entry.get('lot_id', '').strip()) 
                              for entry in delink_tray_data if entry.get('tray_id', '').strip())
            half_pairs = set((entry.get('tray_id', '').strip(), entry.get('lot_id', '').strip()) 
                            for entry in half_filled_tray_data if entry.get('tray_id', '').strip())
            
            overlap_pairs = delink_pairs & half_pairs
            if overlap_pairs:
                dup_ids = [pair[0] for pair in overlap_pairs]
                return JsonResponse({
                    'success': False,
                    'error': f'Tray ID(s) cannot be in both De-link and Half Filled sections for same Lot: {", ".join(dup_ids)}'
                }, status=400)

            # Set primary lot ID if not provided
            if not primary_lot_id and lot_ids:
                primary_lot_id = lot_ids[0]

            # Check for existing draft
            draft_id = data.get('draft_id')
            jig_detail = None
            if draft_id:
                try:
                    jig_detail = JigDetails.objects.get(id=draft_id, draft_save=True)
                    # Store draft_id for use in lot calculations
                    self._current_draft_id = draft_id
                except JigDetails.DoesNotExist:
                    jig_detail = None

            # *** UNIFIED LOT CALCULATION - SAME FOR BOTH DRAFT AND FINAL ***
            filtered_lot_ids, filtered_lot_id_quantities, recalculated_total_cases_loaded, primary_lot_id = self.calculate_lot_quantities_and_filter_lots(
                lot_ids, lot_id_quantities, delink_tray_data, half_filled_tray_data, is_draft, primary_lot_id
            )
            
            # Update variables with filtered results
            lot_ids = filtered_lot_ids
            lot_id_quantities = filtered_lot_id_quantities
            total_cases_loaded = recalculated_total_cases_loaded

            # Validation
            if not primary_lot_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'At least one lot ID is required'
                }, status=400)
            


            # Validation for slots (only for non-drafts)
           
            # For non-drafts, require JIG QR ID
            if not is_draft and not jig_qr_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Jig QR ID is required'
                }, status=400)
            
            # Fetch related data from primary lot before validation
            try:
                primary_stock, is_primary_recovery, _ = self.get_stock_model_and_tray_models(primary_lot_id)
                if not primary_stock:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Stock data not found for lot ID: {primary_lot_id}'
                    }, status=404)
                mmc = primary_stock.batch_id
                if not mmc:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Batch data not found for lot ID: {primary_lot_id}'
                    }, status=404)
                # Get model_stock_no
                if hasattr(primary_stock, 'model_stock_no') and primary_stock.model_stock_no:
                    model_stock_no = primary_stock.model_stock_no
                elif hasattr(mmc, 'model_stock_no') and mmc.model_stock_no:
                    model_stock_no = mmc.model_stock_no
                else:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Model stock number not found for lot ID: {primary_lot_id}'
                    }, status=404)
                # Get JigLoadingMaster data
                jig_master = JigLoadingMaster.objects.filter(model_stock_no=model_stock_no).first()
                if not jig_master:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Jig loading master data not found for model: {model_stock_no}'
                    }, status=404)
            except Exception as e:
                return JsonResponse({
                    'success': False, 
                    'error': f'Error fetching related data: {str(e)}'
                }, status=500)
            
            # Validation for slots (only for non-drafts)
            if not is_draft:
                # Only process if empty_slots is zero, else error
                if empty_slots != 0:
                    return JsonResponse({
                        'success': False,
                        'error': 'Too Many Empty Slots. Empty slots must be zero. Please check your input.'
                    }, status=400)
                # Faulty slots validation (capacity-based)
                faulty_limit = 10 if jig_master.jig_capacity > 144 else 5
                if faulty_slots > faulty_limit:
                    return JsonResponse({
                        'success': False,
                        'error': f'Too Many Faulty Slots. Faulty slots cannot be more than {faulty_limit} for this JIG. Please check your input.'
                    }, status=400)
            
            # *** JIG CYCLE VALIDATION (only for non-drafts) ***
            alert_msg = None
            if not is_draft:
                last_jig = JigDetails.objects.filter(
                    jig_qr_id=jig_qr_id, 
                    draft_save=False
                ).order_by('-id').first()
                
                if last_jig:
                    last_no_of_cycle = last_jig.no_of_cycle if last_jig.no_of_cycle else 1
                    new_no_of_cycle = last_no_of_cycle + 1
                else:
                    new_no_of_cycle = 1

                max_cycles = 35
                normal_limit = 30
                
                if new_no_of_cycle > max_cycles:
                    return JsonResponse({
                        'success': False,
                        'error': f'Maximum {max_cycles} cycles completed for this JIG. Cannot save further. Please use a different JIG.'
                    }, status=400)

                if normal_limit < new_no_of_cycle <= max_cycles:
                    alert_msg = f'JIG has completed {new_no_of_cycle} cycles. Maximum recommended is {normal_limit}. Please check if JIG needs maintenance.'
            else:
                # For drafts, use cycle 1 or existing draft cycle
                if jig_detail and jig_detail.no_of_cycle:
                    new_no_of_cycle = jig_detail.no_of_cycle
                else:
                    new_no_of_cycle = 1

            # *** FETCH RELATED DATA FROM PRIMARY LOT ***
            try:
                primary_stock, is_primary_recovery, _ = self.get_stock_model_and_tray_models(primary_lot_id)
                
                if not primary_stock:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Stock data not found for lot ID: {primary_lot_id}'
                    }, status=404)
                
                mmc = primary_stock.batch_id
                if not mmc:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Batch data not found for lot ID: {primary_lot_id}'
                    }, status=404)
                
                # Get model_stock_no
                if hasattr(primary_stock, 'model_stock_no') and primary_stock.model_stock_no:
                    model_stock_no = primary_stock.model_stock_no
                elif hasattr(mmc, 'model_stock_no') and mmc.model_stock_no:
                    model_stock_no = mmc.model_stock_no
                else:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Model stock number not found for lot ID: {primary_lot_id}'
                    }, status=404)
                
                # Get JigLoadingMaster data
                jig_master = JigLoadingMaster.objects.filter(model_stock_no=model_stock_no).first()
                if not jig_master:
                    return JsonResponse({
                        'success': False, 
                        'error': f'Jig loading master data not found for model: {model_stock_no}'
                    }, status=404)
                    
            except Exception as e:
                return JsonResponse({
                    'success': False, 
                    'error': f'Error fetching related data: {str(e)}'
                }, status=500)

            # *** UNIFIED ACTUAL LOT QUANTITIES CALCULATION ***
            actual_lot_id_quantities = self.calculate_actual_lot_quantities(
                lot_id_quantities, total_cases_loaded, faulty_slots, empty_slots, primary_lot_id, is_draft
            )
            
            # Calculate jig_cases_remaining_count
            jig_cases_remaining_count = max(0, jig_master.jig_capacity - total_cases_loaded - faulty_slots)
            
            # *** PREPARE JIG DETAILS DATA (CONSISTENT FOR BOTH DRAFT AND FINAL) ***
            jig_details_data = {
                'jig_qr_id': jig_qr_id,
                'faulty_slots': faulty_slots,
                'jig_type': jig_master.jig_type or '',
                'jig_capacity': jig_master.jig_capacity or 0,
                'ep_bath_type': getattr(mmc, 'ep_bath_type', '') or '',
                'plating_color': getattr(mmc, 'plating_color', '') or '',
                'jig_loaded_date_time': timezone.now(),
                'empty_slots': empty_slots,
                'total_cases_loaded': total_cases_loaded,
                'jig_cases_remaining_count': jig_cases_remaining_count,
                'no_of_model_cases': plating_stock_numbers,
                'no_of_cycle': new_no_of_cycle,
                'lot_id': primary_lot_id,
                'new_lot_ids': lot_ids,
                'electroplating_only': False,
                'lot_id_quantities': actual_lot_id_quantities,  # *** CONSISTENT CALCULATED QUANTITIES ***
                'bath_tub': '',
                'draft_save': is_draft,
                'delink_tray_data': delink_tray_data,
                'half_filled_tray_data': half_filled_tray_data,
            }
            
            print(f"💾 Saving JigDetails with consistent data:")
            print(f"   lot_ids: {lot_ids}")
            print(f"   lot_id_quantities: {actual_lot_id_quantities}")
            print(f"   total_cases_loaded: {total_cases_loaded}")
            print(f"   is_draft: {is_draft}")
            
            # Save or update JigDetails
            if jig_detail:
                # Update existing draft
                for field, value in jig_details_data.items():
                    setattr(jig_detail, field, value)
                jig_detail.save()
                print(f"✅ Updated existing draft JigDetails (ID: {jig_detail.id})")
            else:
                # Create new record
                jig_detail = JigDetails.objects.create(**jig_details_data)
                print(f"✅ Created new JigDetails (ID: {jig_detail.id})")
            
            # --- UPDATED BLOCK: Handle jig locking for drafts ---
            # Set jig state based on draft/submit status
            if jig_qr_id:
                jig_obj, _ = Jig.objects.get_or_create(jig_qr_id=jig_qr_id)
                
                if is_draft:
                    # For drafts: Set current_user and locked_at, DO NOT set is_loaded True
                    jig_obj.current_user = request.user
                    jig_obj.locked_at = timezone.now()
                    jig_obj.drafted = True  # Mark as drafted
                    # FIX: Do NOT set is_loaded=True for drafts
                    print(f"🔒 Jig {jig_qr_id} locked for draft by user {request.user}")
                else:
                    # For final submit: Set is_loaded = True, clear user lock
                    jig_obj.is_loaded = True
                    jig_obj.current_user = None
                    jig_obj.locked_at = None
                    jig_obj.drafted = False  # Clear drafted flag on submit
                    print(f"✅ Jig {jig_qr_id} marked as loaded (final submit)")
                
                jig_obj.save()
            # --- END UPDATED BLOCK ---
            
            
             # Add this check AFTER your existing jig validation
              # Check if this jig_qr_id has any active drafts
          

            # *** TRAY DATA PROCESSING (only for non-drafts) ***
            delink_success_count = 0
            half_filled_success_count = 0
            
            if not is_draft:
                # Process delink tray data
                if delink_tray_data:
                    print(f"🔧 Processing {len(delink_tray_data)} delink tray entries")
                    
                    for delink_entry in delink_tray_data:
                        tray_id = delink_entry.get('tray_id', '').strip()
                        lot_id = delink_entry.get('lot_id', '').strip()
                        tray_quantity = int(delink_entry.get('expected_usage', 0))
                        
                        print(f"🔴 Processing delink tray: {tray_id}, lot_id: {lot_id}, quantity: {tray_quantity}")
                        
                        stock_model, is_recovery, tray_models = self.get_stock_model_and_tray_models(lot_id)
                        if not stock_model:
                            print(f"⚠️ No stock model found for lot_id {lot_id}, skipping tray {tray_id}")
                            continue
                    
                        # Update JigLoadTrayId
                        JigLoadTrayId.objects.filter(
                            tray_id=tray_id,
                            lot_id=lot_id
                        ).update(
                            delink_tray=True,
                            tray_quantity=tray_quantity
                        )

                        if tray_id:
                            try:
                                # Update main TrayId table
                                MainTrayModel = tray_models['TrayId']
                                tray_obj = MainTrayModel.objects.filter(tray_id=tray_id).first()
                                if tray_obj:
                                    tray_obj.delink_tray = True
                                    tray_obj.lot_id = None
                                    tray_obj.tray_quantity = 0
                                    tray_obj.batch_id = None
                                    tray_obj.IP_tray_verified = False
                                    tray_obj.top_tray = False
                                    if hasattr(tray_obj, 'delink_tray_qty'):
                                        tray_obj.delink_tray_qty = tray_obj.tray_quantity
                                    
                                    update_fields = [
                                        'delink_tray', 'lot_id', 'tray_quantity',
                                        'batch_id', 'IP_tray_verified', 'top_tray'
                                    ]
                                    if hasattr(tray_obj, 'delink_tray_qty'):
                                        update_fields.append('delink_tray_qty')
                                        
                                    tray_obj.save(update_fields=update_fields)
                                    delink_success_count += 1
                                    print(f"✅ Updated main {MainTrayModel.__name__} for {tray_id}")

                                # Get batch_ids for this lot_id
                                batch_ids = list(stock_model.__class__.objects.filter(
                                    lot_id=lot_id
                                ).values_list('batch_id_id', flat=True).distinct())
                                
                                entry_batch_id = delink_entry.get('batch_id')
                                if entry_batch_id and entry_batch_id not in batch_ids:
                                    batch_ids.append(entry_batch_id)

                                # Update tray records in other tables
                                tray_model_list = [
                                    tray_models['IQFTrayId'],
                                    tray_models['JigLoadTrayId'],
                                    tray_models['BrassTrayId'],
                                    tray_models['BrassAuditTrayId'],
                                    tray_models['IPTrayId'],
                                    tray_models['DPTrayId_History']
                                ]
                                
                                for Model in tray_model_list:
                                    try:
                                        # Update by tray_id + lot_id
                                        updated_count_1 = Model.objects.filter(
                                            tray_id=tray_id, 
                                            lot_id=lot_id
                                        ).update(delink_tray=True)
                                        
                                        # Update by tray_id + batch_id
                                        updated_count_2 = 0
                                        for batch_id in batch_ids:
                                            if batch_id:
                                                if Model == JigLoadTrayId:
                                                    if is_recovery:
                                                        count = Model.objects.filter(
                                                            tray_id=tray_id, 
                                                            recovery_batch_id=batch_id
                                                        ).update(delink_tray=True)
                                                    else:
                                                        count = Model.objects.filter(
                                                            tray_id=tray_id, 
                                                            batch_id=batch_id
                                                        ).update(delink_tray=True)
                                                else:
                                                    count = Model.objects.filter(
                                                        tray_id=tray_id, 
                                                        batch_id=batch_id
                                                    ).update(delink_tray=True)
                                                updated_count_2 += count
                                        
                                        print(f"Model {Model.__name__}: Updated {updated_count_1} by lot_id, {updated_count_2} by batch_id for tray {tray_id}")
                                        
                                    except Exception as model_error:
                                        print(f"Error updating {Model.__name__} for tray {tray_id}: {str(model_error)}")
                        
                            except Exception as e:
                                print(f"Error processing tray {tray_id}: {str(e)}")

                # Process half filled tray data
                if half_filled_tray_data:
                    print(f"🔧 Processing {len(half_filled_tray_data)} half filled tray entries")
                    
                    for half_entry in half_filled_tray_data:
                        tray_id = half_entry.get('tray_id', '').strip()
                        tray_quantity = int(half_entry.get('tray_quantity', 0))
                        lot_id = half_entry.get('lot_id', '').strip()
                        is_top_tray = half_entry.get('is_top_tray', False)
                        
                        print(f"🟡 Processing half filled tray: {tray_id}, quantity: {tray_quantity}, lot_id: {lot_id}, is_top_tray: {is_top_tray}")
                        
                        if tray_id and tray_quantity > 0:
                            try:
                                stock_model, is_recovery, tray_models = self.get_stock_model_and_tray_models(lot_id)
                                if not stock_model:
                                    print(f"⚠️ No stock model found for lot_id {lot_id}, skipping tray {tray_id}")
                                    continue
                                
                                # Get batch_ids for this lot_id
                                batch_ids = list(stock_model.__class__.objects.filter(
                                    lot_id=lot_id
                                ).values_list('batch_id_id', flat=True).distinct())
                                
                                update_fields = {
                                    'tray_quantity': tray_quantity,
                                    'top_tray': is_top_tray,
                                }
                                
                                # Update by tray_id + lot_id
                                updated_count_1 = JigLoadTrayId.objects.filter(
                                    tray_id=tray_id,
                                    lot_id=lot_id
                                ).update(**update_fields)
                                
                                # Update by tray_id + batch_id if no exact match
                                updated_count_2 = 0
                                if updated_count_1 == 0:
                                    for batch_id in batch_ids:
                                        if batch_id:
                                            if is_recovery:
                                                count = JigLoadTrayId.objects.filter(
                                                    tray_id=tray_id,
                                                    recovery_batch_id=batch_id
                                                ).update(**update_fields)
                                            else:
                                                count = JigLoadTrayId.objects.filter(
                                                    tray_id=tray_id,
                                                    batch_id=batch_id
                                                ).update(**update_fields)
                                            updated_count_2 += count
                                
                                total_updated = updated_count_1 + updated_count_2
                                
                                if total_updated > 0:
                                    print(f"✅ Successfully updated tray {tray_id}: {total_updated} records updated in JigLoadTrayId")
                                    half_filled_success_count += 1
                                    
                                    # Update main tray table
                                    try:
                                        MainTrayModel = tray_models['TrayId']
                                        main_tray_obj = MainTrayModel.objects.filter(tray_id=tray_id).first()
                                        if main_tray_obj:
                                            if is_top_tray:
                                                main_tray_obj.top_tray = True
                                                main_tray_obj.tray_quantity = tray_quantity
                                                main_tray_obj.save(update_fields=['top_tray', 'tray_quantity'])
                                                print(f"✅ Updated main {MainTrayModel.__name__} table for {tray_id}")
                                    except Exception as main_tray_error:
                                        print(f"⚠️ Error updating main tray table for {tray_id}: {str(main_tray_error)}")
                                else:
                                    # Create new record if none exists
                                    print(f"🆕 Creating new JigLoadTrayId record for {tray_id}")
                                    if batch_ids:
                                        first_batch_id = batch_ids[0]
                                        try:
                                            from django.contrib.auth.models import User
                                            
                                            create_kwargs = {
                                                'tray_id': tray_id,
                                                'lot_id': lot_id,
                                                'tray_quantity': tray_quantity,
                                                'top_tray': is_top_tray,
                                                'user': User.objects.first()
                                            }
                                            
                                            if is_recovery:
                                                create_kwargs['recovery_batch_id_id'] = first_batch_id
                                            else:
                                                create_kwargs['batch_id_id'] = first_batch_id
                                            
                                            new_record = JigLoadTrayId.objects.create(**create_kwargs)
                                            print(f"✅ Created new JigLoadTrayId record: {new_record}")
                                            half_filled_success_count += 1
                                        except Exception as create_error:
                                            print(f"❌ Error creating new record: {str(create_error)}")
                            
                            except Exception as e:
                                print(f"❌ Error processing half filled tray {tray_id}: {str(e)}")

                # *** UPDATE STOCK MODELS WITH REMAINING QUANTITIES ***
                half_filled_tray_ids = [entry.get('tray_id', '').strip() for entry in half_filled_tray_data if entry.get('tray_id', '').strip()]

                for lot_id in lot_ids:
                    print(f"\n🔍 UPDATING STOCK MODEL FOR LOT_ID: {lot_id}")
                    
                    stock_model, is_recovery, tray_models = self.get_stock_model_and_tray_models(lot_id)
                    if stock_model and hasattr(stock_model, 'batch_id') and stock_model.batch_id and hasattr(stock_model.batch_id, 'tray_capacity'):
                        tray_capacity = stock_model.batch_id.tray_capacity
                    
                    # Update tray quantities in JigLoadTrayId
                    tray_qs = JigLoadTrayId.objects.filter(lot_id=lot_id)
                    for tray in tray_qs:
                        if tray.tray_id not in half_filled_tray_ids:
                            tray.tray_quantity = tray_capacity
                            tray.top_tray = False
                            tray.save(update_fields=['tray_quantity'])
                    
                    if stock_model:
                        try:
                            from django.db.models import Sum
                            
                            # Get original quantity
                            if is_recovery:
                                if hasattr(stock_model, 'jig_physical_qty_edited') and stock_model.jig_physical_qty_edited and hasattr(stock_model, 'jig_physical_qty') and stock_model.jig_physical_qty:
                                    original_qty = stock_model.jig_physical_qty
                                elif hasattr(stock_model, 'brass_audit_accepted_qty'):
                                    original_qty = stock_model.brass_audit_accepted_qty or 0
                                else:
                                    original_qty = getattr(stock_model, 'total_stock', 0)
                            else:
                                if stock_model.jig_physical_qty_edited and stock_model.jig_physical_qty:
                                    original_qty = stock_model.jig_physical_qty
                                else:
                                    original_qty = stock_model.brass_audit_accepted_qty or 0
                            
                            # Calculate remaining quantity from JigLoadTrayId
                            load_trays = JigLoadTrayId.objects.filter(lot_id=lot_id)
                            remaining_qty = 0
                            
                            for record in load_trays:
                                tray_qty = record.tray_quantity or 0
                                is_delink = getattr(record, 'delink_tray', False)
                                
                                if not is_delink:
                                    remaining_qty += tray_qty

                            # Update stock model
                            if hasattr(stock_model, 'jig_physical_qty'):
                                stock_model.jig_physical_qty = remaining_qty
                            if hasattr(stock_model, 'jig_physical_qty_edited'):
                                stock_model.jig_physical_qty_edited = True
                            stock_model.last_process_module = "Jig Loading"
                            stock_model.next_process_module = "Jig Unloading"
                            
                            update_fields = ['last_process_module', 'next_process_module']
                            if hasattr(stock_model, 'jig_physical_qty'):
                                update_fields.append('jig_physical_qty')
                            if hasattr(stock_model, 'jig_physical_qty_edited'):
                                update_fields.append('jig_physical_qty_edited')
                                
                            stock_model.save(update_fields=update_fields)
                            
                            print(f"✅ UPDATED {'RecoveryStockModel' if is_recovery else 'TotalStockModel'} for lot {lot_id}:")
                            if hasattr(stock_model, 'jig_physical_qty'):
                                print(f"   jig_physical_qty = {remaining_qty}")
                            
                        except Exception as calc_error:
                            print(f"❌ ERROR updating stock model for lot {lot_id}: {str(calc_error)}")

            # Clean up temp variable
            if hasattr(self, '_current_draft_id'):
                delattr(self, '_current_draft_id')

            # Prepare response
            response_data = {
                'success': True,
                'message': f'{"Draft" if is_draft else "Jig details"} saved successfully with QR ID: {jig_qr_id}',
                'jig_id': jig_detail.id,
                'is_draft': is_draft,
                'delink_processed': delink_success_count,
                'half_filled_processed': half_filled_success_count,
                'data': {
                    'jig_qr_id': jig_detail.jig_qr_id,
                    'jig_capacity': jig_detail.jig_capacity,
                    'total_cases_loaded': jig_detail.total_cases_loaded,
                    'empty_slots': jig_detail.empty_slots,
                    'faulty_slots': jig_detail.faulty_slots,
                    'jig_cases_remaining_count': jig_detail.jig_cases_remaining_count,
                    'model_numbers': jig_detail.no_of_model_cases,
                    'lot_ids': jig_detail.new_lot_ids,
                    'no_of_cycle': jig_detail.no_of_cycle,
                    'actual_lot_id_quantities': actual_lot_id_quantities,  # *** CONSISTENT DATA ***
                    'draft_save': jig_detail.draft_save,
                    'delink_tray_data': jig_detail.delink_tray_data,
                    'half_filled_tray_data': jig_detail.half_filled_tray_data,
                }
            }
            
            if not is_draft and 'alert_msg' in locals() and alert_msg:
                response_data['alert'] = alert_msg

            return JsonResponse(response_data)
            
        except ValueError as ve:
            return JsonResponse({
                'success': False, 
                'error': f'Invalid data format: {str(ve)}'
            }, status=400)
            
        except Exception as e:
            print(f"Error in JigDetailsSaveAPIView: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            
            return JsonResponse({
                'success': False, 
                'error': f'An unexpected error occurred: {str(e)}'
            }, status=500)






@api_view(['POST'])
def validate_jig_qr(request):
    jig_qr_id = request.data.get('jig_qr_id')
    if not jig_qr_id:
        return JsonResponse({'valid': False, 'error': 'JIG QR ID required'})

    try:
        jig_obj = Jig.objects.get(jig_qr_id=jig_qr_id)
        # FIXED: Check both is_loaded AND drafted fields
        if jig_obj.is_loaded or getattr(jig_obj, 'drafted', False):
            print(f"❌ JIG QR ID {jig_qr_id} is currently loaded or drafted")
            return JsonResponse({
                'valid': False,
                'error': f'JIG QR ID {jig_qr_id} is currently loaded or drafted and not available for use'
            })
        return JsonResponse({'valid': True, 'message': 'JIG QR ID is available'})
    except Jig.DoesNotExist:
        return JsonResponse({'valid': False, 'error': 'JIG QR ID not found'})


    
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JigDetailsClearDraftAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id', '').strip()
            print(f"Received lot_id for draft clear: {lot_id}")
            if not lot_id:
                return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)
            
            # Get the draft with user info before deleting
            draft_details = JigDetails.objects.filter(
                lot_id=lot_id, 
                draft_save=True,
                created_by=request.user  # Only clear user's own drafts
            ).first()
            
            if not draft_details:
                return JsonResponse({
                    'success': False,
                    'error': 'No draft found for this lot or you do not have permission to clear it.'
                })
            jig_qr_id = draft_details.jig_qr_id if draft_details else None
            
                    # Delete the draft
            deleted_count = JigDetails.objects.filter(
                lot_id=lot_id, 
                draft_save=True,
                created_by=request.user
            ).delete()[0]
            
            # Clear the jig lock if draft was deleted and user matches
            
            if deleted_count > 0 and jig_qr_id:
                try:
                    jig_obj = Jig.objects.get(jig_qr_id=jig_qr_id)
                    if jig_obj.current_user == request.user:
                        jig_obj.clear_user_lock()
                        jig_obj.drafted = False
                        jig_obj.save()
                except Jig.DoesNotExist:
                    pass
                    print(f"🔓 Jig {jig_qr_id} unlocked after draft clear by user {request.user}")
                
                return JsonResponse({'success': True, 'message': f'Draft(s) for lot_id {lot_id} cleared and jig unlocked.'})
            else:
                return JsonResponse({'success': False, 'error': 'No draft found for this lot_id.'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

@api_view(['POST'])
def validate_tray_id(request):
    data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
    tray_id = data.get('tray_id', '').strip()
    lot_id = data.get('lot_id', '').strip()  # Get lot_id for comparison

    tray_obj = JigLoadTrayId.objects.filter(
        tray_id=tray_id,
        lot_id=lot_id,
        rejected_tray=False,
        delink_tray=False
    ).first()
    if not tray_obj:
        return JsonResponse({'exists': False, 'lot_match': False})

    # Check if lot_id matches (if provided)
    if lot_id:
        lot_match = (str(tray_obj.lot_id) == str(lot_id))
        return JsonResponse({'exists': True, 'lot_match': lot_match})
    else:
        # If no lot_id provided, just return exists
        return JsonResponse({'exists': True, 'lot_match': True})

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JigDetailsUpdateAPIView(APIView):
    """
    API endpoint for updating existing JigDetails
    """
    
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            
            jig_id = data.get('jig_id')
            jig_qr_id = data.get('jig_qr_id', '').strip()
            
            if not jig_id and not jig_qr_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Either jig_id or jig_qr_id is required for update'
                }, status=400)
            
            # Find the JigDetails record
            if jig_id:
                jig_detail = JigDetails.objects.filter(id=jig_id).first()
            else:
                jig_detail = JigDetails.objects.filter(jig_qr_id=jig_qr_id).first()
            
            if not jig_detail:
                return JsonResponse({
                    'success': False, 
                    'error': 'Jig details not found'
                }, status=404)
            
            # Update fields if provided
            if 'faulty_slots' in data:
                jig_detail.faulty_slots = int(data['faulty_slots'])
            
            if 'empty_slots' in data:
                jig_detail.empty_slots = int(data['empty_slots'])
            
            if 'total_cases_loaded' in data:
                jig_detail.total_cases_loaded = int(data['total_cases_loaded'])
            
            if 'model_numbers' in data:
                jig_detail.no_of_model_cases = data['model_numbers']
            
            if 'lot_ids' in data:
                jig_detail.new_lot_ids = data['lot_ids']
            
            if 'lot_id_quantities' in data:
                jig_detail.lot_id_quantities = data['lot_id_quantities']
            
            # Recalculate jig_cases_remaining_count
            jig_detail.jig_cases_remaining_count = max(
                0, 
                jig_detail.jig_capacity - jig_detail.total_cases_loaded - jig_detail.faulty_slots
            )
            
            jig_detail.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Jig details updated successfully for QR ID: {jig_detail.jig_qr_id}',
                'data': {
                    'jig_qr_id': jig_detail.jig_qr_id,
                    'jig_capacity': jig_detail.jig_capacity,
                    'total_cases_loaded': jig_detail.total_cases_loaded,
                    'empty_slots': jig_detail.empty_slots,
                    'faulty_slots': jig_detail.faulty_slots,
                    'jig_cases_remaining_count': jig_detail.jig_cases_remaining_count
                }
            })
            
        except Exception as e:
            print(f"Error in JigDetailsUpdateAPIView: {str(e)}")
            return JsonResponse({
                'success': False, 
                'error': f'Update failed: {str(e)}'
            }, status=500)



# Class for JIG QR ID Validation (Draft & Submit, Unload at Jig Unloading)
# Replace the existing JigDetailsValidateQRAPIView class with this updated version
@method_decorator(csrf_exempt, name='dispatch')
class JigDetailsValidateQRAPIView(APIView):
    """
    API endpoint for validating JIG QR ID with user-specific locking mechanism
    - If jig is drafted by User A, only User A can access it
    - Other users are blocked until the jig is unloaded
    - is_loaded=True blocks all access regardless of user
    """
    def post(self, request):
        try:
            if not request.user.is_authenticated:
                return JsonResponse({
                    'valid': False,
                    'error': 'Authentication required. Please log in to continue.',
                    'redirect_to_login': True
                }, status=401)
            
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            jig_qr_id = data.get('jig_qr_id', '').strip()
            
            if not jig_qr_id:
                return JsonResponse({'valid': False, 'error': 'JIG QR ID is required'})
            
            print(f"🔍 Validating JIG QR ID: {jig_qr_id} for user: {request.user.username}")
            
            # ✅ FIXED: Don't set is_loaded=True on creation, only basic fields
            jig_obj, created = Jig.objects.get_or_create(
                jig_qr_id=jig_qr_id,
                defaults={
                    'is_loaded': False,  # ✅ FIX: Don't load immediately
                    'current_user': None,  # ✅ FIX: Don't assign user yet
                    'drafted': False,
                    'locked_at': None
                }
            )
            
            if created:
                print(f"✅ New JIG QR ID created: {jig_qr_id} - Available for {request.user.username}")
                return JsonResponse({
                    'valid': True,
                    'message': f'JIG QR ID {jig_qr_id} is valid and available',
                    'jig_qr_id': jig_qr_id
                })
            
            # Check if jig is currently loaded (blocks everyone)
            if jig_obj.is_loaded:
                print(f"❌ JIG QR ID {jig_qr_id} is currently loaded")
                return JsonResponse({
                    'valid': False,
                    'error': f'JIG QR ID {jig_qr_id} is currently loaded and not available for use'
                })
            
            # ✅ ENHANCED: Check for active drafts with time-based override for old drafts
            active_draft = JigDetails.objects.filter(
                jig_qr_id=jig_qr_id,
                draft_save=True,
                unload_over=False
            ).first()
            
            if active_draft:
                # Allow takeover if draft is older than 24 hours (orphaned draft)
                draft_age = timezone.now() - active_draft.date_time
                is_old_draft = draft_age > timedelta(hours=24)
                
                if active_draft.created_by == request.user:
                    print(f"❌ User {request.user.username} already drafted JIG QR ID {jig_qr_id}")
                    return JsonResponse({
                        'valid': False,
                        'error': f'You have already drafted JIG QR ID {jig_qr_id}. Please complete or clear your existing draft first.'
                    })
                elif is_old_draft:
                    # Allow takeover of orphaned drafts
                    print(f"⚠️ Allowing takeover of old draft for JIG QR ID {jig_qr_id} (age: {draft_age})")
                    # Optionally, you could auto-clear the old draft here, but for now just allow
                else:
                    drafting_user = active_draft.created_by.username if active_draft.created_by else 'Unknown'
                    print(f"❌ JIG QR ID {jig_qr_id} is drafted by user: {drafting_user}")
                    return JsonResponse({
                        'valid': False,
                        'error': f'JIG QR ID {jig_qr_id} is currently occupied & unavailable to use.'
                    })
        
            
            # ✅ JIG QR ID is available for this user
            print(f"✅ JIG QR ID {jig_qr_id} is available for user: {request.user.username}")
            
            return JsonResponse({
                'valid': True,
                'message': f'JIG QR ID {jig_qr_id} is valid and available',
                'jig_qr_id': jig_qr_id
            })
            
        except Exception as e:
            print(f"❌ Error validating JIG QR ID: {str(e)}")
            return JsonResponse({
                'valid': False,
                'error': f'Internal server error: {str(e)}'
            }, status=500)




    
        
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JigCycleCountAPIView(APIView):
    """
    API endpoint to get current cycle count for a jig QR ID
    """
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            jig_qr_id = data.get('jig_qr_id', '').strip()
            
            if not jig_qr_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Jig QR ID is required'
                }, status=400)

            # Get the last completed (non-draft) JigDetails for this jig_qr_id
            last_jig = JigDetails.objects.filter(
                jig_qr_id=jig_qr_id, 
                draft_save=False
            ).order_by('-id').first()
            
            if last_jig:
                current_cycle = last_jig.no_of_cycle or 1
                next_cycle = current_cycle + 1
            else:
                current_cycle = 0
                next_cycle = 1
            
            # Determine status and validation
            max_cycles = 35
            normal_limit = 30
            
            if next_cycle <= normal_limit:
                status = 'normal'
                message = f'Cycle {next_cycle}/{normal_limit} - Normal operation'
            elif normal_limit < next_cycle <= max_cycles:
                status = 'warning'
                message = f'Cycle {next_cycle}/{normal_limit} - Warning: Approaching maintenance limit'
            else:
                status = 'blocked'
                message = f'Maximum {max_cycles} cycles completed. JIG cannot be used further.'
            
            return JsonResponse({
                'success': True,
                'current_cycle': current_cycle,
                'next_cycle': next_cycle,
                'status': status,
                'message': message,
                'can_save': next_cycle <= max_cycles,
                'show_warning': normal_limit < next_cycle <= max_cycles,
                'display_text': f'{next_cycle}/{normal_limit}'
            })
            
        except Exception as e:
            print(f"Error in JigCycleCountAPIView: {str(e)}")
            return JsonResponse({
                'success': False, 
                'error': f'Failed to get cycle count: {str(e)}'
            }, status=500)

@method_decorator(login_required, name='dispatch')
class JigCompletedTable(TemplateView):
    template_name = "JigLoading/Jig_Completedtable.html"

    def get_stock_model_data(self, lot_id):
        """
        Helper function to get stock model data from either TotalStockModel or RecoveryStockModel
        Returns: (stock_model, is_recovery, batch_model_class)
        """
        # Try TotalStockModel first
        tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if tsm:
            return tsm, False, ModelMasterCreation
        
        # Try RecoveryStockModel if not found in TotalStockModel
        try:
            rsm = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if rsm:
                # Try to import RecoveryMasterCreation safely
                try:
                    from Recovery_DP.models import RecoveryMasterCreation
                    return rsm, True, RecoveryMasterCreation
                except ImportError:
                    print("⚠️ RecoveryMasterCreation not found, using ModelMasterCreation as fallback")
                    return rsm, True, ModelMasterCreation
        except Exception as e:
            print(f"⚠️ Error accessing RecoveryStockModel: {e}")
        
        return None, False, None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # ✅ Use IST timezone
        tz = pytz.timezone("Asia/Kolkata")
        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        # ✅ Get date filter parameters from request
        from_date_str = self.request.GET.get('from_date')
        to_date_str = self.request.GET.get('to_date')

        # ✅ Calculate date range
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

        
        # *** UPDATED: Get polish_finish from both TotalStockModel and RecoveryStockModel ***
        # Try TotalStockModel first
        try:
            total_polish_finish_subquery = TotalStockModel.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('polish_finish__polish_finish')[:1]
        except:
            # If polish_finish field doesn't exist, use alternative field or default
            total_polish_finish_subquery = TotalStockModel.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('batch_id__polish_finish')[:1]
        
        # Try RecoveryStockModel as fallback
        try:
            recovery_polish_finish_subquery = RecoveryStockModel.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('polish_finish__polish_finish')[:1]
        except:
            # If polish_finish field doesn't exist, use alternative field or default
            recovery_polish_finish_subquery = RecoveryStockModel.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('batch_id__polish_finish')[:1]
        
        # Fetch JigDetails with polish_finish annotation (prefer TotalStock, fallback to Recovery)
        try:
            jig_details_qs = JigDetails.objects.annotate(
                polish_finish_name=Coalesce(
                    Subquery(total_polish_finish_subquery),
                    Subquery(recovery_polish_finish_subquery),
                    Value('No Polish Finish')
                )
            ).select_related()
        except Exception as e:
            print(f"⚠️ Error with polish_finish annotation, using default: {e}")
            jig_details_qs = JigDetails.objects.select_related()
            for jig_detail in jig_details_qs:
                jig_detail.polish_finish_name = 'No Polish Finish'

        # ✅ Filter by last two days (IST)
        jig_details_qs = jig_details_qs.filter(
            jig_loaded_date_time__date__gte=from_date,
            jig_loaded_date_time__date__lte=to_date
        )

        # Order by jig_loaded_date_time (descending)
        jig_details = jig_details_qs.order_by('-jig_loaded_date_time')

        # Process each JigDetails to handle multiple models
        processed_jig_details = []
        
        for jig_detail in jig_details:
            # Process new_lot_ids to get comma-separated field values
            lot_ids_data = self.process_new_lot_ids(jig_detail.new_lot_ids)
            # Process no_of_model_cases to get comma-separated field values (NOT multiple instances)
            model_cases_data = self.process_model_cases(jig_detail.no_of_model_cases)
            lot_id = getattr(jig_detail, 'lot_id', None)
            batch_status = None
            if lot_id:
                # Use the same logic as JigPickTableView
                status_obj = JigPickTableView().calculate_batch_status(lot_id)
                if status_obj.get('status') == 'Yet to Release':
                    batch_status = status_obj
            # Create ONLY ONE instance per JigDetails with all comma-separated data
            jig_detail_copy = self.create_single_jig_detail_copy(jig_detail, lot_ids_data, model_cases_data, batch_status)
            processed_jig_details.append(jig_detail_copy)
        
        context['jig_details'] = processed_jig_details
        return context
    
    def process_new_lot_ids(self, new_lot_ids):
        """
        Process new_lot_ids ArrayField with hybrid approach:
        - plating_stk_nos: ONLY first lot_id (single value)
        - polishing_stk_nos: ONLY first lot_id (single value)  
        - version_names: ALL lot_ids (comma-separated list)
        """
        if not new_lot_ids:
            return {
                'plating_stk_nos': 'No Plating Stock No',
                'polishing_stk_nos': 'No Polishing Stock No',
                'version_names': 'No Version'
            }
        
        # Get stock objects from both models for ALL lot_ids
        total_stocks = TotalStockModel.objects.filter(
            lot_id__in=new_lot_ids
        ).select_related('batch_id')
        
        recovery_stocks = RecoveryStockModel.objects.filter(
            lot_id__in=new_lot_ids
        ).select_related('batch_id')
        
        # Create mappings
        lot_to_total_stock = {stock.lot_id: stock for stock in total_stocks}
        lot_to_recovery_stock = {stock.lot_id: stock for stock in recovery_stocks}
        
        print(f"🔍 Processing {len(new_lot_ids)} lot_ids")
        print(f"   Found {len(total_stocks)} in TotalStockModel")
        print(f"   Found {len(recovery_stocks)} in RecoveryStockModel")
        
        # Get batch data for all lot_ids
        total_batch_ids = [stock.batch_id.id for stock in total_stocks if stock.batch_id]
        recovery_batch_ids = [stock.batch_id.id for stock in recovery_stocks if stock.batch_id]
        
        batch_to_model_master = {}
        batch_to_recovery_master = {}
        
        # Fetch ModelMasterCreation objects
        if total_batch_ids:
            model_masters = ModelMasterCreation.objects.filter(
                id__in=total_batch_ids
            ).select_related('model_stock_no', 'version')
            batch_to_model_master = {model.id: model for model in model_masters}
        
        # Fetch RecoveryMasterCreation objects
        if recovery_batch_ids:
            try:
                from Recovery_DP.models import RecoveryMasterCreation
                recovery_masters = RecoveryMasterCreation.objects.filter(
                    id__in=recovery_batch_ids
                ).select_related('model_stock_no', 'version')
                batch_to_recovery_master = {model.id: model for model in recovery_masters}
            except ImportError:
                print("⚠️ RecoveryMasterCreation model not found")
            except Exception as e:
                print(f"⚠️ Error fetching RecoveryMasterCreation: {e}")
        
        # Variables to store results
        first_plating_stk_no = None
        first_polishing_stk_no = None
        version_names = []
        
        # Process each lot_id
        for i, lot_id in enumerate(new_lot_ids):
            print(f"   Processing lot_id: {lot_id}")
            
            # Check TotalStockModel first
            total_stock = lot_to_total_stock.get(lot_id)
            if total_stock and total_stock.batch_id:
                model_master = batch_to_model_master.get(total_stock.batch_id.id)
                if model_master:
                    # For FIRST lot_id only, get plating and polishing stock numbers
                    if i == 0:  # First lot_id
                        first_plating_stk_no = model_master.plating_stk_no or "No Plating Stock No"
                        first_polishing_stk_no = model_master.polishing_stk_no or "No Polishing Stock No"
                    
                    # For ALL lot_ids, get version names
                    version_name = "No Version"
                    if hasattr(model_master, 'version') and model_master.version:
                        version_name = getattr(model_master.version, 'version_internal', None) or getattr(model_master.version, 'version_name', 'No Version')
                    version_names.append(version_name)
                    print(f"     ✅ Found in TotalStock -> ModelMaster")
                    continue
            
            # Check RecoveryStockModel if not found in TotalStock
            recovery_stock = lot_to_recovery_stock.get(lot_id)
            if recovery_stock and recovery_stock.batch_id:
                recovery_master = batch_to_recovery_master.get(recovery_stock.batch_id.id)
                if recovery_master:
                    # For FIRST lot_id only, get plating and polishing stock numbers
                    if i == 0:  # First lot_id
                        first_plating_stk_no = getattr(recovery_master, 'plating_stk_no', None) or "No Plating Stock No"
                        first_polishing_stk_no = getattr(recovery_master, 'polishing_stk_no', None) or "No Polishing Stock No"
                    
                    # For ALL lot_ids, get version names
                    version_name = "No Version"
                    if hasattr(recovery_master, 'version') and recovery_master.version:
                        version_name = getattr(recovery_master.version, 'version_internal', None) or getattr(recovery_master.version, 'version_name', 'No Version')
                    version_names.append(version_name)
                    print(f"     ✅ Found in RecoveryStock -> RecoveryMaster")
                    continue
            
            # If not found in either model
            if i == 0:  # First lot_id defaults
                first_plating_stk_no = "No Plating Stock No"
                first_polishing_stk_no = "No Polishing Stock No"
            version_names.append("No Version")
            print(f"     ❌ Not found in either model")
        
        # Set defaults if first lot_id processing failed
        if first_plating_stk_no is None:
            first_plating_stk_no = "No Plating Stock No"
        if first_polishing_stk_no is None:
            first_polishing_stk_no = "No Polishing Stock No"
        
        return {
            'plating_stk_nos': first_plating_stk_no,  # Single value from first lot_id
            'polishing_stk_nos': first_polishing_stk_no,  # Single value from first lot_id
            'version_names': ', '.join(version_names) if version_names else 'No Version'  # Comma-separated from all lot_ids
        }
    
    def process_model_cases(self, no_of_model_cases):
        """
        Process no_of_model_cases to get comma-separated field values (NOT multiple instances)
        Updated to search both ModelMasterCreation and RecoveryMasterCreation
        Returns comma-separated values for plating_stk_no, polishing_stk_no, version_name
        """
        model_stock_nos = self.parse_model_cases(no_of_model_cases)
        
        if not model_stock_nos:
            return {
                'model_plating_stk_nos': '',
                'model_polishing_stk_nos': '',
                'model_version_names': ''
            }
        
        # *** UPDATED: Get data from both ModelMasterCreation and RecoveryMasterCreation ***
        models_data = self.get_models_data(model_stock_nos)
        
        plating_stk_nos = []
        polishing_stk_nos = []
        version_names = []
        
        for model_stock_no in model_stock_nos:
            model_data = models_data.get(model_stock_no, {})
            plating_stk_nos.append(model_data.get('plating_stk_no', 'No Plating Stock No'))
            polishing_stk_nos.append(model_data.get('polishing_stk_no', 'No Polishing Stock No'))
            version_names.append(model_data.get('version_name', 'No Version'))
        
        return {
            'model_plating_stk_nos': ', '.join(plating_stk_nos),
            'model_polishing_stk_nos': ', '.join(polishing_stk_nos),
            'model_version_names': ', '.join(version_names)
        }
    
    def create_single_jig_detail_copy(self, original_jig_detail, lot_ids_data, model_cases_data, batch_status=None):
        """
        Create a single copy of jig_detail with ALL data as comma-separated values
        Updated to handle both stock model types
        """
        # Create a new object that behaves like the original but with additional attributes
        jig_detail_copy = type('JigDetailCopy', (), {})()
        
        # Copy all original attributes
        for attr in dir(original_jig_detail):
            if not attr.startswith('_'):
                try:
                    setattr(jig_detail_copy, attr, getattr(original_jig_detail, attr))
                except:
                    pass
        
        # Add lot_ids data (comma-separated values from new_lot_ids)
        jig_detail_copy.lot_plating_stk_nos = lot_ids_data['plating_stk_nos']
        jig_detail_copy.lot_polishing_stk_nos = lot_ids_data['polishing_stk_nos']
        jig_detail_copy.lot_version_names = lot_ids_data['version_names']
        jig_detail_copy.batch_status = batch_status

        # Add model_cases data (comma-separated values from no_of_model_cases)
        jig_detail_copy.model_plating_stk_nos = model_cases_data['model_plating_stk_nos']
        jig_detail_copy.model_polishing_stk_nos = model_cases_data['model_polishing_stk_nos']
        jig_detail_copy.model_version_names = model_cases_data['model_version_names']
        
        # Combine both sources for final display (you can choose which one to prioritize)
        # Option 1: Use model_cases data if available, otherwise lot_ids data
        jig_detail_copy.final_plating_stk_nos = (
            jig_detail_copy.model_plating_stk_nos if jig_detail_copy.model_plating_stk_nos 
            else jig_detail_copy.lot_plating_stk_nos
        )
        jig_detail_copy.final_polishing_stk_nos = (
            jig_detail_copy.model_polishing_stk_nos if jig_detail_copy.model_polishing_stk_nos 
            else jig_detail_copy.lot_polishing_stk_nos
        )
        jig_detail_copy.final_version_names = (
            jig_detail_copy.model_version_names if jig_detail_copy.model_version_names 
            else jig_detail_copy.lot_version_names
        )
        
        # Add single instance indicators
        jig_detail_copy.is_single_instance = True
        jig_detail_copy.has_multiple_lots = bool(lot_ids_data['plating_stk_nos'])
        jig_detail_copy.has_multiple_models = bool(model_cases_data['model_plating_stk_nos'])
        
        # *** UPDATED: Get additional data from appropriate stock model ***
        if original_jig_detail.lot_id:
            try:
                stock_model, is_recovery, batch_model_class = self.get_stock_model_data(original_jig_detail.lot_id)
                
                if stock_model and stock_model.batch_id:
                    print(f"🔍 Getting batch data for lot {original_jig_detail.lot_id} from {'Recovery' if is_recovery else 'Regular'} model")
                    batch_data = self.get_batch_data(stock_model.batch_id.id, batch_model_class)
                    
                    # Apply batch data for additional fields not covered by comma-separated data
                    for key, value in batch_data.items():
                        if not hasattr(jig_detail_copy, key) or getattr(jig_detail_copy, key) is None:
                            setattr(jig_detail_copy, key, value)
                    
                    # Add source information
                    jig_detail_copy.source_model = 'RecoveryStock' if is_recovery else 'TotalStock'
                    jig_detail_copy.batch_model_type = 'RecoveryMasterCreation' if is_recovery else 'ModelMasterCreation'
                else:
                    self.set_default_values(jig_detail_copy)
            except Exception as e:
                print(f"⚠️ Error getting batch data for lot {original_jig_detail.lot_id}: {e}")
                self.set_default_values(jig_detail_copy)
        else:
            self.set_default_values(jig_detail_copy)
        
        return jig_detail_copy
    
    def parse_model_cases(self, no_of_model_cases):
        """
        Parse no_of_model_cases field to extract model_stock_no values
        Assuming it's stored as JSON, comma-separated, or some other format
        """
        if not no_of_model_cases:
            return []
        
        try:
            # Try parsing as JSON first
            if isinstance(no_of_model_cases, str):
                # If it's JSON format like: {"model1": 10, "model2": 15}
                if no_of_model_cases.startswith('{') or no_of_model_cases.startswith('['):
                    parsed = json.loads(no_of_model_cases)
                    if isinstance(parsed, dict):
                        return list(parsed.keys())
                    elif isinstance(parsed, list):
                        return parsed
                
                # If it's comma-separated like: "model1,model2,model3"
                elif ',' in no_of_model_cases:
                    return [model.strip() for model in no_of_model_cases.split(',') if model.strip()]
                
                # If it's a single model
                else:
                    return [no_of_model_cases.strip()]
            
            # If it's already a list or other format
            elif isinstance(no_of_model_cases, (list, tuple)):
                return list(no_of_model_cases)
            
            # Single value case
            else:
                return [str(no_of_model_cases)]
                
        except (json.JSONDecodeError, AttributeError):
            # Fallback: treat as single model
            return [str(no_of_model_cases)] if no_of_model_cases else []
    
    def get_models_data(self, model_stock_nos):
        """
        Fetch model data from both ModelMasterCreation and RecoveryMasterCreation
        Updated to search both model types
        """
        models_data = {}
        
        if not model_stock_nos:
            return models_data
        
        print(f"🔍 Getting models data for: {model_stock_nos}")
        
        # *** UPDATED: Fetch from both ModelMasterCreation and RecoveryMasterCreation ***
        
        # Fetch from ModelMasterCreation
        model_masters = ModelMasterCreation.objects.filter(
            model_stock_no__model_no__in=model_stock_nos
        ).select_related(
            'version',
            'model_stock_no',
            'model_stock_no__tray_type',
            'location'
        ).prefetch_related(
            'model_stock_no__images'
        )
        
        print(f"   Found {len(model_masters)} in ModelMasterCreation")
        
        # Process ModelMasterCreation results
        for model_master in model_masters:
            model_no = model_master.model_stock_no.model_no if model_master.model_stock_no else None
            if model_no:
                models_data[model_no] = self.extract_model_data(model_master, 'ModelMasterCreation')
        
        # Fetch from RecoveryMasterCreation for any not found in ModelMasterCreation
        remaining_model_nos = [model_no for model_no in model_stock_nos if model_no not in models_data]
        
        if remaining_model_nos:
            try:
                # Try to import RecoveryMasterCreation safely
                from Recovery_DP.models import RecoveryMasterCreation
                
                recovery_masters = RecoveryMasterCreation.objects.filter(
                    model_stock_no__model_no__in=remaining_model_nos
                ).select_related(
                    'version',
                    'model_stock_no',
                    'model_stock_no__tray_type',
                    'location'
                ).prefetch_related(
                    'model_stock_no__images'
                )
                
                print(f"   Found {len(recovery_masters)} in RecoveryMasterCreation")
                
                # Process RecoveryMasterCreation results
                for recovery_master in recovery_masters:
                    model_no = recovery_master.model_stock_no.model_no if recovery_master.model_stock_no else None
                    if model_no:
                        models_data[model_no] = self.extract_model_data(recovery_master, 'RecoveryMasterCreation')
                        
            except ImportError:
                print("⚠️ RecoveryMasterCreation model not found, skipping recovery model search")
            except Exception as e:
                print(f"⚠️ Error searching RecoveryMasterCreation: {e}")
        
        print(f"   Total models_data collected: {len(models_data)}")
        return models_data
    
    def get_images_from_plating_stk_no(self, plating_stk_no):
        """
        Simple method to get model images by parsing plating_stk_no
        Example: "2648SSA02" -> model_no="2648", plating="S", polish="S", version="A"
        """
        if not plating_stk_no or len(plating_stk_no) < 7:
            return [static('assets/images/imagePlaceholder.jpg')]
        
        try:
            # Parse the components
            model_no = plating_stk_no[:4]  # First 4 chars: "2648"
            plating_code = plating_stk_no[4]  # 5th char: "S" 
            polish_code = plating_stk_no[5]  # 6th char: "S"
            version_code = plating_stk_no[6]  # 7th char: "A"
            
            # Find matching ModelMaster
            model_master = ModelMaster.objects.filter(
                model_no=model_no,
                plating_color__plating_color_internal=plating_code,
                polish_finish__polish_internal=polish_code,
                version__icontains=version_code
            ).prefetch_related('images').first()
            
            if model_master:
                # Get image URLs
                images = []
                for img in model_master.images.all():
                    if hasattr(img, 'master_image') and img.master_image:
                        images.append(img.master_image.url)
                
                return images if images else [static('assets/images/imagePlaceholder.jpg')]
            
        except Exception as e:
            print(f"Error parsing {plating_stk_no}: {e}")
        
        return [static('assets/images/imagePlaceholder.jpg')]
    def extract_model_data(self, model_master, source_type):
        """
        Extract model data from either ModelMasterCreation or RecoveryMasterCreation
        """
        # Get model images
        images = []
        if model_master.model_stock_no:
            for img in model_master.model_stock_no.images.all():
                if img.master_image:
                    images.append(img.master_image.url)
        
        if not images:
            images = [static('assets/images/imagePlaceholder.jpg')]
        
        model_no = model_master.model_stock_no.model_no if model_master.model_stock_no else None
        
        # Safe version access
        version_name = "No Version"
        if hasattr(model_master, 'version') and model_master.version:
            version_name = getattr(model_master.version, 'version_name', None) or getattr(model_master.version, 'version_internal', 'No Version')
        
        return {
            'batch_id': model_master.id,
            'model_no': model_no,
            'version_name': version_name,
            'plating_color': getattr(model_master, 'plating_color', None) or "No Plating Color",
            'polish_finish': getattr(model_master, 'polish_finish', None) or "No Polish Finish",
            'plating_stk_no': getattr(model_master, 'plating_stk_no', None) or "No Plating Stock No",
            'polishing_stk_no': getattr(model_master, 'polishing_stk_no', None) or "No Polishing Stock No",
            'location_name': model_master.location.location_name if hasattr(model_master, 'location') and model_master.location else "No Location",
            'tray_type': getattr(model_master, 'tray_type', None) or "No Tray Type",
            'tray_capacity': getattr(model_master, 'tray_capacity', 0) or 0,
            'vendor_internal': getattr(model_master, 'vendor_internal', None) or "No Vendor",
            'model_images': images,
            'model_stock_no_obj': model_master.model_stock_no,
            'source_type': source_type  # Track which model type this came from
        }

    def get_batch_data(self, batch_id, batch_model_class):
        """
        Get batch data for single model case from either ModelMasterCreation or RecoveryMasterCreation
        Updated to handle both model types
        """
        try:
            print(f"🔍 Getting batch data from {batch_model_class.__name__} for batch_id: {batch_id}")
            
            model_master = batch_model_class.objects.select_related(
                'version', 
                'model_stock_no', 
                'model_stock_no__tray_type', 
                'location'
            ).prefetch_related(
                'model_stock_no__images'
            ).get(id=batch_id)
            
            # Get model images
            images = []
            if model_master.model_stock_no:
                for img in model_master.model_stock_no.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            
            # Safe version access
            version_name = "No Version"
            if hasattr(model_master, 'version') and model_master.version:
                version_name = getattr(model_master.version, 'version_name', None) or getattr(model_master.version, 'version_internal', 'No Version')
            
            return {
                'batch_id': batch_id,
                'model_no': model_master.model_stock_no.model_no if model_master.model_stock_no else None,
                'version_name': version_name,
                'plating_color': getattr(model_master, 'plating_color', None) or "No Plating Color",
                'polish_finish': getattr(model_master, 'polish_finish', None) or "No Polish Finish",
                'plating_stk_no': getattr(model_master, 'plating_stk_no', None) or "No Plating Stock No",
                'polishing_stk_no': getattr(model_master, 'polishing_stk_no', None) or "No Polishing Stock No",
                'location_name': model_master.location.location_name if hasattr(model_master, 'location') and model_master.location else "No Location",
                'tray_type': getattr(model_master, 'tray_type', None) or "No Tray Type",
                'tray_capacity': getattr(model_master, 'tray_capacity', 0) or 0,
                'vendor_internal': getattr(model_master, 'vendor_internal', None) or "No Vendor",
                'model_images': images,
                'calculated_no_of_trays': 0,
                'batch_model_type': batch_model_class.__name__
            }
        except Exception as e:
            if 'DoesNotExist' in str(type(e)):
                print(f"⚠️ {batch_model_class.__name__} with id {batch_id} not found")
            else:
                print(f"⚠️ Error getting batch data: {e}")
            return self.get_default_values()
    
    def set_default_values(self, jig_detail_copy):
        """
        Set default values when no data is found
        """
        defaults = self.get_default_values()
        for key, value in defaults.items():
            setattr(jig_detail_copy, key, value)
    
    def get_default_values(self):
        """
        Get default values for when no model data is found
        """
        return {
            'batch_id': None,
            'model_no': None,
            'version_name': "No Version",
            'plating_color': "No Plating Color",
            'polish_finish': "No Polish Finish",
            'plating_stk_no': "No Plating Stock No",
            'polishing_stk_no': "No Polishing Stock No",
            'location_name': "No Location",
            'tray_type': "No Tray Type",
            'tray_capacity': 0,
            'vendor_internal': "No Vendor",
            'calculated_no_of_trays': 0,
            'model_images': [static('assets/images/imagePlaceholder.jpg')],
            'source_model': 'Unknown',
            'batch_model_type': 'Unknown'
        }

    def calculate_no_of_trays(self, jig_detail):
        """
        Calculate number of trays based on both TotalStockModel and RecoveryStockModel
        """
        total_trays = 0
        
        if not jig_detail.new_lot_ids:
            return 0
        
        print(f"🔢 Calculating no_of_trays for lot_ids: {jig_detail.new_lot_ids}")
        
        for lot_id in jig_detail.new_lot_ids:
            try:
                # Get stock model data (supports both types)
                stock_model, is_recovery, batch_model_class = self.get_stock_model_data(lot_id)
                
                if not stock_model or not stock_model.batch_id:
                    print(f"  ⚠️ No stock/batch data for lot_id: {lot_id}")
                    continue
                
                print(f"  📊 Processing lot_id {lot_id} ({'Recovery' if is_recovery else 'Regular'})")
                
                # Get tray capacity from batch data
                batch_data = stock_model.batch_id
                tray_capacity = getattr(batch_data, 'tray_capacity', 12)  # Default to 12
                
                # Get quantity used for this lot from jig_detail
                quantity_used = 0
                if jig_detail.lot_id_quantities and lot_id in jig_detail.lot_id_quantities:
                    quantity_used = jig_detail.lot_id_quantities.get(lot_id, 0)
                    if isinstance(quantity_used, str) and quantity_used.isdigit():
                        quantity_used = int(quantity_used)
                    elif not isinstance(quantity_used, (int, float)):
                        quantity_used = 0
                
                # Calculate number of trays for this lot
                if quantity_used > 0 and tray_capacity > 0:
                    lot_trays = math.ceil(quantity_used / tray_capacity)
                    total_trays += lot_trays
                    print(f"    ✅ Lot {lot_id}: {quantity_used} pieces ÷ {tray_capacity} capacity = {lot_trays} trays")
                else:
                    print(f"    ❌ Lot {lot_id}: Invalid quantities (used: {quantity_used}, capacity: {tray_capacity})")
                    
            except Exception as e:
                print(f"    ❌ Error calculating trays for lot_id {lot_id}: {e}")
                continue
        
        print(f"  🎯 Total calculated trays: {total_trays}")
        return total_trays
    
    def create_single_jig_detail_copy(self, original_jig_detail, lot_ids_data, model_cases_data, batch_status=None):
        """
        Create a single copy of jig_detail with ALL data as comma-separated values
        Updated to handle both stock model types and calculate no_of_trays
        """
        # Create a new object that behaves like the original but with additional attributes
        jig_detail_copy = type('JigDetailCopy', (), {})()
        
        # Copy all original attributes
        for attr in dir(original_jig_detail):
            if not attr.startswith('_'):
                try:
                    setattr(jig_detail_copy, attr, getattr(original_jig_detail, attr))
                except:
                    pass
        
        # Add lot_ids data (comma-separated values from new_lot_ids)
        jig_detail_copy.lot_plating_stk_nos = lot_ids_data['plating_stk_nos']
        jig_detail_copy.lot_polishing_stk_nos = lot_ids_data['polishing_stk_nos']
        jig_detail_copy.lot_version_names = lot_ids_data['version_names']
        jig_detail_copy.batch_status = batch_status

        # Add model_cases data (comma-separated values from no_of_model_cases)
        jig_detail_copy.model_plating_stk_nos = model_cases_data['model_plating_stk_nos']
        jig_detail_copy.model_polishing_stk_nos = model_cases_data['model_polishing_stk_nos']
        jig_detail_copy.model_version_names = model_cases_data['model_version_names']
        
        # Combine both sources for final display (you can choose which one to prioritize)
        # Option 1: Use model_cases data if available, otherwise lot_ids data
        jig_detail_copy.final_plating_stk_nos = (
            jig_detail_copy.model_plating_stk_nos if jig_detail_copy.model_plating_stk_nos 
            else jig_detail_copy.lot_plating_stk_nos
        )
        jig_detail_copy.final_polishing_stk_nos = (
            jig_detail_copy.model_polishing_stk_nos if jig_detail_copy.model_polishing_stk_nos 
            else jig_detail_copy.lot_polishing_stk_nos
        )
        jig_detail_copy.final_version_names = (
            jig_detail_copy.model_version_names if jig_detail_copy.model_version_names 
            else jig_detail_copy.lot_version_names
        )
        
        # *** NEW: Calculate no_of_trays based on both stock models ***
        jig_detail_copy.calculated_no_of_trays = self.calculate_no_of_trays(original_jig_detail)
        
        # Add single instance indicators
        jig_detail_copy.is_single_instance = True
        jig_detail_copy.has_multiple_lots = bool(lot_ids_data['plating_stk_nos'])
        jig_detail_copy.has_multiple_models = bool(model_cases_data['model_plating_stk_nos'])
        
        # *** UPDATED: Get additional data from appropriate stock model ***
        if original_jig_detail.lot_id:
            try:
                stock_model, is_recovery, batch_model_class = self.get_stock_model_data(original_jig_detail.lot_id)
                
                if stock_model and stock_model.batch_id:
                    print(f"🔍 Getting batch data for lot {original_jig_detail.lot_id} from {'Recovery' if is_recovery else 'Regular'} model")
                    batch_data = self.get_batch_data(stock_model.batch_id.id, batch_model_class)
                    
                    # Apply batch data for additional fields not covered by comma-separated data
                    for key, value in batch_data.items():
                        if not hasattr(jig_detail_copy, key) or getattr(jig_detail_copy, key) is None:
                            setattr(jig_detail_copy, key, value)
                    
                    # Add source information
                    jig_detail_copy.source_model = 'RecoveryStock' if is_recovery else 'TotalStock'
                    jig_detail_copy.batch_model_type = 'RecoveryMasterCreation' if is_recovery else 'ModelMasterCreation'
                else:
                    self.set_default_values(jig_detail_copy)
            except Exception as e:
                print(f"⚠️ Error getting batch data for lot {original_jig_detail.lot_id}: {e}")
                self.set_default_values(jig_detail_copy)
        else:
            self.set_default_values(jig_detail_copy)
        
        return jig_detail_copy
        
   
        
# ✅ CORRECTED: AfterCheckTrayValidate_Complete_APIView - Use BrassTrayId and remove False filtering
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JIGTrayValidate_Complete_APIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            batch_id_input = str(data.get('batch_id')).strip()
            tray_id = str(data.get('tray_id')).strip()
            
            # ✅ Get Brass Audit status parameters
            brassQcAccptance = data.get('brass_audit_accptance', False)
            brassQcRejection = data.get('brass_audit_rejection', False)
            brassQcFewCases = data.get('brass_qc_few_cases_accptance', False)

            print(f"🔧 [AfterCheckTrayValidate_Complete_APIView] Received:")
            print(f"   batch_id: {batch_id_input}")
            print(f"   tray_id: {tray_id}")
            print(f"   brass_audit_accptance: {brassQcAccptance}")
            print(f"   brass_audit_rejection: {brassQcRejection}")
            print(f"   brass_qc_few_cases_accptance: {brassQcFewCases}")

            # ✅ CORRECTED: Use BrassTrayId model (created after brass checkbox verification)
            base_queryset = BrassTrayId.objects.filter(
                batch_id__batch_id__icontains=batch_id_input,
                tray_quantity__gt=0
            )
            
            print(f"✅ [AfterCheckTrayValidate] Using BrassTrayId model")
            print(f"✅ [AfterCheckTrayValidate] Base queryset count: {base_queryset.count()}")
            
            # ✅ CORRECTED: Only apply filtering if at least one Brass Audit parameter is True
            has_brass_qc_status = brassQcAccptance or brassQcRejection or brassQcFewCases
            
            if has_brass_qc_status:
                # Apply filtering only when there's actual Brass Audit status
                if brassQcAccptance and not brassQcFewCases:
                    # Only validate against Brass Audit accepted trays
                    trays = base_queryset.filter(rejected_tray=False)
                    print(f"✅ [AfterCheckTrayValidate] Validating against Brass Audit ACCEPTED trays only")
                elif brassQcRejection and not brassQcFewCases:
                    # Only validate against Brass Audit rejected trays
                    trays = base_queryset.filter(rejected_tray=True)
                    print(f"✅ [AfterCheckTrayValidate] Validating against Brass Audit REJECTED trays only")
                else:
                    # Validate against all trays (few_cases or default)
                    trays = base_queryset
                    print(f"✅ [AfterCheckTrayValidate] Validating against ALL BrassTrayId records")
            else:
                # ✅ NEW: When all parameters are False, validate against all BrassTrayId records
                trays = base_queryset
                print(f"✅ [AfterCheckTrayValidate] All Brass Audit parameters are False - validating against ALL BrassTrayId records")
            
            print(f"✅ [AfterCheckTrayValidate] Available tray_ids: {[t.tray_id for t in trays[:10]]}...")  # Show first 10

            exists = trays.filter(tray_id=tray_id).exists()
            print(f"🔍 [AfterCheckTrayValidate] Tray ID '{tray_id}' exists in BrassTrayId results? {exists}")

            # Get additional info about the tray if it exists
            tray_info = {}
            if exists:
                tray = trays.filter(tray_id=tray_id).first()
                if tray:
                    tray_info = {
                        'rejected_tray': getattr(tray, 'rejected_tray', False),
                        'tray_quantity': tray.tray_quantity,
                        'top_tray': getattr(tray, 'top_tray', False),
                        'top_tray': getattr(tray, 'top_tray', False),
                        'rejected_tray': getattr(tray, 'rejected_tray', False),  # This might not exist in BrassTrayId
                        'ip_top_tray': getattr(tray, 'ip_top_tray', False),  # Add IP top tray info
                        'data_source': 'BrassTrayId'  # ✅ NEW: Indicate data source
                    }

            return JsonResponse({
                'success': True, 
                'exists': exists,
                'tray_info': tray_info,
                'data_source': 'BrassTrayId',  # ✅ NEW: Indicate data source
                'filtering_applied': has_brass_qc_status  # ✅ NEW: Indicate if filtering was applied
            })
            
        except Exception as e:
            print(f"❌ [AfterCheckTrayValidate_Complete_APIView] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
           
# ✅ CORRECTED: AfterCheckPickTrayIdList_Complete_APIView - Use BrassTrayId and remove False filtering
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class JIGTrayIdList_Complete_APIView(APIView):
    def get(self, request):
        stock_lot_id = request.GET.get('stock_lot_id')
        lot_id = request.GET.get('lot_id') or stock_lot_id
        brass_audit_accptance = request.GET.get('brass_audit_accptance', 'false').lower() == 'true'
        brass_audit_rejection = request.GET.get('brass_audit_rejection', 'false').lower() == 'true'
        brass_audit_few_cases_accptance = request.GET.get('brass_audit_few_cases_accptance', 'false').lower() == 'true'

        if not lot_id:
            return JsonResponse({'success': False, 'error': 'Missing lot_id or stock_lot_id'}, status=400)

        # ✅ CORRECTED: Use BrassTrayId model (created after brass checkbox verification)
        base_queryset = JigLoadTrayId.objects.filter(
            tray_quantity__gt=0,
            lot_id=lot_id
        ).exclude(rejected_tray=True)

        # ✅ CORRECTED: Only apply filtering if at least one Brass Audit parameter is True
        has_brass_qc_status = brass_audit_accptance or brass_audit_rejection or brass_audit_few_cases_accptance
        
        if has_brass_qc_status:
            # Apply filtering only when there's actual Brass Audit status
            if brass_audit_accptance and not brass_audit_few_cases_accptance:
                # Show only Brass Audit accepted trays
                queryset = base_queryset.filter(rejected_tray=False)
            elif brass_audit_rejection and not brass_audit_few_cases_accptance:
                # Show only Brass Audit rejected trays
                queryset = base_queryset.filter(rejected_tray=True)
            elif brass_audit_few_cases_accptance:
                # Show both accepted and rejected trays
                queryset = base_queryset
            else:
                queryset = base_queryset
        else:
            # ✅ NEW: When all parameters are False, show all BrassTrayId records without filtering
            queryset = base_queryset


        # ✅ UPDATED: Find top tray using BrassTrayId fields
        # Check for top_tray first, then fall back to top_tray
        top_tray = queryset.filter(top_tray=True).first()
        if not top_tray:
            top_tray = queryset.filter(top_tray=True).first()
        
        other_trays = queryset.exclude(pk=top_tray.pk if top_tray else None).order_by('id')

        data = []
        row_counter = 1

        def create_tray_data(tray_obj, is_top=False):
            nonlocal row_counter
            
            # Get rejection details if tray is rejected in Brass Audit
            rejection_details = []
            if getattr(tray_obj, 'rejected_tray', False):
                rejected_scans = Brass_Audit_Rejected_TrayScan.objects.filter(
                    lot_id=lot_id,
                    rejected_tray_id=tray_obj.tray_id
                )
                for scan in rejected_scans:
                    rejection_details.append({
                        'rejected_quantity': scan.rejected_tray_quantity,
                        'rejection_reason': scan.rejection_reason.rejection_reason if scan.rejection_reason else 'Unknown',
                        'rejection_reason_id': scan.rejection_reason.rejection_reason_id if scan.rejection_reason else None,
                        'user': scan.user.username if scan.user else None
                    })
                    
            
            return {
                's_no': row_counter,
                'tray_id': tray_obj.tray_id,
                'tray_quantity': tray_obj.tray_quantity,
                'position': row_counter - 1,
                'is_top_tray': is_top,
                'rejected_tray': getattr(tray_obj, 'rejected_tray', False),
                'delink_tray': getattr(tray_obj, 'delink_tray', False),
                'rejection_details': rejection_details,
                'top_tray': getattr(tray_obj, 'top_tray', False),
                'top_tray': getattr(tray_obj, 'top_tray', False),
                'rejected_tray': getattr(tray_obj, 'rejected_tray', False),  # This might not exist in BrassTrayId
                'ip_top_tray': getattr(tray_obj, 'ip_top_tray', False),  # Add IP top tray info
                'ip_top_tray_qty': getattr(tray_obj, 'ip_top_tray_qty', None)  # Add IP top tray qty
            }

        # Add top tray first if exists
        if top_tray:
            data.append(create_tray_data(top_tray, is_top=True))
            row_counter += 1
            
        # Add other trays
        for tray in other_trays:
            data.append(create_tray_data(tray, is_top=False))
            row_counter += 1

        print(f"✅ [AfterCheckPickTrayIdList_Complete_APIView] Total trays returned: {len(data)}")

        # ✅ UPDATED: Summary based on BrassTrayId
        if has_brass_qc_status:
            accepted_trays = base_queryset.filter(rejected_tray=False)
            rejected_trays = base_queryset.filter(rejected_tray=True)
        else:
            # When no Brass Audit status, consider all as "available"
            accepted_trays = base_queryset
            rejected_trays = base_queryset.none()  # Empty queryset

        rejection_summary = {
            'total_accepted_trays': accepted_trays.count(),
            'accepted_tray_ids': list(accepted_trays.values_list('tray_id', flat=True)),
            'total_rejected_trays': rejected_trays.count(),
            'rejected_tray_ids': list(rejected_trays.values_list('tray_id', flat=True)),
            'filter_applied': f'brass_qc_status_filtering_{"enabled" if has_brass_qc_status else "disabled"}',
            'data_source': 'BrassTrayId'  # ✅ NEW: Indicate data source
        }

        return JsonResponse({
            'success': True,
            'trays': data,
            'rejection_summary': rejection_summary
        })
        

  
def chunk_list(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


@method_decorator(login_required, name='dispatch')
class JigCompositionView(TemplateView):
    template_name = "JigLoading/Jig_Composition.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lot_ids_param = self.request.GET.get('lot_ids', '')
        lot_ids = lot_ids_param.split(',') if lot_ids_param else []
        print("==== JigCompositionView: Received lot_ids ====")
        print(lot_ids)
        context['selected_lot_ids'] = lot_ids

        # Dynamic color palette (expand as needed)
        color_palette = [
            "#009688", "#0378bd", "#ffc107", "#28a745", "#dc3545",
            "#8e44ad", "#e67e22", "#16a085", "#2c3e50", "#f39c12",
            "#1abc9c", "#e84393", "#6c5ce7", "#fdcb6e", "#00b894"
        ]
        model_color_map = {}
        color_index = 0

        model_list = []
        for lot_id in lot_ids:
            tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
            if not tsm:
                continue
            mmc = tsm.batch_id if tsm.batch_id else None
            model_no = mmc.model_stock_no.model_no if mmc and mmc.model_stock_no else None

            if not model_no:
                model_no = "Unknown"

            # Assign color dynamically
            if model_no not in model_color_map:
                model_color_map[model_no] = color_palette[color_index % len(color_palette)]
                color_index += 1
            color = model_color_map[model_no]

            if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                original_qty = tsm.jig_physical_qty
            else:
                original_qty = tsm.brass_audit_accepted_qty or 0

            from django.db.models import Q
            jig_details = JigDetails.objects.filter(
                Q(lot_id=lot_id) | Q(new_lot_ids__contains=[lot_id]),
                draft_save=False
            )
            total_used_qty = 0
            for jig_detail in jig_details:
                if jig_detail.lot_id_quantities and lot_id in jig_detail.lot_id_quantities:
                    used_qty = jig_detail.lot_id_quantities.get(lot_id, 0)
                    if isinstance(used_qty, (int, float)):
                        total_used_qty += int(used_qty)
                    elif isinstance(used_qty, str) and used_qty.isdigit():
                        total_used_qty += int(used_qty)
            remaining_qty = max(0, original_qty - total_used_qty)
            case_qty = remaining_qty if remaining_qty > 0 else original_qty

            model_list.append({
                "model_no": model_no,
                "case_qty": case_qty,
                "case_numbers": list(range(1, case_qty + 1)),
                "color": color,
            })

        all_cases = []
        for model in model_list:
            for case in model["case_numbers"]:
                all_cases.append({
                    "model_no": model["model_no"],
                    "case_qty": model["case_qty"],
                    "case_number": case,
                    "color": model["color"],
                })
        def chunk_list(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i + n]
        cards = []
        for chunk in chunk_list(all_cases, 12):
            models_in_card = []
            seen = set()
            for item in chunk:
                if item["model_no"] not in seen:
                    models_in_card.append({
                        "model_no": item["model_no"],
                        "case_qty": item["case_qty"],
                        "color": item["color"],
                    })
                    seen.add(item["model_no"])
            cards.append({
                "models": models_in_card,
                "cases": chunk,
                "color": chunk[0]["color"] if chunk else "#01524a",
            })
        context["cards"] = cards
        return context
    
# Saving auto-draft
@csrf_exempt
@require_http_methods(["POST"])
@login_required
def jig_autosave(request):
    try:
        # Enhanced debugging
        logger.info(f"Auto-save request from user: {request.user} - Content-Type: {request.content_type}")
        
        # Parse request body with better error handling
        try:
            raw_body = request.body or b'{}'
            logger.info(f"Raw request body: {raw_body}")
            data = json.loads(raw_body)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        
        logger.info(f"Parsed data: {data}")
        
        lot_id = data.get('lot_id')

        # Validate lot_id early
        if not lot_id:
            logger.error("No lot_id provided in autosave request")
            return JsonResponse({'success': False, 'error': 'lot_id is required'}, status=400)

        logger.info(f"Processing autosave for lot_id: {lot_id}")

        # Get existing draft if any
        prev_exists = None
        try:
            prev_exists = JigAutoSave.objects.filter(user=request.user, lot_id=lot_id).first()
            logger.info(f"Previous autosave exists: {prev_exists is not None}")
        except Exception as e:
            logger.error(f"Error checking existing autosave: {e}")
            prev_exists = None

        # Determine whether incoming payload is "meaningful"
        jig_qr_filled = bool(str(data.get('jig_qr_id', '')).strip())
        has_tray_data = bool(data.get('delink_tray_data') or data.get('half_filled_tray_data'))
        has_quantities = bool(int(data.get('total_cases_loaded', 0)) > 0)
        has_cycle_data = data.get('no_of_cycle_count', '-/-') not in ('', '-/-', None)

        is_empty = not (jig_qr_filled or has_tray_data or has_quantities or has_cycle_data)
        
        logger.info(f"Data analysis - jig_qr_filled: {jig_qr_filled}, has_tray_data: {has_tray_data}, has_quantities: {has_quantities}, has_cycle_data: {has_cycle_data}, is_empty: {is_empty}")

        # If payload is empty and previous exists -> clear the previous autosave
        if is_empty:
            if prev_exists:
                prev_exists.delete()
                logger.info("Empty autosave cleared")
                return JsonResponse({'success': True, 'cleared': True, 'message': 'Empty autosave cleared'})
            else:
                logger.info("Nothing to save - no data and no previous save")
                return JsonResponse({'success': True, 'cleared': False, 'message': 'Nothing to save'})

        # Proceed to save/update autosave (always allow if jig_qr_filled OR other meaningful fields present)
        try:
            autosave, created = JigAutoSave.objects.update_or_create(
                user=request.user,
                lot_id=lot_id,
                defaults={
                    'jig_qr_id': data.get('jig_qr_id', ''),
                    'faulty_slots': int(data.get('faulty_slots', 0) or 0),
                    'empty_slots': int(data.get('empty_slots', 0) or 0),
                    'total_cases_loaded': int(data.get('total_cases_loaded', 0) or 0),
                    'delink_tray_data': data.get('delink_tray_data', []),
                    'half_filled_tray_data': data.get('half_filled_tray_data', []),
                    'lot_id_quantities': data.get('lot_id_quantities', {}),
                    'selected_model_nos': data.get('selected_model_nos', []),
                    'no_of_cycle_count': data.get('no_of_cycle_count', '-/-'),
                }
            )
            logger.info(f"Autosave {'created' if created else 'updated'} successfully for lot_id: {lot_id}")
            return JsonResponse({'success': True, 'created': created, 'lot_id': lot_id})
        except Exception as db_error:
            logger.error(f"Database error during autosave: {db_error}")
            return JsonResponse({'success': False, 'error': f'Database error: {str(db_error)}'}, status=500)

    except Exception as e:
        logger.error(f"Unexpected error in jig_autosave: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    
# Debug endpoint to test autosave functionality
@csrf_exempt
@require_http_methods(["GET", "POST"])
@login_required
def debug_autosave_test(request):
    """Debug endpoint to test autosave functionality"""
    if request.method == 'GET':
        # Return current autosave records for this user
        autosaves = JigAutoSave.objects.filter(user=request.user).order_by('-updated_at')
        data = []
        for autosave in autosaves:
            data.append({
                'id': autosave.id,
                'lot_id': autosave.lot_id,
                'jig_qr_id': autosave.jig_qr_id,
                'faulty_slots': autosave.faulty_slots,
                'empty_slots': autosave.empty_slots,
                'total_cases_loaded': autosave.total_cases_loaded,
                'delink_tray_data': autosave.delink_tray_data,
                'half_filled_tray_data': autosave.half_filled_tray_data,
                'lot_id_quantities': autosave.lot_id_quantities,
                'selected_model_nos': autosave.selected_model_nos,
                'no_of_cycle_count': autosave.no_of_cycle_count,
                'has_meaningful_data': autosave.has_meaningful_data(),
                'created_at': autosave.created_at.isoformat(),
                'updated_at': autosave.updated_at.isoformat(),
                'is_expired': autosave.is_expired(),
            })
        
        return JsonResponse({
            'success': True, 
            'autosaves': data, 
            'count': len(data),
            'user': request.user.username,
            'message': f'Found {len(data)} autosave records'
        })
    
    elif request.method == 'POST':
        # Test creating an autosave entry with comprehensive data
        test_lot_id = f'TEST_LOT_DEBUG_{timezone.now().strftime("%Y%m%d_%H%M%S")}'
        test_data = {
            'lot_id': test_lot_id,
            'jig_qr_id': 'TEST_JIG_123',
            'faulty_slots': 5,
            'empty_slots': 3,
            'total_cases_loaded': 100,
            'delink_tray_data': [
                {'tray_id': 'T001', 'qty': 50, 'lot_id': test_lot_id},
                {'tray_id': 'T002', 'qty': 50, 'lot_id': test_lot_id}
            ],
            'half_filled_tray_data': [
                {'tray_id': 'T003', 'remaining_qty': 25, 'lot_id': test_lot_id}
            ],
            'lot_id_quantities': {test_lot_id: 100},
            'selected_model_nos': ['MODEL_001', 'MODEL_002'],
            'no_of_cycle_count': '1/30'
        }
        
        try:
            # Delete any existing test data first
            JigAutoSave.objects.filter(user=request.user, lot_id__startswith='TEST_LOT_DEBUG_').delete()
            
            autosave, created = JigAutoSave.objects.update_or_create(
                user=request.user,
                lot_id=test_data['lot_id'],
                defaults=test_data
            )
            
            return JsonResponse({
                'success': True, 
                'created': created, 
                'autosave_id': autosave.id,
                'has_meaningful_data': autosave.has_meaningful_data(),
                'message': f'Test autosave {"created" if created else "updated"} successfully',
                'data': autosave.to_dict()
            })
        except Exception as e:
            logger.error(f"Debug test autosave error: {e}", exc_info=True)
            return JsonResponse({'success': False, 'error': str(e)})


# Clearing Auto -save data
@csrf_exempt
@require_http_methods(["DELETE"])
def clear_jig_autosave(request, lot_id):
    try:
        JigAutoSave.objects.filter(user=request.user, lot_id=lot_id).delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# Get auto-save data
def get_jig_autosave(request, lot_id):
    """
    Return autosave data for the logged-in user and given lot_id.
    Cleans expired autosaves older than 24h.
    """
    try:
        if not request.user.is_authenticated:
            return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)

        # Clean expired first (non-fatal)
        try:
            expired = JigAutoSave.objects.filter(
                user=request.user,
                lot_id=lot_id,
                updated_at__lt=timezone.now() - timedelta(hours=24)
            )
            if expired.exists():
                count = expired.count()
                expired.delete()
                logger.info(f"Cleaned {count} expired auto-saves for user {request.user} lot {lot_id}")
        except Exception as e:
            logger.warning(f"Error cleaning expired autosaves: {e}")

        autosave = JigAutoSave.objects.filter(user=request.user, lot_id=lot_id).first()
        if not autosave:
            return JsonResponse({'success': True, 'has_data': False, 'data': None})

        data = {
            'has_data': True,
            'created_at': autosave.created_at.isoformat(),
            'updated_at': autosave.updated_at.isoformat(),
            'jig_qr_id': autosave.jig_qr_id,
            'faulty_slots': autosave.faulty_slots,
            'empty_slots': autosave.empty_slots,
            'total_cases_loaded': autosave.total_cases_loaded,
            'delink_tray_data': autosave.delink_tray_data,
            'half_filled_tray_data': autosave.half_filled_tray_data,
            'lot_id_quantities': autosave.lot_id_quantities,
            'selected_model_nos': autosave.selected_model_nos,
            'no_of_cycle_count': autosave.no_of_cycle_count,
        }
        return JsonResponse({'success': True, 'has_data': True, 'data': data})
    except Exception as e:
        logging.exception("Error in get_jig_autosave")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
    

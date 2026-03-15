from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.db.models import OuterRef, Subquery, Exists, F
from django.core.paginator import Paginator
from django.templatetags.static import static
import math
from IQF.models import IQFTrayId
from modelmasterapp.models import *
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
from django.views.generic import TemplateView
from rest_framework.decorators import api_view
from rest_framework.response import Response
from Brass_QC.models import *
from DayPlanning.models import *
from InputScreening.models import *
from BrassAudit.models import *
from Jig_Loading.models import *
from Jig_Unloading.models import *
from Nickel_Audit.models import *
from Spider_Spindle.models import *

class Zone_SpiderPickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Spider_Spindle/Spider_Pick_Table.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False
        
        # Get all plating_color IDs where jig_unload_zone_2 is True
        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_2=True
        ).values_list('id', flat=True)
        
        # STEP 1: Query JigUnloadAfterTable with NA (Nickel Audit) criteria
        # Get rejection quantities as subquery for NA
        na_rejection_qty_subquery = Nickel_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        # Query JigUnloadAfterTable with NA acceptance criteria
        queryset = JigUnloadAfterTable.objects.select_related(
            'version',
            'plating_color',
            'polish_finish'
        ).prefetch_related(
            'location'  # ManyToManyField requires prefetch_related
        ).filter(
            Q(na_qc_accptance=True) | Q(na_qc_few_cases_accptance=True),
            total_case_qty__gt=0, # Only show records with quantity > 0
            plating_color_id__in=allowed_color_ids,  # ✅ CHANGED: Only show records for zone 1

            # NA (Nickel Audit) acceptance criteria instead of brass audit
 # Exclude completed jig loads (if field exists)
        ).annotate(
            na_rejection_qty=na_rejection_qty_subquery,
        ).order_by('-na_last_process_date_time')  # Order by NA last process date

        # Filter out "Yet to Release" lots using list comprehension
        eligible_lots = [lot for lot in queryset if self.calculate_batch_status(lot.lot_id)['status'] != 'Yet to Release']
        
        print(f"Found {len(eligible_lots)} eligible lots after status filtering")

        # Convert back to queryset for pagination
        eligible_lot_ids = [lot.lot_id for lot in eligible_lots]
        filtered_queryset = JigUnloadAfterTable.objects.filter(
            lot_id__in=eligible_lot_ids
        ).select_related(
            'version',
            'plating_color', 
            'polish_finish'
        ).prefetch_related(
            'location'
        ).annotate(
            na_rejection_qty=na_rejection_qty_subquery,
        ).order_by('-na_last_process_date_time')

        # STEP 2: Get related JigLoadingMaster data lookup
        jig_loading_lookup = {}
        for jlm in JigLoadingMaster.objects.all():
            jig_loading_lookup[jlm.model_stock_no_id] = jlm

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(filtered_queryset, 10)
        page_obj = paginator.get_page(page_number)

        # STEP 3: Build master_data from JigUnloadAfterTable records with NA fields
        master_data = []
        for jig_unload_obj in page_obj.object_list:
            
            # Build data dict from JigUnloadAfterTable with NA fields
            data = {
                'batch_id': jig_unload_obj.unload_lot_id,  # Using unload_lot_id as batch identifier
                'date_time': jig_unload_obj.created_at,
                'model_stock_no__model_no': 'Combined Model',  # Since this combines multiple lots
                'plating_color': jig_unload_obj.plating_color.plating_color if jig_unload_obj.plating_color else '',
                'polish_finish': jig_unload_obj.polish_finish.polish_finish if jig_unload_obj.polish_finish else '',
                'version__version_internal': jig_unload_obj.version.version_internal if jig_unload_obj.version else '',
                'vendor_internal': '',  # Not available in JigUnloadAfterTable
                'location__location_name': ', '.join([loc.location_name for loc in jig_unload_obj.location.all()]),
                'no_of_trays': 0,  # Will be calculated later
                'tray_type': jig_unload_obj.tray_type or '',
                'tray_capacity': jig_unload_obj.tray_capacity or 0,
                'Moved_to_D_Picker': False,  # Not applicable for JigUnloadAfterTable
                'Draft_Saved': jig_unload_obj.na_draft,  # Use NA draft field
                'plating_stk_no': jig_unload_obj.plating_stk_no or '',
                'polishing_stk_no': jig_unload_obj.polish_stk_no or '',
                'category': jig_unload_obj.category or '',
                'stock_lot_id': jig_unload_obj.lot_id,
                # Stock-related fields from JigUnloadAfterTable - using NA fields instead of brass_audit
                'last_process_module': jig_unload_obj.last_process_module or 'Jig Unload',
                'next_process_module': jig_unload_obj.next_process_module or 'Nickel Audit',  # Default next process
                'brass_audit_accepted_qty_verified': jig_unload_obj.na_ac_accepted_qty_verified,  # Map to NA field
                'brass_audit_accepted_qty': jig_unload_obj.na_qc_accepted_qty or 0,  # Use NA accepted qty
                'brass_audit_missing_qty': jig_unload_obj.na_missing_qty or 0,  # Use NA missing qty
                'brass_audit_physical_qty': jig_unload_obj.na_physical_qty,  # Use NA physical qty
                'brass_audit_physical_qty_edited': False,  # Not available in JigUnloadAfterTable
                'spider_pick_remarks': jig_unload_obj.spider_pick_remarks or '',  # Use NA pick remarks
                'brass_audit_accptance': jig_unload_obj.na_qc_accptance,  # Use NA acceptance
                'brass_audit_accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,  # Use NA tray scan
                'brass_audit_rejection': jig_unload_obj.na_qc_rejection,  # Use NA rejection
                'brass_audit_few_cases_accptance': jig_unload_obj.na_qc_few_cases_accptance,  # Use NA few cases
                'brass_audit_onhold_picking': jig_unload_obj.na_onhold_picking,  # Use NA onhold
                'jig_physical_qty': jig_unload_obj.jig_physical_qty,  # Use na_physical_qty as requested
                'stock_lot_id': jig_unload_obj.lot_id,
                'edited_quantity': jig_unload_obj.na_physical_qty or 0,  # Use na_physical_qty
                'brass_audit_last_process_date_time': jig_unload_obj.na_last_process_date_time,  # Use NA last process date
                'brass_rejection_qty': jig_unload_obj.na_rejection_qty or 0,  # Use NA rejection qty
                
                # Additional fields from JigUnloadAfterTable
                'combine_lot_ids': jig_unload_obj.combine_lot_ids,  # Show which lots were combined
                'unload_lot_id': jig_unload_obj.unload_lot_id,  # Additional identifier
                'total_case_qty': jig_unload_obj.total_case_qty,
                
                # NA-specific fields (keeping original names for template compatibility)
                'na_qc_accptance': jig_unload_obj.na_qc_accptance,
                'na_qc_rejection': jig_unload_obj.na_qc_rejection,
                'na_qc_few_cases_accptance': jig_unload_obj.na_qc_few_cases_accptance,
                'na_onhold_picking': jig_unload_obj.na_onhold_picking,
                'na_physical_qty': jig_unload_obj.na_physical_qty,
                'na_qc_accepted_qty': jig_unload_obj.na_qc_accepted_qty,
                'na_missing_qty': jig_unload_obj.na_missing_qty,
                'na_pick_remarks': jig_unload_obj.na_pick_remarks,
                'na_accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,
                'na_last_process_date_time': jig_unload_obj.na_last_process_date_time,
                'spider_hold_lot': jig_unload_obj.spider_hold_lot,
                'spider_release_lot': jig_unload_obj.spider_release_lot,
                'spider_holding_reason': jig_unload_obj.spider_holding_reason,
                'spider_release_reason': jig_unload_obj.spider_release_reason,
                'na_draft': jig_unload_obj.na_draft,
            }

            # Get JigLoadingMaster and ModelMaster data using plating_stk_no logic
            jlm = None
            model_master = None
            plating_stk_no = getattr(jig_unload_obj, 'plating_stk_no', '')
            if plating_stk_no and len(plating_stk_no) >= 4:
                model_no_prefix = plating_stk_no[:4]
                # Find JigLoadingMaster where model_stock_no__model_no matches the prefix
                jlm = JigLoadingMaster.objects.filter(
                    model_stock_no__model_no__startswith=model_no_prefix
                ).first()
                
                # Find ModelMaster where model_no matches the prefix for images
                model_master = ModelMaster.objects.filter(
                    model_no__startswith=model_no_prefix
                ).prefetch_related('images').first()
            
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

            record_lot_id = jig_unload_obj.lot_id  # Get lot_id from the current record
            
            # Display quantity logic - prioritize na_physical_qty
            jig_physical_qty = data.get('jig_physical_qty', 0)  # This is na_physical_qty
            na_accepted_qty = data.get('brass_audit_accepted_qty', 0)  # This is na_qc_accepted_qty
            na_physical_qty = data.get('na_physical_qty', 0)
            # Always prioritize jig_physical_qty if present and > 0
            if jig_physical_qty and jig_physical_qty > 0:
                data['display_qty'] = jig_physical_qty
            else:
                # Check for total_rejection_quantity in Nickel_Audit_Rejection_ReasonStore
                rejection_obj = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=record_lot_id).first()
                if rejection_obj and rejection_obj.total_rejection_quantity is not None:
                    data['display_qty'] = max(0, (na_physical_qty or 0) - rejection_obj.total_rejection_quantity)
                else:
                    data['display_qty'] = na_accepted_qty
                
            print(f"batch_id={data['batch_id']}, na_physical_qty={jig_physical_qty}, na_qc_accepted_qty={na_accepted_qty}, model_master_found={'Yes' if model_master else 'No'}")

            # Get model images from ModelMaster based on model_no prefix
            images = []
            if model_master:
                # Get images from ModelMaster
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            
            # Use placeholder if no images found
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            
            data['model_images'] = images

            # Calculate batch status
            lot_id = data.get('stock_lot_id')
            batch_status = self.calculate_batch_status(lot_id)
            data['batch_status'] = batch_status
                    
            # Always calculate no_of_trays based on the latest display_qty
            tray_capacity = data.get('tray_capacity', 0)
            if tray_capacity > 0:
                data['no_of_trays'] = math.ceil(data['display_qty'] / tray_capacity)
            else:
                data['no_of_trays'] = 0
            
            print(f"Lot ID: {lot_id}, Batch Status: {batch_status['status']}, Display Qty: {data['display_qty']}, No of Trays: {data['no_of_trays']}, Images Found: {len(images)}")
            
            master_data.append(data)

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
        }
        return Response(context, template_name=self.template_name)

    def calculate_batch_status(self, lot_id):
        """
        Returns a dict with:
        - status: 'Draft' if some trays are delinked and some are not,
                  'Yet to Release' if all trays are delinked,
                  'Yet to Start' if none are delinked or no trays exist
        - remaining_qty: int (jig_physical_qty or 0)
        - color, bg_color, border_color: for UI display
        """
        jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_obj:
            jig_physical_qty = jig_unload_obj.jig_physical_qty or 0
        else:
            tsm = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if not tsm:
                return {
                    'status': 'Yet to Start',
                    'remaining_qty': 0,
                    'color': '#856404',
                    'bg_color': '#fff3cd',
                    'border_color': '#ffc107'
                }
            jig_physical_qty = tsm.jig_physical_qty or 0
    
        tray_qs = Spider_TrayId.objects.filter(lot_id=lot_id)
        total_trays = tray_qs.count()
        delinked_trays = tray_qs.filter(delink_tray=True).count()
    
        if total_trays == 0:
            # No trays exist
            return {
                'status': 'Yet to Start',
                'remaining_qty': jig_physical_qty,
                'color': '#856404',
                'bg_color': '#fff3cd',
                'border_color': '#ffc107'
            }
        elif delinked_trays == total_trays:
            # All trays are delinked
            return {
                'status': 'Yet to Release',
                'remaining_qty': 0,
                'color': '#721c24',
                'bg_color': '#f8d7da',
                'border_color': '#f5c6cb'
            }
        elif 0 < delinked_trays < total_trays:
            # Some trays are delinked, some are not
            return {
                'status': 'Draft',
                'remaining_qty': jig_physical_qty,
                'color': '#004085',
                'bg_color': '#cce5ff',
                'border_color': '#b8daff'
            }
        else:
            # No trays are delinked
            return {
                'status': 'Yet to Start',
                'remaining_qty': jig_physical_qty,
                'color': '#856404',
                'bg_color': '#fff3cd',
                'border_color': '#ffc107'
            }


@method_decorator(csrf_exempt, name='dispatch')
class Zone_Spider_SaveHoldUnholdReasonAPIView(APIView):
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
            print("DEBUG: Received lot_id:", lot_id)  # <-- Add this line

            remark = data.get('remark', '').strip()
            action = data.get('action', '').strip().lower()

            if not lot_id or not remark or action not in ['hold', 'unhold']:
                return JsonResponse({'success': False, 'error': 'Missing or invalid parameters.'}, status=400)

            obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if not obj:
                return JsonResponse({'success': False, 'error': 'LOT not found.'}, status=404)

            if action == 'hold':
                obj.spider_holding_reason = remark
                obj.spider_hold_lot = True
                obj.spider_release_reason = ''
                obj.spider_release_lot = False
            elif action == 'unhold':
                obj.spider_release_reason = remark
                obj.spider_hold_lot = False
                obj.spider_release_lot = True

            obj.save(update_fields=['spider_holding_reason', 'spider_release_reason', 'spider_hold_lot', 'spider_release_lot'])
            return JsonResponse({'success': True, 'message': 'Reason saved.'})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        

@method_decorator(csrf_exempt, name='dispatch')
class Zone_SpiderSaveIPPickRemarkAPIView(APIView):

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('stock_lot_id')
            remark = data.get('remark', '').strip()
            if not lot_id:
                return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)
            obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if not obj:
                return JsonResponse({'success': False, 'error': 'LOT not found.'}, status=404)
            obj.spider_pick_remarks = remark
            obj.save(update_fields=['spider_pick_remarks'])
            return JsonResponse({'success': True, 'message': 'Remark saved'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class Zone_JIGUpdateBatchQuantityAPIView(APIView):
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
class Zone_JIGDeleteBatchAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            stock_lot_id = data.get('stock_lot_id')
            if not stock_lot_id:
                return JsonResponse({'success': False, 'error': 'Missing stock_lot_id'}, status=400)
            obj = JigUnloadAfterTable.objects.filter(lot_id=stock_lot_id).first()
            if not obj:
                return JsonResponse({'success': False, 'error': 'Stock lot not found'}, status=404)
            obj.delete()
            return JsonResponse({'success': True, 'message': 'Stock lot deleted'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


def generate_optimal_tray_distribution_by_capacity(required_qty, tray_capacity, lot_id, available_tray_ids=None):
    """
    Generate optimal tray distribution that respects physical tray constraints.
    Handles both partial and full capacity usage scenarios correctly.
    """
    trays_needed = []
    
    if required_qty <= 0 or tray_capacity <= 0:
        print(f"Invalid inputs: required_qty={required_qty}, tray_capacity={tray_capacity}")
        return trays_needed
    
    print(f"Generating optimal distribution for {required_qty} pieces using tray capacity {tray_capacity}")
    
    # Get available tray IDs from database if not provided
    if not available_tray_ids:
        try:
            actual_trays = Spider_TrayId.objects.filter(
                lot_id=lot_id,
                rejected_tray=False,
                delink_tray=False,
                tray_quantity__gt=0
            ).order_by('tray_id')
            available_tray_ids = [tray.tray_id for tray in actual_trays]
        except Exception as e:
            print(f"Error fetching tray IDs: {e}")
            available_tray_ids = []
    
    total_physical_trays = len(available_tray_ids)
    print(f"Total physical trays available: {total_physical_trays}")
    
    if total_physical_trays == 0:
        print("No physical trays available")
        return trays_needed
    
    # *** UPDATED: Better logic for determining half filled tray requirement ***
    try:
        jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_obj and jig_unload_obj.jig_physical_qty and jig_unload_obj.jig_physical_qty > 0:
            original_qty = jig_unload_obj.jig_physical_qty
            print(f"[DEBUG] original_qty from JigUnloadAfterTable.jig_physical_qty: {original_qty}")
        elif jig_unload_obj and jig_unload_obj.na_qc_accepted_qty and jig_unload_obj.na_qc_accepted_qty > 0:
            original_qty = jig_unload_obj.na_qc_accepted_qty
            print(f"[DEBUG] original_qty from JigUnloadAfterTable.na_qc_accepted_qty: {original_qty}")
        else:
            rejection_obj = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            if rejection_obj and rejection_obj.total_rejection_quantity is not None:
                original_qty = rejection_obj.total_rejection_quantity
                print(f"[DEBUG] original_qty from Nickel_Audit_Rejection_ReasonStore.total_rejection_quantity: {original_qty}")
            else:
                original_qty = 0
                print(f"[DEBUG] original_qty fallback to 0 (no record found)")
        # *** KEY FIX: Check if jig will consume ENTIRE available quantity ***
        remaining_after_jig = original_qty - required_qty
        will_have_half_filled = remaining_after_jig > 0
        
        print(f"Original available quantity: {original_qty}")
        print(f"Required for this jig: {required_qty}")
        print(f"Remaining after jig: {remaining_after_jig}")
        
        # *** NEW: If jig uses entire quantity, no half filled tray needed ***
        if required_qty >= original_qty:
            will_have_half_filled = False
            print("*** JIG USES ENTIRE QUANTITY - No half filled tray needed ***")
        
    except Exception as e:
        print(f"Error checking half filled requirement: {e}")
        will_have_half_filled = False
        original_qty = 0
    
    # Calculate theoretical optimal distribution
    complete_trays = required_qty // tray_capacity
    remainder = required_qty % tray_capacity
    
    print(f"Theoretical calculation: {required_qty} ÷ {tray_capacity} = {complete_trays} complete + {remainder} remainder")
    
    # Calculate maximum delink trays we can use
    max_delink_trays = total_physical_trays - (1 if will_have_half_filled else 0)
    max_delink_trays = max(0, max_delink_trays)
    
    print(f"Will have half filled tray: {will_have_half_filled}")
    print(f"Maximum delink trays we can use: {max_delink_trays}")
    
    # *** UPDATED: Handle both full capacity and partial capacity scenarios ***
    if not will_have_half_filled:
        # *** SCENARIO 1: JIG USES ENTIRE QUANTITY - Use actual tray quantities ***
        print("*** FULL CAPACITY MODE: Using actual tray quantities ***")
        
        # Get actual tray quantities instead of using theoretical tray capacity
        try:
            actual_trays = Spider_TrayId.objects.filter(
                lot_id=lot_id,
                rejected_tray=False,
                delink_tray=False,
                tray_quantity__gt=0
            ).order_by('tray_id')
            
            remaining_qty = required_qty
            tray_index = 0
            
            for tray in actual_trays:
                if remaining_qty <= 0:
                    break
                    
                actual_tray_qty = min(tray.tray_quantity, remaining_qty)
                
                trays_needed.append({
                    'tray_id': tray.tray_id,
                    'tray_quantity': actual_tray_qty,
                    'used_quantity': actual_tray_qty,
                    'original_tray_quantity': tray.tray_quantity,
                    'lot_id': lot_id,
                    'is_complete': actual_tray_qty == tray.tray_quantity,
                    'is_top_tray': actual_tray_qty < tray.tray_quantity,
                    'theoretical': False,  # Using actual tray data
                    'rejected_tray': False,
                    'delink_tray': False,
                })
                
                remaining_qty -= actual_tray_qty
                print(f"✓ Actual tray {tray_index + 1}: {tray.tray_id} using {actual_tray_qty}/{tray.tray_quantity} pieces")
                tray_index += 1
                
        except Exception as e:
            print(f"Error using actual tray quantities, falling back to theoretical: {e}")
            # Fallback to theoretical distribution
            will_have_half_filled = True
    
    if will_have_half_filled or len(trays_needed) == 0:
        # *** SCENARIO 2: PARTIAL CAPACITY - Use theoretical optimal distribution ***
        print("*** PARTIAL CAPACITY MODE: Using theoretical optimal distribution ***")
        
        # Clear any previous attempts
        trays_needed = []
        
        # Adjust distribution if theoretical exceeds physical constraints
        if complete_trays > max_delink_trays:
            print(f"*** CONSTRAINT APPLIED: Reducing {complete_trays} complete trays to {max_delink_trays}")
            actual_complete_trays = max_delink_trays
        else:
            actual_complete_trays = complete_trays
        
        # Build delink tray list (only complete trays, no partial)
        tray_index = 0
        
        for i in range(actual_complete_trays):
            if tray_index < len(available_tray_ids):
                tray_id = available_tray_ids[tray_index]
            else:
                tray_id = f"TRAY-{tray_index+1:03d}"
            
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
            
            print(f"✓ Complete tray {i+1}: {tray_id} using {tray_capacity}/{tray_capacity} pieces")
            tray_index += 1
    
    total_distributed = sum(tray['used_quantity'] for tray in trays_needed)
    print(f"Final delink distribution: {len(trays_needed)} trays totaling {total_distributed} pieces")
    print(f"Remaining for half filled: {required_qty - total_distributed} pieces")
    
    return trays_needed

def calculate_half_filled_trays_by_capacity(stock_lot_id, display_qty, jig_capacity, tray_capacity):
    """
    Calculate half filled trays with proper full capacity detection.
    Only shows half filled tray when there's actually remaining quantity.
    COMPLETELY FIXED: Correct calculation of remaining quantity and top tray portion.
    """
    half_filled_trays = []
    try:
        jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=stock_lot_id).first()
        if jig_unload_obj and jig_unload_obj.jig_physical_qty and jig_unload_obj.jig_physical_qty > 0:
            original_qty = jig_unload_obj.jig_physical_qty
            print(f"[DEBUG] original_qty from JigUnloadAfterTable.jig_physical_qty: {original_qty}")
        elif jig_unload_obj and jig_unload_obj.na_qc_accepted_qty and jig_unload_obj.na_qc_accepted_qty > 0:
            original_qty = jig_unload_obj.na_qc_accepted_qty
            print(f"[DEBUG] original_qty from JigUnloadAfterTable.na_qc_accepted_qty: {original_qty}")
        else:
            rejection_obj = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=stock_lot_id).first()
            if rejection_obj and rejection_obj.total_rejection_quantity is not None:
                original_qty = rejection_obj.total_rejection_quantity
                print(f"[DEBUG] original_qty from Nickel_Audit_Rejection_ReasonStore.total_rejection_quantity: {original_qty}")
            else:
                original_qty = 0
                print(f"[DEBUG] original_qty fallback to 0 (no record found)")

        print(f"HALF FILLED CALCULATION (COMPLETELY FIXED):")
        print(f"  Original qty: {original_qty}")
        print(f"  Display qty (this jig): {display_qty}")
        print(f"  Tray capacity: {tray_capacity}")

        # Check if jig uses entire quantity
        if display_qty >= original_qty:
            print("  *** JIG USES ENTIRE QUANTITY - No half filled tray needed ***")
            return half_filled_trays
        
        # COMPLETELY FIXED: Calculate remaining quantity directly
        # NEW (correct)
        delink_trays = generate_optimal_tray_distribution_by_capacity(
            display_qty, tray_capacity, stock_lot_id
        )
        actual_delink_qty = sum(tray['used_quantity'] for tray in delink_trays)
        remaining_qty_after_jig = original_qty - actual_delink_qty        
        print(f"  DIRECT CALCULATION: Remaining = {original_qty} - {display_qty} = {remaining_qty_after_jig}")

        if remaining_qty_after_jig <= 0:
            print("  No remaining quantity, no half filled trays needed")
            return half_filled_trays

        # Calculate optimal distribution for remaining quantity
        complete_trays = remaining_qty_after_jig // tray_capacity
        remainder = remaining_qty_after_jig % tray_capacity
        
        print(f"  Distribution: {remaining_qty_after_jig} ÷ {tray_capacity} = {complete_trays} complete + {remainder} remainder")

        # ONLY show the top tray (remainder) for verification
        if remainder > 0:
            half_filled_trays.append({
                'tray_id': f"TOP-TRAY",
                'tray_quantity': remainder,  # Only the remainder
                'original_tray_quantity': tray_capacity,
                'is_top_tray': True,
                'lot_id': stock_lot_id,
                'theoretical': True
            })
            print(f"  ✓ TOP TRAY: {remainder} pieces (remainder only)")
        elif complete_trays > 0:
            # If only complete trays remain, show one for verification
            half_filled_trays.append({
                'tray_id': f"COMPLETE-TRAY",
                'tray_quantity': tray_capacity,
                'original_tray_quantity': tray_capacity,
                'is_top_tray': False,
                'lot_id': stock_lot_id,
                'theoretical': True
            })
            print(f"  ✓ COMPLETE TRAY: {tray_capacity} pieces")
        
        print(f"  Result: {len(half_filled_trays)} half filled tray entries")

    except Exception as e:
        print(f"Error calculating half filled trays: {str(e)}")
    
    return half_filled_trays

def generate_multi_model_optimal_distribution(lot_quantities_dict, tray_capacity_dict):
    """
    Generate optimal tray distribution for multiple models/lots.
    Respects physical constraints and maintains consistency with single model logic.
    
    Args:
        lot_quantities_dict: {lot_id: required_quantity}
        tray_capacity_dict: {lot_id: tray_capacity}
    
    Returns:
        {
            'delink_trays': [...],
            'half_filled_trays': [...],
            'total_delink_qty': int,
            'lot_distributions': {lot_id: {...}}
        }
    """
    result = {
        'delink_trays': [],
        'half_filled_trays': [],
        'total_delink_qty': 0,
        'lot_distributions': {}
    }
    
    try:
        print(f"=== MULTI-MODEL OPTIMAL DISTRIBUTION ===")
        print(f"Lot quantities: {lot_quantities_dict}")
        print(f"Tray capacities: {tray_capacity_dict}")
        
        # Process each lot individually first to respect physical constraints
        for lot_id, required_qty in lot_quantities_dict.items():
            if required_qty <= 0:
                continue
                
            tray_capacity = tray_capacity_dict.get(lot_id, 12)  # Default to 12
            
            print(f"\nProcessing lot {lot_id}: {required_qty} pieces, tray capacity {tray_capacity}")
            
            # Get optimal distribution for this lot using existing function
            lot_delink_trays = generate_optimal_tray_distribution_by_capacity(
                required_qty, 
                tray_capacity, 
                lot_id
            )
            
            # Calculate half-filled trays for this lot
            lot_half_filled = calculate_half_filled_trays_by_capacity(
                lot_id, 
                required_qty, 
                0,  # jig_capacity not needed for this calculation
                tray_capacity
            )
            
            # Store lot-specific distribution info
            lot_delink_qty = sum(tray['used_quantity'] for tray in lot_delink_trays)
            result['lot_distributions'][lot_id] = {
                'required_qty': required_qty,
                'delink_qty': lot_delink_qty,
                'delink_trays': lot_delink_trays,
                'half_filled_trays': lot_half_filled,
                'tray_capacity': tray_capacity
            }
            
            # Add to combined results
            result['delink_trays'].extend(lot_delink_trays)
            result['half_filled_trays'].extend(lot_half_filled)
            result['total_delink_qty'] += lot_delink_qty
            
            print(f"  Lot {lot_id} delink: {lot_delink_qty} pieces in {len(lot_delink_trays)} trays")
            print(f"  Lot {lot_id} half-filled: {len(lot_half_filled)} trays")
        
        print(f"\nCombined results:")
        print(f"  Total delink trays: {len(result['delink_trays'])}")
        print(f"  Total delink quantity: {result['total_delink_qty']}")
        print(f"  Total half-filled trays: {len(result['half_filled_trays'])}")
        
        return result
        
    except Exception as e:
        print(f"Error in multi-model distribution: {str(e)}")
        return result

@api_view(['POST'])
def Zone_get_multi_model_distribution(request):
    """
    API endpoint for multi-model optimal tray distribution.
    """
    try:
        data = request.data
        lot_quantities = data.get('lot_quantities', {})
        
        if not lot_quantities:
            return Response({'error': 'lot_quantities is required'}, status=400)
        
        # Get tray capacities for each lot - Check JigUnloadAfterTable first
        tray_capacities = {}
        for lot_id in lot_quantities.keys():
            try:
                # First check JigUnloadAfterTable
                jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
                if jig_unload_obj and jig_unload_obj.tray_capacity:
                    tray_capacity = jig_unload_obj.tray_capacity
                else:
                    # Fallback to TotalStockModel
                    tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                    if tsm and tsm.batch_id:
                        tray_capacity = tsm.batch_id.tray_capacity or 12
                    else:
                        tray_capacity = 12  # Default
                tray_capacities[lot_id] = tray_capacity
            except:
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
        print(f"Error in Zone_get_multi_model_distribution: {str(e)}")
        return Response({'error': str(e)}, status=500)

def calculate_multi_model_half_filled_optimal(lot_quantities_dict):
    """
    Calculate half-filled trays for multiple models using optimal distribution.
    Only shows trays that actually have remaining quantity after jig processing.
    COMPLETELY FIXED: Uses ACTUAL delink quantity used, not requested jig quantity.
    """
    combined_half_filled = []
    
    try:
        print(f"=== MULTI-MODEL HALF-FILLED CALCULATION (COMPLETELY FIXED) ===")
        
        for lot_id, jig_qty in lot_quantities_dict.items():
            if jig_qty <= 0:
                continue
                
            print(f"\nProcessing half-filled for lot {lot_id} with jig qty {jig_qty}")
            
            # Check JigUnloadAfterTable first, then fallback to TotalStockModel
            jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if jig_unload_obj:
                if jig_unload_obj.na_physical_qty and jig_unload_obj.na_physical_qty > 0:
                    original_qty = jig_unload_obj.na_physical_qty
                else:
                    original_qty = jig_unload_obj.na_qc_accepted_qty or 0
                tray_capacity = jig_unload_obj.tray_capacity or 12
                model_no = f"LOT-{lot_id}"  # JigUnloadAfterTable doesn't have direct model
            else:
                # Fallback to TotalStockModel
                tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                if tsm:
                    if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                        original_qty = tsm.jig_physical_qty
                    else:
                        original_qty = tsm.brass_audit_accepted_qty or 0
                        
                    tray_capacity = tsm.batch_id.tray_capacity if tsm.batch_id else 12
                    model_no = tsm.batch_id.model_stock_no.model_no if tsm.batch_id and tsm.batch_id.model_stock_no else f"LOT-{lot_id}"
                else:
                    print(f"  No data found for lot {lot_id}")
                    continue
            
            print(f"  Original qty: {original_qty}, Jig qty: {jig_qty}, Tray capacity: {tray_capacity}")
            
            # FIXED: Get actual delink distribution to see what was ACTUALLY used
            delink_trays = generate_optimal_tray_distribution_by_capacity(
                jig_qty, 
                tray_capacity, 
                lot_id
            )
            
            # Calculate actual quantity used in delink trays (may be less than jig_qty)
            actual_delink_qty = sum(tray['used_quantity'] for tray in delink_trays)
            
            # FIXED: Calculate remaining based on ACTUAL delink usage
            remaining_after_jig = original_qty - actual_delink_qty
            
            print(f"  ACTUAL DELINK QTY USED: {actual_delink_qty}")
            print(f"  CORRECTED CALCULATION: Remaining = {original_qty} - {actual_delink_qty} = {remaining_after_jig}")
            
            if remaining_after_jig <= 0:
                print(f"  No remaining quantity for lot {lot_id} - skipping")
                continue
            
            # Calculate optimal distribution for remaining quantity
            remaining_complete_trays = remaining_after_jig // tray_capacity
            remaining_partial = remaining_after_jig % tray_capacity
            
            print(f"  Distribution: {remaining_after_jig} ÷ {tray_capacity} = {remaining_complete_trays} complete + {remaining_partial} remainder")
            
            # ONLY ADD TOP TRAY (PARTIAL) FOR VERIFICATION - DON'T ADD COMPLETE TRAYS
            # Complete trays are handled automatically, only partial tray needs verification
            if remaining_partial > 0:
                combined_half_filled.append({
                    'tray_id': f"{model_no}-TOP-TRAY",
                    'tray_quantity': remaining_partial,  # FIXED: Only the remainder portion
                    'original_tray_quantity': tray_capacity,
                    'is_top_tray': True,
                    'lot_id': lot_id,
                    'model_no': model_no,
                    'theoretical': True,
                    'remaining_type': 'partial'
                })
                print(f"  ✓ TOP TRAY: {remaining_partial} pieces (remainder only)")
            elif remaining_complete_trays > 0:
                # If only complete trays remain, show one complete tray for verification
                combined_half_filled.append({
                    'tray_id': f"{model_no}-COMPLETE-TRAY",
                    'tray_quantity': tray_capacity,  # Show full tray capacity
                    'original_tray_quantity': tray_capacity,
                    'is_top_tray': False,
                    'lot_id': lot_id,
                    'model_no': model_no,
                    'theoretical': True,
                    'remaining_type': 'complete'
                })
                print(f"  ✓ COMPLETE TRAY: {tray_capacity} pieces")
        
        print(f"\nResult: {len(combined_half_filled)} combined half-filled trays (FIXED - based on actual delink usage)")
        
        # Sort by model and tray type (complete first, then partial)
        combined_half_filled.sort(key=lambda x: (x['model_no'], x['is_top_tray']))
        
        return combined_half_filled
        
    except Exception as e:
        print(f"Error calculating multi-model half-filled trays: {str(e)}")
        return []

@api_view(['GET'])
def Zone_fetch_jig_related_data(request):
    stock_lot_id = request.GET.get('stock_lot_id')
    if not stock_lot_id:
        print("No stock_lot_id provided")
        return Response({'error': 'stock_lot_id is required'}, status=400)

    try:
        # Check JigUnloadAfterTable first, then fallback to TotalStockModel
        jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=stock_lot_id).first()
        
        if jig_unload_obj:
            # Get model_no from plating_stk_no (first 4 digits)
            model_no = None
            jig_master = None
            model_master = None  # For image fetching
            
            if jig_unload_obj.plating_stk_no:
                # Extract first 4 digits from plating_stk_no as model_no
                plating_stk_no = str(jig_unload_obj.plating_stk_no)
                if len(plating_stk_no) >= 4:
                    model_no = plating_stk_no[:4]
                    print(f"📋 Extracted model_no: {model_no} from plating_stk_no: {plating_stk_no}")
                    
                    # *** ADD MODEL IMAGE FETCHING LOGIC HERE ***
                    # Find ModelMaster for images (same logic as main view)
                    try:
                        model_master = ModelMaster.objects.filter(
                            model_no__startswith=model_no
                        ).prefetch_related('images').first()
                        
                        if model_master:
                            print(f"✅ Found ModelMaster for images: {model_master.model_no}")
                        else:
                            print(f"⚠️ No ModelMaster found for model_no: {model_no}")
                    except Exception as e:
                        print(f"❌ Error fetching ModelMaster: {e}")
                        model_master = None
                    
                    # Get JigLoadingMaster data using the extracted model_no (first 4 digits)
                    print(f"🔍 Querying JigLoadingMaster for model_no starting with: '{model_no}'")
                    
                    # Since model_stock_no is a ForeignKey, we need to query through the relationship
                    try:
                        # Try different possible field structures
                        jig_master = None
                        
                        # Option 1: model_stock_no__model_no__startswith
                        try:
                            jig_master = JigLoadingMaster.objects.filter(
                                model_stock_no__model_no__startswith=model_no
                            ).first()
                            if jig_master:
                                print(f"✅ Found with model_stock_no__model_no__startswith")
                        except Exception as e1:
                            print(f"🔍 Option 1 failed: {e1}")
                        
                        # Option 2: model_stock_no__startswith (if the related model has __str__ method)
                        if not jig_master:
                            try:
                                # This might work if the related model's __str__ method returns the model number
                                jig_master = JigLoadingMaster.objects.select_related('model_stock_no').filter(
                                    model_stock_no__isnull=False
                                )
                                # Filter in Python since we can't use startswith on FK directly
                                for jm in jig_master:
                                    if hasattr(jm.model_stock_no, 'model_no'):
                                        if str(jm.model_stock_no.model_no).startswith(model_no):
                                            jig_master = jm
                                            print(f"✅ Found with Python filtering on model_stock_no.model_no")
                                            break
                                    elif str(jm.model_stock_no).startswith(model_no):
                                        jig_master = jm
                                        print(f"✅ Found with Python filtering on model_stock_no.__str__")
                                        break
                                else:
                                    jig_master = None
                            except Exception as e2:
                                print(f"🔍 Option 2 failed: {e2}")
                                jig_master = None
                        
                        # Option 3: Check what fields are available in the related model
                        if not jig_master:
                            print(f"🔍 DEBUG: Investigating JigLoadingMaster structure...")
                            sample_jlm = JigLoadingMaster.objects.select_related('model_stock_no').first()
                            if sample_jlm and sample_jlm.model_stock_no:
                                related_obj = sample_jlm.model_stock_no
                                print(f"📋 Related model type: {type(related_obj)}")
                                print(f"📋 Related object str: '{related_obj}'")
                                
                                # Check available fields
                                if hasattr(related_obj, '_meta'):
                                    fields = [f.name for f in related_obj._meta.fields]
                                    print(f"📋 Available fields in related model: {fields}")
                                
                                # Check specific common field names
                                possible_fields = ['model_no', 'model_number', 'code', 'name', 'stock_no']
                                for field_name in possible_fields:
                                    if hasattr(related_obj, field_name):
                                        field_value = getattr(related_obj, field_name)
                                        print(f"📋 {field_name}: '{field_value}'")
                                        
                                        # Try to match this field
                                        if str(field_value).startswith(model_no):
                                            print(f"🎯 Field '{field_name}' matches! Trying query...")
                                            try:
                                                query_dict = {f'model_stock_no__{field_name}__startswith': model_no}
                                                jig_master = JigLoadingMaster.objects.filter(**query_dict).first()
                                                if jig_master:
                                                    print(f"✅ Found with model_stock_no__{field_name}__startswith")
                                                    break
                                            except Exception as e3:
                                                print(f"❌ Query failed for {field_name}: {e3}")
                        
                        if jig_master:
                            model_stock_display = str(jig_master.model_stock_no)
                            print(f"✅ Found JigLoadingMaster: model_stock_no='{model_stock_display}', jig_type={getattr(jig_master, 'jig_type', 'N/A')}, jig_capacity={getattr(jig_master, 'jig_capacity', 0)}")
                        else:
                            print(f"❌ No JigLoadingMaster found for model_no: '{model_no}' after trying all options")
                            
                    except Exception as e:
                        print(f"❌ Error querying JigLoadingMaster: {e}")
                        jig_master = None
                else:
                    print(f"⚠️ plating_stk_no too short: {plating_stk_no}")
                    model_no = f"SHORT_{plating_stk_no}"
            else:
                print(f"⚠️ No plating_stk_no found for lot_id: {stock_lot_id}")
                model_no = f"NO_PLATING_{stock_lot_id[-4:]}"

            # *** ENHANCED IMAGE COLLECTION LOGIC ***
            images = []
            
            # Priority 1: Get images from ModelMaster (same as main view)
            if model_master:
                print(f"🎯 Getting images from ModelMaster: {model_master.model_no}")
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
                        print(f"📸 Added image from ModelMaster: {img.master_image.url}")
            
            # Use JigUnloadAfterTable data
            tray_capacity = jig_unload_obj.tray_capacity or 12
            
            # Priority 2: Try to get additional model info from combined lots if available (for images and other data)
            mmc = None
            if jig_unload_obj.combine_lot_ids:
                first_lot_id = jig_unload_obj.combine_lot_ids[0]
                tsm = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
                if tsm and tsm.batch_id:
                    mmc = tsm.batch_id
                    if mmc.model_stock_no and not images:  # Only get images if ModelMaster didn't provide any
                        print("🔄 No ModelMaster images, trying TotalStockModel fallback")
                        # Get images from TotalStockModel batch_id
                        for img in mmc.model_stock_no.images.all():
                            if img.master_image:
                                images.append(img.master_image.url)
                                print(f"📸 Added image from TotalStockModel: {img.master_image.url}")
            
            # Priority 3: Use placeholder if no images found
            if not images:
                print("📷 No images found, using placeholder")
                images = [static('assets/images/imagePlaceholder.jpg')]
            
            print(f"📸 Final images list: {len(images)} images - {images}")
        
        else:
            print(f"⚠️ No JigUnloadAfterTable found for lot_id: {stock_lot_id}")
            return Response({'error': 'No JigUnloadAfterTable data found for this lot_id'}, status=404)

        # Get jig capacity from JigLoadingMaster
        jig_capacity = getattr(jig_master, 'jig_capacity', 0) if jig_master else 0
        jig_type = getattr(jig_master, 'jig_type', None) if jig_master else None

        # Calculate remaining quantity
        def calculate_remaining_quantity_enhanced(lot_id):
            try:
                # Check JigUnloadAfterTable first
                jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
                if jig_unload_obj:
                    if jig_unload_obj.jig_physical_qty and jig_unload_obj.jig_physical_qty > 0:
                        original_qty = jig_unload_obj.jig_physical_qty
                    else:
                        original_qty = jig_unload_obj.na_qc_accepted_qty or 0
                else:
                    # Fallback to TotalStockModel
                    tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                    if tsm:
                        if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                            original_qty = tsm.jig_physical_qty
                        else:
                            original_qty = tsm.brass_audit_accepted_qty or 0
                    else:
                        original_qty = 0

                if original_qty <= 0:
                    return 0

                # Check SpiderJigDetails instead of JigDetails
                jig_details = SpiderJigDetails.objects.filter(
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

        remaining_qty = calculate_remaining_quantity_enhanced(stock_lot_id)

        # FIXED: Always cap to jig capacity, even for jig_physical_qty
        if jig_unload_obj and jig_unload_obj.jig_physical_qty and jig_unload_obj.jig_physical_qty > 0:
            # Use jig_physical_qty but cap it to jig_capacity
            uncapped_qty = jig_unload_obj.jig_physical_qty
            display_qty = min(uncapped_qty, jig_capacity) if jig_capacity > 0 else uncapped_qty
            
            # Log if we're capping the quantity
            if jig_capacity > 0 and uncapped_qty > jig_capacity:
                print(f"⚠️ CAPPING LOT QTY: {uncapped_qty} -> {display_qty} (Jig Capacity: {jig_capacity})")
        else:
            # Original logic with capping
            display_qty = min(remaining_qty, jig_capacity) if jig_capacity and remaining_qty > 0 else remaining_qty

        print(f"✅ Final display_qty: {display_qty}, jig_capacity: {jig_capacity}, remaining_qty: {remaining_qty}")
                
        # Get available tray IDs for reference - Use Spider_TrayId instead of JigLoadTrayId
        actual_trays_queryset = Spider_TrayId.objects.filter(
            lot_id=stock_lot_id,
            rejected_tray=False,
            delink_tray=False,
            tray_quantity__gt=0
        ).order_by('tray_id')
        
        available_tray_ids = [tray.tray_id for tray in actual_trays_queryset]

        # Use optimal distribution based on TRAY CAPACITY
        if display_qty > 0:
            current_trays_data = generate_optimal_tray_distribution_by_capacity(
                display_qty, 
                tray_capacity, 
                stock_lot_id, 
                available_tray_ids
            )
        else:
            current_trays_data = []
        
        # Calculate half filled trays using TRAY CAPACITY
        half_filled_trays = calculate_half_filled_trays_by_capacity(
            stock_lot_id, 
            display_qty, 
            jig_capacity, 
            tray_capacity
        )

        # Get original tray records for reference
        original_trays = TrayId.objects.filter(lot_id=stock_lot_id)
        original_trays_data = [
            {
                'tray_id': tray.tray_id,
                'tray_quantity': tray.tray_quantity,
                'lot_id': tray.lot_id
            }
            for tray in original_trays
        ]

        # Check for showing half filled table
        if jig_unload_obj:
            # For JigUnloadAfterTable, compare with na_qc_accepted_qty
            original_qty_for_comparison = jig_unload_obj.na_qc_accepted_qty or 0
        else:
            original_qty_for_comparison = 0
            
        show_half_filled_table = (
            len(half_filled_trays) > 0 and 
            display_qty < original_qty_for_comparison
        )

        # Handle draft data - Use SpiderJigDetails instead of JigDetails
        draft_data = {'has_draft': False}
        try:
            draft_jig = SpiderJigDetails.objects.filter(
                lot_id=stock_lot_id, 
                draft_save=True
            ).order_by('-id').first()
            
            if draft_jig:
                # *** FIXED: Use saved draft half_filled_tray_data instead of calculated half_filled_trays ***
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
                        'from_draft': True  # Indicator that this is from draft
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
                    'half_filled_tray_data': formatted_draft_half_filled,  # ✅ FIXED: Use saved draft data
                    'trays': current_trays_data,
                }
                
                # Override calculated half_filled_trays with draft data for consistency
                if formatted_draft_half_filled:
                    half_filled_trays = formatted_draft_half_filled
                    print(f"✅ Using draft half_filled_tray_data instead of calculated data")
                
        except Exception as e:
            print(f"Error getting draft data: {str(e)}")

        print("==== OPTIMAL TRAY DISTRIBUTION SUMMARY ====")
        print(f"Required qty: {display_qty}")
        print(f"Tray capacity: {tray_capacity}")
        print(f"Model No: {model_no}")
        print(f"Jig Type: {jig_type}")
        print(f"Jig Capacity: {jig_capacity}")
        print(f"Images: {len(images)} found - {images}")

        return Response({
            'model_no': model_no,
            'model_images': images,  # ✅ Enhanced with proper ModelMaster integration
            'ep_bath_type': mmc.ep_bath_type if mmc else None,
            'jig_capacity': jig_capacity,
            'jig_type': jig_type,
            'tray_capacity': tray_capacity,
            'trays': current_trays_data,
            'original_trays': original_trays_data,
            'plating_color': mmc.plating_color if mmc else None,
            'polish_finish': mmc.polish_finish if mmc else None,
            'version': mmc.version.version_name if mmc and mmc.version else None,
            'remaining_quantity': remaining_qty,
            'display_qty': display_qty,
            'original_quantity': original_qty_for_comparison,
            'edited_quantity': display_qty,
            'is_fully_processed': remaining_qty <= 0,
            'can_add_more_jigs': remaining_qty > 0,
            'draft_data': draft_data,
            'tray_distribution_method': 'optimal_by_physical_constraints',
            'half_filled_trays': half_filled_trays,
            'show_half_filled_table': show_half_filled_table,
            'jig_fully_utilized': display_qty >= original_qty_for_comparison,
            'plating_stk_no': jig_unload_obj.plating_stk_no if jig_unload_obj else None,
        })

    except Exception as e:
        print(f"Error in Zone_fetch_jig_related_data: {str(e)}")
        return Response({'error': f'Internal server error: {str(e)}'}, status=500)
     
@method_decorator(csrf_exempt, name='dispatch')
class Zone_SpiderJigDetailsSaveAPIView(APIView):
    """
    API endpoint for saving SpiderJigDetails from the right side modal
    """
    def post(self, request):
        import traceback
        import json
        try:
            # Parse request data
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            half_filled_tray_data = data.get('half_filled_tray_data', [])

            # Validation: If half-filled tray section is shown but no tray_id entered, block save
            if half_filled_tray_data:
                missing_tray_ids = [entry for entry in half_filled_tray_data if not entry.get('tray_id')]
                if missing_tray_ids:
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
            model_numbers = data.get('model_numbers', [])  # List of model numbers
            lot_ids = data.get('lot_ids', [])  # List of lot IDs
            lot_id_quantities = data.get('lot_id_quantities', {})  # Dict: {lot_id: quantity}
            
            # Extract delink tray data
            delink_tray_data = data.get('delink_tray_data', [])  # List of delink tray entries
            tray_ids = [entry.get('tray_id', '').strip() for entry in delink_tray_data if entry.get('tray_id', '').strip()]
            duplicates = set([tid for tid in tray_ids if tray_ids.count(tid) > 1])
            if duplicates:
                return JsonResponse({
                    'success': False,
                    'error': f'Duplicate Tray ID(s) not allowed: {", ".join(duplicates)}'
                }, status=400)

            # *** NEW: RECALCULATE lot_id_quantities AND total_cases_loaded BASED ON DELINK_TRAY_DATA ***
            if delink_tray_data:
                print(f"🔄 Recalculating quantities based on delink_tray_data: {delink_tray_data}")
                
                # Calculate actual lot_id_quantities by summing expected_usage for each lot_id
                recalculated_lot_id_quantities = {}
                recalculated_total_cases_loaded = 0
                
                for delink_entry in delink_tray_data:
                    lot_id = delink_entry.get('lot_id', '').strip()
                    expected_usage = int(delink_entry.get('expected_usage', 0))
                    
                    if lot_id and expected_usage > 0:
                        if lot_id not in recalculated_lot_id_quantities:
                            recalculated_lot_id_quantities[lot_id] = 0
                        recalculated_lot_id_quantities[lot_id] += expected_usage
                        recalculated_total_cases_loaded += expected_usage
                
                print(f"📊 Original lot_id_quantities: {lot_id_quantities}")
                print(f"📊 Original total_cases_loaded: {total_cases_loaded}")
                print(f"✅ Recalculated lot_id_quantities: {recalculated_lot_id_quantities}")
                print(f"✅ Recalculated total_cases_loaded: {recalculated_total_cases_loaded}")
                
                # Update the variables with recalculated values
                lot_id_quantities = recalculated_lot_id_quantities
                total_cases_loaded = recalculated_total_cases_loaded
                
                # Also update lot_ids to only include lots that have actual quantities
                lot_ids = list(recalculated_lot_id_quantities.keys())
                
                print(f"🔄 Updated lot_ids: {lot_ids}")
            else:
                print(f"⚠️ No delink_tray_data found, using original quantities")
            
            # *** NEW: Extract half filled tray data ***
            half_filled_tray_data = data.get('half_filled_tray_data', [])  # List of half filled tray entries
            print(f"Received half_filled_tray_data: {half_filled_tray_data}")
            
            # *** NEW: Validate half filled tray data for duplicates ***
            half_tray_ids = [entry.get('tray_id', '').strip() for entry in half_filled_tray_data if entry.get('tray_id', '').strip()]
            half_duplicates = set([tid for tid in half_tray_ids if half_tray_ids.count(tid) > 1])
            if half_duplicates:
                return JsonResponse({
                    'success': False,
                    'error': f'Duplicate Half Filled Tray ID(s) not allowed: {", ".join(half_duplicates)}'
                }, status=400)
            
            # *** NEW: Check for overlap between delink and half filled tray IDs ***
            overlap_tray_ids = set(tray_ids) & set(half_tray_ids)
            if overlap_tray_ids:
                return JsonResponse({
                    'success': False,
                    'error': f'Tray ID(s) cannot be in both De-link and Half Filled sections: {", ".join(overlap_tray_ids)}'
                }, status=400)
                
            # Primary lot ID (first one or original)
            primary_lot_id = data.get('primary_lot_id', '')
            if not primary_lot_id and lot_ids:
                primary_lot_id = lot_ids[0]
            
            # --- FILTER OUT FULLY PROCESSED LOTS ---
            filtered_lot_ids = []
            filtered_lot_id_quantities = {}
            filtered_model_numbers = []
            for idx, lot_id in enumerate(list(lot_ids)):
                # Check JigUnloadAfterTable first, then TotalStockModel
                jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
                if jig_unload_obj:
                    if jig_unload_obj.jig_physical_qty and jig_unload_obj.jig_physical_qty > 0:
                        original_qty = jig_unload_obj.jig_physical_qty
                    else:
                        original_qty = jig_unload_obj.na_qc_accepted_qty or 0
                else:
                    tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                    if not tsm:
                        continue
                    # Calculate original qty
                    if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                        original_qty = tsm.jig_physical_qty
                    else:
                        original_qty = tsm.brass_audit_accepted_qty or 0
                        
                # Calculate used qty using SpiderJigDetails
                from django.db.models import Q
                jig_details = SpiderJigDetails.objects.filter(
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
                # --- CHANGE: For drafts, do NOT filter out fully processed lots ---
                if is_draft:
                    filtered_lot_ids.append(lot_id)
                    if lot_id in lot_id_quantities:
                        filtered_lot_id_quantities[lot_id] = lot_id_quantities[lot_id]
                    if idx < len(model_numbers):
                        filtered_model_numbers.append(model_numbers[idx])
                else:
                    if remaining_qty > 0:
                        filtered_lot_ids.append(lot_id)
                        if lot_id in lot_id_quantities:
                            filtered_lot_id_quantities[lot_id] = lot_id_quantities[lot_id]
                        if idx < len(model_numbers):
                            filtered_model_numbers.append(model_numbers[idx])
            lot_ids = filtered_lot_ids
            lot_id_quantities = filtered_lot_id_quantities
            model_numbers = filtered_model_numbers
            # Also update primary_lot_id if needed
            if lot_ids and (primary_lot_id not in lot_ids):
                primary_lot_id = lot_ids[0] if lot_ids else ''
            # --- END FILTER ---

            # Validation (relaxed for drafts)
            if not primary_lot_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'At least one lot ID is required'
                }, status=400)
            
            # For drafts, allow empty JIG QR ID
            if not is_draft and not jig_qr_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Jig QR ID is required'
                }, status=400)

            # --- MODIFIED: Always check for draft_id and update that instance ---
            draft_id = data.get('draft_id')
            jig_detail = None
            if draft_id:
                try:
                    jig_detail = SpiderJigDetails.objects.get(id=draft_id, draft_save=True)
                except SpiderJigDetails.DoesNotExist:
                    jig_detail = None

            # Empty slots validation (only for non-drafts)
            if not is_draft:
                if empty_slots > 10:
                    return JsonResponse({
                        'success': False,
                        'error': 'Too Many Empty Slots. Empty slots cannot be more than 10. Please check your input.'
                    }, status=400)
                if faulty_slots > 10:
                    return JsonResponse({
                        'success': False,
                        'error': 'Too Many Faulty Slots. Faulty slots cannot be more than 10. Please check your input.'
                    }, status=400)

            # --- Enhanced Jig cycle validation logic (only for non-drafts) ---
            if not is_draft:
                # Get last SpiderJigDetails for this jig_qr_id
                last_jig = SpiderJigDetails.objects.filter(
                    jig_qr_id=jig_qr_id, 
                    draft_save=False
                ).order_by('-id').first()
                
                if last_jig:
                    last_no_of_cycle = last_jig.no_of_cycle if last_jig.no_of_cycle else 1
                    new_no_of_cycle = last_no_of_cycle + 1
                else:
                    new_no_of_cycle = 1  # Start from 1

                # Validation rules
                max_cycles = 35
                normal_limit = 30
                
                # If after increment, cycle is more than 35, don't save
                if new_no_of_cycle > max_cycles:
                    return JsonResponse({
                        'success': False,
                        'error': f'Maximum {max_cycles} cycles completed for this JIG. Cannot save further. Please use a different JIG.'
                    }, status=400)

                # If cycle is between 31 and 35 (inclusive), save but show alert
                alert_msg = None
                if normal_limit < new_no_of_cycle <= max_cycles:
                    alert_msg = f'JIG has completed {new_no_of_cycle} cycles. Maximum recommended is {normal_limit}. Please check if JIG needs maintenance.'
            else:
                # For drafts, use cycle 1 or existing draft cycle
                if jig_detail and jig_detail.no_of_cycle:
                    new_no_of_cycle = jig_detail.no_of_cycle
                else:
                    new_no_of_cycle = 1
                alert_msg = None

            # Fetch related data from the primary lot
            try:
                # Check JigUnloadAfterTable first
                jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=primary_lot_id).first()
                if jig_unload_obj:
                    # Get model data from combine_lot_ids if available
                    if jig_unload_obj.combine_lot_ids:
                        first_lot_id = jig_unload_obj.combine_lot_ids[0]
                        primary_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
                        if primary_stock:
                            mmc = primary_stock.batch_id
                            jig_master = JigLoadingMaster.objects.filter(
                                model_stock_no=primary_stock.model_stock_no
                            ).first()
                        else:
                            mmc = None
                            jig_master = None
                    else:
                        mmc = None
                        jig_master = None
                        
                    # Set default values for JigUnloadAfterTable
                    if not mmc:
                        # Create dummy objects for JigUnloadAfterTable data
                        class DummyMaster:
                            jig_type = 'Standard'
                            jig_capacity = 36  # Default capacity
                            
                        class DummyMMC:
                            ep_bath_type = 'Standard'
                            plating_color = jig_unload_obj.plating_color.plating_color if jig_unload_obj.plating_color else 'Default'
                            
                        jig_master = DummyMaster()
                        mmc = DummyMMC()
                else:
                    # Fallback to TotalStockModel
                    primary_stock = TotalStockModel.objects.filter(lot_id=primary_lot_id).first()
                    if not primary_stock:
                        return JsonResponse({
                            'success': False, 
                            'error': f'Stock data not found for lot ID: {primary_lot_id}'
                        }, status=404)
                    
                    # Get ModelMasterCreation data
                    mmc = primary_stock.batch_id
                    if not mmc:
                        return JsonResponse({
                            'success': False, 
                            'error': f'Model master data not found for lot ID: {primary_lot_id}'
                        }, status=404)
                    
                    # Get JigLoadingMaster data
                    jig_master = JigLoadingMaster.objects.filter(
                        model_stock_no=primary_stock.model_stock_no
                    ).first()
                    
                    if not jig_master:
                        return JsonResponse({
                            'success': False, 
                            'error': f'Jig loading master data not found for model: {primary_stock.model_stock_no}'
                        }, status=404)
                        
            except Exception as e:
                return JsonResponse({
                    'success': False, 
                    'error': f'Error fetching related data: {str(e)}'
                }, status=500)
            
            # Calculate total original quantity
            total_original_qty = sum(int(qty) for qty in lot_id_quantities.values())
            
            # For drafts, use simpler quantity logic
            if is_draft:
                actual_lot_id_quantities = {k: int(v) for k, v in lot_id_quantities.items()}
            else:
                # Use existing complex quantity calculation for non-drafts
                actual_lot_id_quantities = {}
                if total_original_qty > 0 and total_cases_loaded > 0:
                    # If total_cases_loaded is less than total_original_qty, use first-fill approach
                    if total_cases_loaded < total_original_qty:
                        remaining_to_distribute = total_cases_loaded
                        
                        # Sort lot_ids to ensure consistent order (use original/primary lot first)
                        sorted_lot_ids = sorted(lot_id_quantities.keys())
                        if primary_lot_id in sorted_lot_ids:
                            # Move primary lot to front
                            sorted_lot_ids.remove(primary_lot_id)
                            sorted_lot_ids.insert(0, primary_lot_id)
                        
                        for lot_id in sorted_lot_ids:
                            original_qty = int(lot_id_quantities[lot_id])
                            
                            # Use first-fill approach: fill current lot completely before moving to next
                            if remaining_to_distribute > 0:
                                # Take minimum of what's available in this lot or what we still need
                                used_qty = min(original_qty, remaining_to_distribute)
                                
                                if used_qty > 0:
                                    actual_lot_id_quantities[lot_id] = used_qty
                                    remaining_to_distribute -= used_qty
                            
                            if remaining_to_distribute <= 0:
                                break
                        
                        # Handle special case: if we have faulty slots, we need to reduce from the lots
                        if faulty_slots > 0 and empty_slots == 0:
                            reduction_needed = faulty_slots
                            
                            # Reduce from the last lot first (LIFO approach)
                            for lot_id in reversed(sorted_lot_ids):
                                if lot_id in actual_lot_id_quantities and reduction_needed > 0:
                                    current_qty = actual_lot_id_quantities[lot_id]
                                    reduction = min(current_qty, reduction_needed)
                                    
                                    actual_lot_id_quantities[lot_id] -= reduction
                                    reduction_needed -= reduction
                                    
                                    # Remove lot if quantity becomes 0
                                    if actual_lot_id_quantities[lot_id] <= 0:
                                        del actual_lot_id_quantities[lot_id]
                                    
                                    if reduction_needed <= 0:
                                        break
                    else:
                        # If total_cases_loaded >= total_original_qty, use original quantities
                        actual_lot_id_quantities = {k: int(v) for k, v in lot_id_quantities.items()}
                else:
                    # Fallback to original quantities
                    actual_lot_id_quantities = {k: int(v) for k, v in lot_id_quantities.items()}
            
            # Calculate jig_cases_remaining_count
            jig_cases_remaining_count = max(0, jig_master.jig_capacity - total_cases_loaded - faulty_slots)
            
            # Prepare SpiderJigDetails data
            jig_details_data = {
                'jig_qr_id': jig_qr_id,
                'faulty_slots': faulty_slots,
                'jig_type': jig_master.jig_type or '',
                'jig_capacity': jig_master.jig_capacity or 0,
                'ep_bath_type': mmc.ep_bath_type or '',
                'plating_color': mmc.plating_color or '',
                'jig_loaded_date_time': timezone.now(),
                'empty_slots': empty_slots,
                'total_cases_loaded': total_cases_loaded,
                'jig_cases_remaining_count': jig_cases_remaining_count,
                'no_of_model_cases': model_numbers,  # ArrayField
                'no_of_cycle': new_no_of_cycle,
                'lot_id': primary_lot_id,
                'new_lot_ids': lot_ids,  # ArrayField
                'electroplating_only': False,  # Default value
                'lot_id_quantities': actual_lot_id_quantities,  # JSONField - Use calculated quantities
                'bath_tub': '',  # Can be filled later if needed
                'draft_save': is_draft,  # Set draft flag
                'delink_tray_data': delink_tray_data,
                'half_filled_tray_data': half_filled_tray_data,
                'forging': '',  # Default value for SpiderJigDetails
            }
            
            # --- MODIFIED: Update draft or create new ---
            if jig_detail:
                # Update existing draft (convert to final if not draft)
                for field, value in jig_details_data.items():
                    setattr(jig_detail, field, value)
                jig_detail.draft_save = is_draft  # Set draft_save flag accordingly
                jig_detail.save()
            else:
                # Create new record
                jig_detail = SpiderJigDetails.objects.create(**jig_details_data)
                
            # --- ENHANCED DELINK TRAY DATA PROCESSING (only for non-drafts) ---
            delink_success_count = 0
            if not is_draft and delink_tray_data:
                print(f"🔧 Processing {len(delink_tray_data)} delink tray entries")
                
                for delink_entry in delink_tray_data:
                    tray_id = delink_entry.get('tray_id', '').strip()
                    lot_id = delink_entry.get('lot_id', '').strip()
                    # Use expected_usage (from backend) as tray_quantity
                    tray_quantity = int(delink_entry.get('expected_usage', 0))
                    
                    print(f"🔴 Processing delink tray: {tray_id}, lot_id: {lot_id}, quantity: {tray_quantity}")
                
                    # Update Spider_TrayId instead of JigLoadTrayId
                    Spider_TrayId.objects.filter(
                        tray_id=tray_id,
                        lot_id=lot_id
                    ).update(
                        delink_tray=True,
                        tray_quantity=tray_quantity
                    )

                    if tray_id:
                        try:
                            # Update main TrayId table
                            tray_obj = TrayId.objects.filter(tray_id=tray_id).first()
                            if tray_obj:
                                tray_obj.delink_tray = True
                                tray_obj.lot_id = None
                                tray_obj.tray_quantity = 0
                                tray_obj.batch_id = None
                                tray_obj.IP_tray_verified = False
                                tray_obj.top_tray = False
                                tray_obj.delink_tray_qty = tray_obj.tray_quantity
                                tray_obj.save(update_fields=[
                                    'delink_tray', 'delink_tray_qty', 'lot_id', 'tray_quantity',
                                    'batch_id', 'IP_tray_verified', 'top_tray'
                                ])
                                delink_success_count += 1

                            # Get batch_ids for this lot_id (could be multiple if lot spans batches)
                            # First check JigUnloadAfterTable
                            jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
                            if jig_unload_obj and jig_unload_obj.combine_lot_ids:
                                # Get batch_ids from the combined lots
                                batch_ids = []
                                for combined_lot_id in jig_unload_obj.combine_lot_ids:
                                    tsm_batch_ids = list(TotalStockModel.objects.filter(
                                        lot_id=combined_lot_id
                                    ).values_list('batch_id_id', flat=True).distinct())
                                    batch_ids.extend(tsm_batch_ids)
                                batch_ids = list(set(batch_ids))  # Remove duplicates
                            else:
                                # Fallback to TotalStockModel
                                batch_ids = list(TotalStockModel.objects.filter(
                                    lot_id=lot_id
                                ).values_list('batch_id_id', flat=True).distinct())
                            
                            # Also get batch_id from delink_entry if provided
                            entry_batch_id = delink_entry.get('batch_id')
                            if entry_batch_id and entry_batch_id not in batch_ids:
                                batch_ids.append(entry_batch_id)

                            # Update tray records in all related tables (include Spider_TrayId)
                            for Model in [Spider_TrayId]:
                                try:
                                    # Strategy 1: Update by tray_id + lot_id (exact match)
                                    updated_count_1 = Model.objects.filter(
                                        tray_id=tray_id, 
                                        lot_id=lot_id
                                    ).update(delink_tray=True)
                                    
                                    # Strategy 2: Update by tray_id + batch_id for same batch different lots
                                    updated_count_2 = 0
                                    for batch_id in batch_ids:
                                        if batch_id:
                                            count = Model.objects.filter(
                                                tray_id=tray_id, 
                                                batch_id=batch_id
                                            ).update(delink_tray=True)
                                            updated_count_2 += count
                                    
                                    print(f"Model {Model.__name__}: Updated {updated_count_1} records by lot_id, {updated_count_2} records by batch_id for tray {tray_id}")
                                    
                                except Exception as model_error:
                                    print(f"Error updating {Model.__name__} for tray {tray_id}: {str(model_error)}")
                
                        except Exception as e:
                            print(f"Error processing tray {tray_id}: {str(e)}")

            # *** NEW: HALF FILLED TRAY DATA PROCESSING (only for non-drafts) ***
            half_filled_success_count = 0
            if not is_draft and half_filled_tray_data:
                print(f"🔧 Processing {len(half_filled_tray_data)} half filled tray entries")
                
                for half_entry in half_filled_tray_data:
                    tray_id = half_entry.get('tray_id', '').strip()
                    tray_quantity = int(half_entry.get('tray_quantity', 0))
                    lot_id = half_entry.get('lot_id', '').strip()
                    is_top_tray = half_entry.get('is_top_tray', False)
                    
                    print(f"🟡 Processing half filled tray: {tray_id}, quantity: {tray_quantity}, lot_id: {lot_id}, is_top_tray: {is_top_tray}")
                    
                    if tray_id and tray_quantity > 0:
                        try:
                            # Get batch_ids for this lot_id
                            # First check JigUnloadAfterTable
                            jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
                            if jig_unload_obj and jig_unload_obj.combine_lot_ids:
                                batch_ids = []
                                for combined_lot_id in jig_unload_obj.combine_lot_ids:
                                    tsm_batch_ids = list(TotalStockModel.objects.filter(
                                        lot_id=combined_lot_id
                                    ).values_list('batch_id_id', flat=True).distinct())
                                    batch_ids.extend(tsm_batch_ids)
                                batch_ids = list(set(batch_ids))
                            else:
                                batch_ids = list(TotalStockModel.objects.filter(
                                    lot_id=lot_id
                                ).values_list('batch_id_id', flat=True).distinct())
                            
                            print(f"🔍 Found batch_ids for lot {lot_id}: {batch_ids}")
                            
                            # Prepare update fields for Spider_TrayId
                            update_fields = {
                                'tray_quantity': tray_quantity,
                                'top_tray': is_top_tray,
                            }
                            
                            print(f"📝 Update fields for {tray_id}: {update_fields}")
                            
                            # Strategy 1: Update by tray_id + lot_id (exact match)
                            print(f"🎯 Strategy 1: Trying to update by tray_id={tray_id} + lot_id={lot_id}")
                            updated_count_1 = Spider_TrayId.objects.filter(
                                tray_id=tray_id,
                                lot_id=lot_id
                            ).update(**update_fields)
                            
                            print(f"✅ Strategy 1 result: {updated_count_1} records updated")
                            
                            # Strategy 2: Update by tray_id + batch_id if no exact match
                            updated_count_2 = 0
                            if updated_count_1 == 0:
                                print(f"🎯 Strategy 2: No exact match found, trying batch_id matches...")
                                for batch_id in batch_ids:
                                    if batch_id:
                                        print(f"   Trying tray_id={tray_id} + batch_id={batch_id}")
                                        count = Spider_TrayId.objects.filter(
                                            tray_id=tray_id,
                                            batch_id=batch_id
                                        ).update(**update_fields)
                                        updated_count_2 += count
                                        print(f"   Updated {count} records for batch_id={batch_id}")
                            
                            total_updated = updated_count_1 + updated_count_2
                            print(f"📊 Total updated: {total_updated} records for tray {tray_id}")
                            
                            if total_updated > 0:
                                print(f"✅ Successfully updated tray {tray_id}: {total_updated} records updated in Spider_TrayId")
                                half_filled_success_count += 1
                                
                                # *** ALSO UPDATE MAIN TRAY TABLE IF NEEDED ***
                                print(f"🔧 Updating main TrayId table for {tray_id}")
                                try:
                                    main_tray_obj = TrayId.objects.filter(tray_id=tray_id).first()
                                    if main_tray_obj:
                                        if is_top_tray:
                                            main_tray_obj.top_tray = True
                                            main_tray_obj.tray_quantity = tray_quantity
                                            main_tray_obj.save(update_fields=['top_tray', 'tray_quantity'])
                                            print(f"✅ Updated main TrayId table for {tray_id}")
                                    else:
                                        print(f"⚠️ No record found in main TrayId table for {tray_id}")
                                except Exception as main_tray_error:
                                    print(f"⚠️ Error updating main TrayId table for {tray_id}: {str(main_tray_error)}")
                                
                            else:
                                print(f"❌ No matching records found for tray {tray_id} in Spider_TrayId")
                                
                                # Debug: Let's check what records exist for this tray
                                existing_records = Spider_TrayId.objects.filter(tray_id=tray_id)
                                print(f"🔍 Existing records for tray_id {tray_id}:")
                                if existing_records.exists():
                                    for record in existing_records:
                                        print(f"   - ID: {record.id}, lot_id: {record.lot_id}, batch_id: {record.batch_id}, qty: {record.tray_quantity}, top_tray: {record.top_tray}")
                                else:
                                    print(f"   - No records found for tray_id {tray_id} in Spider_TrayId table")
                                    
                                    # If no record exists, create one
                                    print(f"🆕 Creating new Spider_TrayId record for {tray_id}")
                                    if batch_ids:
                                        first_batch_id = batch_ids[0]
                                        try:
                                            from django.contrib.auth.models import User
                                            new_record = Spider_TrayId.objects.create(
                                                tray_id=tray_id,
                                                lot_id=lot_id,
                                                tray_quantity=tray_quantity,
                                                top_tray=is_top_tray,
                                                batch_id_id=first_batch_id,
                                                user=User.objects.first()  # Get first available user or set to None
                                            )
                                            print(f"✅ Created new Spider_TrayId record: {new_record}")
                                            half_filled_success_count += 1
                                        except Exception as create_error:
                                            print(f"❌ Error creating new record: {str(create_error)}")
                                    else:
                                        print(f"❌ Cannot create record - no batch_ids found for lot {lot_id}")
                        
                        except Exception as e:
                            print(f"❌ Error processing half filled tray {tray_id}: {str(e)}")
                            import traceback
                            print(f"🔍 Traceback: {traceback.format_exc()}")
                    else:
                        print(f"⚠️ Skipping invalid half filled tray entry: tray_id='{tray_id}', quantity={tray_quantity}")

            print(f"📈 Delink tray processing complete: {delink_success_count} trays processed")
            print(f"📈 Half filled tray processing complete: {half_filled_success_count} trays updated/created")

            # *** NOW UPDATE REMAINING QTY AFTER DELINK AND HALF FILLED PROCESSING ***
            # Update process modules for all involved lot_ids if not a draft
            if not is_draft:
                for lot_id in lot_ids:
                    print(f"\n🔍 PROCESSING LOT_ID: {lot_id}")
                    print(f"="*50)
                    
                    # Check JigUnloadAfterTable first
                    jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
                    if jig_unload_obj:
                        # Update JigUnloadAfterTable
                        try:
                            from django.db.models import Sum
                            
                            # Get original quantity for reference
                            if jig_unload_obj.jig_physical_qty and jig_unload_obj.jig_physical_qty > 0:
                                original_qty = jig_unload_obj.jig_physical_qty
                            else:
                                original_qty = jig_unload_obj.na_qc_accepted_qty or 0
                            print(f"📋 Original Quantity: {original_qty}")
                            
                            # Read from Spider_TrayId where we just updated delink_tray status
                            load_trays = Spider_TrayId.objects.filter(lot_id=lot_id)
                            print(f"🔍 Found {load_trays.count()} records in Spider_TrayId for lot {lot_id}")
                            
                            delink_trays_sum = 0
                            half_filled_sum = 0
                            remaining_qty = 0
                            
                            # Show all Spider_TrayId records for debugging
                            print(f"\n🔍 ALL Spider_TrayId RECORDS FOR LOT {lot_id}:")
                            if load_trays.exists():
                                for record in load_trays:
                                    tray_id = record.tray_id
                                    tray_qty = record.tray_quantity or 0
                                    is_top_tray = getattr(record, 'top_tray', False)
                                    is_delink = getattr(record, 'delink_tray', False)
                                    
                                    print(f"   Tray: {tray_id}, Qty: {tray_qty}, Top_Tray: {is_top_tray}, Is_Delink: {is_delink}")
                                    
                                    # Categorize the tray
                                    if is_delink:
                                        delink_trays_sum += tray_qty
                                        print(f"     -> Added to DELINK sum: {tray_qty}")
                                    else:
                                        remaining_qty += tray_qty
                                        if is_top_tray:
                                            half_filled_sum += tray_qty
                                            print(f"     -> Added to HALF FILLED sum: {tray_qty}")
                                        print(f"     -> Added to REMAINING sum: {tray_qty}")
                            else:
                                print(f"   ❌ NO RECORDS FOUND in Spider_TrayId for lot {lot_id}")
                                # If no Spider_TrayId records, fallback to original quantity
                                remaining_qty = original_qty
                            
                            print(f"\n🔴 DELINK TRAYS SUM: {delink_trays_sum}")
                            print(f"🟡 HALF FILLED TRAYS SUM (top_tray=True, not delinked): {half_filled_sum}")
                            print(f"🟢 REMAINING QTY (not delinked): {remaining_qty}")
                            
                            # Update JigUnloadAfterTable jig_physical_qty
                            jig_unload_obj.jig_physical_qty = remaining_qty
                            jig_unload_obj.save(update_fields=['jig_physical_qty'])
                            
                            print(f"✅ UPDATED JigUnloadAfterTable for lot {lot_id}:")
                            print(f"   jig_physical_qty = {remaining_qty}")
                            
                        except Exception as calc_error:
                            print(f"❌ ERROR calculating remaining_qty for lot {lot_id}: {str(calc_error)}")
                            import traceback
                            print(f"🔍 TRACEBACK: {traceback.format_exc()}")
                    else:
                        # Fallback to TotalStockModel
                        tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                        if tsm:
                            # *** MODIFIED: Calculate remaining_qty from Spider_TrayId table ***
                            try:
                                from django.db.models import Sum
                                
                                # Get original quantity for reference
                                if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                                    original_qty = tsm.jig_physical_qty
                                else:
                                    original_qty = tsm.brass_audit_accepted_qty or 0
                                print(f"📋 Original Quantity: {original_qty}")
                                
                                # Read from Spider_TrayId where we just updated delink_tray status
                                load_trays = Spider_TrayId.objects.filter(lot_id=lot_id)
                                print(f"🔍 Found {load_trays.count()} records in Spider_TrayId for lot {lot_id}")
                                
                                delink_trays_sum = 0
                                half_filled_sum = 0
                                remaining_qty = 0
                                
                                # Show all Spider_TrayId records for debugging
                                print(f"\n🔍 ALL Spider_TrayId RECORDS FOR LOT {lot_id}:")
                                if load_trays.exists():
                                    for record in load_trays:
                                        tray_id = record.tray_id
                                        tray_qty = record.tray_quantity or 0
                                        is_top_tray = getattr(record, 'top_tray', False)
                                        is_delink = getattr(record, 'delink_tray', False)
                                        
                                        print(f"   Tray: {tray_id}, Qty: {tray_qty}, Top_Tray: {is_top_tray}, Is_Delink: {is_delink}")
                                        
                                        # Categorize the tray
                                        if is_delink:
                                            delink_trays_sum += tray_qty
                                            print(f"     -> Added to DELINK sum: {tray_qty}")
                                        else:
                                            remaining_qty += tray_qty
                                            if is_top_tray:
                                                half_filled_sum += tray_qty
                                                print(f"     -> Added to HALF FILLED sum: {tray_qty}")
                                            print(f"     -> Added to REMAINING sum: {tray_qty}")
                                else:
                                    print(f"   ❌ NO RECORDS FOUND in Spider_TrayId for lot {lot_id}")
                                    # If no Spider_TrayId records, fallback to original quantity
                                    remaining_qty = original_qty
                                
                                print(f"\n🔴 DELINK TRAYS SUM: {delink_trays_sum}")
                                print(f"🟡 HALF FILLED TRAYS SUM (top_tray=True, not delinked): {half_filled_sum}")
                                print(f"🟢 REMAINING QTY (not delinked): {remaining_qty}")
                                
                                # Detailed breakdown
                                print(f"\n📊 DETAILED BREAKDOWN FOR LOT {lot_id}:")
                                print(f"   Original Qty:      {original_qty}")
                                print(f"   Delink Trays:     -{delink_trays_sum}")
                                print(f"   Half Filled:       {half_filled_sum} (included in remaining)")
                                print(f"   Final Remaining:   {remaining_qty}")
                                print(f"   Calculation Check: {original_qty} - {delink_trays_sum} = {original_qty - delink_trays_sum}")
                                
                            except Exception as calc_error:
                                print(f"❌ ERROR calculating remaining_qty for lot {lot_id}: {str(calc_error)}")
                                import traceback
                                print(f"🔍 TRACEBACK: {traceback.format_exc()}")
                                
                                # Fallback to original calculation
                                print(f"🔄 USING FALLBACK CALCULATION...")
                                if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                                    original_qty = tsm.jig_physical_qty
                                else:
                                    original_qty = tsm.brass_audit_accepted_qty or 0
                                
                                from django.db.models import Q
                                jig_details = SpiderJigDetails.objects.filter(
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
                                delink_trays_sum = 0  # Set to 0 for fallback
                                half_filled_sum = 0   # Set to 0 for fallback
                                print(f"📊 FALLBACK - Remaining qty: {remaining_qty}")

                            # Update jig_physical_qty and set edited flag
                            tsm.jig_physical_qty = remaining_qty
                            tsm.jig_physical_qty_edited = True
                            tsm.last_process_module = "Jig Loading"
                            tsm.next_process_module = "Jig Unloading"
                            tsm.save(update_fields=[
                                'jig_physical_qty', 'jig_physical_qty_edited',
                                'last_process_module', 'next_process_module'
                            ])
                            
                            print(f"✅ UPDATED TotalStockModel for lot {lot_id}:")
                            print(f"   jig_physical_qty = {remaining_qty}")
                            print(f"   last_process_module = Jig Loading")
                            print(f"   next_process_module = Jig Unloading")
                            print(f"="*50)
                            
                        else:
                            print(f"❌ No data found for lot {lot_id}")
                            print(f"="*50)
                        
            # Prepare response
            response_data = {
                'success': True,
                'message': f'{"Draft" if is_draft else "Spider Jig details"} saved successfully with QR ID: {jig_qr_id}',
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
                    'actual_lot_id_quantities': actual_lot_id_quantities,
                    'draft_save': jig_detail.draft_save
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
            # Log the error for debugging
            print(f"Error in Zone_SpiderJigDetailsSaveAPIView: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            
            return JsonResponse({
                'success': False, 
                'error': f'An unexpected error occurred: {str(e)}'
            }, status=500)


@api_view(['POST'])
def Zone_validate_spider_tray_id(request):
    data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
    tray_id = data.get('tray_id', '').strip()
    lot_id = data.get('lot_id', '').strip()  # Get lot_id for comparison

    tray_obj = Spider_TrayId.objects.filter(
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
class Zone_SpiderJigDetailsUpdateAPIView(APIView):
    """
    API endpoint for updating existing SpiderJigDetails
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
            
            # Find the SpiderJigDetails record
            if jig_id:
                jig_detail = SpiderJigDetails.objects.filter(id=jig_id).first()
            else:
                jig_detail = SpiderJigDetails.objects.filter(jig_qr_id=jig_qr_id).first()
            
            if not jig_detail:
                return JsonResponse({
                    'success': False, 
                    'error': 'Spider Jig details not found'
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
                'message': f'Spider Jig details updated successfully for QR ID: {jig_detail.jig_qr_id}',
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
            print(f"Error in Zone_SpiderJigDetailsUpdateAPIView: {str(e)}")
            return JsonResponse({
                'success': False, 
                'error': f'Update failed: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class Zone_SpiderJigDetailsValidateQRAPIView(APIView):
    """
    API endpoint for validating JIG QR ID before saving
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

            # Remove the check for existing QR ID
            return JsonResponse({
                'success': True,
                'exists': False,
                'message': f'Jig QR ID "{jig_qr_id}" is available'
            })
                
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'error': f'Validation failed: {str(e)}'
            }, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class Zone_SpiderJigCycleCountAPIView(APIView):
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

            # Get the last completed (non-draft) SpiderJigDetails for this jig_qr_id
            last_jig = SpiderJigDetails.objects.filter(
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
            print(f"Error in Zone_SpiderJigCycleCountAPIView: {str(e)}")
            return JsonResponse({
                'success': False, 
                'error': f'Failed to get cycle count: {str(e)}'
            }, status=500)
            

@method_decorator(csrf_exempt, name='dispatch')
class Zone_JIGTrayValidate_Complete_APIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            tray_id = str(data.get('tray_id')).strip()
            
            # ✅ Use same parameter handling as Zone_JIGTrayIdList_Complete_APIView
            stock_lot_id = data.get('stock_lot_id')
            lot_id = data.get('lot_id') or stock_lot_id

            print(f"🔧 [Zone_JIGTrayValidate_Complete_APIView] Received:")
            print(f"   tray_id: {tray_id}")
            print(f"   stock_lot_id: {stock_lot_id}")
            print(f"   lot_id: {lot_id}")

            if not lot_id:
                return JsonResponse({'success': False, 'error': 'Missing lot_id or stock_lot_id'}, status=400)

            # ✅ SIMPLIFIED: Use only Spider_TrayId table with lot_id filtering (same as Zone_JIGTrayIdList_Complete_APIView)
            queryset = Spider_TrayId.objects.filter(
                lot_id=lot_id,
                tray_quantity__gt=0
            ).exclude(
                delink_tray=True
            )
            
            print(f"✅ [JIGTrayValidate] Using lot_id filter: {lot_id}")
            print(f"✅ [JIGTrayValidate] Total available trays: {queryset.count()}")
            print(f"✅ [JIGTrayValidate] Sample tray_ids: {[t.tray_id for t in queryset[:5]]}...")  # Show first 5

            # ✅ Check if tray exists
            exists = queryset.filter(tray_id=tray_id).exists()
            print(f"🔍 [JIGTrayValidate] Tray ID '{tray_id}' exists in Spider_TrayId? {exists}")

            # ✅ Get tray info if it exists
            tray_info = {}
            if exists:
                tray = queryset.filter(tray_id=tray_id).first()
                if tray:
                    tray_info = {
                        'tray_quantity': tray.tray_quantity,
                        'top_tray': getattr(tray, 'top_tray', False),
                        'rejected_tray': getattr(tray, 'rejected_tray', False),
                        'delink_tray': getattr(tray, 'delink_tray', False),
                        'lot_id': tray.lot_id,
                        'batch_id': tray.batch_id.batch_id if tray.batch_id else None,
                        'data_source': 'Spider_TrayId'
                    }

            return JsonResponse({
                'success': True, 
                'exists': exists,
                'tray_info': tray_info,
                'data_source': 'Spider_TrayId',
                'lot_match': True if exists else False  # Since we're filtering by lot_id, if exists then it matches lot
            })
            
        except Exception as e:
            print(f"❌ [Zone_JIGTrayValidate_Complete_APIView] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ✅ CORRECTED: AfterCheckPickTrayIdList_Complete_APIView - Use BrassTrayId and remove False filtering
@method_decorator(csrf_exempt, name='dispatch')
class Zone_JIGTrayIdList_Complete_APIView(APIView):
    def get(self, request):
        batch_id = request.GET.get('batch_id')
        stock_lot_id = request.GET.get('stock_lot_id')
        lot_id = request.GET.get('lot_id') or stock_lot_id

        if not batch_id:
            return JsonResponse({'success': False, 'error': 'Missing batch_id'}, status=400)
        if not lot_id:
            return JsonResponse({'success': False, 'error': 'Missing lot_id or stock_lot_id'}, status=400)

        # ✅ SIMPLIFIED: Use only Spider_TrayId table
        queryset = Spider_TrayId.objects.filter(
            lot_id=lot_id,
            tray_quantity__gt=0
        ).exclude(
            delink_tray=True
        ).order_by('id')

        # ✅ Find top tray
        top_tray = queryset.filter(top_tray=True).first()
        other_trays = queryset.exclude(pk=top_tray.pk if top_tray else None)

        data = []
        row_counter = 1

        def create_tray_data(tray_obj, is_top=False):
            nonlocal row_counter
            
            return {
                's_no': row_counter,
                'tray_id': tray_obj.tray_id,
                'tray_quantity': tray_obj.tray_quantity,
                'position': row_counter - 1,
                'is_top_tray': is_top,
                'rejected_tray': getattr(tray_obj, 'rejected_tray', False),
                'delink_tray': getattr(tray_obj, 'delink_tray', False),
                'top_tray': getattr(tray_obj, 'top_tray', False),
                'lot_id': tray_obj.lot_id
            }

        # Add top tray first if exists
        if top_tray:
            data.append(create_tray_data(top_tray, is_top=True))
            row_counter += 1
            
        # Add other trays
        for tray in other_trays:
            data.append(create_tray_data(tray, is_top=False))
            row_counter += 1

        print(f"✅ [Zone_JIGTrayIdList_Complete_APIView] Total Spider_TrayId records returned: {len(data)}")

        # ✅ SIMPLIFIED: Basic summary
        total_trays = queryset.count()
        rejected_trays = queryset.filter(rejected_tray=True)
        
        rejection_summary = {
            'total_trays': total_trays,
            'total_rejected_trays': rejected_trays.count(),
            'rejected_tray_ids': list(rejected_trays.values_list('tray_id', flat=True)),
            'data_source': 'Spider_TrayId'
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

class Zone_SpiderCompositionView(TemplateView):
    template_name = "Spider_Spindle/spider_Composition.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lot_ids_param = self.request.GET.get('lot_ids', '')
        lot_ids = lot_ids_param.split(',') if lot_ids_param else []
        print("==== Zone_SpiderCompositionView: Received lot_ids ====")
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
            print(f"🔍 Processing lot_id: {lot_id}")
            
            # Get model_no from JigUnloadAfterTable.plating_stk_no (first 4 digits)
            jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            model_no = None
            
            if jig_unload_obj:
                if jig_unload_obj.plating_stk_no:
                    # Extract first 4 digits from plating_stk_no as model_no
                    plating_stk_no = str(jig_unload_obj.plating_stk_no)
                    if len(plating_stk_no) >= 4:
                        model_no = plating_stk_no[:4]
                        print(f"📋 Extracted model_no: {model_no} from plating_stk_no: {plating_stk_no} for lot_id: {lot_id}")
                    else:
                        print(f"⚠️ plating_stk_no too short: {plating_stk_no} for lot_id: {lot_id}")
                        model_no = f"UNKNOWN_{lot_id[-4:]}"  # Use last 4 digits of lot_id
                else:
                    print(f"⚠️ No plating_stk_no found for lot_id: {lot_id}")
                    model_no = f"UNKNOWN_{lot_id[-4:]}"  # Use last 4 digits of lot_id
            else:
                print(f"⚠️ No JigUnloadAfterTable found for lot_id: {lot_id}")
                # Fallback: Try to get from TotalStockModel for backward compatibility
                tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                if tsm and tsm.batch_id and tsm.batch_id.model_stock_no:
                    model_no = tsm.batch_id.model_stock_no.model_no
                    print(f"🔄 Fallback: Got model_no {model_no} from TotalStockModel for lot_id: {lot_id}")
                else:
                    model_no = f"UNKNOWN_{lot_id[-4:]}"  # Use last 4 digits of lot_id
                    print(f"🚫 Using fallback model_no: {model_no} for lot_id: {lot_id}")

            if not model_no:
                model_no = f"UNKNOWN_{lot_id[-4:]}"

            # Get JigLoadingMaster data for jig_type and jig_capacity (optional, for reference)
            jig_master = None
            if model_no and not model_no.startswith("UNKNOWN_"):
                jig_master = JigLoadingMaster.objects.filter(model_stock_no=model_no).first()
                if jig_master:
                    print(f"✅ Found JigLoadingMaster for {model_no}: jig_type={jig_master.jig_type}, jig_capacity={jig_master.jig_capacity}")
                else:
                    print(f"⚠️ No JigLoadingMaster found for model_no: {model_no}")

            # Assign color dynamically
            if model_no not in model_color_map:
                model_color_map[model_no] = color_palette[color_index % len(color_palette)]
                color_index += 1
            color = model_color_map[model_no]

            # Get original_qty using the specified logic from JigUnloadAfterTable
            original_qty = 0
            if jig_unload_obj:
                if jig_unload_obj.jig_physical_qty and jig_unload_obj.jig_physical_qty > 0:
                    original_qty = jig_unload_obj.jig_physical_qty
                    print(f"[DEBUG] original_qty from JigUnloadAfterTable.jig_physical_qty: {original_qty}")
                elif jig_unload_obj.na_qc_accepted_qty and jig_unload_obj.na_qc_accepted_qty > 0:
                    original_qty = jig_unload_obj.na_qc_accepted_qty
                    print(f"[DEBUG] original_qty from JigUnloadAfterTable.na_qc_accepted_qty: {original_qty}")
                else:
                    rejection_obj = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
                    if rejection_obj and rejection_obj.total_rejection_quantity is not None:
                        original_qty = rejection_obj.total_rejection_quantity
                        print(f"[DEBUG] original_qty from Nickel_Audit_Rejection_ReasonStore.total_rejection_quantity: {original_qty}")
                    else:
                        original_qty = 0
                        print(f"[DEBUG] original_qty fallback to 0 (no record found)")
            else:
                # Fallback: Try to get quantity from TotalStockModel
                tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                if tsm:
                    if tsm.jig_physical_qty_edited and tsm.jig_physical_qty:
                        original_qty = tsm.jig_physical_qty
                        print(f"[DEBUG] Fallback: original_qty from TotalStockModel.jig_physical_qty: {original_qty}")
                    else:
                        original_qty = tsm.brass_audit_accepted_qty or 0
                        print(f"[DEBUG] Fallback: original_qty from TotalStockModel.brass_audit_accepted_qty: {original_qty}")
                else:
                    print(f"[DEBUG] No quantity data found for lot_id: {lot_id}")
                    original_qty = 10  # Default quantity for display purposes

            from django.db.models import Q
            jig_details = SpiderJigDetails.objects.filter(
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
            
            # Ensure we have at least 1 case for display purposes if original_qty > 0
            if case_qty <= 0 and original_qty > 0:
                case_qty = 1
                print(f"[DEBUG] Adjusted case_qty to 1 for display purposes")
            elif case_qty <= 0:
                case_qty = 1  # Default minimum for display
                print(f"[DEBUG] Using default case_qty of 1 for lot_id: {lot_id}")
                
            print(f"[DEBUG] Final case_qty: {case_qty} for lot_id: {lot_id}")

            model_list.append({
                "model_no": model_no,
                "case_qty": case_qty,
                "case_numbers": list(range(1, case_qty + 1)),
                "color": color,
                "jig_type": jig_master.jig_type if jig_master else None,  # Added jig_type
                "jig_capacity": jig_master.jig_capacity if jig_master else 0,  # Added jig_capacity
                "plating_stk_no": jig_unload_obj.plating_stk_no if jig_unload_obj else None,  # Added for reference
                            })
        
        print(f"📊 Generated {len(model_list)} models:")
        for i, model in enumerate(model_list):
            print(f"  {i+1}. {model['model_no']}: {model['case_qty']} cases")
        
        all_cases = []
        for model in model_list:
            for case in model["case_numbers"]:
                all_cases.append({
                    "model_no": model["model_no"],
                    "case_qty": model["case_qty"],
                    "case_number": case,
                    "color": model["color"],
                    "jig_type": model["jig_type"],  # Added jig_type
                    "jig_capacity": model["jig_capacity"],  # Added jig_capacity
                    "plating_stk_no": model["plating_stk_no"],  # Added for reference
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
                        "jig_type": item["jig_type"],  # Added jig_type
                        "jig_capacity": item["jig_capacity"],  # Added jig_capacity
                        "plating_stk_no": item["plating_stk_no"],  # Added for reference
                    })
                    seen.add(item["model_no"])
            cards.append({
                "models": models_in_card,
                "cases": chunk,
                "color": chunk[0]["color"] if chunk else "#01524a",
            })
        
        print(f"🎴 Generated {len(cards)} cards:")
        for i, card in enumerate(cards):
            print(f"  Card {i+1}: {len(card['models'])} models, {len(card['cases'])} cases")
        
        context["cards"] = cards
        return context 
    
    
class Zone_SpiderCompletedTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Spider_Spindle/Spider_Completed_Table.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False
        
        # Get all plating_color IDs where jig_unload_zone_2 is True
        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_2=True
        ).values_list('id', flat=True)
        
        # Get eligible lot_ids from JigUnloadAfterTable that match zone criteria
        eligible_lot_ids = JigUnloadAfterTable.objects.filter(
            plating_color_id__in=allowed_color_ids  # Only records for zone 1
        ).values_list('lot_id', flat=True)
        
        # Query SpiderJigDetails table with zone filtering
        queryset = SpiderJigDetails.objects.select_related(
            'bath_numbers'
        ).filter(
            total_cases_loaded__gt=0,  # Only show records with cases loaded
            unload_over=False,  # Only show records that haven't been unloaded yet
            lot_id__in=eligible_lot_ids,  # Only show records from zone 1
        ).order_by('-date_time')  # Order by date_time

        print(f"Found {queryset.count()} Spider completed records for zone 1")

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        # Create lookup for JigUnloadAfterTable data (for plating_stk_no, polishing_stk_no, polish_finish, version, location)
        # Filter this lookup to only include zone 1 records as well
        jig_unload_lookup = {}
        jig_unload_data = JigUnloadAfterTable.objects.select_related(
            'polish_finish', 'version', 'plating_color'
        ).prefetch_related('location').filter(
            plating_color_id__in=allowed_color_ids  # Only zone 1 records
        )
        
        for item in jig_unload_data:
            jig_unload_lookup[item.lot_id] = {
                'plating_stk_no': item.plating_stk_no or '',
                'polish_stk_no': item.polish_stk_no or '',
                'polish_finish': item.polish_finish.polish_finish if item.polish_finish else '',
                'version_internal': item.version.version_internal if item.version else '',
                'location_names': ', '.join([loc.location_name for loc in item.location.all()]),
                'plating_color': item.plating_color.plating_color if item.plating_color else '',
            }

        # Build master_data from SpiderJigDetails records
        master_data = []
        for spider_jig in page_obj.object_list:
            # Get JigUnloadAfterTable data for this lot_id
            jig_unload_info = jig_unload_lookup.get(spider_jig.lot_id, {})
            
            # Build data dict from SpiderJigDetails
            data = {
                'batch_id': spider_jig.jig_qr_id,  # Using jig_qr_id as batch identifier
                'date_time': spider_jig.date_time,
                'model_stock_no__model_no': 'Spider Jig',  # Generic model name
                'plating_color': jig_unload_info.get('plating_color', spider_jig.plating_color),  # Prefer from JigUnloadAfterTable
                'polish_finish': jig_unload_info.get('polish_finish', ''),  # From JigUnloadAfterTable
                'version__version_internal': jig_unload_info.get('version_internal', ''),  # From JigUnloadAfterTable
                'vendor_internal': '',  # Not available in SpiderJigDetails
                'location__location_name': jig_unload_info.get('location_names', spider_jig.bath_tub or ''),  # From JigUnloadAfterTable, fallback to bath_tub
                'no_of_trays': 1,  # Each jig is essentially one "tray"
                'tray_type': spider_jig.jig_type,
                'tray_capacity': spider_jig.jig_capacity,
                'Moved_to_D_Picker': False,  # Not applicable
                'Draft_Saved': spider_jig.draft_save,
                'plating_stk_no': jig_unload_info.get('plating_stk_no', ''),  # From JigUnloadAfterTable
                'polishing_stk_no': jig_unload_info.get('polish_stk_no', ''),  # From JigUnloadAfterTable
                'category': spider_jig.forging,
                'stock_lot_id': spider_jig.lot_id,
                
                # Process-related fields
                'last_process_module': spider_jig.last_process_module or 'Jig Loading',
                'next_process_module': 'Electroplating' if not spider_jig.electroplating_only else 'Jig Unload',
                'brass_audit_accepted_qty_verified': False,  # Not available
                'brass_audit_accepted_qty': spider_jig.total_cases_loaded,
                'brass_audit_missing_qty': 0,  # Not available
                'brass_audit_physical_qty': spider_jig.total_cases_loaded,
                'brass_audit_physical_qty_edited': False,  # Not available
                'jig_pick_remarks': spider_jig.pick_remarks or '',
                'brass_audit_accptance': True,  # Assume accepted if loaded
                'brass_audit_accepted_tray_scan_status': True,  # Assume scanned
                'brass_audit_rejection': False,  # Not available
                'brass_audit_few_cases_accptance': False,  # Not available
                'brass_audit_onhold_picking': False,  # Not available
                'jig_physical_qty': spider_jig.total_cases_loaded,
                'edited_quantity': spider_jig.total_cases_loaded,
                'brass_audit_last_process_date_time': spider_jig.jig_loaded_date_time or spider_jig.date_time,
                'brass_rejection_qty': 0,  # Not available
                
                # SpiderJigDetails specific fields
                'jig_qr_id': spider_jig.jig_qr_id,
                'faulty_slots': spider_jig.faulty_slots,
                'jig_type': spider_jig.jig_type,
                'jig_capacity': spider_jig.jig_capacity,
                'bath_tub': spider_jig.bath_tub,
                'empty_slots': spider_jig.empty_slots,
                'ep_bath_type': spider_jig.ep_bath_type,
                'total_cases_loaded': spider_jig.total_cases_loaded,
                'jig_cases_remaining_count': spider_jig.jig_cases_remaining_count,
                'forging': spider_jig.forging,
                'no_of_model_cases': spider_jig.no_of_model_cases,
                'no_of_cycle': spider_jig.no_of_cycle,
                'new_lot_ids': spider_jig.new_lot_ids,
                'electroplating_only': spider_jig.electroplating_only,
                'lot_id_quantities': spider_jig.lot_id_quantities,
                'delink_tray_data': spider_jig.delink_tray_data,
                'half_filled_tray_data': spider_jig.half_filled_tray_data,
                'bath_numbers': spider_jig.bath_numbers.bath_number if spider_jig.bath_numbers else '',
                'jig_position': spider_jig.jig_position,
                'remarks': spider_jig.remarks,
                'jig_unload_draft': spider_jig.jig_unload_draft,
                'combined_lot_ids': spider_jig.combined_lot_ids,
                'jig_loaded_date_time': spider_jig.jig_loaded_date_time,
                'IP_loaded_date_time': spider_jig.IP_loaded_date_time,
                'unload_over': spider_jig.unload_over,
                'Un_loaded_date_time': spider_jig.Un_loaded_date_time,
            }

            # Get JigLoadingMaster data using plating_stk_no logic (same as SpiderPickTableView)
            jlm = None
            model_master = None
            plating_stk_no = jig_unload_info.get('plating_stk_no', '')
            if plating_stk_no and len(plating_stk_no) >= 4:
                model_no_prefix = plating_stk_no[:4]
                # Find JigLoadingMaster where model_stock_no__model_no matches the prefix
                jlm = JigLoadingMaster.objects.filter(
                    model_stock_no__model_no__startswith=model_no_prefix
                ).first()
                
                # Find ModelMaster where model_no matches the prefix for images
                model_master = ModelMaster.objects.filter(
                    model_no__startswith=model_no_prefix
                ).prefetch_related('images').first()
            
            if jlm:
                # Override with JigLoadingMaster data
                data.update({
                    'jig_type': jlm.jig_type,
                    'jig_capacity': jlm.jig_capacity,
                    'tray_type': jlm.jig_type,  # Update tray_type as well
                    'tray_capacity': jlm.jig_capacity,  # Update tray_capacity as well
                })
            # If no JigLoadingMaster found, keep SpiderJigDetails values (already set above)

            # Set display quantity - use remaining count if available, otherwise total loaded
            if spider_jig.jig_cases_remaining_count is not None and spider_jig.jig_cases_remaining_count > 0:
                data['display_qty'] = spider_jig.jig_cases_remaining_count
            else:
                data['display_qty'] = spider_jig.total_cases_loaded

            print(f"jig_qr_id={spider_jig.jig_qr_id}, total_cases_loaded={spider_jig.total_cases_loaded}, remaining={spider_jig.jig_cases_remaining_count}, jlm_found={'Yes' if jlm else 'No'}, model_master_found={'Yes' if model_master else 'No'}")

            # Get model images from ModelMaster based on model_no prefix
            images = []
            if model_master:
                # Get images from ModelMaster
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            
            # Use placeholder if no images found
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            
            data['model_images'] = images
                    
            # Calculate no_of_trays based on the final jig_capacity (from JigLoadingMaster if available, else SpiderJigDetails)
            final_jig_capacity = data.get('jig_capacity', spider_jig.jig_capacity)
            if final_jig_capacity and final_jig_capacity > 0:
                data['no_of_trays'] = math.ceil(data['display_qty'] / final_jig_capacity)
            else:
                data['no_of_trays'] = 1  # Default to 1 jig
            
            master_data.append(data)

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'is_admin': is_admin,
        }
        return Response(context, template_name=self.template_name)  
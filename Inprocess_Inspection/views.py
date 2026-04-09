from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from modelmasterapp.models import *
from django.db.models import OuterRef, Subquery, Exists, F
import math
import json
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from django.views.generic import TemplateView
from django.core.paginator import Paginator
from django.templatetags.static import static
from Recovery_DP.models import *
from django.db.models import Value
from django.db.models.functions import Coalesce
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, timedelta
import pytz
from django.db.models import Q
from .models import InprocessInspectionTrayCapacity
from Jig_Loading.models import JigCompleted

# Inprocess Inspection View
class InprocessInspectionView(TemplateView):
    template_name = "Inprocess_Inspection/Inprocess_Inspection.html"

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

    def get_dynamic_tray_capacity(self, tray_type_name):
        """
        Get dynamic tray capacity for Inprocess Inspection
        Rules:
        - Jumbo: Use ModelMaster capacity (12)
        - Normal: Use custom capacity from InprocessInspectionTrayCapacity (20)
        - Others: Use ModelMaster capacity
        """
        print(f"🔍 Getting dynamic tray capacity for tray_type: {tray_type_name}")
        
        if not tray_type_name or tray_type_name == "No Tray Type":
            print("❌ No valid tray type provided")
            return 0
        
        try:
            # Get the TrayType object from ModelMaster
            tray_type_obj = TrayType.objects.get(tray_type=tray_type_name)
            original_capacity = tray_type_obj.tray_capacity
            
            print(f"   📦 Original capacity from ModelMaster: {original_capacity}")
            
            # Check if there's a custom capacity for this tray type in Inprocess Inspection
            try:
                custom_capacity = InprocessInspectionTrayCapacity.objects.get(
                    tray_type=tray_type_obj,
                    is_active=True
                )
                print(f"   ✅ Found custom capacity: {custom_capacity.custom_capacity}")
                return custom_capacity.custom_capacity
                
            except InprocessInspectionTrayCapacity.DoesNotExist:
                # No custom capacity found, use original from ModelMaster
                print(f"   📋 No custom capacity found, using original: {original_capacity}")
                return original_capacity
                
        except TrayType.DoesNotExist:
            print(f"❌ TrayType '{tray_type_name}' not found in ModelMaster")
            return 0
        except Exception as e:
            print(f"❌ Error getting dynamic tray capacity: {e}")
            return 0

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        print("🔍 ==> Starting InprocessInspectionView.get_context_data")
        
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
        
        # Fetch JigCompleted with polish_finish annotation (prefer TotalStock, fallback to Recovery)
        # ✅ FILTER: Exclude completed records (where jig_position is NOT NULL)
        try:
                
                
                jig_details = JigCompleted.objects.filter(
                    jig_position__isnull=True,  # Only get records NOT completed (no jig_position selected)
                    draft_status='submitted'     # Only show fully submitted jigs (not drafts/active)
                ).annotate(
                    polish_finish=Coalesce(Subquery(total_polish_finish_subquery), Subquery(recovery_polish_finish_subquery))
                ).order_by('-updated_at')
                
                
        except Exception as e:
            print(f"⚠️ Error with polish_finish annotation, using default: {e}")
            # Fallback without polish_finish annotation
            jig_details = JigCompleted.objects.filter(draft_status='submitted').order_by('-updated_at')
            # Add default polish_finish_name to each jig_detail
            for jig_detail in jig_details:
                jig_detail.polish_finish_name = 'No Polish Finish'
        
        print(f"📊 Total JigCompleted found: {len(jig_details)}")
        
        # Group bath numbers by type for better organization
        bath_numbers_by_type = {}
        for bath in BathNumbers.objects.filter(is_active=True).order_by('bath_type', 'bath_number'):
            if bath.bath_type not in bath_numbers_by_type:
                bath_numbers_by_type[bath.bath_type] = []
            bath_numbers_by_type[bath.bath_type].append(bath)
        
        context['bath_numbers_by_type'] = bath_numbers_by_type
        context['all_bath_numbers'] = BathNumbers.objects.filter(is_active=True).order_by('bath_type', 'bath_number')
        
        
        # Process each JigCompleted to handle multiple models and lots
        processed_jig_details = []
        
        for idx, jig_detail in enumerate(jig_details):
            print(f"\n{'='*50}")
            print(f"🔧 Processing JigDetail #{idx+1} (ID: {jig_detail.id})")
            print(f"   lot_id: {jig_detail.lot_id}")
            
            # ✅ FIX: Build multi-model allocation string exactly like JigCompletedTable
            # Template expects: "model1:qty1,model2:qty2,model3:qty3" for split(",") and get_model_name/get_model_qty filters
            if jig_detail.is_multi_model and jig_detail.multi_model_allocation:
                try:
                    models_list = []
                    for m in jig_detail.multi_model_allocation:
                        if isinstance(m, dict):
                            model_name = m.get('model_name', m.get('model', ''))
                            qty = m.get('allocated_qty', 0)
                            if model_name:
                                models_list.append(f"{model_name}:{qty}")
                    no_of_model_cases_str = ','.join(models_list) if models_list else ''
                    if no_of_model_cases_str:
                        jig_detail.no_of_model_cases = no_of_model_cases_str
                        # Also provide a string copy for templates that call split()
                        jig_detail.no_of_model_cases_str = no_of_model_cases_str
                        print(f"   ✅ Built no_of_model_cases from multi_model_allocation: {no_of_model_cases_str}")
                except Exception as e:
                    print(f"   ⚠️ Failed to process multi_model_allocation: {e}")
            
            # Get multiple lot_ids exactly like JigCompletedTable
            multiple_lot_ids = self.get_multiple_lot_ids(jig_detail)
            print(f"   multiple_lot_ids found: {multiple_lot_ids}")
            print(f"   no_of_model_cases: {jig_detail.no_of_model_cases}")
            
            # Process multiple lot_ids to get comma-separated field values (SAME AS JigCompletedTable)
            lot_ids_data = self.process_new_lot_ids(multiple_lot_ids)
            # Fallback: JIG-generated lot_ids don't exist in TotalStockModel; use JigCompleted.batch_id directly
            if jig_detail.batch_id and all(v == 'No Plating Stock No' for v in (lot_ids_data.get('plating_stk_nos_list') or ['No Plating Stock No'])):
                _m = ModelMasterCreation.objects.filter(batch_id=jig_detail.batch_id).select_related('model_stock_no', 'version').first()
                if _m:
                    _ver = 'No Version'
                    if getattr(_m, 'version', None):
                        _ver = getattr(_m.version, 'version_internal', None) or getattr(_m.version, 'version_name', 'No Version')
                    _pl = getattr(_m, 'plating_stk_no', None) or 'No Plating Stock No'
                    _po = getattr(_m, 'polishing_stk_no', None) or 'No Polishing Stock No'
                    lot_ids_data = {
                        'plating_stk_nos': [_pl] * len(multiple_lot_ids),
                        'polishing_stk_nos': [_po] * len(multiple_lot_ids),
                        'version_names': ', '.join([_ver] * len(multiple_lot_ids)),
                        'plating_stk_nos_list': [_pl] * len(multiple_lot_ids),
                        'polishing_stk_nos_list': [_po] * len(multiple_lot_ids),
                        'version_names_list': [_ver] * len(multiple_lot_ids),
                    }

            # Process model_cases using THE SAME batch_ids from lot_ids (CORRECTED LOGIC)
            model_cases_data = self.process_model_cases_corrected(jig_detail.no_of_model_cases, multiple_lot_ids, jig_detail.batch_id)
            
            # Create enhanced jig_detail with multi-lot support
            enhanced_jig_detail = self.create_enhanced_jig_detail(jig_detail, lot_ids_data, model_cases_data)
            
            # Fetch hold/release info from TotalStockModel or RecoveryStockModel
            hold_info = {
                'inprocess_holding_reason': '',
                'inprocess_release_reason': '',
                'inprocess_hold_lot': False,
                'inprocess_release_lot': False,
            }
            tsm = TotalStockModel.objects.filter(lot_id=jig_detail.lot_id).first()
            if tsm:
                hold_info['inprocess_holding_reason'] = tsm.inprocess_holding_reason or ''
                hold_info['inprocess_release_reason'] = tsm.inprocess_release_reason or ''
                hold_info['inprocess_hold_lot'] = tsm.inprocess_hold_lot
                hold_info['inprocess_release_lot'] = tsm.inprocess_release_lot
            else:
                rsm = RecoveryStockModel.objects.filter(lot_id=jig_detail.lot_id).first()
                if rsm:
                    hold_info['inprocess_holding_reason'] = rsm.inprocess_holding_reason or ''
                    hold_info['inprocess_release_reason'] = rsm.inprocess_release_reason or ''
                    hold_info['inprocess_hold_lot'] = rsm.inprocess_hold_lot
                    hold_info['inprocess_release_lot'] = rsm.inprocess_release_lot
        
            # Attach to enhanced_jig_detail
            enhanced_jig_detail.inprocess_holding_reason = hold_info['inprocess_holding_reason']
            enhanced_jig_detail.inprocess_release_reason = hold_info['inprocess_release_reason']
            enhanced_jig_detail.inprocess_hold_lot = hold_info['inprocess_hold_lot']
            enhanced_jig_detail.inprocess_release_lot = hold_info['inprocess_release_lot']
        
            # FIX BUG 1 & 3: For multi-model, display all model names with model qty
            # and use original_lot_qty instead of loaded_cases_qty for display
            try:
                if jig_detail.is_multi_model and jig_detail.multi_model_allocation:
                    mm_data = jig_detail.multi_model_allocation
                    if isinstance(mm_data, str):
                        import json
                        mm_data = json.loads(mm_data)
                    
                    # Build multi-model display: "M1, M2, M3"
                    model_names = []
                    total_qty = 0
                    for i, m in enumerate(mm_data, 1):
                        model_name = m.get('model_name', '')
                        allocated_qty = m.get('allocated_qty', 0)
                        if model_name:
                            model_names.append(f"M{i}")
                            total_qty += int(allocated_qty)
                    
                    # Store multi-model display format for template
                    enhanced_jig_detail.multi_model_display = ', '.join(model_names) if model_names else jig_detail.plating_stock_num
                    enhanced_jig_detail.display_lot_qty = jig_detail.original_lot_qty  # Use original for display
                    enhanced_jig_detail.stored_model_names = [m.get('model_name', '') for m in mm_data]  # For hover tooltip
                else:
                    enhanced_jig_detail.multi_model_display = jig_detail.plating_stock_num or ''
                    enhanced_jig_detail.display_lot_qty = jig_detail.original_lot_qty
                    enhanced_jig_detail.stored_model_names = []
            except Exception as e:
                enhanced_jig_detail.multi_model_display = jig_detail.plating_stock_num or ''
                enhanced_jig_detail.display_lot_qty = jig_detail.original_lot_qty
                enhanced_jig_detail.stored_model_names = []
        
            processed_jig_details.append(enhanced_jig_detail)
            
            print(f"✅ Final Results for JigDetail #{idx+1}:")
            print(f"   final_plating_stk_nos: {enhanced_jig_detail.final_plating_stk_nos}")
            print(f"   final_polishing_stk_nos: {enhanced_jig_detail.final_polishing_stk_nos}")
            print(f"   final_version_names: {enhanced_jig_detail.final_version_names}")
        
        # Add pagination
        page_number = self.request.GET.get('page', 1)
        paginator = Paginator(processed_jig_details, 10)
        page_obj = paginator.get_page(page_number)
        
        print(f"\n📄 Pagination: Page {page_number}, Total items: {len(processed_jig_details)}")
        
        context['jig_details'] = page_obj
        context['bath_numbers'] = bath_numbers_by_type
        context['all_bath_numbers'] = BathNumbers.objects.filter(
            is_active=True
        ).order_by('bath_type', 'bath_number')
        
        return context
    
    def get_multiple_lot_ids(self, jig_detail):
        """
        Get multiple lot_ids exactly like JigCompletedTable does
        This ensures we get the same comma-separated behavior
        """
        print(f"\n🔎 get_multiple_lot_ids for JigDetail ID: {jig_detail.id}")
        
        # First, check if new_lot_ids field exists and has data (like JigCompletedTable)
        new_lot_ids = getattr(jig_detail, 'new_lot_ids', None)
        print(f"   🔍 Checking new_lot_ids field: {new_lot_ids}")
        
        if new_lot_ids and len(new_lot_ids) > 0:
            print(f"   ✅ Found new_lot_ids with {len(new_lot_ids)} items: {new_lot_ids}")
            return new_lot_ids
        
        # If new_lot_ids doesn't exist or is empty, check for other possible fields
        # that might contain multiple lot_ids (adapt based on your model structure)
        
        # Check if there's a lot_ids field (plural)
        lot_ids_field = getattr(jig_detail, 'lot_ids', None)
        print(f"   🔍 Checking lot_ids field: {lot_ids_field}")
        
        if lot_ids_field and len(lot_ids_field) > 0:
            print(f"   ✅ Found lot_ids with {len(lot_ids_field)} items: {lot_ids_field}")
            return lot_ids_field
        
        # As a fallback, use the single lot_id if it exists
        if jig_detail.lot_id:
            print(f"   📝 Using single lot_id as fallback: [{jig_detail.lot_id}]")
            return [jig_detail.lot_id]
        
        print(f"   ❌ No lot_ids found, returning empty list")
        return []

    # FIRST INSTANCE - InprocessInspectionView
    def process_model_cases_corrected(self, no_of_model_cases, lot_ids, jig_batch_id=None):
        """
        Process model_cases using the SAME batch_ids from lot_ids
        Updated to search both TotalStockModel and RecoveryStockModel
        """
        print(f"\n🎲 process_model_cases_corrected called with:")
        print(f"   no_of_model_cases: {no_of_model_cases}")
        print(f"   lot_ids: {lot_ids}")
        
        if not lot_ids:
            print("   ❌ No model_cases or lot_ids provided, returning empty data")
            return {
                'model_plating_stk_nos': '',
                'model_polishing_stk_nos': '',
                'model_version_names': '',
                'model_plating_stk_nos_list': [],
                'model_polishing_stk_nos_list': [],
                'model_version_names_list': []
            }
        
        # STEP 1: Get batch_ids from lot_ids using BOTH stock models
        print("   🔍 STEP 1: Getting batch_ids from lot_ids...")
        
        # *** UPDATED: Search both TotalStockModel and RecoveryStockModel ***
        total_stocks = TotalStockModel.objects.filter(
            lot_id__in=lot_ids
        ).select_related('batch_id')
        
        recovery_stocks = RecoveryStockModel.objects.filter(
            lot_id__in=lot_ids
        ).select_related('batch_id')
        
        print(f"   📦 Found {len(total_stocks)} TotalStockModel records")
        print(f"   📦 Found {len(recovery_stocks)} RecoveryStockModel records")
        
        # Create lot_id to batch_id mapping from both models
        lot_to_batch = {}
        batch_ids = []
        batch_to_model_type = {}  # Track which model type each batch_id comes from
        
        # Process TotalStock results first (priority)
        for stock in total_stocks:
            if stock.batch_id:
                lot_to_batch[stock.lot_id] = stock.batch_id.id
                batch_ids.append(stock.batch_id.id)
                batch_to_model_type[stock.batch_id.id] = 'ModelMasterCreation'
                print(f"      🔗 TotalStock - lot_id: {stock.lot_id} -> batch_id: {stock.batch_id.id}")
        
        # Process RecoveryStock results for lot_ids not found in TotalStock
        for stock in recovery_stocks:
            if stock.batch_id and stock.lot_id not in lot_to_batch:
                lot_to_batch[stock.lot_id] = stock.batch_id.id
                batch_ids.append(stock.batch_id.id)
                batch_to_model_type[stock.batch_id.id] = 'RecoveryMasterCreation'
                print(f"      🔗 RecoveryStock - lot_id: {stock.lot_id} -> batch_id: {stock.batch_id.id}")
        
        # STEP 2: Get Master Creation data using BOTH model types
        print("   🔍 STEP 2: Getting Master Creation data from batch_ids...")
        print(f"   🔢 Using batch_ids: {batch_ids}")
        
        if not batch_ids:
            if jig_batch_id:
                print(f"   🔄 Direct fallback via JigCompleted.batch_id: {jig_batch_id}")
                master = ModelMasterCreation.objects.filter(
                    batch_id=jig_batch_id
                ).select_related('version', 'model_stock_no').first()
                if master:
                    print(f"      ✅ Found ModelMasterCreation id={master.id}")
                    version_value = "No Version"
                    if master.version:
                        version_value = getattr(master.version, 'version_internal', None) or getattr(master.version, 'version_name', 'No Version')
                    plating_value = master.plating_stk_no or "No Plating Stock No"
                    polishing_value = master.polishing_stk_no or "No Polishing Stock No"
                    model_data = {
                        'model_name': getattr(getattr(master, 'model_stock_no', None), 'model_no', None) or getattr(master, 'model_no', None) or "N/A",
                        'plating_color': getattr(master, 'plating_color', None) or "No Plating Color",
                        'polish_finish': getattr(master, 'polish_finish', None) or "N/A",
                        'tray_type': getattr(master, 'tray_type', None) or "No Tray Type",
                        'tray_capacity': getattr(master, 'tray_capacity', None) or self.get_dynamic_tray_capacity(getattr(master, 'tray_type', None) or "No Tray Type")
                    }
                    models_data_list = [model_data] * len(lot_ids)
                    plating_list = [plating_value] * len(lot_ids)
                    polishing_list = [polishing_value] * len(lot_ids)
                    version_list = [version_value] * len(lot_ids)
                    return {
                        'model_plating_stk_nos': ', '.join(plating_list),
                        'model_polishing_stk_nos': ', '.join(polishing_list),
                        'model_version_names': ', '.join(version_list),
                        'model_plating_stk_nos_list': plating_list,
                        'model_polishing_stk_nos_list': polishing_list,
                        'model_version_names_list': version_list,
                        'models_data': models_data_list
                    }
            print("   ❌ No batch_ids found")
            return {
                'model_plating_stk_nos': '',
                'model_polishing_stk_nos': '',
                'model_version_names': '',
                'model_plating_stk_nos_list': [],
                'model_polishing_stk_nos_list': [],
                'model_version_names_list': []
            }
        
        # Separate batch_ids by model type
        model_batch_ids = [bid for bid, mtype in batch_to_model_type.items() if mtype == 'ModelMasterCreation']
        recovery_batch_ids = [bid for bid, mtype in batch_to_model_type.items() if mtype == 'RecoveryMasterCreation']
        
        batch_to_master = {}
        
        # Fetch from ModelMasterCreation
        if model_batch_ids:
            model_masters = ModelMasterCreation.objects.filter(
                id__in=model_batch_ids
            ).select_related('version', 'model_stock_no')
            
            print(f"   🏭 Found {len(model_masters)} ModelMasterCreation records")
            
            for model in model_masters:
                batch_to_master[model.id] = model
                print(f"      🎯 ModelMaster batch_id: {model.id}")
                print(f"         plating_stk_no: {model.plating_stk_no}")
                print(f"         polishing_stk_no: {model.polishing_stk_no}")
                print(f"         version_internal: {getattr(model.version, 'version_internal', None) if model.version else 'None'}")
                print(f"         plating_color: {model.plating_color}")
                print(f"         polish_finish: {model.polish_finish}")
                print(f"         tray_type: {model.tray_type}")
        
        # Fetch from RecoveryMasterCreation
        if recovery_batch_ids:
            try:
                from Recovery_DP.models import RecoveryMasterCreation
                
                recovery_masters = RecoveryMasterCreation.objects.filter(
                    id__in=recovery_batch_ids
                ).select_related('version', 'model_stock_no')
                
                print(f"   🏭 Found {len(recovery_masters)} RecoveryMasterCreation records")
                
                for model in recovery_masters:
                    batch_to_master[model.id] = model
                    print(f"      🎯 RecoveryMaster batch_id: {model.id}")
                    print(f"         plating_stk_no: {getattr(model, 'plating_stk_no', None)}")
                    print(f"         polishing_stk_no: {getattr(model, 'polishing_stk_no', None)}")
                    print(f"         version_internal: {getattr(getattr(model, 'version', None), 'version_internal', None) if hasattr(model, 'version') and model.version else 'None'}")
                    
            except ImportError:
                print("⚠️ RecoveryMasterCreation not found, skipping recovery batch_ids")
            except Exception as e:
                print(f"⚠️ Error fetching RecoveryMasterCreation: {e}")
        
        # STEP 3: Process in the same order as lot_ids to maintain consistency
        print("   🔍 STEP 3: Processing in lot_ids order...")
        
        plating_stk_nos = []
        polishing_stk_nos = []
        version_names = []
        models_data = []
        
        for lot_id in lot_ids:
            batch_id = lot_to_batch.get(lot_id)
            if batch_id and batch_id in batch_to_master:
                master = batch_to_master[batch_id]
                
                plating_value = getattr(master, 'plating_stk_no', None) or "No Plating Stock No"
                polishing_value = getattr(master, 'polishing_stk_no', None) or "No Polishing Stock No"
                
                # Safe version access for both model types
                version_value = "No Version"
                if hasattr(master, 'version') and master.version:
                    version_value = getattr(master.version, 'version_internal', None) or getattr(master.version, 'version_name', 'No Version')
                
                plating_stk_nos.append(plating_value)
                polishing_stk_nos.append(polishing_value)
                version_names.append(version_value)
                
                # plating_color / polish_finish / tray_type are plain CharFields on ModelMasterCreation
                model_data = {
                    'model_name': getattr(getattr(master, 'model_stock_no', None), 'model_no', None) or getattr(master, 'model_no', None) or "N/A",
                    'plating_color': getattr(master, 'plating_color', None) or "No Plating Color",
                    'polish_finish': getattr(master, 'polish_finish', None) or "N/A",
                    'tray_type': getattr(master, 'tray_type', None) or "No Tray Type",
                    'tray_capacity': getattr(master, 'tray_capacity', None) or self.get_dynamic_tray_capacity(getattr(master, 'tray_type', None) or "No Tray Type")
                }
                models_data.append(model_data)
                
                print(f"   🔄 lot_id: {lot_id} -> batch_id: {batch_id}")
                print(f"      ✅ Data: plating={plating_value}, polishing={polishing_value}, version={version_value}")
                print(f"      ✅ Model: name={model_data['model_name']}, color={model_data['plating_color']}, finish={model_data['polish_finish']}, tray={model_data['tray_type']}-{model_data['tray_capacity']}")
            else:
                plating_stk_nos.append("No Plating Stock No")
                polishing_stk_nos.append("No Polishing Stock No")
                version_names.append("No Version")
                models_data.append({
                    'model_name': "N/A",
                    'plating_color': "No Plating Color",
                    'polish_finish': "N/A",
                    'tray_type': "No Tray Type",
                    'tray_capacity': 0
                })
                print(f"   ❌ No data found for lot_id: {lot_id}")
        
        result = {
            'model_plating_stk_nos': ', '.join(plating_stk_nos),
            'model_polishing_stk_nos': ', '.join(polishing_stk_nos),
            'model_version_names': ', '.join(version_names),
            'model_plating_stk_nos_list': plating_stk_nos,
            'model_polishing_stk_nos_list': polishing_stk_nos,
            'model_version_names_list': version_names,
            'models_data': models_data
        }
        
        print(f"   🎉 process_model_cases_corrected FINAL RESULT:")
        print(f"      model_plating_stk_nos: '{result['model_plating_stk_nos']}'")
        print(f"      model_polishing_stk_nos: '{result['model_polishing_stk_nos']}'")
        print(f"      model_version_names: '{result['model_version_names']}'")
        print(f"      models_data: {result['models_data']}")
        
        return result
    
    def process_new_lot_ids(self, new_lot_ids):
        """
        Process new_lot_ids ArrayField to get plating_stk_no, polishing_stk_no, version_name
        Updated to search both TotalStockModel and RecoveryStockModel
        Returns comma-separated values for each field
        """
        print(f"\n🎯 process_new_lot_ids called with: {new_lot_ids}")
        
        if not new_lot_ids:
            print("   ❌ No new_lot_ids provided, returning empty data")
            return {
                'plating_stk_nos': '',
                'polishing_stk_nos': '',
                'version_names': '',
                'plating_stk_nos_list': [],
                'polishing_stk_nos_list': [],
                'version_names_list': []
            }
        
        print(f"   ✅ Processing {len(new_lot_ids)} lot_ids: {new_lot_ids}")
        
        plating_stk_nos = []
        polishing_stk_nos = []
        version_names = []
        
        # *** UPDATED: Get stock objects from both TotalStockModel and RecoveryStockModel ***
        total_stocks = TotalStockModel.objects.filter(
            lot_id__in=new_lot_ids
        ).select_related('batch_id')
        
        recovery_stocks = RecoveryStockModel.objects.filter(
            lot_id__in=new_lot_ids
        ).select_related('batch_id')
        
        # Create mappings of lot_id to stock model
        lot_to_total_stock = {stock.lot_id: stock for stock in total_stocks}
        lot_to_recovery_stock = {stock.lot_id: stock for stock in recovery_stocks}
        
        print(f"   📦 Found {len(total_stocks)} in TotalStockModel")
        print(f"   📦 Found {len(recovery_stocks)} in RecoveryStockModel")
        
        # Get all batch_ids from both models
        total_batch_ids = [stock.batch_id.id for stock in total_stocks if stock.batch_id]
        recovery_batch_ids = [stock.batch_id.id for stock in recovery_stocks if stock.batch_id]
        
        batch_to_model_master = {}
        batch_to_recovery_master = {}
        
        # Fetch ModelMasterCreation objects for TotalStock batch_ids
        if total_batch_ids:
            model_masters = ModelMasterCreation.objects.filter(
                id__in=total_batch_ids
            ).select_related('model_stock_no', 'version')
            batch_to_model_master = {model.id: model for model in model_masters}
            print(f"   🏭 Found {len(model_masters)} ModelMasterCreation objects")
        
        # Fetch RecoveryMasterCreation objects for RecoveryStock batch_ids
        if recovery_batch_ids:
            try:
                from Recovery_DP.models import RecoveryMasterCreation
                
                recovery_masters = RecoveryMasterCreation.objects.filter(
                    id__in=recovery_batch_ids
                ).select_related('model_stock_no', 'version')
                batch_to_recovery_master = {model.id: model for model in recovery_masters}
                print(f"   🏭 Found {len(recovery_masters)} RecoveryMasterCreation objects")
            except ImportError:
                print("⚠️ RecoveryMasterCreation model not found")
                batch_to_recovery_master = {}
            except Exception as e:
                print(f"⚠️ Error fetching RecoveryMasterCreation: {e}")
                batch_to_recovery_master = {}
        
        # Process each lot_id in the original order
        for lot_id in new_lot_ids:
            print(f"   🔄 Processing lot_id: {lot_id}")
            
            # Check TotalStockModel first
            total_stock = lot_to_total_stock.get(lot_id)
            if total_stock and total_stock.batch_id:
                model_master = batch_to_model_master.get(total_stock.batch_id.id)
                if model_master:
                    plating_stk_nos.append(model_master.plating_stk_no or "No Plating Stock No")
                    polishing_stk_nos.append(model_master.polishing_stk_no or "No Polishing Stock No")
                    # Safe version access
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
                    plating_stk_nos.append(getattr(recovery_master, 'plating_stk_no', None) or "No Plating Stock No")
                    polishing_stk_nos.append(getattr(recovery_master, 'polishing_stk_no', None) or "No Polishing Stock No")
                    # Safe version access for recovery master
                    version_name = "No Version"
                    if hasattr(recovery_master, 'version') and recovery_master.version:
                        version_name = getattr(recovery_master.version, 'version_internal', None) or getattr(recovery_master.version, 'version_name', 'No Version')
                    version_names.append(version_name)
                    print(f"     ✅ Found in RecoveryStock -> RecoveryMaster")
                    continue
            
            # If not found in either model, use default values
            plating_stk_nos.append("No Plating Stock No")
            polishing_stk_nos.append("No Polishing Stock No")
            version_names.append("No Version")
            print(f"     ❌ Not found in either model")
        
        result = {
            'plating_stk_nos': plating_stk_nos,  # Keep as list for comma joining
            'polishing_stk_nos': polishing_stk_nos,  # Keep as list for comma joining  
            'version_names': ', '.join(version_names),
            'plating_stk_nos_list': plating_stk_nos,
            'polishing_stk_nos_list': polishing_stk_nos,
            'version_names_list': version_names,
            
        }
        
        print(f"   🎉 process_new_lot_ids FINAL RESULT:")
        print(f"      plating_stk_nos: {result['plating_stk_nos']}")
        print(f"      polishing_stk_nos: {result['polishing_stk_nos']}")
        print(f"      version_names: '{result['version_names']}'")
        
        return result
    
    def process_model_cases(self, no_of_model_cases):
        """
        Process no_of_model_cases to get comma-separated field values
        Updated to search both ModelMasterCreation and RecoveryMasterCreation
        Returns comma-separated values for plating_stk_no, polishing_stk_no, version_name
        """
        print(f"\n🎲 process_model_cases called with: {no_of_model_cases}")
        
        model_stock_nos = self.parse_model_cases(no_of_model_cases)
        print(f"   📋 Parsed model_stock_nos: {model_stock_nos}")
        
        if not model_stock_nos:
            print("   ❌ No model_stock_nos found, returning empty data")
            return {
                'model_plating_stk_nos': '',
                'model_polishing_stk_nos': '',
                'model_version_names': '',
                'model_plating_stk_nos_list': [],
                'model_polishing_stk_nos_list': [],
                'model_version_names_list': []
            }
        
        # *** UPDATED: Get data from both ModelMasterCreation and RecoveryMasterCreation ***
        models_data = self.get_models_data(model_stock_nos)
        print(f"   🏭 get_models_data returned {len(models_data)} records")
        
        for model_no, data in models_data.items():
            print(f"      🎯 model_no: {model_no}")
            print(f"         plating_stk_no: {data.get('plating_stk_no', 'N/A')}")
            print(f"         polishing_stk_no: {data.get('polishing_stk_no', 'N/A')}")
            print(f"         version_name: {data.get('version_name', 'N/A')}")
        
        plating_stk_nos = []
        polishing_stk_nos = []
        version_names = []
        
        for model_stock_no in model_stock_nos:
            model_data = models_data.get(model_stock_no, {})
            plating_value = model_data.get('plating_stk_no', 'No Plating Stock No')
            polishing_value = model_data.get('polishing_stk_no', 'No Polishing Stock No')
            version_value = model_data.get('version_name', 'No Version')
            
            plating_stk_nos.append(plating_value)
            polishing_stk_nos.append(polishing_value)
            version_names.append(version_value)
            
            print(f"   🔄 Processing model_stock_no: {model_stock_no}")
            print(f"      plating={plating_value}, polishing={polishing_value}, version={version_value}")
        
        result = {
            'model_plating_stk_nos': ', '.join(plating_stk_nos),
            'model_polishing_stk_nos': ', '.join(polishing_stk_nos),
            'model_version_names': ', '.join(version_names),
            'model_plating_stk_nos_list': plating_stk_nos,
            'model_polishing_stk_nos_list': polishing_stk_nos,
            'model_version_names_list': version_names
        }
        
        print(f"   🎉 process_model_cases FINAL RESULT:")
        print(f"      model_plating_stk_nos: '{result['model_plating_stk_nos']}'")
        print(f"      model_polishing_stk_nos: '{result['model_polishing_stk_nos']}'")
        print(f"      model_version_names: '{result['model_version_names']}'")
        
        return result
    
    def create_enhanced_jig_detail(self, original_jig_detail, lot_ids_data, model_cases_data):
        """
        Create enhanced jig_detail with multi-lot support and existing functionality
        EXACT SAME LOGIC AS JigCompletedTable
        """
        print(f"\n🔄 create_enhanced_jig_detail:")
        print(f"   lot_ids_data: {lot_ids_data}")
        print(f"   model_cases_data: {model_cases_data}")
        
        # Keep the original object but add new attributes
        jig_detail = original_jig_detail
        
        # Add multi-lot data - EXACT SAME AS JigCompletedTable format
        # lot_ids_data contains lists, so we need to join them for comma-separated display
        jig_detail.lot_plating_stk_nos = lot_ids_data['plating_stk_nos']  # This is a list
        jig_detail.lot_polishing_stk_nos = lot_ids_data['polishing_stk_nos']  # This is a list
        jig_detail.lot_version_names = lot_ids_data['version_names']  # This is already comma-separated
        jig_detail.lot_plating_stk_nos_list = lot_ids_data['plating_stk_nos_list']
        jig_detail.lot_polishing_stk_nos_list = lot_ids_data['polishing_stk_nos_list']
        jig_detail.lot_version_names_list = lot_ids_data['version_names_list']
        
        # Add model_cases data (comma-separated values from no_of_model_cases)
        jig_detail.model_plating_stk_nos = model_cases_data['model_plating_stk_nos']
        jig_detail.model_polishing_stk_nos = model_cases_data['model_polishing_stk_nos']
        jig_detail.model_version_names = model_cases_data['model_version_names']
        jig_detail.model_plating_stk_nos_list = model_cases_data['model_plating_stk_nos_list']
        jig_detail.model_polishing_stk_nos_list = model_cases_data['model_polishing_stk_nos_list']
        jig_detail.model_version_names_list = model_cases_data['model_version_names_list']
        
        # Set model_presents and plating_color from models_data or draft_data
        models_data = model_cases_data.get('models_data', [])
        draft_data = jig_detail.draft_data or {}
        
        if models_data:
            jig_detail.model_presents = ", ".join([m.get('model_name', '') for m in models_data])
            jig_detail.plating_color = models_data[0].get('plating_color', 'No Plating Color') if models_data else 'No Plating Color'
            jig_detail.polish_finish = models_data[0].get('polish_finish', 'N/A') if models_data else 'N/A'
            jig_detail.no_of_model_cases = [m.get('model_name', '') for m in models_data]  # For circles display
            # Provide a string copy in "model:qty" format for templates that call split() + get_model_name/get_model_qty
            try:
                mm = getattr(jig_detail, 'multi_model_allocation', None)
                if mm and isinstance(mm, list):
                    mm_parts = []
                    for _m in mm:
                        if isinstance(_m, dict):
                            _name = _m.get('model_name', _m.get('model', ''))
                            _qty = _m.get('allocated_qty', 0)
                            if _name:
                                mm_parts.append(f"{_name}:{_qty}")
                    jig_detail.no_of_model_cases_str = ','.join(mm_parts) if mm_parts else ','.join([str(m.get('model_name', '')) for m in models_data if m.get('model_name')])
                else:
                    jig_detail.no_of_model_cases_str = ','.join([str(m.get('model_name', '')) for m in models_data if m.get('model_name')])
            except Exception:
                jig_detail.no_of_model_cases_str = ''
        else:
            # No models_data available — build best-effort from draft_data
            model_presents = draft_data.get('model_no', None)
            polish_finish = draft_data.get('polish_finish', None)
            
            jig_detail.model_presents = model_presents or "No Model Info"
            jig_detail.polish_finish = polish_finish or "N/A"
            jig_detail.plating_color = "No Plating Color"  # overridden by TotalStockModel fallback below
            
            # CRITICAL FIX: Parse the original no_of_model_cases from draft_data if it exists
            # This preserves model data saved during jig loading
            original_no_of_model_cases = original_jig_detail.no_of_model_cases
            if original_no_of_model_cases:
                parsed_models = self.parse_model_cases(original_no_of_model_cases)
                jig_detail.no_of_model_cases = parsed_models
                # Also provide a string copy for templates that call split()
                try:
                    jig_detail.no_of_model_cases_str = ','.join([str(x) for x in parsed_models])
                except Exception:
                    jig_detail.no_of_model_cases_str = ''
                print(f"   ✅ Parsed no_of_model_cases from draft_data: {parsed_models}")
            else:
                jig_detail.no_of_model_cases = []
        
        # For single model jigs, set no_of_model_cases if model_no is available
        if not jig_detail.no_of_model_cases and hasattr(jig_detail, 'model_no') and jig_detail.model_no:
            jig_detail.no_of_model_cases = [jig_detail.model_no]
        
        # Set template attributes for Inprocess Inspection table
        jig_detail.jig_qr_id = jig_detail.jig_id  # For JIG ID column
        jig_detail.jig_loaded_date_time = jig_detail.IP_loaded_date_time or jig_detail.updated_at  # For Date & Time column
        jig_detail.total_cases_loaded = jig_detail.updated_lot_qty  # For Jig Lot Qty column
        
        # Parse draft_data for bath_type and tray info
        draft_data = jig_detail.draft_data or {}
        jig_detail.ep_bath_type = draft_data.get('nickel_bath_type', 'Bright')  # For Bath Type column
        
        # Get tray info from draft_data first, fallback to model_cases_data if not available
        jig_detail.tray_type = draft_data.get('tray_type', None)
        jig_detail.tray_capacity = draft_data.get('tray_capacity', None)
        
        # If tray info not in draft_data, try to get from model_cases_data (model data)
        if not jig_detail.tray_type or jig_detail.tray_type == 'No Tray Type':
            if models_data and len(models_data) > 0:
                jig_detail.tray_type = models_data[0].get('tray_type', 'No Tray Type')
            else:
                jig_detail.tray_type = 'No Tray Type'
        
        if not jig_detail.tray_capacity or jig_detail.tray_capacity == 0:
            if models_data and len(models_data) > 0:
                jig_detail.tray_capacity = models_data[0].get('tray_capacity', 0)
            else:
                jig_detail.tray_capacity = 0
        
        # Fallback: Fetch plating_color and polish_finish from TotalStockModel if not set and models_data is empty
        if not models_data and (jig_detail.plating_color == 'No Plating Color' or jig_detail.polish_finish == 'N/A'):
            try:
                tsm = TotalStockModel.objects.filter(lot_id=jig_detail.lot_id).first()
                if tsm:
                    if tsm.plating_color and jig_detail.plating_color == 'No Plating Color':
                        jig_detail.plating_color = tsm.plating_color.plating_color
                        print(f"   🔄 Plating color fallback from TotalStockModel: {jig_detail.plating_color}")
                    if tsm.polish_finish and jig_detail.polish_finish == 'N/A':
                        jig_detail.polish_finish = tsm.polish_finish.polish_finish
                        print(f"   🔄 Polish finish fallback from TotalStockModel: {jig_detail.polish_finish}")
            except Exception as e:
                print(f"   ⚠️ Error fetching plating_color/polish_finish from TotalStockModel: {e}")
        
        # Fallback: Fetch tray info from TotalStockModel if not set
        if not jig_detail.tray_type or jig_detail.tray_type == 'No Tray Type':
            try:
                tsm = TotalStockModel.objects.filter(lot_id=jig_detail.lot_id).first()
                if tsm and tsm.batch_id:
                    mmc = tsm.batch_id
                    if mmc.model_stock_no and mmc.model_stock_no.tray_type:
                        jig_detail.tray_type = mmc.model_stock_no.tray_type.tray_type
                        jig_detail.tray_capacity = self.get_dynamic_tray_capacity(mmc.model_stock_no.tray_type.tray_type if mmc.model_stock_no.tray_type else "No Tray Type")
                        print(f"   🔄 Tray info fallback from TotalStockModel: type={jig_detail.tray_type}, capacity={jig_detail.tray_capacity}")
            except Exception as e:
                print(f"   ⚠️ Error fetching tray info from TotalStockModel: {e}")
        
        print(f"   📝 Multi-lot data assigned (as lists):")
        print(f"      lot_plating_stk_nos: {jig_detail.lot_plating_stk_nos}")
        print(f"      lot_polishing_stk_nos: {jig_detail.lot_polishing_stk_nos}")
        print(f"      lot_version_names: '{jig_detail.lot_version_names}'")

        
        print(f"   📝 Multi-model data assigned:")
        print(f"      model_plating_stk_nos: '{jig_detail.model_plating_stk_nos}'")
        print(f"      model_polishing_stk_nos: '{jig_detail.model_polishing_stk_nos}'")
        print(f"      model_version_names: '{jig_detail.model_version_names}'")
        
        # Combine both sources for final display - EXACT SAME LOGIC AS JigCompletedTable
        # Priority: model data if available, otherwise lot data
        if jig_detail.model_plating_stk_nos:
            jig_detail.final_plating_stk_nos = jig_detail.model_plating_stk_nos
        else:
            # Convert lot data list to comma-separated string like JigCompletedTable
            jig_detail.final_plating_stk_nos = ', '.join(jig_detail.lot_plating_stk_nos) if jig_detail.lot_plating_stk_nos else ''
            
        if jig_detail.model_polishing_stk_nos:
            jig_detail.final_polishing_stk_nos = jig_detail.model_polishing_stk_nos
        else:
            # Convert lot data list to comma-separated string like JigCompletedTable
            jig_detail.final_polishing_stk_nos = ', '.join(jig_detail.lot_polishing_stk_nos) if jig_detail.lot_polishing_stk_nos else ''
            
        if jig_detail.model_version_names:
            jig_detail.final_version_names = jig_detail.model_version_names
        else:
            # lot_version_names is already comma-separated from JigCompletedTable logic
            jig_detail.final_version_names = jig_detail.lot_version_names if jig_detail.lot_version_names else ''
        
        print(f"   🎯 Final combined data (model takes priority):")
        print(f"      final_plating_stk_nos: '{jig_detail.final_plating_stk_nos}'")
        print(f"      final_polishing_stk_nos: '{jig_detail.final_polishing_stk_nos}'")
        print(f"      final_version_names: '{jig_detail.final_version_names}'")
        
        # Add indicators for template logic
        jig_detail.has_multiple_lots = bool(jig_detail.lot_plating_stk_nos)
        jig_detail.has_multiple_models = bool(model_cases_data['model_plating_stk_nos'])
        
        print(f"   🚩 Indicators:")
        print(f"      has_multiple_lots: {jig_detail.has_multiple_lots}")
        print(f"      has_multiple_models: {jig_detail.has_multiple_models}")
        
        # Apply existing InprocessInspectionView logic for single model data
        self.apply_existing_logic(jig_detail)
        
        return jig_detail
    
    
    def apply_existing_logic(self, jig_detail):
            """
            Apply the existing InprocessInspectionView logic for backward compatibility
            Updated to properly handle model images
            """
            print(f"\n🔧 apply_existing_logic for single lot_id: {jig_detail.lot_id}")
            
            # Define color palette for model circles (global consistency)
            color_palette = [
                "#e74c3c", "#f1c40f", "#2ecc71", "#3498db", "#9b59b6",
                "#e67e22", "#1abc9c", "#34495e", "#f39c12", "#d35400",
                "#c0392b", "#8e44ad", "#2980b9", "#27ae60", "#16a085",
                "#ff6b6b", "#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7",
                "#dda0dd", "#98d8c8", "#f7dc6f", "#bb8fce", "#85c1e9"
            ]
            
            # Get or create global model color mapping
            if not hasattr(self, '_global_model_colors'):
                self._global_model_colors = {}
                self._color_index = 0
            
            if jig_detail.no_of_model_cases:
                # Create CONSISTENT color mapping for display
                jig_model_colors = {}
                jig_model_images = {}
                
                # Sort models for consistent color assignment
                sorted_models = sorted(jig_detail.no_of_model_cases)
                
                for model_no in sorted_models:
                    if model_no not in self._global_model_colors:
                        color_index = self._color_index % len(color_palette)
                        self._global_model_colors[model_no] = color_palette[color_index]
                        self._color_index += 1
                    
                    jig_model_colors[model_no] = self._global_model_colors[model_no]
                    
                    # FIXED: Get images for each model from ModelMaster
                    try:
                        # Extract clean model number for lookup
                        clean_model_no = model_no
                        # Try to extract just the numeric part (e.g., "1805SSA02" -> "1805")
                        import re
                        match = re.match(r'^(\d+)', str(model_no))
                        if match:
                            clean_model_no = match.group(1)
                        
                        print(f"🔍 Looking up images for model: {model_no} -> {clean_model_no}")
                        
                        # Search for ModelMaster with this model_no
                        model_master = ModelMaster.objects.filter(
                            model_no=clean_model_no
                        ).prefetch_related('images').first()
                        
                        images = []
                        if model_master and model_master.images.exists():
                            for img in model_master.images.all():
                                if img.master_image:
                                    images.append(img.master_image.url)
                                    print(f"   📸 Found image: {img.master_image.url}")
                        
                        # Fallback: try ModelMasterCreation.images via JigCompleted.batch_id
                        if not images:
                            _jbc = getattr(jig_detail, 'batch_id', None)
                            if _jbc:
                                try:
                                    _mmc = ModelMasterCreation.objects.filter(batch_id=_jbc).prefetch_related('images').first()
                                    if _mmc:
                                        for _img in _mmc.images.all():
                                            if _img.master_image:
                                                images.append(_img.master_image.url)
                                                print(f"   📸 Found MMC image: {_img.master_image.url}")
                                except Exception as _ie:
                                    print(f"   ⚠️ MMC image lookup error: {_ie}")
                        
                        if not images:
                            images = [static('assets/images/imagePlaceholder.jpg')]
                            print(f"   📸 No images found, using placeholder")
                        
                        jig_model_images[model_no] = images
                        
                    except Exception as e:
                        print(f"   ❌ Error getting images for model {model_no}: {e}")
                        jig_model_images[model_no] = [static('assets/images/imagePlaceholder.jpg')]
                
                jig_detail.model_colors = jig_model_colors
                jig_detail.model_images = jig_model_images
                
                print(f"   🎨 Model colors assigned: {jig_model_colors}")
                print(f"   📸 Model images assigned: {list(jig_model_images.keys())}")
                        
                # *** UPDATED: Use dual model approach to get batch data ***
                batch_id = None
                batch_model_class = None
                
                if jig_detail.lot_id:
                    print(f"   🔍 Looking up stock model for lot_id: {jig_detail.lot_id}")
                    try:
                        stock_model, is_recovery, batch_model_cls = self.get_stock_model_data(jig_detail.lot_id)
                        if stock_model and stock_model.batch_id:
                            batch_id = stock_model.batch_id.id
                            batch_model_class = batch_model_cls
                            print(f"   ✅ Found batch_id: {batch_id} from {'Recovery' if is_recovery else 'Total'}Stock")
                        else:
                            print(f"   ❌ No stock model or batch_id found for lot_id: {jig_detail.lot_id}")
                    except Exception as e:
                        print(f"   ⚠️ Error querying stock models: {e}")
                
                if batch_id and batch_model_class:
                    # Get batch data using the appropriate model class
                    print(f"   🏭 Looking up {batch_model_class.__name__} for batch_id: {batch_id}")
                    try:
                        batch_data = self.get_batch_data(batch_id, batch_model_class)
                        
                        print(f"   ✅ Found {batch_model_class.__name__}:")
                        print(f"      model_no: {batch_data.get('model_no', 'None')}")
                        print(f"      plating_stk_no: {batch_data.get('plating_stk_no', 'None')}")
                        print(f"      polishing_stk_no: {batch_data.get('polishing_stk_no', 'None')}")
                        print(f"      version_name: {batch_data.get('version_name', 'None')}")
                        
                        # Apply batch data to jig_detail
                        for key, value in batch_data.items():
                            if not hasattr(jig_detail, key) or getattr(jig_detail, key) is None:
                                setattr(jig_detail, key, value)
                        
                        # If plating_stock_num is set, try to populate no_of_model_cases from it
                        if hasattr(jig_detail, 'plating_stock_num') and jig_detail.plating_stock_num:
                            try:
                                model_master = ModelMaster.objects.filter(plating_stk_no=jig_detail.plating_stock_num).first()
                                if model_master:
                                    jig_detail.no_of_model_cases = [model_master.model_no]
                                    print(f"   📦 Populated no_of_model_cases from plating_stock_num: {jig_detail.no_of_model_cases}")
                                else:
                                    print(f"   ⚠️ No ModelMaster found for plating_stock_num: {jig_detail.plating_stock_num}")
                            except Exception as e:
                                print(f"   ⚠️ Error populating model from plating_stock_num: {e}")
                        
                        # Keep existing model display logic for frontend (multiple model circles)
                        if jig_detail.no_of_model_cases:
                            # Create color mapping for display (keeping existing functionality)
                            jig_model_colors = {}
                            for idx, model_no in enumerate(jig_detail.no_of_model_cases):
                                color_index = idx % len(color_palette)
                                jig_model_colors[model_no] = color_palette[color_index]
                            jig_detail.model_colors = jig_model_colors
                            
                            # Keep model images for existing functionality
                            jig_model_images = {}
                            model_images = batch_data.get('model_images', [static('assets/images/imagePlaceholder.jpg')])
                            for model_no in jig_detail.no_of_model_cases:
                                jig_model_images[model_no] = {
                                    'images': model_images,
                                    'first_image': model_images[0] if model_images else None
                                }
                            jig_detail.model_images = jig_model_images
                        else:
                            jig_detail.model_colors = {}
                            jig_detail.model_images = {}
                        
                        # Create single item lists for template compatibility
                        jig_detail.unique_versions = [batch_data.get('version_name', 'No Version')]
                        jig_detail.unique_vendors = [batch_data.get('vendor_internal', 'No Vendor')]
                        jig_detail.unique_locations = [batch_data.get('location_name', 'No Location')]
                        jig_detail.unique_tray_types = [batch_data.get('tray_type', 'No Tray Type')]
                        jig_detail.unique_tray_capacities = [batch_data.get('tray_capacity', 0)]
                        
                        # Calculate no_of_trays based on total_cases_loaded and tray_capacity
                        tray_capacity = batch_data.get('tray_capacity', 0)
                        if tray_capacity > 0 and jig_detail.total_cases_loaded:
                            jig_detail.calculated_no_of_trays = math.ceil(
                                jig_detail.total_cases_loaded / tray_capacity
                            )
                            jig_detail.primary_tray_capacity = tray_capacity
                        else:
                            jig_detail.calculated_no_of_trays = 0
                            jig_detail.primary_tray_capacity = 0
                            
                        print(f"   🎯 Applied batch data from {batch_model_class.__name__}")
                            
                    except Exception as e:
                        print(f"   ❌ Error getting batch data: {e}")
                        self._apply_mmc_direct_fallback(jig_detail)
                else:
                    print(f"   ❌ No batch_id from TotalStock — using MMC direct fallback")
                    self._apply_mmc_direct_fallback(jig_detail)
            else:
                # CRITICAL FIX: If no_of_model_cases is empty, but we have plating_stk_nos,
                # populate models from the successfully extracted plating stock numbers
                if hasattr(jig_detail, 'final_plating_stk_nos') and jig_detail.final_plating_stk_nos:
                    print(f"   🔧 CRITICAL FIX: Populating models from final_plating_stk_nos: {jig_detail.final_plating_stk_nos}")
                    
                    # Split comma-separated plating stock numbers
                    plating_stk_nos = [x.strip() for x in jig_detail.final_plating_stk_nos.split(',')]
                    model_numbers = []
                    jig_model_colors = {}
                    jig_model_images = {}
                    
                    # For each plating stock number, find the corresponding ModelMaster
                    for plating_stk_no in plating_stk_nos:
                        try:
                            # Find ModelMaster with this plating stock number
                            model_master = ModelMaster.objects.filter(plating_stk_no=plating_stk_no).prefetch_related('images').first()
                            if model_master:
                                model_no = model_master.model_no
                                model_numbers.append(model_no)
                                
                                # Assign color from global palette
                                if model_no not in self._global_model_colors:
                                    color_index = self._color_index % len(color_palette)
                                    self._global_model_colors[model_no] = color_palette[color_index]
                                    self._color_index += 1
                                jig_model_colors[model_no] = self._global_model_colors[model_no]
                                
                                # Get model images
                                images = []
                                if model_master.images.exists():
                                    for img in model_master.images.all():
                                        if img.master_image:
                                            images.append(img.master_image.url)
                                
                                if not images:
                                    images = [static('assets/images/imagePlaceholder.jpg')]
                                
                                jig_model_images[model_no] = images
                                print(f"   ✅ Found ModelMaster: {plating_stk_no} -> {model_no}")
                            else:
                                print(f"   ⚠️ No ModelMaster found for plating_stk_no: {plating_stk_no}")
                        except Exception as e:
                            print(f"   ❌ Error processing plating_stk_no {plating_stk_no}: {e}")
                    
                    # Populate the required fields for frontend
                    jig_detail.no_of_model_cases = model_numbers
                    # Also provide a string copy for templates that call split()
                    try:
                        jig_detail.no_of_model_cases_str = ','.join([str(x) for x in model_numbers])
                    except Exception:
                        jig_detail.no_of_model_cases_str = ''
                    jig_detail.model_colors = jig_model_colors
                    jig_detail.model_images = jig_model_images
                    
                    print(f"   🎯 POPULATED FROM PLATING STK NOS:")
                    print(f"      no_of_model_cases: {jig_detail.no_of_model_cases}")
                    print(f"      model_colors: {jig_model_colors}")
                    print(f"      model_images keys: {list(jig_model_images.keys())}")
                else:
                    # No models data at all - initialize empty dictionaries to prevent template errors
                    jig_detail.model_colors = {}
                    jig_detail.model_images = {}
                    print(f"   ℹ️ No models for jig_detail, initialized empty dicts")       
    
        
    
  
    def _apply_mmc_direct_fallback(self, jig_detail):
        """
        Fallback: use JigCompleted.batch_id to get ModelMasterCreation directly.
        Preserves plating_color/polish_finish/tray data already set from models_data.
        """
        jig_batch = getattr(jig_detail, 'batch_id', None)
        if jig_batch:
            try:
                mmc = ModelMasterCreation.objects.filter(
                    batch_id=jig_batch
                ).prefetch_related('images').select_related('version', 'model_stock_no').first()
                if mmc:
                    imgs = [img.master_image.url for img in mmc.images.all() if img.master_image]
                    if not imgs:
                        imgs = [static('assets/images/imagePlaceholder.jpg')]
                    if isinstance(getattr(jig_detail, 'model_images', None), dict):
                        for mn in (jig_detail.no_of_model_cases or []):
                            jig_detail.model_images[mn] = imgs
                    else:
                        jig_detail.model_images = {mn: imgs for mn in (jig_detail.no_of_model_cases or [])}
                    tray_cap = getattr(mmc, 'tray_capacity', 0) or 0
                    ver = 'No Version'
                    if getattr(mmc, 'version', None):
                        ver = getattr(mmc.version, 'version_internal', None) or getattr(mmc.version, 'version_name', 'No Version')
                    jig_detail.unique_versions = [ver]
                    jig_detail.unique_vendors = ['No Vendor']
                    jig_detail.unique_locations = ['No Location']
                    jig_detail.unique_tray_types = [getattr(mmc, 'tray_type', 'No Tray Type') or 'No Tray Type']
                    jig_detail.unique_tray_capacities = [tray_cap]
                    if tray_cap > 0 and getattr(jig_detail, 'total_cases_loaded', 0):
                        jig_detail.calculated_no_of_trays = math.ceil(jig_detail.total_cases_loaded / tray_cap)
                        jig_detail.primary_tray_capacity = tray_cap
                    else:
                        jig_detail.calculated_no_of_trays = 0
                        jig_detail.primary_tray_capacity = 0
                    print(f"   ✅ MMC direct fallback applied via batch_id={jig_batch}")
                    return
            except Exception as e:
                print(f"   ⚠️ MMC direct fallback error: {e}")
        for attr in ('unique_versions', 'unique_vendors', 'unique_locations',
                     'unique_tray_types', 'unique_tray_capacities'):
            if not hasattr(jig_detail, attr):
                setattr(jig_detail, attr, [])
        if not hasattr(jig_detail, 'calculated_no_of_trays'):
            jig_detail.calculated_no_of_trays = 0
        if not hasattr(jig_detail, 'primary_tray_capacity'):
            jig_detail.primary_tray_capacity = 0
        if not getattr(jig_detail, 'model_images', None):
            jig_detail.model_images = {}

    def get_batch_data(self, batch_id, batch_model_class):
        """
        Get batch data for single model case from either ModelMasterCreation or RecoveryMasterCreation
        Updated to handle both model types (copied from JigCompletedTable)
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
            
            # Fetch plating_color from TotalStockModel (total stock model)
            plating_color = "No Plating Color"
            try:
                tsm = TotalStockModel.objects.filter(batch_id=model_master.id).first()
                if tsm and tsm.plating_color:
                    plating_color = tsm.plating_color.plating_color
            except Exception as e:
                print(f"⚠️ Error fetching plating_color from TotalStockModel: {e}")
            
            # Fetch tray info from ModelMaster
            tray_type = "No Tray Type"
            tray_capacity = 0
            if model_master.model_stock_no and model_master.model_stock_no.tray_type:
                tray_type = model_master.model_stock_no.tray_type.tray_type
                tray_capacity = model_master.model_stock_no.tray_capacity or 0
            
            return {
                'batch_id': batch_id,
                'model_no': model_master.model_stock_no.model_no if model_master.model_stock_no else None,
                'version_name': version_name,
                'plating_color': plating_color,
                'polish_finish': getattr(model_master, 'polish_finish', None) or "No Polish Finish",
                'plating_stk_no': getattr(model_master, 'plating_stk_no', None) or "No Plating Stock No",
                'polishing_stk_no': getattr(model_master, 'polishing_stk_no', None) or "No Polishing Stock No",
                'location_name': model_master.location.location_name if hasattr(model_master, 'location') and model_master.location else "No Location",
                'tray_type': tray_type,
                'tray_capacity': tray_capacity,
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
            return self.get_default_batch_data()
    
    def parse_model_cases(self, no_of_model_cases):
        """
        Parse no_of_model_cases field to extract model_stock_no values
        """
        print(f"\n🧩 parse_model_cases called with: {no_of_model_cases} (type: {type(no_of_model_cases)})")
        
        if not no_of_model_cases:
            print("   ❌ No no_of_model_cases provided, returning empty list")
            return []
        
        try:
            # Try parsing as JSON first
            if isinstance(no_of_model_cases, str):
                print(f"   📝 Processing as string: '{no_of_model_cases}'")
                
                # If it's JSON format like: {"model1": 10, "model2": 15}
                if no_of_model_cases.startswith('{') or no_of_model_cases.startswith('['):
                    print("   🔍 Detected JSON format, parsing...")
                    parsed = json.loads(no_of_model_cases)
                    if isinstance(parsed, dict):
                        result = list(parsed.keys())
                        print(f"      ✅ JSON dict parsed, keys: {result}")
                        return result
                    elif isinstance(parsed, list):
                        print(f"      ✅ JSON list parsed: {parsed}")
                        return parsed
                
                # If it's comma-separated like: "model1,model2,model3"
                elif ',' in no_of_model_cases:
                    result = [model.strip() for model in no_of_model_cases.split(',') if model.strip()]
                    print(f"   ✅ Comma-separated parsed: {result}")
                    return result
                
                # If it's a single model
                else:
                    result = [no_of_model_cases.strip()]
                    print(f"   ✅ Single model parsed: {result}")
                    return result
            
            # If it's already a list or other format
            elif isinstance(no_of_model_cases, (list, tuple)):
                result = list(no_of_model_cases)
                print(f"   ✅ List/tuple format: {result}")
                return result
            
            # Single value case
            else:
                result = [str(no_of_model_cases)]
                print(f"   ✅ Single value converted to list: {result}")
                return result
                
        except (json.JSONDecodeError, AttributeError) as e:
            # Fallback: treat as single model
            result = [str(no_of_model_cases)] if no_of_model_cases else []
            print(f"   ⚠️ JSON parsing failed ({e}), fallback result: {result}")
            return result
    
    def get_models_data(self, model_stock_nos):
        """
        Fetch model data from both ModelMasterCreation and RecoveryMasterCreation
        Updated to search both model types (copied from JigCompletedTable)
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
    
    def extract_model_data(self, model_master, source_type):
        """
        Extract model data from either ModelMasterCreation or RecoveryMasterCreation
        (Copied from JigCompletedTable)
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
        
        # Fetch plating_color from TotalStockModel (total stock model) using batch_id
        # This ensures we get the authoritative plating color data
        plating_color_display = "No Plating Color"
        try:
            tsm = TotalStockModel.objects.filter(batch_id=model_master.id).first()
            if tsm and tsm.plating_color:
                plating_color_display = tsm.plating_color.plating_color
        except Exception as e:
            print(f"⚠️ Error fetching plating_color from TotalStockModel: {e}")
        
        return {
            'batch_id': model_master.id,
            'model_no': model_no,
            'version_name': version_name,
            'plating_color': plating_color_display,
            'polish_finish': getattr(model_master, 'polish_finish', None) or "No Polish Finish",
            'plating_stk_no': getattr(model_master, 'plating_stk_no', None) or "No Plating Stock No",
            'polishing_stk_no': getattr(model_master, 'polishing_stk_no', None) or "No Polishing Stock No",
            'location_name': model_master.location.location_name if hasattr(model_master, 'location') and model_master.location else "No Location",
            'tray_type': getattr(model_master, 'tray_type', None).tray_type if getattr(model_master, 'tray_type', None) else "No Tray Type",
            'tray_capacity': self.get_dynamic_tray_capacity(getattr(model_master, 'tray_type', None).tray_type if getattr(model_master, 'tray_type', None) else "No Tray Type"),
            'vendor_internal': getattr(model_master, 'vendor_internal', None) or "No Vendor",
            'model_images': images,
            'model_stock_no_obj': model_master.model_stock_no,
            'source_type': source_type  # Track which model type this came from
        }
    
    def set_default_values(self, jig_detail):
        """
        Set default values when no data is found
        """
        defaults = self.get_default_batch_data()
        for key, value in defaults.items():
            setattr(jig_detail, key, value)
        
        # Additional defaults for InprocessInspectionView
        jig_detail.model_colors = {}
        jig_detail.model_images = {}
        jig_detail.unique_versions = []
        jig_detail.unique_vendors = []
        jig_detail.unique_locations = []
        jig_detail.unique_tray_types = []
        jig_detail.unique_tray_capacities = []
        jig_detail.calculated_no_of_trays = 0
        jig_detail.primary_tray_capacity = 0
    
    def get_default_batch_data(self):
        """
        Get default values for when no model data is found
        (Copied from JigCompletedTable)
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

@method_decorator(csrf_exempt, name='dispatch')
class GetBathNumbersByTypeAPIView(APIView):
    """
    API endpoint to get bath numbers filtered by bath type
    """
    def get(self, request):
        try:
            bath_type = request.GET.get('bath_type', '').strip()
            
            if not bath_type:
                return Response({'error': 'bath_type parameter is required'}, status=400)
            
            # Get active bath numbers for the specified type
            bath_numbers = BathNumbers.objects.filter(
                bath_type=bath_type,
                is_active=True
            ).order_by('bath_number')
            
            bath_data = []
            for bath in bath_numbers:
                bath_data.append({
                    'id': bath.id,
                    'bath_number': bath.bath_number,
                    'bath_type': bath.bath_type
                })
            
            return Response({
                'success': True,
                'bath_numbers': bath_data,
                'bath_type': bath_type,
                'count': len(bath_data)
            })
            
        except Exception as e:
            print(f"Error in GetBathNumbersByTypeAPIView: {str(e)}")
            return Response({'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class SaveBathNumberAPIView(APIView):
    """
    API endpoint for saving bath number to JigCompleted
    """
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            jig_id = data.get('jig_id')
            bath_number = data.get('bath_number', '').strip()
            
            if not jig_id or not bath_number:
                return Response({
                    'success': False,
                    'message': 'jig_id and bath_number are required'
                }, status=400)
            
            # Find the JigCompleted record
            try:
                jig_detail = JigCompleted.objects.get(id=jig_id)
            except JigCompleted.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'JigCompleted record not found'
                }, status=404)
            
            # Find the BathNumbers record
            try:
                bath_obj = BathNumbers.objects.get(
                    bath_number=bath_number,
                    is_active=True
                )
            except BathNumbers.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Bath number not found or inactive'
                }, status=404)
            
            # Validate bath type matches (optional validation)
            if jig_detail.ep_bath_type and jig_detail.ep_bath_type != bath_obj.bath_type:
                return Response({
                    'success': False,
                    'message': f'Bath type mismatch. Expected: {jig_detail.ep_bath_type}, Got: {bath_obj.bath_type}'
                }, status=400)
            
            # Save the bath number to jig_detail
            jig_detail.bath_numbers = bath_obj
            jig_detail.save(update_fields=['bath_numbers'])
            
            return Response({
                'success': True,
                'message': 'Bath number saved successfully',
                'bath_number': bath_obj.bath_number,
                'bath_type': bath_obj.bath_type
            })
            
        except Exception as e:
            print(f"Error in SaveBathNumberAPIView: {str(e)}")
            return Response({
                'success': False,
                'message': f'Internal server error: {str(e)}'
            }, status=500)

# AJAX endpoint to save bath number
@csrf_exempt
@require_http_methods(["POST"])
def save_bath_number(request):
    try:
        data = json.loads(request.body)
        jig_id = data.get('jig_id')
        bath_number = data.get('bath_number')
        
        if not jig_id or not bath_number:
            return JsonResponse({
                'success': False, 
                'message': 'Missing jig_id or bath_number'
            }, status=400)
        
        # Get the JigCompleted instance
        try:
            jig_detail = JigCompleted.objects.get(id=jig_id)
        except JigCompleted.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'message': 'JigCompleted not found'
            }, status=404)
        
        bath_type = data.get('bath_type')

        # Get the BathNumbers instance
        try:
            qs = BathNumbers.objects.filter(bath_number=bath_number)
            if bath_type:
                qs = qs.filter(bath_type=bath_type)
            bath_obj = qs.get()
        except BathNumbers.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Bath number not found'
            }, status=404)
        except BathNumbers.MultipleObjectsReturned:
            # Fallback: pick first active match
            bath_obj = BathNumbers.objects.filter(bath_number=bath_number, is_active=True).first()
            if not bath_obj:
                return JsonResponse({
                    'success': False,
                    'message': 'Ambiguous bath number — please select again'
                }, status=400)
        
        # Save the bath number to JigCompleted
        jig_detail.bath_numbers = bath_obj
        # jig_detail.last_process_module = "Inprocess Inspection"
        # jig_detail.IP_loaded_date_time = timezone.now()
        jig_detail.save(update_fields=['bath_numbers', 'last_process_module', 'IP_loaded_date_time'])

        return JsonResponse({
            'success': True, 
            'message': 'Bath number saved successfully',
            'bath_number': bath_number
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False, 
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'message': f'Error saving bath number: {str(e)}'
        }, status=500)


# AJAX endpoint to save jig remarks - UPDATED TO MAKE REMARKS OPTIONAL
@csrf_exempt
@require_http_methods(["POST"])
def save_jig_remarks(request):
    try:
        data = json.loads(request.body)
        jig_id = data.get('jig_id')
        jig_position = data.get('jig_position')
        remarks = data.get('remarks', '').strip()  # Default to empty string if not provided
        
        if not jig_id:
            return JsonResponse({
                'success': False, 
                'message': 'Missing jig_id'
            }, status=400)
            
        # UPDATED: Only jig_position is required, remarks is optional
        if not jig_position:
            return JsonResponse({
                'success': False, 
                'message': 'Jig position is required'
            }, status=400)
        
        # Validate jig_position
        valid_positions = ['Top', 'Middle', 'Bottom']
        if jig_position not in valid_positions:
            return JsonResponse({
                'success': False, 
                'message': 'Invalid jig position'
            }, status=400)
        
        # Validate remarks length only if remarks is provided
        if remarks and len(remarks) > 50:
            return JsonResponse({
                'success': False, 
                'message': 'Remarks cannot exceed 50 characters'
            }, status=400)
        
        # Get the JigCompleted instance
        try:
            jig_detail = JigCompleted.objects.get(id=jig_id)
        except JigCompleted.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'message': 'JigCompleted not found'
            }, status=404)
        
        # Save the jig position and remarks to JigCompleted
        jig_detail.jig_position = jig_position
        jig_detail.IP_loaded_date_time = timezone.now()
        jig_detail.last_process_module = "Inprocess Inspection"
        jig_detail.remarks = remarks  # Can be empty string
        jig_detail.save(update_fields=['jig_position', 'remarks', 'IP_loaded_date_time', 'last_process_module'])

        return JsonResponse({
            'success': True, 
            'message': 'Jig position and remarks saved successfully',
            'jig_position': jig_position,
            'remarks': remarks
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False, 
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'message': f'Error saving jig details: {str(e)}'
        }, status=500)  
        
        
@method_decorator(csrf_exempt, name='dispatch')
class IISaveIPPickRemarkAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            pick_remarks = data.get('pick_remarks', '').strip()
            if not lot_id:
                return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)
            if not pick_remarks:
                return JsonResponse({'success': False, 'error': 'Missing pick_remarks'}, status=400)
            # Save pick_remarks to JigCompleted.remarks for all matching lot_id
            updated = JigCompleted.objects.filter(lot_id=lot_id).update(pick_remarks=pick_remarks)
            if updated == 0:
                return JsonResponse({'success': False, 'error': 'No JigCompleted found for this lot_id'}, status=404)
            return JsonResponse({'success': True, 'message': 'Pick remarks saved to JigCompleted'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
  

@method_decorator(csrf_exempt, name='dispatch')
class InprocessSaveHoldUnholdReasonAPIView(APIView):
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
                obj.inprocess_holding_reason = remark
                obj.inprocess_hold_lot = True
                obj.inprocess_release_reason = ''
                obj.inprocess_release_lot = False
            elif action == 'unhold':
                obj.inprocess_release_reason = remark
                obj.inprocess_hold_lot = False
                obj.inprocess_release_lot = True

            obj.save(update_fields=['inprocess_holding_reason', 'inprocess_release_reason', 'inprocess_hold_lot', 'inprocess_release_lot'])
            return JsonResponse({'success': True, 'message': 'Reason saved.'})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


  

@method_decorator(csrf_exempt, name='dispatch')
class JigCompletedDeleteAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            if not lot_id:
                return Response({'success': False, 'message': 'Missing lot_id'}, status=status.HTTP_400_BAD_REQUEST)
            deleted, _ = JigCompleted.objects.filter(lot_id=lot_id).delete()
            if deleted == 0:
                return Response({'success': False, 'message': 'No record found for this lot_id'}, status=status.HTTP_404_NOT_FOUND)
            return Response({'success': True, 'message': 'Record deleted successfully'})
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InprocessInspectionCompleteView(TemplateView):
    template_name = "Inprocess_Inspection/Inprocess_Inspection_Completed.html"

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
        # Use IST timezone
        tz = pytz.timezone("Asia/Kolkata")
        now_local = timezone.now().astimezone(tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        # Get date filter parameters from request
        from_date_str = self.request.GET.get('from_date')
        to_date_str = self.request.GET.get('to_date')

        # Calculate date range
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

        # Filter JigCompleted by IP_loaded_date_time
        # ✅ FILTER: Include only completed records (where jig_position IS NOT NULL)
        jig_details_qs = JigCompleted.objects.filter(
            updated_at__date__gte=from_date,
            updated_at__date__lte=to_date,
            jig_position__isnull=False  # Only get completed records (jig_position selected)
        ).order_by('-updated_at')
        
        print("🔍 ==> Starting InprocessInspectionCompleteView.get_context_data")

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
        
        # Fetch JigCompleted with filters for completed items and polish_finish annotation
        # ✅ FILTER: Include only completed records (where jig_position IS NOT NULL)
        try:
            jig_details = JigCompleted.objects.filter(
                jig_position__isnull=False  # Only get completed records (jig_position selected)
            ).annotate(
                polish_finish=Coalesce(Subquery(total_polish_finish_subquery), Subquery(recovery_polish_finish_subquery))
            ).order_by('-updated_at')
        except Exception as e:
            print(f"⚠️ Error with polish_finish annotation, using default: {e}")
            # Fallback without polish_finish annotation
            jig_details = JigCompleted.objects.order_by('-updated_at')
            # Add default polish_finish_name to each jig_detail
            for jig_detail in jig_details:
                jig_detail.polish_finish_name = 'No Polish Finish'
        
        print(f"📊 Total JigCompleted found (completed): {len(jig_details)}")
        
        # Fetch all Bath Numbers for dropdown
        bath_numbers = BathNumbers.objects.all().order_by('bath_number')
        
        # Process each JigCompleted to handle multiple models and lots - SAME AS InprocessInspectionView
        processed_jig_details = []
        
        for idx, jig_detail in enumerate(jig_details_qs):
            print(f"\n{'='*50}")
            print(f"🔧 Processing JigDetail #{idx+1} (ID: {jig_detail.id})")
            print(f"   lot_id: {jig_detail.lot_id}")
            
            # Get multiple lot_ids exactly like JigCompletedTable
            multiple_lot_ids = self.get_multiple_lot_ids(jig_detail)
            print(f"   multiple_lot_ids found: {multiple_lot_ids}")
            print(f"   no_of_model_cases: {jig_detail.no_of_model_cases}")
            
            # Process multiple lot_ids to get comma-separated field values (SAME AS JigCompletedTable)
            lot_ids_data = self.process_new_lot_ids(multiple_lot_ids)
            # Fallback: JIG-generated lot_ids don't exist in TotalStockModel; use JigCompleted.batch_id directly
            if jig_detail.batch_id and all(v == 'No Plating Stock No' for v in (lot_ids_data.get('plating_stk_nos_list') or ['No Plating Stock No'])):
                _m = ModelMasterCreation.objects.filter(batch_id=jig_detail.batch_id).select_related('model_stock_no', 'version').first()
                if _m:
                    _ver = 'No Version'
                    if getattr(_m, 'version', None):
                        _ver = getattr(_m.version, 'version_internal', None) or getattr(_m.version, 'version_name', 'No Version')
                    _pl = getattr(_m, 'plating_stk_no', None) or 'No Plating Stock No'
                    _po = getattr(_m, 'polishing_stk_no', None) or 'No Polishing Stock No'
                    lot_ids_data = {
                        'plating_stk_nos': [_pl] * len(multiple_lot_ids),
                        'polishing_stk_nos': [_po] * len(multiple_lot_ids),
                        'version_names': ', '.join([_ver] * len(multiple_lot_ids)),
                        'plating_stk_nos_list': [_pl] * len(multiple_lot_ids),
                        'polishing_stk_nos_list': [_po] * len(multiple_lot_ids),
                        'version_names_list': [_ver] * len(multiple_lot_ids),
                    }

            # Process model_cases using THE SAME batch_ids from lot_ids (CORRECTED LOGIC)
            model_cases_data = self.process_model_cases_corrected(jig_detail.no_of_model_cases, multiple_lot_ids, jig_detail.batch_id)
            
            # Create enhanced jig_detail with multi-lot support
            enhanced_jig_detail = self.create_enhanced_jig_detail(jig_detail, lot_ids_data, model_cases_data)
            
            processed_jig_details.append(enhanced_jig_detail)
            
            print(f"✅ Final Results for JigDetail #{idx+1}:")
            print(f"   final_plating_stk_nos: {enhanced_jig_detail.final_plating_stk_nos}")
            print(f"   final_polishing_stk_nos: {enhanced_jig_detail.final_polishing_stk_nos}")
            print(f"   final_version_names: {enhanced_jig_detail.final_version_names}")
        
        # Add pagination
        page_number = self.request.GET.get('page', 1)
        paginator = Paginator(processed_jig_details, 10)
        page_obj = paginator.get_page(page_number)
        
        print(f"\n📄 Pagination: Page {page_number}, Total items: {len(processed_jig_details)}")
        
        context['jig_details'] = page_obj
        context['bath_numbers'] = bath_numbers
        context['from_date'] = from_date
        context['to_date'] = to_date

        
        return context
    
    def get_multiple_lot_ids(self, jig_detail):
        """
        Get multiple lot_ids exactly like JigCompletedTable does
        This ensures we get the same comma-separated behavior
        """
        print(f"\n🔎 get_multiple_lot_ids for JigDetail ID: {jig_detail.id}")
        
        # First, check if new_lot_ids field exists and has data (like JigCompletedTable)
        new_lot_ids = getattr(jig_detail, 'new_lot_ids', None)
        print(f"   🔍 Checking new_lot_ids field: {new_lot_ids}")
        
        if new_lot_ids and len(new_lot_ids) > 0:
            print(f"   ✅ Found new_lot_ids with {len(new_lot_ids)} items: {new_lot_ids}")
            return new_lot_ids
        
        # Check if there's a lot_ids field (plural)
        lot_ids_field = getattr(jig_detail, 'lot_ids', None)
        print(f"   🔍 Checking lot_ids field: {lot_ids_field}")
        
        if lot_ids_field and len(lot_ids_field) > 0:
            print(f"   ✅ Found lot_ids with {len(lot_ids_field)} items: {lot_ids_field}")
            return lot_ids_field
        
        # As a fallback, use the single lot_id if it exists
        if jig_detail.lot_id:
            print(f"   📝 Using single lot_id as fallback: [{jig_detail.lot_id}]")
            return [jig_detail.lot_id]
        
        print(f"   ❌ No lot_ids found, returning empty list")
        return []

    def process_new_lot_ids(self, new_lot_ids):
        """
        Process new_lot_ids ArrayField to get plating_stk_no, polishing_stk_no, version_name
        Updated to search both TotalStockModel and RecoveryStockModel
        Returns comma-separated values for each field
        """
        print(f"\n🎯 process_new_lot_ids called with: {new_lot_ids}")
        
        if not new_lot_ids:
            print("   ❌ No new_lot_ids provided, returning empty data")
            return {
                'plating_stk_nos': '',
                'polishing_stk_nos': '',
                'version_names': '',
                'plating_stk_nos_list': [],
                'polishing_stk_nos_list': [],
                'version_names_list': []
            }
        
        print(f"   ✅ Processing {len(new_lot_ids)} lot_ids: {new_lot_ids}")
        
        plating_stk_nos = []
        polishing_stk_nos = []
        version_names = []
        
        # *** UPDATED: Get stock objects from both TotalStockModel and RecoveryStockModel ***
        total_stocks = TotalStockModel.objects.filter(
            lot_id__in=new_lot_ids
        ).select_related('batch_id')
        
        recovery_stocks = RecoveryStockModel.objects.filter(
            lot_id__in=new_lot_ids
        ).select_related('batch_id')
        
        # Create mappings of lot_id to stock model
        lot_to_total_stock = {stock.lot_id: stock for stock in total_stocks}
        lot_to_recovery_stock = {stock.lot_id: stock for stock in recovery_stocks}
        
        print(f"   📦 Found {len(total_stocks)} in TotalStockModel")
        print(f"   📦 Found {len(recovery_stocks)} in RecoveryStockModel")
        
        # Get all batch_ids from both models
        total_batch_ids = [stock.batch_id.id for stock in total_stocks if stock.batch_id]
        recovery_batch_ids = [stock.batch_id.id for stock in recovery_stocks if stock.batch_id]
        
        batch_to_model_master = {}
        batch_to_recovery_master = {}
        
        # Fetch ModelMasterCreation objects for TotalStock batch_ids
        if total_batch_ids:
            model_masters = ModelMasterCreation.objects.filter(
                id__in=total_batch_ids
            ).select_related('model_stock_no', 'version')
            batch_to_model_master = {model.id: model for model in model_masters}
            print(f"   🏭 Found {len(model_masters)} ModelMasterCreation objects")
        
        # Fetch RecoveryMasterCreation objects for RecoveryStock batch_ids
        if recovery_batch_ids:
            try:
                from Recovery_DP.models import RecoveryMasterCreation
                
                recovery_masters = RecoveryMasterCreation.objects.filter(
                    id__in=recovery_batch_ids
                ).select_related('model_stock_no', 'version')
                batch_to_recovery_master = {model.id: model for model in recovery_masters}
                print(f"   🏭 Found {len(recovery_masters)} RecoveryMasterCreation objects")
            except ImportError:
                print("⚠️ RecoveryMasterCreation model not found")
                batch_to_recovery_master = {}
            except Exception as e:
                print(f"⚠️ Error fetching RecoveryMasterCreation: {e}")
                batch_to_recovery_master = {}
        
        # Process each lot_id in the original order
        for lot_id in new_lot_ids:
            print(f"   🔄 Processing lot_id: {lot_id}")
            
            # Check TotalStockModel first
            total_stock = lot_to_total_stock.get(lot_id)
            if total_stock and total_stock.batch_id:
                model_master = batch_to_model_master.get(total_stock.batch_id.id)
                if model_master:
                    plating_stk_nos.append(model_master.plating_stk_no or "No Plating Stock No")
                    polishing_stk_nos.append(model_master.polishing_stk_no or "No Polishing Stock No")
                    # Safe version access
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
                    plating_stk_nos.append(getattr(recovery_master, 'plating_stk_no', None) or "No Plating Stock No")
                    polishing_stk_nos.append(getattr(recovery_master, 'polishing_stk_no', None) or "No Polishing Stock No")
                    # Safe version access for recovery master
                    version_name = "No Version"
                    if hasattr(recovery_master, 'version') and recovery_master.version:
                        version_name = getattr(recovery_master.version, 'version_internal', None) or getattr(recovery_master.version, 'version_name', 'No Version')
                    version_names.append(version_name)
                    print(f"     ✅ Found in RecoveryStock -> RecoveryMaster")
                    continue
            
            # If not found in either model, use default values
            plating_stk_nos.append("No Plating Stock No")
            polishing_stk_nos.append("No Polishing Stock No")
            version_names.append("No Version")
            print(f"     ❌ Not found in either model")
        
        result = {
            'plating_stk_nos': plating_stk_nos,  # Keep as list for comma joining
            'polishing_stk_nos': polishing_stk_nos,  # Keep as list for comma joining  
            'version_names': ', '.join(version_names),
            'plating_stk_nos_list': plating_stk_nos,
            'polishing_stk_nos_list': polishing_stk_nos,
            'version_names_list': version_names
        }
        
        print(f"   🎉 process_new_lot_ids FINAL RESULT:")
        print(f"      plating_stk_nos: {result['plating_stk_nos']}")
        print(f"      polishing_stk_nos: {result['polishing_stk_nos']}")
        print(f"      version_names: '{result['version_names']}'")
        
        return result

    # SECOND INSTANCE - Another class
    def process_model_cases_corrected(self, no_of_model_cases, lot_ids, jig_batch_id=None):
        """
        Process model_cases using the SAME batch_ids from lot_ids (plating_color/polish_finish/tray_type are plain CharFields)
        Updated to search both TotalStockModel and RecoveryStockModel
        """
        print(f"\n🎲 process_model_cases_corrected called with:")
        print(f"   no_of_model_cases: {no_of_model_cases}")
        print(f"   lot_ids: {lot_ids}")
        
        if not lot_ids:
            print("   ❌ No model_cases or lot_ids provided, returning empty data")
            return {
                'model_plating_stk_nos': '',
                'model_polishing_stk_nos': '',
                'model_version_names': '',
                'model_plating_stk_nos_list': [],
                'model_polishing_stk_nos_list': [],
                'model_version_names_list': []
            }
        
        # STEP 1: Get batch_ids from lot_ids using BOTH stock models
        print("   🔍 STEP 1: Getting batch_ids from lot_ids...")
        
        # *** UPDATED: Search both TotalStockModel and RecoveryStockModel ***
        total_stocks = TotalStockModel.objects.filter(
            lot_id__in=lot_ids
        ).select_related('batch_id')
        
        recovery_stocks = RecoveryStockModel.objects.filter(
            lot_id__in=lot_ids
        ).select_related('batch_id')
        
        print(f"   📦 Found {len(total_stocks)} TotalStockModel records")
        print(f"   📦 Found {len(recovery_stocks)} RecoveryStockModel records")
        
        # Create lot_id to batch_id mapping from both models
        lot_to_batch = {}
        batch_ids = []
        batch_to_model_type = {}  # Track which model type each batch_id comes from
        
        # Process TotalStock results first (priority)
        for stock in total_stocks:
            if stock.batch_id:
                lot_to_batch[stock.lot_id] = stock.batch_id.id
                batch_ids.append(stock.batch_id.id)
                batch_to_model_type[stock.batch_id.id] = 'ModelMasterCreation'
                print(f"      🔗 TotalStock - lot_id: {stock.lot_id} -> batch_id: {stock.batch_id.id}")
        
        # Process RecoveryStock results for lot_ids not found in TotalStock
        for stock in recovery_stocks:
            if stock.batch_id and stock.lot_id not in lot_to_batch:
                lot_to_batch[stock.lot_id] = stock.batch_id.id
                batch_ids.append(stock.batch_id.id)
                batch_to_model_type[stock.batch_id.id] = 'RecoveryMasterCreation'
                print(f"      🔗 RecoveryStock - lot_id: {stock.lot_id} -> batch_id: {stock.batch_id.id}")
        
        # STEP 2: Get Master Creation data using BOTH model types
        print("   🔍 STEP 2: Getting Master Creation data from batch_ids...")
        print(f"   🔢 Using batch_ids: {batch_ids}")
        
        if not batch_ids:
            if jig_batch_id:
                print(f"   🔄 Direct fallback via JigCompleted.batch_id: {jig_batch_id}")
                master = ModelMasterCreation.objects.filter(
                    batch_id=jig_batch_id
                ).select_related('version', 'model_stock_no').first()
                if master:
                    print(f"      ✅ Found ModelMasterCreation id={master.id}")
                    version_value = "No Version"
                    if master.version:
                        version_value = getattr(master.version, 'version_internal', None) or getattr(master.version, 'version_name', 'No Version')
                    plating_value = master.plating_stk_no or "No Plating Stock No"
                    polishing_value = master.polishing_stk_no or "No Polishing Stock No"
                    model_data = {
                        'model_name': getattr(getattr(master, 'model_stock_no', None), 'model_no', None) or getattr(master, 'model_no', None) or "N/A",
                        'plating_color': getattr(master, 'plating_color', None) or "No Plating Color",
                        'polish_finish': getattr(master, 'polish_finish', None) or "N/A",
                        'tray_type': getattr(master, 'tray_type', None) or "No Tray Type",
                        'tray_capacity': getattr(master, 'tray_capacity', None) or self.get_dynamic_tray_capacity(getattr(master, 'tray_type', None) or "No Tray Type")
                    }
                    models_data_list = [model_data] * len(lot_ids)
                    plating_list = [plating_value] * len(lot_ids)
                    polishing_list = [polishing_value] * len(lot_ids)
                    version_list = [version_value] * len(lot_ids)
                    return {
                        'model_plating_stk_nos': ', '.join(plating_list),
                        'model_polishing_stk_nos': ', '.join(polishing_list),
                        'model_version_names': ', '.join(version_list),
                        'model_plating_stk_nos_list': plating_list,
                        'model_polishing_stk_nos_list': polishing_list,
                        'model_version_names_list': version_list,
                        'models_data': models_data_list
                    }
            print("   ❌ No batch_ids found")
            return {
                'model_plating_stk_nos': '',
                'model_polishing_stk_nos': '',
                'model_version_names': '',
                'model_plating_stk_nos_list': [],
                'model_polishing_stk_nos_list': [],
                'model_version_names_list': []
            }
        
        # Separate batch_ids by model type
        model_batch_ids = [bid for bid, mtype in batch_to_model_type.items() if mtype == 'ModelMasterCreation']
        recovery_batch_ids = [bid for bid, mtype in batch_to_model_type.items() if mtype == 'RecoveryMasterCreation']
        
        batch_to_master = {}
        
        # Fetch from ModelMasterCreation
        if model_batch_ids:
            model_masters = ModelMasterCreation.objects.filter(
                id__in=model_batch_ids
            ).select_related('version', 'model_stock_no')
            
            print(f"   🏭 Found {len(model_masters)} ModelMasterCreation records")
            
            for model in model_masters:
                batch_to_master[model.id] = model
                print(f"      🎯 ModelMaster batch_id: {model.id}")
                print(f"         plating_stk_no: {model.plating_stk_no}")
                print(f"         polishing_stk_no: {model.polishing_stk_no}")
                print(f"         version_internal: {getattr(model.version, 'version_internal', None) if model.version else 'None'}")
                print(f"         plating_color: {model.plating_color}")
                print(f"         polish_finish: {model.polish_finish}")
                print(f"         tray_type: {model.tray_type}")
        
        # Fetch from RecoveryMasterCreation
        if recovery_batch_ids:
            try:
                from Recovery_DP.models import RecoveryMasterCreation
                
                recovery_masters = RecoveryMasterCreation.objects.filter(
                    id__in=recovery_batch_ids
                ).select_related('version', 'model_stock_no')
                
                print(f"   🏭 Found {len(recovery_masters)} RecoveryMasterCreation records")
                
                for model in recovery_masters:
                    batch_to_master[model.id] = model
                    print(f"      🎯 RecoveryMaster batch_id: {model.id}")
                    print(f"         plating_stk_no: {getattr(model, 'plating_stk_no', None)}")
                    print(f"         polishing_stk_no: {getattr(model, 'polishing_stk_no', None)}")
                    print(f"         version_internal: {getattr(getattr(model, 'version', None), 'version_internal', None) if hasattr(model, 'version') and model.version else 'None'}")
                    
            except ImportError:
                print("⚠️ RecoveryMasterCreation not found, skipping recovery batch_ids")
            except Exception as e:
                print(f"⚠️ Error fetching RecoveryMasterCreation: {e}")
        
        # STEP 3: Process in the same order as lot_ids to maintain consistency
        print("   🔍 STEP 3: Processing in lot_ids order...")
        
        plating_stk_nos = []
        polishing_stk_nos = []
        version_names = []
        models_data = []
        
        for lot_id in lot_ids:
            batch_id = lot_to_batch.get(lot_id)
            if batch_id and batch_id in batch_to_master:
                master = batch_to_master[batch_id]
                
                plating_value = getattr(master, 'plating_stk_no', None) or "No Plating Stock No"
                polishing_value = getattr(master, 'polishing_stk_no', None) or "No Polishing Stock No"
                
                # Safe version access for both model types
                version_value = "No Version"
                if hasattr(master, 'version') and master.version:
                    version_value = getattr(master.version, 'version_internal', None) or getattr(master.version, 'version_name', 'No Version')
                
                plating_stk_nos.append(plating_value)
                polishing_stk_nos.append(polishing_value)
                version_names.append(version_value)
                
                # plating_color / polish_finish / tray_type are plain CharFields on ModelMasterCreation
                model_data = {
                    'model_name': getattr(getattr(master, 'model_stock_no', None), 'model_no', None) or getattr(master, 'model_no', None) or "N/A",
                    'plating_color': getattr(master, 'plating_color', None) or "No Plating Color",
                    'polish_finish': getattr(master, 'polish_finish', None) or "N/A",
                    'tray_type': getattr(master, 'tray_type', None) or "No Tray Type",
                    'tray_capacity': getattr(master, 'tray_capacity', None) or self.get_dynamic_tray_capacity(getattr(master, 'tray_type', None) or "No Tray Type")
                }
                models_data.append(model_data)
                
                print(f"   🔄 lot_id: {lot_id} -> batch_id: {batch_id}")
                print(f"      ✅ Data: plating={plating_value}, polishing={polishing_value}, version={version_value}")
                print(f"      ✅ Model: name={model_data['model_name']}, color={model_data['plating_color']}, finish={model_data['polish_finish']}, tray={model_data['tray_type']}-{model_data['tray_capacity']}")
            else:
                plating_stk_nos.append("No Plating Stock No")
                polishing_stk_nos.append("No Polishing Stock No")
                version_names.append("No Version")
                models_data.append({
                    'model_name': "N/A",
                    'plating_color': "No Plating Color",
                    'polish_finish': "N/A",
                    'tray_type': "No Tray Type",
                    'tray_capacity': 0
                })
                print(f"   ❌ No data found for lot_id: {lot_id}")
        
        result = {
            'model_plating_stk_nos': ', '.join(plating_stk_nos),
            'model_polishing_stk_nos': ', '.join(polishing_stk_nos),
            'model_version_names': ', '.join(version_names),
            'model_plating_stk_nos_list': plating_stk_nos,
            'model_polishing_stk_nos_list': polishing_stk_nos,
            'model_version_names_list': version_names,
            'models_data': models_data
        }
        
        print(f"   🎉 process_model_cases_corrected FINAL RESULT:")
        print(f"      model_plating_stk_nos: '{result['model_plating_stk_nos']}'")
        print(f"      model_polishing_stk_nos: '{result['model_polishing_stk_nos']}'")
        print(f"      model_version_names: '{result['model_version_names']}'")
        print(f"      models_data: {result['models_data']}")
        
        return result

    def create_enhanced_jig_detail(self, original_jig_detail, lot_ids_data, model_cases_data):
        """
        Create enhanced jig_detail with multi-lot support and existing functionality
        EXACT SAME LOGIC AS JigCompletedTable
        """
        print(f"\n🔄 create_enhanced_jig_detail:")
        print(f"   lot_ids_data: {lot_ids_data}")
        print(f"   model_cases_data: {model_cases_data}")
        
        # Keep the original object but add new attributes
        jig_detail = original_jig_detail
        
        # Add multi-lot data - EXACT SAME AS JigCompletedTable format
        # lot_ids_data contains lists, so we need to join them for comma-separated display
        jig_detail.lot_plating_stk_nos = lot_ids_data['plating_stk_nos']  # This is a list
        jig_detail.lot_polishing_stk_nos = lot_ids_data['polishing_stk_nos']  # This is a list
        jig_detail.lot_version_names = lot_ids_data['version_names']  # This is already comma-separated
        jig_detail.lot_plating_stk_nos_list = lot_ids_data['plating_stk_nos_list']
        jig_detail.lot_polishing_stk_nos_list = lot_ids_data['polishing_stk_nos_list']
        jig_detail.lot_version_names_list = lot_ids_data['version_names_list']
        
        # Add model_cases data (comma-separated values from no_of_model_cases)
        jig_detail.model_plating_stk_nos = model_cases_data['model_plating_stk_nos']
        jig_detail.model_polishing_stk_nos = model_cases_data['model_polishing_stk_nos']
        jig_detail.model_version_names = model_cases_data['model_version_names']
        jig_detail.model_plating_stk_nos_list = model_cases_data['model_plating_stk_nos_list']
        jig_detail.model_polishing_stk_nos_list = model_cases_data['model_polishing_stk_nos_list']
        jig_detail.model_version_names_list = model_cases_data['model_version_names_list']
        jig_detail.last_process_module = getattr(original_jig_detail, 'last_process_module', None)  # <-- FIXED INDENT

        print(f"   📝 Multi-lot data assigned (as lists):")
        print(f"      lot_plating_stk_nos: {jig_detail.lot_plating_stk_nos}")
        print(f"      lot_polishing_stk_nos: {jig_detail.lot_polishing_stk_nos}")
        print(f"      lot_version_names: '{jig_detail.lot_version_names}'")
        
        print(f"   📝 Multi-model data assigned:")
        print(f"      model_plating_stk_nos: '{jig_detail.model_plating_stk_nos}'")
        print(f"      model_polishing_stk_nos: '{jig_detail.model_polishing_stk_nos}'")
        print(f"      model_version_names: '{jig_detail.model_version_names}'")
        
        # Combine both sources for final display - EXACT SAME LOGIC AS JigCompletedTable
        # Priority: model data if available, otherwise lot data
        if jig_detail.model_plating_stk_nos:
            jig_detail.final_plating_stk_nos = jig_detail.model_plating_stk_nos
        else:
            # Convert lot data list to comma-separated string like JigCompletedTable
            jig_detail.final_plating_stk_nos = ', '.join(jig_detail.lot_plating_stk_nos) if jig_detail.lot_plating_stk_nos else ''
            
        if jig_detail.model_polishing_stk_nos:
            jig_detail.final_polishing_stk_nos = jig_detail.model_polishing_stk_nos
        else:
            # Convert lot data list to comma-separated string like JigCompletedTable
            jig_detail.final_polishing_stk_nos = ', '.join(jig_detail.lot_polishing_stk_nos) if jig_detail.lot_polishing_stk_nos else ''
            
        if jig_detail.model_version_names:
            jig_detail.final_version_names = jig_detail.model_version_names
        else:
            # lot_version_names is already comma-separated from JigCompletedTable logic
            jig_detail.final_version_names = jig_detail.lot_version_names if jig_detail.lot_version_names else ''
        
        print(f"   🎯 Final combined data (model takes priority):")
        print(f"      final_plating_stk_nos: '{jig_detail.final_plating_stk_nos}'")
        print(f"      final_polishing_stk_nos: '{jig_detail.final_polishing_stk_nos}'")
        print(f"      final_version_names: '{jig_detail.final_version_names}'")
        
        # Add indicators for template logic
        jig_detail.has_multiple_lots = bool(jig_detail.lot_plating_stk_nos)
        jig_detail.has_multiple_models = bool(model_cases_data['model_plating_stk_nos'])
        
        print(f"   🚩 Indicators:")
        print(f"      has_multiple_lots: {jig_detail.has_multiple_lots}")
        print(f"      has_multiple_models: {jig_detail.has_multiple_models}")
        
        # Set template attributes for Inprocess Inspection table
        jig_detail.jig_qr_id = jig_detail.jig_id  # For JIG ID column
        if not jig_detail.jig_id:
            jig_detail.jig_id = f"JIG-{jig_detail.id}"
            jig_detail.jig_qr_id = jig_detail.jig_id
        jig_detail.jig_loaded_date_time = jig_detail.IP_loaded_date_time or jig_detail.updated_at  # For Date & Time column
        jig_detail.total_cases_loaded = jig_detail.updated_lot_qty  # For Jig Lot Qty column
        
        # Apply existing InprocessInspectionCompleteView logic for single model data
        self.apply_existing_logic(jig_detail)
        
        return jig_detail

    def apply_existing_logic(self, jig_detail):
        """
        Apply the existing InprocessInspectionCompleteView logic for backward compatibility
        Updated to use dual model approach
        """
        print(f"\n🔧 apply_existing_logic for single lot_id: {jig_detail.lot_id}")
        
        # Define color palette for model circles (keeping existing functionality)
        color_palette = [
            "#e74c3c", "#f1c40f", "#2ecc71", "#3498db", "#9b59b6",
            "#e67e22", "#1abc9c", "#34495e", "#f39c12", "#d35400",
            "#c0392b", "#8e44ad", "#2980b9", "#27ae60", "#16a085"
        ]
        
        # *** UPDATED: Use dual model approach to get batch data ***
        batch_id = None
        batch_model_class = None
        
        if jig_detail.lot_id:
            print(f"   🔍 Looking up stock model for lot_id: {jig_detail.lot_id}")
            try:
                stock_model, is_recovery, batch_model_cls = self.get_stock_model_data(jig_detail.lot_id)
                if stock_model and stock_model.batch_id:
                    batch_id = stock_model.batch_id.id
                    batch_model_class = batch_model_cls
                    print(f"   ✅ Found batch_id: {batch_id} from {'Recovery' if is_recovery else 'Total'}Stock")
                else:
                    print(f"   ❌ No stock model or batch_id found for lot_id: {jig_detail.lot_id}")
            except Exception as e:
                print(f"   ⚠️ Error querying stock models: {e}")
        
        if batch_id and batch_model_class:
            # Get batch data using the appropriate model class
            print(f"   🏭 Looking up {batch_model_class.__name__} for batch_id: {batch_id}")
            try:
                batch_data = self.get_batch_data(batch_id, batch_model_class)
                
                print(f"   ✅ Found {batch_model_class.__name__}:")
                print(f"      model_no: {batch_data.get('model_no', 'None')}")
                print(f"      plating_stk_no: {batch_data.get('plating_stk_no', 'None')}")
                print(f"      polishing_stk_no: {batch_data.get('polishing_stk_no', 'None')}")
                print(f"      version_name: {batch_data.get('version_name', 'None')}")
                
                # Apply batch data to jig_detail
                for key, value in batch_data.items():
                    if not hasattr(jig_detail, key) or getattr(jig_detail, key) is None:
                        setattr(jig_detail, key, value)
                
                # ---------------------------------------------------------------
                # FIX: Parse no_of_model_cases into a proper list.
                # Raw format: 'MODEL1 [lot_id]:qty | MODEL2 [lot_id]:qty'
                # Iterating a raw string gives characters — we need model names.
                # ---------------------------------------------------------------
                raw_nmc = jig_detail.no_of_model_cases
                if raw_nmc and isinstance(raw_nmc, str):
                    # Pipe-separated: 'MODEL [lot]:qty | MODEL2 [lot]:qty'
                    parsed_model_list = [
                        part.split(' [')[0].strip()
                        for part in raw_nmc.split(' | ')
                        if part.strip() and part.split(' [')[0].strip()
                    ]
                elif raw_nmc and isinstance(raw_nmc, list):
                    parsed_model_list = raw_nmc
                else:
                    parsed_model_list = []

                # Fallback: use already-resolved lot plating_stk_nos when no_of_model_cases is empty
                if not parsed_model_list:
                    parsed_model_list = (
                        getattr(jig_detail, 'lot_plating_stk_nos_list', None) or
                        getattr(jig_detail, 'model_plating_stk_nos_list', None) or
                        []
                    )

                # Replace raw string with clean parsed list so template iterates models
                jig_detail.no_of_model_cases = parsed_model_list

                # Keep existing model display logic for frontend (multiple model circles)
                if parsed_model_list:
                    # Create color mapping for display
                    jig_model_colors = {}
                    for idx, model_no in enumerate(parsed_model_list):
                        color_index = idx % len(color_palette)
                        jig_model_colors[model_no] = color_palette[color_index]
                    jig_detail.model_colors = jig_model_colors
                    
                    # Keep model images for existing functionality
                    jig_model_images = {}
                    model_images = batch_data.get('model_images', [static('assets/images/imagePlaceholder.jpg')])
                    for model_no in parsed_model_list:
                        jig_model_images[model_no] = {
                            'images': model_images,
                            'first_image': model_images[0] if model_images else None
                        }
                    jig_detail.model_images = jig_model_images
                else:
                    jig_detail.model_colors = {}
                    jig_detail.model_images = {}
                
                # Create single item lists for template compatibility
                jig_detail.unique_versions = [batch_data.get('version_name', 'No Version')]
                jig_detail.unique_vendors = [batch_data.get('vendor_internal', 'No Vendor')]
                jig_detail.unique_locations = [batch_data.get('location_name', 'No Location')]
                jig_detail.unique_tray_types = [batch_data.get('tray_type', 'No Tray Type')]
                jig_detail.unique_tray_capacities = [batch_data.get('tray_capacity', 0)]
                
                # Calculate no_of_trays based on total_cases_loaded and tray_capacity
                tray_capacity = batch_data.get('tray_capacity', 0)
                if tray_capacity > 0 and jig_detail.total_cases_loaded:
                    jig_detail.calculated_no_of_trays = math.ceil(
                        jig_detail.total_cases_loaded / tray_capacity
                    )
                    jig_detail.primary_tray_capacity = tray_capacity
                else:
                    jig_detail.calculated_no_of_trays = 0
                    jig_detail.primary_tray_capacity = 0
                    
                print(f"   🎯 Applied batch data from {batch_model_class.__name__}")
                
                # Ensure model_presents is populated if empty
                if not hasattr(jig_detail, 'model_presents') or not jig_detail.model_presents or jig_detail.model_presents in ['', 'No Model Info']:
                    jig_detail.model_presents = batch_data.get('model_no', 'No Model Info')
                    
            except Exception as e:
                print(f"   ❌ Error getting batch data: {e}")
                self._apply_mmc_direct_fallback(jig_detail)
        else:
            print(f"   ❌ No batch_id from TotalStock — using MMC direct fallback")
            self._apply_mmc_direct_fallback(jig_detail)

    def _apply_mmc_direct_fallback(self, jig_detail):
        """
        Fallback: use JigCompleted.batch_id to get ModelMasterCreation directly.
        Preserves plating_color/polish_finish/tray data already set from models_data.
        """
        jig_batch = getattr(jig_detail, 'batch_id', None)
        if jig_batch:
            try:
                mmc = ModelMasterCreation.objects.filter(
                    batch_id=jig_batch
                ).prefetch_related('images').select_related('version', 'model_stock_no').first()
                if mmc:
                    imgs = [img.master_image.url for img in mmc.images.all() if img.master_image]
                    if not imgs:
                        imgs = [static('assets/images/imagePlaceholder.jpg')]
                    if isinstance(getattr(jig_detail, 'model_images', None), dict):
                        for mn in (jig_detail.no_of_model_cases or []):
                            jig_detail.model_images[mn] = imgs
                    else:
                        jig_detail.model_images = {mn: imgs for mn in (jig_detail.no_of_model_cases or [])}
                    tray_cap = getattr(mmc, 'tray_capacity', 0) or 0
                    ver = 'No Version'
                    if getattr(mmc, 'version', None):
                        ver = getattr(mmc.version, 'version_internal', None) or getattr(mmc.version, 'version_name', 'No Version')
                    jig_detail.unique_versions = [ver]
                    jig_detail.unique_vendors = ['No Vendor']
                    jig_detail.unique_locations = ['No Location']
                    jig_detail.unique_tray_types = [getattr(mmc, 'tray_type', 'No Tray Type') or 'No Tray Type']
                    jig_detail.unique_tray_capacities = [tray_cap]
                    if tray_cap > 0 and getattr(jig_detail, 'total_cases_loaded', 0):
                        jig_detail.calculated_no_of_trays = math.ceil(jig_detail.total_cases_loaded / tray_cap)
                        jig_detail.primary_tray_capacity = tray_cap
                    else:
                        jig_detail.calculated_no_of_trays = 0
                        jig_detail.primary_tray_capacity = 0
                    print(f"   ✅ MMC direct fallback applied via batch_id={jig_batch}")
                    return
            except Exception as e:
                print(f"   ⚠️ MMC direct fallback error: {e}")
        for attr in ('unique_versions', 'unique_vendors', 'unique_locations',
                     'unique_tray_types', 'unique_tray_capacities'):
            if not hasattr(jig_detail, attr):
                setattr(jig_detail, attr, [])
        if not hasattr(jig_detail, 'calculated_no_of_trays'):
            jig_detail.calculated_no_of_trays = 0
        if not hasattr(jig_detail, 'primary_tray_capacity'):
            jig_detail.primary_tray_capacity = 0
        if not getattr(jig_detail, 'model_images', None):
            jig_detail.model_images = {}

    def get_dynamic_tray_capacity(self, tray_type_name):
        """
        Get tray capacity with custom override for Inprocess Inspection.
        For Normal tray type, use custom capacity from InprocessInspectionTrayCapacity.
        For other tray types (like Jumbo), use ModelMaster capacity.
        """
        try:
            # First try to get custom capacity for this tray type
            custom_capacity = InprocessInspectionTrayCapacity.objects.filter(
                tray_type__tray_type=tray_type_name,
                is_active=True
            ).first()
            
            if custom_capacity:
                return custom_capacity.custom_capacity
            
            # Fallback to ModelMaster tray capacity
            from modelmasterapp.models import TrayType
            tray_type = TrayType.objects.filter(tray_type=tray_type_name).first()
            if tray_type:
                return tray_type.tray_capacity
                
            # Default fallback
            return 0
            
        except Exception as e:
            print(f"⚠️ Error getting dynamic tray capacity: {e}")
            return 0

    def _apply_mmc_direct_fallback(self, jig_detail):
        """
        Fallback: use JigCompleted.batch_id to get ModelMasterCreation directly.
        Preserves plating_color/polish_finish/tray data already set from models_data.
        Only fills in aux attrs (unique_*, calculated_no_of_trays, model_images).
        """
        jig_batch = getattr(jig_detail, 'batch_id', None)
        if jig_batch:
            try:
                mmc = ModelMasterCreation.objects.filter(
                    batch_id=jig_batch
                ).prefetch_related('images').select_related('version', 'model_stock_no').first()
                if mmc:
                    # Get images from ModelMasterCreation.images
                    imgs = [img.master_image.url for img in mmc.images.all() if img.master_image]
                    if not imgs:
                        imgs = [static('assets/images/imagePlaceholder.jpg')]
                    
                    # Update model_images dict
                    if isinstance(getattr(jig_detail, 'model_images', None), dict):
                        for mn in (jig_detail.no_of_model_cases or []):
                            jig_detail.model_images[mn] = imgs
                    else:
                        jig_detail.model_images = {mn: imgs for mn in (jig_detail.no_of_model_cases or [])}
                    
                    # Set auxiliary attrs without overwriting plating_color/tray/polish
                    tray_cap = getattr(mmc, 'tray_capacity', 0) or 0
                    ver = 'No Version'
                    if getattr(mmc, 'version', None):
                        ver = getattr(mmc.version, 'version_internal', None) or getattr(mmc.version, 'version_name', 'No Version')
                    jig_detail.unique_versions = [ver]
                    jig_detail.unique_vendors = ['No Vendor']
                    jig_detail.unique_locations = ['No Location']
                    jig_detail.unique_tray_types = [getattr(mmc, 'tray_type', 'No Tray Type') or 'No Tray Type']
                    jig_detail.unique_tray_capacities = [tray_cap]
                    if tray_cap > 0 and getattr(jig_detail, 'total_cases_loaded', 0):
                        jig_detail.calculated_no_of_trays = math.ceil(jig_detail.total_cases_loaded / tray_cap)
                        jig_detail.primary_tray_capacity = tray_cap
                    else:
                        jig_detail.calculated_no_of_trays = 0
                        jig_detail.primary_tray_capacity = 0
                    print(f"   ✅ MMC direct fallback applied via batch_id={jig_batch}")
                    return
            except Exception as e:
                print(f"   ⚠️ MMC direct fallback error: {e}")
        # Absolute last resort — only set attrs not already present
        for attr in ('unique_versions', 'unique_vendors', 'unique_locations',
                     'unique_tray_types', 'unique_tray_capacities'):
            if not hasattr(jig_detail, attr):
                setattr(jig_detail, attr, [])
        if not hasattr(jig_detail, 'calculated_no_of_trays'):
            jig_detail.calculated_no_of_trays = 0
        if not hasattr(jig_detail, 'primary_tray_capacity'):
            jig_detail.primary_tray_capacity = 0
        if not getattr(jig_detail, 'model_images', None):
            jig_detail.model_images = {}

    def get_batch_data(self, batch_id, batch_model_class):
        """
        Get batch data for single model case from either ModelMasterCreation or RecoveryMasterCreation
        Updated to handle both model types (copied from JigCompletedTable)
        """
        try:
            print(f"🔍 Getting batch data from {batch_model_class.__name__} for batch_id: {batch_id}")
            
            model_master = batch_model_class.objects.select_related(
                'version', 
                'model_stock_no', 
                'model_stock_no__tray_type', 
                'location'
            ).prefetch_related(
                'model_stock_no__images',
                'images'
            ).get(id=batch_id)
            
            # Get model images — prefer ModelMasterCreation.images, fall back to model_stock_no.images
            images = []
            for img in model_master.images.all():
                if img.master_image:
                    images.append(img.master_image.url)
            if not images and model_master.model_stock_no:
                for img in model_master.model_stock_no.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            
            # Safe version access
            version_name = "No Version"
            if hasattr(model_master, 'version') and model_master.version:
                version_name = getattr(model_master.version, 'version_name', None) or getattr(model_master.version, 'version_internal', 'No Version')
            
            # plating_color is a plain CharField on ModelMasterCreation
            plating_color = getattr(model_master, 'plating_color', None) or "No Plating Color"
            
            # Fetch tray info — tray_type is a plain CharField on ModelMasterCreation
            tray_type = getattr(model_master, 'tray_type', None) or ""
            tray_capacity = getattr(model_master, 'tray_capacity', None) or self.get_dynamic_tray_capacity(tray_type) or 0
            
            return {
                'batch_id': batch_id,
                'model_no': model_master.model_stock_no.model_no if model_master.model_stock_no else None,
                'version_name': version_name,
                'plating_color': plating_color,
                'polish_finish': getattr(model_master, 'polish_finish', None) or "No Polish Finish",
                'plating_stk_no': getattr(model_master, 'plating_stk_no', None) or "No Plating Stock No",
                'polishing_stk_no': getattr(model_master, 'polishing_stk_no', None) or "No Polishing Stock No",
                'location_name': model_master.location.location_name if hasattr(model_master, 'location') and model_master.location else "No Location",
                'tray_type': tray_type,
                'tray_capacity': tray_capacity,
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
            return self.get_default_batch_data()

    def set_default_values(self, jig_detail):
        """
        Set default values when no data is found
        """
        defaults = self.get_default_batch_data()
        for key, value in defaults.items():
            setattr(jig_detail, key, value)
        
        # Additional defaults for InprocessInspectionCompleteView
        jig_detail.model_colors = {}
        jig_detail.model_images = {}
        jig_detail.unique_versions = []
        jig_detail.unique_vendors = []
        jig_detail.unique_locations = []
        jig_detail.unique_tray_types = []
        jig_detail.unique_tray_capacities = []
        jig_detail.calculated_no_of_trays = 0
        jig_detail.primary_tray_capacity = 0
    
    def get_default_batch_data(self):
        """
        Get default values for when no model data is found
        (Copied from JigCompletedTable)
        """
        return {
            'batch_id': None,
            'model_no': None,
            'version_name': "No Version",
            'plating_color': "",
            'polish_finish': "",
            'plating_stk_no': "No Plating Stock No",
            'polishing_stk_no': "No Polishing Stock No",
            'location_name': "No Location",
            'tray_type': "",
            'tray_capacity': 0,
            'vendor_internal': "No Vendor",
            'calculated_no_of_trays': 0,
            'model_images': [static('assets/images/imagePlaceholder.jpg')],
            'source_model': 'Unknown',
            'batch_model_type': 'Unknown'
        }

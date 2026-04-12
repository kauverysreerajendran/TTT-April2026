from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from modelmasterapp.models import *
from django.db.models import OuterRef, Subquery, Exists, F, TextField
from django.db.models.functions import Cast
from django.db.models.fields.json import KeyTextTransform
from django.core.paginator import Paginator
import math
import json
import re
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.http import require_GET
from Jig_Loading.models import *
from Jig_Unloading.models import *
from Recovery_DP.models import *
from Inprocess_Inspection.models import InprocessInspectionTrayCapacity

class Jig_Unloading_MainTable(TemplateView):
    template_name = "Jig_Unloading/Jig_Unloading_Main.html"

    def get_dynamic_tray_capacity(self, tray_type_name):
        """
        Get tray capacity based on tray type name.
        Rules (per workflow spec):
        - Normal: 20
        - Jumbo:  12
        - Others: DB lookup fallback
        """
        try:
            # Workflow-spec hardcoded values
            if tray_type_name == 'Normal':
                return 20
            elif tray_type_name == 'Jumbo':
                return 12

            # Fallback: try custom capacity override table
            custom_capacity = InprocessInspectionTrayCapacity.objects.filter(
                tray_type__tray_type=tray_type_name,
                is_active=True
            ).first()

            if custom_capacity:
                return custom_capacity.custom_capacity

            # Fallback to TrayType table
            tray_type = TrayType.objects.filter(tray_type=tray_type_name).first()
            if tray_type:
                return tray_type.tray_capacity

            # Default fallback
            return 0

        except Exception as e:
            print(f"⚠️ Error getting dynamic tray capacity: {e}")
            return 0

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

    def get_lot_specific_data(self, lot_id, model_no):
        """Get lot-specific data from either TotalStockModel or RecoveryStockModel"""
        
        print(f"🔍 get_lot_specific_data called for lot_id: {lot_id}, model_no: {model_no}")
        
        # STEP 0: JigCompleted → batch_id → ModelMasterCreation (for Jig Loading lots not in TotalStockModel)
        _jc = JigCompleted.objects.filter(lot_id=lot_id).only('batch_id').first()
        if _jc and _jc.batch_id:
            _mmc = ModelMasterCreation.objects.select_related(
                'version', 'model_stock_no', 'model_stock_no__tray_type', 'location'
            ).filter(batch_id=_jc.batch_id).first()
            if _mmc:
                _version_name = "No Version"
                if hasattr(_mmc, 'version') and _mmc.version:
                    _version_name = getattr(_mmc.version, 'version_internal', None) or getattr(_mmc.version, 'version_name', 'No Version')
                _tray_type_str = _mmc.model_stock_no.tray_type.tray_type if _mmc.model_stock_no and _mmc.model_stock_no.tray_type else "No Tray Type"
                print(f"✅ get_lot_specific_data via JigCompleted.batch_id={_jc.batch_id}: tray={_tray_type_str}")
                return {
                    'version': _version_name,
                    'vendor': getattr(_mmc, 'vendor_internal', None) or "No Vendor",
                    'location': _mmc.location.location_name if hasattr(_mmc, 'location') and _mmc.location else "No Location",
                    'tray_type': _tray_type_str,
                    'tray_capacity': self.get_dynamic_tray_capacity(_tray_type_str) if _tray_type_str != "No Tray Type" else 0,
                    'plating_stk_no': getattr(_mmc, 'plating_stk_no', None) or "No Plating Stock No",
                    'polishing_stk_no': getattr(_mmc, 'polishing_stk_no', None) or "No Polishing Stock No",
                    'plating_color': getattr(_mmc, 'plating_color', None) or "N/A",
                    'source': 'JigCompleted→ModelMasterCreation'
                }

        # STEP 1: Get stock model data using the proven method
        stock_model, is_recovery, batch_model_class = self.get_stock_model_data(lot_id)
        
        if not stock_model or not stock_model.batch_id:
            print(f"❌ No stock model or batch_id found for lot_id: {lot_id}")
            return None
            
        batch_id = stock_model.batch_id.id
        print(f"✅ Found stock model: {'Recovery' if is_recovery else 'Total'}Stock -> batch_id: {batch_id}")
        
        # STEP 2: Get MasterCreation data using batch_id and correct model class
        try:
            print(f"🏭 Looking up {batch_model_class.__name__} for batch_id: {batch_id}")
            
            master_creation = batch_model_class.objects.select_related(
                'version', 'model_stock_no', 'model_stock_no__tray_type', 'location'
            ).filter(id=batch_id).first()
            
            if master_creation:
                print(f"🎯 Found {batch_model_class.__name__} for batch_id: {batch_id}")
                print(f"🏭 Details: plating_stk_no={getattr(master_creation, 'plating_stk_no', None)}, polishing_stk_no={getattr(master_creation, 'polishing_stk_no', None)}, version={getattr(master_creation, 'version', None)}")
                
                # Safe version access - prioritize version_internal
                version_name = "No Version"
                if hasattr(master_creation, 'version') and master_creation.version:
                    version_name = getattr(master_creation.version, 'version_internal', None) or getattr(master_creation.version, 'version_name', 'No Version')
                
                return {
                    'version': version_name,
                    'vendor': getattr(master_creation, 'vendor_internal', None) or "No Vendor",
                    'location': master_creation.location.location_name if hasattr(master_creation, 'location') and master_creation.location else "No Location",
                    'tray_type': master_creation.model_stock_no.tray_type.tray_type if master_creation.model_stock_no and master_creation.model_stock_no.tray_type else "No Tray Type",
                    'tray_capacity': self.get_dynamic_tray_capacity(master_creation.model_stock_no.tray_type.tray_type) if master_creation.model_stock_no and master_creation.model_stock_no.tray_type else 0,
                    'plating_stk_no': getattr(master_creation, 'plating_stk_no', None) or "No Plating Stock No",
                    'polishing_stk_no': getattr(master_creation, 'polishing_stk_no', None) or "No Polishing Stock No",
                    'plating_color': getattr(master_creation, 'plating_color', None) or "N/A",
                    'source': batch_model_class.__name__
                }
            else:
                print(f"❌ No {batch_model_class.__name__} found for batch_id: {batch_id}")
                
        except Exception as e:
            print(f"❌ Error getting {batch_model_class.__name__} data: {e}")
        
        print(f"❌ No lot-specific data found for lot_id: {lot_id}")
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Zone 1: Only IPS color should be routed here
        # Get only IPS plating color for Zone 1
        allowed_colors = Plating_Color.objects.filter(
            plating_color='IPS'
        ).values_list('plating_color', flat=True)
        
        print(f"🔍 Zone 1 - Allowed colors: {list(allowed_colors)}")

        # Get all plating colors and strip "IP-" prefix from stored values for matching
        allowed_colors_list = list(allowed_colors)
        
        # Build list of patterns to match (handle both "IPS" and "IP-IPS" formats)
        plating_patterns = allowed_colors_list + [f"IP-{color}" for color in allowed_colors_list]
        
        # Create polish_finish subquery for annotation
        polish_finish_subquery = TotalStockModel.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('polish_finish__polish_finish')[:1]
        
        jig_unload = JigCompleted.objects.select_related('bath_numbers').annotate(
            plating_color_cast=KeyTextTransform('plating_color', 'draft_data'),
            polish_finish_name=Subquery(polish_finish_subquery)
        ).filter(
            plating_color_cast__in=plating_patterns,
            last_process_module='Inprocess Inspection'
        ).exclude(
            last_process_module='Jig Unloading'
        ).order_by('-IP_loaded_date_time')
        
        # ENHANCED FILTER: Also get jigs where plating_color is not in draft_data 
        # but can be determined from TotalStockModel or RecoveryStockModel
        jigs_without_plating_in_draft = JigCompleted.objects.select_related('bath_numbers').annotate(
            plating_color_cast=KeyTextTransform('plating_color', 'draft_data'),
            polish_finish_name=Subquery(polish_finish_subquery)
        ).filter(
            plating_color_cast__isnull=True,  # draft_data has no plating_color
            last_process_module='Inprocess Inspection'
        ).order_by('-IP_loaded_date_time')
        
        # Get lot_ids from jigs without plating color in draft_data
        lot_ids_without_plating = list(jigs_without_plating_in_draft.values_list('lot_id', flat=True))
        
        if lot_ids_without_plating:
            # Get plating colors from TotalStockModel for these lot_ids
            total_stock_colors = TotalStockModel.objects.filter(
                lot_id__in=lot_ids_without_plating,
                plating_color__plating_color__in=allowed_colors_list
            ).values_list('lot_id', 'plating_color__plating_color')
            
            # Get plating colors from RecoveryStockModel for these lot_ids
            try:
                from Recovery_DP.models import RecoveryStockModel
                recovery_stock_colors = RecoveryStockModel.objects.filter(
                    lot_id__in=lot_ids_without_plating,
                    plating_color__plating_color__in=allowed_colors_list
                ).values_list('lot_id', 'plating_color__plating_color')
            except:
                recovery_stock_colors = []
            
            # Combine all valid lot_ids that have matching plating colors
            valid_lot_ids_for_zone1 = set()
            for lot_id, color in total_stock_colors:
                if color in allowed_colors_list:
                    valid_lot_ids_for_zone1.add(lot_id)
                    
            for lot_id, color in recovery_stock_colors:
                if color in allowed_colors_list:
                    valid_lot_ids_for_zone1.add(lot_id)

            # ✅ FIX: JigCompleted fallback — for Jig Loading lot IDs not in TotalStock/RecoveryStock.
            # JigCompleted.lot_id ≠ TotalStockModel.lot_id (Jig Loading creates its own lot IDs).
            # Use draft_data['batch_id'] → TotalStockModel.batch_id FK → plating_color check.
            batch_ids_to_check = []
            jig_lot_to_batch = {}
            for jig in jigs_without_plating_in_draft:
                if jig.lot_id not in valid_lot_ids_for_zone1:
                    batch_id_str = (jig.draft_data or {}).get('batch_id')
                    if batch_id_str:
                        batch_ids_to_check.append(batch_id_str)
                        jig_lot_to_batch[jig.lot_id] = batch_id_str

            if batch_ids_to_check:
                ips_batch_ids = set(
                    TotalStockModel.objects.filter(
                        batch_id__batch_id__in=batch_ids_to_check,
                        plating_color__plating_color__in=allowed_colors_list
                    ).values_list('batch_id__batch_id', flat=True)
                )
                for jig_lot_id, batch_id_str in jig_lot_to_batch.items():
                    if batch_id_str in ips_batch_ids:
                        valid_lot_ids_for_zone1.add(jig_lot_id)
                        print(f"✅ Zone1 JigCompleted fallback: {jig_lot_id} -> {batch_id_str} -> IPS")

            # Get additional jigs that match by lot_id even if draft_data lacks plating_color
            additional_jigs = jigs_without_plating_in_draft.filter(lot_id__in=valid_lot_ids_for_zone1)
            
            # Combine both sets: jigs with plating_color in draft_data + jigs with valid colors from TotalStock/Recovery
            jig_unload = jig_unload.union(additional_jigs, all=False)
        
        # 🧠 SMART FILTER: Remove jigs with ALL lot_ids unloaded
        jig_unload = self.filter_fully_unloaded_jigs(jig_unload)
        
        # Fetch all Bath Numbers for dropdown
        bath_numbers = BathNumbers.objects.all().order_by('bath_number')
        
        # Get all unique model numbers from all jig_unload for bulk processing
        all_model_numbers = set()
        all_lot_ids = set()
        all_batch_ids = set()  # For Jig Loading batch_id → images fallback
        for jig_detail in jig_unload:
            if jig_detail.no_of_model_cases:
                _raw_mc = jig_detail.no_of_model_cases
                if isinstance(_raw_mc, str):
                    try:
                        import json
                        _parsed = json.loads(_raw_mc)
                        if isinstance(_parsed, list):
                            _raw_mc = _parsed
                    except Exception:
                        pass
                
                if isinstance(_raw_mc, list):
                    all_model_numbers.update([str(m) for m in _raw_mc])
                elif isinstance(_raw_mc, str):
                    # Parse comma-separated 'plating_stk_no:qty' format e.g. '1805NAK02:14,1805NAR02:13'
                    for _item in _raw_mc.split(','):
                        _mn = _item.split(':')[0].strip()
                        if _mn:
                            all_model_numbers.add(_mn)
            elif getattr(jig_detail, 'plating_stock_num', None):
                # Single-model jig: no_of_model_cases stored as '' but plating_stock_num has the model
                all_model_numbers.add(str(jig_detail.plating_stock_num).strip())
            # Collect lot_ids for dual-table lookup
            if hasattr(jig_detail, 'lot_id_quantities') and jig_detail.lot_id_quantities:
                all_lot_ids.update(jig_detail.lot_id_quantities.keys())
            # Collect batch_ids for Jig Loading image fallback path
            _jd_batch = getattr(jig_detail, 'batch_id', None)
            if _jd_batch:
                all_batch_ids.add(str(_jd_batch).strip())
                
        # Define color palette for model circles
        color_palette = [
            "#e74c3c",  # Red
            "#f1c40f",  # Yellow
            "#2ecc71",  # Green
            "#3498db",  # Blue
            "#9b59b6",  # Purple
            "#e67e22",  # Orange
            "#1abc9c",  # Turquoise
            "#34495e",  # Dark Blue-Gray
            "#f39c12",  # Dark Orange
            "#d35400",  # Dark Orange
            "#c0392b",  # Dark Red
            "#8e44ad",  # Dark Purple
            "#2980b9",  # Dark Blue
            "#27ae60",  # Dark Green
            "#16a085"   # Dark Turquoise
        ]
        
        # Create a global color mapping for all unique model numbers
        global_model_colors = {}
        sorted_model_numbers = sorted(list(all_model_numbers))
        print(f"🎨 Creating color mapping for models: {sorted_model_numbers}")

        for idx, model_no in enumerate(sorted_model_numbers):
            color_index = idx % len(color_palette)
            assigned_color = color_palette[color_index]
            # Ensure model_no is always stored as a complete string
            model_key = str(model_no)  # Force string conversion
            global_model_colors[model_key] = assigned_color
            print(f"🎨 Assigned {assigned_color} to model '{model_key}'")

        # 🚀 ENHANCED: Dual-table model data fetching (TotalStock + Recovery)
        model_data_map = {}
        model_images_map = {}
        
        if all_model_numbers:
            # Build a set of numeric model_nos to match ModelMasterCreation.model_stock_no__model_no
            # all_model_numbers may contain plating_stk_nos like '1805SAD02' — extract numeric prefix too
            numeric_model_nos = set()
            for _mn in all_model_numbers:
                _match = re.match(r'^(\d+)', str(_mn))
                numeric_model_nos.add(_match.group(1) if _match else str(_mn))

            # First, try ModelMasterCreation (linked to TotalStockModel)
            model_master_creations = ModelMasterCreation.objects.filter(
                model_stock_no__model_no__in=numeric_model_nos
            ).select_related(
                'version', 
                'model_stock_no', 
                'model_stock_no__tray_type', 
                'location'
            ).values(
                'model_stock_no__model_no', 
                'version__version_name',
                'vendor_internal',
                'location__location_name',
                'model_stock_no__tray_type__tray_type',
                'model_stock_no__tray_capacity',
                'plating_stk_no',
                'polishing_stk_no',
            ).distinct()
            
            # Store found model numbers to avoid duplicates
            found_model_numbers = set()
            
            for mmc in model_master_creations:
                model_no = mmc['model_stock_no__model_no']
                found_model_numbers.add(model_no)
                
                if model_no not in model_data_map:
                    tray_type_name = mmc['model_stock_no__tray_type__tray_type'] or "No Tray Type"
                    dynamic_capacity = self.get_dynamic_tray_capacity(tray_type_name) if tray_type_name != "No Tray Type" else 0
                    model_data_map[model_no] = {
                        'version': mmc['version__version_name'] or "No Version",
                        'vendor': mmc['vendor_internal'] or "No Vendor",
                        'location': mmc['location__location_name'] or "No Location",
                        'tray_type': tray_type_name,
                        'tray_capacity': dynamic_capacity,
                        'plating_stk_no': mmc['plating_stk_no'] or "No Plating Stock No",
                        'polishing_stk_no': mmc['polishing_stk_no'] or "No Polishing Stock No",
                        'plating_color': "N/A",
                        'source': 'ModelMasterCreation'
                    }

            # 🔥 NEW: For missing models, try RecoveryMasterCreation
            missing_model_numbers = numeric_model_nos - found_model_numbers
            
            if missing_model_numbers:
                print(f"🔍 Checking RecoveryMasterCreation for missing models: {missing_model_numbers}")
                
                recovery_master_creations = RecoveryMasterCreation.objects.filter(
                    model_stock_no__model_no__in=missing_model_numbers
                ).select_related(
                    'version', 
                    'model_stock_no', 
                    'model_stock_no__tray_type', 
                    'location'
                ).values(
                    'model_stock_no__model_no', 
                    'version__version_name',
                    'vendor_internal',
                    'location__location_name',
                    'model_stock_no__tray_type__tray_type',
                    'model_stock_no__tray_capacity',
                    'plating_stk_no',
                    'polishing_stk_no',
                ).distinct()
                
                for rmc in recovery_master_creations:
                    model_no = rmc['model_stock_no__model_no']
                    
                    if model_no not in model_data_map:
                        tray_type_name = rmc['model_stock_no__tray_type__tray_type'] or "No Tray Type"
                        dynamic_capacity = self.get_dynamic_tray_capacity(tray_type_name) if tray_type_name != "No Tray Type" else 0
                        model_data_map[model_no] = {
                            'version': rmc['version__version_name'] or "No Version",
                            'vendor': rmc['vendor_internal'] or "No Vendor", 
                            'location': rmc['location__location_name'] or "No Location",
                            'tray_type': tray_type_name,
                            'tray_capacity': dynamic_capacity,
                            'plating_stk_no': rmc['plating_stk_no'] or "No Plating Stock No",
                            'polishing_stk_no': rmc['polishing_stk_no'] or "No Polishing Stock No",
                            'plating_color': "N/A",
                            'source': 'RecoveryMasterCreation'
                        }
                        print(f"✅ Found {model_no} in RecoveryMasterCreation")

            # SEPARATE QUERY TO GET PLATING COLORS - ENHANCED FOR DUAL SOURCE
            print("=== DEBUGGING PLATING COLOR FIELD ===")
            try:
                # Try ModelMasterCreation first
                mmc_sample = ModelMasterCreation.objects.first()
                if mmc_sample and hasattr(mmc_sample, 'plating_color'):
                    if isinstance(mmc_sample.plating_color, str):
                        # Direct string field - try both tables
                        plating_colors = ModelMasterCreation.objects.filter(
                            model_stock_no__model_no__in=all_model_numbers
                        ).values('model_stock_no__model_no', 'plating_color').distinct()
                        
                        for pc in plating_colors:
                            model_no = pc['model_stock_no__model_no']
                            if model_no in model_data_map:
                                model_data_map[model_no]['plating_color'] = pc['plating_color'] or "N/A"
                        
                        # Also try RecoveryMasterCreation for plating colors
                        recovery_plating_colors = RecoveryMasterCreation.objects.filter(
                            model_stock_no__model_no__in=missing_model_numbers
                        ).values('model_stock_no__model_no', 'plating_color').distinct()
                        
                        for pc in recovery_plating_colors:
                            model_no = pc['model_stock_no__model_no']
                            if model_no in model_data_map:
                                model_data_map[model_no]['plating_color'] = pc['plating_color'] or "N/A"
                    
                    elif hasattr(mmc_sample.plating_color, '_meta'):
                        # Related object field
                        related_model = type(mmc_sample.plating_color)
                        related_fields = [f.name for f in related_model._meta.get_fields()]
                        
                        color_field = None
                        for field_name in ['name', 'color_name', 'color', 'title']:
                            if field_name in related_fields:
                                color_field = field_name
                                break
                        
                        if color_field:
                            # ModelMasterCreation plating colors
                            plating_colors = ModelMasterCreation.objects.filter(
                                model_stock_no__model_no__in=all_model_numbers
                            ).select_related('plating_color').values(
                                'model_stock_no__model_no', 
                                f'plating_color__{color_field}'
                            ).distinct()
                            
                            for pc in plating_colors:
                                model_no = pc['model_stock_no__model_no']
                                if model_no in model_data_map:
                                    model_data_map[model_no]['plating_color'] = pc[f'plating_color__{color_field}'] or "N/A"
                            
                            # RecoveryMasterCreation plating colors
                            recovery_plating_colors = RecoveryMasterCreation.objects.filter(
                                model_stock_no__model_no__in=missing_model_numbers
                            ).select_related('plating_color').values(
                                'model_stock_no__model_no', 
                                f'plating_color__{color_field}'
                            ).distinct()
                            
                            for pc in recovery_plating_colors:
                                model_no = pc['model_stock_no__model_no']
                                if model_no in model_data_map:
                                    model_data_map[model_no]['plating_color'] = pc[f'plating_color__{color_field}'] or "N/A"
                
            except Exception as e:
                print(f"Error debugging plating color: {e}")

            # Fetch images for each model
            print(f"🔍 DEBUG: Looking up images for models: {all_model_numbers}")
            
            # ✅ FIX: Create clean model mapping for image lookup (like Inprocess Inspection)
            clean_model_mapping = {}
            for model_no in all_model_numbers:
                clean_model_no = model_no
                # Extract just the numeric part (e.g., "1805SAD02" -> "1805")
                match = re.match(r'^(\d+)', str(model_no))
                if match:
                    clean_model_no = match.group(1)
                clean_model_mapping[model_no] = clean_model_no
                print(f"🔍 Model mapping: {model_no} -> {clean_model_no}")
            
            # Get unique clean model numbers for lookup
            clean_model_numbers = set(clean_model_mapping.values())
            
            model_masters = ModelMaster.objects.filter(
                model_no__in=clean_model_numbers
            ).prefetch_related('images').order_by('model_no', 'plating_stk_no')

            # Create lookup map: deduplicate by model_no, prefer the record that has images
            # Also build a direct plating_stk_no map for exact-match lookup
            clean_model_images = {}
            plating_stk_images = {}  # plating_stk_no -> image data
            seen_clean = set()
            for model_master in model_masters:
                images = list(model_master.images.all())
                img_urls_mm = [img.master_image.url for img in images if img.master_image]

                # Always record by plating_stk_no (exact match for fallback)
                if model_master.plating_stk_no and img_urls_mm:
                    plating_stk_images[model_master.plating_stk_no] = {
                        'images': img_urls_mm, 'first_image': img_urls_mm[0]
                    }

                # For clean model_no key: only store if has images, or first occurrence
                mn = model_master.model_no
                if mn not in clean_model_images:
                    if img_urls_mm:
                        clean_model_images[mn] = {'images': img_urls_mm, 'first_image': img_urls_mm[0]}
                    seen_clean.add(mn)
                elif not clean_model_images[mn]['images'] and img_urls_mm:
                    # Upgrade to a record that actually has images
                    clean_model_images[mn] = {'images': img_urls_mm, 'first_image': img_urls_mm[0]}
            
            # Map back to original model numbers
            for original_model, clean_model in clean_model_mapping.items():
                # First: exact plating_stk_no match (most specific)
                if original_model in plating_stk_images:
                    model_images_map[original_model] = plating_stk_images[original_model]
                    print(f"📸 Mapped {original_model} via exact plating_stk_no -> {len(plating_stk_images[original_model]['images'])} images")
                elif clean_model in clean_model_images:
                    model_images_map[original_model] = clean_model_images[clean_model]
                    print(f"📸 Mapped {original_model} -> {clean_model} -> {len(clean_model_images[clean_model]['images'])} images")
                else:
                    model_images_map[original_model] = {'images': [], 'first_image': None}
                    print(f"❌ No images found for {original_model} (clean: {clean_model})")

            # Fallback: for models still missing images, scan ModelMaster by plating_stk_no
            missing_images = {m for m, v in model_images_map.items() if not v.get('images')}
            if missing_images:
                print(f"🔍 Searching plating_stk_no variants for models without images: {missing_images}")
                # Also try ModelMasterCreation.images directly (may differ from ModelMaster.images)
                for orig_no in list(missing_images):
                    _mmc_direct = ModelMasterCreation.objects.filter(
                        plating_stk_no=orig_no
                    ).prefetch_related('images').first()
                    if _mmc_direct and _mmc_direct.images.exists():
                        _mmc_urls = [img.master_image.url for img in _mmc_direct.images.all() if img.master_image]
                        if _mmc_urls:
                            model_images_map[orig_no] = {'images': _mmc_urls, 'first_image': _mmc_urls[0]}
                            missing_images.discard(orig_no)
                            print(f"📸 MMC direct images: '{orig_no}' -> {len(_mmc_urls)} images")
                # Scan ModelMaster by plating_stk_no for any remaining
                if missing_images:
                    plating_candidates = ModelMaster.objects.filter(
                        plating_stk_no__isnull=False
                    ).exclude(plating_stk_no='').prefetch_related('images')
                    for mm in plating_candidates:
                        if not mm.plating_stk_no:
                            continue
                        for orig_no in list(missing_images):
                            _numeric = re.match(r'^(\d+)', str(orig_no))
                            _numeric_no = _numeric.group(1) if _numeric else None
                            # Match: exact plating_stk_no equality OR plating_stk_no starts with numeric prefix
                            if (mm.plating_stk_no == orig_no or
                                    (_numeric_no and str(mm.plating_stk_no).startswith(_numeric_no))) and mm.images.exists():
                                img_list = list(mm.images.all())
                                img_urls_fb = [img.master_image.url for img in img_list if img.master_image]
                                if img_urls_fb:
                                    model_images_map[orig_no] = {'images': img_urls_fb, 'first_image': img_urls_fb[0]}
                                    missing_images.discard(orig_no)
                                    print(f"📸 Fallback: mapped '{orig_no}' via plating_stk_no '{mm.plating_stk_no}'")
                                    break

        # Build batch_id → ModelMasterCreation → images map
        # Checks ModelMasterCreation.images first (direct), then ModelMaster.images via FK
        # This is the reliable fallback for Jig Loading lots (which have their own lot_id scheme)
        batch_images_map = {}
        batch_tray_map = {}          # batch_id → (tray_type_str, tray_capacity_int)
        batch_polish_finish_map = {} # batch_id → polish_finish_str
        if all_batch_ids:
            for _bmmc in ModelMasterCreation.objects.filter(
                batch_id__in=all_batch_ids
            ).select_related('model_stock_no').prefetch_related('images', 'model_stock_no__images'):
                if not _bmmc.batch_id:
                    continue
                # Capture tray and polish_finish (plain CharField/IntegerField on MMC)
                if _bmmc.tray_type:
                    _tc = _bmmc.tray_capacity if _bmmc.tray_capacity else self.get_dynamic_tray_capacity(_bmmc.tray_type)
                    batch_tray_map[_bmmc.batch_id] = (_bmmc.tray_type, _tc)
                if _bmmc.polish_finish:
                    batch_polish_finish_map[_bmmc.batch_id] = _bmmc.polish_finish
                # Prefer ModelMasterCreation.images directly
                _bimgs = [img.master_image.url for img in _bmmc.images.all() if img.master_image]
                if not _bimgs and _bmmc.model_stock_no:
                    # Fall back to ModelMaster.images via FK
                    _bimgs = [img.master_image.url for img in _bmmc.model_stock_no.images.all() if img.master_image]
                if _bimgs:
                    batch_images_map[_bmmc.batch_id] = {'images': _bimgs, 'first_image': _bimgs[0]}
                    print(f"📦 batch_images: {_bmmc.batch_id} -> {len(_bimgs)} images")

        # Process each JigCompleted to attach all information
        for jig_detail in jig_unload:
            # Check if this lot_id already has unload data
            jig_detail.is_unloaded = JigUnload_TrayId.objects.filter(lot_id=jig_detail.lot_id).exists()
            
             # --- Tray Info Fallback Logic ---
            # Try to get tray_type and tray_capacity from lot-level, else fallback to model-level
            tray_type = None
            tray_capacity = None
            
            # 1. Try lot-level (from lot_id_quantities)
            if hasattr(jig_detail, 'lot_id_quantities') and jig_detail.lot_id_quantities:
                for lot_id in jig_detail.lot_id_quantities.keys():
                    lot_data = self.get_lot_specific_data(lot_id, None)
                    if lot_data and lot_data.get('tray_type') and lot_data.get('tray_type') != 'No Tray Type':
                        tray_type = lot_data['tray_type']
                    if lot_data and lot_data.get('tray_capacity') and lot_data.get('tray_capacity') > 0:
                        tray_capacity = lot_data['tray_capacity']
                    if tray_type and tray_capacity:
                        break
            
            # 2. Fallback to model-level (from first model in no_of_model_cases)
            if (not tray_type or not tray_capacity) and hasattr(jig_detail, 'no_of_model_cases') and jig_detail.no_of_model_cases:
                model_no = list(jig_detail.no_of_model_cases)[0]
                model_data = model_data_map.get(model_no)
                if model_data:
                    if not tray_type and model_data.get('tray_type') and model_data.get('tray_type') != 'No Tray Type':
                        tray_type = model_data['tray_type']
                    if not tray_capacity and model_data.get('tray_capacity') and model_data.get('tray_capacity') > 0:
                        tray_capacity = model_data['tray_capacity']
            
            # 3. Set on jig_detail for template
            jig_detail.tray_type = tray_type
            jig_detail.tray_capacity = tray_capacity
            # Fix tray_type from batch_tray_map if still missing
            if not jig_detail.tray_type or jig_detail.tray_type == 'No Tray Type':
                _jd_b1 = getattr(jig_detail, 'batch_id', None)
                if _jd_b1 and _jd_b1 in batch_tray_map:
                    _tt1, _tc1 = batch_tray_map[_jd_b1]
                    jig_detail.tray_type = _tt1
                    jig_detail.tray_capacity = self.get_dynamic_tray_capacity(_tt1)
            # Fix polish_finish_name for Jig Loading lots (not in TotalStockModel annotation)
            if not getattr(jig_detail, 'polish_finish_name', None):
                _jd_b1 = getattr(jig_detail, 'batch_id', None)
                if _jd_b1 and _jd_b1 in batch_polish_finish_map:
                    jig_detail.polish_finish_name = batch_polish_finish_map[_jd_b1]
            # Extract bath_number string from draft_data if bath_numbers FK is None
            # Explicitly resolve by FK ID so union() doesn't break lazy-load
            _bath_fk_id_z1 = getattr(jig_detail, 'bath_numbers_id', None)
            if _bath_fk_id_z1:
                _bn_row_z1 = BathNumbers.objects.filter(id=_bath_fk_id_z1).values('bath_number').first()
                jig_detail.bath_number = _bn_row_z1['bath_number'] if _bn_row_z1 else None
            else:
                _dd1 = getattr(jig_detail, 'draft_data', {}) or {}
                _bn_str1 = _dd1.get('bath_number') or _dd1.get('bath_numbers') or _dd1.get('nickel_bath_number') or _dd1.get('bath_no')
                jig_detail.bath_number = str(_bn_str1) if _bn_str1 else None

            # Fallback: if bath_number still None, try to find from another JigCompleted with same jig_id
            if not jig_detail.bath_number:
                _jig_id_z1 = getattr(jig_detail, 'jig_id', None)
                if _jig_id_z1:
                    _sibling_jc = JigCompleted.objects.filter(
                        jig_id=_jig_id_z1, bath_numbers__isnull=False
                    ).values('bath_numbers__bath_number').first()
                    if _sibling_jc:
                        jig_detail.bath_number = _sibling_jc['bath_numbers__bath_number']
            
            # *** NEW: Add helper properties for lot_id_quantities values ***
            if hasattr(jig_detail, 'lot_id_quantities') and jig_detail.lot_id_quantities:
                jig_detail.quantity_values = list(jig_detail.lot_id_quantities.values())
                jig_detail.quantity_values_str = ", ".join(map(str, jig_detail.lot_id_quantities.values()))
                jig_detail.total_quantity = sum(jig_detail.lot_id_quantities.values())
            else:
                jig_detail.quantity_values = []
                jig_detail.quantity_values_str = "0"
                jig_detail.total_quantity = 0
            
            # 🚀 ENHANCED: Dual-table lot_id to model mapping (using full plating_stk_no)
            lot_id_model_map = {}
            if getattr(jig_detail, 'lot_id_quantities', None):
                for lot_id in jig_detail.lot_id_quantities.keys():
                    plating_stk_no = None
                    
                    # Try TotalStockModel → batch_id → ModelMasterCreation first
                    tsm = TotalStockModel.objects.filter(lot_id=lot_id).first()
                    if tsm and tsm.batch_id:
                        mmc = ModelMasterCreation.objects.filter(id=tsm.batch_id.id).first()
                        if mmc:
                            plating_stk_no = getattr(mmc, 'plating_stk_no', None) or (mmc.model_stock_no.model_no if mmc.model_stock_no else None)
                            print(f"🎯 Found {lot_id} in ModelMasterCreation -> {plating_stk_no}")
                    
                    if not plating_stk_no:
                        # 🔥 NEW: Try RecoveryStockModel → batch_id → RecoveryMasterCreation
                        rsm = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
                        if rsm and rsm.batch_id:
                            rmc = RecoveryMasterCreation.objects.filter(id=rsm.batch_id.id).first()
                            if rmc:
                                plating_stk_no = getattr(rmc, 'plating_stk_no', None) or (rmc.model_stock_no.model_no if rmc.model_stock_no else None)
                                print(f"🔄 Found {lot_id} in RecoveryMasterCreation -> {plating_stk_no}")
                    
                    if not plating_stk_no:
                        # Existing fallback logic
                        tray = TrayId.objects.filter(lot_id=lot_id).select_related('batch_id__model_stock_no').first()
                        if tray and tray.batch_id:
                            plating_stk_no = getattr(tray.batch_id, 'plating_stk_no', None) or (tray.batch_id.model_stock_no.model_no if tray.batch_id.model_stock_no else None)
                            print(f"📦 Found {lot_id} in TrayId -> {plating_stk_no}")
                        else:
                            # Final fallback - use model_no from stock models
                            if tsm and hasattr(tsm, 'model_stock_no') and tsm.model_stock_no:
                                plating_stk_no = tsm.model_stock_no.model_no
                                print(f"📊 Found {lot_id} in TotalStockModel (fallback) -> {plating_stk_no}")
                            elif rsm and hasattr(rsm, 'model_stock_no') and rsm.model_stock_no:
                                plating_stk_no = rsm.model_stock_no.model_no
                                print(f"♻️ Found {lot_id} in RecoveryStockModel (fallback) -> {plating_stk_no}")
                    
                    lot_id_model_map[lot_id] = plating_stk_no
            
            print(f"DEBUG: {jig_detail.lot_id} lot_id_model_map = {lot_id_model_map}")
            jig_detail.lot_id_model_map = lot_id_model_map
            
            # Also check for individual model lot_ids if they exist
            if hasattr(jig_detail, 'lot_id_list') and jig_detail.lot_id_list:
                unloaded_model_lot_ids = set(
                    JigUnload_TrayId.objects.filter(
                        lot_id__in=jig_detail.lot_id_list
                    ).values_list('lot_id', flat=True)
                )
                jig_detail.unloaded_model_lot_ids = list(unloaded_model_lot_ids)
            else:
                jig_detail.unloaded_model_lot_ids = []
                
            if jig_detail.no_of_model_cases:
                # Initialize collections for this jig
                jig_versions = {}
                jig_vendors = {}
                jig_locations = {}
                jig_tray_types = {}
                jig_tray_capacities = {}
                jig_plating_stk_nos = {}
                jig_polishing_stk_nos = {}
                jig_plating_colors = {}
                jig_model_colors = {}
                jig_model_images = {}
                
                all_versions = []
                all_vendors = []
                all_locations = []
                all_tray_types = []
                all_tray_capacities = []
                all_plating_stk_nos = []
                all_polishing_stk_nos = []
                
                # 🚀 FIXED: Use no_of_model_cases as primary source for color assignment
                # This ensures we use full model numbers instead of truncated database values
                print(f"🎯 PRIMARY COLOR ASSIGNMENT: Using no_of_model_cases: {jig_detail.no_of_model_cases}")
                
                for model_no in jig_detail.no_of_model_cases:
                    print(f"🔍 PRIMARY: Processing model_no='{model_no}'")
                    
                    # Use global color mapping with full model number
                    model_key = str(model_no)  # Force string conversion
                    assigned_color = global_model_colors.get(model_key, "#cccccc")
                    jig_model_colors[model_key] = assigned_color
                    print(f"🎨 PRIMARY: Assigned color {assigned_color} to full model '{model_key}'")
                    
                    # Get images for this model
                    if model_key in model_images_map:
                        jig_model_images[model_key] = model_images_map[model_key]
                    else:
                        jig_model_images[model_key] = {'images': [], 'first_image': None}
                    
                    # Get additional data from model_data_map if available (with numeric prefix fallback)
                    model_data = model_data_map.get(model_key)
                    if not model_data:
                        _nm2 = re.match(r'^(\d+)', model_key)
                        if _nm2:
                            model_data = model_data_map.get(_nm2.group(1))
                    if model_data:
                        
                        # Collect from model_data_map
                        version = model_data['version']
                        if version and version != "No Version":
                            jig_versions[model_key] = version
                            all_versions.append(version)
                        
                        vendor = model_data['vendor']
                        if vendor and vendor != "No Vendor":
                            all_vendors.append(vendor)
                        
                        location = model_data['location']
                        if location and location != "No Location":
                            all_locations.append(location)
                        
                        tray_type = model_data['tray_type']
                        if tray_type and tray_type != "No Tray Type":
                            all_tray_types.append(tray_type)
                        
                        tray_capacity = model_data['tray_capacity']
                        if tray_capacity and tray_capacity > 0:
                            all_tray_capacities.append(tray_capacity)
                        
                        plating_stk_no = model_data['plating_stk_no']
                        if plating_stk_no and plating_stk_no != "No Plating Stock No":
                            all_plating_stk_nos.append(plating_stk_no)
                        
                        # Use plating_stk_no for display (polishing_stk_no has X mask)
                        _display_polishing = model_data['plating_stk_no']
                        if _display_polishing and _display_polishing != "No Plating Stock No":
                            all_polishing_stk_nos.append(_display_polishing)
                
                all_plating_colors = []
                
                # Replace the lot_id_quantities processing section with this version that keeps ALL values including duplicates:

                # 🚀 ENHANCED: Use lot_id_quantities for comprehensive lot-specific data collection (INCLUDING DUPLICATES)
                if hasattr(jig_detail, 'lot_id_quantities') and jig_detail.lot_id_quantities:
                    print(f"🔥 Processing lot_id_quantities for ALL individual values: {jig_detail.lot_id_quantities}")
                    
                    for lot_id, quantity in jig_detail.lot_id_quantities.items():
                        # Get model_no for this specific lot_id
                        model_no = jig_detail.lot_id_model_map.get(lot_id)
                        if not model_no:
                            print(f"❌ No model_no found for lot_id: {lot_id}")
                            continue
                            
                        print(f"🔄 Processing lot_id: {lot_id} -> model_no: {model_no}")
                        
                        # 🐛 DEBUG: Check for model number truncation
                        print(f"🔍 DEBUG: model_no type: {type(model_no)}, value: '{model_no}', length: {len(str(model_no))}")
                        
                        # Use global color mapping for model_no with explicit string conversion
                        model_key = str(model_no)  # Force string conversion
                        assigned_color = global_model_colors.get(model_key, "#cccccc")
                        # 🚨 SKIP: Don't assign color here - potentially truncated model_no
                        # jig_model_colors[model_key] = assigned_color  # COMMENTED OUT
                        print(f"🚨 SKIPPING color assignment for potentially truncated '{model_key}' -> {assigned_color}")
                        print(f"🔍 DEBUG: jig_model_colors kept unchanged: {jig_model_colors}")
                        
                        # Get images for this model
                        if model_no in model_images_map:
                            jig_model_images[model_no] = model_images_map[model_no]
                        else:
                            jig_model_images[model_no] = {
                                'images': [], 'first_image': None}
                        
                        # 🎯 PRIMARY: Get comprehensive lot-specific data
                        lot_specific_data = self.get_lot_specific_data(lot_id, model_no)
                        
                        if lot_specific_data:
                            # Store lot-specific data in dictionaries
                            # Complete field mapping per lot_id
                            jig_versions[lot_id] = lot_specific_data['version']
                            jig_vendors[lot_id] = lot_specific_data['vendor']
                            jig_locations[lot_id] = lot_specific_data['location']
                            jig_tray_types[lot_id] = lot_specific_data['tray_type']
                            jig_tray_capacities[lot_id] = lot_specific_data['tray_capacity']
                            jig_plating_stk_nos[lot_id] = lot_specific_data['plating_stk_no']
                            jig_polishing_stk_nos[lot_id] = lot_specific_data['polishing_stk_no']
                            jig_plating_colors[lot_id] = lot_specific_data['plating_color']
                            # ✅ COLLECT ALL VALUES (INCLUDING DUPLICATES)
                            version = lot_specific_data['version']
                            if version and version != "No Version":
                                all_versions.append(version)  # NO duplicate check - add every value
                                print(f"✅ Added version: '{version}' from lot_id: {lot_id}")
                            
                            vendor = lot_specific_data['vendor']
                            if vendor and vendor != "No Vendor":
                                all_vendors.append(vendor)  # NO duplicate check
                            
                            location = lot_specific_data['location']
                            if location and location != "No Location":
                                all_locations.append(location)  # NO duplicate check
                            
                            tray_type = lot_specific_data['tray_type']
                            if tray_type and tray_type != "No Tray Type":
                                all_tray_types.append(tray_type)  # NO duplicate check
                            
                            tray_capacity = lot_specific_data['tray_capacity']
                            if tray_capacity and tray_capacity > 0:
                                all_tray_capacities.append(tray_capacity)  # NO duplicate check
                            
                            # ✅ CRITICAL: Collect ALL plating_stk_no values (including duplicates)
                            plating_stk_no = lot_specific_data['plating_stk_no']
                            if plating_stk_no and plating_stk_no != "No Plating Stock No":
                                all_plating_stk_nos.append(plating_stk_no)  # NO duplicate check - add every value
                                print(f"✅ Added plating_stk_no: '{plating_stk_no}' from lot_id: {lot_id}")
                            
                            # ✅ CRITICAL: Use plating_stk_no for display (polishing_stk_no has X mask)
                            _disp_pol = lot_specific_data['plating_stk_no']
                            if _disp_pol and _disp_pol != "No Plating Stock No":
                                all_polishing_stk_nos.append(_disp_pol)  # NO duplicate check - add every value
                                print(f"✅ Added polishing_stk_no (from plating): '{_disp_pol}' from lot_id: {lot_id}")
                            
                            plating_color = lot_specific_data['plating_color']
                            if plating_color and plating_color != "N/A":
                                all_plating_colors.append(plating_color)  # NO duplicate check
                            
                            print(f"✅ Processed lot {lot_id}: plating={plating_stk_no}, version={version}")
                            
                        else:
                            print(f"⚠️ No lot-specific data from get_lot_specific_data for lot_id: {lot_id}, trying fallback...")
                            
                            # ✅ ENHANCED FALLBACK: Get data directly from stock models
                            stock_model, is_recovery, batch_model_class = self.get_stock_model_data(lot_id)
                            if stock_model:
                                print(f"📋 Using stock model fallback for lot_id: {lot_id}")
                                
                                # Extract plating_stk_no directly from stock model
                                fallback_plating = getattr(stock_model, 'plating_stk_no', None)
                                if fallback_plating:
                                    all_plating_stk_nos.append(fallback_plating)  # NO duplicate check
                                    jig_plating_stk_nos[lot_id] = fallback_plating
                                    print(f"📋 Added fallback plating_stk_no: '{fallback_plating}'")
                                
                                # Use plating_stk_no for display (polishing_stk_no has X mask)
                                if fallback_plating:
                                    all_polishing_stk_nos.append(fallback_plating)  # NO duplicate check
                                    jig_polishing_stk_nos[lot_id] = fallback_plating
                                    print(f"📋 Added fallback polishing_stk_no (from plating): '{fallback_plating}'")
                                
                                # Extract version from stock model
                                fallback_version = None
                                if hasattr(stock_model, 'version') and stock_model.version:
                                    if hasattr(stock_model.version, 'version_internal'):
                                        fallback_version = stock_model.version.version_internal
                                    elif hasattr(stock_model.version, 'version_name'):
                                        fallback_version = stock_model.version.version_name
                                    else:
                                        fallback_version = str(stock_model.version)
                                
                                if fallback_version:
                                    all_versions.append(fallback_version)  # NO duplicate check
                                    jig_versions[lot_id] = fallback_version
                                    print(f"📋 Added fallback version: '{fallback_version}'")
                            else:
                                print(f"❌ No fallback data available for lot_id: {lot_id}")
                
                else:
                    # Fallback to model-based logic if no lot_id_quantities
                    print(f"⚠️ No lot_id_quantities found, falling back to model-based logic for {jig_detail.lot_id}")
                    for model_no in jig_detail.no_of_model_cases:
                        # 🐛 DEBUG: Check for model number truncation in fallback
                        print(f"🔍 FALLBACK DEBUG: model_no type: {type(model_no)}, value: '{model_no}', length: {len(str(model_no))}")
                        
                        # Use global color mapping for model_no with explicit string conversion
                        model_key = str(model_no)  # Force string conversion
                        assigned_color = global_model_colors.get(model_key, "#cccccc")
                        # 🚨 SKIP: Color already assigned in primary section above
                        # jig_model_colors[model_key] = assigned_color  # COMMENTED OUT
                        print(f"🚨 FALLBACK SKIPPED: Color already assigned for '{model_key}' -> {assigned_color}")
                        print(f"🔍 FALLBACK DEBUG: jig_model_colors unchanged: {jig_model_colors}")
                        
                        # Get images for this model
                        if model_no in model_images_map:
                            jig_model_images[model_no] = model_images_map[model_no]
                            print(f"📸 Found images for model {model_no}: {len(model_images_map[model_no]['images'])} images")
                        else:
                            jig_model_images[model_no] = {'images': [], 'first_image': None}
                            print(f"❌ No images found for model {model_no}")
                            
                        # Special debug for 1805 models
                        if '1805' in str(model_no):
                            print(f"🎯 1805 MODEL DEBUG:")
                            print(f"   model_no: {model_no}")
                            print(f"   in model_images_map: {model_no in model_images_map}")
                            if model_no in model_images_map:
                                print(f"   images count: {len(model_images_map[model_no]['images'])}")
                                print(f"   first_image: {model_images_map[model_no]['first_image']}")
                            print(f"   assigned images: {jig_model_images.get(model_no, 'NOT FOUND')}")

                    # Attach all collected data to jig_detail object
                    jig_detail.model_colors = jig_model_colors
                    jig_detail.model_images = jig_model_images
                    
                    # Debug log for 1805 models
                    has_1805 = any('1805' in str(k) for k in jig_model_images.keys())
                    if has_1805:
                        print(f"🎯 JIG {jig_detail.lot_id} - Final model_images with 1805:")
                        for model_key, image_data in jig_model_images.items():
                            if '1805' in str(model_key):
                                print(f"   {model_key}: {len(image_data['images'])} images, first: {image_data['first_image']}")
                    
                    # Basic debug info
                    print(f"📊 JIG {jig_detail.jig_id} - Total models: {len(jig_model_images)}, Colors: {len(jig_model_colors)}")

                    # 🎨 ENHANCED DEBUG: Print color assignments for this jig
                    print(f"🎨 FINAL COLOR ASSIGNMENTS for {jig_detail.lot_id}:")
                    print(f"   🎯 model_colors dict: {jig_detail.model_colors}")
                    print(f"   📋 no_of_model_cases list: {jig_detail.no_of_model_cases}")
                    for model_no in (jig_detail.no_of_model_cases or []):
                        color = jig_detail.model_colors.get(model_no, 'NOT_FOUND')
                        print(f"   🔍 Model {model_no} -> Color {color}")
                        
                        # 🐛 EXTRA DEBUG: Check model number type and value
                        print(f"   🔍 EXTRA DEBUG: model_no type: {type(model_no)}, repr: {repr(model_no)}")
                        
                        if model_no in model_data_map:
                            model_data = model_data_map[model_no]
                            
                            # Collect from model_data_map (keep duplicates here too for consistency)
                            version = model_data['version']
                            if version and version != "No Version":
                                jig_versions[model_no] = version
                                all_versions.append(version)  # NO duplicate check
                            
                            vendor = model_data['vendor']
                            if vendor and vendor != "No Vendor":
                                jig_vendors[model_no] = vendor
                                all_vendors.append(vendor)  # NO duplicate check
                            
                            location = model_data['location']
                            if location and location != "No Location":
                                jig_locations[model_no] = location
                                all_locations.append(location)  # NO duplicate check
                            
                            tray_type = model_data['tray_type']
                            if tray_type and tray_type != "No Tray Type":
                                jig_tray_types[model_no] = tray_type
                                all_tray_types.append(tray_type)  # NO duplicate check
                            
                            tray_capacity = model_data['tray_capacity']
                            if tray_capacity and tray_capacity > 0:
                                jig_tray_capacities[model_no] = tray_capacity
                                all_tray_capacities.append(tray_capacity)  # NO duplicate check
                            
                            # ✅ CRITICAL: Collect ALL values including duplicates
                            plating_stk_no = model_data['plating_stk_no']
                            if plating_stk_no and plating_stk_no != "No Plating Stock No":
                                jig_plating_stk_nos[model_no] = plating_stk_no
                                all_plating_stk_nos.append(plating_stk_no)  # NO duplicate check
                            
                            # Use plating_stk_no for display (polishing_stk_no has X mask)
                            _disp_pol2 = model_data['plating_stk_no']
                            if _disp_pol2 and _disp_pol2 != "No Plating Stock No":
                                jig_polishing_stk_nos[model_no] = _disp_pol2
                                all_polishing_stk_nos.append(_disp_pol2)  # NO duplicate check
                              
                            plating_color = model_data['plating_color']
                            if plating_color and plating_color != "N/A":
                                jig_plating_colors[model_no] = plating_color
                                all_plating_colors.append(plating_color)  # NO duplicate check
                
                # Attach all collected data to jig_detail object
                jig_detail.model_versions = jig_versions
                jig_detail.model_vendors = jig_vendors
                jig_detail.model_locations = jig_locations
                jig_detail.model_tray_types = jig_tray_types
                jig_detail.model_tray_capacities = jig_tray_capacities
                jig_detail.model_plating_stk_nos = jig_plating_stk_nos
                jig_detail.model_polishing_stk_nos = jig_polishing_stk_nos
                jig_detail.model_plating_colors = jig_plating_colors
                
                jig_detail.model_colors = jig_model_colors
                jig_detail.model_images = jig_model_images
                
                # *** NEW: Prepare colored quantity data for multi-model display ***
                if hasattr(jig_detail, 'lot_id_quantities') and jig_detail.lot_id_quantities:
                    jig_detail.colored_quantities = []
                    if hasattr(jig_detail, 'lot_id_model_map') and jig_detail.lot_id_model_map:
                        for lot_id, quantity in jig_detail.lot_id_quantities.items():
                            model_no = jig_detail.lot_id_model_map.get(lot_id, 'Unknown')
                            color = jig_detail.model_colors.get(model_no, '#6c757d')
                            jig_detail.colored_quantities.append({
                                'quantity': quantity,
                                'model': model_no,
                                'color': color,
                                'tooltip': f'Model: {model_no}, Lot: {lot_id}, Qty: {quantity}'
                            })
                    else:
                        # Fallback: if no model mapping, use default color
                        for lot_id, quantity in jig_detail.lot_id_quantities.items():
                            jig_detail.colored_quantities.append({
                                'quantity': quantity,
                                'model': 'Unknown',
                                'color': '#6c757d',
                                'tooltip': f'Lot: {lot_id}, Qty: {quantity}'
                            })
                else:
                    jig_detail.colored_quantities = []
                
                # 🎨 DEBUG: Print color assignments for this jig
                print(f"🎨 FINAL COLOR ASSIGNMENTS for {jig_detail.lot_id}:")
                print(f"   🎯 model_colors: {jig_detail.model_colors}")
                print(f"   📋 no_of_model_cases: {jig_detail.no_of_model_cases}")
                for model_no in (jig_detail.no_of_model_cases or []):
                    color = jig_detail.model_colors.get(model_no, 'NOT_FOUND')
                    print(f"   🔍 Model {model_no} -> Color {color}")
                
                # ✅ KEEP ALL VALUES INCLUDING DUPLICATES (no set() function used)
                jig_detail.all_versions = [v for v in all_versions if v and v != "No Version"]
                jig_detail.all_vendors = [v for v in all_vendors if v and v != "No Vendor"]
                jig_detail.all_locations = [v for v in all_locations if v and v != "No Location"]
                jig_detail.all_plating_stk_nos = [v for v in all_plating_stk_nos if v and v != "No Plating Stock No"]
                jig_detail.all_polishing_stk_nos = [v for v in all_polishing_stk_nos if v and v != "No Polishing Stock No"]
                jig_detail.all_plating_colors = [v for v in all_plating_colors if v and v != "N/A"]
                
                # ✅ ALSO PROVIDE UNIQUE VERSIONS (for backward compatibility)
                jig_detail.unique_versions = sorted(list(set(jig_detail.all_versions)))
                jig_detail.unique_vendors = sorted(list(set(jig_detail.all_vendors)))
                jig_detail.unique_locations = sorted(list(set(jig_detail.all_locations)))
                jig_detail.unique_plating_stk_nos = sorted(list(set(jig_detail.all_plating_stk_nos)))
                jig_detail.unique_polishing_stk_nos = sorted(list(set(jig_detail.all_polishing_stk_nos)))
                jig_detail.unique_plating_colors = sorted(list(set(jig_detail.all_plating_colors)))
                
                # ✅ ENHANCED DEBUG: Print both all and unique values
                print(f"🎊 FINAL RESULTS for {jig_detail.lot_id}:")
                print(f"   📋 ALL plating_stk_nos ({len(jig_detail.all_plating_stk_nos)}): {jig_detail.all_plating_stk_nos}")
                print(f"   📋 ALL polishing_stk_nos ({len(jig_detail.all_polishing_stk_nos)}): {jig_detail.all_polishing_stk_nos}")
                print(f"   📋 ALL versions ({len(jig_detail.all_versions)}): {jig_detail.all_versions}")
                print(f"   🎯 UNIQUE plating_stk_nos ({len(jig_detail.unique_plating_stk_nos)}): {jig_detail.unique_plating_stk_nos}")
                print(f"   🎯 UNIQUE polishing_stk_nos ({len(jig_detail.unique_polishing_stk_nos)}): {jig_detail.unique_polishing_stk_nos}")
                print(f"   🎯 UNIQUE versions ({len(jig_detail.unique_versions)}): {jig_detail.unique_versions}")
                
                # Set default values for remaining fields
                jig_detail.jig_type = getattr(jig_detail, 'jig_type', "N/A")
                jig_detail.jig_capacity = getattr(jig_detail, 'jig_capacity', 0)
                # Safely resolve plating color — prefer explicit attribute, then annotated cast, else fallback
                plating_color_val = getattr(jig_detail, 'plating_color', None)
                if not plating_color_val:
                    plating_color_val = getattr(jig_detail, 'plating_color_cast', None)
                jig_detail.plating_color = plating_color_val or "N/A"
                
                # Calculate no_of_trays based on total_cases_loaded and tray_capacity
                valid_capacities = [cap for cap in all_tray_capacities if cap and cap > 0]
                if valid_capacities and hasattr(jig_detail, 'total_cases_loaded') and jig_detail.total_cases_loaded:
                    primary_tray_capacity = valid_capacities[0]
                    jig_detail.calculated_no_of_trays = math.ceil(jig_detail.total_cases_loaded / primary_tray_capacity)
                    jig_detail.primary_tray_capacity = primary_tray_capacity
                else:
                    jig_detail.calculated_no_of_trays = 0
                    jig_detail.primary_tray_capacity = 0
            else:
                jig_detail.model_versions = {}
                jig_detail.model_vendors = {}
                jig_detail.model_locations = {}
                jig_detail.model_tray_types = {}
                jig_detail.model_tray_capacities = {}
                jig_detail.model_plating_stk_nos = {}
                jig_detail.model_polishing_stk_nos = {}
                jig_detail.model_plating_colors = {}
                jig_detail.model_colors = {}
                jig_detail.model_images = {}
                jig_detail.unique_versions = []
                jig_detail.unique_vendors = []
                jig_detail.unique_locations = []
                jig_detail.unique_tray_types = []
                jig_detail.unique_tray_capacities = []
                jig_detail.unique_plating_stk_nos = []
                jig_detail.unique_polishing_stk_nos = []
                jig_detail.calculated_no_of_trays = 0
                jig_detail.primary_tray_capacity = 0
                jig_detail.plating_color = "N/A"
                
        # This converts the QuerySet to a list, so it MUST be last
        jig_unload = self.check_draft_status_for_jigs(jig_unload)
        
        # Ensure required fields are set for template compatibility
        for jig_detail in jig_unload:
            # Set jig_qr_id for template (use jig_id or fallback to lot_id)
            jig_detail.jig_qr_id = getattr(jig_detail, 'jig_id', None) or jig_detail.lot_id
            # Set jig_loaded_date_time for Last Updated column (fallback to updated_at)
            jig_detail.jig_loaded_date_time = getattr(jig_detail, 'IP_loaded_date_time', None) or getattr(jig_detail, 'updated_at', None)
            
            # Check if all models have been submitted for Z1 unloading
            _dd_z1 = getattr(jig_detail, 'draft_data', {}) or {}
            # Build all_lot_ids: prefer multi_model_allocation → lot_id_quantities → fallback
            _alloc_z1 = _dd_z1.get('multi_model_allocation', []) if isinstance(_dd_z1, dict) else []
            _liq_z1 = _dd_z1.get('lot_id_quantities', {}) if isinstance(_dd_z1, dict) else {}
            if _alloc_z1:
                _all_lids_z1 = set(a['lot_id'] for a in _alloc_z1 if a.get('lot_id'))
            elif _liq_z1:
                _all_lids_z1 = set(_liq_z1.keys())
            else:
                _all_lids_z1 = {jig_detail.lot_id}
            _submitted_z1 = set(
                JUSubmittedZ1.objects.filter(jig_completed_id=jig_detail.id, is_draft=False)
                .values_list('lot_id', flat=True)
            )
            jig_detail.all_models_submitted_z1 = _all_lids_z1.issubset(_submitted_z1) and len(_submitted_z1) > 0

            # Draft indicator: any JUSubmittedZ1 draft record for this jig
            _has_draft_z1 = JUSubmittedZ1.objects.filter(
                jig_completed_id=jig_detail.id, is_draft=True
            ).exists()
            if _has_draft_z1 and not jig_detail.all_models_submitted_z1:
                jig_detail.jig_unload_draft = True
                jig_detail.has_unload_draft = True
            
            # Parse draft_data if needed
            draft_data = {}
            if hasattr(jig_detail, 'draft_data') and jig_detail.draft_data:
                if isinstance(jig_detail.draft_data, str):
                    try:
                        import json
                        draft_data = json.loads(jig_detail.draft_data)
                    except:
                        draft_data = {}
                elif isinstance(jig_detail.draft_data, dict):
                    draft_data = jig_detail.draft_data
            
            # Set plating_color from draft_data or fetch from models
            plating_color = draft_data.get('plating_color')
            if not plating_color:
                # Try to get plating color from stock models
                stock_model, is_recovery, batch_model_class = self.get_stock_model_data(jig_detail.lot_id)
                if stock_model and hasattr(stock_model, 'plating_color') and stock_model.plating_color:
                    plating_color = stock_model.plating_color.plating_color
            # Fallback: JigCompleted.batch_id → ModelMasterCreation.plating_color (for Jig Loading lots)
            if not plating_color:
                _jd_b_pc = getattr(jig_detail, 'batch_id', None)
                if _jd_b_pc:
                    _mmc_pc = ModelMasterCreation.objects.filter(batch_id=_jd_b_pc).values('plating_color').first()
                    if _mmc_pc and _mmc_pc.get('plating_color'):
                        plating_color = _mmc_pc['plating_color']
            jig_detail.plating_color = plating_color or 'N/A'
            
            # Set tray info from draft_data or fetch from models
            tray_type = draft_data.get('tray_type')
            tray_capacity = draft_data.get('tray_capacity')
            if not tray_type or not tray_capacity:
                # Try to get tray info from model data
                lot_data = self.get_lot_specific_data(jig_detail.lot_id, None)
                if lot_data:
                    if not tray_type:
                        tray_type = lot_data.get('tray_type')
                    if not tray_capacity:
                        tray_capacity = lot_data.get('tray_capacity')
            jig_detail.tray_type = tray_type
            jig_detail.tray_capacity = tray_capacity
            
            # Set lot_id_quantities from draft_data or create from stock data
            lot_id_quantities = draft_data.get('lot_id_quantities', {})
            if not lot_id_quantities:
                # Use delink_tray_qty as primary source for processed quantity
                delink_qty = getattr(jig_detail, 'delink_tray_qty', 0)
                if delink_qty and delink_qty > 0:
                    lot_id_quantities = {jig_detail.lot_id: delink_qty}
                else:
                    # Try to get quantity from stock models as fallback
                    stock_model, is_recovery, batch_model_class = self.get_stock_model_data(jig_detail.lot_id)
                    if stock_model and hasattr(stock_model, 'total_stock'):
                        lot_id_quantities = {jig_detail.lot_id: stock_model.total_stock}
                    else:
                        lot_id_quantities = {jig_detail.lot_id: getattr(jig_detail, 'updated_lot_qty', 0)}
            jig_detail.lot_id_quantities = lot_id_quantities

            # Rebuild lot_id_model_map now that lot_id_quantities is properly set
            # Use jig_detail.lot_id directly as key (draft_data lot_id_quantities keys may have typos)
            if not getattr(jig_detail, 'lot_id_model_map', None) and lot_id_quantities:
                _psn = getattr(jig_detail, 'plating_stock_num', None) or draft_data.get('plating_stock_num')
                if _psn:
                    # Include jig_detail.lot_id (correct DB key) AND all lot_id_quantities keys
                    # (draft_data keys may differ due to typos; both must resolve to the same model)
                    _rebuilt_map = {jig_detail.lot_id: str(_psn).strip()}
                    for _k in lot_id_quantities.keys():
                        _rebuilt_map.setdefault(_k, str(_psn).strip())
                    jig_detail.lot_id_model_map = _rebuilt_map
                    print(f"🏷️ Rebuilt lot_id_model_map for {jig_detail.lot_id}: {jig_detail.lot_id_model_map}")

            # Ensure no_of_model_cases is a list
            model_cases = draft_data.get('no_of_model_cases', getattr(jig_detail, 'no_of_model_cases', None))
            if not model_cases:  # catches None AND empty string (single-model jigs store '' in no_of_model_cases)
                # plating_stock_num is the most reliable source for single-model jigs
                _plating_sn = getattr(jig_detail, 'plating_stock_num', None) or draft_data.get('plating_stock_num')
                if _plating_sn:
                    model_cases = [str(_plating_sn).strip()]
                else:
                    # Fallback to stock model lookup (may fail for JigCompleted lot_ids)
                    stock_model, is_recovery, batch_model_class = self.get_stock_model_data(jig_detail.lot_id)
                    if stock_model and hasattr(stock_model, 'model_stock_no') and stock_model.model_stock_no:
                        model_cases = [stock_model.model_stock_no.model_no]
                    else:
                        model_cases = []
            if isinstance(model_cases, str):
                try:
                    _parsed = json.loads(model_cases)
                    jig_detail.no_of_model_cases = _parsed if isinstance(_parsed, list) else ([str(_parsed)] if _parsed else [])
                except:
                    # Parse comma-separated 'plating_stk_no:qty' format e.g. '1805NAK02:14,1805NAR02:13'
                    _parsed_items = [_i.split(':')[0].strip() for _i in model_cases.split(',') if _i.split(':')[0].strip()]
                    jig_detail.no_of_model_cases = _parsed_items if _parsed_items else []
            elif isinstance(model_cases, list):
                jig_detail.no_of_model_cases = model_cases
            else:
                jig_detail.no_of_model_cases = []

            # After parsing, if still empty (e.g. DB stored '[]'), fall back to plating_stock_num
            if not jig_detail.no_of_model_cases:
                _psn2 = getattr(jig_detail, 'plating_stock_num', None) or draft_data.get('plating_stock_num')
                if _psn2:
                    jig_detail.no_of_model_cases = [str(_psn2).strip()]

            # Set lot_plating_stk_nos for template (model widget + data-plating-stk-no attr)
            if not getattr(jig_detail, 'lot_plating_stk_nos', None):
                if jig_detail.no_of_model_cases:
                    jig_detail.lot_plating_stk_nos = ', '.join(str(x) for x in jig_detail.no_of_model_cases)
                else:
                    _fallback_psn = getattr(jig_detail, 'plating_stock_num', None) or draft_data.get('plating_stock_num', '')
                    jig_detail.lot_plating_stk_nos = str(_fallback_psn).strip() if _fallback_psn else ''

            # Re-populate model_images and model_colors if first loop skipped them
            # (first loop skips single-model jigs where no_of_model_cases DB value is '')
            if jig_detail.no_of_model_cases and not getattr(jig_detail, 'model_images', None):
                _model_imgs = {}
                _model_clrs = {}
                for _mn in jig_detail.no_of_model_cases:
                    _mk = str(_mn)
                    _model_clrs[_mk] = global_model_colors.get(_mk, '#cccccc')
                    # Image priority: exact plating_stk_no match → batch_id path
                    _img_data = model_images_map.get(_mk, {'images': [], 'first_image': None})
                    if not _img_data.get('images'):
                        _batch_img = batch_images_map.get(getattr(jig_detail, 'batch_id', None))
                        if _batch_img:
                            _img_data = _batch_img
                    _model_imgs[_mk] = _img_data
                jig_detail.model_images = _model_imgs
                jig_detail.model_colors = _model_clrs
                # Populate model_data (versions/tray info) with numeric prefix fallback
                _first_mk = str(jig_detail.no_of_model_cases[0])
                _md = model_data_map.get(_first_mk)
                if not _md:
                    _nmp = re.match(r'^(\d+)', _first_mk)
                    if _nmp:
                        _md = model_data_map.get(_nmp.group(1))
                if _md:
                    if not getattr(jig_detail, 'unique_versions', None):
                        jig_detail.unique_versions = [_md['version']]
                    if not getattr(jig_detail, 'unique_vendors', None):
                        jig_detail.unique_vendors = [_md['vendor']]
                    if not getattr(jig_detail, 'unique_locations', None):
                        jig_detail.unique_locations = [_md['location']]
                    if not getattr(jig_detail, 'unique_tray_types', None):
                        jig_detail.unique_tray_types = [_md['tray_type']]
                    if not getattr(jig_detail, 'unique_plating_stk_nos', None):
                        jig_detail.unique_plating_stk_nos = [_md['plating_stk_no']]
                    if not getattr(jig_detail, 'unique_polishing_stk_nos', None):
                        jig_detail.unique_polishing_stk_nos = [_md['polishing_stk_no']]
            
            # Ensure other list fields are lists
            for field in ['all_versions', 'all_vendors', 'all_locations', 'all_plating_stk_nos', 'all_polishing_stk_nos', 'all_plating_colors']:
                if not hasattr(jig_detail, field) or getattr(jig_detail, field) is None:
                    setattr(jig_detail, field, [])
            
            # If we don't have polishing stock numbers, try to fetch them
            if not jig_detail.all_polishing_stk_nos and jig_detail.no_of_model_cases:
                polishing_stk_nos = []
                plating_stk_nos = []
                for model_no in jig_detail.no_of_model_cases:
                    lot_data = self.get_lot_specific_data(jig_detail.lot_id, model_no)
                    if lot_data:
                        if lot_data.get('polishing_stk_no') and lot_data['polishing_stk_no'] != 'No Polishing Stock No':
                            polishing_stk_nos.append(lot_data['polishing_stk_no'])
                        if lot_data.get('plating_stk_no') and lot_data['plating_stk_no'] != 'No Plating Stock No':
                            plating_stk_nos.append(lot_data['plating_stk_no'])
                jig_detail.all_polishing_stk_nos = polishing_stk_nos
                if not jig_detail.all_plating_stk_nos:
                    jig_detail.all_plating_stk_nos = plating_stk_nos
        
        # Add pagination with consistent logic as Inprocess Inspection
        page_number = self.request.GET.get('page', 1)
        paginator = Paginator(jig_unload, 10)  # 10 items per page like Inprocess Inspection
        page_obj = paginator.get_page(page_number)
        
        print(f"\n📄 Jig Unloading Main - Pagination: Page {page_number}, Total items: {len(jig_unload)}")
        print(f"📄 Current page items: {len(page_obj.object_list)}")
        print(f"📄 Total pages: {paginator.num_pages}")
        
        context['jig_unload'] = page_obj  # For table data
        context['jig_details'] = page_obj  # For pagination controls (template uses this name)
        context['bath_numbers'] = bath_numbers
        
        return context
    
    def filter_fully_unloaded_jigs(self, queryset):
        """Smart filter to remove jigs where ALL lot_ids are unloaded"""
        
        def parse_combined_lot_id(combined_id):
            try:
                return combined_id.rsplit('-', 1) if combined_id and '-' in combined_id else (None, None)
            except:
                return None, None

        # ✅ FAST PATH: jigs already flagged as fully unloaded via last_process_module
        # These were set by save_jig_unload_tray_ids - skip combine_lot_ids scan for them.
        completed_jig_ids = set(
            JigCompleted.objects.filter(last_process_module='Jig Unloading')
            .values_list('jig_id', flat=True)
        )
        completed_lot_ids = set(
            JigCompleted.objects.filter(last_process_module='Jig Unloading')
            .values_list('lot_id', flat=True)
        )
        print(f"[FILTER] Fast-path jig_ids with last_process_module='Jig Unloading': {len(completed_jig_ids)}")

        # Get all unload records once
        unload_records = JigUnloadAfterTable.objects.filter(
            combine_lot_ids__isnull=False
        ).exclude(combine_lot_ids__exact=[]).values('combine_lot_ids')

        
        # Build unload mapping: jig_lot_id -> set of unloaded lot_ids
        # Also collect bare lot_ids (stored when jig_lot_id was empty: "-LIDxxx" or plain "LIDxxx")
        unload_map = {}
        bare_unloaded_lot_ids = set()  # lot_ids with no valid jig_id prefix
        for record in unload_records:
            if record['combine_lot_ids']:
                for combined_id in record['combine_lot_ids']:
                    parts = parse_combined_lot_id(combined_id)
                    if len(parts) == 2 and parts[0] and parts[1]:
                        jig_id, lot_id = parts[0], parts[1]
                        unload_map.setdefault(jig_id, set()).add(lot_id)
                    elif len(parts) == 2 and parts[1]:
                        # empty prefix (e.g. "-LIDxxx") — store bare lot_id
                        bare_unloaded_lot_ids.add(parts[1])
                    elif combined_id and '-' not in combined_id:
                        # plain lot_id (no prefix at all)
                        bare_unloaded_lot_ids.add(combined_id)
        
        # Also check direct unloads
        direct_unloads = set(JigUnload_TrayId.objects.values_list('lot_id', flat=True))
        bare_unloaded_lot_ids |= direct_unloads
        
        # Filter jigs
        filtered_jigs = []
        for jig in queryset:
            # lot_id_quantities may not be set yet (second-pass loop runs after this filter),
            # so fall back to reading directly from draft_data on the ORM object.
            _jfq = getattr(jig, 'lot_id_quantities', None) or {}
            if not _jfq:
                _dd_f = getattr(jig, 'draft_data', {}) or {}
                _jfq = _dd_f.get('lot_id_quantities', {}) if isinstance(_dd_f, dict) else {}
            if not _jfq:
                # Fallback to base lot_id if lot_id_quantities isn't present in draft_data
                if getattr(jig, 'lot_id', None):
                    _jfq = {jig.lot_id: getattr(jig, 'updated_lot_qty', 1)}
                else:
                    # Truly no lot data — keep the jig visible
                    filtered_jigs.append(jig)
                    continue

            jig_lot_ids = set(_jfq.keys())
            _jig_id = getattr(jig, 'jig_id', None) or jig.lot_id

            # ✅ FAST PATH: If this jig_id or its lot_id is in completed_jig_ids / completed_lot_ids
            # (set from JigCompleted.unload_over=True), hide it immediately.
            if _jig_id in completed_jig_ids or jig.lot_id in completed_lot_ids:
                print(f"🚫 [FAST PATH] Hiding fully unloaded jig (unload_over=True): {jig.lot_id}")
                continue

            # Also hide if ALL lot_ids in lot_id_quantities are marked as unloaded
            if jig_lot_ids and jig_lot_ids.issubset(completed_lot_ids):
                print(f"🚫 [FAST PATH] Hiding jig - all lot_ids unloaded: {jig.lot_id}")
                continue

            # Fallback: scan combine_lot_ids unload map (handles older records without unload_over flag)
            unloaded_lot_ids = (
                unload_map.get(_jig_id, set())
                | (jig_lot_ids & bare_unloaded_lot_ids)
            )
            
            # Keep jig if ANY lot_id is NOT unloaded
            if not jig_lot_ids.issubset(unloaded_lot_ids):
                filtered_jigs.append(jig)
            else:
                print(f"🚫 [MAP PATH] Hiding fully unloaded jig: {jig.lot_id}")
        
        return filtered_jigs

    def check_draft_status_for_jigs(self, jig_queryset):
        """Check if any jig has draft records prioritizing draft_data['lot_id_quantities'].

        This function will inspect each jig's `draft_data` JSON field first and look
        for a `lot_id_quantities` dict. If present, keys of that dict are treated as
        draft lot ids. Falls back to JigUnloadDraft.main_lot_id values only when
        `lot_id_quantities` is not available.
        """

        # Convert QuerySet to list explicitly
        jig_list = list(jig_queryset)

        # Cache all saved draft main_lot_ids for fallback checks
        saved_draft_main_lot_ids = set(JigUnloadDraft.objects.values_list('main_lot_id', flat=True))
        print(f"🔍 Saved draft main_lot_ids (fallback): {saved_draft_main_lot_ids}")

        for jig_detail in jig_list:
            has_draft = False

            print(f"🔍 Zone 2 - Checking jig {getattr(jig_detail, 'jig_id', jig_detail.lot_id)}")

            # Primary: Inspect draft_data JSON on the jig itself (prefer this)
            draft_data = getattr(jig_detail, 'draft_data', None) or {}
            lot_quantities = {}
            if isinstance(draft_data, dict):
                lot_quantities = draft_data.get('lot_id_quantities', {}) or {}

            # Debug print keys when present
            if lot_quantities:
                print(f"lot_id_quantities keys: {list(lot_quantities.keys())}")
                # If the jig's main lot_id is present in lot_id_quantities, mark draft
                main_lot = getattr(jig_detail, 'lot_id', None)
                if main_lot and main_lot in lot_quantities:
                    has_draft = True
                    print(f"✅ Zone 2 - JIG {getattr(jig_detail, 'jig_id', jig_detail.lot_id)} DRAFT FOUND")

            # Secondary: check new_lot_ids array field if present and not already matched
            if not has_draft and hasattr(jig_detail, 'new_lot_ids') and jig_detail.new_lot_ids:
                print(f"   - new_lot_ids: {jig_detail.new_lot_ids}")
                for lid in jig_detail.new_lot_ids:
                    if lid in lot_quantities or lid in saved_draft_main_lot_ids:
                        has_draft = True
                        print(f"✅ DRAFT MATCH in new_lot_ids: {lid}")
                        break

            # Tertiary fallback: if lot_id_quantities absent, check saved drafts table
            if not has_draft and not lot_quantities:
                main_lot = getattr(jig_detail, 'lot_id', None)
                print(f"   - main lot_id fallback: {main_lot}")
                if main_lot and main_lot in saved_draft_main_lot_ids:
                    has_draft = True
                    print(f"✅ DRAFT MATCH in saved drafts for main lot_id: {main_lot}")

            # Set BOTH flags to ensure template compatibility
            jig_detail.has_unload_draft = has_draft
            jig_detail.jig_unload_draft = has_draft

            if not has_draft and not lot_quantities:
                print(f"❌ Zone 2 - JIG {getattr(jig_detail, 'jig_id', jig_detail.lot_id)} NO DRAFT")

        print(f"🔍 Draft check complete for {len(jig_list)} jigs")
        return jig_list  # Return the list, not queryset


class JigUnloading_Completedtable(TemplateView):
    template_name = 'Jig_Unloading/JigUnloading_Completedtable.html'

    def get_dynamic_tray_capacity(self, tray_type_name):
        """
        Get tray capacity based on tray type name.
        Rules (per workflow spec):
        - Normal: 20
        - Jumbo:  12
        - Others: DB lookup fallback
        """
        try:
            # Workflow-spec hardcoded values
            if tray_type_name == 'Normal':
                return 20
            elif tray_type_name == 'Jumbo':
                return 12

            # Fallback: try custom capacity override table
            custom_capacity = InprocessInspectionTrayCapacity.objects.filter(
                tray_type__tray_type=tray_type_name,
                is_active=True
            ).first()

            if custom_capacity:
                return custom_capacity.custom_capacity

            # Fallback to TrayType table
            tray_type = TrayType.objects.filter(tray_type=tray_type_name).first()
            if tray_type:
                return tray_type.tray_capacity

            # Default fallback
            return 0

        except Exception as e:
            print(f"⚠️ Error getting dynamic tray capacity: {e}")
            return 0

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
                try:
                    from Recovery_DP.models import RecoveryMasterCreation
                    return rsm, True, RecoveryMasterCreation
                except ImportError:
                    print("⚠️ RecoveryMasterCreation not found, using ModelMasterCreation as fallback")
                    return rsm, True, ModelMasterCreation
        except Exception as e:
            print(f"⚠️ Error accessing RecoveryStockModel: {e}")
        
        return None, False, None

    def _resolve_bath_number_for_completed(self, unload, jig_qr_id):
        """Fetch bath number dynamically from JigCompleted for completed table entries."""
        try:
            # 1. Try via jig_qr_id (jig_id on JigCompleted)
            if jig_qr_id:
                jc = JigCompleted.objects.filter(
                    jig_id=jig_qr_id, bath_numbers__isnull=False
                ).values('bath_numbers__bath_number').first()
                if jc:
                    return jc['bath_numbers__bath_number']

            # 2. Try via combine_lot_ids
            if unload.combine_lot_ids:
                for cid in unload.combine_lot_ids:
                    # Extract plain lot_id
                    lid = cid.lstrip('-')
                    if lid.startswith('JLOT-') and '-' in lid[5:]:
                        lid = lid.rsplit('-', 1)[1]
                    jc = JigCompleted.objects.filter(
                        draft_data__lot_id_quantities__has_key=lid, bath_numbers__isnull=False
                    ).values('bath_numbers__bath_number').first()
                    if jc:
                        return jc['bath_numbers__bath_number']
                    # Also try direct lot_id match
                    jc = JigCompleted.objects.filter(
                        lot_id=lid, bath_numbers__isnull=False
                    ).values('bath_numbers__bath_number').first()
                    if jc:
                        return jc['bath_numbers__bath_number']

            # 3. Try via draft_data keys from JigCompleted
            if jig_qr_id:
                jc = JigCompleted.objects.filter(jig_id=jig_qr_id).values('draft_data').first()
                if jc and jc.get('draft_data'):
                    dd = jc['draft_data'] if isinstance(jc['draft_data'], dict) else {}
                    bn = dd.get('bath_number') or dd.get('nickel_bath_number') or dd.get('bath_no')
                    if bn:
                        return str(bn)
        except Exception as e:
            print(f"[BATH FIX] Error resolving bath number: {e}")

        return 'N/A'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 🔥 NEW: Add date filtering logic (same as Inprocess Inspection)
        from django.utils import timezone
        import pytz
        from datetime import datetime, timedelta
        
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

        print(f"[DEBUG] Zone 1 Completed - Date filter: {from_date} to {to_date}")

        # DEBUG: Check total records in JigUnloadAfterTable
        total_unload_records = JigUnloadAfterTable.objects.all().count()
        print(f"[DEBUG] Total JigUnloadAfterTable records: {total_unload_records}")

        # DEBUG: Check allowed color IDs for Zone 1 (Only IPS)
        allowed_color_ids = Plating_Color.objects.filter(
            plating_color='IPS'
        ).values_list('id', flat=True)
        print(f"[DEBUG] Zone 1 Completed - Allowed color IDs (IPS only): {list(allowed_color_ids)}")

        # Filter completed_unloads by Un_loaded_date_time with date filtering
        # ✅ FIX: Also include records where plating_color FK is NULL (happens when populate_jig_unload_fields
        # fails to resolve the FK) so we can post-filter them by resolving color from combine_lot_ids.
        from django.db.models import Q
        completed_unloads_qs = JigUnloadAfterTable.objects.filter(
            Q(plating_color_id__in=allowed_color_ids) | Q(plating_color__isnull=True),
            Un_loaded_date_time__date__gte=from_date,
            Un_loaded_date_time__date__lte=to_date
        ).select_related(
            'plating_color', 'polish_finish', 'version'
        ).prefetch_related('location').order_by('-Un_loaded_date_time')

        # Post-filter: for records with plating_color=None, verify they belong to IPS
        # by tracing combine_lot_ids → TotalStockModel → plating_color
        allowed_colors_set = set(Plating_Color.objects.filter(
            plating_color='IPS'
        ).values_list('plating_color', flat=True))  # {'IPS'}

        def _is_ips_record(rec):
            """Return True if the record's plating color is IPS (traced from combine_lot_ids if FK is null)."""
            if rec.plating_color and rec.plating_color.plating_color in allowed_colors_set:
                return True
            # FK is null — try to resolve from combine_lot_ids
            if rec.combine_lot_ids:
                for _cid in rec.combine_lot_ids:
                    _lid = _extract_lot_id_local(_cid)  # use local helper defined below
                    _tsm = TotalStockModel.objects.filter(lot_id=_lid).select_related('plating_color').first()
                    if _tsm and _tsm.plating_color and _tsm.plating_color.plating_color in allowed_colors_set:
                        # Backfill the FK so future reads are fast
                        try:
                            rec.plating_color = _tsm.plating_color
                            rec.save(update_fields=['plating_color'])
                            print(f"[COMPLETED TABLE FIX] ✅ Backfilled plating_color for record {rec.id} from lot {_lid}")
                        except Exception as _bfe:
                            print(f"[COMPLETED TABLE FIX] ⚠️ Could not backfill plating_color: {_bfe}")
                        return True
                    # Also try JigCompleted→batch_id→ModelMasterCreation path
                    _jc = JigCompleted.objects.filter(
                        draft_data__lot_id_quantities__has_key=_lid
                    ).first()
                    if _jc and _jc.batch_id:
                        _mmc = ModelMasterCreation.objects.filter(
                            batch_id=_jc.batch_id
                        ).values('plating_color').first()
                        if _mmc and _mmc.get('plating_color') in allowed_colors_set:
                            return True
            return False

        # _extract_lot_id is defined later in this method — define a local copy here
        def _extract_lot_id_local(combined):
            if not combined:
                return combined
            s = combined.lstrip('-')
            if s.startswith('JLOT-') and '-' in s[5:]:
                return s.rsplit('-', 1)[1]
            return s

        completed_unloads = [rec for rec in completed_unloads_qs if _is_ips_record(rec)]
        
        print(f"[DEBUG] Filtered completed_unloads count: {len(completed_unloads)}")
        
        # Debug individual records
        for record in completed_unloads:
            print(f"[DEBUG] Record {record.id}: plating_color={record.plating_color}, plating_color_id={record.plating_color_id}")
        
        # Also check all records to see what plating colors they have
        all_records = JigUnloadAfterTable.objects.all()
        print(f"[DEBUG] All records plating colors:")
        for record in all_records:
            color_name = record.plating_color.plating_color if record.plating_color else "None"
            print(f"[DEBUG]   Record {record.id}: plating_color={color_name} (ID: {record.plating_color_id})")

        # ✅ ENHANCED: Get all model numbers from combine_lot_ids for bulk processing
        all_model_numbers = set()
        all_lot_ids = set()

        def _extract_lot_id(combined):
            """Normalise combine_lot_ids entry to a plain lot_id.
            Handles: 'JLOT-xxx-LIDyyy' → 'LIDyyy', '-LIDyyy' → 'LIDyyy', 'LIDyyy' → 'LIDyyy'."""
            if not combined:
                return combined
            s = combined.lstrip('-')
            if s.startswith('JLOT-') and '-' in s[5:]:
                return s.rsplit('-', 1)[1]
            return s

        for unload in completed_unloads:
            if unload.combine_lot_ids:
                all_lot_ids.update(unload.combine_lot_ids)
                # Get model numbers from lot_ids
                for _raw_cid in unload.combine_lot_ids:
                    _actual_lid = _extract_lot_id(_raw_cid)
                    stock_model, is_recovery, batch_model_class = self.get_stock_model_data(_actual_lid)
                    if stock_model and hasattr(stock_model, 'model_stock_no') and stock_model.model_stock_no:
                        all_model_numbers.add(stock_model.model_stock_no.model_no)

        print(f"[DEBUG] Found {len(all_model_numbers)} unique model numbers: {all_model_numbers}")
        print(f"[DEBUG] Found {len(all_lot_ids)} unique lot IDs")

        # ✅ ENHANCED: Use same color palette as Jig_Unloading_MainTable
        color_palette = [
            "#e74c3c", "#f1c40f", "#2ecc71", "#3498db", "#9b59b6",
            "#e67e22", "#1abc9c", "#34495e", "#f39c12", "#d35400",
            "#c0392b", "#8e44ad", "#2980b9", "#27ae60", "#16a085"
        ]
        
        # Create a global color mapping for all unique model numbers
        global_model_colors = {}
        sorted_model_numbers = sorted(list(all_model_numbers))
        for idx, model_no in enumerate(sorted_model_numbers):
            color_index = idx % len(color_palette)
            global_model_colors[model_no] = color_palette[color_index]

        # ✅ ENHANCED: Comprehensive model images fetching (same as MainTable)
        model_images_map = {}
        if all_model_numbers:
            print(f"[DEBUG] Fetching images for {len(all_model_numbers)} models")
            
            # Fetch images for each model using ModelMaster
            model_masters = ModelMaster.objects.filter(
                model_no__in=all_model_numbers
            ).prefetch_related('images')
            
            for model_master in model_masters:
                images = list(model_master.images.all())
                image_urls = []
                first_image = "/static/assets/images/imagePlaceholder.jpg"
                
                for img in images:
                    if img.master_image:
                        try:
                            img_url = img.master_image.url if hasattr(img.master_image, 'url') else str(img.master_image)
                            image_urls.append(img_url)
                            if first_image == "/static/assets/images/imagePlaceholder.jpg":
                                first_image = img_url
                        except Exception as img_err:
                            print(f"[DEBUG] Error processing image {img.id}: {img_err}")
                            continue
                
                model_images_map[model_master.model_no] = {
                    'images': image_urls,
                    'first_image': first_image
                }
                print(f"[DEBUG] Model {model_master.model_no}: {len(image_urls)} images, first: {first_image}")

        # ✅ ENHANCED: Process each unload record with comprehensive data
        table_data = []
        for idx, unload in enumerate(completed_unloads):
            print(f"\n[DEBUG] ===== PROCESSING RECORD {idx + 1} =====")
            print(f"[DEBUG] Unload lot_id: {unload.lot_id}")
            print(f"[DEBUG] combine_lot_ids: {unload.combine_lot_ids}")
            
            # Get jig_qr_id — use DB field, then parse from combine_lot_ids, then JigCompleted lookup
            jig_qr_id = unload.jig_qr_id or ''
            unloading_remarks = None
            if not jig_qr_id and unload.combine_lot_ids:
                for _cid_z1 in unload.combine_lot_ids:
                    # combine_lot_ids format: "JLOT-xxx-LIDyyy" → rsplit gives ("JLOT-xxx", "LIDyyy")
                    if _cid_z1 and '-' in _cid_z1:
                        _parts_z1 = _cid_z1.rsplit('-', 1)
                        _parsed_jig_id = _parts_z1[0] if len(_parts_z1) == 2 else None
                        _parsed_lot_id = _parts_z1[1] if len(_parts_z1) == 2 else _cid_z1
                        if _parsed_jig_id and _parsed_jig_id.startswith('JLOT-'):
                            jig_qr_id = _parsed_jig_id
                            # Also fetch remarks via parsed lot_id
                            _jc_z1 = JigCompleted.objects.filter(
                                draft_data__lot_id_quantities__has_key=_parsed_lot_id
                            ).first()
                            if _jc_z1:
                                unloading_remarks = getattr(_jc_z1, 'unloading_remarks', None)
                            break
                        elif _parsed_lot_id:
                            # Broken format '-LIDyyy': no JLOT prefix — look up JigCompleted via extracted lot_id
                            _actual_lot_z1 = _extract_lot_id(_cid_z1)
                            _jc_z1_fb = JigCompleted.objects.filter(
                                draft_data__lot_id_quantities__has_key=_actual_lot_z1
                            ).first()
                            if _jc_z1_fb:
                                jig_qr_id = getattr(_jc_z1_fb, 'jig_id', None) or ''
                                unloading_remarks = getattr(_jc_z1_fb, 'unloading_remarks', None)
                            break

            # ✅ FINAL FALLBACK: plain lot IDs (no dash) — query JigCompleted directly
            if not jig_qr_id and unload.combine_lot_ids:
                for _cid_plain in unload.combine_lot_ids:
                    _lid_plain = _extract_lot_id(_cid_plain) if _cid_plain else None
                    if not _lid_plain:
                        continue
                    # Try lot_id_quantities key match first
                    _jc_plain = JigCompleted.objects.filter(
                        draft_data__lot_id_quantities__has_key=_lid_plain
                    ).first()
                    if not _jc_plain:
                        # Try direct lot_id match on JigCompleted
                        _jc_plain = JigCompleted.objects.filter(lot_id=_lid_plain).first()
                    if _jc_plain:
                        _jid = getattr(_jc_plain, 'jig_id', None)
                        if _jid:
                            jig_qr_id = _jid
                            unloading_remarks = getattr(_jc_plain, 'unloading_remarks', None)
                            print(f"[ZONE1 FIX] ✅ jig_qr_id resolved from JigCompleted: {jig_qr_id}")
                            break
                        # Even if jig_id is empty, store remarks
                        if not unloading_remarks:
                            unloading_remarks = getattr(_jc_plain, 'unloading_remarks', None)

            # Also backfill jig_qr_id to DB so future renders skip the lookup
            if jig_qr_id and not unload.jig_qr_id:
                try:
                    unload.jig_qr_id = jig_qr_id
                    unload.save(update_fields=['jig_qr_id'])
                    print(f"[ZONE1 FIX] ✅ Backfilled jig_qr_id={jig_qr_id} for record {unload.id}")
                except Exception as _bjid:
                    print(f"[ZONE1 FIX] ⚠️ Backfill jig_qr_id failed: {_bjid}")

            if jig_qr_id and not unloading_remarks:
                _jc_z1_rem = JigCompleted.objects.filter(jig_id=jig_qr_id).first()
                if _jc_z1_rem:
                    unloading_remarks = getattr(_jc_z1_rem, 'unloading_remarks', None)

            # Handle location (many-to-many) with fallback from TotalStockModel
            try:
                locations = unload.location.all()
                location_names = [loc.location_name for loc in locations]
                location_display = ", ".join(location_names) if location_names else "N/A"
            except Exception as e:
                print(f"[DEBUG] Error processing location: {e}")
                location_display = "N/A"
                location_names = []
            # Fallback: look up location from TotalStockModel via combine_lot_ids
            if not location_names and unload.combine_lot_ids:
                for _cid_loc1 in unload.combine_lot_ids:
                    _actual_loc1 = _extract_lot_id(_cid_loc1)
                    _tsm_loc1 = TotalStockModel.objects.filter(lot_id=_actual_loc1).prefetch_related('location').first()
                    if _tsm_loc1 and _tsm_loc1.location.exists():
                        location_names = [loc.location_name for loc in _tsm_loc1.location.all()]
                        location_display = ", ".join(location_names)
                        break
                    elif _tsm_loc1 and _tsm_loc1.batch_id and getattr(_tsm_loc1.batch_id, 'location', None):
                        location_names = [_tsm_loc1.batch_id.location.location_name]
                        location_display = location_names[0]
                        break

            # ✅ NEW FALLBACK: JigCompleted → batch_id → ModelMasterCreation.location
            # This handles Jig Loading lots where TotalStockModel has no location set.
            if not location_names and unload.combine_lot_ids:
                for _cid_loc2 in unload.combine_lot_ids:
                    _actual_loc2 = _extract_lot_id(_cid_loc2)
                    # Try JigCompleted keyed by lot_id_quantities
                    _jc_loc = JigCompleted.objects.filter(
                        draft_data__lot_id_quantities__has_key=_actual_loc2
                    ).first()
                    if not _jc_loc:
                        # Try direct lot_id match on JigCompleted
                        _jc_loc = JigCompleted.objects.filter(lot_id=_actual_loc2).first()
                    if _jc_loc and _jc_loc.batch_id:
                        _mmc_loc = ModelMasterCreation.objects.filter(
                            batch_id=_jc_loc.batch_id
                        ).select_related('location').first()
                        if _mmc_loc and _mmc_loc.location:
                            location_names = [_mmc_loc.location.location_name]
                            location_display = location_names[0]
                            print(f"[COMPLETED TABLE] ✅ Location resolved via JigCompleted→MMC: {location_display}")
                            break
                    # Also try: jig_qr_id → JigCompleted → batch_id → MMC
                    if jig_qr_id:
                        _jc_jid = JigCompleted.objects.filter(jig_id=jig_qr_id).select_related().first()
                        if _jc_jid and _jc_jid.batch_id:
                            _mmc_jid = ModelMasterCreation.objects.filter(
                                batch_id=_jc_jid.batch_id
                            ).select_related('location').first()
                            if _mmc_jid and _mmc_jid.location:
                                location_names = [_mmc_jid.location.location_name]
                                location_display = location_names[0]
                                print(f"[COMPLETED TABLE] ✅ Location resolved via jig_id→JigCompleted→MMC: {location_display}")
                                break
                
            # 🔧 ENHANCED: Calculate tray info using dynamic capacity method
            tray_type_display = unload.tray_type or "N/A"
            
            # Use get_dynamic_tray_capacity method for proper Normal tray handling (16 -> 20)
            if tray_type_display != "N/A":
                dynamic_tray_capacity = self.get_dynamic_tray_capacity(tray_type_display)
                tray_capacity = dynamic_tray_capacity if dynamic_tray_capacity > 0 else (unload.tray_capacity if unload.tray_capacity else 1)
                print(f"[DEBUG] Zone 1 - Dynamic tray capacity for '{tray_type_display}': {dynamic_tray_capacity} (was: {unload.tray_capacity})")
            else:
                tray_capacity = unload.tray_capacity if unload.tray_capacity else 1
                print(f"[DEBUG] Zone 1 - Using raw tray capacity: {tray_capacity}")
            
            total_case_qty = unload.total_case_qty if unload.total_case_qty else 0
            no_of_trays = math.ceil(total_case_qty / tray_capacity) if tray_capacity > 0 else 0

            # ✅ SIMPLIFIED: Use saved list fields from database instead of processing individual lot_ids
            print(f"[DEBUG] ===== USING SAVED LIST FIELDS FROM DATABASE =====")
            
            # ✅ GET SAVED LISTS from database fields
            saved_plating_list = getattr(unload, 'plating_stk_no_list', []) or []
            saved_polish_list = getattr(unload, 'polish_stk_no_list', []) or []
            saved_version_list = getattr(unload, 'version_list', []) or []
            
            print(f"[DEBUG] saved_plating_stk_no_list: {saved_plating_list} (type: {type(saved_plating_list)})")
            print(f"[DEBUG] saved_polish_stk_no_list: {saved_polish_list} (type: {type(saved_polish_list)})")
            print(f"[DEBUG] saved_version_list: {saved_version_list} (type: {type(saved_version_list)})")
            
            # ✅ FIX ERR2/ERR3: Use plating_stk_no_list for display (NOT polish which has X-mask)
            # USE REAL PLATING VALUES FOR DISPLAY, not the X-masked polishing values
            all_plating_stk_nos = saved_plating_list if saved_plating_list else []
            all_polish_stk_nos = saved_plating_list if saved_plating_list else []  # ← CRITICAL FIX: Use plating, not polish
            all_versions = saved_version_list if saved_version_list else []
            
            # ✅ ALSO PROVIDE UNIQUE VERSIONS for backward compatibility
            unique_plating_stk_nos = list(set(all_plating_stk_nos)) if all_plating_stk_nos else []
            unique_polish_stk_nos = list(set(all_plating_stk_nos)) if all_plating_stk_nos else []  # ← CRITICAL FIX: Use plating for unique too
            unique_versions = list(set(all_versions)) if all_versions else []
            
            # ✅ FALLBACK: Use single field values if no saved lists (for backward compatibility)
            if not all_plating_stk_nos and unload.plating_stk_no:
                all_plating_stk_nos = [unload.plating_stk_no]
                unique_plating_stk_nos = [unload.plating_stk_no]
                print(f"[DEBUG] Fallback: Using single plating_stk_no: {unload.plating_stk_no}")
            
            if not all_polish_stk_nos and unload.plating_stk_no:  # ← FIX: Use plating not polish in fallback too
                all_polish_stk_nos = [unload.plating_stk_no]
                unique_polish_stk_nos = [unload.plating_stk_no]
                print(f"[DEBUG] Fallback: Using single plating_stk_no (not polishing): {unload.plating_stk_no}")
            
            if not all_versions and unload.version:
                version_display = getattr(unload.version, 'version_internal', str(unload.version)) if unload.version else "N/A"
                all_versions = [version_display]
                unique_versions = [version_display]
                print(f"[DEBUG] Fallback: Using single version: {version_display}")

            # ✅ BASIC MODEL DATA PROCESSING (simplified - no complex lot_id processing needed)
            model_images = {}
            model_colors = {}
            no_of_model_cases = []
            lot_id_quantities = {}
            
            if unload.combine_lot_ids:
                for lot_id in unload.combine_lot_ids:
                    lot_id = _extract_lot_id(lot_id)
                    try:
                        stock_model, is_recovery, batch_model_class = self.get_stock_model_data(lot_id)
                        if stock_model and hasattr(stock_model, 'model_stock_no') and stock_model.model_stock_no:
                            model_no = stock_model.model_stock_no.model_no
                            no_of_model_cases.append(model_no)
                            
                            # Get lot quantity
                            if hasattr(stock_model, 'total_stock'):
                                lot_id_quantities[lot_id] = stock_model.total_stock
                            elif hasattr(stock_model, 'stock_qty'):
                                lot_id_quantities[lot_id] = stock_model.stock_qty
                            else:
                                lot_id_quantities[lot_id] = 0
                            
                            # Use global color mapping
                            model_colors[model_no] = global_model_colors.get(model_no, "#cccccc")
                            
                            # Get model images from the pre-built map
                            if model_no in model_images_map:
                                model_images[model_no] = model_images_map[model_no]
                            else:
                                model_images[model_no] = {
                                    'images': [],
                                    'first_image': "/static/assets/images/imagePlaceholder.jpg"
                                }
                    except Exception as e:
                        print(f"[DEBUG] Error processing lot_id {lot_id}: {e}")
                        continue

            # Remove duplicates while preserving order
            no_of_model_cases = list(dict.fromkeys(no_of_model_cases))
            
            print(f"[DEBUG] ===== FINAL VALUES SUMMARY =====")
            print(f"[DEBUG] ALL plating_stk_nos ({len(all_plating_stk_nos)}): {all_plating_stk_nos}")
            print(f"[DEBUG] ALL polish_stk_nos ({len(all_polish_stk_nos)}): {all_polish_stk_nos}")
            print(f"[DEBUG] ALL versions ({len(all_versions)}): {all_versions}")
            print(f"[DEBUG] UNIQUE plating_stk_nos ({len(unique_plating_stk_nos)}): {unique_plating_stk_nos}")
            print(f"[DEBUG] UNIQUE polish_stk_nos ({len(unique_polish_stk_nos)}): {unique_polish_stk_nos}")
            print(f"[DEBUG] UNIQUE versions ({len(unique_versions)}): {unique_versions}")

            # Extract foreign key display values
            plating_color_display = "N/A"
            if unload.plating_color:
                plating_color_display = getattr(unload.plating_color, 'plating_color', str(unload.plating_color))
            
            polish_finish_display = "N/A"
            if unload.polish_finish:
                polish_finish_display = getattr(unload.polish_finish, 'polish_finish', str(unload.polish_finish))
            
            # Use the first version from all_versions or fallback
            version_display = all_versions[0] if all_versions else "N/A"

            # ✅ ENHANCED: Create comprehensive table data entry using SAVED LIST FIELDS
            table_entry = {
                # Basic fields
                'id': unload.id,
                'lot_id': unload.lot_id,
                'jig_qr_id': jig_qr_id,
                'combine_lot_ids': unload.combine_lot_ids,
                'total_case_qty': unload.total_case_qty,
                'missing_qty': unload.missing_qty,
                
                # ✅ PRIMARY: Stock numbers (using first value from saved lists)
                'plating_stk_no': all_plating_stk_nos[0] if all_plating_stk_nos else (unload.plating_stk_no or "N/A"),
                'polish_stk_no': all_polish_stk_nos[0] if all_polish_stk_nos else (unload.polish_stk_no or "N/A"),
                
                # ✅ ALL VALUES INCLUDING DUPLICATES (from saved database fields)
                'all_plating_stk_nos': all_plating_stk_nos,
                'all_polishing_stk_nos': all_polish_stk_nos,  # Using 'polishing' to match template expectations
                'all_versions': all_versions,
                
                # ✅ UNIQUE VALUES ONLY (for backward compatibility)
                'unique_plating_stk_nos': unique_plating_stk_nos,
                'unique_polishing_stk_nos': unique_polish_stk_nos,  # Using 'polishing' to match original name
                'unique_versions': unique_versions,
                
                # Foreign key displays
                'plating_color': plating_color_display,
                'polish_finish': polish_finish_display,
                'polish_finish_name': polish_finish_display,
                'version': version_display,  # First version from ALL list or fallback
                
                # Location
                'location': location_display,
                'unique_locations': location_names if location_names else ["N/A"],
                
                # Tray information (using dynamic capacity)
                'tray_type': tray_type_display,
                'tray_capacity': tray_capacity,  # Using calculated dynamic capacity
                'jig_type': tray_type_display,  # Alias for template
                'jig_capacity': tray_capacity,  # Using calculated dynamic capacity
                'no_of_trays': no_of_trays,
                'calculated_no_of_trays': no_of_trays,
                'last_process_module': unload.last_process_module,
                
                # Dates
                'created_at': unload.created_at,
                'un_loaded_date_time': unload.Un_loaded_date_time,
                'Un_loaded_date_time': unload.Un_loaded_date_time,
                
                # Status fields
                'jig_unload_draft': False,  # Default for completed
                'electroplating_only': False,  # Default
                
                # ✅ ENHANCED: Model data with comprehensive fetching
                'no_of_model_cases': no_of_model_cases,
                'model_images': model_images,
                'model_colors': model_colors,
                'lot_id_quantities': lot_id_quantities,
                'lot_id_model_map': {},  # Can be populated if needed
                
                # Remarks
                'unloading_remarks': unloading_remarks,
                
                # Bath numbers - fetch dynamically from JigCompleted
                'bath_numbers': {'bath_number': self._resolve_bath_number_for_completed(unload, jig_qr_id)},
            }
            
            print(f"[DEBUG] ✅ Created table entry for {unload.lot_id}")
            table_data.append(table_entry)

        print(f"\n[DEBUG] ===== FINAL SUMMARY =====")
        print(f"[DEBUG] Total table_data entries: {len(table_data)}")
        
        # Add pagination with consistent logic as Inprocess Inspection
        page_number = self.request.GET.get('page', 1)
        paginator = Paginator(table_data, 10)  # 10 items per page like Inprocess Inspection
        page_obj = paginator.get_page(page_number)
        
        print(f"\n📄 Jig Unloading Completed - Pagination: Page {page_number}, Total items: {len(table_data)}")
        print(f"📄 Current page items: {len(page_obj.object_list)}")
        print(f"📄 Total pages: {paginator.num_pages}")
        
        # ✅ CONTEXT: Use consistent context variable name with pagination
        context['page_obj'] = page_obj  # For pagination controls
        context['completed_unloads'] = page_obj  # For table data
        context['debug'] = True  # Enable debug section in template (remove in production)
        
        # 🔥 NEW: Add date filter context variables
        context['from_date'] = from_date
        context['to_date'] = to_date
        
        return context


# =============================================================================
# ZONE 1 UNLOADING APIs — All names end with _z1
# Principle: "Frontend displays. Backend decides."
# =============================================================================

@method_decorator(csrf_exempt, name='dispatch')
class GetUnloadModelsZ1View(APIView):
    """
    GET /api/get_unload_models_z1/?jig_completed_id=<id>
    Returns computed model list with tray info for unload modal.
    """

    def _resolve_lot_id_to_model_z1(self, lot_id):
        """Resolve lot_id → model plating_stk_no via TotalStock/Recovery path"""
        tsm = TotalStockModel.objects.filter(lot_id=lot_id).select_related('batch_id__model_stock_no').first()
        if tsm and tsm.batch_id:
            mmc = ModelMasterCreation.objects.filter(id=tsm.batch_id.id).select_related('model_stock_no__tray_type').first()
            if mmc:
                return mmc
        # Recovery fallback
        rsm = RecoveryStockModel.objects.filter(lot_id=lot_id).select_related('batch_id').first()
        if rsm and rsm.batch_id:
            try:
                from Recovery_DP.models import RecoveryMasterCreation
                rmc = RecoveryMasterCreation.objects.filter(id=rsm.batch_id.id).select_related('model_stock_no__tray_type').first()
                if rmc:
                    return rmc
            except ImportError:
                pass
        return None

    def _get_tray_info_z1(self, model_master):
        """Get tray_type, tray_capacity, tray_code, tray_color from ModelMaster.
        All values are read directly from the TrayType DB record — no hardcoding.
        TrayType.tray_type (e.g. NR, NB, ND, JB, JR) IS the tray_code.
        TrayType.tray_capacity is the authoritative capacity from DB.
        TrayType.tray_color is the authoritative color from DB.
        """
        if not model_master:
            return '', 20, '', ''
        tray_type_obj = model_master.tray_type
        if tray_type_obj:
            tray_code     = tray_type_obj.tray_type or ''      # e.g. NR, NB, ND, JB, JR, JD, NL
            tray_capacity = tray_type_obj.tray_capacity or 20  # from DB — never hardcoded
            tray_color    = tray_type_obj.tray_color or ''     # e.g. Red, Blue, D.Green, L.Green
            return tray_code, tray_capacity, tray_code, tray_color
        # Fallback: ModelMaster.tray_capacity (direct field)
        tray_capacity = model_master.tray_capacity or 20
        return '', tray_capacity, '', ''

    def get(self, request):
        jig_completed_id = request.GET.get('jig_completed_id')
        if not jig_completed_id:
            return Response({'error': 'jig_completed_id is required'}, status=400)

        try:
            jc = JigCompleted.objects.get(id=jig_completed_id)
        except JigCompleted.DoesNotExist:
            return Response({'error': 'JigCompleted not found'}, status=404)

        draft_data = jc.draft_data or {}
        jig_id = jc.jig_id or ''

        # ---------------------------------------------------------------
        # STEP 1: Build per-lot effective qty + tray list from draft_data.
        # Use tray_data[].delink_qty (effective qty after delinks) summed
        # per source_lot_id.  This is the ONLY authoritative source for
        # what is physically on the jig.
        # ---------------------------------------------------------------
        raw_tray_data = draft_data.get('tray_data', [])
        per_lot_trays = {}   # {lot_id: [{tray_id, qty, top_tray}]}
        per_lot_qty   = {}   # {lot_id: total_effective_qty}
        for entry in raw_tray_data:
            src = entry.get('source_lot_id', '')
            dq  = entry.get('delink_qty', 0)
            if not src or dq == 0:
                continue  # Fully-delinked tray — skip
            top = entry.get('top_tray', False)
            tid = entry.get('tray_id', '')
            per_lot_qty[src] = per_lot_qty.get(src, 0) + dq
            per_lot_trays.setdefault(src, []).append(
                {'tray_id': tid, 'qty': dq, 'top_tray': top}
            )

        # ---------------------------------------------------------------
        # STEP 2: Determine lot order and qty.
        # Priority: multi_model_allocation > per_lot_qty > legacy fallback
        # ---------------------------------------------------------------
        alloc = draft_data.get('multi_model_allocation', [])
        if alloc:
            lot_entries = []
            for a in alloc:
                lid = a['lot_id']
                # Prefer delink_qty sum; fall back to allocated_qty
                qty = per_lot_qty.get(lid, a.get('allocated_qty', 0))
                lot_entries.append((lid, a.get('model', ''), qty))
        elif per_lot_qty:
            lot_entries = [(lid, '', qty) for lid, qty in per_lot_qty.items()]
        else:
            # Legacy fallback — use loaded_cases_qty (never original_lot_qty)
            qty = jc.loaded_cases_qty or jc.updated_lot_qty or jc.original_lot_qty or 0
            lot_entries = [(jc.lot_id, '', qty)]

        # ---------------------------------------------------------------
        # STEP 3: Build model list
        # ---------------------------------------------------------------
        models_list = []
        for lot_id, model_hint, qty in lot_entries:
            if qty == 0:
                continue  # Nothing physically on jig for this lot

            mmc = self._resolve_lot_id_to_model_z1(lot_id)
            if mmc:
                plating_stk_no   = getattr(mmc, 'plating_stk_no', None) or ''
                polishing_stk_no = getattr(mmc, 'polishing_stk_no', None) or ''
                # Look up ModelMaster by plating_stk_no (not model_stock_no FK
                # which may point to the polishing model with wrong tray type).
                plating_model = ModelMaster.objects.filter(
                    plating_stk_no=plating_stk_no
                ).select_related('tray_type').first() if plating_stk_no else None
                model_stock = plating_model if plating_model else mmc.model_stock_no
                tray_type, tray_capacity, tray_code, tray_color = self._get_tray_info_z1(model_stock)
                images = []
                if model_stock:
                    images = [img.master_image.url for img in model_stock.images.all() if img.master_image]
                if not images:
                    images = [img.master_image.url for img in mmc.images.all() if img.master_image]
            else:
                plating_stk_no   = model_hint or draft_data.get('plating_stock_num', lot_id)
                polishing_stk_no = ''
                tray_type, tray_capacity, tray_code, tray_color = 'Normal', 20, 'N', ''
                images = []

            # ---------------------------------------------------------------
            # STEP 4: Always recompute tray slots using DB capacity.
            #   - Top tray (partial / remainder qty) is ALWAYS slot 1.
            #   - Full trays follow after it.
            # ---------------------------------------------------------------
            cap = tray_capacity if tray_capacity > 0 else 20
            num_trays = math.ceil(qty / cap) if qty > 0 else 1
            remainder = qty % cap if qty % cap != 0 else cap  # top-tray qty
            tray_slots = []
            for i in range(num_trays):
                is_top = (i == 0)
                slot_qty = remainder if is_top else cap
                tray_slots.append({
                    'slot': i + 1,
                    'tray_id': '',
                    'qty': slot_qty,
                    'is_top_tray': is_top,
                    'editable_qty': is_top,
                })

            num_trays = len(tray_slots)

            # Check if already submitted
            # Check if already submitted (final, not draft)
            is_unloaded = JUSubmittedZ1.objects.filter(
                jig_completed_id=jig_completed_id, lot_id=lot_id, is_draft=False
            ).exists()

            # Load draft or final submitted data for pre-fill
            submitted_data = None
            sub = JUSubmittedZ1.objects.filter(
                jig_completed_id=jig_completed_id, lot_id=lot_id
            ).order_by('-submitted_at').first()
            if sub:
                submitted_data = {
                    'tray_data': sub.tray_data,
                    'missing_qty': sub.missing_qty,
                    'top_tray_remark': sub.top_tray_remark,
                    'is_draft': sub.is_draft,
                }

            # Determine draft status for this model
            has_draft = bool(submitted_data and submitted_data.get('is_draft'))

            models_list.append({
                'lot_id': lot_id,
                'model_no': plating_stk_no or lot_id,
                'polishing_stk_no': polishing_stk_no,
                'qty': qty,
                'tray_type': tray_type,
                'tray_capacity': tray_capacity,
                'tray_code': tray_code,
                'tray_color': tray_color,
                'num_trays': num_trays,
                'tray_slots': tray_slots,
                'is_unloaded': is_unloaded,
                'is_draft': has_draft,
                'submitted_data': submitted_data,
                'images': images,
                'jig_id': jig_id,
            })

        is_multi_model = len(models_list) > 1

        # ---------------------------------------------------------------
        # STEP 5: Process additional jig IDs (Add Model merge).
        # If plating_stk_no matches an existing model → merge qty.
        # If different → add as separate row.
        # ---------------------------------------------------------------
        additional_ids = request.GET.getlist('additional_jig_ids')
        for add_id in additional_ids:
            try:
                add_jc = JigCompleted.objects.get(id=add_id)
            except JigCompleted.DoesNotExist:
                continue

            add_draft = add_jc.draft_data or {}
            add_jig_id = add_jc.jig_id or ''

            # Build lot entries for additional jig (same STEP 1+2 logic)
            add_raw_tray = add_draft.get('tray_data', [])
            add_plq = {}
            for e in add_raw_tray:
                src = e.get('source_lot_id', '')
                dq = e.get('delink_qty', 0)
                if src and dq > 0:
                    add_plq[src] = add_plq.get(src, 0) + dq

            add_alloc = add_draft.get('multi_model_allocation', [])
            if add_alloc:
                add_lots = [
                    (a['lot_id'], a.get('model', ''),
                     add_plq.get(a['lot_id'], a.get('allocated_qty', 0)))
                    for a in add_alloc
                ]
            elif add_plq:
                add_lots = [(lid, '', q) for lid, q in add_plq.items()]
            else:
                q = add_jc.loaded_cases_qty or add_jc.updated_lot_qty or add_jc.original_lot_qty or 0
                add_lots = [(add_jc.lot_id, '', q)]

            for a_lot_id, a_model_hint, a_qty in add_lots:
                if a_qty == 0:
                    continue

                a_mmc = self._resolve_lot_id_to_model_z1(a_lot_id)
                if a_mmc:
                    a_plating = getattr(a_mmc, 'plating_stk_no', None) or ''
                    a_polishing = getattr(a_mmc, 'polishing_stk_no', None) or ''
                else:
                    a_plating = a_model_hint or add_draft.get('plating_stock_num', a_lot_id)
                    a_polishing = ''

                # Try to merge with existing model by plating_stk_no
                merged = False
                for m in models_list:
                    if m['model_no'] == a_plating and a_plating:
                        # MERGE: same plating_stk_no — keep primary qty, note added jig for record
                        if add_jig_id and add_jig_id not in m['jig_id']:
                            m['jig_id'] = m['jig_id'] + ', ' + add_jig_id
                        info = f'similar model added ({add_jig_id} +{a_qty})'
                        m.setdefault('merged_info', '')
                        m['merged_info'] = (m['merged_info'] + '; ' + info) if m['merged_info'] else info
                        m.setdefault('merged_lots', [])
                        m['merged_lots'].append({
                            'jig_completed_id': int(add_id),
                            'lot_id': a_lot_id,
                            'qty': a_qty,
                            'jig_id': add_jig_id,
                        })
                        # Keep primary qty and tray slots unchanged — scan is for primary jig only
                        merged = True
                        break

                if not merged:
                    # Different model — add as separate row
                    if a_mmc:
                        plating_model = ModelMaster.objects.filter(
                            plating_stk_no=a_plating
                        ).select_related('tray_type').first() if a_plating else None
                        a_model_stock = plating_model if plating_model else a_mmc.model_stock_no
                        a_tt, a_tc, a_tcode, a_tcolor = self._get_tray_info_z1(a_model_stock)
                        a_images = []
                        if a_model_stock:
                            a_images = [img.master_image.url for img in a_model_stock.images.all() if img.master_image]
                        if not a_images:
                            a_images = [img.master_image.url for img in a_mmc.images.all() if img.master_image]
                    else:
                        a_tt, a_tc, a_tcode, a_tcolor = 'Normal', 20, 'N', ''
                        a_images = []

                    a_cap = a_tc if a_tc > 0 else 20
                    a_ntrays = math.ceil(a_qty / a_cap) if a_qty > 0 else 1
                    a_rem = a_qty % a_cap if a_qty % a_cap != 0 else a_cap
                    a_tslots = [
                        {'slot': i + 1, 'tray_id': '', 'qty': a_rem if i == 0 else a_cap,
                         'is_top_tray': i == 0, 'editable_qty': i == 0}
                        for i in range(a_ntrays)
                    ]

                    models_list.append({
                        'lot_id': a_lot_id,
                        'model_no': a_plating or a_lot_id,
                        'polishing_stk_no': a_polishing,
                        'qty': a_qty,
                        'tray_type': a_tt,
                        'tray_capacity': a_tc,
                        'tray_code': a_tcode,
                        'tray_color': a_tcolor,
                        'num_trays': len(a_tslots),
                        'tray_slots': a_tslots,
                        'is_unloaded': False,
                        'is_draft': False,
                        'submitted_data': None,
                        'images': a_images,
                        'jig_id': add_jig_id,
                        'added_jig_completed_id': int(add_id),
                    })

        is_multi_model = len(models_list) > 1
        all_unloaded = all(m['is_unloaded'] for m in models_list) if models_list else False

        return Response({
            'jig_completed_id': int(jig_completed_id),
            'jig_qr_id': jig_id,
            'models': models_list,
            'is_multi_model': is_multi_model,
            'all_unloaded': all_unloaded,
        })


@method_decorator(csrf_exempt, name='dispatch')
class SaveModelUnloadZ1View(APIView):
    """
    POST /api/save_model_unload_z1/
    Saves tray scan data for one model. Creates/updates JUSubmittedZ1 record.
    """
    def post(self, request):
        data = request.data
        jig_completed_id = data.get('jig_completed_id')
        lot_id = data.get('lot_id')
        model_no = data.get('model_no')
        tray_data = data.get('tray_data', [])
        total_qty = data.get('total_qty', 0)
        missing_qty = data.get('missing_qty', 0)
        top_tray_remark = data.get('top_tray_remark', '')
        tray_type = data.get('tray_type', '')
        tray_capacity = data.get('tray_capacity', 0)
        tray_code = data.get('tray_code', '')
        tray_color = data.get('tray_color', '')

        if not jig_completed_id or not lot_id or not model_no:
            return Response({'error': 'jig_completed_id, lot_id, and model_no are required'}, status=400)

        is_draft = data.get('is_draft', False)

        # Validate tray IDs (only for final save, not draft)
        if not is_draft:
            seen_tray_ids = set()
            for tray in tray_data:
                tray_id = tray.get('tray_id', '')
                if len(tray_id) > 9:
                    return Response({'error': f'Tray ID "{tray_id}" exceeds 9 characters'}, status=400)
                if not tray_id:
                    return Response({'error': 'All tray slots must be scanned'}, status=400)
                if tray_id in seen_tray_ids:
                    return Response({'error': f'Duplicate tray ID "{tray_id}" — each tray must be unique'}, status=400)
                seen_tray_ids.add(tray_id)
                # Tray code prefix validation: tray_id must start with the expected tray_code prefix
                if tray_code:
                    expected_prefix = tray_code.upper() + '-'
                    if not tray_id.upper().startswith(expected_prefix):
                        return Response({
                            'error': f'Tray ID "{tray_id}" does not match expected tray code "{tray_code}". '
                                     f'Expected prefix: {expected_prefix}'
                        }, status=400)

                # Tray occupancy validation: reject trays already assigned to another lot
                existing_tray = TrayId.objects.filter(tray_id=tray_id).first()
                if existing_tray:
                    # Already scanned and not delinked → occupied
                    if existing_tray.scanned and not existing_tray.delink_tray:
                        return Response({
                            'error': f'Tray "{tray_id}" is already scanned and occupied by lot {existing_tray.lot_id}. '
                                     f'Please use a free tray or delink this one first.'
                        }, status=400)
                    # Has a lot_id, not delinked, and belongs to a different lot → occupied
                    if existing_tray.lot_id and not existing_tray.delink_tray and existing_tray.lot_id != lot_id:
                        return Response({
                            'error': f'Tray "{tray_id}" is assigned to another lot ({existing_tray.lot_id}). '
                                     f'Please use a free tray or delink this one first.'
                        }, status=400)

        # Top tray remark validation (only if qty was edited, only on final save)
        if not is_draft:
            for tray in tray_data:
                if tray.get('is_top_tray') and tray.get('qty_edited') and not top_tray_remark.strip():
                    return Response({'error': 'Top tray remark is required when quantity is edited'}, status=400)

        try:
            jc = JigCompleted.objects.get(id=jig_completed_id)
        except JigCompleted.DoesNotExist:
            return Response({'error': 'JigCompleted not found'}, status=404)

        jig_qr_id = jc.jig_id or jc.lot_id

        # Create or update JUSubmittedZ1
        obj, created = JUSubmittedZ1.objects.update_or_create(
            jig_completed_id=jig_completed_id,
            lot_id=lot_id,
            defaults={
                'jig_qr_id': jig_qr_id,
                'model_no': model_no,
                'total_qty': total_qty,
                'tray_type': tray_type,
                'tray_capacity': tray_capacity,
                'tray_code': tray_code,
                'tray_color': tray_color,
                'num_trays': len(tray_data),
                'tray_data': tray_data,
                'missing_qty': missing_qty,
                'top_tray_remark': top_tray_remark,
                'is_draft': is_draft,
                'submitted_by': request.user if request.user.is_authenticated else None,
            }
        )

        # Save records for merged lots (Add Model with same plating_stk_no)
        merged_lots = data.get('merged_lots', [])
        for ml in merged_lots:
            ml_jc_id = ml.get('jig_completed_id')
            ml_lot_id = ml.get('lot_id')
            ml_jig_id = ml.get('jig_id', '')
            ml_qty = ml.get('qty', 0)
            if ml_jc_id and ml_lot_id:
                JUSubmittedZ1.objects.update_or_create(
                    jig_completed_id=ml_jc_id,
                    lot_id=ml_lot_id,
                    defaults={
                        'jig_qr_id': ml_jig_id,
                        'model_no': model_no,
                        'total_qty': ml_qty,
                        'tray_type': tray_type,
                        'tray_capacity': tray_capacity,
                        'tray_code': tray_code,
                        'tray_color': tray_color,
                        'num_trays': len(tray_data),
                        'tray_data': tray_data,
                        'missing_qty': missing_qty,
                        'top_tray_remark': top_tray_remark,
                        'is_draft': is_draft,
                        'submitted_by': request.user if request.user.is_authenticated else None,
                    }
                )

        # Check if all models for this jig are now unloaded
        draft_data = jc.draft_data or {}
        # Build all_lot_ids: prefer multi_model_allocation → lot_id_quantities → fallback
        _alloc = draft_data.get('multi_model_allocation', [])
        lot_id_quantities = draft_data.get('lot_id_quantities', {})
        if _alloc:
            all_lot_ids = set(a['lot_id'] for a in _alloc if a.get('lot_id'))
        elif lot_id_quantities:
            all_lot_ids = set(lot_id_quantities.keys())
        else:
            all_lot_ids = {jc.lot_id}
        submitted_lot_ids = set(
            JUSubmittedZ1.objects.filter(
                jig_completed_id=jig_completed_id, is_draft=False
            ).values_list('lot_id', flat=True)
        )
        all_unloaded = all_lot_ids.issubset(submitted_lot_ids)

        return Response({
            'success': True,
            'created': created,
            'all_unloaded': all_unloaded,
            'message': f'Model {model_no} tray data saved successfully',
        })


@method_decorator(csrf_exempt, name='dispatch')
class SubmitAllUnloadZ1View(APIView):
    """
    POST /api/submit_all_unload_z1/
    Final submission: unlocks jig, marks JigCompleted as fully unloaded.
    """
    def post(self, request):
        jig_completed_id = request.data.get('jig_completed_id')
        if not jig_completed_id:
            return Response({'error': 'jig_completed_id is required'}, status=400)

        try:
            jc = JigCompleted.objects.get(id=jig_completed_id)
        except JigCompleted.DoesNotExist:
            return Response({'error': 'JigCompleted not found'}, status=404)

        # Verify all models are unloaded
        draft_data = jc.draft_data or {}
        # Build all_lot_ids: prefer multi_model_allocation → lot_id_quantities → fallback
        _alloc = draft_data.get('multi_model_allocation', [])
        lot_id_quantities = draft_data.get('lot_id_quantities', {})
        if _alloc:
            all_lot_ids = set(a['lot_id'] for a in _alloc if a.get('lot_id'))
            # Build lot_id_quantities from allocation for qty lookup
            if not lot_id_quantities:
                lot_id_quantities = {a['lot_id']: a.get('allocated_qty', 0) for a in _alloc}
        elif lot_id_quantities:
            all_lot_ids = set(lot_id_quantities.keys())
        else:
            all_lot_ids = {jc.lot_id}
            lot_id_quantities = {jc.lot_id: jc.updated_lot_qty or 0}
        submitted_lot_ids = set(
            JUSubmittedZ1.objects.filter(
                jig_completed_id=jig_completed_id, is_draft=False
            ).values_list('lot_id', flat=True)
        )

        if not all_lot_ids.issubset(submitted_lot_ids):
            missing = all_lot_ids - submitted_lot_ids
            return Response({
                'error': f'Not all models have been unloaded. Missing: {list(missing)}'
            }, status=400)

        # Mark JigCompleted as fully unloaded
        jc.last_process_module = 'Jig Unloading'
        jc.save(update_fields=['last_process_module'])

        # Unlock the jig for reuse in Jig Loading
        jig_qr_id = jc.jig_id
        if jig_qr_id:
            Jig.objects.filter(jig_qr_id=jig_qr_id).update(
                is_loaded=False,
                current_user=None,
                locked_at=None,
                drafted=False,
                batch_id=None,
                lot_id=None,
            )

        # Create ONE JigUnloadAfterTable record per jig (all models combined)
        # This ensures multi-model jigs display ALL models in the completed table
        from django.utils import timezone

        all_combine_lot_ids = list(all_lot_ids)
        total_qty = 0
        for lid in all_lot_ids:
            sub = JUSubmittedZ1.objects.filter(
                jig_completed_id=jig_completed_id, lot_id=lid, is_draft=False
            ).first()
            total_qty += (sub.total_qty if sub else lot_id_quantities.get(lid, 0))

        # Idempotency: check if a record already exists for any of these lot_ids
        existing = None
        for lid in all_combine_lot_ids:
            existing = JigUnloadAfterTable.objects.filter(
                combine_lot_ids__contains=[lid]
            ).first()
            if existing:
                break

        if existing:
            after_table = existing
            changed_fields = []
            if not existing.last_process_module:
                existing.last_process_module = 'Jig Unloading'
                changed_fields.append('last_process_module')
            if not existing.Un_loaded_date_time:
                existing.Un_loaded_date_time = timezone.now()
                changed_fields.append('Un_loaded_date_time')
            # Ensure combine_lot_ids has ALL lot_ids
            if set(all_combine_lot_ids) != set(existing.combine_lot_ids or []):
                existing.combine_lot_ids = all_combine_lot_ids
                existing.total_case_qty = total_qty
                changed_fields.extend(['combine_lot_ids', 'total_case_qty'])
            if changed_fields:
                existing.save(update_fields=list(set(changed_fields)))
        else:
            # Pre-populate list fields from ALL lot_ids
            plating_stk_no_list = []
            polish_stk_no_list = []
            version_list = []
            for lid in all_combine_lot_ids:
                try:
                    tsm = TotalStockModel.objects.filter(lot_id=lid).select_related('batch_id').first()
                    if tsm and tsm.batch_id:
                        mmc = ModelMasterCreation.objects.select_related('version').filter(
                            id=tsm.batch_id.id
                        ).first()
                        if mmc:
                            if mmc.plating_stk_no:
                                plating_stk_no_list.append(mmc.plating_stk_no)
                            if mmc.polishing_stk_no:
                                polish_stk_no_list.append(mmc.polishing_stk_no)
                            if mmc.version and hasattr(mmc.version, 'version_internal'):
                                version_list.append(mmc.version.version_internal)
                except Exception as e:
                    print(f"⚠️ Error populating lists for {lid}: {e}")

            after_table = JigUnloadAfterTable(
                jig_qr_id=jig_qr_id or jc.lot_id,
                combine_lot_ids=all_combine_lot_ids,
                total_case_qty=total_qty,
                selected_user=request.user if request.user.is_authenticated else None,
                Un_loaded_date_time=timezone.now(),
                last_process_module='Jig Unloading',
                plating_stk_no_list=plating_stk_no_list,
                polish_stk_no_list=polish_stk_no_list,
                version_list=version_list,
            )
            after_table.save()

        # Build response records
        created_records = []
        for lid in all_lot_ids:
            sub = JUSubmittedZ1.objects.filter(
                jig_completed_id=jig_completed_id, lot_id=lid, is_draft=False
            ).first()
            created_records.append({
                'lot_id': lid,
                'model_no': sub.model_no if sub else '',
                'unload_lot_id': after_table.unload_lot_id,
                'qty': sub.total_qty if sub else lot_id_quantities.get(lid, 0),
            })

        return Response({
            'success': True,
            'message': 'Jig unloading submitted successfully. Jig unlocked for reuse.',
            'records': created_records,
            'unload_lot_id': after_table.unload_lot_id or '',
        })


@method_decorator(csrf_exempt, name='dispatch')
class GetUnloadViewZ1View(APIView):
    """
    GET /api/get_unload_view_z1/?jig_completed_id=<id>
    Returns submitted data for read-only view.
    """
    def get(self, request):
        jig_completed_id = request.GET.get('jig_completed_id')
        if not jig_completed_id:
            return Response({'error': 'jig_completed_id is required'}, status=400)

        records = JUSubmittedZ1.objects.filter(
            jig_completed_id=jig_completed_id
        ).order_by('model_no')

        if not records.exists():
            return Response({'error': 'No submitted records found'}, status=404)

        result = []
        for rec in records:
            result.append({
                'model_no': rec.model_no,
                'lot_id': rec.lot_id,
                'total_qty': rec.total_qty,
                'tray_type': rec.tray_type,
                'tray_capacity': rec.tray_capacity,
                'tray_code': rec.tray_code,
                'tray_color': rec.tray_color,
                'num_trays': rec.num_trays,
                'tray_data': rec.tray_data,
                'missing_qty': rec.missing_qty,
                'top_tray_remark': rec.top_tray_remark,
                'submitted_at': rec.submitted_at.strftime('%d-%b-%Y %I:%M %p') if rec.submitted_at else '',
                'submitted_by': rec.submitted_by.username if rec.submitted_by else 'System',
            })

        return Response({
            'jig_completed_id': int(jig_completed_id),
            'records': result,
        })


@method_decorator(csrf_exempt, name='dispatch')
class JigUnloadPickRemarkZ1View(APIView):
    """
    POST /api/save_jig_pick_remark_z1/
    Saves unloading_remarks on JigCompleted record.
    """
    def post(self, request):
        try:
            data = request.data
            jig_completed_id = data.get('jig_completed_id')
            remark = (data.get('unloading_remarks') or '').strip()
            if not jig_completed_id:
                return Response({'success': False, 'error': 'jig_completed_id is required'}, status=400)
            try:
                jc = JigCompleted.objects.get(id=jig_completed_id)
            except JigCompleted.DoesNotExist:
                return Response({'success': False, 'error': 'JigCompleted not found'}, status=404)
            jc.unloading_remarks = remark
            jc.save(update_fields=['unloading_remarks'])
            return Response({'success': True, 'message': 'Remark saved'})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class GetJigForTrayZ1View(APIView):
    """
    GET /api/get_jig_for_tray_z1/?tray_id=<id>
    Searches JigCompleted draft_data for a tray ID and returns matching jig info.
    Used by the scan button to locate jigs across pagination.
    """
    def get(self, request):
        tray_id = request.GET.get('tray_id', '').strip()
        if not tray_id:
            return Response({'success': False, 'error': 'Tray ID is required'})

        try:
            # Search in scanned_trays JSONField
            all_jigs = JigCompleted.objects.filter(
                draft_status='submitted'
            )
            for jc in all_jigs:
                scanned = jc.scanned_trays or []
                for tray_entry in scanned:
                    if isinstance(tray_entry, dict) and tray_entry.get('tray_id') == tray_id:
                        return Response({
                            'success': True,
                            'jig_completed_id': jc.id,
                            'lot_id': jc.lot_id,
                            'jig_id': jc.jig_id or jc.lot_id,
                        })

            # Fallback: search in draft_data tray slots
            for jc in all_jigs:
                dd = jc.draft_data or {}
                if isinstance(dd, dict):
                    alloc = dd.get('multi_model_allocation', [])
                    for model_alloc in alloc:
                        for tray_entry in (model_alloc.get('tray_data') or []):
                            if isinstance(tray_entry, dict) and tray_entry.get('tray_id') == tray_id:
                                return Response({
                                    'success': True,
                                    'jig_completed_id': jc.id,
                                    'lot_id': jc.lot_id,
                                    'jig_id': jc.jig_id or jc.lot_id,
                                })

            # Search in JUSubmittedZ1 tray_data
            submitted = JUSubmittedZ1.objects.all()
            for rec in submitted:
                for tray_entry in (rec.tray_data or []):
                    if isinstance(tray_entry, dict) and tray_entry.get('tray_id') == tray_id:
                        try:
                            jc = JigCompleted.objects.get(id=rec.jig_completed_id)
                            return Response({
                                'success': True,
                                'jig_completed_id': jc.id,
                                'lot_id': jc.lot_id,
                                'jig_id': jc.jig_id or jc.lot_id,
                            })
                        except JigCompleted.DoesNotExist:
                            pass

            return Response({'success': False, 'error': 'Tray ID not found in any jig'})

        except Exception as e:
            return Response({'success': False, 'error': f'System error: {str(e)}'}, status=500)


@require_GET
def validate_tray_occupancy_z1(request):
    """
    GET /api/validate_tray_occupancy_z1/?tray_id=XX&lot_id=YY
    Real-time tray occupancy check for Jig Unloading Z1/Z2 tray scan.
    Returns success=True if tray is free/delinked/belongs to current lot.
    Returns success=False with error message if tray is occupied by another lot.
    """
    tray_id = request.GET.get('tray_id', '').strip()
    lot_id = request.GET.get('lot_id', '').strip()

    if not tray_id:
        return JsonResponse({'success': False, 'error': 'Tray ID is required'}, status=400)

    try:
        existing_tray = TrayId.objects.filter(tray_id=tray_id).first()
        if not existing_tray:
            # Tray not in system — accept it (will be created on save)
            return JsonResponse({'success': True, 'message': 'Tray ID not in system — new tray'})

        # Already scanned and not delinked → occupied
        if existing_tray.scanned and not existing_tray.delink_tray:
            return JsonResponse({
                'success': False,
                'error': f'Tray "{tray_id}" is already scanned and occupied by lot {existing_tray.lot_id}. '
                         f'Please use a free tray or delink this one first.'
            })

        # Has a lot_id, not delinked, and belongs to a different lot → occupied
        if existing_tray.lot_id and not existing_tray.delink_tray:
            if lot_id and existing_tray.lot_id != lot_id:
                return JsonResponse({
                    'success': False,
                    'error': f'Tray "{tray_id}" is assigned to another lot ({existing_tray.lot_id}). '
                             f'Please use a free tray or delink this one first.'
                })

        # Tray is free or delinked or belongs to current lot
        return JsonResponse({'success': True, 'message': 'Tray is available'})

    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Validation error: {str(e)}'}, status=500)


@require_GET
def jig_unload_view_tray_list_z1(request):
    """
    GET /jig_unload_view_tray_list/?lot_id=<UNLOT_ID>
    Returns tray list for the Completed table View icon.
    Sources data from JUSubmittedZ1 (Z1 unload modal) with fallback to JigUnload_TrayId.
    """
    lot_id = request.GET.get('lot_id', '').strip()
    if not lot_id:
        return JsonResponse({'success': False, 'error': 'lot_id is required'}, status=400)

    try:
        record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if not record:
            return JsonResponse({'success': False, 'error': f'Record not found for lot_id: {lot_id}'}, status=404)

        combine_lot_ids = record.combine_lot_ids or []
        if not combine_lot_ids:
            return JsonResponse({'success': False, 'error': 'No combine_lot_ids found'}, status=404)

        # Primary source: JUSubmittedZ1 tray_data (Z1 unload modal saves here)
        tray_list = []
        subs = JUSubmittedZ1.objects.filter(lot_id__in=combine_lot_ids, is_draft=False).order_by('id')
        for sub in subs:
            for entry in (sub.tray_data or []):
                tray_list.append({
                    'tray_id': entry.get('tray_id', ''),
                    'tray_quantity': entry.get('qty', 0),
                    'top_tray': entry.get('is_top_tray', False),
                })

        # Fallback: JigUnload_TrayId (old Zone 2 flow)
        if not tray_list:
            trays = JigUnload_TrayId.objects.filter(lot_id__in=combine_lot_ids).order_by('id')
            for tray in trays:
                tray_list.append({
                    'tray_id': tray.tray_id,
                    'tray_quantity': tray.tray_qty,
                    'top_tray': tray.top_tray,
                })

        return JsonResponse({'success': True, 'trays': tray_list})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_GET
def jig_unload_get_model_images_z1(request):
    """
    GET /get_model_images/?lot_id=<UNLOT_ID>
    Returns model images for the Completed table View icon.
    """
    import re
    lot_id = request.GET.get('lot_id', '').strip()
    model_number = request.GET.get('model_number', '').strip()

    if not lot_id:
        return JsonResponse({'success': False, 'error': 'lot_id required'}, status=400)

    try:
        model = None
        model_no = None

        # Method 1: JigUnloadAfterTable → plating_stk_no → ModelMaster
        jig_unload = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload and jig_unload.plating_stk_no:
            candidate = ModelMaster.objects.prefetch_related('images').filter(
                plating_stk_no=jig_unload.plating_stk_no
            ).first()
            if candidate:
                model = candidate
                model_no = jig_unload.plating_stk_no

        # Method 2: JigUnloadAfterTable → polish_stk_no → ModelMaster by model_no
        if not model and jig_unload and jig_unload.polish_stk_no:
            raw_no = jig_unload.polish_stk_no.split('X')[0] if 'X' in jig_unload.polish_stk_no else jig_unload.polish_stk_no
            candidate = ModelMaster.objects.prefetch_related('images').filter(model_no=raw_no).first()
            if candidate:
                model = candidate
                model_no = raw_no

        # Method 3: combine_lot_ids → TotalStockModel → ModelMasterCreation → ModelMaster
        if not model and jig_unload:
            combine_lot_ids = jig_unload.combine_lot_ids or []
            for clid in combine_lot_ids:
                tsm = TotalStockModel.objects.filter(lot_id=clid).select_related('batch_id__model_stock_no').first()
                if tsm and tsm.batch_id and tsm.batch_id.model_stock_no:
                    candidate = ModelMaster.objects.prefetch_related('images').filter(pk=tsm.batch_id.model_stock_no.pk).first()
                    if candidate:
                        model = candidate
                        model_no = candidate.plating_stk_no or candidate.model_no
                        break

        # Method 4: model_number param
        if not model and model_number:
            candidate = ModelMaster.objects.prefetch_related('images').filter(plating_stk_no=model_number).first()
            if candidate:
                model = candidate
                model_no = model_number

        if not model:
            return JsonResponse({'success': False, 'image': None, 'error': f'No model found for lot_id: {lot_id}'})

        images = [img.master_image.url for img in model.images.all() if img.master_image]
        if images:
            return JsonResponse({
                'success': True, 'image': images[0],
                'total_images': len(images), 'all_images': images, 'model_no': model_no,
            })
        else:
            return JsonResponse({'success': False, 'image': None, 'error': f'Model {model_no} has no images'})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from modelmasterapp.models import *
from rest_framework import status
from rest_framework.renderers import TemplateHTMLRenderer, JSONRenderer
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone  # Added timezone import
import json
from .serializers import *
import datetime
from InputScreening import *
from django.db import transaction
from django.db.models import Sum, Q
from django.db.models.functions import Cast
from django.db.models import IntegerField
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from adminportal.models import *
from .models import *
import traceback
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import os
from django.contrib.auth.models import Group
from django.http import JsonResponse
from django.contrib.auth import authenticate
from django.views.decorators.csrf import csrf_exempt
import json
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Module, UserModuleProvision
from Recovery_DP.models import *


def get_allowed_modules_for_user(user):
    if not user.is_authenticated:
        return []
    if (
        user.is_superuser
        or user.groups.filter(name__iexact="Admin").exists()
        or (
            hasattr(user, 'userprofile')
            and user.userprofile.department
            and user.userprofile.department.name.lower() == "admin"
        )
    ):
        return list(Module.objects.values_list('name', flat=True))
    # Use UserModuleProvision for per-user modules
    return list(
        UserModuleProvision.objects.filter(user=user)
        .values_list('module_name', flat=True)
        .distinct()
    )



@method_decorator(login_required(login_url='login-api'), name='dispatch')
class IndexView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'index.html'
 
    def get(self, request, format=None):
        # Get current date and format it
        from django.utils import timezone
        import datetime
        
        allowed_modules = get_allowed_modules_for_user(request.user)
        dashboard_stats = self.get_dashboard_stats(allowed_modules)
        
        context = { 
            'user': request.user,
            'allowed_modules': allowed_modules,
            'dashboard_stats': dashboard_stats,
            'current_date': timezone.now().strftime('%d %b %Y'),
        }
        response = Response(context)
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        return response
    
    def get_dashboard_stats(self, allowed_modules):
        """Fetch statistics for Day Planning module"""
        stats = []
        
        for module_name in allowed_modules:
            if 'DAYPLANNING' in module_name.upper().replace(' ', '') or 'DP' in module_name.upper():
                from modelmasterapp.models import ModelMasterCreation
                
                # Total lots = total batches with Draft_Saved=False
                total_lots = ModelMasterCreation.objects.filter(Draft_Saved=False).count()
                
                # Yet to Start = Draft_Saved=False
                yet_to_start = ModelMasterCreation.objects.filter(Draft_Saved=False).count()
                
                # Jumbo tray count
                jumbo_count = ModelMasterCreation.objects.filter(Draft_Saved=False, tray_type__icontains='Jumbo').count()
                
                # Normal tray count
                normal_count = ModelMasterCreation.objects.filter(Draft_Saved=False, tray_type__icontains='Normal').count()
                
                # Processed/Released = count of batches with "Released" status from completed table
                # "Released" if ip_person_qty_verified or draft_tray_verify or accepted_Ip_stock or few_cases_accepted_Ip_stock or rejected_ip_stock
                from modelmasterapp.models import TotalStockModel
                processed = TotalStockModel.objects.filter(
                    Q(ip_person_qty_verified=True) |
                    Q(draft_tray_verify=True) |
                    Q(accepted_Ip_stock=True) |
                    Q(few_cases_accepted_Ip_stock=True) |
                    Q(rejected_ip_stock=True)
                ).count()
                
                # In Progress = Jumbo count
                in_progress = jumbo_count
                
                # Drafted = Normal count
                drafted = normal_count
                
                # Calculate total lots as yet_to_start + processed
                total_lots = yet_to_start + processed
                
                # Calculate progress percentage
                progress_percent = int((processed / max(total_lots, 1)) * 100) if total_lots > 0 else 0
                yet_to_start_percent = int((yet_to_start / max(total_lots, 1)) * 100) if total_lots > 0 else 0
                drafted_percent = int((drafted / max(total_lots, 1)) * 100) if total_lots > 0 else 0
                in_progress_percent = int((in_progress / max(total_lots, 1)) * 100) if total_lots > 0 else 0
                
                labels = {
                    'total_lots': 'Total Rows (Yet to Start)',
                    'progress': 'Total Processed in Complete Table',
                    'in_progress': 'Jumbo Tray Count',
                    'status_overview': 'Status Overview'
                }
                
                stats.append({
                    'module': module_name,
                    'label': 'Day Planning',
                    'total_lot': total_lots,
                    'yet_to_start': yet_to_start,
                    'yet_to_start_percent': yet_to_start_percent,
                    'drafted': drafted,
                    'drafted_percent': drafted_percent,
                    'processed': processed,
                    'processed_percent': progress_percent,
                    'in_progress': in_progress,
                    'in_progress_percent': in_progress_percent,
                    'progress': progress_percent,
                    'completed_percent': progress_percent,
                    'moved_to_next_percent': in_progress_percent,
                    'color': '#008080',
                    'icon': 'mdi-package-variant-closed',
                    'labels': labels,
                })
                break  # Only add once
        
        for module_name in allowed_modules:
            if 'INPUTSCREENING' in module_name.upper().replace(' ', '') or 'IS' in module_name.upper():
                from modelmasterapp.models import ModelMasterCreation
                from InputScreening.models import IP_Accepted_TrayScan, IP_Rejected_TrayScan, IP_Accepted_TrayID_Store
                
                # Total rows in pick table = count of batches moved to D Picker
                total_input_qty = ModelMasterCreation.objects.filter(Moved_to_D_Picker=True).count()
                
                # Accepted count from accept table
                accepted_qty = IP_Accepted_TrayScan.objects.count()
                
                # Rejected count from reject table
                rejected_qty = IP_Rejected_TrayScan.objects.count()
                
                # Completed data from complete table
                completed_qty = IP_Accepted_TrayID_Store.objects.filter(is_save=True).count()
                
                stats.append({
                    'module': module_name,
                    'label': 'Input Screening',
                    'total_input_qty': total_input_qty,
                    'accepted_qty': accepted_qty,
                    'rejected_qty': rejected_qty,
                    'completed_qty': completed_qty,
                    'color': '#20b2aa',
                    'icon': 'mdi-magnify',
                })
                break  # Only add once
        
        return stats
    
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class Visual_AidView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'ModelMaster/VisualAid.html'

    def get(self, request, batch_id=None, format=None):
        # Get parameters from URL or query string
        batch_id = batch_id or request.GET.get('batch_id')
        lot_id = request.GET.get('lot_id')
        plating_stk_no = request.GET.get('plating_stk_no')

        context = {
            'user': request.user,
        }

        # Import required models
        from modelmasterapp.models import ModelMasterCreation, LookLikeModel, ModelMaster, TotalStockModel

        batch_obj = None
        model_master_obj = None
        data_source = None  # Track whether data comes from ModelMasterCreation or ModelMaster

        # Handle lot_id parameter - NEW ADDITION
        if lot_id:
            print(f"🔍 Visual_AidView received lot_id: {lot_id}")
            
            # Find TotalStockModel by lot_id to get batch_id
            total_stock_obj = TotalStockModel.objects.filter(lot_id=lot_id).first()
            
            if total_stock_obj and hasattr(total_stock_obj, 'batch_id'):
                batch_id_obj = total_stock_obj.batch_id
                print(f"Found batch_id object from TotalStockModel: {batch_id_obj}")
                print(f"Type of batch_id object: {type(batch_id_obj)}")
                
                # Check if batch_id is a ForeignKey (ModelMasterCreation object) or string
                if hasattr(batch_id_obj, 'batch_id'):
                    # batch_id is a ForeignKey to ModelMasterCreation
                    batch_obj = batch_id_obj  # This IS the ModelMasterCreation object
                    print(f"batch_id is ForeignKey, using object directly: {batch_obj}")
                    model_master_obj = batch_obj.model_stock_no
                    data_source = "ModelMasterCreation"
                elif isinstance(batch_id_obj, str):
                    # batch_id is a string field
                    full_batch_id_str = str(batch_id_obj)
                    print(f"batch_id is string: {full_batch_id_str}")
                    
                    # Extract only the BATCH part after " - " if it exists
                    if " - " in full_batch_id_str:
                        batch_id = full_batch_id_str.split(" - ", 1)[1]
                        print(f"Extracted batch_id: {batch_id}")
                    else:
                        batch_id = full_batch_id_str
                        print(f"Using full batch_id as no separator found: {batch_id}")
                    
                    # Find ModelMasterCreation by batch_id string
                    batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
                    if batch_obj:
                        print(f"Found batch_obj by batch_id: {batch_obj}")
                        model_master_obj = batch_obj.model_stock_no
                        data_source = "ModelMasterCreation"
                    else:
                        print(f"No ModelMasterCreation found for batch_id: {batch_id}")
                else:
                    print(f"Unknown batch_id type: {type(batch_id_obj)}")
            else:
                print(f"No TotalStockModel found with lot_id: {lot_id} or no batch_id attribute")

        # Handle plating_stk_no parameter
        elif plating_stk_no:
            print(f"🔍 Visual_AidView received plating_stk_no: {plating_stk_no}")
            
            # First, try to find ModelMasterCreation through ModelMaster
            model_master_obj = ModelMaster.objects.filter(plating_stk_no=plating_stk_no).first()
            print(f"Found ModelMaster by plating_stk_no: {model_master_obj}")
            
            if model_master_obj:
                # Try to find corresponding ModelMasterCreation
                batch_obj = ModelMasterCreation.objects.filter(model_stock_no=model_master_obj).first()
                
                if batch_obj:
                    print(f"Found batch_obj by ModelMaster: {batch_obj}")
                    data_source = "ModelMasterCreation"
                else:
                    print(f"No ModelMasterCreation found, using ModelMaster data directly")
                    data_source = "ModelMaster"
            else:
                print(f"No ModelMaster found with plating_stk_no: {plating_stk_no}")
                
        # Handle batch_id parameter
        elif batch_id:
            print(f"🔍 Visual_AidView received batch_id: {batch_id}")
            batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
            if batch_obj:
                print(f"Found batch_obj by batch_id: {batch_obj}")
                model_master_obj = batch_obj.model_stock_no
                data_source = "ModelMasterCreation"

        # Populate context based on available data
        if batch_obj or model_master_obj:
            if data_source == "ModelMasterCreation" and batch_obj:
                # Use ModelMasterCreation data (preferred)
                images = batch_obj.images.all()
                image_urls = [img.master_image.url for img in images if img.master_image]
                
                context.update({
                    'batch_id': batch_obj.batch_id,
                    'lot_id': lot_id,  # Include lot_id in context if it was provided
                    'image_urls': image_urls,
                    'plating_stk_no': batch_obj.plating_stk_no,
                    'changes': batch_obj.changes,
                    'polish_finish': batch_obj.polish_finish,
                    'version': batch_obj.version.version_internal if batch_obj.version else None,
                    'data_source': 'ModelMasterCreation'
                })
                model_master_instance = batch_obj.model_stock_no
                
            elif data_source == "ModelMaster" and model_master_obj:
                # Use ModelMaster data directly
                images = model_master_obj.images.all()
                image_urls = [img.master_image.url for img in images if img.master_image]
                
                context.update({
                    'batch_id': None,
                    'lot_id': lot_id,  # Include lot_id in context if it was provided
                    'image_urls': image_urls,
                    'plating_stk_no': model_master_obj.plating_stk_no,
                    'changes': getattr(model_master_obj, 'changes', 'N/A'),  # May not exist in ModelMaster
                    'polish_finish': model_master_obj.polish_finish,
                    'version': model_master_obj.version,
                    'brand': model_master_obj.brand,
                    'gender': model_master_obj.gender,
                    'ep_bath_type': model_master_obj.ep_bath_type,
                    'data_source': 'ModelMaster'
                })
                model_master_instance = model_master_obj

            print(f"Using {data_source} as data source")
            print(f"Context plating_stk_no: {context.get('plating_stk_no')}")

            # Get related versions and similar models
            if model_master_instance:
                # Get all ModelMaster objects with same model_no for variants
                masters = ModelMaster.objects.filter(model_no=model_master_instance.model_no)
                version_list = [m.version for m in masters if m.version]
                version_labels = [str(v) for v in version_list]
                context['modelmaster_versions'] = version_labels

                # Find similar models through LookLikeModel
                look_like_obj = LookLikeModel.objects.filter(same_plating_stk_no=model_master_instance).first()
                print(f"LookLikeModel object: {look_like_obj}")

                if look_like_obj:
                    # Get all related ModelMaster objects
                    related_model_masters = look_like_obj.plating_stk_no.all()
                    same_model_list = []
                    
                    for related_master in related_model_masters:
                        # Check if this ModelMaster has a corresponding ModelMasterCreation
                        has_creation = ModelMasterCreation.objects.filter(
                            model_stock_no=related_master
                        ).exists()
                        
                        model_info = {
                            'plating_stk_no': related_master.plating_stk_no,
                            'model_master_id': related_master.id,
                            'has_creation': has_creation,
                            'has_model_master': True,  # Always true since we're iterating ModelMaster objects
                            'version': related_master.version,
                            'polish_finish': str(related_master.polish_finish) if related_master.polish_finish else None,
                        }
                        
                        same_model_list.append(model_info)
                    
                    context['same_model_list'] = same_model_list
                    print(f"Same model list with ModelMaster details: {same_model_list}")
                else:
                    context['same_model_list'] = []
            else:
                context['same_model_list'] = []
                context['modelmaster_versions'] = []
        else:
            # Handle error cases
            if lot_id:
                context['error'] = f"No data found for lot_id: {lot_id}"
            elif plating_stk_no:
                context['error'] = f"No ModelMaster found with plating_stk_no: {plating_stk_no}"
            elif batch_id:
                context['error'] = f"No ModelMasterCreation found for batch_id: {batch_id}"
            else:
                context['error'] = "Please provide either lot_id, batch_id, or plating_stk_no parameter"

        return Response(context)
    
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class Rec_Visual_AidView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'ModelMaster/VisualAid.html'

    def get(self, request, batch_id=None, format=None):
        # Get parameters from URL or query string
        batch_id = batch_id or request.GET.get('batch_id')
        plating_stk_no = request.GET.get('plating_stk_no')

        context = {
            'user': request.user,
        }


        batch_obj = None
        model_master_obj = None
        data_source = None  # Track whether data comes from ModelMasterCreation or ModelMaster

        # Handle plating_stk_no parameter
        if plating_stk_no:
            print(f"🔍 Visual_AidView received plating_stk_no: {plating_stk_no}")
            
            # First, try to find RecoveryMasterCreation through ModelMaster
            model_master_obj = ModelMaster.objects.filter(plating_stk_no=plating_stk_no).first()
            print(f"Found ModelMaster by plating_stk_no: {model_master_obj}")
            
            if model_master_obj:
                # Try to find corresponding RecoveryMasterCreation
                batch_obj = RecoveryMasterCreation.objects.filter(model_stock_no=model_master_obj).first()
                
                if batch_obj:
                    print(f"Found batch_obj by ModelMaster: {batch_obj}")
                    data_source = "RecoveryMasterCreation"
                else:
                    print(f"No RecoveryMasterCreation found, using ModelMaster data directly")
                    data_source = "ModelMaster"
            else:
                print(f"No ModelMaster found with plating_stk_no: {plating_stk_no}")
                
        # Handle batch_id parameter
        elif batch_id:
            print(f"🔍 Visual_AidView received batch_id: {batch_id}")
            batch_obj = RecoveryMasterCreation.objects.filter(batch_id=batch_id).first()
            if batch_obj:
                print(f"Found batch_obj by batch_id: {batch_obj}")
                model_master_obj = batch_obj.model_stock_no
                data_source = "RecoveryMasterCreation"

        # Populate context based on available data
        if batch_obj or model_master_obj:
            if data_source == "RecoveryMasterCreation" and batch_obj:
                # Use RecoveryMasterCreation data (preferred)
                images = batch_obj.images.all()
                image_urls = [img.master_image.url for img in images if img.master_image]
                
                context.update({
                    'batch_id': batch_obj.batch_id,
                    'image_urls': image_urls,
                    'plating_stk_no': batch_obj.plating_stk_no,
                    'changes': batch_obj.changes,
                    'polish_finish': batch_obj.polish_finish,
                    'version': batch_obj.version.version_internal if batch_obj.version else None,
                    'data_source': 'ModelMasterCreation'
                })
                model_master_instance = batch_obj.model_stock_no
                
            elif data_source == "ModelMaster" and model_master_obj:
                # Use ModelMaster data directly
                images = model_master_obj.images.all()
                image_urls = [img.master_image.url for img in images if img.master_image]
                
                context.update({
                    'batch_id': None,
                    'image_urls': image_urls,
                    'plating_stk_no': model_master_obj.plating_stk_no,
                    'changes': getattr(model_master_obj, 'changes', 'N/A'),  # May not exist in ModelMaster
                    'polish_finish': model_master_obj.polish_finish,
                    'version': model_master_obj.version,
                    'brand': model_master_obj.brand,
                    'gender': model_master_obj.gender,
                    'ep_bath_type': model_master_obj.ep_bath_type,
                    'data_source': 'ModelMaster'
                })
                model_master_instance = model_master_obj

            print(f"Using {data_source} as data source")
            print(f"Context plating_stk_no: {context.get('plating_stk_no')}")

            # Get related versions and similar models
            if model_master_instance:
                # Get all ModelMaster objects with same model_no for variants
                masters = ModelMaster.objects.filter(model_no=model_master_instance.model_no)
                version_list = [m.version for m in masters if m.version]
                version_labels = [str(v) for v in version_list]
                context['modelmaster_versions'] = version_labels

                # Find similar models through LookLikeModel
                look_like_obj = LookLikeModel.objects.filter(same_plating_stk_no=model_master_instance).first()
                print(f"LookLikeModel object: {look_like_obj}")

                if look_like_obj:
                    # Get all related ModelMaster objects
                    related_model_masters = look_like_obj.plating_stk_no.all()
                    same_model_list = []
                    
                    for related_master in related_model_masters:
                        # Check if this ModelMaster has a corresponding RecoveryMasterCreation
                        has_creation = RecoveryMasterCreation.objects.filter(
                            model_stock_no=related_master
                        ).exists()
                        
                        model_info = {
                            'plating_stk_no': related_master.plating_stk_no,
                            'model_master_id': related_master.id,
                            'has_creation': has_creation,
                            'has_model_master': True,  # Always true since we're iterating ModelMaster objects
                            'version': related_master.version,
                            'polish_finish': str(related_master.polish_finish) if related_master.polish_finish else None,
                        }
                        
                        same_model_list.append(model_info)
                    
                    context['same_model_list'] = same_model_list
                    print(f"Same model list with ModelMaster details: {same_model_list}")
                else:
                    context['same_model_list'] = []
            else:
                context['same_model_list'] = []
                context['modelmaster_versions'] = []
        else:
            # Handle error cases
            if plating_stk_no:
                context['error'] = f"No ModelMaster found with plating_stk_no: {plating_stk_no}"
            elif batch_id:
                context['error'] = f"No ModelMasterCreation found for batch_id: {batch_id}"
            else:
                context['error'] = "Please provide either batch_id or plating_stk_no parameter"

        return Response(context)

@method_decorator(login_required(login_url='login-api'), name='dispatch')
class Other_Visual_AidView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'ModelMaster/VisualAid.html'

    def get(self, request, batch_id=None, format=None):
        # Get parameters from URL or query string
        batch_id = batch_id or request.GET.get('batch_id')
        plating_stk_no = request.GET.get('plating_stk_no')
        model_no = request.GET.get('model_no')  # Add this new parameter

        context = {
            'user': request.user,
        }

        # Import required models
        from modelmasterapp.models import ModelMasterCreation, LookLikeModel, ModelMaster

        batch_obj = None
        model_master_obj = None
        data_source = None

        # Handle model_no parameter (NEW)
        if model_no:
            print(f"🔍 Visual_AidView received model_no: {model_no}")
            
            # Find ModelMaster by model_no (first match)
            model_master_obj = ModelMaster.objects.filter(model_no__startswith=model_no).first()
            print(f"Found ModelMaster by model_no: {model_master_obj}")
            
            if model_master_obj:
                # Try to find corresponding ModelMasterCreation
                batch_obj = ModelMasterCreation.objects.filter(model_stock_no=model_master_obj).first()
                
                if batch_obj:
                    print(f"Found batch_obj by ModelMaster: {batch_obj}")
                    data_source = "ModelMasterCreation"
                else:
                    print(f"No ModelMasterCreation found, using ModelMaster data directly")
                    data_source = "ModelMaster"
            else:
                print(f"No ModelMaster found with model_no: {model_no}")

        # Handle plating_stk_no parameter (EXISTING)
        elif plating_stk_no:
            print(f"🔍 Visual_AidView received plating_stk_no: {plating_stk_no}")
            
            # First, try to find ModelMasterCreation through ModelMaster
            model_master_obj = ModelMaster.objects.filter(plating_stk_no=plating_stk_no).first()
            print(f"Found ModelMaster by plating_stk_no: {model_master_obj}")
            
            if model_master_obj:
                # Try to find corresponding ModelMasterCreation
                batch_obj = ModelMasterCreation.objects.filter(model_stock_no=model_master_obj).first()
                
                if batch_obj:
                    print(f"Found batch_obj by ModelMaster: {batch_obj}")
                    data_source = "ModelMasterCreation"
                else:
                    print(f"No ModelMasterCreation found, using ModelMaster data directly")
                    data_source = "ModelMaster"
            else:
                print(f"No ModelMaster found with plating_stk_no: {plating_stk_no}")
                
        # Handle batch_id parameter (EXISTING)
        elif batch_id:
            print(f"🔍 Visual_AidView received batch_id: {batch_id}")
            batch_obj = ModelMasterCreation.objects.filter(batch_id=batch_id).first()
            if batch_obj:
                print(f"Found batch_obj by batch_id: {batch_obj}")
                model_master_obj = batch_obj.model_stock_no
                data_source = "ModelMasterCreation"

        # Populate context based on available data
        if batch_obj or model_master_obj:
            if data_source == "ModelMasterCreation" and batch_obj:
                # Use ModelMasterCreation data (preferred)
                images = batch_obj.images.all()
                image_urls = [img.master_image.url for img in images if img.master_image]
                
                context.update({
                    'batch_id': batch_obj.batch_id,
                    'image_urls': image_urls,
                    'plating_stk_no': batch_obj.plating_stk_no,
                    'changes': batch_obj.changes,
                    'polish_finish': batch_obj.polish_finish,
                    'version': batch_obj.version.version_internal if batch_obj.version else None,
                    'data_source': 'ModelMasterCreation'
                })
                model_master_instance = batch_obj.model_stock_no
                
            elif data_source == "ModelMaster" and model_master_obj:
                # Use ModelMaster data directly
                images = model_master_obj.images.all()
                image_urls = [img.master_image.url for img in images if img.master_image]
                
                context.update({
                    'batch_id': None,
                    'image_urls': image_urls,
                    'plating_stk_no': model_master_obj.plating_stk_no,
                    'changes': getattr(model_master_obj, 'changes', 'N/A'),  # May not exist in ModelMaster
                    'polish_finish': model_master_obj.polish_finish,
                    'version': model_master_obj.version,
                    'brand': model_master_obj.brand,
                    'gender': model_master_obj.gender,
                    'ep_bath_type': model_master_obj.ep_bath_type,
                    'data_source': 'ModelMaster'
                })
                model_master_instance = model_master_obj

            print(f"Using {data_source} as data source")
            print(f"Context plating_stk_no: {context.get('plating_stk_no')}")

            # Get related versions and similar models
            if model_master_instance:
                # Get all ModelMaster objects with same model_no for variants
                masters = ModelMaster.objects.filter(model_no=model_master_instance.model_no)
                version_list = [m.version for m in masters if m.version]
                version_labels = [str(v) for v in version_list]
                context['modelmaster_versions'] = version_labels

                # Find similar models through LookLikeModel
                look_like_obj = LookLikeModel.objects.filter(same_plating_stk_no=model_master_instance).first()
                print(f"LookLikeModel object: {look_like_obj}")

                if look_like_obj:
                    # Get all related ModelMaster objects
                    related_model_masters = look_like_obj.plating_stk_no.all()
                    same_model_list = []
                    
                    for related_master in related_model_masters:
                        # Check if this ModelMaster has a corresponding ModelMasterCreation
                        has_creation = ModelMasterCreation.objects.filter(
                            model_stock_no=related_master
                        ).exists()
                        
                        model_info = {
                            'plating_stk_no': related_master.plating_stk_no,
                            'model_master_id': related_master.id,
                            'has_creation': has_creation,
                            'has_model_master': True,  # Always true since we're iterating ModelMaster objects
                            'version': related_master.version,
                            'polish_finish': str(related_master.polish_finish) if related_master.polish_finish else None,
                        }
                        
                        same_model_list.append(model_info)
                    
                    context['same_model_list'] = same_model_list
                    print(f"Same model list with ModelMaster details: {same_model_list}")
                else:
                    context['same_model_list'] = []
            else:
                context['same_model_list'] = []
                context['modelmaster_versions'] = []
        else:
            # Handle error cases
            if plating_stk_no:
                context['error'] = f"No ModelMaster found with plating_stk_no: {plating_stk_no}"
            elif batch_id:
                context['error'] = f"No ModelMasterCreation found for batch_id: {batch_id}"
            else:
                context['error'] = "Please provide either batch_id or plating_stk_no parameter"

        return Response(context)



from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

@method_decorator(login_required(login_url='login-api'), name='dispatch')
class DP_ViewmasterView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'ModelMaster/viewmasters.html'

    def get_paginated_data(self, queryset, page_param, items_per_page=10):
        """Helper method to paginate queryset"""
        paginator = Paginator(queryset, items_per_page)
        page = self.request.GET.get(page_param, 1)
        
        try:
            paginated_items = paginator.page(page)
        except PageNotAnInteger:
            paginated_items = paginator.page(1)
        except EmptyPage:
            paginated_items = paginator.page(paginator.num_pages)
        
        return paginated_items

    def get(self, request, format=None):
        # Check if this is an AJAX request for pagination
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return self.handle_ajax_pagination(request)
        
        # Fetch all data with pagination
        model_masters = self.get_paginated_data(ModelMaster.objects.all(), 'model_page')
        polish_finishes = self.get_paginated_data(PolishFinishType.objects.all(), 'polish_page')
        plating_colors = self.get_paginated_data(Plating_Color.objects.all(), 'plating_page')
        tray_types = self.get_paginated_data(TrayType.objects.all(), 'tray_page')
        locations = self.get_paginated_data(Location.objects.all(), 'vendor_page')
        model_images = self.get_paginated_data(ModelImage.objects.all(), 'images_page')
        tray_ids = self.get_paginated_data(TrayId.objects.all(), 'trayid_page')
        categories = self.get_paginated_data(Category.objects.all(), 'category_page')
        ip_rejections = self.get_paginated_data(IP_Rejection_Table.objects.all(), 'iprejection_page')
        nickel_rejections = self.get_paginated_data(Nickel_QC_Rejection_Table.objects.all(), 'nickelrejection_page')
        brassiqf_rejections = self.get_paginated_data(Brass_QC_Rejection_Table.objects.all(), 'brassiqf_page')

        context = {
            'model_masters': model_masters,
            'polish_finishes': polish_finishes,
            'plating_colors': plating_colors,
            'tray_types': tray_types,
            'locations': locations,
            'model_images': model_images,
            'tray_ids': tray_ids,
            'categories': categories,
            'ip_rejections': ip_rejections,
            'nickel_rejections': nickel_rejections,
            'brassiqf_rejections': brassiqf_rejections,
        }
        return Response(context)

    def handle_ajax_pagination(self, request):
        """Handle AJAX pagination requests"""
        tab_name = request.GET.get('tab')
        page = request.GET.get('page', 1)
        
        # Map tab names to models
        tab_mapping = {
            'model': ModelMaster.objects.all(),
            'polish': PolishFinishType.objects.all(),
            'plating': Plating_Color.objects.all(),
            'tray': TrayType.objects.all(),
            'vendor': Location.objects.all(),
            'images': ModelImage.objects.all(),
            'trayid': TrayId.objects.all(),
            'category': Category.objects.all(),
            'iprejection': IP_Rejection_Table.objects.all(),
            'nickelrejection': Nickel_QC_Rejection_Table.objects.all(),
            'brassiqf': Brass_QC_Rejection_Table.objects.all(),
        }
        
        if tab_name not in tab_mapping:
            return JsonResponse({'error': 'Invalid tab'}, status=400)
        
        queryset = tab_mapping[tab_name]
        
        # Paginate the data
        paginator = Paginator(queryset, 10)
        try:
            paginated_data = paginator.page(page)
        except PageNotAnInteger:
            paginated_data = paginator.page(1)
        except EmptyPage:
            paginated_data = paginator.page(paginator.num_pages)
        
        # Generate HTML for the specific tab
        html_data = self.generate_table_rows(tab_name, paginated_data)
        
        return JsonResponse({
            'html': html_data,
            'current_page': paginated_data.number,
            'total_pages': paginated_data.paginator.num_pages,
            'total_items': paginated_data.paginator.count,
            'has_previous': paginated_data.has_previous(),
            'has_next': paginated_data.has_next(),
            'previous_page': paginated_data.previous_page_number() if paginated_data.has_previous() else None,
            'next_page': paginated_data.next_page_number() if paginated_data.has_next() else None,
        })

    def generate_table_rows(self, tab_name, paginated_data):
        """Generate HTML table rows for specific tab data"""
        html_rows = ""
        
        if tab_name == 'model':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox model-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.model_no}</td>
                    <td>{obj.plating_stk_no}</td>
                    <td>{obj.polish_finish.polish_finish if obj.polish_finish else '-'}</td>
                    <td>{obj.ep_bath_type}</td>
                    <td>{obj.version}</td>
                    <td>{obj.tray_type.tray_type if obj.tray_type else '-'}</td>
                    <td>{obj.tray_type.tray_capacity if obj.tray_type else '-'}</td>
                </tr>
                """
        elif tab_name == 'polish':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox polish-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.polish_finish}</td>
                    <td>{obj.polish_internal}</td>
                </tr>
                """
        elif tab_name == 'plating':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox plating-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.plating_color}</td>
                    <td>{obj.plating_color_internal}</td>
                </tr>
                """
        elif tab_name == 'tray':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox tray-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.tray_type}</td>
                    <td>{obj.tray_capacity}</td>
                </tr>
                """
        elif tab_name == 'vendor':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox vendor-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.location_name}</td>
                </tr>
                """
        elif tab_name == 'images':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                image_name = obj.master_image.name if obj.master_image else '-'
                image_url = f'<a href="{obj.master_image.url}" target="_blank">{obj.master_image.url}</a>' if obj.master_image else '-'
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox images-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{image_name}</td>
                    <td>{image_url}</td>
                </tr>
                """
        elif tab_name == 'trayid':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox trayid-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date.strftime('%Y-%m-%d')}</td>
                    <td>{obj.tray_id}</td>
                    <td>{obj.tray_type}</td>
                    <td>{obj.tray_capacity}</td>
                </tr>
                """
        elif tab_name == 'category':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox category-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.category_name}</td>
                </tr>
                """
        elif tab_name == 'iprejection':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox iprejection-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date.strftime('%Y-%m-%d')}</td>
                    <td>{obj.rejection_reason_id}</td>
                    <td>{obj.rejection_reason}</td>
                </tr>
                """
        elif tab_name == 'brassiqf':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox brassiqf-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.rejection_reason_id}</td>
                    <td>{obj.rejection_reason}</td>
                </tr>
                """
        elif tab_name == 'nickelrejection':
            for i, obj in enumerate(paginated_data, start=paginated_data.start_index()):
                html_rows += f"""
                <tr>
                    <td><input type="checkbox" class="select-checkbox nickelrejection-checkbox" name="selected_ids" value="{obj.id}"></td>
                    <td>{i}</td>
                    <td>{obj.date_time.strftime('%Y-%m-%d')}</td>
                    <td>{obj.rejection_reason}</td>
                </tr>
                """
        
        if not html_rows:
            # Return appropriate empty message based on tab
            col_count = {
                'model': 10, 'polish': 5, 'plating': 5, 'tray': 5, 'vendor': 4,
                'images': 5, 'trayid': 6, 'category': 4, 'iprejection': 6,
                'brassiqf': 5, 'nickelrejection': 4
            }
            html_rows = f'<tr><td colspan="{col_count.get(tab_name, 5)}">No records found.</td></tr>'
        
        return html_rows

    def post(self, request, format=None):
        """Handle deletion of selected items"""
        try:
            action = request.POST.get('action')
            if action != 'delete':
                return JsonResponse({'success': False, 'error': 'Invalid action'})

            tab_name = request.POST.get('tab_name')
            selected_ids = request.POST.getlist('selected_ids')

            if not selected_ids:
                return JsonResponse({'success': False, 'error': 'No items selected'})

            # Map tab names to models
            model_mapping = {
                'model': ModelMaster,
                'polish': PolishFinishType,
                'plating': Plating_Color,
                'tray': TrayType,
                'vendor': Location,
                'images': ModelImage,
                'trayid': TrayId,
                'category': Category,
                'iprejection': IP_Rejection_Table,  
                'brassiqf': Brass_QC_Rejection_Table,
                'nickelrejection': Nickel_QC_Rejection_Table,
            }

            if tab_name not in model_mapping:
                return JsonResponse({'success': False, 'error': 'Invalid tab name'})

            model_class = model_mapping[tab_name]
            
            # Delete selected items
            deleted_count = 0
            for item_id in selected_ids:
                try:
                    if tab_name == 'brassiqf':
                        # Delete from all Brass/IQF tables by rejection_reason_id
                        obj = get_object_or_404(Brass_QC_Rejection_Table, id=item_id)
                        reason_id = obj.rejection_reason_id
                        obj.delete()
                        Brass_QC_Rejection_Table.objects.filter(rejection_reason_id=reason_id).delete()  
                        Brass_Audit_Rejection_Table.objects.filter(rejection_reason_id=reason_id).delete()
                        IQF_Rejection_Table.objects.filter(rejection_reason_id=reason_id).delete()
                        deleted_count += 1
                    elif tab_name == 'nickelrejection':
                        # Delete from both Nickel tables by rejection_reason text
                        obj = get_object_or_404(Nickel_QC_Rejection_Table, id=item_id)
                        reason_text = obj.rejection_reason
                        obj.delete()
                        Nickel_Audit_Rejection_Table.objects.filter(rejection_reason=reason_text).delete()
                        deleted_count += 1
                    else:
                        item = get_object_or_404(model_class, id=item_id)
                        item.delete()
                        deleted_count += 1
                except Exception as e:
                    print(f"Error deleting item {item_id}: {str(e)}")
                    continue

            return JsonResponse({
                'success': True, 
                'deleted_count': deleted_count,
                'message': f'Successfully deleted {deleted_count} item(s)'
            })

        except Exception as e:
            return JsonResponse({
                'success': False, 
                'error': str(e)
            })

@method_decorator(login_required(login_url='login-api'), name='dispatch')
class DP_ModelmasterView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'ModelMaster/dp_modelmaster.html'

    def get(self, request, format=None):
        # Get all data for dropdowns and existing records
        context = {
            'polish_finishes': PolishFinishType.objects.all(),
            'plating_colors': Plating_Color.objects.all(),
            'tray_types': TrayType.objects.all(),
            'vendors': Vendor.objects.all(),
            'model_images': ModelImage.objects.all(),
            'model_masters': ModelMaster.objects.all(),
            'versions': Version.objects.all(),
            # Add categories for dropdown
            'categories': Category.objects.all(),
        }
        return Response(context)

    def post(self, request, format=None):
        # Handle Category form submission
        if 'category_name' in request.data:
            # Add current datetime to the request data
            data = request.data.copy()
            data['date_time'] = timezone.now()
            
            serializer = CategorySerializer(data=data)
            if serializer.is_valid():
                category = serializer.save()
                # Redirect to same page with category_name in query params
                from django.shortcuts import redirect
                return redirect(f"/adminportal/dp_modelmaster/?category_name={category.category_name}")
            else:
                # Re-render page with errors
                context = {
                    'polish_finishes': PolishFinishType.objects.all(),
                    'plating_colors': Plating_Color.objects.all(),
                    'tray_types': TrayType.objects.all(),
                    'vendors': Vendor.objects.all(),
                    'model_images': ModelImage.objects.all(),
                    'model_masters': ModelMaster.objects.all(),
                    'versions': Version.objects.all(),
                    'categories': Category.objects.all(),
                    'category_form_errors': serializer.errors,
                }
                return Response(context)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class PolishFinishAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Polish Finish types"""
        polish_finishes = PolishFinishType.objects.all()
        serializer = PolishFinishTypeSerializer(polish_finishes, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Polish Finish type"""
        try:
            # Add current datetime to the request data
            data = request.data.copy()
            data['date_time'] = timezone.now()
            
            serializer = PolishFinishTypeSerializer(data=data)
            if serializer.is_valid():
                polish_finish = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Polish finish created successfully!',
                    'data': PolishFinishTypeSerializer(polish_finish).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating polish finish: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Polish Finish type"""
        try:
            polish_finish = get_object_or_404(PolishFinishType, pk=pk)
            serializer = PolishFinishTypeSerializer(polish_finish, data=request.data)
            if serializer.is_valid():
                updated_polish_finish = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Polish finish updated successfully!',
                    'data': PolishFinishTypeSerializer(updated_polish_finish).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating polish finish: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Polish Finish type"""
        try:
            polish_finish = get_object_or_404(PolishFinishType, pk=pk)
            polish_finish.delete()
            return Response({
                'success': True,
                'message': 'Polish finish deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting polish finish: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class PlatingColorAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Plating Colors"""
        plating_colors = Plating_Color.objects.all()
        serializer = PlatingColorSerializer(plating_colors, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Plating Color"""
        try:
            # Add current datetime to the request data
            data = request.data.copy()
            data['date_time'] = timezone.now()
            
            serializer = PlatingColorSerializer(data=data)
            if serializer.is_valid():
                plating_color = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Plating color created successfully!',
                    'data': PlatingColorSerializer(plating_color).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating plating color: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Plating Color"""
        try:
            plating_color = get_object_or_404(Plating_Color, pk=pk)
            serializer = PlatingColorSerializer(plating_color, data=request.data)
            if serializer.is_valid():
                updated_plating_color = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Plating color updated successfully!',
                    'data': PlatingColorSerializer(updated_plating_color).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating plating color: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Plating Color"""
        try:
            plating_color = get_object_or_404(Plating_Color, pk=pk)
            plating_color.delete()
            return Response({
                'success': True,
                'message': 'Plating color deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting plating color: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class TrayTypeAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Tray Types"""
        tray_types = TrayType.objects.all()
        serializer = TrayTypeSerializer(tray_types, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Tray Type"""
        try:
            # Add current datetime to the request data
            data = request.data.copy()
            data['date_time'] = timezone.now()
            
            serializer = TrayTypeSerializer(data=data)
            if serializer.is_valid():
                tray_type = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Tray type created successfully!',
                    'data': TrayTypeSerializer(tray_type).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating tray type: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Tray Type"""
        try:
            tray_type = get_object_or_404(TrayType, pk=pk)
            serializer = TrayTypeSerializer(tray_type, data=request.data)
            if serializer.is_valid():
                updated_tray_type = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Tray type updated successfully!',
                    'data': TrayTypeSerializer(updated_tray_type).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating tray type: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Tray Type"""
        try:
            tray_type = get_object_or_404(TrayType, pk=pk)
            tray_type.delete()
            return Response({
                'success': True,
                'message': 'Tray type deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting tray type: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class ModelImageAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Model Images"""
        model_images = ModelImage.objects.all()
        serializer = ModelImageSerializer(model_images, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Upload new Model Images"""
        try:
            # Handle multiple image uploads
            uploaded_images = []
            
            if 'images' in request.FILES:
                images = request.FILES.getlist('images')
                for image in images:
                    image_data = {
                        'master_image': image,
                        'date_time': timezone.now()  # Add datetime for each image
                    }
                    serializer = ModelImageSerializer(data=image_data)
                    if serializer.is_valid():
                        model_image = serializer.save()
                        uploaded_images.append(ModelImageSerializer(model_image).data)
                    else:
                        return Response({
                            'success': False,
                            'message': 'Invalid image file',
                            'errors': serializer.errors
                        }, status=status.HTTP_400_BAD_REQUEST)
                
                return Response({
                    'success': True,
                    'message': f'{len(uploaded_images)} image(s) uploaded successfully!',
                    'data': uploaded_images
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'No images provided'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error uploading images: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Model Image"""
        try:
            model_image = get_object_or_404(ModelImage, pk=pk)
            # Delete the actual file
            if model_image.master_image:
                model_image.master_image.delete()
            model_image.delete()
            return Response({
                'success': True,
                'message': 'Model image deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting model image: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class ModelMasterAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Model Masters"""
        model_masters = ModelMaster.objects.all()
        serializer = ModelMasterSerializer(model_masters, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Model Master"""
        try:
            # Add current datetime to the request data
            data = request.data.copy()
            data['date_time'] = timezone.now()
            
            serializer = ModelMasterSerializer(data=data)
            if serializer.is_valid():
                model_master = serializer.save()
                
                # Handle many-to-many relationship for images
                if 'images' in request.data:
                    image_ids = request.data.getlist('images') if hasattr(request.data, 'getlist') else request.data.get('images', [])
                    if image_ids:
                        model_master.images.set(image_ids)
                
                return Response({
                    'success': True,
                    'message': 'Model master created successfully!',
                    'data': ModelMasterSerializer(model_master).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating model master: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Model Master"""
        try:
            model_master = get_object_or_404(ModelMaster, pk=pk)
            serializer = ModelMasterSerializer(model_master, data=request.data)
            if serializer.is_valid():
                updated_model_master = serializer.save()
                
                # Handle many-to-many relationship for images
                if 'images' in request.data:
                    image_ids = request.data.getlist('images') if hasattr(request.data, 'getlist') else request.data.get('images', [])
                    updated_model_master.images.set(image_ids)
                
                return Response({
                    'success': True,
                    'message': 'Model master updated successfully!',
                    'data': ModelMasterSerializer(updated_model_master).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating model master: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Model Master"""
        try:
            model_master = get_object_or_404(ModelMaster, pk=pk)
            model_master.delete()
            return Response({
                'success': True,
                'message': 'Model master deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting model master: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class LocationAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Locations"""
        locations = Location.objects.all()
        serializer = LocationSerializer(locations, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Location"""
        try:
            # Add current datetime to the request data
            data = request.data.copy()
            data['date_time'] = timezone.now()
            
            serializer = LocationSerializer(data=data)
            if serializer.is_valid():
                location = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Location created successfully!',
                    'data': LocationSerializer(location).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating location: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Location"""
        try:
            location = get_object_or_404(Location, pk=pk)
            serializer = LocationSerializer(location, data=request.data)
            if serializer.is_valid():
                updated_location = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Location updated successfully!',
                    'data': LocationSerializer(updated_location).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating location: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Location"""
        try:
            location = get_object_or_404(Location, pk=pk)
            location.delete()
            return Response({
                'success': True,
                'message': 'Location deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting location: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class TrayIdAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Tray IDs"""
        tray_ids = TrayId.objects.all()
        serializer = TrayIdSerializer(tray_ids, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Tray ID"""
        try:
            # Convert tray_type to pk if needed (from string to int)
            data = request.data.copy()
            data['date'] = timezone.now()  # Add datetime
            
            if isinstance(data.get('tray_type'), str) and data.get('tray_type').isdigit():
                data['tray_type'] = int(data['tray_type'])
            serializer = TrayIdSerializer(data=data)
            if serializer.is_valid():
                tray_id = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Tray ID created successfully!',
                    'data': TrayIdSerializer(tray_id).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating tray id: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Tray ID"""
        try:
            tray_id_obj = get_object_or_404(TrayId, pk=pk)
            data = request.data.copy()
            if isinstance(data.get('tray_type'), str) and data.get('tray_type').isdigit():
                data['tray_type'] = int(data['tray_type'])
            serializer = TrayIdSerializer(tray_id_obj, data=data)
            if serializer.is_valid():
                updated_tray_id = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Tray ID updated successfully!',
                    'data': TrayIdSerializer(updated_tray_id).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating tray id: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class CategoryAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Categories"""
        categories = Category.objects.all()
        serializer = CategorySerializer(categories, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Category"""
        try:
            # Add current datetime to the request data
            data = request.data.copy()
            data['date_time'] = timezone.now()
            
            serializer = CategorySerializer(data=data)
            if serializer.is_valid():
                category = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Category created successfully!',
                    'data': CategorySerializer(category).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating category: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Category"""
        try:
            category = get_object_or_404(Category, pk=pk)
            serializer = CategorySerializer(category, data=request.data)
            if serializer.is_valid():
                updated_category = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Category updated successfully!',
                    'data': CategorySerializer(updated_category).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating category: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Category"""
        try:
            category = get_object_or_404(Category, pk=pk)
            category.delete()
            return Response({
                'success': True,
                'message': 'Category deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting category: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class IPRejectionAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all IP Rejection Reasons"""
        rejections = IP_Rejection_Table.objects.all()
        serializer = IPRejectionSerializer(rejections, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new IP Rejection Reason"""
        try:
            data = request.data.copy()
            data['date_time'] = timezone.now()
 
            serializer = IPRejectionSerializer(data=data)
            if serializer.is_valid():
                rejection = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Rejection reason created successfully!',
                    'data': IPRejectionSerializer(rejection).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update IP Rejection Reason"""
        try:
            rejection = get_object_or_404(IP_Rejection_Table, pk=pk)
            serializer = IPRejectionSerializer(rejection, data=request.data)
            if serializer.is_valid():
                updated_rejection = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Rejection reason updated successfully!',
                    'data': IPRejectionSerializer(updated_rejection).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete IP Rejection Reason"""
        try:
            rejection = get_object_or_404(IP_Rejection_Table, pk=pk)
            rejection.delete()
            return Response({
                'success': True,
                'message': 'Rejection reason deleted successfully!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class BrassIQFRejectionAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Brass/IQF Rejection Reasons (from Brass_QC_Rejection_Table only)"""
        rejections = Brass_QC_Rejection_Table.objects.all()
        data = [
            {
                'id': obj.id,
                'rejection_reason_id': obj.rejection_reason_id,
                'rejection_reason': obj.rejection_reason,
                
            }
            for obj in rejections
        ]
        return Response({
            'success': True,
            'data': data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Brass/IQF Rejection Reason in all three tables"""
        try:
            data = request.data.copy()
            serializer = BrassIQFRejectionSerializer(data=data)
            if serializer.is_valid():
                result = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Rejection reason created successfully in all tables!',
                    'data': BrassIQFRejectionSerializer(result).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Brass/IQF Rejection Reason in all three tables by id (Brass_QC_Rejection_Table only)"""
        try:
            qc_obj = get_object_or_404(Brass_QC_Rejection_Table, pk=pk)
            serializer = BrassIQFRejectionSerializer(qc_obj, data=request.data)
            if serializer.is_valid():
                updated_qc = serializer.save()
                # Optionally update other tables if needed
                return Response({
                    'success': True,
                    'message': 'Rejection reason updated successfully!',
                    'data': BrassIQFRejectionSerializer({'qc': updated_qc, 'audit': None, 'iqf': None}).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Brass/IQF Rejection Reason from all three tables by id (Brass_QC_Rejection_Table only)"""
        try:
            qc_obj = get_object_or_404(Brass_QC_Rejection_Table, pk=pk)
            reason_id = qc_obj.rejection_reason_id
            qc_obj.delete()
            # Also delete from other tables by rejection_reason_id
            Brass_Audit_Rejection_Table.objects.filter(rejection_reason_id=reason_id).delete()
            IQF_Rejection_Table.objects.filter(rejection_reason_id=reason_id).delete()
            return Response({
                'success': True,
                'message': 'Rejection reason deleted from all tables!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class NickelAuditQCRejectionAPIView(APIView):
    renderer_classes = [JSONRenderer]

    def get(self, request):
        """Get all Nickel QC Rejection Reasons (from Nickel_QC_Rejection_Table only)"""
        rejections = Nickel_QC_Rejection_Table.objects.all()
        data = [
            {
                'id': obj.id,
                'rejection_reason': obj.rejection_reason
            }
            for obj in rejections
        ]
        return Response({
            'success': True,
            'data': data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create new Nickel Audit/QC Rejection Reason in both tables"""
        try:
            data = request.data.copy()
            serializer = NickelAuditQCRejectionSerializer(data=data)
            if serializer.is_valid():
                result = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Nickel Audit/QC rejection reason created successfully in both tables!',
                    'data': NickelAuditQCRejectionSerializer(result).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error creating rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, pk):
        """Update Nickel QC Rejection Reason by id (Nickel_QC_Rejection_Table only)"""
        try:
            qc_obj = get_object_or_404(Nickel_QC_Rejection_Table, pk=pk)
            serializer = NickelAuditQCRejectionSerializer(qc_obj, data=request.data)
            if serializer.is_valid():
                updated_qc = serializer.save()
                return Response({
                    'success': True,
                    'message': 'Nickel QC rejection reason updated successfully!',
                    'data': NickelAuditQCRejectionSerializer({'qc': updated_qc, 'audit': None}).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete Nickel QC Rejection Reason from both tables by id (Nickel_QC_Rejection_Table only)"""
        try:
            qc_obj = get_object_or_404(Nickel_QC_Rejection_Table, pk=pk)
            reason_text = qc_obj.rejection_reason
            qc_obj.delete()
            # Also delete from audit table by rejection_reason
            Nickel_Audit_Rejection_Table.objects.filter(rejection_reason=reason_text).delete()
            return Response({
                'success': True,
                'message': 'Nickel rejection reason deleted from both tables!'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error deleting rejection reason: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Utility view to get dropdown data
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class ModelMasterDropdownDataAPIView(APIView):
    renderer_classes = [JSONRenderer]
    
    def get(self, request):
        """Get all dropdown data for Model Master form"""
        try:
            data = {
                'polish_finishes': list(PolishFinishType.objects.values('id', 'polish_finish')),
                'plating_colors': list(Plating_Color.objects.values('id', 'plating_color')),
                'tray_types': list(TrayType.objects.values('id', 'tray_type', 'tray_capacity')),
                'vendors': list(Vendor.objects.values('id', 'vendor_name')),
                'model_images': list(ModelImage.objects.values('id', 'master_image')),
                'versions': list(Version.objects.values('id', 'version_name')),
                'locations': list(Location.objects.values('id', 'location_name')),
                'tray_ids': list(TrayId.objects.values('id', 'tray_id', 'tray_type', 'tray_capacity')),
                'categories': list(Category.objects.values('id', 'category_name')),
            }
            return Response({
                'success': True,
                'data': data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error fetching dropdown data: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

""" Module - User Management """
# Class for Admin Portal HTML File Navigation (Dashboard/Settings gear - Dropdown - User Creation)
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class AdminPortalView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'AdminPortal/adminPortal.html'
    
    def get(self, request, format=None):
        last_user = User.objects.order_by('-id').first()
        next_user_id = (last_user.id + 1) if last_user else 1
        allowed_modules = get_allowed_modules_for_user(request.user)
        is_admin = (
            request.user.is_authenticated and (
                request.user.is_superuser
                or request.user.groups.filter(name__iexact="Admin").exists()
                or (
                    hasattr(request.user, 'userprofile')
                    and request.user.userprofile.department
                    and request.user.userprofile.department.name.lower() == "admin"
                )
            )
        )
        return Response({
            'next_user_id': next_user_id,
            'allowed_modules': allowed_modules,
            'is_admin': is_admin,  # <-- Add this line
        })

# Class for Department List APIs Masters
class DepartmentListAPIView(APIView):
    def get(self, request):
        departments = Department.objects.all().values('id', 'name')
        return Response(list(departments))
    
    
# Class for Role List APIs Masters
@method_decorator(csrf_exempt, name='dispatch')
class RoleListAPIView(APIView):
    def get(self, request):
        roles = Role.objects.all().values('id', 'name')
        return Response(list(roles))


# Class for User Creation API - Fixed

@method_decorator(csrf_exempt, name='dispatch')
class UserCreateAPIView(APIView):
    def post(self, request, *args, **kwargs):
        data = request.data or {}
        email = data.get('email')
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        password = data.get('password')
        department_id = data.get('department')
        role_id = data.get('role')
        group_id = data.get('group')
        username = (data.get('username') or email or f"{(first_name or '').strip()}.{(last_name or '').strip()}").lower()

        try:
            with transaction.atomic():
                # If user exists, update instead of failing
                existing = User.objects.filter(username=username).first()
                if existing:
                    user = existing
                    if first_name:
                        user.first_name = first_name
                    if last_name:
                        user.last_name = last_name
                    if email:
                        user.email = email
                    # Update password only when provided
                    if password:
                        user.set_password(password)
                    user.save()

                    # Update group if provided
                    if group_id:
                        try:
                            grp = Group.objects.get(id=group_id)
                            user.groups.clear()
                            user.groups.add(grp)
                        except Group.DoesNotExist:
                            pass

                    # Ensure profile exists, then update
                    profile = getattr(user, 'userprofile', None)
                    if not profile:
                        profile = UserProfile.objects.create(user=user)

                    if department_id and Department.objects.filter(id=department_id).exists():
                        profile.department_id = department_id
                    if role_id and Role.objects.filter(id=role_id).exists():
                        profile.role_id = role_id

                    profile.manager = data.get('manager', profile.manager)
                    profile.employment_status = data.get('employment_status', profile.employment_status)
                    profile.save()

                    return Response({
                        'success': True,
                        'user_id': user.id,
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'email': user.email,
                        },
                        'message': 'Existing user updated.'
                    }, status=status.HTTP_200_OK)

                # Create new user (original behaviour)
                user = User.objects.create_user(username=username, password=password, email=email)
                user.first_name = first_name or ""
                user.last_name = last_name or ""

                # Attach group and preserve original Admin flag behaviour on creation
                if group_id:
                    try:
                        group = Group.objects.get(id=group_id)
                        user.groups.add(group)
                        if group.name.lower() == "admin":
                            user.is_active = True
                            user.is_staff = True
                            user.is_superuser = True
                    except Group.DoesNotExist:
                        pass

                user.save()

                # Validate department and role for new user
                if not department_id or not Department.objects.filter(id=department_id).exists():
                    return Response({'success': False, 'error': 'Invalid department selected.'}, status=status.HTTP_400_BAD_REQUEST)
                if not role_id or not Role.objects.filter(id=role_id).exists():
                    return Response({'success': False, 'error': 'Invalid role selected.'}, status=status.HTTP_400_BAD_REQUEST)

                # Ensure profile exists (signal may create it) and update it
                profile = getattr(user, "userprofile", None)
                if not profile:
                    profile = UserProfile.objects.create(user=user)

                profile.department_id = department_id
                profile.role_id = role_id
                profile.manager = data.get('manager')
                profile.employment_status = data.get('employment_status')
                profile.save()

            return Response({
                'success': True,
                'user_id': user.id,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                },
                'message': 'User created successfully.'
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            print(traceback.format_exc())
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def create_user(request):
    with transaction.atomic():
        # create or get user
        user, created = User.objects.get_or_create(
            username=request.data['username'],
            defaults={
                'first_name': request.data['first_name'],
                'last_name': request.data['last_name'],
                'email': request.data['email']
            }
        )
        
        # create profile only if it doesn't exist
        if not hasattr(user, 'userprofile'):
            UserProfile.objects.create(
                user=user,
                department_id=request.data['department'],
                role_id=request.data['role']
            )
        
        return Response({'success': True, 'user_id': user.id})
    
    
    
@method_decorator(csrf_exempt, name='dispatch')
class UserListAPIView(APIView):
    def get(self, request):
        users = User.objects.all().order_by('id')
        paginator = Paginator(users, 8)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        user_list = []
        for user in page_obj.object_list:
            try:
                profile = user.userprofile
                department = profile.department.name if profile.department else ""
                role = profile.role.name if profile.role else ""
                manager = profile.manager
                employment_status = profile.employment_status
            except Exception:
                department = role = manager = employment_status = ""
            module_access = UserModuleProvision.objects.filter(user=user)
            modules = [
                {
                    "name": access.module_name,
                    "headings": access.headings
                }
                for access in module_access
            ]
            created = user.date_joined.strftime("%Y-%m-%d %H:%M")
            user_list.append({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "department": department,
                "user_category": user.groups.first().name if user.groups.exists() else "",
                "role": role,
                "manager": manager,
                "employment_status": employment_status,
                "modules": modules,
                "created": created,
                "is_superuser": user.is_superuser
            })
        return Response({
            "results": user_list,
            "count": paginator.count,
            "num_pages": paginator.num_pages,
            "current_page": page_obj.number
        })



class UserGroupListAPIView(APIView):
    def get(self, request):
        groups = Group.objects.all().values('id', 'name')
        return Response(list(groups))
    
    
    
class GroupModulesAPIView(APIView):
    def get(self, request, group_id):
        try:
            group = Group.objects.get(id=group_id)
            modules = Module.objects.filter(groups=group)
            data = [
                {"id": m.id, "name": m.name, "menu_title": m.menu_title, "headings": m.headings}
                for m in modules
            ]
            return Response({"success": True, "modules": data})
        except Group.DoesNotExist:
            return Response({"success": False, "error": "Group not found"}, status=404)

# Function for User Visibile Modules API (checkbox/unchecked logic)
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_allowed_modules(request):
    user = request.user
    if not user.is_authenticated:
        return {'allowed_modules': []}

    # ----- POST logic -----
    if request.method == 'POST':
        user_id = request.data.get('user_id')
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({'success': False, 'error': 'User not found.'}, status=404)

        try:
            modules = request.data.get('modules', [])
            if not isinstance(modules, list):
                return Response({'success': False, 'error': 'Modules should be a list.'}, status=400)

            UserModuleProvision.objects.filter(user=user).delete()
            # Example: in your API view for saving user module provisions
            for mod in modules:
                UserModuleProvision.objects.update_or_create(
                    user=user,
                    module_name=mod['name'],
                    defaults={
                        'headings': mod['headings'],
                        'file_name': mod.get('file_name', '')
                    }
                )
            return Response({'success': True, 'message': 'Modules saved successfully.'})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=500)

    # ----- GET logic -----
    # ----- GET logic -----
    # Check if a specific user_id is requested (for Admin editing)
    target_user = user
    requested_user_id = request.GET.get('user_id')
    
    # Permission check for fetching other users
    is_admin = (
        user.is_superuser
        or user.groups.filter(name__iexact="Admin").exists()
        or (
            hasattr(user, 'userprofile')
            and user.userprofile.department
            and user.userprofile.department.name.lower() == "admin"
        )
    )

    if requested_user_id and is_admin:
        try:
            target_user = User.objects.get(id=requested_user_id)
        except User.DoesNotExist:
            return Response({'allowed_modules': []}, status=404)

    # 1. If target is Admin/Superuser -> Full Access
    # (We check target_user properties here)
    if (
        target_user.is_superuser
        or target_user.groups.filter(name__iexact="Admin").exists()
        or (
            hasattr(target_user, 'userprofile')
            and target_user.userprofile.department
            and target_user.userprofile.department.name.lower() == "admin"
        )
    ):
        all_modules = Module.objects.all()
        modules = [{"name": mod.name, "headings": mod.headings} for mod in all_modules]
        return Response({"modules": modules})

    # 2. Normal users: use UserModuleProvision for target_user
    provisions = UserModuleProvision.objects.filter(user=target_user)
    modules = [{"name": p.module_name, "headings": p.headings} for p in provisions]
    return Response({"modules": modules})



#Class for User Deletion API
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class UserDeleteAPIView(APIView):
    def delete(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.delete()
            return Response({'success': True, 'message': 'User deleted.'}, status=200)
        except User.DoesNotExist:
            return Response({'success': False, 'error': 'User not found.'}, status=404)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=500)
        

  
    
@csrf_exempt
def extract_headings_api(request):
    html_file = request.GET.get('html_file')
    if not html_file:
        return JsonResponse({'success': False, 'error': 'No file specified'})
    TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'templates')
    abs_path = os.path.join(TEMPLATES_DIR, html_file)
    if not os.path.exists(abs_path):
        return JsonResponse({'success': False, 'error': 'File not found'})
    headings = extract_table_headings_from_html(abs_path)
    return JsonResponse({'success': True, 'headings': headings})

@csrf_exempt  # Remove this if you use CSRF tokens correctly in JS
def swap_login(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            username = data.get("username")
            password = data.get("password")
            user = authenticate(request, username=username, password=password)
            if user is not None:
                # Optionally, you can log in the user or just return success
                return JsonResponse({"success": True})
            else:
                return JsonResponse({"success": False, "error": "Invalid credentials"})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"}, status=400)

class UserDetailAPIView(APIView):
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            profile = getattr(user, 'userprofile', None)
            group = user.groups.first()
            return Response({
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "department_id": profile.department.id if profile and profile.department else "",
                "role_id": profile.role.id if profile and profile.role else "",
                "manager": profile.manager if profile else "",
                "employment_status": profile.employment_status if profile else "",
                "group_id": group.id if group else "",
            })
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

    def put(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            data = request.data
            user.username = data.get('username', user.username)
            user.first_name = data.get('first_name', user.first_name)
            user.last_name = data.get('last_name', user.last_name)
            user.email = data.get('email', user.email)
            
            # Update password only if provided
            password = data.get('password')
            if password and password.strip():
                user.set_password(password)
                
            user.save()

            profile = getattr(user, 'userprofile', None)
            if profile:
                department_id = data.get('department')
                role_id = data.get('role')
                if department_id:
                    profile.department_id = department_id
                if role_id:
                    profile.role_id = role_id
                profile.manager = data.get('manager', profile.manager)
                profile.employment_status = data.get('employment_status', profile.employment_status)
                profile.save()

            group_id = data.get('group')
            if group_id:

                group = Group.objects.filter(id=group_id).first()
                if group:
                    user.groups.clear()
                    user.groups.add(group)

            return Response({'success': True, 'message': 'User updated successfully.'})
        except User.DoesNotExist:
            return Response({'success': False, 'error': 'User not found.'}, status=404)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=500)

    def delete(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.delete()
            return Response({'success': True, 'message': 'User deleted.'}, status=200)
        except User.DoesNotExist:
            return Response({'success': False, 'error': 'User not found.'}, status=404)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=500)
            
        
# Safe class - static handling
""" @method_decorator(login_required(login_url='login-api'), name='dispatch')
class DP_PickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Day_Planning/DP_PickTable.html'

    def get(self, request, format=None):
        # ...your existing logic to get master_data, etc...
        user = request.user
        # Example: Assume module_name is "DayPlanningPickTable"
        module_name = "DP Pick Table"
        # Get allowed headings for this user/module
        allowed_headings = []
        provision = UserModuleProvision.objects.filter(user=user, module_name=module_name).first()
        print('Provision:', provision)
        if provision and provision.headings:
            allowed_headings = provision.headings
            print(f"User {user.username} has specific module provisions: {allowed_headings}")
        else:
            # fallback: show all headings if not restricted
            allowed_headings = [
                "S.No", "Last Updated", "Plating Stk No", "Polishing Stk No", "Plating Color",
                "Category", "Polish Finish", "Version", "Tray Cate-Capacity", "Source",
                "No of Trays", "Input Qty", "Process Status", "Action", "Lot Status",
                "Current Stage", "Remarks"
            ]
            print(f"User {user.username} has no specific module provisions, using default headings: {allowed_headings}" )
        context = {
            # ...existing context...
            'allowed_headings': allowed_headings,
            # ...other context...
        }
        return Response(context)
 """



def get_visible_headings_for_user(user, module_name):
    """
    Returns a dict: {heading: True/False} for all headings of the module.
    True = editable, False = non-editable (blurred).
    """
    module = Module.objects.filter(name=module_name).first()
    all_headings = module.headings if module else []
    provision = UserModuleProvision.objects.filter(user=user, module_name=module_name).first()
    allowed_headings = provision.headings if (provision and provision.headings) else all_headings
    return {h: h in allowed_headings for h in all_headings}


# Class for Generic Module Table View
@method_decorator(login_required(login_url='login-api'), name='dispatch')
class ModuleTableView(APIView):
    """
    Generic view for any module table.
    Usage: pass module_name as a URL kwarg or query param.
    Example URL: /adminportal/module-table/?module_name=DP Pick Table
    """
    renderer_classes = [TemplateHTMLRenderer]

    def get(self, request, *args, **kwargs):
        # 1. Get module_name from URL (query param or kwarg)
        module_name = kwargs.get('module_name') or request.GET.get('module_name')
        if not module_name:
            return Response({'error': 'Module name not specified.'}, status=400)

        # 2. Fetch the Module object
        module = Module.objects.filter(name=module_name).first()
        if not module:
            return Response({'error': f'Module "{module_name}" not found.'}, status=404)

        # 3. Get the template file name from the module
        template_name = module.html_file or 'Day_Planning/DP_PickTable.html'
        self.template_name = template_name

        # 4. Get allowed headings for this user/module from UserModuleProvision
        provision = UserModuleProvision.objects.filter(user=request.user, module_name=module_name).first()
        if provision and provision.headings:
            allowed_headings = provision.headings
        else:
            # fallback: use all headings from the Module master
            allowed_headings = module.headings or []

        visible_headings = get_visible_headings_for_user(request.user, module_name)
        context = {
            'allowed_headings': allowed_headings,
            'module_name': module_name,
            'visible_headings': visible_headings,
        }
        return Response(context)


# Function for checking if a user is an admin for heading blurred logic 
# Function for checking if a user is an admin for heading blurred logic 
def is_admin_user(user):
    """
    Returns True if the user is superuser, in Admin group, or department is Admin.
    """
    if not user.is_authenticated:
        return False
    return (
        user.is_superuser
        or user.groups.filter(name__iexact="Admin").exists()
        or (
            hasattr(user, 'userprofile')
            and user.userprofile.department
            and user.userprofile.department.name.lower() == "admin"
        )
    )

class UserPageAPIView(APIView):
    def get(self, request):
        user_id = request.GET.get('user_id')
        if not user_id:
            return Response({'error': 'User ID required'}, status=400)
        
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)
            
        # Must match UserListAPIView ordering (id ascending)
        position = User.objects.filter(id__lt=user_id).count() 
        
        page_size = 6 # Must match UserListAPIView
        page_number = (position // page_size) + 1
        
        return Response({'page': page_number})
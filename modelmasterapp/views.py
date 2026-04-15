from django.shortcuts import render, redirect, get_object_or_404
from rest_framework import status
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from modelmasterapp.models import (
    ModelMasterCreation, TrayId, DraftTrayId, TotalStockModel,
    DP_TrayIdRescan, Brass_QC_Rejection_ReasonStore,
    IQF_Rejection_ReasonStore, Brass_QC_Rejected_TrayScan, IQF_Rejected_TrayScan, Brass_Qc_Accepted_TrayScan, IQF_Accepted_TrayScan,
     Brass_Qc_Accepted_TrayID_Store, IQF_Accepted_TrayID_Store,TrayAutoSaveData
)
from IQF.models import *
from Jig_Loading.models import JigLoadTrayId
from Jig_Unloading.models import JigUnload_TrayId, JigUnloadAfterTable
from BrassAudit.models import *
from InputScreening.models import (
    IPTrayId, IP_TrayVerificationStatus, IP_Rejection_ReasonStore,
    IP_Rejected_TrayScan, IP_Accepted_TrayScan, IP_Accepted_TrayID_Store, IP_Rejection_Draft,IP_Rejection_Table
)
from Brass_QC.models import *
from Nickel_Audit.models import *
from Nickel_Inspection.models import *
from Recovery_DP.models import *
from Recovery_IS.models import *
from Recovery_Brass_QC.models import *
from Recovery_BrassAudit.models import *
from Recovery_IQF.models import *
from django.contrib.auth import authenticate, login, logout
from rest_framework.renderers import TemplateHTMLRenderer, JSONRenderer
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q

class BaseAPIView(APIView):
    """
    API View to return user details, fetch TrayId data based on barcodeInput,
    and fetch additional details from ModelMasterCreation and TotalStockModel.
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, *args, **kwargs):
        # Fetch user details
        user = request.user
        context = {
            'username': user.username,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        }

        # Get barcodeInput from query parameters
        barcode_input = request.query_params.get('barcodeInput')
        if barcode_input:
            try:
                # Fetch the TrayId object based on the barcodeInput
                tray = get_object_or_404(TrayId, tray_id=barcode_input)
                print(f"[DEBUG] TrayId fetched: {tray.tray_id} - {tray.lot_id} - {tray.tray_quantity}")

                # Add TrayId details to the response
                context['tray_details'] = {
                    'tray_id': tray.tray_id,
                    'lot_id': tray.lot_id,
                    'tray_quantity': tray.tray_quantity,
                }

                # Fetch the batch_id and model_stock_no from TrayId
                batch_id = tray.batch_id
                model_stock_no = tray.batch_id.model_stock_no if tray.batch_id else None

                if batch_id and model_stock_no:
                    # Check if the batch_id and model_stock_no exist in ModelMasterCreation
                    try:
                        model_master = get_object_or_404(
                            ModelMasterCreation,
                            batch_id=batch_id.batch_id,  # Match batch_id
                            model_stock_no=model_stock_no  # Match model_stock_no
                        )
                        print(f"[DEBUG] ModelMasterCreation fetched for batch_id {batch_id.batch_id} and model_stock_no {model_stock_no}")

                        # Fetch associated images
                        mmc = batch_id  # assuming batch_id is ModelMasterCreation instance
                        model_images = [img.master_image.url for img in mmc.images.all()] if mmc else []
                        print(f"[DEBUG] ModelMasterCreation images fetched: {model_images}")
                        
                        # Add ModelMasterCreation details to the response
                        context['model_master_details'] = {
                            'model_stock_no': model_master.model_stock_no.model_no,
                            'polish_finish': model_master.polish_finish,
                            'plating_color': model_master.plating_color,
                            'version': model_master.version.version_name,
                            'vendor_internal': model_master.vendor_internal,
                            'location': model_master.location.location_name if model_master.location else None,
                            'model_images': model_images,  # ✅ Pass the actual list of URLs
                        }
                    except Exception as e:
                        print(f"[ERROR] Error fetching ModelMasterCreation: {e}")
                        context['model_master_details'] = f"ModelMasterCreation not found for batch_id: {batch_id.batch_id} and model_stock_no: {model_stock_no}"
                else:
                    print("[DEBUG] No batch_id or model_stock_no found in TrayId")
                    context['model_master_details'] = "No batch_id or model_stock_no found in TrayId"

                # Fetch TotalStockModel details based on lot_id
                try:
                    total_stock = get_object_or_404(TotalStockModel, lot_id=tray.lot_id)
                    print(f"[DEBUG] TotalStockModel fetched for lot_id {tray.lot_id}")

                    # Add TotalStockModel details to the response
                    context['total_stock_details'] = {
                        'last_process_date_time': total_stock.last_process_date_time,
                        'last_process_module': total_stock.last_process_module,
                        'next_process_module': total_stock.next_process_module,
                        'total_stock': total_stock.total_stock,  # Include total_stock in the response
                    }
                except Exception as e:
                    print(f"[ERROR] Error fetching TotalStockModel: {e}")
                    context['total_stock_details'] = f"TotalStockModel not found for lot_id: {tray.lot_id}"

            except Exception as e:
                print(f"[ERROR] Error fetching TrayId: {e}")
                return Response({
                    'success': False,
                    'error': f"TrayId not found for barcodeInput: {barcode_input}"
                }, status=status.HTTP_404_NOT_FOUND)

        return Response(context, status=status.HTTP_200_OK)


class GetLotByModelAPIView(APIView):
    """API to fetch tray/lot/model details by model number or related identifiers."""
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, *args, **kwargs):
        model_no = request.query_params.get('model_no')
        if not model_no:
            return Response({'error': 'model_no required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Search through related ModelMasterCreation / ModelMaster fields
            trays = TrayId.objects.filter(
                Q(batch_id__model_stock_no__model_no__icontains=model_no) |
                Q(batch_id__plating_stk_no__icontains=model_no) |
                Q(lot_id__icontains=model_no) |
                Q(tray_id__iexact=model_no)
            )
            if not trays.exists():
                return Response({'error': 'No data found'}, status=status.HTTP_404_NOT_FOUND)

            tray = trays.first()

            context = {}
            context['tray_details'] = {
                'tray_id': tray.tray_id,
                'lot_id': tray.lot_id,
                'tray_quantity': tray.tray_quantity,
            }

            # Use the related ModelMasterCreation (batch) directly
            batch = tray.batch_id
            if batch:
                try:
                    model_images = [img.master_image.url for img in batch.images.all()] if hasattr(batch, 'images') else []
                    # Determine vendor/internal source string: prefer batch.vendor_internal (explicit),
                    # otherwise try the related ModelMaster -> Vendor.vendor_internal
                    vendor_internal_value = None
                    if batch.vendor_internal:
                        vendor_internal_value = batch.vendor_internal
                    else:
                        mm = getattr(batch, 'model_stock_no', None)
                        if mm and getattr(mm, 'vendor_internal', None):
                            # mm.vendor_internal is a FK to Vendor; prefer its vendor_internal field
                            try:
                                vendor_internal_value = mm.vendor_internal.vendor_internal or mm.vendor_internal.vendor_name
                            except Exception:
                                vendor_internal_value = str(mm.vendor_internal)

                    # Also fall back to location name if vendor_internal is still empty
                    if not vendor_internal_value and batch.location:
                        vendor_internal_value = batch.location.location_name

                    context['model_master_details'] = {
                        'model_stock_no': getattr(batch.model_stock_no, 'model_no', None),
                        'polish_finish': batch.polish_finish,
                        'plating_color': batch.plating_color,
                        'version': getattr(batch.version, 'version_name', None),
                        'vendor_internal': vendor_internal_value,
                        'location': batch.location.location_name if batch.location else None,
                        'model_images': model_images,
                    }
                except Exception as e:
                    context['model_master_details'] = f"Error reading batch/model data: {e}"
            else:
                context['model_master_details'] = "No batch_id found for this TrayId"

            try:
                total_stock = TotalStockModel.objects.filter(lot_id=tray.lot_id).first()
                if total_stock:
                    # Format last_process_date_time to human-readable string
                    # Fall back to created_at if last_process_date_time is not set (e.g. Day Planning stage)
                    date_value = total_stock.last_process_date_time or total_stock.created_at
                    formatted_date = ''
                    if date_value:
                        formatted_date = date_value.strftime('%d %b %Y, %I:%M %p')

                    # Determine input_type: "Recovery" only if lot came from a Recovery module
                    input_type = 'Fresh'
                    last_mod = (total_stock.last_process_module or '').lower()
                    next_mod = (total_stock.next_process_module or '').lower()
                    if 'recovery' in last_mod or 'recovery' in next_mod:
                        input_type = 'Recovery'

                    # Compute current stage lot qty based on last_process_module
                    current_qty = total_stock.total_stock  # default: original DP qty
                    if 'jig unloading' in last_mod or 'inprocess' in last_mod:
                        current_qty = total_stock.jig_physical_qty or total_stock.total_stock
                    elif 'jig' in last_mod:
                        current_qty = total_stock.jig_physical_qty or total_stock.total_stock
                    elif 'iqf' in last_mod:
                        current_qty = total_stock.iqf_accepted_qty or total_stock.total_stock
                    elif 'brass audit' in last_mod:
                        current_qty = total_stock.brass_audit_accepted_qty or total_stock.total_stock
                    elif 'brass' in last_mod:
                        current_qty = total_stock.brass_qc_accepted_qty or total_stock.total_stock
                    elif 'input' in last_mod or 'screening' in last_mod:
                        current_qty = total_stock.total_IP_accpeted_quantity or total_stock.total_stock
                    elif 'day' in last_mod or 'planning' in last_mod:
                        if total_stock.dp_physical_qty_edited and total_stock.dp_physical_qty:
                            current_qty = total_stock.dp_physical_qty

                    context['total_stock_details'] = {
                        'last_process_date_time': formatted_date,
                        'last_process_module': total_stock.last_process_module or 'Day Planning',
                        'next_process_module': total_stock.next_process_module or 'Input Screening',
                        'total_stock': total_stock.total_stock,
                        'input_type': input_type,
                        'lot_qty': current_qty,
                    }
                else:
                    context['total_stock_details'] = "TotalStockModel not found for this lot"
            except Exception as e:
                context['total_stock_details'] = f"Error fetching TotalStockModel: {e}"

            return Response(context, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
class LoginAPIView(APIView):
    renderer_classes = [TemplateHTMLRenderer, JSONRenderer]
    template_name = 'login.html'

    def get(self, request, *args, **kwargs):
        # Render the login page on GET
        return Response({}, template_name=self.template_name)

    def post(self, request, *args, **kwargs):
        username = request.data.get('username') or request.POST.get('username')
        password = request.data.get('password') or request.POST.get('password')

        # Basic validation
        if not username or not password:
            error_msg = 'Please enter both username and password.'
            if request.accepted_renderer.format == 'html':
                return Response({
                    'error': error_msg,
                    'username': username or ''
                }, template_name=self.template_name, status=status.HTTP_400_BAD_REQUEST)
            return Response({
                'success': False, 
                'message': error_msg
            }, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                login(request, user)
                if request.accepted_renderer.format == 'html':
                    return redirect('index')
                return Response({
                    'success': True, 
                    'message': 'Login successful'
                }, status=status.HTTP_200_OK)
            else:
                error_msg = 'Your account has been deactivated. Please contact support.'
                if request.accepted_renderer.format == 'html':
                    return Response({
                        'error': error_msg,
                        'username': username
                    }, template_name=self.template_name, status=status.HTTP_401_UNAUTHORIZED)
                return Response({
                    'success': False, 
                    'message': error_msg
                }, status=status.HTTP_401_UNAUTHORIZED)
        else:
            # Invalid credentials
            error_msg = 'Invalid username or password. Please try again.'
            if request.accepted_renderer.format == 'html':
                return Response({
                    'error': error_msg,
                    'username': username
                }, template_name=self.template_name, status=status.HTTP_401_UNAUTHORIZED)
            return Response({
                'success': False, 
                'message': error_msg
            }, status=status.HTTP_401_UNAUTHORIZED)

def logout_view(request):
    logout(request)
    return redirect('login-api')  # Redirect to login page after logout


from django.http import JsonResponse
from django.views.decorators.http import require_POST
@csrf_exempt
@require_POST
def delete_all_tables(request):
    # List all model classes you want to clear
    model_list = [
    ModelMasterCreation,
    TrayId,
    IPTrayId,
    BrassTrayId,
    IQFTrayId,
    IP_TrayVerificationStatus,
    DraftTrayId,
    TotalStockModel,
    DP_TrayIdRescan,
    IP_Rejection_Draft,
    IP_Rejection_ReasonStore,
    Brass_QC_Rejection_ReasonStore,
    IQF_Rejection_ReasonStore,
    IP_Rejected_TrayScan,
    Brass_QC_Rejected_TrayScan,
    IQF_Rejected_TrayScan,
    IP_Accepted_TrayScan,
    Brass_Qc_Accepted_TrayScan,
    Brass_Qc_Accepted_TrayID_Store,
    IQF_Accepted_TrayScan,
    IP_Accepted_TrayID_Store,
    Brass_Qc_Accepted_TrayID_Store,
    Brass_QC_Draft_Store,
    Brass_TopTray_Draft_Store,
    Brass_Audit_Rejection_ReasonStore,
    Brass_Audit_Draft_Store,
    Brass_Audit_TopTray_Draft_Store,
    Brass_Audit_Rejected_TrayScan,
    Brass_Audit_Accepted_TrayScan,
    Brass_Audit_Accepted_TrayID_Store,
    IQF_Accepted_TrayID_Store,
    JigLoadTrayId,
    JigUnload_TrayId,
    JigUnloadAfterTable,
    TrayAutoSaveData,
    Nickel_AuditTrayId,
    Nickel_Audit_Rejection_ReasonStore,
    Nickel_Audit_Draft_Store,
    Nickel_Audit_TopTray_Draft_Store,
    Nickel_Audit_Rejected_TrayScan,
    Nickel_Audit_Accepted_TrayScan,
    Nickel_Audit_Accepted_TrayID_Store,
    NickelQcTrayId,
    Nickel_QC_Rejection_ReasonStore,
    Nickel_QC_Draft_Store,
    Nickel_QC_TopTray_Draft_Store,
    Nickel_QC_Rejected_TrayScan,
    Nickel_Qc_Accepted_TrayScan,
    Nickel_Qc_Accepted_TrayID_Store,
    RecoveryTrayId,
    RecoveryDraftTrayId,
    RecoveryStockModel,
    RecoveryTrayId_History,
    RecoveryMasterCreation,
    RecoveryIPTrayId,
    RecoveryIP_Rejection_ReasonStore,
    RecoveryIP_Rejected_TrayScan,
    RecoveryIP_Accepted_TrayScan,
    RecoveryIP_Accepted_TrayID_Store,
    RecoveryIP_Rejection_Draft,
    RecoveryBrassTrayId,
    RecoveryBrass_QC_Rejection_ReasonStore,
    RecoveryBrass_QC_Rejected_TrayScan,
    RecoveryBrass_Qc_Accepted_TrayScan,
    RecoveryBrass_Qc_Accepted_TrayID_Store,
    RecoveryBrass_QC_Draft_Store,
    RecoveryBrass_TopTray_Draft_Store,
    RecoveryBrassAuditTrayId,
    RecoveryBrass_Audit_Rejection_ReasonStore,
    RecoveryBrass_Audit_Draft_Store,
    RecoveryBrass_Audit_TopTray_Draft_Store,
    RecoveryBrass_Audit_Rejected_TrayScan,
    RecoveryBrass_Audit_Accepted_TrayScan,
    RecoveryBrass_Audit_Accepted_TrayID_Store,
    RecoveryIQFTrayId,
    RecoveryIQF_Draft_Store,
    RecoveryIQF_Accepted_TrayScan,
    RecoveryIQF_Accepted_TrayID_Store,
    RecoveryIQF_Rejection_ReasonStore,
    RecoveryIQF_Rejected_TrayScan,
    RecoveryIQF_OptimalDistribution_Draft
]
    for model in model_list:
        model.objects.all().delete()
    return JsonResponse({'status': 'success', 'message': 'All tables cleared.'})


from modelmasterapp.models import ModelMaster
from django.views.decorators.http import require_GET as _require_GET

@_require_GET
def get_plating_images(request):
    """Return images for a given plating_stk_no from ModelMaster."""
    plating_stk_no = request.GET.get('plating_stk_no', '').strip()
    if not plating_stk_no:
        return JsonResponse({'images': []})

    import re as _re
    mm = ModelMaster.objects.prefetch_related('images').filter(plating_stk_no=plating_stk_no).first()

    # Fallback: try numeric prefix match (e.g. '1805' matches '1805NAK02')
    if not mm:
        _m = _re.match(r'^(\d+)', plating_stk_no)
        if _m:
            mm = ModelMaster.objects.prefetch_related('images').filter(
                plating_stk_no__startswith=_m.group(1)
            ).first()

    if mm and mm.images.exists():
        image_urls = [img.master_image.url for img in mm.images.all() if img.master_image]
        return JsonResponse({'images': image_urls})

    return JsonResponse({'images': []})

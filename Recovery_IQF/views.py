from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import TemplateHTMLRenderer
from django.shortcuts import render
from django.db.models import OuterRef, Subquery, Exists, F
from django.core.paginator import Paginator
from django.templatetags.static import static
import math
from Recovery_Brass_QC.models import *
from Recovery_BrassAudit.models import *
from Recovery_DP.models import *
from Recovery_IS.models import *
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

# Create your views here.

def generate_new_lot_id():
        from datetime import datetime
        timestamp = datetime.now().strftime("%d%m%Y%H%M%S")
        last_lot = RecoveryStockModel.objects.order_by('-id').first()
        if last_lot and last_lot.lot_id and last_lot.lot_id.startswith("RLID"):
            last_seq_no = int(last_lot.lot_id[-4:])
            next_seq_no = last_seq_no + 1
        else:
            next_seq_no = 1
        seq_no = f"{next_seq_no:04d}"
        return f"RLID{timestamp}{seq_no}"
    
    
class RecoveryIQFPickTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Recovery_IQF/Recovery_Iqf_PickTable.html'

    def get(self, request):
        user = request.user
        is_admin = user.groups.filter(name='Admin').exists() if user.is_authenticated else False

        lot_id = request.GET.get('lot_id')
        iqf_rejection_reasons = RecoveryIQF_Rejection_Table.objects.all()

        # ✅ CHANGED: Query RecoveryStockModel directly instead of RecoveryMasterCreation
        brass_rejection_qty_subquery = RecoveryBrass_QC_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        iqf_rejection_qty_subquery = RecoveryIQF_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = RecoveryStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            batch_id__total_batch_quantity__gt=0
        ).annotate(
            wiping_required=F('batch_id__model_stock_no__wiping_required'),
            brass_rejection_total_qty=brass_rejection_qty_subquery,
            iqf_rejection_qty=iqf_rejection_qty_subquery,
        ).filter(
            # ✅ Direct filtering on RecoveryStockModel fields (no more subquery filtering)
            (
                Q(brass_qc_rejection=True) |
                Q(send_brass_audit_to_iqf=True) |
                Q(brass_qc_few_cases_accptance=True, brass_onhold_picking=False)
            )
        ).exclude(
            Q(iqf_acceptance=True) | 
            Q(iqf_rejection=True) | 
            Q(iqf_few_cases_acceptance=True, iqf_onhold_picking=False)
        ).order_by('-bq_last_process_date_time', '-lot_id')

        print(f"📊 Found {queryset.count()} Recovery IQF pick records")
        print("All lot_ids in Recovery IQF pick queryset:", list(queryset.values_list('lot_id', flat=True)))

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        # ✅ UPDATED: Build master_data from RecoveryStockModel records
        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            
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
                'Draft_Saved': batch.Draft_Saved,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                
                # ✅ Stock-related fields from RecoveryStockModel
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
                'brass_accepted_tray_scan_status': stock_obj.brass_accepted_tray_scan_status,
                'brass_qc_rejection': stock_obj.brass_qc_rejection,  # ✅ Direct access
                'brass_rejection_total_qty': stock_obj.brass_rejection_total_qty,
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
                'send_brass_audit_to_iqf': stock_obj.send_brass_audit_to_iqf,
            }
            master_data.append(data)

        print(f"[RecoveryIQFPickTableView] Total master_data records: {len(master_data)}")
        
        # ✅ Process the data (same logic as before)
        for data in master_data:
            print(data['batch_id'], data['brass_rejection_total_qty'])

        for data in master_data:
            brass_rejection_total_qty = data.get('brass_rejection_total_qty') or 0
            tray_capacity = data.get('tray_capacity') or 0
            total_IP_accpeted_quantity = data.get('total_IP_accpeted_quantity') or 0
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            
            # Use total_IP_accpeted_quantity if brass_rejection_total_qty is zero
            qty_for_trays = brass_rejection_total_qty if brass_rejection_total_qty > 0 else total_IP_accpeted_quantity
            
            if tray_capacity and tray_capacity > 0:
                data['no_of_trays'] = math.ceil(qty_for_trays / tray_capacity)
            else:
                data['no_of_trays'] = 0

            # Get model images
            batch_obj = RecoveryMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj:
                model_master = batch_obj.model_stock_no
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            # Add available_qty for each row
            lot_id = data.get('stock_lot_id')
            total_stock_obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if total_stock_obj:
                if total_stock_obj.iqf_physical_qty and total_stock_obj.iqf_physical_qty > 0:
                    data['available_qty'] = total_stock_obj.iqf_physical_qty
                else:
                    data['available_qty'] = data.get('brass_rejection_total_qty', 0)
            else:
                data['available_qty'] = 0
            
            # Add display_physical_qty for frontend
            iqf_physical_qty = data.get('iqf_physical_qty', 0)
            if iqf_physical_qty and iqf_physical_qty > 0:
                data['display_physical_qty'] = iqf_physical_qty
            else:
                data['display_physical_qty'] = data.get('brass_rejection_total_qty', 0)

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
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_brass_rejection_quantities(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # Fetch rejection reasons from database
        rejection_reasons = []
        for reason in RecoveryIQF_Rejection_Table.objects.all().order_by('id'):
            rejection_reasons.append({
                'id': reason.id,
                'rejection_reason_id': reason.rejection_reason_id,
                'rejection_reason': reason.rejection_reason
            })
        
        # Fetch brass rejection quantities for this lot_id
        brass_rejected_trays = RecoveryBrass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id)
        brass_rejection_qty_map = {}
        
        for tray in brass_rejected_trays:
            reason = tray.rejection_reason.rejection_reason.strip()
            qty = int(tray.rejected_tray_quantity) if tray.rejected_tray_quantity else 0
            if reason in brass_rejection_qty_map:
                brass_rejection_qty_map[reason] += qty
            else:
                brass_rejection_qty_map[reason] = qty

        # If no tray-wise reasons, show lot_rejected_comment from RecoveryBrass_QC_Rejection_ReasonStore
        lot_rejected_comment = ""
        if not brass_rejection_qty_map:
            reason_store = RecoveryBrass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
            if reason_store:
                lot_rejected_comment = reason_store.lot_rejected_comment or ""

        return Response({
            'success': True,
            'rejection_reasons': rejection_reasons,
            'brass_rejection_qty_map': brass_rejection_qty_map,
            'lot_rejected_comment': lot_rejected_comment  # <-- Added this field
        })
    except Exception as e:
        print(f"❌ ERROR in recovery_iqf_get_brass_rejection_quantities: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=500)  
    
@method_decorator(csrf_exempt, name='dispatch')
class RecoveryIQFSaveHoldUnholdReasonAPIView(APIView):
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

            obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if not obj:
                return JsonResponse({'success': False, 'error': 'LOT not found.'}, status=404)

            if action == 'hold':
                obj.iqf_holding_reason = remark
                obj.iqf_hold_lot = True
                obj.iqf_release_reason = ''
                obj.iqf_release_lot = False
            elif action == 'unhold':
                obj.iqf_release_reason = remark
                obj.iqf_hold_lot = False
                obj.iqf_release_lot = True

            obj.save(update_fields=['iqf_holding_reason', 'iqf_release_reason', 'iqf_hold_lot', 'iqf_release_lot'])
            return JsonResponse({'success': True, 'message': 'Reason saved.'})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        
@method_decorator(csrf_exempt, name='dispatch')  
@method_decorator(login_required, name='dispatch')  
class RecoveryIQFSaveIPCheckboxView(APIView):
    def post(self, request, format=None):
        try:
            data = request.data
            lot_id = data.get("lot_id")
            missing_qty = data.get("missing_qty")

            if not lot_id:
                return Response({"success": False, "error": "Lot ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            total_stock = RecoveryStockModel.objects.get(lot_id=lot_id)
            total_stock.iqf_accepted_qty_verified = True
            total_stock.last_process_module = "Recovery IQF"
            total_stock.next_process_module = "Recovery Brass QC"

            brass_rejection_obj = RecoveryBrass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            brass_rejection_total_qty = brass_rejection_obj.total_rejection_quantity if brass_rejection_obj else 0
            
            # Use total_IP_accpeted_quantity if send_brass_audit_to_iqf is True
            use_total_qty = brass_rejection_total_qty
            if getattr(total_stock, 'send_brass_audit_to_iqf', False):
                use_total_qty = getattr(total_stock, 'total_IP_accpeted_quantity', 0) or 0
            
            if missing_qty not in [None, ""]:
                try:
                    missing_qty = int(missing_qty)
                except ValueError:
                    return Response({"success": False, "error": "Missing quantity must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
            
                # Case 1: missing_qty == use_total_qty
                if missing_qty == use_total_qty:
                    return Response(
                        {"success": False, "error": "Missing quantity cannot be equal to assigned quantity."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
                # Case 2: missing_qty > use_total_qty
                if missing_qty > use_total_qty:
                    return Response(
                        {"success": False, "error": "Missing quantity must be less than assigned quantity."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
                # Case 3: missing_qty < use_total_qty (allow)
                total_stock.iqf_missing_qty = missing_qty
                total_stock.iqf_physical_qty = use_total_qty - missing_qty
            total_stock.save()

 # ✅ If send_brass_audit_to_iqf is True, create RecoveryIQFTrayId from RecoveryBrassAuditTrayId (rejected_tray=True)
            if getattr(total_stock, 'send_brass_audit_to_iqf', False):
                rejected_trays = RecoveryBrassAuditTrayId.objects.filter(lot_id=lot_id, rejected_tray=True)
            else:
                rejected_trays = RecoveryBrassTrayId.objects.filter(lot_id=lot_id, rejected_tray=True)
            
            created_count = 0
            updated_count = 0

            for tray in rejected_trays:
                iqf_tray, created = RecoveryIQFTrayId.objects.get_or_create(
                    tray_id=tray.tray_id,
                    lot_id=lot_id,
                    defaults={
                        'lot_id': lot_id,
                        'batch_id': tray.batch_id,
                        'tray_quantity': tray.tray_quantity,
                        'tray_capacity': tray.tray_capacity,
                        'tray_type': tray.tray_type,
                        'rejected_tray': True,
                        'IP_tray_verified': True,
                        'new_tray': False,
                    }
                )
                if not created:
                    iqf_tray.lot_id = lot_id
                    iqf_tray.batch_id = tray.batch_id
                    iqf_tray.tray_quantity = tray.tray_quantity
                    iqf_tray.tray_capacity = tray.tray_capacity
                    iqf_tray.tray_type = tray.tray_type
                    iqf_tray.rejected_tray = True
                    iqf_tray.IP_tray_verified = True
                    iqf_tray.new_tray = False
                    iqf_tray.save(update_fields=[
                        'lot_id', 'batch_id', 'tray_quantity', 'tray_capacity',
                        'tray_type', 'rejected_tray', 'IP_tray_verified', 'new_tray'
                    ])
                    updated_count += 1
                else:
                    created_count += 1

            print(f"✅ Synced rejected trays to RecoveryIQFTrayId: created={created_count}, updated={updated_count}")
            
            return Response({"success": True})

        except RecoveryStockModel.DoesNotExist:
            return Response({"success": False, "error": "Stock not found."}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"success": False, "error": "Unexpected error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class RecoveryIQFSaveIPPickRemarkAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            batch_id = data.get('batch_id')
            remark = data.get('remark', '').strip()
            if not batch_id:
                return JsonResponse({'success': False, 'error': 'Missing batch_id'}, status=400)
            mmc = RecoveryMasterCreation.objects.filter(batch_id=batch_id).first()
            if not mmc:
                return JsonResponse({'success': False, 'error': 'Batch not found'}, status=404)
            batch_obj = RecoveryStockModel.objects.filter(batch_id=mmc).first()  
            if not batch_obj:
                return JsonResponse({'success': False, 'error': 'RecoveryStockModel not found'}, status=404)
            batch_obj.IQF_pick_remarks = remark
            batch_obj.save(update_fields=['IQF_pick_remarks'])
            return JsonResponse({'success': True, 'message': 'Remark saved'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class RecoveryIQFTrayValidate_Complete_APIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            tray_id = str(data.get('tray_id', '')).strip()

            # Only check if tray_id exists in RecoveryTrayId table
            exists = RecoveryTrayId.objects.filter(tray_id=tray_id).exists()

            return JsonResponse({
                'success': True,
                'exists': exists
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
# 1. ADD THIS API VIEW TO YOUR views.py

@method_decorator(csrf_exempt, name='dispatch')
class RecoveryIQFCompleteTableTrayIdListAPIView(APIView):
    def get(self, request):
        lot_id = request.GET.get("lot_id")
        if not lot_id:
            return Response({"success": False, "error": "Lot ID is required"}, status=400)

        try:
            # Get all trays from RecoveryIQFTrayId table for this lot
            total_stock = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            iqf_accepted_qty_verified = False
            if total_stock and hasattr(total_stock, 'iqf_accepted_qty_verified'):
                iqf_accepted_qty_verified = total_stock.iqf_accepted_qty_verified

            # Choose the tray source based on the flag
            # Choose the tray source based on the flag
            if iqf_accepted_qty_verified:
                trays = RecoveryIQFTrayId.objects.filter(lot_id=lot_id)
            elif getattr(total_stock, 'send_brass_audit_to_iqf', False):
                trays = RecoveryBrassAuditTrayId.objects.filter(lot_id=lot_id, rejected_tray=True)
            else:
                trays = RecoveryBrassTrayId.objects.filter(lot_id=lot_id, rejected_tray=True) 
            
            all_trays = []
            for tray in trays:
                tray_data = {
                    "tray_id": tray.tray_id,
                    "tray_quantity": tray.tray_quantity,
                    "rejected_tray": tray.rejected_tray,
                    "delink_tray": getattr(tray, 'delink_tray', False),
                    "iqf_reject_verify": getattr(tray, 'iqf_reject_verify', False),
                    "new_tray": getattr(tray, 'new_tray', False),
                    "IP_tray_verified": getattr(tray, 'IP_tray_verified', False)
                }
                all_trays.append(tray_data)
            
            # Also check if we have accepted trays from IQF_Accepted_TrayID_Store
            accepted_store_trays = IQF_Accepted_TrayID_Store.objects.filter(lot_id=lot_id)
            for store_tray in accepted_store_trays:
                # Check if this tray is already in our list
                existing_tray = next((t for t in all_trays if t['tray_id'] == store_tray.tray_id), None)
                if not existing_tray:
                    all_trays.append({
                        "tray_id": store_tray.tray_id,
                        "tray_quantity": store_tray.tray_qty,
                        "rejected_tray": False,
                        "delink_tray": False,
                        "iqf_reject_verify": False,
                        "new_tray": False,
                        "IP_tray_verified": True
                    })
            
            return Response({
                "success": True,
                "trays": all_trays,
                "total_trays": len(all_trays)
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class RecoveryIQFRejectTableTrayIdListAPIView(APIView):
    def get(self, request):
        lot_id = request.GET.get("lot_id")
        if not lot_id:
            return Response({"success": False, "error": "Lot ID is required"}, status=400)

        try:
            trays = RecoveryIQF_Rejected_TrayScan.objects.filter(lot_id=lot_id)
            all_trays = []
            for tray in trays:
                # Check delink_tray status in RecoveryIQFTrayId
                delink_tray = False
                iqf_tray = RecoveryIQFTrayId.objects.filter(tray_id=tray.tray_id, lot_id=lot_id).first()
                if iqf_tray:
                    delink_tray = getattr(iqf_tray, 'delink_tray', False)
                tray_data = {
                    "tray_id": tray.tray_id,
                    "tray_quantity": tray.rejected_tray_quantity,
                    "rejection_reason": tray.rejection_reason.rejection_reason if tray.rejection_reason else "",
                    "rejected_tray": True,
                    "delink_tray": delink_tray,  # <-- Add this field
                    "user": tray.user.username if tray.user else "",
                    "created_at": tray.created_at if hasattr(tray, "created_at") else None,
                }
                all_trays.append(tray_data)
            
            return Response({
                "success": True,
                "trays": all_trays,
                "total_trays": len(all_trays)
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class RecoveryIQF_Accepted_form(APIView):

    def post(self, request, format=None):
        data = request.data
        lot_id = data.get("stock_lot_id")
        try:
            total_stock_data = RecoveryStockModel.objects.get(lot_id=lot_id)
            total_stock_data.iqf_acceptance = True

            # Use iqf_physical_qty if set and > 0, else use total_stock
            physical_qty = total_stock_data.iqf_physical_qty

            total_stock_data.iqf_accepted_qty = physical_qty

            # Update process modules
            total_stock_data.next_process_module = "Recovery IQF"
            total_stock_data.last_process_module = "Recovery Brass QC"
            total_stock_data.iqf_last_process_date_time = timezone.now()
            total_stock_data.save()

            # Set all RecoveryIQFTrayId for this lot_id to rejected_tray=False
            RecoveryIQFTrayId.objects.filter(lot_id=lot_id).update(rejected_tray=False)

            # --- NEW LOGIC: Create new lot and copy accepted trays ---
            new_lot_id = generate_new_lot_id()

            # Create new RecoveryStockModel instance
            new_total_stock = RecoveryStockModel.objects.create(
                lot_id=new_lot_id,
                model_stock_no=total_stock_data.model_stock_no,
                batch_id=total_stock_data.batch_id,
                version=total_stock_data.version,
                total_stock=total_stock_data.total_stock,
                total_IP_accpeted_quantity=total_stock_data.iqf_accepted_qty,
                polish_finish=total_stock_data.polish_finish,
                plating_color=total_stock_data.plating_color,
                created_at=total_stock_data.created_at,
                last_process_date_time=total_stock_data.last_process_date_time,
                tray_scan_status=True,
                ip_person_qty_verified=True,
                accepted_Ip_stock=True,
                send_brass_qc=True,
                last_process_module="Recovery IQF",
                iqf_last_process_date_time=timezone.now()
            )
            # Fetch accepted trays (rejected_tray=False) for the selected lot_id
            accepted_trays = RecoveryIQFTrayId.objects.filter(lot_id=lot_id, rejected_tray=False)

            # Create new RecoveryIQFTrayId for each accepted tray, but with new_lot_id
            for tray in accepted_trays:
                RecoveryIQFTrayId.objects.create(
                    tray_id=tray.tray_id,
                    lot_id=new_lot_id,
                    batch_id=tray.batch_id,
                    tray_quantity=tray.tray_quantity,
                    tray_capacity=tray.tray_capacity,
                    tray_type=tray.tray_type,
                    rejected_tray=False,
                    IP_tray_verified=True,
                    new_tray=False
                    # add other fields as needed
                )

            return Response({"success": True, "new_lot_id": new_lot_id})

        except RecoveryStockModel.DoesNotExist:
            return Response(
                {"success": False, "error": "Stock not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class RecoveryIQFLotRejectionDraftAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            batch_id = data.get('batch_id')
            lot_id = data.get('lot_id')
            total_qty = data.get('total_qty', 0)
            lot_rejected_comment = data.get('lot_rejected_comment', '').strip()
            is_draft = data.get('is_draft', True)

            if not batch_id or not lot_id or not lot_rejected_comment:
                return Response({'success': False, 'error': 'Missing required fields'}, status=400)

            draft_obj, created = RecoveryIQF_Draft_Store.objects.get_or_create(
                lot_id=lot_id,
                draft_type='combined_rejection',
                defaults={
                    'batch_id': batch_id,
                    'user': request.user,
                    'draft_data': {}
                }
            )

            # Only keep lot rejection data, remove tray rejection
            updated_draft_data = {
                'lot_rejection': {
                    'total_qty': total_qty,
                    'lot_rejected_comment': lot_rejected_comment,
                    'is_draft': is_draft
                },
                'has_lot_rejection': True,
                'last_updated_type': 'lot_rejection',
                'batch_id': batch_id
            }

            draft_obj.draft_data = updated_draft_data
            draft_obj.batch_id = batch_id
            draft_obj.user = request.user
            draft_obj.save()

            return Response({
                'success': True,
                'message': 'Lot rejection draft saved successfully',
                'draft_id': draft_obj.id,
                'combined_draft': True
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class RecoveryIQFTrayRejectionDraftAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            batch_id = data.get('batch_id')
            tray_rejections = data.get('tray_rejections', [])
            accepted_trays = data.get('accepted_trays', [])
            acceptance_remarks = data.get('acceptance_remarks', '')
            is_draft = data.get('is_draft', True)

            if not lot_id or not tray_rejections:
                return Response({'success': False, 'error': 'Missing lot_id or tray_rejections'}, status=400)

            draft_obj, created = RecoveryIQF_Draft_Store.objects.get_or_create(
                lot_id=lot_id,
                draft_type='combined_rejection',
                defaults={
                    'batch_id': batch_id,
                    'user': request.user,
                    'draft_data': {}
                }
            )

            updated_draft_data = {
                'tray_rejection': {
                    'tray_rejections': tray_rejections,
                    'accepted_trays': accepted_trays,
                    'acceptance_remarks': acceptance_remarks,
                    'is_draft': is_draft
                },
                'has_tray_rejection': True,
                'last_updated_type': 'tray_rejection',
                'batch_id': batch_id
            }
            draft_obj.draft_data = updated_draft_data
            draft_obj.batch_id = batch_id
            draft_obj.user = request.user
            draft_obj.save()

            return Response({
                'success': True,
                'message': 'Tray rejection draft saved successfully',
                'draft_id': draft_obj.id,
                'total_rejections': len(tray_rejections),
                'combined_draft': True
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class RecoveryIQFClearDraftAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            clear_type = data.get('clear_type', 'all')  # 'all', 'lot_rejection', 'tray_rejection'

            if not lot_id:
                return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

            # Get the combined draft
            try:
                draft_obj = RecoveryIQF_Draft_Store.objects.get(
                    lot_id=lot_id,
                    draft_type='combined_rejection'
                )
            except RecoveryIQF_Draft_Store.DoesNotExist:
                return Response({'success': True, 'message': 'No draft found to clear'})

            if clear_type == 'all':
                # Delete the entire draft record
                draft_obj.delete()
                return Response({'success': True, 'message': 'All drafts cleared successfully'})
            
            elif clear_type == 'lot_rejection':
                # Remove only lot rejection data
                draft_data = draft_obj.draft_data or {}
                draft_data.pop('lot_rejection', None)
                draft_data.pop('has_lot_rejection', None)
                
                # If no tray rejection data exists, delete the record
                if not draft_data.get('has_tray_rejection'):
                    draft_obj.delete()
                else:
                    draft_obj.draft_data = draft_data
                    draft_obj.save()
                
                return Response({'success': True, 'message': 'Lot rejection draft cleared successfully'})
            
            elif clear_type == 'tray_rejection':
                # Remove only tray rejection data
                draft_data = draft_obj.draft_data or {}
                draft_data.pop('tray_rejection', None)
                draft_data.pop('has_tray_rejection', None)
                
                # If no lot rejection data exists, delete the record
                if not draft_data.get('has_lot_rejection'):
                    draft_obj.delete()
                else:
                    draft_obj.draft_data = draft_data
                    draft_obj.save()
                
                return Response({'success': True, 'message': 'Tray rejection draft cleared successfully'})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_draft_data(request):
    """Get combined draft data for a lot_id"""
    lot_id = request.GET.get('lot_id')
    
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        draft_obj = RecoveryIQF_Draft_Store.objects.filter(
            lot_id=lot_id,
            draft_type='combined_rejection'
        ).first()
        
        if draft_obj and draft_obj.draft_data:
            draft_data = draft_obj.draft_data
            return Response({
                'success': True,
                'has_draft': True,
                'has_lot_rejection': draft_data.get('has_lot_rejection', False),
                'has_tray_rejection': draft_data.get('has_tray_rejection', False),
                'lot_rejection_data': draft_data.get('lot_rejection', {}),
                'tray_rejection_data': draft_data.get('tray_rejection', {}),
                'last_updated_type': draft_data.get('last_updated_type', ''),
                'created_at': draft_obj.created_at,
                'updated_at': draft_obj.updated_at
            })
        else:
            return Response({
                'success': True,
                'has_draft': False,
                'has_lot_rejection': False,
                'has_tray_rejection': False,
                'lot_rejection_data': {},
                'tray_rejection_data': {}
            })
            
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_all_drafts(request):
    """Get combined draft data for a lot_id (backwards compatibility)"""
    lot_id = request.GET.get('lot_id')
    
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        draft_obj = RecoveryIQF_Draft_Store.objects.filter(
            lot_id=lot_id,
            draft_type='combined_rejection'
        ).first()
        
        response_data = {
            'success': True,
            'lot_rejection_draft': None,
            'tray_rejection_draft': None
        }
        
        if draft_obj and draft_obj.draft_data:
            draft_data = draft_obj.draft_data
            
            # Lot rejection draft data
            if draft_data.get('has_lot_rejection') and draft_data.get('lot_rejection'):
                response_data['lot_rejection_draft'] = {
                    'has_draft': True,
                    'draft_data': {
                        'lot_rejected_comment': draft_data['lot_rejection'].get('lot_rejected_comment', ''),
                        'total_qty': draft_data['lot_rejection'].get('total_qty', 0)
                    },
                    'created_at': draft_obj.created_at,
                    'updated_at': draft_obj.updated_at
                }
            
            # Tray rejection draft data (return all fields)
            if draft_data.get('has_tray_rejection') and draft_data.get('tray_rejection'):
                response_data['tray_rejection_draft'] = {
                    'has_draft': True,
                    'draft_data': {
                        'tray_rejections': draft_data['tray_rejection'].get('tray_rejections', []),
                        'accepted_trays': draft_data['tray_rejection'].get('accepted_trays', []),
                        'acceptance_remarks': draft_data['tray_rejection'].get('acceptance_remarks', ''),
                        'is_draft': draft_data['tray_rejection'].get('is_draft', True)
                    },
                    'created_at': draft_obj.created_at,
                    'updated_at': draft_obj.updated_at
                }
        
        return Response(response_data)
            
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500) 
    
# Update your existing IQFBatchRejectionAPIView to handle lot rejection
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class RecoveryIQFLotRejectionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            batch_id = data.get('batch_id')
            lot_id = data.get('lot_id')
            total_qty = data.get('total_qty', 0)
            lot_rejected_comment = data.get('lot_rejected_comment', '').strip()

            if not batch_id or not lot_id or not lot_rejected_comment:
                return Response({'success': False, 'error': 'Missing required fields including lot rejection comment'}, status=400)

            # Get RecoveryMasterCreation by batch_id string
            mmc = RecoveryMasterCreation.objects.filter(batch_id=batch_id).first()
            if not mmc:
                return Response({'success': False, 'error': 'Batch not found'}, status=404)

            # Get RecoveryStockModel using lot_id (not batch_id)
            total_stock = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if not total_stock:
                return Response({'success': False, 'error': 'RecoveryStockModel not found'}, status=404)

            # Get iqf_physical_qty if set and > 0, else use brass_qc_accepted_qty
            qty = total_stock.iqf_physical_qty if total_stock.iqf_physical_qty and total_stock.iqf_physical_qty > 0 else total_stock.brass_qc_accepted_qty

            # Set iqf_rejection = True
            total_stock.iqf_rejection = True
            # Only set fields that exist in RecoveryStockModel!
            # If you want to store the rejection quantity, make sure iqf_rejection_qty exists in RecoveryStockModel
            # If not, remove it from update_fields
            # total_stock.iqf_rejection_qty = qty  # <-- Only if this field exists!
            total_stock.last_process_module = "Recovery IQF"
            total_stock.next_process_module = "Jig Loading"
            total_stock.iqf_last_process_date_time = timezone.now()
            total_stock.save(update_fields=['iqf_rejection', 'iqf_last_process_date_time','last_process_module', 'next_process_module'])

            # Create RecoveryIQF_Rejection_ReasonStore entry with comment
            RecoveryIQF_Rejection_ReasonStore.objects.create(
                lot_id=lot_id,
                user=request.user,
                total_rejection_quantity=qty,
                batch_rejection=True,
                lot_rejected_comment=lot_rejected_comment
            )

            # Clear any existing drafts for this lot
            RecoveryIQF_Draft_Store.objects.filter(
                lot_id=lot_id,
                draft_type__in=['lot_rejection', 'tray_rejection']
            ).delete()

            return Response({'success': True, 'message': 'Lot rejection saved successfully.'})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class RecoveryIQFTrayRejectionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            batch_id = data.get('batch_id')
            tray_rejections = data.get('tray_rejections', [])  # [{reason_id, quantity}]
            accepted_trays = data.get('accepted_trays', [])    # [{tray_id, qty, sequence}]
            acceptance_remarks = data.get('acceptance_remarks', '').strip()

            if not lot_id or not tray_rejections or not accepted_trays or not acceptance_remarks:
                return Response({'success': False, 'error': 'Missing required fields'}, status=400)

            # 1. Save rejection reasons and qty (no tray_id) in RecoveryIQF_Rejection_ReasonStore
            reason_ids = [item['reason_id'] for item in tray_rejections if int(item['quantity']) > 0]
            reasons = RecoveryIQF_Rejection_Table.objects.filter(rejection_reason_id__in=reason_ids)
            total_qty = sum(int(item['quantity']) for item in tray_rejections if int(item['quantity']) > 0)
            reason_store = RecoveryIQF_Rejection_ReasonStore.objects.create(
                lot_id=lot_id,
                user=request.user,
                total_rejection_quantity=total_qty,
                batch_rejection=False
            )
            reason_store.rejection_reason.set(reasons)

            # 1b. Save individual RecoveryIQF_Rejected_TrayScan records for each reason and quantity
            for item in tray_rejections:
                qty = int(item.get('quantity', 0))
                reason_id = item.get('reason_id')
                if qty > 0 and reason_id:
                    reason_obj = RecoveryIQF_Rejection_Table.objects.filter(rejection_reason_id=reason_id).first()
                    if reason_obj:
                        RecoveryIQF_Rejected_TrayScan.objects.create(
                            lot_id=lot_id,
                            rejected_tray_quantity=str(qty),
                            rejection_reason=reason_obj,
                            user=request.user
                        )

            # 2. Save accepted tray IDs and qty and acceptance remarks in IQF_Accepted_TrayID_Store
            for tray in accepted_trays:
                IQF_Accepted_TrayID_Store.objects.create(
                    lot_id=lot_id,
                    tray_id=tray['tray_id'],
                    tray_qty=tray['qty'],
                    user=request.user,
                    accepted_comment=acceptance_remarks
                )
            
                batch_obj = RecoveryMasterCreation.objects.filter(batch_id=batch_id).first()
            
                # Fetch tray_type and tray_capacity from RecoveryTrayId
                tray_obj = RecoveryTrayId.objects.filter(tray_id=tray['tray_id']).first()
                tray_type = tray_obj.tray_type if tray_obj else None
                tray_capacity = tray_obj.tray_capacity if tray_obj else None
            
                # Create or update RecoveryIQFTrayId
                iqf_tray, created = RecoveryIQFTrayId.objects.get_or_create(
                    tray_id=tray['tray_id'],
                    lot_id=lot_id,
                    defaults={
                        'batch_id': batch_obj,
                        'tray_quantity': tray['qty'],
                        'tray_capacity': tray_capacity,
                        'tray_type': tray_type,
                        'rejected_tray': False,
                    }
                )
                if not created:
                    iqf_tray.lot_id = lot_id
                    iqf_tray.batch_id = batch_obj
                    iqf_tray.tray_quantity = tray['qty']
                    iqf_tray.tray_capacity = tray_capacity
                    iqf_tray.tray_type = tray_type
                    iqf_tray.rejected_tray = False
                    iqf_tray.save(update_fields=['lot_id', 'batch_id', 'tray_quantity', 'tray_capacity', 'tray_type', 'rejected_tray'])
            
                # ✅ Only update RecoveryTrayId, do not create
                if tray_obj:
                    tray_obj.lot_id = lot_id
                    tray_obj.batch_id = batch_obj
                    tray_obj.tray_quantity = tray['qty']
                    tray_obj.tray_capacity = tray_capacity
                    tray_obj.tray_type = tray_type
                    tray_obj.rejected_tray = False
                    tray_obj.save(update_fields=['lot_id', 'batch_id', 'tray_quantity', 'tray_capacity', 'tray_type', 'rejected_tray'])
            # 3. Update RecoveryStockModel fields
            total_stock_obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if total_stock_obj:
                total_stock_obj.iqf_few_cases_acceptance = True
                total_stock_obj.iqf_onhold_picking = True
                total_stock_obj.iqf_last_process_date_time = timezone.now()
                total_stock_obj.iqf_accepted_qty = total_stock_obj.iqf_physical_qty - total_qty
                total_stock_obj.save(update_fields=[
                    'iqf_few_cases_acceptance', 'iqf_onhold_picking', 'iqf_accepted_qty', 'iqf_last_process_date_time'
                    
                ])
                
            new_lot_id = generate_new_lot_id()

            # Create new RecoveryStockModel instance
            new_total_stock = RecoveryStockModel.objects.create(
                lot_id=new_lot_id,
                model_stock_no=total_stock_obj.model_stock_no,
                batch_id=total_stock_obj.batch_id,
                version=total_stock_obj.version,
                total_stock=total_stock_obj.total_stock,
                total_IP_accpeted_quantity=total_stock_obj.iqf_accepted_qty,
                polish_finish=total_stock_obj.polish_finish,
                plating_color=total_stock_obj.plating_color,
                created_at=total_stock_obj.created_at,
                last_process_date_time=total_stock_obj.last_process_date_time,
                send_brass_qc=True,
                tray_scan_status=True,
                ip_person_qty_verified=True,
                accepted_Ip_stock=True,
                last_process_module="Recovery IQF",
                iqf_last_process_date_time=timezone.now()
            )
            # ✅ Fetch accepted trays (rejected_tray=False) for the selected lot_id
            accepted_trays = RecoveryIQFTrayId.objects.filter(lot_id=lot_id, rejected_tray=False)

            # ✅ Create new RecoveryIQFTrayId for each accepted tray, but with new_lot_id
            for tray in accepted_trays:
                RecoveryIQFTrayId.objects.create(
                    tray_id=tray.tray_id,
                    lot_id=new_lot_id,
                    batch_id=tray.batch_id,
                    tray_quantity=tray.tray_quantity,
                    tray_capacity=tray.tray_capacity,
                    tray_type=tray.tray_type,
                    rejected_tray=False,
                    IP_tray_verified=True,
                    new_tray=False
                    # add other fields as needed
                )
            

              
            return Response({'success': True, 'message': 'Tray rejection and acceptance saved.'})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)



@require_GET
def recovery_iqf_reject_check_tray_id(request):
    tray_id = request.GET.get('tray_id', '')
    exists = RecoveryTrayId.objects.filter(tray_id=tray_id).exists()
    return JsonResponse({'exists': exists})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_accepted_tray_scan_data(request):
    lot_id = request.GET.get('lot_id')
    
    
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    try:
        # Get rejection details
        reason_store = RecoveryIQF_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        rejection_details = []
        batch_rejection = False
        lot_rejected_comment = ""
        total_rejection_qty = 0
        if reason_store:
            batch_rejection = reason_store.batch_rejection
            lot_rejected_comment = reason_store.lot_rejected_comment or ""
            total_rejection_qty = reason_store.total_rejection_quantity
            for reason in reason_store.rejection_reason.all():
                rejection_details.append({
                    'reason': reason.rejection_reason,
                    'reason_id': reason.rejection_reason_id,
                    'qty': total_rejection_qty
                })



        # Get model_no and tray_capacity from RecoveryStockModel
        stock = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
        model_no = ""
        tray_capacity = 0
        total_stock = 0
        if stock:
            model_no = stock.model_stock_no.model_no if stock.model_stock_no else ""
            tray_capacity = stock.batch_id.tray_capacity if stock.batch_id and hasattr(stock.batch_id, 'tray_capacity') else 0
            total_stock = stock.iqf_physical_qty if stock.iqf_physical_qty and stock.iqf_physical_qty > 0 else stock.brass_qc_accepted_qty or 0



        return Response({
            'success': True,
            'rejection_details': rejection_details,
            'batch_rejection': batch_rejection,
            'lot_rejected_comment': lot_rejected_comment,
            'total_rejection_qty': total_rejection_qty,
            'model_no': model_no,
            'tray_capacity': tray_capacity,
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_view_tray_list(request):
    """
    Returns tray list for a given lot_id based on different conditions:
    1. If iqf_acceptance is True: get from RecoveryTrayId table
    2. If batch_rejection is True: split total_rejection_quantity by tray_capacity and get tray_ids from RecoveryTrayId
    3. If batch_rejection is False: return all trays from IQF_Accepted_TrayID_Store
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

    try:
        # Check if this lot has iqf_acceptance = True
        stock = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
        iqf_acceptance = False
        tray_capacity = 0
        
        if stock:
            iqf_acceptance = stock.iqf_acceptance or False
            if stock.batch_id and hasattr(stock.batch_id, 'tray_capacity'):
                tray_capacity = stock.batch_id.tray_capacity or 0

        tray_list = []

        # Condition 1: If iqf_acceptance is True, get from RecoveryTrayId table
        if iqf_acceptance:
            trays = RecoveryTrayId.objects.filter(lot_id=lot_id).order_by('id')
            for idx, tray_obj in enumerate(trays):
                tray_list.append({
                    'sno': idx + 1,
                    'tray_id': tray_obj.tray_id,
                    'tray_qty': tray_obj.tray_quantity,  # Assuming this field exists in RecoveryTrayId model
                })
            
            return Response({
                'success': True,
                'iqf_acceptance': True,
                'batch_rejection': False,
                'total_rejection_qty': 0,
                'tray_capacity': tray_capacity,
                'trays': tray_list,
            })

        # Condition 2 & 3: Check rejection reason store (existing logic)
        reason_store = RecoveryIQF_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        batch_rejection = False
        total_rejection_qty = 0
        
        if reason_store:
            batch_rejection = reason_store.batch_rejection
            total_rejection_qty = reason_store.total_rejection_quantity

        if batch_rejection and total_rejection_qty > 0 and tray_capacity > 0:
            # Batch rejection: split total_rejection_qty by tray_capacity, get tray_ids from RecoveryTrayId
            tray_ids = list(RecoveryTrayId.objects.filter(lot_id=lot_id).values_list('tray_id', flat=True))
            num_trays = ceil(total_rejection_qty / tray_capacity)
            qty_left = total_rejection_qty
            
            for i in range(num_trays):
                qty = tray_capacity if qty_left > tray_capacity else qty_left
                tray_id = tray_ids[i] if i < len(tray_ids) else ""
                tray_list.append({
                    'sno': i + 1,
                    'tray_id': tray_id,
                    'tray_qty': qty,
                })
                qty_left -= qty
        else:
            # Not batch rejection: get from IQF_Accepted_TrayID_Store
            trays = IQF_Accepted_TrayID_Store.objects.filter(lot_id=lot_id).order_by('id')
            for idx, obj in enumerate(trays):
                tray_list.append({
                    'sno': idx + 1,
                    'tray_id': obj.tray_id,
                    'tray_qty': obj.tray_qty,
                })

        return Response({
            'success': True,
            'iqf_acceptance': iqf_acceptance,
            'batch_rejection': batch_rejection,
            'total_rejection_qty': total_rejection_qty,
            'tray_capacity': tray_capacity,
            'trays': tray_list,
        })
        
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class RecoveryIQFTrayValidateAPIView(APIView):
    def post(self, request):
        try:
            # Parse request data
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            
            # Get parameters
            lot_id_input = str(data.get('batch_id', '') or data.get('lot_id', '')).strip()
            tray_id = str(data.get('tray_id', '')).strip()
            
            print("="*50)
            print(f"[DEBUG] Raw request data: {data}")
            print(f"[DEBUG] Extracted lot_id: '{lot_id_input}' (length: {len(lot_id_input)})")
            print(f"[DEBUG] Extracted tray_id: '{tray_id}' (length: {len(tray_id)})")
            
            if not lot_id_input or not tray_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Both lot_id and tray_id are required'
                }, status=400)

            # Step 1: Check if lot_id exists in RecoveryMasterCreation (optional validation)
            print(f"[DEBUG] Checking if lot_id exists in RecoveryMasterCreation: '{lot_id_input}'")
            try:
                model_master_creation = RecoveryMasterCreation.objects.get(lot_id=lot_id_input)
                print(f"[DEBUG] Found RecoveryMasterCreation: batch_id='{model_master_creation.batch_id}', lot_id='{model_master_creation.lot_id}'")
            except RecoveryMasterCreation.DoesNotExist:
                print(f"[DEBUG] No RecoveryMasterCreation found with lot_id: '{lot_id_input}'")
                # Continue anyway since we're checking RecoveryTrayId which uses lot_id directly

            # Step 2: Check if the tray exists in RecoveryTrayId for this lot_id
            print(f"[DEBUG] Checking if tray '{tray_id}' exists in RecoveryTrayId for lot_id: '{lot_id_input}'")
            
            tray_exists = RecoveryTrayId.objects.filter(
                lot_id=lot_id_input,  # Use lot_id directly
                tray_id=tray_id
            ).exists()
            
            print(f"[DEBUG] Tray exists in RecoveryTrayId: {tray_exists}")
            
            # Additional debugging: show all trays for this lot_id in RecoveryTrayId
            all_trays = RecoveryTrayId.objects.filter(
                lot_id=lot_id_input
            ).values_list('tray_id', flat=True)
            print(f"[DEBUG] All trays in RecoveryTrayId for lot_id '{lot_id_input}': {list(all_trays)}")
            
            # Also check if tray exists anywhere in RecoveryTrayId (for debugging)
            tray_anywhere = RecoveryTrayId.objects.filter(tray_id=tray_id)
            if tray_anywhere.exists():
                tray_lot_ids = list(tray_anywhere.values_list('lot_id', flat=True))
                print(f"[DEBUG] Tray '{tray_id}' found in RecoveryTrayId for lot_ids: {tray_lot_ids}")
            
            print(f"[DEBUG] Final result - exists: {tray_exists}")
            print("="*50)
            
            return JsonResponse({
                'success': True, 
                'exists': tray_exists,
                'debug_info': {
                    'lot_id_received': lot_id_input,
                    'tray_id_received': tray_id,
                    'all_trays_in_brass_qc_store': list(all_trays),
                    'tray_exists_in_brass_qc_store': tray_exists
                }
            })
            
        except Exception as e:
            print(f"[DEBUG] ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False, 
                'error': str(e)
            }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def IQF_check_accepted_tray_draft(request):
    """Check if draft data exists for accepted tray scan"""
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        has_draft = IQF_Accepted_TrayID_Store.objects.filter(
            lot_id=lot_id, 
            is_draft=True
        ).exists()
        
        return Response({
            'success': True,
            'has_draft': has_draft
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)



@require_GET
def recovery_iqf_check_tray_id(request):
    tray_id = request.GET.get('tray_id', '')
    lot_id = request.GET.get('lot_id', '')  # This is your stock_lot_id

    # 1. Must exist in RecoveryTrayId table and lot_id must match
    tray_obj = RecoveryTrayId.objects.filter(tray_id=tray_id).first()
    exists = bool(tray_obj)
    same_lot = exists and str(tray_obj.lot_id) == str(lot_id)

    # 2. Must NOT be in RecoveryIQF_Rejected_TrayScan for this lot
    already_rejected = False
    if exists and same_lot and lot_id:
        already_rejected = RecoveryIQF_Rejected_TrayScan.objects.filter(
            lot_id=lot_id,
        ).exists()

    # Only valid if exists, same lot, and not already rejected
    is_valid = exists and same_lot and not already_rejected

    return JsonResponse({
        'exists': is_valid,
        'already_rejected': already_rejected,
        'not_in_same_lot': exists and not same_lot
    })


from django.db.models import Sum, F, Func, IntegerField

class Cast(Func):
    function = 'CAST'
    template = '%(expressions)s::integer'
    output_field = IntegerField()

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_rejected_tray_scan_data(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    try:
        rejection_rows = []
        
        # STEP 1: Get ALL unique brass rejection reasons for this lot_id first
        all_brass_reasons = RecoveryBrass_QC_Rejected_TrayScan.objects.filter(
            lot_id=lot_id
        ).values(
            'rejection_reason__rejection_reason_id',
            'rejection_reason__rejection_reason'
        ).distinct()

        # STEP 2: For each brass reason, get brass qty and find corresponding Recovery IQF data
        for brass_reason in all_brass_reasons:
            reason_id = brass_reason['rejection_reason__rejection_reason_id']
            reason_text = brass_reason['rejection_reason__rejection_reason']
            
            # Get brass rejection quantity for this reason
            brass_qty = RecoveryBrass_QC_Rejected_TrayScan.objects.filter(
                lot_id=lot_id,
                rejection_reason__rejection_reason_id=reason_id
            ).aggregate(
                total=Sum(Cast('rejected_tray_quantity', output_field=IntegerField()))
            )['total'] or 0
            
            # Try to find corresponding Recovery IQF data - first check tray-wise rejections
            iqf_qty = 0
            tray_id = ''
            iqf_qty = RecoveryIQF_Rejected_TrayScan.objects.filter(
                lot_id=lot_id,
                rejection_reason__rejection_reason_id=reason_id
            ).aggregate(
                total=Sum(Cast('rejected_tray_quantity', output_field=IntegerField()))
            )['total']
            
            if iqf_qty is None or iqf_qty == 0:
                reason_store = RecoveryIQF_Rejection_ReasonStore.objects.filter(
                    lot_id=lot_id,
                    rejection_reason__rejection_reason_id=reason_id
                ).first()
                if reason_store:
                    iqf_qty = reason_store.total_rejection_quantity or 0
                else:
                    iqf_qty = 0
                    
                    
            # Add to rejection_rows
            rejection_rows.append({
                'tray_id': tray_id,
                'qty': iqf_qty,
                'reason': reason_text,
                'reason_id': reason_id,
                'brass_rejection_qty': brass_qty
            })

        # STEP 3: Handle case where there are no brass rejections but Recovery IQF rejections exist
        if not all_brass_reasons.exists():
            # Fallback to original IQF-first logic if no brass data
            tray_rejections = RecoveryIQF_Rejected_TrayScan.objects.filter(lot_id=lot_id)
            if tray_rejections.exists():
                for obj in tray_rejections:
                    rejection_rows.append({
                        'tray_id': '',
                        'qty': obj.rejected_tray_quantity,
                        'reason': obj.rejection_reason.rejection_reason,
                        'reason_id': obj.rejection_reason.rejection_reason_id,
                        'brass_rejection_qty': 0  # No brass data
                    })
            else:
                # Check RecoveryIQF_Rejection_ReasonStore
                reason_store = RecoveryIQF_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
                if reason_store:
                    total_qty = reason_store.total_rejection_quantity
                    for reason in reason_store.rejection_reason.all():
                        rejection_rows.append({
                            'tray_id': '',
                            'qty': total_qty,
                            'reason': reason.rejection_reason,
                            'reason_id': reason.rejection_reason_id,
                            'brass_rejection_qty': 0  # No brass data
                        })

        # Accepted trays (unchanged)
        accepted_trays = []
        for obj in IQF_Accepted_TrayID_Store.objects.filter(lot_id=lot_id):
            accepted_trays.append({
                'tray_id': obj.tray_id,
                'tray_qty': obj.tray_qty,
                'accepted_comment': obj.accepted_comment,
                'is_draft': obj.is_draft,
                'is_save': obj.is_save,
                'user': obj.user.username if obj.user else None,
            })

        print(f"[iqf_get_rejected_tray_scan_data] lot_id={lot_id}")
        print(f"  rejection_rows: {rejection_rows}")
        print(f"  accepted_trays: {accepted_trays}")

        return Response({
            'success': True,
            'rejection_rows': rejection_rows,
            'accepted_trays': accepted_trays
        })
    except Exception as e:
        print(f"[iqf_get_rejected_tray_scan_data] ERROR: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class RecoveryIQFDeleteBatchAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            stock_lot_id = data.get('stock_lot_id')
            if not stock_lot_id:
                return JsonResponse({'success': False, 'error': 'Missing stock_lot_id'}, status=400)
            obj = RecoveryStockModel.objects.filter(lot_id=stock_lot_id).first()
            if not obj:
                return JsonResponse({'success': False, 'error': 'Stock lot not found'}, status=404)
            obj.delete()
            return JsonResponse({'success': True, 'message': 'Stock lot deleted'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class RecoveryIQFCompletedTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Recovery_IQF/Recovery_Iqf_Completed.html'

    def get(self, request):
        from django.utils import timezone
        from datetime import datetime, timedelta
        import pytz
        import math

        user = request.user
        
        # ✅ Date filtering logic (unchanged)
        tz = pytz.timezone("Asia/Kolkata")
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

        # ✅ CHANGED: Query RecoveryStockModel directly instead of RecoveryMasterCreation
        iqf_rejection_reasons = RecoveryIQF_Rejection_Table.objects.all()
        
        # ✅ External data subqueries (only for data from other tables)
        brass_rejection_qty_subquery = RecoveryBrass_QC_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        iqf_rejection_qty_subquery = RecoveryIQF_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = RecoveryStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            batch_id__total_batch_quantity__gt=0,
            iqf_last_process_date_time__range=(from_datetime, to_datetime)  # ✅ Direct date filtering
        ).annotate(
            wiping_required=F('batch_id__model_stock_no__wiping_required'),
            brass_rejection_total_qty=brass_rejection_qty_subquery,
            iqf_rejection_qty=iqf_rejection_qty_subquery,
        ).filter(
            # ✅ Direct filtering on RecoveryStockModel fields (no more subquery filtering)
            Q(iqf_acceptance=True) |
            Q(iqf_rejection=True) |
            (Q(iqf_few_cases_acceptance=True) & Q(iqf_onhold_picking=False))
        ).order_by('-iqf_last_process_date_time', '-lot_id')

        print(f"📊 Found {queryset.count()} Recovery IQF completed records in date range {from_date} to {to_date}")
        print("All lot_ids in Recovery IQF completed queryset:", list(queryset.values_list('lot_id', flat=True)))

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        # ✅ UPDATED: Build master_data from RecoveryStockModel records
        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            
            data = {
                # ✅ Batch fields from foreign key
                'batch_id': batch.batch_id,
                'date_time': batch.date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no,
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'Moved_to_D_Picker': batch.Moved_to_D_Picker,
                'Draft_Saved': batch.Draft_Saved,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                
                # ✅ Stock-related fields from RecoveryStockModel
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
                'brass_accepted_tray_scan_status': stock_obj.brass_accepted_tray_scan_status,
                'brass_qc_rejection': stock_obj.brass_qc_rejection,
                'brass_rejection_total_qty': stock_obj.brass_rejection_total_qty,
                'brass_qc_few_cases_accptance': stock_obj.brass_qc_few_cases_accptance,
                'iqf_accepted_qty_verified': stock_obj.iqf_accepted_qty_verified,
                'iqf_acceptance': stock_obj.iqf_acceptance,  # ✅ Direct access - will show True correctly
                'iqf_rejection': stock_obj.iqf_rejection,
                'iqf_few_cases_acceptance': stock_obj.iqf_few_cases_acceptance,
                'iqf_onhold_picking': stock_obj.iqf_onhold_picking,
                'iqf_accepted_tray_scan_status': stock_obj.iqf_accepted_tray_scan_status,
                'iqf_last_process_date_time': stock_obj.iqf_last_process_date_time,
                'total_IP_accpeted_quantity': stock_obj.total_IP_accpeted_quantity,
            }
            master_data.append(data)

        print(f"[IQFCompletedTableView] Total master_data records: {len(master_data)}")
        
        # ✅ Process the data with fallback to total_IP_accpeted_quantity
        for data in master_data:
            brass_rejection_total_qty = data.get('brass_rejection_total_qty')
            total_ip_accepted_qty = data.get('total_IP_accpeted_quantity', 0)
            tray_capacity = data.get('tray_capacity')
            
            # ✅ UPDATED: Use total_IP_accpeted_quantity as fallback when brass_rejection_total_qty is None
            if brass_rejection_total_qty is None:
                effective_qty = total_ip_accepted_qty
                print(f"Lot {data['lot_id']}: Using total_IP_accpeted_quantity ({total_ip_accepted_qty}) as fallback")
            else:
                effective_qty = brass_rejection_total_qty
                print(f"Lot {data['lot_id']}: Using brass_rejection_total_qty ({brass_rejection_total_qty})")
            
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            
            # Calculate no_of_trays using effective_qty
            if effective_qty is None or tray_capacity is None or tray_capacity == 0:
                data['no_of_trays'] = 0
            else:
                data['no_of_trays'] = math.ceil(effective_qty / tray_capacity)
            
            # ✅ Store the effective quantity for display purposes
            data['display_quantity'] = effective_qty
            data['quantity_source'] = 'total_IP_accpeted_quantity' if brass_rejection_total_qty is None else 'brass_rejection_total_qty'

            # Get model images
            batch_obj = RecoveryMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj:
                model_master = batch_obj.model_stock_no
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            # ✅ UPDATED: Add available_qty logic with fallback
            lot_id = data.get('stock_lot_id')
            total_stock_obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if total_stock_obj:
                if total_stock_obj.iqf_physical_qty and total_stock_obj.iqf_physical_qty > 0:
                    data['available_qty'] = total_stock_obj.iqf_physical_qty
                else:
                    # Use effective_qty (either brass_rejection_total_qty or total_IP_accpeted_quantity)
                    data['available_qty'] = effective_qty or 0
            else:
                data['available_qty'] = 0

        print("Processed lot_ids:", [data['stock_lot_id'] for data in master_data])

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
            'iqf_rejection_reasons': iqf_rejection_reasons,
            'from_date': from_date.strftime('%Y-%m-%d'),
            'to_date': to_date.strftime('%Y-%m-%d'),
            'date_filter_applied': bool(from_date_str and to_date_str),
        }
        return Response(context, template_name=self.template_name)


class RecoveryIQFRejectTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Recovery_IQF/Recovery_Iqf_RejectTable.html'

    def get(self, request):
        user = request.user
        
        iqf_rejection_total_qty_subquery = RecoveryIQF_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]
        
        brass_rejection_total_qty_subquery = RecoveryBrass_QC_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = RecoveryStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            batch_id__total_batch_quantity__gt=0
        ).annotate(
            iqf_rejection_total_qty=iqf_rejection_total_qty_subquery,
            brass_rejection_total_qty=brass_rejection_total_qty_subquery
        ).filter(
            Q(iqf_rejection=True) |
            Q(iqf_few_cases_acceptance=True)
        ).order_by('-iqf_last_process_date_time', '-lot_id')

        print(f"📊 Found {queryset.count()} Recovery IQF rejected records")
        print("All lot_ids in Recovery IQF reject queryset:", list(queryset.values_list('lot_id', flat=True)))

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            
            data = {
                'batch_id': batch.batch_id,
                'date_time': batch.date_time,
                'model_stock_no__model_no': batch.model_stock_no.model_no,
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'Moved_to_D_Picker': batch.Moved_to_D_Picker,
                'Draft_Saved': batch.Draft_Saved,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'lot_id': stock_obj.lot_id,
                'stock_lot_id': stock_obj.lot_id,
                'last_process_module': stock_obj.last_process_module,
                'next_process_module': stock_obj.next_process_module,
                'iqf_accepted_qty_verified': stock_obj.iqf_accepted_qty_verified,
                'iqf_rejection': stock_obj.iqf_rejection,
                'iqf_few_cases_acceptance': stock_obj.iqf_few_cases_acceptance,
                'iqf_rejection_total_qty': stock_obj.iqf_rejection_total_qty,
                'iqf_last_process_date_time': stock_obj.iqf_last_process_date_time,
                'brass_rejection_total_qty': stock_obj.brass_rejection_total_qty,
                'iqf_physical_qty': stock_obj.iqf_physical_qty,
                'iqf_missing_qty': stock_obj.iqf_missing_qty
            }

            # --- Add lot rejection remarks ---
            stock_lot_id = data.get('stock_lot_id')
            lot_rejected_comment = ""
            if stock_lot_id:
                reason_store = RecoveryIQF_Rejection_ReasonStore.objects.filter(lot_id=stock_lot_id).first()
                if reason_store:
                    lot_rejected_comment = reason_store.lot_rejected_comment or ""
            data['lot_rejected_comment'] = lot_rejected_comment
            # --- End lot rejection remarks ---

            # Existing logic for tray_id_in_trayid, rejection_reason_letters, etc.
            tray_exists = RecoveryIQFTrayId.objects.filter(lot_id=stock_lot_id, delink_tray=False).exists()
            data['tray_id_in_trayid'] = tray_exists

            first_letters = []
            data['batch_rejection'] = False

            if stock_lot_id:
                try:
                    rejection_record = RecoveryIQF_Rejection_ReasonStore.objects.filter(
                        lot_id=stock_lot_id
                    ).first()
                    if rejection_record:
                        data['batch_rejection'] = rejection_record.batch_rejection
                        data['iqf_rejection_total_qty'] = rejection_record.total_rejection_quantity
                        reasons = rejection_record.rejection_reason.all()
                        first_letters = [r.rejection_reason.strip()[0].upper() for r in reasons if r.rejection_reason]
                        print(f"✅ Found rejection for {stock_lot_id}: {rejection_record.total_rejection_quantity}")
                    else:
                        if 'iqf_rejection_total_qty' not in data or not data['iqf_rejection_total_qty']:
                            data['iqf_rejection_total_qty'] = 0
                        print(f"⚠️ No rejection record found for {stock_lot_id}")
                except Exception as e:
                    print(f"❌ Error getting rejection for {stock_lot_id}: {str(e)}")
                    data['iqf_rejection_total_qty'] = data.get('iqf_rejection_total_qty', 0)
            else:
                data['iqf_rejection_total_qty'] = 0
                print(f"❌ No stock_lot_id for batch {data.get('batch_id')}")

            data['rejection_reason_letters'] = first_letters

            # Calculate number of trays
            total_stock = data.get('iqf_rejection_total_qty', 0)
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"

            if tray_capacity > 0 and total_stock > 0:
                data['no_of_trays'] = math.ceil(total_stock / tray_capacity)
            else:
                data['no_of_trays'] = 0

            # Get model images
            batch_obj = RecoveryMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj:
                model_master = batch_obj.model_stock_no
                for img in model_master.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            master_data.append(data)

        print("✅ Recovery IQF Reject data processing completed")
        print("Processed lot_ids:", [data['stock_lot_id'] for data in master_data])
            
        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
        }
        return Response(context, template_name=self.template_name)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_rejection_details(request):
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    try:
        reason_store = RecoveryIQF_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
        if not reason_store:
            return Response({'success': True, 'reasons': []})

        reasons = reason_store.rejection_reason.all()
        total_qty = reason_store.total_rejection_quantity

        if reason_store.batch_rejection:
            if reasons.exists():
                data = [{
                    'reason': r.rejection_reason,
                    'qty': total_qty
                } for r in reasons]
            else:
                # No reasons recorded for batch rejection
                data = [{
                    'reason': 'Batch rejection: No individual reasons recorded',
                    'qty': total_qty
                }]
        else:
            data = [{
                'reason': r.rejection_reason,
                'qty': total_qty
            } for r in reasons]

        return Response({'success': True, 'reasons': data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'success': False, 'error': str(e)}, status=500)
    
@require_GET
def recovery_iqf_reject_check_tray_id_simple(request):
    tray_id = request.GET.get('tray_id', '').strip()
    lot_id = request.GET.get('lot_id', '').strip()
    tray_qty = int(request.GET.get('tray_qty', 0))  # Pass tray_qty from frontend

    # ✅ STEP 1: Check "Available (can rearrange)" from RecoveryIQFTrayId table ONLY
    # Get all tray quantities for this lot from RecoveryIQFTrayId
    iqf_tray_quantities = list(RecoveryIQFTrayId.objects.filter(lot_id=lot_id).values_list('tray_quantity', flat=True))
    print(f"[DEBUG] lot_id={lot_id}, scanned tray_qty={tray_qty}, Recovery IQF tray_quantities={iqf_tray_quantities}")

    # Check if this tray exists in RecoveryIQFTrayId with same lot
    iqf_tray_obj = RecoveryIQFTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).first()
    
    if iqf_tray_obj and tray_qty in iqf_tray_quantities:
        # This is an existing tray from RecoveryIQFTrayId - check rearrangement possibility
        try:
            # Get tray capacity dynamically from RecoveryIQFTrayId table based on lot_id
            tray_capacity_obj = RecoveryIQFTrayId.objects.filter(lot_id=lot_id).first()
            if tray_capacity_obj and hasattr(tray_capacity_obj, 'tray_capacity'):
                tray_capacity = tray_capacity_obj.tray_capacity
            else:
                print(f"[DEBUG] No tray_capacity found for lot_id: {lot_id}")
                tray_capacity = 12  # fallback value
            
            print(f"[DEBUG] Using tray_capacity: {tray_capacity} for lot_id: {lot_id}")
            
            # Calculate total current items across all Recovery IQF trays
            total_current_items = sum(iqf_tray_quantities)
            
            # If we use one tray for the scanned quantity (tray_qty),
            # the remaining items need to fit in the remaining trays
            remaining_items = total_current_items - tray_qty
            remaining_trays_count = len(iqf_tray_quantities) - 1
            remaining_trays_capacity = remaining_trays_count * tray_capacity
            
            print(f"[DEBUG] Rearrangement check: remaining_items={remaining_items}, remaining_trays_capacity={remaining_trays_capacity}")
            
            # Check if remaining items can fit in remaining trays
            if remaining_items <= remaining_trays_capacity:
                return JsonResponse({
                    'exists': True,
                    'valid_for_rejection': True,
                    'status_message': 'Available (can rearrange)'
                })
            else:
                return JsonResponse({
                    'exists': False,
                    'valid_for_rejection': False,
                    'status_message': 'Cannot rearrange - insufficient capacity'
                })
                
        except Exception as e:
            print(f"[DEBUG] Error in rearrangement calculation: {e}")
            # Fallback to original logic if calculation fails
            return JsonResponse({
                'exists': True,
                'valid_for_rejection': True,
                'status_message': 'Available (can rearrange)'
            })

    # ✅ STEP 2: Check other cases from RecoveryTrayId table ONLY
    # Check if tray exists in RecoveryTrayId table
    tray_obj = RecoveryTrayId.objects.filter(tray_id=tray_id).first()
    
    if not tray_obj:
        # Tray doesn't exist in RecoveryTrayId table at all
        return JsonResponse({
            'exists': False,
            'valid_for_rejection': False,
            'status_message': 'Invalid Barcode'
        })
    
    # Check if tray belongs to a different lot (not empty and not current lot)
    if (tray_obj.lot_id and 
        str(tray_obj.lot_id).strip() != '' and 
        str(tray_obj.lot_id).strip() != lot_id):
        return JsonResponse({
            'exists': False,
            'valid_for_rejection': False,
            'status_message': 'Different Lot'
        })
    
    # If it's a new tray (no lot_id assigned), check tray type first
    if not tray_obj.lot_id or str(tray_obj.lot_id).strip() == '':
        # Get the expected tray type for the selected lot
        try:
            selected_lot_obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if selected_lot_obj and hasattr(selected_lot_obj, 'batch_id'):
                expected_tray_type = getattr(selected_lot_obj.batch_id, 'tray_type', None)
                
                # Check if tray_obj has tray_type and if it matches
                if (hasattr(tray_obj, 'tray_type') and 
                    tray_obj.tray_type and 
                    expected_tray_type and 
                    tray_obj.tray_type != expected_tray_type):
                    return JsonResponse({
                        'exists': False,
                        'valid_for_rejection': False,
                        'status_message': 'Wrong tray Type'
                    })
        except Exception as e:
            print(f"[DEBUG] Error checking tray type: {e}")
            # Continue with normal flow if tray type check fails
        
        # If tray type is correct or no tray type validation needed, allow new tray
        return JsonResponse({
            'exists': True,
            'valid_for_rejection': True,
            'status_message': 'New Tray Available'
        })
    
    # Default case - tray exists but doesn't meet other criteria
    return JsonResponse({
        'exists': False,
        'valid_for_rejection': False,
        'status_message': 'Tray not allowed for rejection'
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_delink_candidates(request):
    """
    Calculate delink candidates based on new vs existing tray usage logic.
    
    Logic:
    1. Get all initial Recovery IQF trays (existing trays: new_tray=False, IP_tray_verified=True)
    2. Get accepted trays used (both new and existing)
    3. Remove existing tray usage completely
    4. Subtract new tray usage quantities from remaining trays
    5. Trays that become qty=0 are delink candidates
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 1. Get all initial Recovery IQF trays (existing trays after IP verification)
        initial_trays = list(
            RecoveryIQFTrayId.objects.filter(
                lot_id=lot_id,
                new_tray=False,
                IP_tray_verified=True
            ).order_by('id').values('tray_id', 'tray_quantity', 'id')
        )
        
        # 2. Get all accepted trays (rejected_tray=False)
        accepted_trays = list(
            RecoveryIQFTrayId.objects.filter(
                lot_id=lot_id,
                rejected_tray=False
            ).values('tray_id', 'tray_quantity', 'new_tray', 'IP_tray_verified')
        )
        
        # 3. Separate new trays vs existing trays used in acceptance
        new_trays_used = []
        existing_trays_used = []
        
        for tray in accepted_trays:
            if tray['new_tray'] and not tray['IP_tray_verified']:
                # New tray
                new_trays_used.append({
                    'tray_id': tray['tray_id'],
                    'quantity': tray['tray_quantity']
                })
            elif not tray['new_tray'] and tray['IP_tray_verified']:
                # Existing tray
                existing_trays_used.append({
                    'tray_id': tray['tray_id'],
                    'quantity': tray['tray_quantity']
                })
        
        # 4. Process delink logic
        delink_candidates = []
        remaining_trays = initial_trays.copy()
        
        # Step 1: Remove existing tray usage completely
        for existing_usage in existing_trays_used:
            for i, tray in enumerate(remaining_trays):
                if tray['tray_id'] == existing_usage['tray_id']:
                    remaining_trays.pop(i)
                    break
        
        # Step 2: Subtract new tray usage quantities
        new_usage_quantities = [usage['quantity'] for usage in new_trays_used]
        
        for i, new_qty in enumerate(new_usage_quantities):
            if i < len(remaining_trays):
                original_qty = remaining_trays[i]['tray_quantity']
                new_remaining_qty = max(0, original_qty - new_qty)
                
                # If tray becomes 0, it's a delink candidate
                if new_remaining_qty == 0 and original_qty > 0:
                    delink_candidates.append({
                        'tray_id': remaining_trays[i]['tray_id'],
                        'original_quantity': original_qty,
                        'subtracted_quantity': new_qty
                    })
                
                # Update the remaining quantity
                remaining_trays[i]['tray_quantity'] = new_remaining_qty
        
        # 5. Check if any new trays were actually used
        new_tray_used = len(new_trays_used) > 0
        
        return Response({
            'success': True,
            'delink_candidates': delink_candidates if new_tray_used else [],
            'new_tray_used': new_tray_used,
            'debug': {
                'initial_trays': initial_trays,
                'new_trays_used': new_trays_used,
                'existing_trays_used': existing_trays_used,
                'remaining_after_processing': remaining_trays,
                'delink_candidates': delink_candidates
            }
        })
        
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_rejected_trays(request):
    """
    Get remaining rejected trays after processing delink logic.
    Returns trays with remaining quantities > 0 after new tray usage subtraction.
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 1. Get all initial Recovery IQF trays (existing trays after IP verification)
        initial_trays = list(
            RecoveryIQFTrayId.objects.filter(
                lot_id=lot_id,
                new_tray=False,
                IP_tray_verified=True
            ).order_by('id').values('tray_id', 'tray_quantity')
        )
        
        # 2. Get accepted trays to calculate usage
        accepted_trays = list(
            RecoveryIQFTrayId.objects.filter(
                lot_id=lot_id,
                rejected_tray=False
            ).values('tray_id', 'tray_quantity', 'new_tray', 'IP_tray_verified')
        )
        
        # 3. Separate usage types
        new_trays_used = []
        existing_trays_used = []
        
        for tray in accepted_trays:
            if tray['new_tray'] and not tray['IP_tray_verified']:
                new_trays_used.append(tray['tray_quantity'])
            elif not tray['new_tray'] and tray['IP_tray_verified']:
                existing_trays_used.append(tray['tray_id'])
        
        # 4. Process remaining trays
        remaining_trays = initial_trays.copy()
        
        # Remove existing tray usage
        for existing_tray_id in existing_trays_used:
            remaining_trays = [t for t in remaining_trays if t['tray_id'] != existing_tray_id]
        
        # Subtract new tray usage quantities
        rejected_trays = []
        for i, new_qty in enumerate(new_trays_used):
            if i < len(remaining_trays):
                original_qty = remaining_trays[i]['tray_quantity']
                final_qty = max(0, original_qty - new_qty)
                
                if final_qty > 0:
                    rejected_trays.append({
                        'tray_id': remaining_trays[i]['tray_id'],
                        'tray_quantity': final_qty
                    })
        
        # Add any remaining trays that weren't affected
        for i in range(len(new_trays_used), len(remaining_trays)):
            rejected_trays.append({
                'tray_id': remaining_trays[i]['tray_id'],
                'tray_quantity': remaining_trays[i]['tray_quantity']
            })
        
        return Response({
            'success': True,
            'rejected_trays': rejected_trays,
            'count': len(rejected_trays),
            'debug': {
                'initial_trays_count': len(initial_trays),
                'new_trays_used': new_trays_used,
                'existing_trays_removed': len(existing_trays_used),
                'final_rejected_count': len(rejected_trays)
            }
        })
        
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_get_remaining_trays(request):
    """
    Get remaining trays and determine delink needs with correct new/existing identification
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 1. Get all initial Recovery IQF tray IDs for this lot (original trays after IP verification)
        iqf_trays = RecoveryIQFTrayId.objects.filter(
            lot_id=lot_id,
            new_tray=False,  # Original trays after IP verification
            IP_tray_verified=True
            # Removed rejected_tray=True filter to include all original trays
        ).order_by('id')
        
        # Get total rejection quantity from RecoveryBrass_QC_Rejection_ReasonStore table
        stock = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
        if not stock:
            return Response({'success': False, 'error': 'Stock not found'}, status=400)
            
        # Sum total_rejection_quantity from RecoveryBrass_QC_Rejection_ReasonStore for this lot
        brass_rejection_records = RecoveryBrass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id)
        brass_total_rejected_qty = sum([record.total_rejection_quantity or 0 for record in brass_rejection_records])
        
        tray_capacity = stock.batch_id.tray_capacity if stock.batch_id and hasattr(stock.batch_id, 'tray_capacity') else 12
        
        # Calculate initial quantities based on brass_total_rejected_qty distributed across trays
        initial_iqf_trays = {}
        remaining_qty = brass_total_rejected_qty
        
        for tray in iqf_trays:
            if remaining_qty > 0:
                tray_qty = min(remaining_qty, tray_capacity)
                initial_iqf_trays[tray.tray_id] = tray_qty
                remaining_qty -= tray_qty
            else:
                initial_iqf_trays[tray.tray_id] = 0

        print(f"[DEBUG] Recovery Brass rejection records count: {len(brass_rejection_records)}")
        print(f"[DEBUG] Recovery Brass total rejected qty (from RecoveryBrass_QC_Rejection_ReasonStore): {brass_total_rejected_qty}")
        print(f"[DEBUG] Tray capacity: {tray_capacity}")
        print(f"[DEBUG] Initial Recovery IQF trays (calculated): {initial_iqf_trays}")

        # 2. Apply missing quantities to get current physical quantities
        missing_qty = stock.iqf_missing_qty if stock.iqf_missing_qty else 0
        
        # Subtract missing quantity from initial trays (in order)
        current_physical_trays = {}
        remaining_missing = missing_qty
        for tray_id, initial_qty in initial_iqf_trays.items():
            if remaining_missing > 0:
                deduction = min(remaining_missing, initial_qty)
                current_physical_trays[tray_id] = initial_qty - deduction
                remaining_missing -= deduction
            else:
                current_physical_trays[tray_id] = initial_qty

        print(f"[DEBUG] After applying missing qty ({missing_qty}): {current_physical_trays}")

        # 3. Get accepted trays (rejected_tray=False) and separate by type
        accepted_trays = RecoveryIQFTrayId.objects.filter(
            lot_id=lot_id, 
            rejected_tray=False
        )
        
        new_trays_used = []
        existing_trays_used = []
        
        for tray in accepted_trays:
            tray_info = {
                'tray_id': tray.tray_id,
                'qty': tray.tray_quantity
            }
            
            # Check if this tray was in the initial trays (existing) or is new
            if tray.tray_id in initial_iqf_trays:
                existing_trays_used.append(tray_info)
            else:
                new_trays_used.append(tray_info)

        print(f"[DEBUG] New trays used: {new_trays_used}")
        print(f"[DEBUG] Existing trays used: {existing_trays_used}")

        # 4. Apply delink logic using current physical quantities
        remaining_trays = []
        delink_candidates = []
        
        # Start with current physical trays
        working_trays = list(current_physical_trays.items())  # [(tray_id, physical_qty), ...]
        
        # Calculate shortage from existing tray usage
        total_shortage = 0
        for existing_usage in existing_trays_used:
            tray_id = existing_usage['tray_id']
            required_qty = existing_usage['qty']
            available_qty = current_physical_trays.get(tray_id, 0)
            
            if required_qty > available_qty:
                shortage = required_qty - available_qty
                total_shortage += shortage
                print(f"[DEBUG] Shortage for {tray_id}: required {required_qty}, available {available_qty}, shortage {shortage}")
            
            # Remove this tray from working_trays (it's been used)
            working_trays = [(tid, qty) for tid, qty in working_trays if tid != tray_id]
        
        print(f"[DEBUG] Total shortage from existing usage: {total_shortage}")
        print(f"[DEBUG] After removing existing usage: {working_trays}")
        
        # Calculate total new tray quantities used
        new_tray_total = sum(tray['qty'] for tray in new_trays_used)
        
        # Total quantity to subtract = shortage + new tray usage
        total_to_subtract = total_shortage + new_tray_total
        
        print(f"[DEBUG] New tray total: {new_tray_total}, Total to subtract: {total_to_subtract}")
        
        # Subtract total quantity from remaining trays in order
        post_subtract = []
        remaining_to_subtract = total_to_subtract
        
        for tray_id, physical_qty in working_trays:
            if remaining_to_subtract > 0:
                subtract_qty = min(remaining_to_subtract, physical_qty)
                remaining_qty = physical_qty - subtract_qty
                remaining_to_subtract -= subtract_qty
            else:
                subtract_qty = 0
                remaining_qty = physical_qty
            
            post_subtract.append({
                'tray_id': tray_id,
                'initial_qty': initial_iqf_trays[tray_id],
                'physical_qty': physical_qty,
                'used_qty': subtract_qty,
                'remaining_qty': remaining_qty,
            })
        
        # Get tray capacity for combining leftovers (already retrieved above)
        # tray_capacity already available from earlier calculation
        
        # Combine leftovers if sum <= tray_capacity
        leftovers = [t for t in post_subtract if t['remaining_qty'] > 0]
        
        if len(leftovers) > 1 and tray_capacity > 0:
            # Sort by remaining_qty ascending
            leftovers_sorted = sorted(leftovers, key=lambda t: t['remaining_qty'])
            combined = []
            combined_sum = 0
            for t in leftovers_sorted:
                if combined_sum + t['remaining_qty'] <= tray_capacity:
                    combined_sum += t['remaining_qty']
                    combined.append(t)
                else:
                    break
            
            if len(combined) > 1:
                # Find indexes in post_subtract
                combined_indexes = [post_subtract.index(t) for t in combined]
                post_subtract[combined_indexes[0]]['remaining_qty'] = combined_sum
                for idx in combined_indexes[1:]:
                    post_subtract[idx]['remaining_qty'] = 0
        
        # Build remaining_trays and delink_candidates
        remaining_trays = []
        delink_candidates = []
        
        for t in post_subtract:
            # A tray is a delink candidate if it has 0 remaining but had some physical quantity
            is_delink = t['remaining_qty'] == 0 and t['physical_qty'] > 0
            
            remaining_trays.append({
                'tray_id': t['tray_id'],
                'initial_qty': t['initial_qty'],
                'physical_qty': t['physical_qty'],
                'used_qty': t['used_qty'],
                'remaining_qty': t['remaining_qty'],
                'is_delink_candidate': is_delink,
                'used_new_tray': is_delink
            })
            
            if is_delink:
                delink_candidates.append({
                    'tray_id': t['tray_id'],
                    'original_qty': t['initial_qty'],
                    'physical_qty': t['physical_qty'],
                    'subtracted_qty': t['used_qty']
                })

        print(f"[DEBUG] Final remaining trays: {remaining_trays}")
        print(f"[DEBUG] Delink candidates: {delink_candidates}")

        # Need delink if there are any delink candidates or if new trays were used
        needs_delink = len(delink_candidates) > 0 or len(new_trays_used) > 0
        
        return Response({
            'success': True,
            'remaining_trays': remaining_trays,
            'delink_candidates': delink_candidates,
            'new_trays_used': new_trays_used,
            'existing_trays_used': existing_trays_used,
            'needs_delink': needs_delink,
            'debug_info': {
                'brass_total_rejected_qty_source': 'RecoveryBrass_QC_Rejection_ReasonStore',
                'brass_rejection_records_count': len(brass_rejection_records),
                'brass_total_rejected_qty': brass_total_rejected_qty,
                'tray_capacity': tray_capacity,
                'initial_trays': initial_iqf_trays,
                'physical_trays': current_physical_trays,
                'missing_qty': missing_qty,
                'total_shortage': total_shortage,
                'new_trays_count': len(new_trays_used),
                'existing_trays_count': len(existing_trays_used),
                'delink_candidates_count': len(delink_candidates)
            }
        })
        
    except Exception as e:
        print(f"[DEBUG] Error in iqf_get_remaining_trays: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_iqf_validate_delink_tray(request):
    """
    Allow ANY rejected tray from same lot to be delinked,
    but do NOT allow duplicate tray_id in delink or rejection lists.
    """
    tray_id = request.GET.get('tray_id', '').strip()
    lot_id = request.GET.get('lot_id', '').strip()
    
    if not tray_id or not lot_id:
        return Response({'success': False, 'error': 'Missing tray_id or lot_id'}, status=400)
    
    try:
        # Check if tray is a rejected tray for this lot
        rejected_tray_exists = RecoveryIQFTrayId.objects.filter(
            lot_id=lot_id,
            tray_id=tray_id,
            rejected_tray=True
        ).exists()

        # Check if tray is already delinked (delink_tray=True)
        already_delinked = RecoveryIQFTrayId.objects.filter(
            tray_id=tray_id,
            delink_tray=True
        ).exists()

        # Check if tray is already used in any other delink or rejection row for this lot
        # (You may want to check other tables if needed)
        duplicate_in_lot = RecoveryIQFTrayId.objects.filter(
            lot_id=lot_id,
            tray_id=tray_id
        ).exclude(rejected_tray=True).exists()

        if already_delinked:
            return Response({
                'success': False,
                'is_valid': False,
                'error': f'Tray {tray_id} is already delinked'
            })

        if duplicate_in_lot:
            return Response({
                'success': False,
                'is_valid': False,
                'error': f'Tray {tray_id} is already used in this lot'
            })

        if rejected_tray_exists:
            return Response({
                'success': True,
                'is_valid': True,
                'tray_id': tray_id,
                'lot_id': lot_id,
                'message': 'Valid rejected tray for delink'
            })
        else:
            return Response({
                'success': True,
                'is_valid': False,
                'error': f'Tray {tray_id} is not a rejected tray for this lot'
            })
        
    except Exception as e:
        return Response({'success': False, 'error': str(e), 'is_valid': False}, status=500)     



@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recovery_iqf_save_draft_tray_ids(request):
    """
    Save draft tray IDs and quantities in RecoveryIQF_Draft_Store as draft_type='tray_id_draft'.
    """
    try:
        data = request.data
        lot_id = data.get('lot_id')
        trays = data.get('trays', [])
        user = request.user

        if not lot_id or not trays:
            return Response({'success': False, 'error': 'Missing lot_id or trays'}, status=400)

        # Use batch_id if provided, else empty string
        batch_id = data.get('batch_id', '')

        # Prepare draft_data as JSON
        draft_data = {
            'trays': trays
        }

        # Save or update the draft (unique on lot_id, draft_type, user)
        draft_type = 'tray_id_draft'
        obj, created = RecoveryIQF_Draft_Store.objects.update_or_create(
            lot_id=lot_id,
            draft_type=draft_type,
            user=user,
            defaults={
                'batch_id': batch_id,
                'draft_data': draft_data
            }
        )

        return Response({'success': True, 'message': 'Draft trays saved.'})
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recovery_iqf_process_all_tray_data(request):
    """Process all tray data: delink, verification, and rejection top trays"""
    try:
        data = request.data
        lot_id = data.get('lot_id')
        delink_trays = data.get('delink_trays', [])
        verifications = data.get('verifications', [])
        rejection_top_trays = data.get('rejection_top_trays', [])
        is_draft = data.get('is_draft', False)
        
        if not lot_id:
            return Response({
                'success': False, 
                'error': 'Missing lot_id'
            }, status=400)
        
        results = {
            'processed_delinks': 0,
            'processed_verifications': 0,
            'processed_rejections': 0,
            'errors': []
        }
        
        # ✅ Process delink trays
        for tray_id in delink_trays:
            try:
                tray_obj = RecoveryIQFTrayId.objects.filter(lot_id=lot_id, tray_id=tray_id).first()
                if tray_obj:
                    # Update all delink fields
                    tray_obj.lot_id = None
                    tray_obj.delink_tray = True
                    tray_obj.new_tray = False
                    tray_obj.batch_id = None
                    tray_obj.tray_quantity = 0
                    tray_obj.IP_tray_verified = False
                    tray_obj.rejected_tray = False
                    tray_obj.iqf_reject_verify = False
                    tray_obj.top_tray = False
                    
                    tray_obj.save(update_fields=[
                        'lot_id', 'delink_tray', 'new_tray', 'batch_id', 'tray_quantity',
                        'IP_tray_verified', 'rejected_tray', 'iqf_reject_verify', 'top_tray'
                    ])
                    
                    RecoveryIPTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).update(delink_tray=True)
                    results['processed_delinks'] += 1
                    print(f"✅ Delinked tray: {tray_id}")
                    
                    # 🟢 Update only delink_tray in RecoveryBrassTrayId for this tray_id and lot_id
                    RecoveryBrassTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).update(delink_tray=True)
                    results['processed_delinks'] += 1
                    print(f"✅ Delinked tray: {tray_id}")
                    
                    # 🟢 Update only delink_tray in RecoveryBrassAuditTrayId for this tray_id and lot_id
                    RecoveryBrassAuditTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).update(delink_tray=True)
                    results['processed_delinks'] += 1
                    print(f"✅ Delinked tray: {tray_id}")
                    
                    
                    RecoveryTrayId_History.objects.filter(tray_id=tray_id, lot_id=lot_id).update(delink_tray=True)
                    results['processed_delinks'] += 1
                    print(f"✅ Delinked tray: {tray_id}")
                    
                    tray_obj = RecoveryTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).first()
                    if tray_obj:
                        tray_obj.delink_tray = True
                        tray_obj.lot_id = None
                        tray_obj.batch_id = None
                        tray_obj.scanned = False
                        tray_obj.tray_quantity = 0
                        tray_obj.IP_tray_verified = False
                        tray_obj.rejected_tray = False
                        tray_obj.top_tray = False
                        tray_obj.new_tray = True
                        tray_obj.save(update_fields=[
                            'delink_tray', 'lot_id', 'batch_id', 'scanned', 'tray_quantity',
                            'IP_tray_verified', 'rejected_tray', 'top_tray', 'new_tray'
                        ])
                    
                    
                    results['processed_delinks'] += 1
                    print(f"✅ Delinked tray: {tray_id}")
                else:
                    results['errors'].append(f"Delink tray {tray_id} not found")
                    
            except Exception as e:
                results['errors'].append(f"Error processing delink tray {tray_id}: {str(e)}")
        
        # ✅ UPDATED: Process verification checkboxes AND save rejection quantity
        for verification in verifications:
            try:
                tray_id = verification['tray_id']
                verified = verification['verified']
                qty = verification.get('qty')  # ✅ Get the rejection quantity
                
                tray_obj = RecoveryIQFTrayId.objects.filter(lot_id=lot_id, tray_id=tray_id).first()
                if tray_obj:
                    # ✅ UPDATE BOTH VERIFICATION FLAG AND QUANTITY
                    tray_obj.iqf_reject_verify = verified
                    
                    # ✅ SAVE THE REJECTION QUANTITY if provided
                    if qty is not None:
                        try:
                            tray_obj.tray_quantity = int(qty)
                            print(f"✅ Updated tray {tray_id} quantity to {qty}")
                        except (ValueError, TypeError):
                            print(f"⚠️ Invalid quantity {qty} for tray {tray_id}, keeping original")
                    
                    # ✅ SAVE BOTH FIELDS
                    tray_obj.save(update_fields=['iqf_reject_verify', 'tray_quantity'])
                    
                    results['processed_verifications'] += 1
                    print(f"✅ Verified tray: {tray_id} = {verified}, qty = {qty}")
                else:
                    results['errors'].append(f"Verification tray {tray_id} not found")
                    
            except Exception as e:
                results['errors'].append(f"Error processing verification for {verification.get('tray_id', 'unknown')}: {str(e)}")
        
        # ✅ Process rejection top trays (if any)
        for rejection in rejection_top_trays:
            try:
                tray_id = rejection['tray_id']
                qty = rejection['qty']
                
                # Update tray quantity if it exists
                tray_obj = RecoveryIQFTrayId.objects.filter(lot_id=lot_id, tray_id=tray_id).first()
                if tray_obj:
                    tray_obj.tray_quantity = int(qty)
                    tray_obj.save(update_fields=['tray_quantity'])
                    print(f"✅ Updated rejection top tray: {tray_id} = {qty}")
                
                results['processed_rejections'] += 1
                
            except Exception as e:
                results['errors'].append(f"Error processing rejection tray {rejection.get('tray_id', 'unknown')}: {str(e)}")
        
        # ✅ Update stock status
        stock = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
        if stock:
            stock.iqf_onhold_picking = False
            stock.save(update_fields=['iqf_onhold_picking'])

        # ✅ Summary response
        success = len(results['errors']) == 0
        message_parts = []
        
        if results['processed_delinks'] > 0:
            message_parts.append(f"{results['processed_delinks']} trays delinked")
        if results['processed_verifications'] > 0:
            message_parts.append(f"{results['processed_verifications']} verifications saved")
        if results['processed_rejections'] > 0:
            message_parts.append(f"{results['processed_rejections']} rejection trays processed")
        
        message = ", ".join(message_parts) if message_parts else "No data to process"
        
        if results['errors']:
            message += f" (with {len(results['errors'])} errors)"
        
        return Response({
            'success': success,
            'message': message,
            'results': results,
            'is_draft': is_draft
        })
        
    except Exception as e:
        print(f"[DEBUG] Error in iqf_process_all_tray_data: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response({'success': False, 'error': str(e)}, status=500)
     
     
     
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recovery_get_tray_capacity(request):
    lot_id = request.GET.get('lot_id')
    print(f"Received tray capacity request for lot_id: {lot_id}")

    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    try:
        stock = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
        if stock and stock.batch_id and hasattr(stock.batch_id, 'tray_capacity'):
            tray_capacity = stock.batch_id.tray_capacity
        print(f"Tray capacity for lot_id {lot_id}: {tray_capacity}")  # <-- Add this line
        return Response({'success': True, 'tray_capacity': tray_capacity})
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)
    

@csrf_exempt
def recovery_iqf_delink_selected_trays(request):
    if request.method == "POST":
        import json
        try:
            data = json.loads(request.body.decode('utf-8'))
            
            stock_lot_ids = data.get('stock_lot_ids', [])
            tray_ids = data.get('tray_ids', [])
            
            updated_ip_trays = 0
            updated_original_trays = 0
            updated_brass_trays = 0
            updated_brass_audit_trays = 0
            updated_iptrayid_trays = 0  # Track RecoveryIPTrayId updates
            lots_processed = 0
            not_found = []
            
            if stock_lot_ids:
                for stock_lot_id in stock_lot_ids:
                    rejected_tray_ids = list(RecoveryIQFTrayId.objects.filter(
                        lot_id=stock_lot_id, 
                        rejected_tray=True
                    ).values_list('tray_id', flat=True))
                    
                    if rejected_tray_ids:
                        # RecoveryIQFTrayId
                        updated_count_ip = RecoveryIQFTrayId.objects.filter(
                            lot_id=stock_lot_id,
                            rejected_tray=True
                        ).update(
                            delink_tray=True,
                        )
                        updated_ip_trays += updated_count_ip
                        
                        # RecoveryTrayId
                        updated_count_original = RecoveryTrayId.objects.filter(
                            tray_id__in=rejected_tray_ids
                        ).update(
                            delink_tray=True,
                            lot_id=None,
                            batch_id=None,
                            scanned=False,
                            IP_tray_verified=False,
                            rejected_tray=False,
                            top_tray=False,
                            new_tray=True
                        )
                        updated_original_trays += updated_count_original

                        # RecoveryBrassTrayId
                        updated_count_brass = RecoveryBrassTrayId.objects.filter(
                            tray_id__in=rejected_tray_ids
                        ).update(
                            delink_tray=True,
                        )
                        updated_brass_trays += updated_count_brass

                        # RecoveryBrassAuditTrayId
                        updated_count_brass_audit = RecoveryBrassAuditTrayId.objects.filter(
                            tray_id__in=rejected_tray_ids
                        ).update(
                            delink_tray=True,
                        )
                        updated_brass_audit_trays += updated_count_brass_audit

                        # RecoveryIPTrayId
                        updated_count_iptrayid = RecoveryIPTrayId.objects.filter(
                            tray_id__in=rejected_tray_ids
                        ).update(
                            delink_tray=True,
                        )
                        updated_iptrayid_trays += updated_count_iptrayid
                        
                        lots_processed += 1
                    else:
                        not_found.append(stock_lot_id)
                
                return JsonResponse({
                    'success': True, 
                    'updated_ip_trays': updated_ip_trays,
                    'updated_original_trays': updated_original_trays,
                    'updated_brass_trays': updated_brass_trays,
                    'updated_brass_audit_trays': updated_brass_audit_trays,
                    'updated_iptrayid_trays': updated_iptrayid_trays,
                    'total_updated': updated_ip_trays + updated_original_trays + updated_brass_trays + updated_brass_audit_trays + updated_iptrayid_trays,
                    'lots_processed': lots_processed,
                    'not_found': not_found
                })
            
            elif tray_ids:
                for tray_id in tray_ids:
                    # RecoveryIQFTrayId
                    delink_tray_obj = RecoveryIQFTrayId.objects.filter(tray_id=tray_id).first()
                    if delink_tray_obj:
                        delink_tray_obj.delink_tray = True
                        delink_tray_obj.save(update_fields=[
                            'delink_tray'
                        ])
                        updated_ip_trays += 1
                    
                    # RecoveryTrayId
                    original_tray_obj = RecoveryTrayId.objects.filter(tray_id=tray_id).first()
                    if original_tray_obj:
                        original_tray_obj.delink_tray = True
                        original_tray_obj.lot_id = None
                        original_tray_obj.batch_id = None
                        original_tray_obj.scanned = False
                        original_tray_obj.IP_tray_verified = False
                        original_tray_obj.rejected_tray = False
                        original_tray_obj.top_tray = False
                        original_tray_obj.new_tray = True
                        original_tray_obj.save(update_fields=[
                            'delink_tray', 'lot_id', 'batch_id', 'scanned','new_tray','IP_tray_verified', 'top_tray', 'rejected_tray'
                        ])
                        updated_original_trays += 1
                        
                    history_tray_obj = RecoveryTrayId_History.objects.filter(tray_id=tray_id).first()
                    if history_tray_obj:
                        history_tray_obj.delink_tray = True
                        history_tray_obj.save(update_fields=[
                            'delink_tray'
                        ])
                        updated_ip_trays += 1
                        print(f"✅ Updated RecoveryIPTrayId for tray_id: {tray_id}")
                    else:
                        print(f"⚠️ history_tray_obj not found for tray_id: {tray_id}")
                    
                    # RecoveryBrassTrayId
                    brass_tray_obj = RecoveryBrassTrayId.objects.filter(tray_id=tray_id).first()
                    if brass_tray_obj:
                        brass_tray_obj.delink_tray = True
                        brass_tray_obj.save(update_fields=[
                            'delink_tray'
                        ])
                        updated_brass_trays += 1
 
                    # RecoveryBrassAuditTrayId
                    brass_audit_tray_obj = RecoveryBrassAuditTrayId.objects.filter(tray_id=tray_id).first()
                    if brass_audit_tray_obj:
                        brass_audit_tray_obj.delink_tray = True
                        brass_audit_tray_obj.save(update_fields=[
                            'delink_tray'
                        ])
                        updated_brass_audit_trays += 1

                    # RecoveryIPTrayId
                    iptrayid_tray_obj = RecoveryIPTrayId.objects.filter(tray_id=tray_id).first()
                    if iptrayid_tray_obj:
                        iptrayid_tray_obj.delink_tray = True
                        iptrayid_tray_obj.save(update_fields=[
                            'delink_tray'
                        ])
                        updated_iptrayid_trays += 1

                    else:
                        not_found.append(tray_id)
                
                return JsonResponse({
                    'success': True, 
                    'updated_ip_trays': updated_ip_trays,
                    'updated_original_trays': updated_original_trays,
                    'updated_brass_trays': updated_brass_trays,
                    'updated_brass_audit_trays': updated_brass_audit_trays,
                    'updated_iptrayid_trays': updated_iptrayid_trays,
                    'total_updated': updated_ip_trays + updated_original_trays + updated_brass_trays + updated_brass_audit_trays + updated_iptrayid_trays,
                    'not_found': not_found
                })
            
            else:
                return JsonResponse({'success': False, 'error': 'No stock_lot_ids or tray_ids provided'})
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)
# These views is for draft ( Delink and Rejection Verification )

from django.views.decorators.http import require_http_methods
from django.views import View

@method_decorator([login_required, csrf_exempt], name='dispatch')
class RecoveryIQFOptimalDistributionDraftView(View):
    """
    Handle optimal distribution draft save/load operations
    """
    
    def get(self, request):
        """
        Get draft data for a specific lot_id
        """
        try:
            lot_id = request.GET.get('lot_id')
            
            if not lot_id:
                return JsonResponse({
                    'success': False,
                    'error': 'lot_id parameter is required'
                }, status=400)
            
            try:
                draft = RecoveryIQF_OptimalDistribution_Draft.objects.get(
                    lot_id=lot_id,
                    user=request.user
                )
                
                return JsonResponse({
                    'success': True,
                    'has_draft': True,
                    'draft_data': {
                        'lot_id': draft.lot_id,
                        'delink_trays': draft.delink_trays,
                        'rejection_verifications': draft.rejection_verifications,
                        'created_at': draft.created_at.isoformat(),
                        'updated_at': draft.updated_at.isoformat()
                    }
                })
                
            except RecoveryIQF_OptimalDistribution_Draft.DoesNotExist:
                return JsonResponse({
                    'success': True,
                    'has_draft': False,
                    'draft_data': None
                })
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error retrieving draft: {str(e)}'
            }, status=500)
    
    def post(self, request):
        """
        Save draft data for optimal distribution
        """
        try:
            data = json.loads(request.body)
            lot_id = data.get('lot_id')
            delink_trays = data.get('delink_trays', [])
            rejection_verifications = data.get('rejection_verifications', [])
            
            if not lot_id:
                return JsonResponse({
                    'success': False,
                    'error': 'lot_id is required'
                }, status=400)
            
            # Validate delink_trays structure
            if not isinstance(delink_trays, list):
                return JsonResponse({
                    'success': False,
                    'error': 'delink_trays must be an array'
                }, status=400)
            
            # Validate rejection_verifications structure
            if not isinstance(rejection_verifications, list):
                return JsonResponse({
                    'success': False,
                    'error': 'rejection_verifications must be an array'
                }, status=400)
            
            # Create or update draft
            draft, created = RecoveryIQF_OptimalDistribution_Draft.objects.update_or_create(
                lot_id=lot_id,
                user=request.user,
                defaults={
                    'delink_trays': delink_trays,
                    'rejection_verifications': rejection_verifications
                }
            )
            
            action = 'created' if created else 'updated'
            
            return JsonResponse({
                'success': True,
                'message': f'Draft {action} successfully',
                'draft_id': draft.id,
                'action': action,
                'data': {
                    'lot_id': draft.lot_id,
                    'delink_trays_count': len(draft.delink_trays),
                    'rejection_verifications_count': len(draft.rejection_verifications),
                    'updated_at': draft.updated_at.isoformat()
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error saving draft: {str(e)}'
            }, status=500)
    
    def delete(self, request):
        """
        Delete draft data for a specific lot_id
        """
        try:
            data = json.loads(request.body)
            lot_id = data.get('lot_id')
            
            if not lot_id:
                return JsonResponse({
                    'success': False,
                    'error': 'lot_id is required'
                }, status=400)
            
            try:
                draft = RecoveryIQF_OptimalDistribution_Draft.objects.get(
                    lot_id=lot_id,
                    user=request.user
                )
                draft.delete()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Draft deleted successfully'
                })
                
            except RecoveryIQF_OptimalDistribution_Draft.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Draft not found'
                }, status=404)
                
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error deleting draft: {str(e)}'
            }, status=500)


# Alternative function-based views (if you prefer)

@csrf_exempt
@login_required
@require_http_methods(["GET"])
def recovery_iqf_check_optimal_distribution_draft(request):
    """
    Check if draft exists for a lot_id
    """
    try:
        lot_id = request.GET.get('lot_id')
        
        if not lot_id:
            return JsonResponse({
                'success': False,
                'error': 'lot_id parameter is required'
            }, status=400)
        
        has_draft = RecoveryIQF_OptimalDistribution_Draft.objects.filter(
            lot_id=lot_id,
            user=request.user
        ).exists()
        
        return JsonResponse({
            'success': True,
            'has_draft': has_draft
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error checking draft: {str(e)}'
        }, status=500)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def recovery_iqf_save_optimal_distribution_draft(request):
    """
    Save optimal distribution draft data
    """
    try:
        data = json.loads(request.body)
        lot_id = data.get('lot_id')
        delink_trays = data.get('delink_trays', [])
        rejection_verifications = data.get('rejection_verifications', [])
        
        if not lot_id:
            return JsonResponse({
                'success': False,
                'error': 'lot_id is required'
            }, status=400)
        
        # Save or update the draft
        draft, created = RecoveryIQF_OptimalDistribution_Draft.objects.update_or_create(
            lot_id=lot_id,
            user=request.user,
            defaults={
                'delink_trays': delink_trays,
                'rejection_verifications': rejection_verifications
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Draft {"created" if created else "updated"} successfully',
            'draft_id': draft.id
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error saving draft: {str(e)}'
        }, status=500)


@csrf_exempt
@login_required
@require_http_methods(["GET"])
def recovery_iqf_load_optimal_distribution_draft(request):
    """
    Load optimal distribution draft data
    """
    try:
        lot_id = request.GET.get('lot_id')
        
        if not lot_id:
            return JsonResponse({
                'success': False,
                'error': 'lot_id parameter is required'
            }, status=400)
        
        try:
            draft = RecoveryIQF_OptimalDistribution_Draft.objects.get(
                lot_id=lot_id,
                user=request.user
            )
            
            return JsonResponse({
                'success': True,
                'draft_data': {
                    'lot_id': draft.lot_id,
                    'delink_trays': draft.delink_trays,
                    'rejection_verifications': draft.rejection_verifications,
                    'created_at': draft.created_at.isoformat(),
                    'updated_at': draft.updated_at.isoformat()
                }
            })
            
        except RecoveryIQF_OptimalDistribution_Draft.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Draft not found'
            }, status=404)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error loading draft: {str(e)}'
        }, status=500)
        


@method_decorator(login_required, name='dispatch')
class RecoveryIQFAcceptTableView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Recovery_IQF/Recovery_Iqf_AcceptTable.html'
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import math

        user = request.user

        # Query only accepted IQF lots (no date filter)
        queryset = RecoveryStockModel.objects.select_related(
            'batch_id',
            'batch_id__model_stock_no',
            'batch_id__version',
            'batch_id__location'
        ).filter(
            Q(iqf_acceptance=True) |
            (Q(iqf_few_cases_acceptance=True) & Q(iqf_onhold_picking=False)),
            batch_id__total_batch_quantity__gt=0
        ).order_by('-iqf_last_process_date_time')

        # Subqueries for rejection quantities
        brass_rejection_qty_subquery = RecoveryBrass_QC_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        iqf_rejection_qty_subquery = RecoveryIQF_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = queryset.annotate(
            wiping_required=F('batch_id__model_stock_no__wiping_required'),
            brass_rejection_total_qty=brass_rejection_qty_subquery,
            iqf_rejection_qty=iqf_rejection_qty_subquery,
        )

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        master_data = []
        for stock_obj in page_obj.object_list:
            batch = stock_obj.batch_id
            data = {
                'batch_id': batch.batch_id,
                'date_time': getattr(batch, 'date_time', None),
                'model_stock_no__model_no': batch.model_stock_no.model_no if batch.model_stock_no else '',
                'plating_color': batch.plating_color,
                'polish_finish': batch.polish_finish,
                'version__version_name': batch.version.version_name if batch.version else '',
                'vendor_internal': batch.vendor_internal,
                'location__location_name': batch.location.location_name if batch.location else '',
                'tray_type': batch.tray_type,
                'tray_capacity': batch.tray_capacity,
                'Moved_to_D_Picker': batch.Moved_to_D_Picker,
                'Draft_Saved': batch.Draft_Saved,
                'plating_stk_no': batch.plating_stk_no,
                'polishing_stk_no': batch.polishing_stk_no,
                'category': batch.category,
                'lot_id': stock_obj.lot_id,
                'stock_lot_id': stock_obj.lot_id,
                'last_process_module': stock_obj.last_process_module,
                'next_process_module': stock_obj.next_process_module,
                'wiping_required': getattr(stock_obj, 'wiping_required', None),
                'iqf_missing_qty': stock_obj.iqf_missing_qty,
                'iqf_physical_qty': stock_obj.iqf_physical_qty,
                'iqf_physical_qty_edited': getattr(stock_obj, 'iqf_physical_qty_edited', None),
                'accepted_tray_scan_status': getattr(stock_obj, 'accepted_tray_scan_status', None),
                'iqf_rejection_qty': getattr(stock_obj, 'iqf_rejection_qty', None),
                'iqf_accepted_qty': stock_obj.iqf_accepted_qty,
                'IQF_pick_remarks': getattr(stock_obj, 'IQF_pick_remarks', None),
                'brass_accepted_tray_scan_status': getattr(stock_obj, 'brass_accepted_tray_scan_status', None),
                'brass_qc_rejection': getattr(stock_obj, 'brass_qc_rejection', None),
                'brass_rejection_total_qty': getattr(stock_obj, 'brass_rejection_total_qty', None),
                'brass_qc_few_cases_accptance': getattr(stock_obj, 'brass_qc_few_cases_accptance', None),
                'iqf_accepted_qty_verified': stock_obj.iqf_accepted_qty_verified,
                'iqf_acceptance': stock_obj.iqf_acceptance,
                'iqf_rejection': getattr(stock_obj, 'iqf_rejection', None),
                'iqf_few_cases_acceptance': getattr(stock_obj, 'iqf_few_cases_acceptance', None),
                'iqf_onhold_picking': getattr(stock_obj, 'iqf_onhold_picking', None),
                'iqf_accepted_tray_scan_status': getattr(stock_obj, 'iqf_accepted_tray_scan_status', None),
                'iqf_last_process_date_time': stock_obj.iqf_last_process_date_time,
                'total_IP_accpeted_quantity': stock_obj.total_IP_accpeted_quantity,
            }
            master_data.append(data)

        # Process the data with fallback to total_IP_accpeted_quantity
        for data in master_data:
            brass_rejection_total_qty = data.get('brass_rejection_total_qty')
            total_ip_accepted_qty = data.get('total_IP_accpeted_quantity', 0)
            tray_capacity = data.get('tray_capacity')

            # Use total_IP_accpeted_quantity as fallback when brass_rejection_total_qty is None
            if brass_rejection_total_qty is None:
                effective_qty = total_ip_accepted_qty
            else:
                effective_qty = brass_rejection_total_qty

            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"

            # Calculate no_of_trays using effective_qty
            if effective_qty is None or tray_capacity is None or tray_capacity == 0:
                data['no_of_trays'] = 0
            else:
                data['no_of_trays'] = math.ceil(effective_qty / tray_capacity)

            # Store the effective quantity for display purposes
            data['display_quantity'] = effective_qty
            data['quantity_source'] = 'total_IP_accpeted_quantity' if brass_rejection_total_qty is None else 'brass_rejection_total_qty'

            # Get model images
            batch_obj = RecoveryMasterCreation.objects.filter(batch_id=data['batch_id']).first()
            images = []
            if batch_obj and batch_obj.model_stock_no:
                for img in batch_obj.model_stock_no.images.all():
                    if img.master_image:
                        images.append(img.master_image.url)
            if not images:
                images = [static('assets/images/imagePlaceholder.jpg')]
            data['model_images'] = images

            # Add available_qty logic with fallback
            lot_id = data.get('stock_lot_id')
            total_stock_obj = RecoveryStockModel.objects.filter(lot_id=lot_id).first()
            if total_stock_obj:
                if total_stock_obj.iqf_physical_qty and total_stock_obj.iqf_physical_qty > 0:
                    data['available_qty'] = total_stock_obj.iqf_physical_qty
                else:
                    data['available_qty'] = effective_qty or 0
            else:
                data['available_qty'] = 0

        context = {
            'master_data': master_data,
            'page_obj': page_obj,
            'paginator': paginator,
            'user': user,
        }
        return Response(context, template_name=self.template_name)
    
        
class IQFTrayDelinkTopTrayCalcAPIView(APIView):
    """
    Calculate delink trays and top tray based on missing quantity.

    GET Parameters:
    - lot_id: The lot ID to calculate for
    - missing_qty: The quantity that needs to be delinked

    Returns:
    {
        "success": true,
        "delink_count": int,
        "delink_trays": [tray_id, ...],
        "top_tray": {"tray_id": ..., "qty": ...} or None,
        "total_missing": int,
        "calculation_details": {...}
    }
    """

    def get(self, request):
        try:
            # Get parameters
            lot_id = request.GET.get('lot_id')
            missing_qty = request.GET.get('missing_qty', 0)

            # Validation
            if not lot_id:
                return Response({
                    'success': False,
                    'error': 'Missing lot_id parameter'
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                missing_qty = int(missing_qty)
                if missing_qty < 0:
                    raise ValueError("Missing quantity cannot be negative")
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'error': 'Invalid missing_qty parameter. Must be a non-negative integer.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # If missing quantity is 0, return empty result
            if missing_qty == 0:
                return Response({
                    'success': True,
                    'delink_count': 0,
                    'delink_trays': [],
                    'top_tray': None,
                    'total_missing': 0,
                    'message': 'No delink required'
                })

            # Get trays for the lot, ordered by creation/ID to maintain consistency
            trays = RecoveryIQFTrayId.objects.filter(
                lot_id=lot_id,
                tray_quantity__gt=0  # Only trays with quantity > 0
            ).order_by('id').values('tray_id', 'tray_quantity')

            if not trays.exists():
                return Response({
                    'success': False,
                    'error': f'No trays found for lot {lot_id}'
                }, status=status.HTTP_404_NOT_FOUND)

            # Convert to list for easier processing
            tray_list = list(trays)

            # Calculate total available quantity
            total_available = sum(tray['tray_quantity'] for tray in tray_list)

            if missing_qty > total_available:
                return Response({
                    'success': False,
                    'error': f'Missing quantity ({missing_qty}) exceeds total available quantity ({total_available})'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Sort tray_list by tray_quantity ascending (smallest first)
            tray_list_sorted = sorted(tray_list, key=lambda x: x['tray_quantity'])
            
            delink_trays = []
            top_tray = None
            remaining_missing = missing_qty
            calculation_steps = []
            
            for i, tray in enumerate(tray_list_sorted):
                tray_id = tray['tray_id']
                tray_qty = tray['tray_quantity']
            
                print(f"[DELINK DEBUG] Step {i+1}: tray_id={tray_id}, tray_qty={tray_qty}, remaining_missing={remaining_missing}")
            
                if remaining_missing <= 0:
                    break
            
                if remaining_missing >= tray_qty:
                    print(f"[DELINK DEBUG] Delinking full tray {tray_id} (qty {tray_qty})")
                    delink_trays.append(tray_id)
                    remaining_missing -= tray_qty
                    calculation_steps.append({
                        'step': i + 1,
                        'tray_id': tray_id,
                        'tray_qty': tray_qty,
                        'action': 'delink_complete',
                        'remaining_missing': remaining_missing
                    })
                else:
                    remaining_qty_in_tray = tray_qty - remaining_missing
                    print(f"[DELINK DEBUG] Top tray is {tray_id}: original_qty={tray_qty}, delinked_qty={remaining_missing}, remaining_qty_in_tray={remaining_qty_in_tray}")
                    top_tray = {
                        'tray_id': tray_id,
                        'qty': remaining_qty_in_tray,
                        'original_qty': tray_qty,
                        'delinked_qty': remaining_missing
                    }
                    calculation_steps.append({
                        'step': i + 1,
                        'tray_id': tray_id,
                        'tray_qty': tray_qty,
                        'action': 'partial_delink',
                        'delinked_from_tray': remaining_missing,
                        'remaining_in_tray': remaining_qty_in_tray,
                        'remaining_missing': 0
                    })
                    remaining_missing = 0
                    break
            
            print(f"[DELINK DEBUG] Final delink_count: {len(delink_trays)}")
            # ✅ PATCH: If missing_qty is exactly consumed by full trays, show next tray as top tray
            if remaining_missing == 0 and len(delink_trays) > 0 and len(tray_list) > len(delink_trays) and top_tray is None:
                next_tray = tray_list[len(delink_trays)]
                top_tray = {
                    'tray_id': next_tray['tray_id'],
                    'qty': next_tray['tray_quantity'],
                    'original_qty': next_tray['tray_quantity'],
                    'delinked_qty': 0,
                    'top_tray': True  # <-- Add this line

                }

            # Prepare response
            result = {
                'success': True,
                'delink_count': len(delink_trays),
                'delink_trays': delink_trays,
                'top_tray': top_tray,
                'total_missing': missing_qty,
                'total_available': total_available,
                'calculation_details': {
                    'steps': calculation_steps,
                    'trays_processed': len([step for step in calculation_steps]),
                    'total_trays_in_lot': len(tray_list)
                }
            }

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            # Log the error in production
            print(f"Error in IQFTrayDelinkTopTrayCalcAPIView: {str(e)}")

            return Response({
                'success': False,
                'error': 'Internal server error occurred while calculating delink requirements'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class IQFTrayDelinkAndTopTrayUpdateAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            delink_tray_ids = data.get('delink_tray_ids', [])
            top_tray_id = data.get('top_tray_id')
            top_tray_qty = data.get('top_tray_qty')
            
            print(f"[DEBUG] Incoming data: {data}")
            print(f"[DEBUG] Delink tray IDs: {delink_tray_ids}")
            print(f"[DEBUG] Top tray: {top_tray_id} with qty: {top_tray_qty}")

            # 1. Process delink trays across all tables
            delinked_count = 0
            for delink_tray_id in delink_tray_ids:
                print(f"[DELINK] Processing tray: {delink_tray_id}")
                # RecoveryIQFTrayId - Remove from lot completely
                iqf_delink_tray_obj = RecoveryIQFTrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if iqf_delink_tray_obj:
                    iqf_delink_tray_obj.delink_tray = True
                    iqf_delink_tray_obj.lot_id = None
                    iqf_delink_tray_obj.batch_id = None
                    iqf_delink_tray_obj.IP_tray_verified = False
                    iqf_delink_tray_obj.top_tray = False
                    iqf_delink_tray_obj.save(update_fields=[
                        'delink_tray', 'lot_id', 'batch_id', 'IP_tray_verified', 'top_tray'
                    ])
                    print(f"✅ Delinked IQFTrayId tray: {delink_tray_id}")
    
                # RecoveryIPTrayId - Mark as delinked
                ip_delink_tray_obj = RecoveryIPTrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if ip_delink_tray_obj:
                    ip_delink_tray_obj.delink_tray = True
                    ip_delink_tray_obj.save(update_fields=['delink_tray'])
                    print(f"✅ Delinked RecoveryIPTrayId tray: {delink_tray_id} for lot: {lot_id}")
                
                # BQTrayId - Mark as delinked
                bq_delink_tray_obj = RecoveryBrassTrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if bq_delink_tray_obj:
                    bq_delink_tray_obj.delink_tray = True
                    bq_delink_tray_obj.save(update_fields=['delink_tray'])
                    print(f"✅ Delinked RecoveryBrassTrayId tray: {delink_tray_id} for lot: {lot_id}")

                # RecoveryTrayId_History - Mark as delinked
                dp_history_tray_obj = RecoveryTrayId_History.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if dp_history_tray_obj:
                    dp_history_tray_obj.delink_tray = True
                    dp_history_tray_obj.save(update_fields=['delink_tray'])
                    print(f"✅ Delinked RecoveryTrayId_History tray: {delink_tray_id} for lot: {lot_id}")
                
                # TrayId - Remove from lot completely
                trayid_delink_tray_obj = TrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if trayid_delink_tray_obj:
                    trayid_delink_tray_obj.delink_tray = True
                    trayid_delink_tray_obj.lot_id = None
                    trayid_delink_tray_obj.batch_id = None
                    trayid_delink_tray_obj.IP_tray_verified = False
                    trayid_delink_tray_obj.top_tray = False
                    trayid_delink_tray_obj.save(update_fields=[
                        'delink_tray', 'lot_id', 'batch_id', 'IP_tray_verified', 'top_tray'
                    ])
                    print(f"✅ Delinked TrayId tray: {delink_tray_id}")
                
                delinked_count += 1

            # 2. Update top tray (if provided)
            if top_tray_id and top_tray_qty is not None:
                print(f"[TOP TRAY] Updating tray: {top_tray_id} with qty: {top_tray_qty}")
                
                # Update RecoveryIQFTrayId for top tray
                top_tray_obj = RecoveryIQFTrayId.objects.filter(tray_id=top_tray_id, lot_id=lot_id).first()
                if top_tray_obj:
                    top_tray_obj.top_tray = True
                    top_tray_obj.tray_quantity = int(top_tray_qty)
                    top_tray_obj.delink_tray = False  # Ensure it's not marked as delink
                    top_tray_obj.save(update_fields=['top_tray', 'tray_quantity', 'delink_tray'])
                    print(f"✅ Updated RecoveryIQFTrayId top tray: {top_tray_id} to qty: {top_tray_qty}")

            # 3. Reset other trays (not delinked or top tray) to full capacity
            other_trays_iqf = RecoveryIQFTrayId.objects.filter(
                lot_id=lot_id
            ).exclude(
                tray_id__in=delink_tray_ids + ([top_tray_id] if top_tray_id else [])
            )
            
            other_trays_count = 0
            for tray in other_trays_iqf:
                print(f"[OTHER TRAY] Resetting IQFTrayId {tray.tray_id} to full capacity: {tray.tray_capacity}")
                tray.tray_quantity = tray.tray_capacity  # Reset to full capacity
                tray.top_tray = False
                tray.delink_tray = False
                tray.save(update_fields=['tray_quantity', 'top_tray', 'delink_tray'])
                other_trays_count += 1

            # 4. Summary logging
            print(f"[SUMMARY] Processing completed:")
            print(f"  - Delinked {delinked_count} trays across all tables")
            if top_tray_id:
                print(f"  - Updated top tray {top_tray_id} to qty={top_tray_qty}")
            print(f"  - Reset {other_trays_count} other trays to full capacity")

            return Response({
                'success': True, 
                'message': f'Delink and top tray update completed successfully.',
                'details': {
                    'delinked_trays': delinked_count,
                    'top_tray_updated': bool(top_tray_id),
                    'other_trays_reset': other_trays_count,
                    'top_tray_id': top_tray_id,
                    'top_tray_qty': top_tray_qty
                }
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] Failed to update trays: {str(e)}")
            return Response({
                'success': False, 
                'error': f'Failed to update trays: {str(e)}'
            }, status=500)
            
class IQFValidateTrayIdAPIView(APIView):
    def get(self, request):
        tray_id = request.GET.get('tray_id')
        lot_id = request.GET.get('lot_id')
        exists = RecoveryIQFTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).exists()
        return Response({
            'exists': exists,
            'valid_for_lot': exists
        })


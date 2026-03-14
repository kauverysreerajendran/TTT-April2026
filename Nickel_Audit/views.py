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
from Spider_Spindle.models import *

from Jig_Unloading.models import *


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
        ).order_by('-nq_last_process_date_time', '-lot_id')

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
                'tray_type': jig_unload_obj.tray_type or '',
                'tray_capacity': jig_unload_obj.tray_capacity or 0,
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
                images = [static('assets/images/imagePlaceholder.png')]
            
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

@method_decorator(csrf_exempt, name='dispatch')
class NASaveHoldUnholdReasonAPIView(APIView):
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
                obj.na_holding_reason = remark
                obj.na_hold_lot = True
                obj.na_release_reason = ''
                obj.na_release_lot = False
            elif action == 'unhold':
                obj.na_release_reason = remark
                obj.na_hold_lot = False
                obj.na_release_lot = True

            obj.save(update_fields=['na_holding_reason', 'na_release_reason', 'na_hold_lot', 'na_release_lot'])
            return JsonResponse({'success': True, 'message': 'Reason saved.'})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        
    
@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')  
class NASaveIPCheckboxView(APIView):
    def post(self, request, format=None):
        try:
            data = request.data
            lot_id = data.get("lot_id")
            missing_qty = data.get("missing_qty")
            print("DEBUG: Received lot_id:", lot_id)
            print("DEBUG: Received missing_qty:", missing_qty)

            if not lot_id:
                return Response({"success": False, "error": "Lot ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Debug: Check what records exist in JigUnloadAfterTable
            all_records = JigUnloadAfterTable.objects.all().values_list('unload_lot_id', flat=True)
            print("DEBUG: All unload_lot_id values in database:", list(all_records))
            
            # Try to find the record - first try unload_lot_id, then try other possible fields
            total_stock = None
            try:
                total_stock = JigUnloadAfterTable.objects.get(unload_lot_id=lot_id)
                print("DEBUG: Found record using unload_lot_id:", total_stock.unload_lot_id)
            except JigUnloadAfterTable.DoesNotExist:
                # If unload_lot_id doesn't work, try other possible field names
                try:
                    total_stock = JigUnloadAfterTable.objects.get(lot_id=lot_id)
                    print("DEBUG: Found record using lot_id:", total_stock.lot_id)
                except JigUnloadAfterTable.DoesNotExist:
                    print("DEBUG: No record found with lot_id or unload_lot_id:", lot_id)
                    # Check if any record exists with this value in any field
                    matching_records = JigUnloadAfterTable.objects.filter(
                        Q(unload_lot_id=lot_id) | Q(lot_id=lot_id)
                    )
                    print("DEBUG: Matching records found:", matching_records.count())
                    if matching_records.exists():
                        total_stock = matching_records.first()
                    else:
                        raise JigUnloadAfterTable.DoesNotExist()
            
            if not total_stock:
                raise JigUnloadAfterTable.DoesNotExist()
            
            # Update required fields
            total_stock.na_ac_accepted_qty_verified = True
            total_stock.last_process_module = "Nickel Audit"
            total_stock.next_process_module = "Nickel Audit"

            # Calculate display_accepted_qty with rejection quantity logic

            # Calculate display_accepted_qty from JigUnloadAfterTable with rejection adjustment
            display_accepted_qty = total_stock.nq_qc_accepted_qty

            if missing_qty not in [None, ""]:
                try:
                    missing_qty = int(missing_qty)
                except ValueError:
                    return Response({"success": False, "error": "Missing quantity must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
            
                if missing_qty > display_accepted_qty:
                    return Response(
                        {"success": False, "error": f"Missing quantity must be less than or equal to display accepted quantity ({display_accepted_qty})."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
                total_stock.na_missing_qty = missing_qty
                total_stock.na_physical_qty = display_accepted_qty - missing_qty
                print(f"[DEBUG] Set na_physical_qty: {total_stock.na_physical_qty} (display_accepted_qty: {display_accepted_qty}, missing_qty: {missing_qty})")

                self.create_nickel_tray_instances(lot_id)
           
            total_stock.save()
            return Response({"success": True})

        except JigUnloadAfterTable.DoesNotExist:
            return Response({"success": False, "error": "Stock not found."}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"success": False, "error": "Unexpected error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def create_nickel_tray_instances(self, lot_id):
        """
        Create or update NickelQcTrayId instances for all verified tray IDs in the given lot (excluding rejected trays).
        tray_type and tray_capacity are fetched from TrayId table based on tray_id.
        tray_quantity and top_tray are taken from JigUnload_TrayId.
        """
        try:
            print(f"✅ [create_nickel_tray_instances] Starting for lot_id: {lot_id}")
    
            verified_trays = NickelQcTrayId.objects.filter(
                lot_id=lot_id,
                rejected_tray=False
            ).all()
    
            # Get record from JigUnloadAfterTable using unload_lot_id
            total_stock = JigUnloadAfterTable.objects.filter(unload_lot_id=lot_id).first()
    
            created_count = 0
            updated_count = 0
    
            for tray in verified_trays:
                # Get tray_type and tray_capacity from TrayId table
                tray_master = TrayId.objects.filter(tray_id=tray.tray_id).first()
                tray_type = tray_master.tray_type if tray_master else None
                tray_capacity = tray_master.tray_capacity if tray_master else None
                top_tray_value = tray.top_tray
                # Only update if tray exists with lot_id IS NULL (placeholder tray)
                nickel_tray = Nickel_AuditTrayId.objects.filter(tray_id=tray.tray_id, lot_id__isnull=True).first()
                if nickel_tray:
                    print(f"🔄 Updating NickelQcTrayId with empty lot_id for tray_id: {tray.tray_id}")
                    nickel_tray.lot_id = lot_id
                    nickel_tray.date = timezone.now()
                    nickel_tray.user = self.request.user
                    nickel_tray.tray_quantity = tray.tray_qty  # from JigUnload_TrayId
                    nickel_tray.top_tray = top_tray_value       # from JigUnload_TrayId
                    nickel_tray.IP_tray_verified = True
                    nickel_tray.tray_type = tray_type          # from TrayId
                    nickel_tray.tray_capacity = tray_capacity  # from TrayId
                    nickel_tray.new_tray = False
                    nickel_tray.delink_tray = False
                    nickel_tray.rejected_tray = False
                    nickel_tray.save(update_fields=[
                        'lot_id', 'date', 'user', 'tray_quantity',
                        'top_tray', 'IP_tray_verified', 'tray_type', 'tray_capacity',
                        'new_tray', 'delink_tray', 'rejected_tray'
                    ])
                    updated_count += 1
                else:
                    print(f"➕ Creating new NickelQcTrayId for tray_id: {tray.tray_id}")
                    nickel_tray = Nickel_AuditTrayId(
                        tray_id=tray.tray_id,
                        lot_id=lot_id,
                        date=timezone.now(),
                        user=self.request.user,
                        tray_quantity=tray.tray_quantity,      # from JigUnload_TrayId
                        top_tray=top_tray_value,           # from JigUnload_TrayId
                        IP_tray_verified=True,
                        tray_type=tray_type,              # from TrayId
                        tray_capacity=tray_capacity,      # from TrayId
                        new_tray=False,
                        delink_tray=False,
                        rejected_tray=False,
                    )
                    nickel_tray.save()
                    created_count += 1
    
            print(f"📊 [create_nickel_tray_instances] Summary for lot {lot_id}:")
            print(f"   Created: {created_count} NickelQcTrayId records")
            print(f"   Updated: {updated_count} NickelQcTrayId records")
            print(f"   Total Processed: {created_count + updated_count}")
    
        except Exception as e:
            print(f"❌ [create_nickel_tray_instances] Error creating/updating NickelQcTrayId instances: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def get(self, request, format=None):
        return Response(
            {"success": False, "error": "Invalid request method."},
            status=status.HTTP_400_BAD_REQUEST
        )

@method_decorator(csrf_exempt, name='dispatch')
class NASaveIPPickRemarkAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            remark = data.get('remark', '').strip()
            if not lot_id:
                return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)
            obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if not obj:
                return JsonResponse({'success': False, 'error': 'LOT not found.'}, status=404)
            obj.na_pick_remarks = remark
            obj.save(update_fields=['na_pick_remarks'])
            return JsonResponse({'success': True, 'message': 'Remark saved'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

@require_GET
def brass_get_tray_capacity_for_lot(request):
    """
    Get ACTUAL tray capacity for a specific lot from the same source as main table
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return JsonResponse({'success': False, 'error': 'Missing lot_id'})
    
    try:
        print(f"🔍 [brass_get_tray_capacity_for_lot] Getting tray capacity for lot_id: {lot_id}")
        
        # ✅ METHOD 1: Get from TotalStockModel -> batch_id (same as main table)
        total_stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if total_stock:
            print(f"✅ Found TotalStockModel for lot_id: {lot_id}")
            
            # Get the batch_id from TotalStockModel
            if hasattr(total_stock, 'batch_id') and total_stock.batch_id:
                batch_obj = total_stock.batch_id  # This is ModelMasterCreation object
                print(f"✅ Found batch_id: {batch_obj.batch_id}")
                
                # Get tray_capacity from ModelMasterCreation (same as main table)
                if hasattr(batch_obj, 'tray_capacity') and batch_obj.tray_capacity:
                    tray_capacity = batch_obj.tray_capacity
                    print(f"✅ Found tray_capacity from ModelMasterCreation: {tray_capacity}")
                    return JsonResponse({
                        'success': True, 
                        'tray_capacity': tray_capacity,
                        'source': 'ModelMasterCreation.tray_capacity'
                    })
        
        # ✅ METHOD 2: Direct lookup in ModelMasterCreation by lot_id
        try:
            model_creation = ModelMasterCreation.objects.filter(lot_id=lot_id).first()
            if model_creation and hasattr(model_creation, 'tray_capacity') and model_creation.tray_capacity:
                tray_capacity = model_creation.tray_capacity
                print(f"✅ Found tray_capacity from direct ModelMasterCreation lookup: {tray_capacity}")
                return JsonResponse({
                    'success': True, 
                    'tray_capacity': tray_capacity,
                    'source': 'Direct ModelMasterCreation lookup'
                })
        except Exception as e:
            print(f"⚠️ Direct ModelMasterCreation lookup failed: {e}")
        
        # ✅ METHOD 3: Get from any existing TrayId for this lot
        tray_objects = TrayId.objects.filter(lot_id=lot_id).exclude(rejected_tray=True)
        if tray_objects.exists():
            for tray in tray_objects:
                if hasattr(tray, 'tray_capacity') and tray.tray_capacity and tray.tray_capacity > 0:
                    print(f"✅ Found tray_capacity from TrayId: {tray.tray_capacity}")
                    return JsonResponse({
                        'success': True, 
                        'tray_capacity': tray.tray_capacity,
                        'source': 'TrayId.tray_capacity'
                    })
        
        # ✅ METHOD 4: Debug - Show all available data
        print(f"❌ Could not find tray capacity. Debug info:")
        if total_stock:
            print(f"   - TotalStockModel exists: batch_id = {getattr(total_stock.batch_id, 'batch_id', 'None') if total_stock.batch_id else 'None'}")
            if total_stock.batch_id:
                print(f"   - ModelMasterCreation tray_capacity = {getattr(total_stock.batch_id, 'tray_capacity', 'None')}")
        
        # Show available ModelMasterCreation records
        all_mmc = ModelMasterCreation.objects.filter(lot_id=lot_id)
        print(f"   - ModelMasterCreation count for lot_id {lot_id}: {all_mmc.count()}")
        for mmc in all_mmc:
            print(f"     - batch_id: {mmc.batch_id}, tray_capacity: {getattr(mmc, 'tray_capacity', 'None')}")
                
        return JsonResponse({
            'success': False, 
            'error': f'No tray capacity found for lot_id: {lot_id}',
            'debug_info': {
                'lot_id': lot_id,
                'total_stock_exists': bool(total_stock),
                'model_creation_count': all_mmc.count()
            }
        })
        
    except Exception as e:
        print(f"❌ [brass_get_tray_capacity_for_lot] Error: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})
    
@method_decorator(csrf_exempt, name='dispatch')
class NADeleteBatchAPIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            stock_lot_id = data.get('lot_id')
            print(f"🔍 [NADeleteBatchAPIView] Deleting stock lot with ID: {stock_lot_id}")
            if not stock_lot_id:
                return JsonResponse({'success': False, 'error': 'Missing stock_lot_id'}, status=400)
            obj = JigUnloadAfterTable.objects.filter(lot_id=stock_lot_id).first()
            if not obj:
                return JsonResponse({'success': False, 'error': 'Stock lot not found'}, status=404)
            obj.delete()
            return JsonResponse({'success': True, 'message': 'Stock lot deleted'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class NA_Accepted_form(APIView):

    def post(self, request, format=None):
        print("STEP 1: Received POST request for NA_Accepted_form")
        data = request.data
        lot_id = data.get("stock_lot_id")
        print(f"STEP 2: Extracted lot_id = {lot_id}")

        try:
            total_stock_data = JigUnloadAfterTable.objects.get(lot_id=lot_id)
            print("STEP 3: Fetched JigUnloadAfterTable record")

            total_stock_data.na_qc_accptance = True

            physical_qty = total_stock_data.na_physical_qty

            total_stock_data.na_qc_accepted_qty = physical_qty

            total_stock_data.send_to_nickel_brass = False

            total_stock_data.next_process_module = "Nickel Audit"
            total_stock_data.last_process_module = "Nickel Audit"

            total_stock_data.na_last_process_date_time = timezone.now()

            total_stock_data.save()

            # ✅ Create Spider_TrayId records from Nickel_AuditTrayId for this lot_id
            nickel_trays = Nickel_AuditTrayId.objects.filter(lot_id=lot_id)
            created_count = 0
            for tray in nickel_trays:
                spider_tray, created = Spider_TrayId.objects.get_or_create(
                    tray_id=tray.tray_id,
                    lot_id=tray.lot_id,
                    defaults={
                        'tray_quantity': tray.tray_quantity,
                        'batch_id': tray.batch_id,
                        'date': tray.date,
                        'user': tray.user,
                        'top_tray': tray.top_tray,
                        'delink_tray': tray.delink_tray,
                        'delink_tray_qty': tray.delink_tray_qty,
                        'IP_tray_verified': tray.IP_tray_verified,
                        'rejected_tray': tray.rejected_tray,
                        'new_tray': tray.new_tray,
                        'tray_type': tray.tray_type,
                        'tray_capacity': tray.tray_capacity,
                    }
                )
                if created:
                    created_count += 1
                    print(f"✅ Created Spider_TrayId for tray_id: {tray.tray_id}")
                else:
                    print(f"ℹ️ Spider_TrayId already exists for tray_id: {tray.tray_id}")

            print(f"STEP 11: Created {created_count} Spider_TrayId records from Nickel_AuditTrayId for lot_id: {lot_id}")

            return Response({"success": True})

        except JigUnloadAfterTable.DoesNotExist:
            print("ERROR: JigUnloadAfterTable record not found for lot_id:", lot_id)
            return Response(
                {"success": False, "error": "Stock not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print("ERROR: Unexpected exception:", str(e))
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class NABatchRejectionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            batch_id = data.get('batch_id')
            lot_id = data.get('lot_id')
            total_qty = data.get('total_qty', 0)
            lot_rejected_comment = data.get('lot_rejected_comment', '').strip()

            if not lot_id:
                return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
            if not lot_rejected_comment:
                return Response({'success': False, 'error': 'Lot rejection remarks are required for batch rejection'}, status=400)

            # Find JigUnloadAfterTable record
            jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if not jig_unload_record:
                return Response({'success': False, 'error': 'Unload record not found'}, status=404)

            qty = jig_unload_record.na_physical_qty or jig_unload_record.total_case_qty or 0

            # Set rejection status
            jig_unload_record.na_qc_rejection = True
            jig_unload_record.last_process_module = "Nickel Audit"
            jig_unload_record.next_process_module = "Nickel Wiping"
            jig_unload_record.na_last_process_date_time = timezone.now()
            jig_unload_record.save(update_fields=[
                'na_qc_rejection', 'last_process_module', 'next_process_module', 'na_last_process_date_time'
            ])

            # Update trays as rejected
            updated_trays_count = Nickel_AuditTrayId.objects.filter(lot_id=lot_id).update(rejected_tray=True)

            # Create rejection reason store
            Nickel_Audit_Rejection_ReasonStore.objects.create(
                lot_id=lot_id,
                user=request.user,
                total_rejection_quantity=qty,
                batch_rejection=True,
                lot_rejected_comment=lot_rejected_comment
            )

            # ✅ Create new JigUnloadAfterTable instance for next process
            
            def generate_new_lot_id():
                import uuid, datetime
                return f"NAUDIT-{uuid.uuid4().hex[:8]}-{datetime.datetime.now().strftime('%d%m%Y%H%M%S')}"
            
            new_lot_id = generate_new_lot_id()
            
            # Only use fields that exist in your model!
            new_jig_unload = JigUnloadAfterTable.objects.create(
                lot_id=new_lot_id,
                unload_lot_id=new_lot_id,
                total_case_qty=qty,  # Use your calculated qty
                version=jig_unload_record.version,
                category=jig_unload_record.category,
                tray_type=jig_unload_record.tray_type,
                tray_capacity=jig_unload_record.tray_capacity,
                polish_finish=jig_unload_record.polish_finish,
                plating_color=jig_unload_record.plating_color,
                plating_stk_no=jig_unload_record.plating_stk_no,
                polish_stk_no=jig_unload_record.polish_stk_no,
                combine_lot_ids=jig_unload_record.combine_lot_ids,
                created_at=timezone.now(),
                last_process_module="Nickel Audit",
                next_process_module="Nickel Wiping",
                send_to_nickel_brass=False,
                na_last_process_date_time=timezone.now(),
                selected_user=request.user,
                plating_stk_no_list=jig_unload_record.plating_stk_no_list,
                polish_stk_no_list=jig_unload_record.polish_stk_no_list,
                version_list=jig_unload_record.version_list,
            )
            new_jig_unload.location.set(jig_unload_record.location.all())

            print(f"✅ Created new JigUnloadAfterTable for next process: {new_lot_id}")
            print(f"✅ Created new JigUnloadAfterTable for next process: {new_lot_id}")

            # Copy rejected trays to new JigUnloadAfterTable lot
            rejected_trays = Nickel_AuditTrayId.objects.filter(lot_id=lot_id, rejected_tray=True)
            for tray in rejected_trays:
                NickelQcTrayId.objects.create(
                    tray_id=tray.tray_id,
                    lot_id=new_lot_id,
                    tray_quantity=tray.tray_quantity,
                    tray_capacity=tray.tray_capacity,
                    tray_type=tray.tray_type,
                    rejected_tray=False,
                    IP_tray_verified=True,
                    new_tray=False,
                    user=request.user,
                    date=timezone.now()
                )

            return Response({'success': True, 'message': 'Batch rejection saved with remarks.'})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class NATrayRejectionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')  # Could be original lot_id or unload_lot_id
            batch_id = data.get('batch_id')  # May not be used anymore
            tray_rejections = data.get('tray_rejections', [])  # List of {reason_id, qty, tray_id}

            if not lot_id or not tray_rejections:
                return Response({'success': False, 'error': 'Missing lot_id or tray_rejections'}, status=400)

            # 🔥 NEW LOGIC: Find JigUnloadAfterTable record
            jig_unload_record = None
            unload_lot_id = None
            original_lot_ids = []


            # Method 1: Try to find by direct lot_id match (if lot_id is already unload_lot_id)
            jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            
            if jig_unload_record:
                unload_lot_id = str(jig_unload_record.lot_id)
                original_lot_ids = jig_unload_record.combine_lot_ids or []
            else:
                # Method 2: Try to find by combine_lot_ids (if lot_id is original lot_id)
                
                jig_unload_records = JigUnloadAfterTable.objects.filter(
                    combine_lot_ids__isnull=False
                ).exclude(combine_lot_ids__exact=[])
                
                for record in jig_unload_records:
                    if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                        if lot_id in record.combine_lot_ids:
                            jig_unload_record = record
                            unload_lot_id = str(record.lot_id)
                            original_lot_ids = record.combine_lot_ids
                            break

            if not jig_unload_record:
                print(f"❌ [NATrayRejectionAPIView] No JigUnloadAfterTable record found for lot_id: {lot_id}")
                return Response({
                    'success': False, 
                    'error': f'No unload record found for lot_id: {lot_id}. This lot may not have been unloaded yet.'
                }, status=404)

            # Use na_physical_qty from JigUnloadAfterTable instead of TotalStockModel
            available_qty = jig_unload_record.na_physical_qty or 0
            print(f"🔍 [NATrayRejectionAPIView] Available quantity from JigUnloadAfterTable: {available_qty}")
            
            # Validate total rejection quantity
            running_total = 0
            for idx, item in enumerate(tray_rejections):
                qty = int(item.get('qty', 0))
                running_total += qty
                if running_total > available_qty:
                    return Response({
                        'success': False,
                        'error': f'Quantity exceeds available ({available_qty}).'
                    }, status=400)

            # ✅ Process each tray rejection INDIVIDUALLY with detailed logging
            total_qty = 0
            saved_rejections = []
            reason_ids_used = set()  # Track unique reason IDs for summary
            
            print(f"🔍 [NATrayRejectionAPIView] Processing {len(tray_rejections)} individual tray rejections...")
            
            # ✅ Process each rejection individually (no grouping)
            for idx, item in enumerate(tray_rejections):
                tray_id = item.get('tray_id', '').strip()
                reason_id = item.get('reason_id', '').strip()
                qty = int(item.get('qty', 0))
                
                print(f"🔍 [NATrayRejectionAPIView] Processing rejection {idx + 1}:")
                print(f"   - Tray ID: '{tray_id}'")
                print(f"   - Reason ID: '{reason_id}'")
                print(f"   - Quantity: {qty}")
                
                if qty <= 0:
                    print(f"   ⚠️ Skipping - zero or negative quantity")
                    continue
                    
                if not tray_id or not reason_id:
                    print(f"   ⚠️ Skipping - missing tray_id or reason_id")
                    continue
                
                try:
                    reason_obj = Nickel_Audit_Rejection_Table.objects.get(rejection_reason_id=reason_id)
                    print(f"   ✅ Found rejection reason: {reason_obj.rejection_reason}")
                    
                    # ✅ CREATE INDIVIDUAL RECORD FOR EACH TRAY + REASON COMBINATION
                    # Use unload_lot_id for consistency
                    rejection_record = Nickel_Audit_Rejected_TrayScan.objects.create(
                        lot_id=unload_lot_id,  # Use unload_lot_id
                        rejected_tray_quantity=qty,  # Individual tray quantity
                        rejection_reason=reason_obj,
                        user=request.user,
                        rejected_tray_id=tray_id  # Individual tray ID
                    )
                    
                    saved_rejections.append({
                        'record_id': rejection_record.id,
                        'tray_id': tray_id,
                        'qty': qty,
                        'reason': reason_obj.rejection_reason,
                        'reason_id': reason_id
                    })
                    
                    total_qty += qty
                    reason_ids_used.add(reason_id)
                    
                    print(f"   ✅ SAVED rejection record ID {rejection_record.id}: tray_id={tray_id}, qty={qty}, reason={reason_obj.rejection_reason}")
                    
                except Nickel_Audit_Rejection_Table.DoesNotExist:
                    print(f"   ❌ Rejection reason {reason_id} not found")
                    return Response({
                        'success': False,
                        'error': f'Rejection reason {reason_id} not found'
                    }, status=400)
                except Exception as e:
                    print(f"   ❌ Error creating rejection record: {e}")
                    return Response({
                        'success': False,
                        'error': f'Error creating rejection record: {str(e)}'
                    }, status=500)

            if not saved_rejections:
                return Response({
                    'success': False,
                    'error': 'No valid rejections were processed'
                }, status=400)

            # ✅ Create ONE summary record for the lot (with all unique rejection reasons)
            if reason_ids_used:
                reasons = Nickel_Audit_Rejection_Table.objects.filter(rejection_reason_id__in=list(reason_ids_used))
                
                # Use unload_lot_id for consistency
                reason_store = Nickel_Audit_Rejection_ReasonStore.objects.create(
                    lot_id=unload_lot_id,  # Use unload_lot_id
                    user=request.user,
                    total_rejection_quantity=total_qty,
                    batch_rejection=False
                )
                reason_store.rejection_reason.set(reasons)
                
                print(f"✅ [NATrayRejectionAPIView] Created summary record: total_qty={total_qty}, reasons={len(reasons)}")

            # ✅ Update TrayId records for ALL individual tray IDs (using unload_lot_id)
            unique_tray_ids = list(set([item['tray_id'] for item in saved_rejections]))
            updated_tray_count = 0
            
            print(f"🔍 [NATrayRejectionAPIView] Updating TrayId records for {len(unique_tray_ids)} unique trays: {unique_tray_ids}")
            
            for tray_id in unique_tray_ids:
                # 🔥 UPDATE: Look for tray in JigUnload_TrayId first (using unload_lot_id)
                jig_tray_obj = JigUnload_TrayId.objects.filter(
                    tray_id=tray_id, 
                    lot_id=unload_lot_id
                ).first()
                
                # Also check regular TrayId table
                tray_obj = TrayId.objects.filter(tray_id=tray_id).first()
                
                if jig_tray_obj or tray_obj:
                    tray_total_qty = sum([item['qty'] for item in saved_rejections if item['tray_id'] == tray_id])
                    print(f"🔍 [NATrayRejectionAPIView] Updating tray {tray_id}: total_qty={tray_total_qty}")
                    
                    # Update regular TrayId if exists
                    if tray_obj:
                        is_new_tray = getattr(tray_obj, 'new_tray', False)
                        if is_new_tray:
                            # For original lot_ids, use the first one or main lot_id
                            main_original_lot_id = original_lot_ids[0] if original_lot_ids else lot_id
                            tray_obj.lot_id = main_original_lot_id
                            tray_obj.rejected_tray = True
                            tray_obj.top_tray = False
                            tray_obj.tray_quantity = tray_total_qty
                            tray_obj.save(update_fields=['lot_id', 'rejected_tray', 'top_tray', 'tray_quantity'])
                            print(f"✅ [NATrayRejectionAPIView] Updated NEW TrayId {tray_id}: lot_id={main_original_lot_id}")
                        else:
                            tray_obj.rejected_tray = True
                            tray_obj.top_tray = False
                            tray_obj.tray_quantity = tray_total_qty
                            tray_obj.save(update_fields=['rejected_tray', 'top_tray', 'tray_quantity'])
                            print(f"✅ [NATrayRejectionAPIView] Updated EXISTING TrayId {tray_id}")

                    # 🔥 NEW: Update/Create Nickel_AuditTrayId (replaces BrassTrayId)
                    nickel_audit_tray_obj = Nickel_AuditTrayId.objects.filter(
                        tray_id=tray_id, 
                        lot_id=unload_lot_id
                    ).first()
                    
                    if nickel_audit_tray_obj:
                        # Update existing NickelQcTrayId
                        nickel_audit_tray_obj.tray_quantity = tray_total_qty
                        nickel_audit_tray_obj.rejected_tray = True
                        nickel_audit_tray_obj.top_tray = False
                        nickel_audit_tray_obj.save(update_fields=['tray_quantity', 'rejected_tray', 'top_tray'])
                        print(f"✅ [NATrayRejectionAPIView] Updated Nickel_AuditTrayId for tray {tray_id}: tray_quantity={tray_total_qty}, rejected_tray=True")
                    else:
                        # Create new Nickel_AuditTrayId record
                        Nickel_AuditTrayId.objects.create(
                            tray_id=tray_id,
                            lot_id=unload_lot_id,  # Use unload_lot_id
                            tray_quantity=tray_total_qty,
                            rejected_tray=True,
                            top_tray=False,
                            tray_type=getattr(tray_obj, 'tray_type', None) if tray_obj else None,
                            tray_capacity=getattr(tray_obj, 'tray_capacity', None) if tray_obj else None,
                            IP_tray_verified=False,
                            new_tray=getattr(tray_obj, 'new_tray', False) if tray_obj else False,
                            delink_tray=False,
                            user=request.user if hasattr(request, 'user') else None,
                            date=timezone.now()
                        )
                        print(f"➕ [NATrayRejectionAPIView] Created new NickelQcTrayId for tray_id={tray_id}, tray_quantity={tray_total_qty}")
            
                    updated_tray_count += 1
                else:
                    print(f"⚠️ [NATrayRejectionAPIView] Tray {tray_id} not found in any tray table")
            
            print(f"✅ [NATrayRejectionAPIView] Updated {updated_tray_count} tray IDs as rejected")

            # 🔥 UPDATE: Update status in JigUnloadAfterTable instead of TotalStockModel
            if total_qty >= available_qty:
                # All pieces rejected: Check if delink is needed
                print("🔍 All pieces rejected - checking for delink requirements...")
                
                # Check if delink trays are needed
                delink_needed = self.check_delink_required(unload_lot_id, available_qty)
                print(f"🔍 Delink needed: {delink_needed}")
                
                if delink_needed:
                    # All rejected + delink needed = Keep on hold for delink scanning
                    jig_unload_record.na_qc_rejection = True
                    jig_unload_record.na_onhold_picking = True  # Keep on hold
                    jig_unload_record.na_qc_few_cases_accptance = False
                    jig_unload_record.send_brass_audit_to_qc = False
                    print("✅ All pieces rejected + delink needed: na_qc_rejection=True, na_onhold_picking=True")
                    update_fields = ['na_qc_rejection', 'na_onhold_picking', 'na_qc_few_cases_accptance', 'nq_last_process_date_time', 'send_brass_audit_to_qc']
                else:
                    # All rejected + no delink = Complete rejection (remove from pick table)
                    jig_unload_record.na_qc_rejection = True
                    jig_unload_record.na_onhold_picking = False  # Remove from pick table
                    jig_unload_record.na_qc_few_cases_accptance = False
                    jig_unload_record.send_brass_audit_to_qc = False
                    print("✅ All pieces rejected + no delink: na_qc_rejection=True, na_onhold_picking=False")
                    update_fields = ['na_qc_rejection', 'na_onhold_picking', 'na_qc_few_cases_accptance', 'nq_last_process_date_time', 'send_brass_audit_to_qc']
            else:
                # Partial rejection logic
                jig_unload_record.na_onhold_picking = True
                jig_unload_record.na_qc_few_cases_accptance = True
                jig_unload_record.na_qc_rejection = False
                print("✅ Partial rejection: na_qc_few_cases_accptance=True, na_onhold_picking=True")
                update_fields = ['na_qc_few_cases_accptance', 'na_onhold_picking', 'na_qc_rejection', 'nq_last_process_date_time']
            
            jig_unload_record.na_qc_accepted_qty = available_qty - total_qty
            jig_unload_record.na_last_process_date_time = timezone.now()
            update_fields.append('na_qc_accepted_qty')
            update_fields.append('na_last_process_date_time')
            
            jig_unload_record.save(update_fields=update_fields)
            print(f"✅ [NATrayRejectionAPIView] Updated JigUnloadAfterTable record ID {jig_unload_record.id}")
            
            print(f"🔍 [NATrayRejectionAPIView] === TRAY REJECTION END ===")            
            # After processing all tray rejections and updating JigUnloadAfterTable status

            def generate_new_lot_id():
                import uuid, datetime
                return f"NAUDIT-{uuid.uuid4().hex[:8]}-{datetime.datetime.now().strftime('%d%m%Y%H%M%S')}"
            
            new_lot_id = generate_new_lot_id()
            
            new_jig_unload = JigUnloadAfterTable.objects.create(
                lot_id=new_lot_id,
                unload_lot_id=new_lot_id,
                total_case_qty=total_qty,  # Use the remaining available qty after rejection
                version=jig_unload_record.version,
                category=jig_unload_record.category,
                tray_type=jig_unload_record.tray_type,
                tray_capacity=jig_unload_record.tray_capacity,
                polish_finish=jig_unload_record.polish_finish,
                plating_color=jig_unload_record.plating_color,
                plating_stk_no=jig_unload_record.plating_stk_no,
                polish_stk_no=jig_unload_record.polish_stk_no,
                combine_lot_ids=jig_unload_record.combine_lot_ids,
                created_at=timezone.now(),
                last_process_module="Nickel Audit",
                next_process_module="Nickel Wiping",
                send_to_nickel_brass=False,
                na_last_process_date_time=timezone.now(),
                selected_user=request.user,
                plating_stk_no_list=jig_unload_record.plating_stk_no_list,
                polish_stk_no_list=jig_unload_record.polish_stk_no_list,
                version_list=jig_unload_record.version_list,
            )
            new_jig_unload.location.set(jig_unload_record.location.all())

            print(f"✅ Created new JigUnloadAfterTable for next process: {new_lot_id}")

            # ✅ Copy rejected trays to new JigUnloadAfterTable lot
            rejected_trays = Nickel_AuditTrayId.objects.filter(lot_id=lot_id, rejected_tray=True)
            for tray in rejected_trays:
                NickelQcTrayId.objects.create(
                    tray_id=tray.tray_id,
                    lot_id=new_lot_id,
                    tray_quantity=tray.tray_quantity,
                    tray_capacity=tray.tray_capacity,
                    tray_type=tray.tray_type,
                    rejected_tray=False,
                    IP_tray_verified=True,
                    new_tray=False,
                    user=request.user,
                    date=timezone.now()
                )
            
            # ✅ Return detailed information about what was saved
            return Response({
                'success': True, 
                'message': f'Tray rejections saved: {len(saved_rejections)} individual records created for {len(unique_tray_ids)} trays.',
                'saved_rejections': saved_rejections,
                'total_qty': total_qty,
                'total_records': len(saved_rejections),
                'unique_tray_ids': unique_tray_ids,
                'updated_tray_count': updated_tray_count,
                'unload_lot_id': unload_lot_id,
                'original_lot_ids': original_lot_ids,
                'available_qty': available_qty,
                'accepted_qty': available_qty - total_qty
            })

        except json.JSONDecodeError as e:
            print(f"❌ [NATrayRejectionAPIView] JSON Decode Error: {e}")
            return Response({'success': False, 'error': 'Invalid JSON data'}, status=400)
        except Exception as e:
            print(f"❌ [NATrayRejectionAPIView] Unexpected Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)
        
    def check_delink_required(self, unload_lot_id, available_qty):
        """
        🔥 UPDATED: Check if delink trays are required after all rejections
        Now works with JigUnloadAfterTable and unload_lot_id
        """
        try:
            print(f"🔍 [check_delink_required] Checking for unload_lot_id: {unload_lot_id}")
            
            # Get the JigUnloadAfterTable record
            jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=unload_lot_id).first()
            if not jig_unload_record:
                print(f"❌ [check_delink_required] No JigUnloadAfterTable record found for unload_lot_id: {unload_lot_id}")
                return False
            
            # Get original distribution using unload_lot_id
            original_distribution = get_nickel_qc_actual_tray_distribution_for_delink(unload_lot_id, jig_unload_record)
            print(f"🔍 [check_delink_required] Original distribution: {original_distribution}")
            
            if not original_distribution:
                print(f"ℹ️ [check_delink_required] No original distribution - no delink needed")
                return False
            
            # Calculate current distribution after rejections using unload_lot_id
            current_distribution = nickel_qc_calculate_distribution_after_rejections_enhanced(unload_lot_id, original_distribution)
            print(f"🔍 [check_delink_required] Current distribution: {current_distribution}")
            
            # Check for empty trays (quantity = 0)
            empty_trays = [qty for qty in current_distribution if qty == 0]
            empty_tray_count = len(empty_trays)
            
            print(f"🔍 [check_delink_required] Empty trays found: {empty_tray_count}")
            
            # Delink is needed if there are empty trays
            delink_needed = empty_tray_count > 0
            print(f"🔍 [check_delink_required] Final result: delink_needed = {delink_needed}")
            
            return delink_needed
            
        except Exception as e:
            print(f"❌ [check_delink_required] Error: {e}")
            import traceback
            traceback.print_exc()
            return False  # Default to no delink needed on error      



@require_GET
def nickel_qc_reject_check_tray_id(request):
    """
    🔥 UPDATED: Check if tray_id exists and is valid for nickel QC rejection
    Works with JigUnloadAfterTable and unload_lot_id
    """
    tray_id = request.GET.get('tray_id', '').strip()
    lot_id = request.GET.get('lot_id', '').strip()  # Could be original or unload_lot_id
    
    print(f"🔍 [Nickel QC] Checking tray_id={tray_id}, lot_id={lot_id}")
    
    if not tray_id:
        return JsonResponse({'exists': False, 'error': 'Tray ID is required'})
    
    try:
        # 🔥 NEW: Find the unload_lot_id from JigUnloadAfterTable
        jig_unload_record = None
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        jig_unload_record = record
                        unload_lot_id = str(record.lot_id)
                        break
        
        if not unload_lot_id:
            return JsonResponse({
                'exists': False,
                'error': 'No unload record found for this lot',
                'status_message': 'Lot Not Unloaded'
            })
        
        print(f"🔍 [Nickel QC] Using unload_lot_id: {unload_lot_id}")
        
        # Get the tray object if it exists
        tray_obj = TrayId.objects.filter(tray_id=tray_id).first()
        
        if not tray_obj:
            return JsonResponse({
                'exists': False,
                'error': 'Tray ID not found',
                'status_message': 'Not Found'
            })

        # ✅ CHECK 1: For new trays without lot_id, show "New Tray Available"
        is_new_tray = getattr(tray_obj, 'new_tray', False) or not tray_obj.lot_id or tray_obj.lot_id == '' or tray_obj.lot_id is None
        
        if is_new_tray:
            return JsonResponse({
                'exists': True,
                'status_message': 'New Tray Available',
                'validation_type': 'new_tray'
            })

        # ✅ CHECK 2: For existing trays, must belong to same unload_lot_id
        if tray_obj.lot_id:
            if str(tray_obj.lot_id).strip() != str(unload_lot_id).strip():
                return JsonResponse({
                    'exists': False,
                    'error': 'Different lot',
                    'status_message': 'Different Lot'
                })

        # ✅ CHECK 3: Must NOT be already rejected
        if hasattr(tray_obj, 'rejected_tray') and tray_obj.rejected_tray:
            return JsonResponse({
                'exists': False,
                'error': 'Already rejected',
                'status_message': 'Already Rejected'
            })

        # ✅ CHECK 4: Must NOT be in Nickel_Audit_Rejected_TrayScan for this unload_lot_id
        already_rejected_in_nickel_qc = Nickel_Audit_Rejected_TrayScan.objects.filter(
            lot_id=unload_lot_id,
            rejected_tray_id=tray_id
        ).exists()
        
        if already_rejected_in_nickel_qc:
            return JsonResponse({
                'exists': False,
                'error': 'Already rejected in Nickel QC',
                'status_message': 'Already Rejected'
            })

        # ✅ SUCCESS: Tray is valid for nickel QC rejection
        return JsonResponse({
            'exists': True,
            'status_message': 'Available (can rearrange)',
            'validation_type': 'existing_valid',
            'tray_quantity': getattr(tray_obj, 'tray_quantity', 0) or 0,
            'unload_lot_id': unload_lot_id
        })
        
    except Exception as e:
        print(f"❌ [Nickel QC] Error: {e}")
        return JsonResponse({
            'exists': False,
            'error': 'System error',
            'status_message': 'System Error'
        })


@require_GET
def nickel_qc_reject_check_tray_id_simple(request):
    """
    🔥 UPDATED: Enhanced tray validation for Nickel QC rejections with NickelQcTrayId priority
    Works with JigUnloadAfterTable and unload_lot_id
    """
    tray_id = request.GET.get('tray_id', '')
    current_lot_id = request.GET.get('lot_id', '')
    rejection_qty = int(request.GET.get('rejection_qty', 0))
    
    print(f"🔍 [Nickel QC Simple] tray_id: {tray_id}, lot_id: {current_lot_id}, qty: {rejection_qty}")

    try:
        # 🔥 NEW: Find the unload_lot_id from JigUnloadAfterTable
        jig_unload_record = None
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=current_lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if current_lot_id in record.combine_lot_ids:
                        jig_unload_record = record
                        unload_lot_id = str(record.lot_id)
                        break
        
        if not jig_unload_record:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'No unload record found',
                'status_message': 'Lot Not Unloaded'
            })

        # Print overall qty from JigUnloadAfterTable
        overall_qty = jig_unload_record.total_case_qty or 0
        print(f"🔍 [Nickel QC Simple] Overall total_case_qty for unload_lot_id {unload_lot_id}: {overall_qty}")

        # ✅ STEP 1: First check Nickel_AuditTrayId table for this specific unload_lot_id
        nickel_qc_tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=tray_id, lot_id=unload_lot_id).first()
        
        if nickel_qc_tray_obj:
            print(f"🔍 [Nickel QC Simple] Found in Nickel_AuditTrayId for unload_lot_id {unload_lot_id}")
            
            # Check if already rejected
            if nickel_qc_tray_obj.rejected_tray:
                return JsonResponse({
                    'exists': False,
                    'valid_for_rejection': False,
                    'error': 'Already rejected in Nickel QC',
                    'status_message': 'Already Rejected'
                })
            
            # Validate tray capacity and rearrangement logic for existing tray
            tray_qty = nickel_qc_tray_obj.tray_quantity or 0
            tray_capacity = nickel_qc_tray_obj.tray_capacity or 0
            remaining_in_tray = tray_qty - rejection_qty

            # If some pieces will remain, check if they can fit in other trays
            if remaining_in_tray > 0:
                other_trays = Nickel_AuditTrayId.objects.filter(
                    lot_id=unload_lot_id,
                    tray_quantity__gt=0,
                    rejected_tray=False
                ).exclude(tray_id=tray_id)
                
                available_space_in_other_trays = 0
                for t in other_trays:
                    current_qty = t.tray_quantity or 0
                    max_capacity = t.tray_capacity or tray_capacity
                    available_space_in_other_trays += max(0, max_capacity - current_qty)
                
                if remaining_in_tray > available_space_in_other_trays:
                    return JsonResponse({
                        'exists': False,
                        'valid_for_rejection': False,
                        'error': f'Cannot reject: {remaining_in_tray} pieces will remain but only {available_space_in_other_trays} space available in other trays',
                        'status_message': 'Need New Tray'
                    })
            
            # Validation passed for existing tray
            return JsonResponse({
                'exists': True,
                'valid_for_rejection': True,
                'status_message': 'Available (Can Rearrange)',
                'validation_type': 'existing_tray_in_nickel_qc',
                'tray_capacity': tray_capacity,
                'current_quantity': tray_qty,
                'remaining_after_rejection': remaining_in_tray,
                'unload_lot_id': unload_lot_id
            })
        
        # ✅ STEP 2: Not found in NickelQcTrayId, check TrayId for new tray availability
        print(f"🔍 [Nickel QC Simple] Not found in NickelQcTrayId, checking TrayId for new tray")
        
        tray_obj = TrayId.objects.filter(tray_id=tray_id).first()
        
        if not tray_obj:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Tray ID not found in system',
                'status_message': 'Tray Not Found'
            })
        
        # ✅ Check if tray is already rejected in JigUnload_TrayId
        jig_unload_tray_obj = JigUnload_TrayId.objects.filter(tray_id=tray_id, lot_id=unload_lot_id).first()
        if jig_unload_tray_obj and getattr(jig_unload_tray_obj, 'rejected_tray', False):
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Already rejected in Jig Unloading',
                'status_message': 'Already Rejected in JU'
            })
        
        # ✅ Check if tray belongs to a different lot
        if tray_obj.lot_id and str(tray_obj.lot_id).strip():
            if str(tray_obj.lot_id).strip() != str(unload_lot_id).strip():
                return JsonResponse({
                    'exists': False,
                    'valid_for_rejection': False,
                    'error': 'Tray belongs to different lot',
                    'status_message': 'Different Lot',
                    'debug_info': {
                        'tray_lot_id': str(tray_obj.lot_id).strip(),
                        'expected_unload_lot_id': str(unload_lot_id).strip()
                    }
                })
            
            # Same lot but check if rejected
            if tray_obj.rejected_tray:
                return JsonResponse({
                    'exists': False,
                    'valid_for_rejection': False,
                    'error': 'Already rejected',
                    'status_message': 'Already Rejected'
                })
        
        # ✅ Validate tray capacity compatibility
        tray_capacity_validation = validate_nickel_qc_tray_capacity_compatibility(tray_obj, unload_lot_id)
        if not tray_capacity_validation['is_compatible']:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': tray_capacity_validation['error'],
                'status_message': 'Wrong Tray Type',
                'tray_capacity_mismatch': True,
                'scanned_tray_capacity': tray_capacity_validation['scanned_tray_capacity'],
                'expected_tray_capacity': tray_capacity_validation['expected_tray_capacity']
            })
        
        # ✅ Check if it's a new tray (no lot_id or empty lot_id)
        is_new_tray = (not tray_obj.lot_id or str(tray_obj.lot_id).strip() == '')
        
        print(f"🔍 [Nickel QC Simple] TrayId analysis:")
        print(f"  - lot_id: '{tray_obj.lot_id}'")
        print(f"  - is_new_tray (lot_id None or empty): {is_new_tray}")
        
        if is_new_tray:
            return JsonResponse({
                'exists': True,
                'valid_for_rejection': True,
                'status_message': 'New Tray Available',
                'validation_type': 'new_tray_from_master',
                'tray_capacity_compatible': True,
                'tray_capacity': tray_obj.tray_capacity or tray_capacity_validation['expected_tray_capacity'],
                'unload_lot_id': unload_lot_id
            })
        
        # ✅ If we reach here, tray exists in TrayId with same unload_lot_id but not in NickelQcTrayId
        return JsonResponse({
            'exists': True,
            'valid_for_rejection': True,
            'status_message': 'Available (from TrayId)',
            'validation_type': 'existing_tray_from_master',
            'tray_capacity_compatible': True,
            'tray_capacity': tray_obj.tray_capacity,
            'unload_lot_id': unload_lot_id
        })

    except Exception as e:
        print(f"❌ [Nickel QC Simple] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'exists': False,
            'valid_for_rejection': False,
            'error': 'System error',
            'status_message': 'System Error'
        })


def validate_nickel_qc_tray_capacity_compatibility(tray_obj, unload_lot_id):
    """
    🔥 UPDATED: Validate tray capacity compatibility for Nickel QC using JigUnloadAfterTable
    """
    try:
        # Get the scanned tray's capacity
        scanned_tray_capacity = getattr(tray_obj, 'tray_capacity', None)
        
        if not scanned_tray_capacity:
            # If tray doesn't have capacity info, try to get from batch
            if hasattr(tray_obj, 'batch_id') and tray_obj.batch_id:
                batch_capacity = getattr(tray_obj.batch_id, 'tray_capacity', None)
                if batch_capacity:
                    scanned_tray_capacity = batch_capacity
        
        print(f"🔍 [Nickel QC Capacity] Scanned tray capacity: {scanned_tray_capacity}")
        
        # Get the expected tray capacity for the unload_lot_id
        expected_tray_capacity = get_expected_tray_capacity_for_nickel_qc_lot(unload_lot_id)
        print(f"🔍 [Nickel QC Capacity] Expected tray capacity for unload_lot_id {unload_lot_id}: {expected_tray_capacity}")
        
        # If we can't determine either capacity, allow it (fallback)
        if not scanned_tray_capacity or not expected_tray_capacity:
            print(f"🔍 [Nickel QC Capacity] Missing capacity info - allowing as fallback")
            return {
                'is_compatible': True,
                'scanned_tray_capacity': scanned_tray_capacity or 'Unknown',
                'expected_tray_capacity': expected_tray_capacity or 'Unknown'
            }
        
        # Compare tray capacities
        is_compatible = int(scanned_tray_capacity) == int(expected_tray_capacity)
        
        if is_compatible:
            print(f"✅ [Nickel QC Capacity] Compatible: {scanned_tray_capacity} matches {expected_tray_capacity}")
            return {
                'is_compatible': True,
                'scanned_tray_capacity': scanned_tray_capacity,
                'expected_tray_capacity': expected_tray_capacity
            }
        else:
            print(f"❌ [Nickel QC Capacity] Incompatible: {scanned_tray_capacity} ≠ {expected_tray_capacity}")
            return {
                'is_compatible': False,
                'error': f'Wrong Tray Type: Scanned tray capacity {scanned_tray_capacity}, but lot requires capacity {expected_tray_capacity}',
                'status_message': f'Wrong Tray Type',
                'scanned_tray_capacity': scanned_tray_capacity,
                'expected_tray_capacity': expected_tray_capacity
            }
            
    except Exception as e:
        print(f"❌ [Nickel QC Capacity] Error: {e}")
        import traceback
        traceback.print_exc()
        # On error, allow the tray (fallback behavior)
        return {
            'is_compatible': True,
            'scanned_tray_capacity': 'Unknown',
            'expected_tray_capacity': 'Unknown',
            'error': f'Validation error: {str(e)}'
        }


def get_expected_tray_capacity_for_nickel_qc_lot(unload_lot_id):
    """
    🔥 UPDATED: Get expected tray capacity for Nickel QC using JigUnloadAfterTable
    """
    try:
        # Method 1: Get from JigUnloadAfterTable
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=unload_lot_id).first()
        if jig_unload_record:
            # Try to get capacity info from related records
            # Check if there are tray records with capacity info
            tray_records = JigUnload_TrayId.objects.filter(lot_id=unload_lot_id).first()
            if tray_records:
                # Get capacity from TrayId table
                tray_obj = TrayId.objects.filter(tray_id=tray_records.tray_id).first()
                if tray_obj and tray_obj.tray_capacity:
                    print(f"🔍 [Expected Nickel QC Capacity] Found from JigUnload_TrayId: {tray_obj.tray_capacity}")
                    return tray_obj.tray_capacity
        
        # Method 2: Get from existing Nickel_AuditTrayId records for this unload_lot_id
        existing_tray = Nickel_AuditTrayId.objects.filter(
            lot_id=unload_lot_id, 
            rejected_tray=False,
            tray_capacity__isnull=False
        ).first()
        if existing_tray and existing_tray.tray_capacity:
            print(f"🔍 [Expected Nickel QC Capacity] Found from existing Nickel_AuditTrayId: {existing_tray.tray_capacity}")
            return existing_tray.tray_capacity
        
        # Method 3: Try to get from original lot_ids in combine_lot_ids
        if jig_unload_record and jig_unload_record.combine_lot_ids:
            for original_lot_id in jig_unload_record.combine_lot_ids:
                # Check BrassTrayId for backward compatibility
                brass_tray = Nickel_AuditTrayId.objects.filter(lot_id=original_lot_id).first()
                if brass_tray and brass_tray.tray_capacity:
                    print(f"🔍 [Expected Nickel QC Capacity] Found from original lot BrassTrayId: {brass_tray.tray_capacity}")
                    return brass_tray.tray_capacity
        
        print(f"🔍 [Expected Nickel QC Capacity] Could not determine expected tray capacity for unload_lot_id {unload_lot_id}")
        return None
        
    except Exception as e:
        print(f"❌ [Expected Nickel QC Capacity] Error: {e}")
        return None


def get_nickel_qc_available_quantities_with_session_allocations(unload_lot_id, current_session_allocations):
    """
    🔥 UPDATED: Calculate available tray quantities for Nickel QC using JigUnloadAfterTable
    """
    try:
        # Get original distribution and track free space separately
        original_distribution = get_nickel_qc_original_tray_distribution(unload_lot_id)
        original_capacities = get_nickel_qc_tray_capacities_for_lot(unload_lot_id)
        
        available_quantities = original_distribution.copy()
        new_tray_usage_count = 0  # Track NEW tray usage for free space calculation
        
        print(f"🔍 [Nickel QC Session] Starting with: {available_quantities}")
        
        # First, apply saved rejections
        saved_rejections = Nickel_Audit_Rejected_TrayScan.objects.filter(lot_id=unload_lot_id).order_by('id')
        
        for rejection in saved_rejections:
            rejected_qty = rejection.rejected_tray_quantity or 0
            tray_id = rejection.rejected_tray_id
            
            if rejected_qty <= 0:
                continue
                
            if tray_id and is_new_tray_by_id(tray_id):
                # NEW tray creates actual free space
                new_tray_usage_count += 1
                available_quantities = nickel_qc_reduce_quantities_optimally(available_quantities, rejected_qty, is_new_tray=True)
                print(f"🔍 [Nickel QC Session] NEW tray saved rejection: freed up {rejected_qty} space")
            else:
                # EXISTING tray just consumes available quantities
                available_quantities = nickel_qc_reduce_quantities_optimally(available_quantities, rejected_qty, is_new_tray=False)
                print(f"🔍 [Nickel QC Session] EXISTING tray saved rejection: removed tray")
        
        # Then, apply current session allocations
        for allocation in current_session_allocations:
            try:
                reason_text = allocation.get('reason_text', '')
                qty = int(allocation.get('qty', 0))
                tray_ids = allocation.get('tray_ids', [])
                
                if qty <= 0:
                    continue
                
                # Check if NEW tray was used by looking at tray_ids
                is_new_tray_used = False
                if tray_ids:
                    for tray_id in tray_ids:
                        if tray_id and is_new_tray_by_id(tray_id):
                            is_new_tray_used = True
                            break
                
                if is_new_tray_used:
                    new_tray_usage_count += 1
                    available_quantities = nickel_qc_reduce_quantities_optimally(available_quantities, qty, is_new_tray=True)
                    print(f"🔍 [Nickel QC Session] NEW tray session: freed up {qty} space using tray {tray_ids}")
                else:
                    available_quantities = nickel_qc_reduce_quantities_optimally(available_quantities, qty, is_new_tray=False)
                    print(f"🔍 [Nickel QC Session] EXISTING tray session: removed tray")
            except Exception as e:
                print(f"❌ [Nickel QC Session] Error processing allocation: {e}")
                continue
        
        # Calculate ACTUAL current free space
        actual_free_space = 0
        if len(available_quantities) <= len(original_capacities):
            for i, qty in enumerate(available_quantities):
                if i < len(original_capacities):
                    capacity = original_capacities[i]
                    actual_free_space += max(0, capacity - qty)
        
        # Calculate totals
        total_available = sum(available_quantities)
        total_capacity = sum(original_capacities[:len(available_quantities)])
        
        print(f"🔍 [Nickel QC Session] FINAL:")
        print(f"  Available quantities: {available_quantities}")
        print(f"  Total available: {total_available}")
        print(f"  Total capacity of current trays: {total_capacity}")
        print(f"  ACTUAL free space in current trays: {actual_free_space}")
        print(f"  NEW tray usage count: {new_tray_usage_count}")
        
        return available_quantities, actual_free_space
        
    except Exception as e:
        print(f"❌ [Nickel QC Session] Error: {e}")
        return get_nickel_qc_original_tray_distribution(unload_lot_id), 0


def nickel_qc_reduce_quantities_optimally(available_quantities, qty_to_reduce, is_new_tray=True):
    """
    🔥 UPDATED: Reduce quantities optimally for Nickel QC
    """
    quantities = available_quantities.copy()
    remaining = qty_to_reduce

    if is_new_tray:
        # NEW tray usage should FREE UP space from existing trays
        print(f"🔍 [nickel_qc_reduce_quantities] NEW tray: freeing up {qty_to_reduce} space")
        
        # Free up space from smallest trays first (to create empty trays)
        sorted_indices = sorted(range(len(quantities)), key=lambda i: quantities[i])
        for i in sorted_indices:
            if remaining <= 0:
                break
            current_qty = quantities[i]
            if current_qty >= remaining:
                quantities[i] = current_qty - remaining
                print(f"  Freed {remaining} from tray {i}, new qty: {quantities[i]}")
                remaining = 0
            elif current_qty > 0:
                remaining -= current_qty
                print(f"  Freed entire tray {i}: {current_qty}")
                quantities[i] = 0
        
        return quantities
    else:
        # EXISTING tray should consume rejection quantity precisely
        total_available = sum(quantities)
        if total_available < qty_to_reduce:
            print(f"🔍 [nickel_qc_reduce_quantities] EXISTING tray: insufficient quantity ({total_available} < {qty_to_reduce})")
            return quantities
        
        print(f"🔍 [nickel_qc_reduce_quantities] EXISTING tray: consuming {qty_to_reduce} pieces")
        
        # Consume from trays optimally to minimize fragmentation
        temp_quantities = quantities.copy()
        remaining_to_consume = qty_to_reduce
        
        # Try to consume from larger trays first to minimize fragmentation
        sorted_indices = sorted(range(len(temp_quantities)), key=lambda i: temp_quantities[i], reverse=True)
        
        for i in sorted_indices:
            if remaining_to_consume <= 0:
                break
            current_qty = temp_quantities[i]
            if current_qty > 0:
                consume_from_this_tray = min(remaining_to_consume, current_qty)
                temp_quantities[i] -= consume_from_this_tray
                remaining_to_consume -= consume_from_this_tray
                print(f"  Consumed {consume_from_this_tray} from tray {i}, new qty: {temp_quantities[i]}")
                
                if remaining_to_consume == 0:
                    break
        
        print(f"  Final quantities after consumption: {temp_quantities}")
        return temp_quantities


def get_nickel_qc_original_tray_distribution(unload_lot_id):
    """
    🔥 UPDATED: Get original tray quantity distribution for Nickel QC using JigUnloadAfterTable
    """
    try:
        print(f"🔍 [Nickel QC Distribution] Getting distribution for unload_lot_id: {unload_lot_id}")
        
        # First try to get from Nickel_AuditTrayId records
        tray_objects = Nickel_AuditTrayId.objects.filter(lot_id=unload_lot_id).exclude(
            rejected_tray=True
        ).order_by('date')

        print(f"🔍 [Nickel QC Distribution] Found {tray_objects.count()} valid Nickel_AuditTrayId objects")
        
        if tray_objects.exists():
            quantities = []
            for tray in tray_objects:
                tray_qty = getattr(tray, 'tray_quantity', None)
                rejected_tray = getattr(tray, 'rejected_tray', False)
                
                print(f"🔍 [Nickel QC Distribution] Tray {tray.tray_id}: quantity = {tray_qty}, rejected = {rejected_tray}")
                
                if not rejected_tray and tray_qty and tray_qty > 0:
                    quantities.append(tray_qty)
                else:
                    print(f"🔍 [Nickel QC Distribution] SKIPPED tray {tray.tray_id} - rejected or zero quantity")
            
            if quantities:
                print(f"🔍 [Nickel QC Distribution] From NickelQcTrayId objects: {quantities}")
                return quantities
        
        # Fallback: Get from JigUnloadAfterTable
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=unload_lot_id).first()
        if not jig_unload_record:
            print(f"❌ [Nickel QC Distribution] No JigUnloadAfterTable found for unload_lot_id: {unload_lot_id}")
            return []
        
        total_qty = jig_unload_record.total_case_qty or 0
        tray_capacity = get_nickel_qc_tray_capacity_for_lot(unload_lot_id)
        
        print(f"🔍 [Nickel QC Distribution] Fallback calculation - total_qty: {total_qty}, tray_capacity: {tray_capacity}")
        
        if not total_qty or not tray_capacity:
            return []
        
        # Calculate distribution: remainder first, then full trays
        remainder = total_qty % tray_capacity
        full_trays = total_qty // tray_capacity
        
        distribution = []
        if remainder > 0:
            distribution.append(remainder)
        
        for _ in range(full_trays):
            distribution.append(tray_capacity)
        
        print(f"🔍 [Nickel QC Distribution] Calculated: {distribution} (total: {total_qty}, capacity: {tray_capacity})")
        return distribution
        
    except Exception as e:
        print(f"❌ [Nickel QC Distribution] Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_nickel_qc_tray_capacities_for_lot(unload_lot_id):
    """
    🔥 UPDATED: Get all tray capacities for Nickel QC using unload_lot_id
    """
    try:
        print(f"🔍 [get_nickel_qc_tray_capacities] Getting all capacities for unload_lot_id: {unload_lot_id}")
        
        # Get from NickelQcTrayId table
        tray_objects = NickelQcTrayId.objects.filter(lot_id=unload_lot_id).exclude(
            rejected_tray=True
        ).order_by('date')
        
        capacities = []
        for tray in tray_objects:
            capacity = getattr(tray, 'tray_capacity', None)
            if capacity and capacity > 0:
                capacities.append(capacity)
            else:
                # Fallback to standard capacity if not set
                standard_capacity = get_nickel_qc_tray_capacity_for_lot(unload_lot_id)
                capacities.append(standard_capacity)
                
        print(f"🔍 [get_nickel_qc_tray_capacities] Capacities: {capacities}")
        return capacities
        
    except Exception as e:
        print(f"❌ [get_nickel_qc_tray_capacities] Error: {e}")
        return []


def get_nickel_qc_tray_capacity_for_lot(unload_lot_id):
    """
    🔥 UPDATED: Get tray capacity for Nickel QC using unload_lot_id
    """
    try:
        print(f"🔍 [get_nickel_qc_tray_capacity] Getting capacity for unload_lot_id: {unload_lot_id}")
        
        # Method 1: Get from Nickel_AuditTrayId table
        tray_objects = Nickel_AuditTrayId.objects.filter(lot_id=unload_lot_id).exclude(rejected_tray=True)

        if tray_objects.exists():
            first_tray = tray_objects.first()
            tray_capacity = getattr(first_tray, 'tray_capacity', None)
            
            if tray_capacity and tray_capacity > 0:
                print(f"🔍 [get_nickel_qc_tray_capacity] Found from Nickel_AuditTrayId: {tray_capacity}")
                return tray_capacity
                
            # Check all trays for a valid capacity
            for tray in tray_objects:
                capacity = getattr(tray, 'tray_capacity', None)
                if capacity and capacity > 0:
                    print(f"🔍 [get_nickel_qc_tray_capacity] Found valid capacity: {capacity}")
                    return capacity
        
        # Method 2: Get from JigUnload_TrayId
        jig_tray_objects = JigUnload_TrayId.objects.filter(lot_id=unload_lot_id)
        if jig_tray_objects.exists():
            for jig_tray in jig_tray_objects:
                # Get from related TrayId
                tray_obj = TrayId.objects.filter(tray_id=jig_tray.tray_id).first()
                if tray_obj and tray_obj.tray_capacity:
                    print(f"🔍 [get_nickel_qc_tray_capacity] Found from JigUnload_TrayId: {tray_obj.tray_capacity}")
                    return tray_obj.tray_capacity
        
        # Method 3: Get from JigUnloadAfterTable original lot_ids
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=unload_lot_id).first()
        if jig_unload_record and jig_unload_record.combine_lot_ids:
            for original_lot_id in jig_unload_record.combine_lot_ids:
                brass_tray = Nickel_AuditTrayId.objects.filter(lot_id=original_lot_id).first()
                if brass_tray and brass_tray.tray_capacity:
                    print(f"🔍 [get_nickel_qc_tray_capacity] Found from original lot: {brass_tray.tray_capacity}")
                    return brass_tray.tray_capacity
                
        print(f"🔍 [get_nickel_qc_tray_capacity] Using default capacity: 12")
        return 12  # Final fallback
        
    except Exception as e:
        print(f"❌ [get_nickel_qc_tray_capacity] Error: {e}")
        import traceback
        traceback.print_exc()
        return 12


def nickel_qc_calculate_distribution_after_rejections_enhanced(unload_lot_id, original_distribution):
    """
    🔥 UPDATED: Enhanced calculation for Nickel QC using unload_lot_id
    """
    current_distribution = original_distribution.copy()
    
    # Get all rejections for this unload_lot_id ordered by creation
    rejections = Nickel_Audit_Rejected_TrayScan.objects.filter(lot_id=unload_lot_id).order_by('id')
    
    print(f"🔧 [Nickel QC Enhanced Distribution] Starting with: {original_distribution}")
    print(f"🔧 [Nickel QC Enhanced Distribution] Processing {rejections.count()} rejections for unload_lot_id {unload_lot_id}")
    
    for idx, rejection in enumerate(rejections):
        rejected_qty = int(rejection.rejected_tray_quantity) if rejection.rejected_tray_quantity else 0
        tray_id = rejection.rejected_tray_id
        reason = rejection.rejection_reason.rejection_reason if rejection.rejection_reason else 'Unknown'
        
        if rejected_qty <= 0:
            continue
        
        print(f"🔧 [Nickel QC Enhanced Distribution] Rejection {idx + 1}:")
        print(f"   - Reason: {reason}")
        print(f"   - Qty: {rejected_qty}")
        print(f"   - Tray ID: '{tray_id}'")
        print(f"   - Before: {current_distribution}")
        
        # Handle SHORTAGE rejections properly
        if not tray_id or tray_id.strip() == '':
            # SHORTAGE rejection - consume from existing trays
            print(f"   - SHORTAGE rejection detected")
            current_distribution = nickel_qc_consume_shortage_from_distribution(current_distribution, rejected_qty)
            print(f"   - After SHORTAGE: {current_distribution}")
            continue
        
        # Check if NEW tray was used for non-SHORTAGE rejections
        is_new_tray = is_new_tray_by_id(tray_id)
        print(f"   - is_new_tray_by_id('{tray_id}') = {is_new_tray}")
        
        if is_new_tray:
            # NEW tray creates empty trays by freeing up space
            print(f"   - NEW tray used - freeing up {rejected_qty} space in existing trays")
            current_distribution = nickel_qc_free_up_space_optimally(current_distribution, rejected_qty)
            print(f"   - After NEW tray free-up: {current_distribution}")
        else:
            # EXISTING tray removes entire tray from distribution
            print(f"   - EXISTING tray used - removing tray from distribution")
            current_distribution = nickel_qc_remove_rejected_tray_from_distribution(current_distribution, rejected_qty)
            print(f"   - After EXISTING tray removal: {current_distribution}")
    
    print(f"🔧 [Nickel QC Enhanced Distribution] FINAL distribution: {current_distribution}")
    
    # Analyze empty trays
    empty_positions = [i for i, qty in enumerate(current_distribution) if qty == 0]
    print(f"🔧 [Nickel QC Enhanced Distribution] Empty positions: {empty_positions}")
    
    return current_distribution

def is_new_tray_by_id(tray_id):
    """
    Returns True ONLY if the tray_id refers to a tray that has no lot_id assigned (lot_id is None or empty)
    AND tray_type is NB (Normal Brass) or JB (Jumbo Brass) as required for reject tray scanning.
    """
    tray_obj = TrayId.objects.filter(tray_id=tray_id).first()
    if tray_obj:
        # Only allow if lot_id is None or empty string
        has_no_lot = not tray_obj.lot_id or str(tray_obj.lot_id).strip() == ''
        # Enforce NB or JB tray type for reject tray scan (SRS requirement)
        is_valid_type = str(tray_obj.tray_type or '').strip().upper() in ('NB', 'JB')
        return has_no_lot and is_valid_type
    return False


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nickel_qc_get_delink_tray_data(request):
    """
    🔥 UPDATED: Get delink tray data for Nickel QC using JigUnloadAfterTable
    """
    try:
        lot_id = request.GET.get('lot_id')  # Could be original or unload_lot_id
        if not lot_id:
            return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
        
        print(f"🔍 [nickel_qc_get_delink_tray_data] Processing lot_id: {lot_id}")
        
        # Find the JigUnloadAfterTable record
        jig_unload_record = None
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        jig_unload_record = record
                        unload_lot_id = str(record.lot_id)
                        break
        
        if not jig_unload_record:
            return Response({'success': False, 'error': 'Unload record not found'}, status=400)
        
        print(f"🔍 [nickel_qc_get_delink_tray_data] Using unload_lot_id: {unload_lot_id}")
        
        # Get actual tray distribution for this unload_lot_id
        original_distribution = get_nickel_qc_actual_tray_distribution_for_delink(unload_lot_id, jig_unload_record)
        print(f"🔍 [nickel_qc_get_delink_tray_data] Original distribution: {original_distribution}")
        
        if not original_distribution:
            print("❌ [nickel_qc_get_delink_tray_data] No original distribution found")
            return Response({
                'success': True,
                'delink_trays': [],
                'message': 'No tray distribution found'
            })
        
        # Check if there are any rejections first
        rejections = Nickel_Audit_Rejected_TrayScan.objects.filter(lot_id=unload_lot_id)
        if not rejections.exists():
            print("ℹ️ [nickel_qc_get_delink_tray_data] No rejections found - no delink needed")
            return Response({
                'success': True,
                'delink_trays': [],
                'message': 'No rejections found - no delink needed'
            })
        
        print(f"🔍 [nickel_qc_get_delink_tray_data] Found {rejections.count()} rejections")
        
        # Calculate current distribution after all rejections
        current_distribution = nickel_qc_calculate_distribution_after_rejections_enhanced(unload_lot_id, original_distribution)
        print(f"🔍 [nickel_qc_get_delink_tray_data] Current distribution after rejections: {current_distribution}")
        
        # Find empty trays that need delink scanning
        delink_trays = []
        empty_tray_positions = []
        
        for i, qty in enumerate(current_distribution):
            if qty == 0:
                original_capacity = original_distribution[i] if i < len(original_distribution) else 0
                
                if original_capacity > 0:
                    delink_trays.append({
                        'tray_number': i + 1,
                        'original_capacity': original_capacity,
                        'current_qty': 0,
                        'needs_delink': True
                    })
                    empty_tray_positions.append(i + 1)
                    print(f"✅ [nickel_qc_get_delink_tray_data] Empty tray found: position {i+1}, original capacity: {original_capacity}")
        
        print(f"🔍 [nickel_qc_get_delink_tray_data] Empty tray positions: {empty_tray_positions}")
        print(f"🔍 [nickel_qc_get_delink_tray_data] Total empty trays needing delink: {len(delink_trays)}")
        
        if len(delink_trays) == 0:
            print("ℹ️ [nickel_qc_get_delink_tray_data] No empty trays found - no delink needed")
            return Response({
                'success': True,
                'delink_trays': [],
                'message': 'No empty trays found - no delink needed',
                'original_distribution': original_distribution,
                'current_distribution': current_distribution
            })
        
        return Response({
            'success': True,
            'delink_trays': delink_trays,
            'original_distribution': original_distribution,
            'current_distribution': current_distribution,
            'total_empty_trays': len(delink_trays),
            'empty_positions': empty_tray_positions,
            'rejection_count': rejections.count(),
            'has_delink_needed': True,
            'unload_lot_id': unload_lot_id
        })
        
    except Exception as e:
        print(f"❌ [nickel_qc_get_delink_tray_data] Error: {e}")
        import traceback
        traceback.print_exc()
        return Response({'success': False, 'error': str(e)}, status=500)


def get_nickel_qc_actual_tray_distribution_for_delink(unload_lot_id, jig_unload_record):
    """
    🔥 UPDATED: Get actual tray distribution for delink using JigUnloadAfterTable
    """
    try:
        print(f"🔍 [get_nickel_qc_actual_tray_distribution_for_delink] Getting distribution for unload_lot_id: {unload_lot_id}")
        
        # Use total_case_qty from JigUnloadAfterTable
        total_qty = jig_unload_record.total_case_qty or 0
        tray_capacity = get_nickel_qc_tray_capacity_for_lot(unload_lot_id)
        
        print(f"🔍 Total qty: {total_qty}, Tray capacity: {tray_capacity}")
        
        if not total_qty or not tray_capacity:
            return []
        
        # Calculate distribution: remainder first, then full trays
        remainder = total_qty % tray_capacity
        full_trays = total_qty // tray_capacity
        
        distribution = []
        if remainder > 0:
            distribution.append(remainder)
        
        for _ in range(full_trays):
            distribution.append(tray_capacity)
        
        print(f"✅ Calculated distribution: {distribution}")
        print(f"   Total: {total_qty}, Capacity: {tray_capacity}")
        print(f"   Remainder: {remainder}, Full trays: {full_trays}")
        
        return distribution
        
    except Exception as e:
        print(f"❌ Error calculating distribution: {e}")
        return []


# Helper functions for distribution calculations (updated for Nickel QC)
def nickel_qc_consume_shortage_from_distribution(distribution, shortage_qty):
    """
    🔥 UPDATED: Handle SHORTAGE rejections for Nickel QC
    """
    result = distribution.copy()
    remaining_shortage = shortage_qty
    
    print(f"   SHORTAGE: consuming {shortage_qty} from distribution {distribution}")
    
    # Consume from smallest trays first (to create empty trays for delink)
    sorted_indices = sorted(range(len(result)), key=lambda i: result[i])
    
    for i in sorted_indices:
        if remaining_shortage <= 0:
            break
            
        current_qty = result[i]
        if current_qty >= remaining_shortage:
            result[i] -= remaining_shortage
            print(f"   Consumed {remaining_shortage} from tray {i}, remaining: {result[i]}")
            remaining_shortage = 0
        elif current_qty > 0:
            remaining_shortage -= current_qty
            print(f"   Consumed all {current_qty} from tray {i}")
            result[i] = 0
    
    if remaining_shortage > 0:
        print(f"   ⚠️ WARNING: Could not consume all shortage qty, remaining: {remaining_shortage}")
    
    print(f"   SHORTAGE result: {result}")
    return result


def nickel_qc_remove_rejected_tray_from_distribution(distribution, rejected_qty):
    """
    🔥 UPDATED: Remove rejected tray from distribution for Nickel QC
    """
    result = distribution.copy()
    total_available = sum(result)
    
    if total_available < rejected_qty:
        return result
    
    # Try to find exact match first
    for i, qty in enumerate(result):
        if qty == rejected_qty:
            del result[i]
            print(f"   Removed tray {i} with exact matching qty {rejected_qty}")
            return result
    
    # No exact match - consume rejected_qty and remove one tray
    remaining_to_consume = rejected_qty
    
    # Consume the rejection quantity from available trays
    for i in range(len(result)):
        if remaining_to_consume <= 0:
            break
        current_qty = result[i]
        consume_from_this_tray = min(remaining_to_consume, current_qty)
        result[i] -= consume_from_this_tray
        remaining_to_consume -= consume_from_this_tray
    
    # Remove one tray entirely (prefer empty ones first)
    for i in range(len(result)):
        if result[i] == 0:
            del result[i]
            print(f"   Removed empty tray at position {i}")
            return result
    
    # If no empty tray, remove the smallest quantity tray
    if result:
        min_qty = min(result)
        for i in range(len(result)):
            if result[i] == min_qty:
                del result[i]
                print(f"   Removed tray {i} with smallest qty {min_qty}")
                return result
    
    return result


def nickel_qc_free_up_space_optimally(distribution, qty_to_free):
    """
    🔥 UPDATED: Free up space optimally for Nickel QC
    """
    result = distribution.copy()
    remaining = qty_to_free
    
    print(f"   🔧 [Nickel QC Free Up Space] Input: {distribution}, qty_to_free: {qty_to_free}")
    
    # Free from smallest trays first (to maximize empty trays for delink)
    sorted_indices = sorted(range(len(result)), key=lambda i: result[i])
    print(f"   🔧 [Nickel QC Free Up Space] Processing order (smallest first): {sorted_indices}")
    
    for i in sorted_indices:
        if remaining <= 0:
            break
        current_qty = result[i]
        if current_qty >= remaining:
            result[i] = current_qty - remaining
            print(f"   🔧 [Nickel QC Free Up Space] Freed {remaining} from tray {i+1}, new qty: {result[i]}")
            remaining = 0
        elif current_qty > 0:
            remaining -= current_qty
            print(f"   🔧 [Nickel QC Free Up Space] Freed entire tray {i+1}: {current_qty} -> 0")
            result[i] = 0
    
    empty_trays_created = [i+1 for i, qty in enumerate(result) if qty == 0]
    print(f"   🔧 [Nickel QC Free Up Space] Result: {result}")
    print(f"   🔧 [Nickel QC Free Up Space] Empty trays created: {empty_trays_created}")
    
    return result
@require_GET
def nickel_delink_check_tray_id(request):
    """
    🔥 UPDATED: Validate tray ID for delink process in Nickel QC
    """
    tray_id = request.GET.get('tray_id', '')
    current_lot_id = request.GET.get('lot_id', '')
    
    try:
        if not tray_id:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Tray ID is required',
                'status_message': 'Required'
            })
        
        # 🔥 NEW: Find the unload_lot_id
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=current_lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if current_lot_id in record.combine_lot_ids:
                        unload_lot_id = str(record.lot_id)
                        break

        if not unload_lot_id:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Unload record not found',
                'status_message': 'Lot Not Unloaded'
            })

        # Get the tray object if it exists
        tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=tray_id, lot_id=unload_lot_id).first()

        if not tray_obj:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Tray ID not found in Nickel QC',
                'status_message': 'Not Found'
            })
        
        # Do NOT allow new trays (without lot_id)
        if not tray_obj.lot_id or tray_obj.lot_id == '' or tray_obj.lot_id is None:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'New trays not allowed for delink',
                'status_message': 'New Tray Not Allowed'
            })

        # Must belong to same lot
        if str(tray_obj.lot_id).strip() != str(unload_lot_id).strip():
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Different lot',
                'status_message': 'Different Lot'
            })

        # Must NOT be already rejected
        if hasattr(tray_obj, 'rejected_tray') and tray_obj.rejected_tray:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Already rejected',
                'status_message': 'Already Rejected'
            })

        # Must NOT be in Nickel_Audit_Rejected_TrayScan for this lot
        already_rejected_in_nickel = Nickel_Audit_Rejected_TrayScan.objects.filter(
            lot_id=unload_lot_id,
            rejected_tray_id=tray_id
        ).exists()
        
        if already_rejected_in_nickel:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Already rejected in Nickel QC',
                'status_message': 'Already Rejected'
            })

        # Must NOT be already delinked
        if hasattr(tray_obj, 'delink_tray') and tray_obj.delink_tray:
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Already delinked',
                'status_message': 'Already Delinked'
            })

        # Must be verified (additional validation for delink)
        if not getattr(tray_obj, 'IP_tray_verified', False):
            return JsonResponse({
                'exists': False,
                'valid_for_rejection': False,
                'error': 'Tray not verified',
                'status_message': 'Not Verified'
            })

        # SUCCESS: Tray is valid for delink
        return JsonResponse({
            'exists': True,
            'valid_for_rejection': True,
            'status_message': 'Available for Delink',
            'validation_type': 'existing_valid',
            'tray_quantity': getattr(tray_obj, 'tray_quantity', 0) or 0,
            'unload_lot_id': unload_lot_id
        })
        
    except Exception as e:
        print(f"❌ [nickel_delink_check_tray_id] Error: {e}")
        return JsonResponse({
            'exists': False,
            'valid_for_rejection': False,
            'error': 'System error',
            'status_message': 'System Error'
        })
#=========================================================

# This endpoint retrieves top tray scan data for a given lot_id
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nickel_get_accepted_tray_scan_data(request):
    """
    🔥 UPDATED: Get top tray scan data for Nickel QC using JigUnloadAfterTable
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 🔥 NEW: Find JigUnloadAfterTable record (could be original or unload_lot_id)
        jig_unload_record = None
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        jig_unload_record = record
                        unload_lot_id = str(record.lot_id)
                        break
        
        if not jig_unload_record:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)
        
        # Get model info from original lot_ids for display
        model_no = "Combined Model"
        tray_capacity = get_nickel_qc_tray_capacity_for_lot(unload_lot_id) or 12
        
        if jig_unload_record.combine_lot_ids:
            # Get model info from first original lot
            first_lot_id = jig_unload_record.combine_lot_ids[0]
            total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
            if total_stock and total_stock.model_stock_no:
                model_no = total_stock.model_stock_no.model_no

        # 🔥 UPDATED: Get rejection qty from Nickel QC
        reason_store = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=unload_lot_id).first()
        total_rejection_qty = reason_store.total_rejection_quantity if reason_store else 0

        # Use total_case_qty from JigUnloadAfterTable
        na_physical_qty = jig_unload_record.total_case_qty or 0
        
        if na_physical_qty <= 0:
            return Response({'success': False, 'error': 'No nickel physical quantity available'}, status=400)

        # Calculate available_qty after subtracting rejections
        available_qty = na_physical_qty - total_rejection_qty
        
        print(f"🔍 [nickel_get_accepted_tray_scan_data] na_physical_qty = {na_physical_qty}")
        print(f"🔍 [nickel_get_accepted_tray_scan_data] total_rejection_qty = {total_rejection_qty}")
        print(f"🔍 [nickel_get_accepted_tray_scan_data] available_qty = {available_qty}")

        # Check if this is for delink-only mode
        is_delink_only_case = (available_qty <= 0 and total_rejection_qty > 0)
        
        if is_delink_only_case:
            print(f"🚨 [nickel_get_accepted_tray_scan_data] Delink-only case detected: all pieces rejected")
            return Response({
                'success': True,
                'model_no': model_no,
                'tray_capacity': tray_capacity,
                'na_physical_qty': na_physical_qty,
                'total_rejection_qty': total_rejection_qty,
                'available_qty': 0,
                'top_tray_qty': 0,
                'has_draft': False,
                'draft_tray_id': "",
                'is_delink_only': True,
                'delink_only_reason': 'All pieces rejected - only delink scanning needed',
                'unload_lot_id': unload_lot_id
            })

        if available_qty <= 0:
            return Response({'success': False, 'error': 'No available quantity for acceptance after rejections'}, status=400)

        # Calculate top tray quantity using available_qty after rejections
        full_trays = available_qty // tray_capacity
        top_tray_qty = available_qty % tray_capacity

        # If remainder is 0 and we have quantity, the last tray should be full capacity
        if top_tray_qty == 0 and available_qty > 0:
            top_tray_qty = tray_capacity

        print(f"📊 [nickel_get_accepted_tray_scan_data] Tray calculation: {available_qty} qty = {full_trays} full trays + {top_tray_qty} top tray")

        # Check for existing draft data
        has_draft = Nickel_Audit_TopTray_Draft_Store.objects.filter(lot_id=unload_lot_id).exists()
        draft_tray_id = ""
        
        if has_draft:
            draft_record = Nickel_Audit_TopTray_Draft_Store.objects.filter(lot_id=unload_lot_id).first()
            if draft_record:
                draft_tray_id = draft_record.tray_id or ""
        
        return Response({
            'success': True,
            'model_no': model_no,
            'tray_capacity': tray_capacity,
            'na_physical_qty': na_physical_qty,
            'total_rejection_qty': total_rejection_qty,
            'available_qty': available_qty,
            'top_tray_qty': top_tray_qty,
            'has_draft': has_draft,
            'draft_tray_id': draft_tray_id,
            'is_delink_only': False,
            'unload_lot_id': unload_lot_id,
            'original_lot_id': lot_id
        })
    except Exception as e:
        traceback.print_exc()
        return Response({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def nickel_save_single_top_tray_scan(request):
    """
    🔥 UPDATED: Save single top tray scan for Nickel QC using NickelQcTrayId and JigUnloadAfterTable
    """
    try:
        data = request.data
        lot_id = data.get('lot_id')
        tray_id = data.get('tray_id', '').strip()
        tray_qty = data.get('tray_qty', 0)
        draft_save = data.get('draft_save', False)
        delink_trays = data.get('delink_trays', [])
        user = request.user

        print(f"🔍 [nickel_save_single_top_tray_scan] Received data:")
        print(f"  lot_id: {lot_id}")
        print(f"  tray_id: '{tray_id}'")
        print(f"  tray_qty: {tray_qty}")
        print(f"  draft_save: {draft_save}")
        print(f"  delink_trays: {delink_trays}")

        # Check if this is a "delink-only" case
        is_delink_only = (not tray_id or tray_qty == 0) and delink_trays
        print(f"  is_delink_only: {is_delink_only}")

        if not lot_id:
            return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

        # For non-delink-only cases, require tray_id and tray_qty
        if not is_delink_only and (not tray_id or not tray_qty):
            return Response({
                'success': False, 
                'error': 'Missing tray_id or tray_qty for top tray scanning'
            }, status=400)

        # For delink-only cases, require delink_trays
        if is_delink_only and not delink_trays:
            return Response({
                'success': False, 
                'error': 'Missing delink_trays for delink-only operation'
            }, status=400)

        # 🔥 NEW: Find the unload_lot_id
        jig_unload_record = None
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        jig_unload_record = record
                        unload_lot_id = str(record.lot_id)
                        break

        if not jig_unload_record:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)

        # Prevent same tray ID for delink and top tray (only if top tray exists)
        if tray_id:
            delink_tray_ids = [delink['tray_id'] for delink in delink_trays if delink.get('tray_id')]
            if tray_id in delink_tray_ids:
                return Response({
                    'success': False,
                    'error': 'Top tray and delink tray cannot be the same'
                }, status=400)

        # Validate top tray_id only if provided
        if tray_id:
            top_tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=tray_id, lot_id=unload_lot_id).first()
            if not top_tray_obj:
                return Response({
                    'success': False,
                    'error': f'Top tray ID "{tray_id}" does not exist in Nickel QC.'
                }, status=400)
            
            # Validate top tray belongs to same lot
            if str(top_tray_obj.lot_id) != str(unload_lot_id):
                return Response({
                    'success': False,
                    'error': f'Top tray ID "{tray_id}" does not belong to this lot.'
                }, status=400)
            
            # Validate top tray is not rejected
            if top_tray_obj.rejected_tray:
                return Response({
                    'success': False,
                    'error': f'Top tray ID "{tray_id}" is already rejected.'
                }, status=400)

        # Validate all delink trays (only if not draft and delink_trays exist)
        if not draft_save and delink_trays:
            missing_delink = any(not tray.get('tray_id') for tray in delink_trays)
            if missing_delink:
                return Response({
                    'success': False,
                    'error': 'Please fill all Delink Tray IDs before submitting.'
                }, status=400)
                
            for delink in delink_trays:
                delink_tray_id = delink.get('tray_id', '').strip()
                if delink_tray_id:
                    delink_tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=delink_tray_id, lot_id=unload_lot_id).first()
                    if not delink_tray_obj:
                        return Response({
                            'success': False,
                            'error': f'Delink tray ID "{delink_tray_id}" does not exist in Nickel QC.'
                        }, status=400)
                    
                    if str(delink_tray_obj.lot_id) != str(unload_lot_id):
                        return Response({
                            'success': False,
                            'error': f'Delink tray ID "{delink_tray_id}" does not belong to this lot.'
                        }, status=400)
                    
                    if delink_tray_obj.rejected_tray:
                        return Response({
                            'success': False,
                            'error': f'Delink tray ID "{delink_tray_id}" is already rejected.'
                        }, status=400)

        # Handle Nickel_AuditTrayId table updates only for final submit (not draft)
        delink_count = 0
        if not draft_save:
            # Update top tray only if provided
            if tray_id:
                top_tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=tray_id, lot_id=unload_lot_id).first()
                if top_tray_obj:
                    top_tray_obj.top_tray = True
                    top_tray_obj.tray_quantity = tray_qty
                    top_tray_obj.save(update_fields=['top_tray', 'tray_quantity'])
                    print(f"✅ [nickel_save_single_top_tray_scan] Updated top tray: {tray_id}")
        
                # Update all other trays (except rejected and top tray) to have tray_quantity = tray_capacity
                all_trays_in_lot = Nickel_AuditTrayId.objects.filter(lot_id=unload_lot_id, rejected_tray=False)
                for tray in all_trays_in_lot:
                    if tray.tray_id == tray_id or tray.delink_tray:
                        continue
                    old_qty = tray.tray_quantity
                    tray.tray_quantity = tray.tray_capacity
                    tray.top_tray = False
                    tray.save(update_fields=['tray_quantity', 'top_tray'])
                    print(f"   Updated Nickel_AuditTrayId tray {tray.tray_id}: qty {old_qty}→{tray.tray_capacity}, top_tray=False")

            # Process delink trays (works for both normal and delink-only modes)
            for delink in delink_trays:
                delink_tray_id = delink.get('tray_id', '').strip()
                if delink_tray_id:
                    delink_count += 1
                    
                    # NickelQcTrayId
                    nickel_delink_tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=delink_tray_id, lot_id=unload_lot_id).first()
                    if nickel_delink_tray_obj:
                        nickel_delink_tray_obj.delink_tray = True
                        nickel_delink_tray_obj.lot_id = None
                        nickel_delink_tray_obj.IP_tray_verified = False
                        nickel_delink_tray_obj.top_tray = False
                        nickel_delink_tray_obj.save(update_fields=[
                            'delink_tray', 'lot_id', 'IP_tray_verified', 'top_tray'
                        ])
                        print(f"✅ Delinked NickelQcTrayId tray: {delink_tray_id}")

            # Update JigUnloadAfterTable flags
            if is_delink_only:
                # For delink-only, set appropriate flags
                jig_unload_record.na_accepted_tray_scan_status = True
                jig_unload_record.next_process_module = "IQF"
                jig_unload_record.last_process_module = "Nickel QC"
                jig_unload_record.na_onhold_picking = False
                print(f"✅ Updated JigUnloadAfterTable for DELINK-ONLY mode")
            else:
                # Normal mode
                jig_unload_record.na_accepted_tray_scan_status = True
                jig_unload_record.next_process_module = "IQF"
                jig_unload_record.last_process_module = "Nickel QC"
                jig_unload_record.na_onhold_picking = False
                print(f"✅ Updated JigUnloadAfterTable for NORMAL mode")
            
            jig_unload_record.save(update_fields=[
                'na_accepted_tray_scan_status', 
                'next_process_module', 
                'last_process_module', 
                'na_onhold_picking'
            ])

            # 🔥 NEW: Handle Spider_TrayId creation from Nickel_AuditTrayId
            try:
                # Get all Nickel_AuditTrayId records for this lot where rejected_tray=False and delink_tray=False
                eligible_nickel_trays = Nickel_AuditTrayId.objects.filter(
                    lot_id=unload_lot_id,
                    rejected_tray=False,
                    delink_tray=False
                )
                
                created_spider_trays = 0
                updated_spider_trays = 0
                
                # Get the batch_id (ModelMasterCreation instance) if needed
                try:
                    batch_instance = ModelMasterCreation.objects.filter(lot_id=unload_lot_id).first()
                except:
                    batch_instance = None
                
                for nickel_tray in eligible_nickel_trays:
                    # Check if Spider_TrayId record already exists
                    spider_tray, created = Spider_TrayId.objects.update_or_create(
                        tray_id=nickel_tray.tray_id,
                        lot_id=unload_lot_id,
                        defaults={
                            'tray_quantity': nickel_tray.tray_quantity,
                            'batch_id': batch_instance,
                            'user': user,
                            'top_tray': nickel_tray.top_tray,
                            'delink_tray': nickel_tray.delink_tray,
                            'rejected_tray': nickel_tray.rejected_tray,
                            'IP_tray_verified': getattr(nickel_tray, 'IP_tray_verified', False),
                            'new_tray': True,  # Default as per Spider_TrayId model
                            'tray_type': getattr(nickel_tray, 'tray_type', None),
                            'tray_capacity': getattr(nickel_tray, 'tray_capacity', None),
                        }
                    )
                    
                    if created:
                        created_spider_trays += 1
                        print(f"✅ Created Spider_TrayId record: {nickel_tray.tray_id}")
                    else:
                        updated_spider_trays += 1
                        print(f"🔄 Updated Spider_TrayId record: {nickel_tray.tray_id}")
                
                print(f"📊 Spider_TrayId Summary: {created_spider_trays} created, {updated_spider_trays} updated")
                
            except Exception as e:
                print(f"❌ Error creating Spider_TrayId records: {str(e)}")
                # Log error but continue with success (don't fail the main operation)
                # Uncomment below line if you want Spider_TrayId creation errors to fail the entire operation:
                # return Response({'success': False, 'error': f'Error creating Spider records: {str(e)}'}, status=500)

        # Handle draft save
        if draft_save:
            if not lot_id or (not tray_id and not delink_trays):
                return Response({
                    'success': False, 
                    'error': 'Missing lot_id, and no tray_id or delink trays provided'
                }, status=400)
            
            batch_id = unload_lot_id  # Use unload_lot_id as batch_id
            draft_obj, created = Nickel_Audit_TopTray_Draft_Store.objects.update_or_create(
                lot_id=unload_lot_id,  # Use unload_lot_id
                defaults={
                    'batch_id': batch_id,
                    'user': user,
                    'tray_id': tray_id or '',
                    'tray_qty': tray_qty or 0,
                    'delink_tray_ids': [d['tray_id'] for d in delink_trays if d.get('tray_id')],
                    'delink_trays_data': {
                        "positions": [
                            {
                                "position": idx,
                                "tray_id": d.get('tray_id', ''),
                                "original_capacity": d.get('original_capacity', 0)
                            }
                            for idx, d in enumerate(delink_trays)
                        ]
                    }
                }
            )
            message = 'Nickel Audit draft saved successfully.'
            return Response({
                'success': True,
                'message': message,
                'draft_id': draft_obj.id,
                'top_tray_id': tray_id or '',
                'is_draft': True,
                'is_delink_only': is_delink_only,
                'unload_lot_id': unload_lot_id
            })

        # Success response
        if is_delink_only:
            message = f'Nickel Audit delink operation completed successfully. {delink_count} tray(s) delinked.'
        else:
            message = f'Nickel Audit top tray scan completed successfully.'
            if delink_count > 0:
                message += f' {delink_count} tray(s) delinked.'

        return Response({
            'success': True, 
            'message': message,
            'delink_count': delink_count,
            'top_tray_id': tray_id or '',
            'is_draft': draft_save,
            'is_delink_only': is_delink_only,
            'unload_lot_id': unload_lot_id
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'success': False, 'error': str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nickel_get_top_tray_scan_draft(request):
    """Get top tray scan draft for Nickel QC"""
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 🔥 NEW: Find the unload_lot_id
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        unload_lot_id = str(record.lot_id)
                        break

        if not unload_lot_id:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)

        draft_obj = Nickel_Audit_TopTray_Draft_Store.objects.filter(lot_id=unload_lot_id).first()
        if draft_obj:
            return Response({
                'success': True,
                'has_draft': True,
                'draft_data': {
                    'tray_id': draft_obj.tray_id,
                    'tray_qty': draft_obj.tray_qty,
                    'delink_tray_ids': draft_obj.delink_tray_ids,
                    'delink_trays': draft_obj.delink_trays_data.get('positions', []) if draft_obj.delink_trays_data else [],
                },
                'unload_lot_id': unload_lot_id
            })
        else:
            return Response({
                'success': True, 
                'has_draft': False,
                'unload_lot_id': unload_lot_id
            })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nickel_view_tray_list(request):
    """
    🔥 UPDATED: Returns tray list for Nickel QC using NickelQcTrayId and JigUnloadAfterTable
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)

    try:
        # 🔥 NEW: Find the unload_lot_id
        jig_unload_record = None
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        jig_unload_record = record
                        unload_lot_id = str(record.lot_id)
                        break

        if not jig_unload_record:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)

        # Check if this lot has nq_qc_accptance = True
        nq_qc_accptance = jig_unload_record.nq_qc_accptance or False
        tray_capacity = get_nickel_qc_tray_capacity_for_lot(unload_lot_id) or 12

        tray_list = []

        # Condition 1: If nq_qc_accptance is True, get from Nickel_AuditTrayId table
        if nq_qc_accptance:
            trays = Nickel_AuditTrayId.objects.filter(lot_id=unload_lot_id).order_by('id')
            for idx, tray_obj in enumerate(trays):
                tray_list.append({
                    'sno': idx + 1,
                    'tray_id': tray_obj.tray_id,
                    'tray_qty': tray_obj.tray_quantity,
                })
            
            return Response({
                'success': True,
                'nq_qc_accptance': True,
                'batch_rejection': False,
                'total_rejection_qty': 0,
                'tray_capacity': tray_capacity,
                'trays': tray_list,
                'unload_lot_id': unload_lot_id
            })

        # Condition 2 & 3: Check rejection reason store
        reason_store = Nickel_Audit_Rejection_ReasonStore.objects.filter(lot_id=unload_lot_id).order_by('-id').first()
        batch_rejection = False
        total_rejection_qty = 0
        
        if reason_store:
            batch_rejection = reason_store.batch_rejection
            total_rejection_qty = reason_store.total_rejection_quantity

        if batch_rejection and total_rejection_qty > 0 and tray_capacity > 0:
            # Batch rejection: split total_rejection_qty by tray_capacity, get tray_ids from Nickel_AuditTrayId
            tray_ids = list(Nickel_AuditTrayId.objects.filter(lot_id=unload_lot_id).values_list('tray_id', flat=True))
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
            # Not batch rejection: get from Nickel_Qc_Accepted_TrayID_Store
            trays = Nickel_Audit_Accepted_TrayID_Store.objects.filter(lot_id=unload_lot_id).order_by('id')
            for idx, obj in enumerate(trays):
                tray_list.append({
                    'sno': idx + 1,
                    'tray_id': obj.tray_id,
                    'tray_qty': obj.tray_qty,
                })

        return Response({
            'success': True,
            'nq_qc_accptance': nq_qc_accptance,
            'batch_rejection': batch_rejection,
            'total_rejection_qty': total_rejection_qty,
            'tray_capacity': tray_capacity,
            'trays': tray_list,
            'unload_lot_id': unload_lot_id
        })
        
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class NickelTrayValidateAPIView(APIView):
    """
    🔥 UPDATED: Validate tray for Nickel QC using NickelQcTrayId and JigUnloadAfterTable
    This replaces BrassTrayValidateAPIView for Nickel QC operations
    """
    def post(self, request):
        try:
            # Parse request data
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            
            # Get parameters
            lot_id_input = str(data.get('batch_id', '') or data.get('lot_id', '')).strip()
            tray_id = str(data.get('tray_id', '')).strip()
            
            print("="*50)
            print(f"[NICKEL DEBUG] Raw request data: {data}")
            print(f"[NICKEL DEBUG] Extracted lot_id: '{lot_id_input}' (length: {len(lot_id_input)})")
            print(f"[NICKEL DEBUG] Extracted tray_id: '{tray_id}' (length: {len(tray_id)})")
            
            if not lot_id_input or not tray_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Both lot_id and tray_id are required'
                }, status=400)

            # 🔥 NEW: Find the unload_lot_id from JigUnloadAfterTable
            print(f"[NICKEL DEBUG] Finding unload_lot_id for input lot_id: '{lot_id_input}'")
            
            jig_unload_record = None
            unload_lot_id = None
            original_lot_ids = []
            
            # Method 1: Try direct match first (if lot_id_input is already unload_lot_id)
            jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id_input).first()
            if jig_unload_record:
                unload_lot_id = str(jig_unload_record.lot_id)
                original_lot_ids = jig_unload_record.combine_lot_ids or []
                print(f"[NICKEL DEBUG] Found by direct lot_id match")
                print(f"[NICKEL DEBUG] unload_lot_id: '{unload_lot_id}'")
                print(f"[NICKEL DEBUG] original_lot_ids: {original_lot_ids}")
            else:
                # Method 2: Try searching in combine_lot_ids (if lot_id_input is original lot_id)
                print(f"[NICKEL DEBUG] Not found by direct match, searching in combine_lot_ids...")
                
                jig_unload_records = JigUnloadAfterTable.objects.filter(
                    combine_lot_ids__isnull=False
                ).exclude(combine_lot_ids__exact=[])
                
                for record in jig_unload_records:
                    if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                        if lot_id_input in record.combine_lot_ids:
                            jig_unload_record = record
                            unload_lot_id = str(record.lot_id)
                            original_lot_ids = record.combine_lot_ids
                            print(f"[NICKEL DEBUG] Found in combine_lot_ids")
                            print(f"[NICKEL DEBUG] unload_lot_id: '{unload_lot_id}'")
                            print(f"[NICKEL DEBUG] original_lot_ids: {original_lot_ids}")
                            break

            if not unload_lot_id:
                print(f"[NICKEL DEBUG] No JigUnloadAfterTable record found for lot_id: '{lot_id_input}'")
                return JsonResponse({
                    'success': False, 
                    'error': f'No unload record found for lot_id: {lot_id_input}. This lot may not have been unloaded yet.',
                    'debug_info': {
                        'input_lot_id': lot_id_input,
                        'unload_lot_id': None,
                        'original_lot_ids': [],
                        'error_type': 'unload_record_not_found'
                    }
                }, status=404)

            # Step 2: Check if the tray exists in Nickel_AuditTrayId for this unload_lot_id
            print(f"[NICKEL DEBUG] Checking if tray '{tray_id}' exists in Nickel_AuditTrayId for unload_lot_id: '{unload_lot_id}'")

            tray_exists = Nickel_AuditTrayId.objects.filter(
                lot_id=unload_lot_id,  # Use unload_lot_id
                tray_id=tray_id
            ).exists()

            print(f"[NICKEL DEBUG] Tray exists in Nickel_AuditTrayId: {tray_exists}")

            # Additional debugging: show all trays for this unload_lot_id in Nickel_AuditTrayId
            all_nickel_trays = Nickel_AuditTrayId.objects.filter(
                lot_id=unload_lot_id
            ).values_list('tray_id', flat=True)
            print(f"[NICKEL DEBUG] All trays in Nickel_AuditTrayId for unload_lot_id '{unload_lot_id}': {list(all_nickel_trays)}")

            # Also check if tray exists anywhere in Nickel_AuditTrayId (for debugging)
            tray_anywhere_nickel = Nickel_AuditTrayId.objects.filter(tray_id=tray_id)
            if tray_anywhere_nickel.exists():
                tray_lot_ids_nickel = list(tray_anywhere_nickel.values_list('lot_id', flat=True))
                print(f"[NICKEL DEBUG] Tray '{tray_id}' found in Nickel_AuditTrayId for lot_ids: {tray_lot_ids_nickel}")
            
            # 🔥 ADDITIONAL: Check if tray exists in JigUnload_TrayId (alternative source)
            jig_unload_tray_exists = JigUnload_TrayId.objects.filter(
                lot_id=unload_lot_id,
                tray_id=tray_id
            ).exists()
            print(f"[NICKEL DEBUG] Tray exists in JigUnload_TrayId: {jig_unload_tray_exists}")
            
            # Get additional tray information if it exists
            tray_info = {}
            if tray_exists:
                nickel_tray_obj = Nickel_AuditTrayId.objects.filter(
                    lot_id=unload_lot_id,
                    tray_id=tray_id
                ).first()
                
                if nickel_tray_obj:
                    tray_info = {
                        'tray_quantity': getattr(nickel_tray_obj, 'tray_quantity', 0),
                        'tray_capacity': getattr(nickel_tray_obj, 'tray_capacity', 0),
                        'rejected_tray': getattr(nickel_tray_obj, 'rejected_tray', False),
                        'top_tray': getattr(nickel_tray_obj, 'top_tray', False),
                        'delink_tray': getattr(nickel_tray_obj, 'delink_tray', False),
                        'IP_tray_verified': getattr(nickel_tray_obj, 'IP_tray_verified', False),
                        'new_tray': getattr(nickel_tray_obj, 'new_tray', True)
                    }
            
            print(f"[NICKEL DEBUG] Final result - exists: {tray_exists}")
            print(f"[NICKEL DEBUG] Tray info: {tray_info}")
            print("="*50)
            
            return JsonResponse({
                'success': True, 
                'exists': tray_exists,
                'tray_info': tray_info,
                'debug_info': {
                    'input_lot_id': lot_id_input,
                    'unload_lot_id': unload_lot_id,
                    'original_lot_ids': original_lot_ids,
                    'tray_id_received': tray_id,
                    'all_trays_in_nickel_qc': list(all_nickel_trays),
                    'tray_exists_in_nickel_qc': tray_exists,
                    'tray_exists_in_jig_unload': jig_unload_tray_exists,
                    'data_source': 'Nickel_AuditTrayId',
                    'validation_method': 'unload_lot_id_lookup'
                }
            })
            
        except Exception as e:
            print(f"[NICKEL DEBUG] ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False, 
                'error': str(e),
                'debug_info': {
                    'error_type': 'exception',
                    'error_location': 'NickelTrayValidateAPIView'
                }
            }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nickel_check_accepted_tray_draft(request):
    """Check if draft data exists for accepted tray scan in Nickel QC"""
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 🔥 NEW: Find the unload_lot_id
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        unload_lot_id = str(record.lot_id)
                        break

        if not unload_lot_id:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)

        has_draft = Nickel_Audit_Accepted_TrayID_Store.objects.filter(
            lot_id=unload_lot_id,  # Use unload_lot_id
            is_draft=True
        ).exists()
        
        return Response({
            'success': True,
            'has_draft': has_draft,
            'unload_lot_id': unload_lot_id
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def nickel_save_accepted_tray_scan(request):
    """
    🔥 UPDATED: Save accepted tray scan for Nickel QC using Nickel_AuditTrayId and JigUnloadAfterTable
    """
    try:
        data = request.data
        lot_id = data.get('lot_id')
        rows = data.get('rows', [])
        draft_save = data.get('draft_save', False)
        user = request.user

        if not lot_id or not rows:
            return Response({'success': False, 'error': 'Missing lot_id or rows'}, status=400)

        # 🔥 NEW: Find the unload_lot_id
        jig_unload_record = None
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        jig_unload_record = record
                        unload_lot_id = str(record.lot_id)
                        break

        if not jig_unload_record:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)

        # Validate all tray_ids exist in Nickel_AuditTrayId table
        for idx, row in enumerate(rows):
            tray_id = row.get('tray_id')
            if not tray_id or not Nickel_AuditTrayId.objects.filter(tray_id=tray_id, lot_id=unload_lot_id).exists():
                return Response({
                    'success': False,
                    'error': f'Tray ID "{tray_id}" is not existing in Nickel QC (Row {idx+1}).'
                }, status=400)

        # Remove existing tray IDs for this lot (to avoid duplicates)
        Nickel_Audit_Accepted_TrayID_Store.objects.filter(lot_id=unload_lot_id).delete()

        total_qty = 0
        for row in rows:
            tray_id = row.get('tray_id')
            tray_qty = row.get('tray_qty')
            if not tray_id or tray_qty is None:
                continue
            total_qty += int(tray_qty)
            
            # Create with appropriate boolean flags based on draft_save parameter
            Nickel_Audit_Accepted_TrayID_Store.objects.create(
                lot_id=unload_lot_id,  # Use unload_lot_id
                tray_id=tray_id,
                tray_qty=tray_qty,
                user=user,
                is_draft=draft_save,
                is_save=not draft_save
            )

        # Save/Update Nickel_Audit_Accepted_TrayScan for this lot
        accepted_scan, created = Nickel_Audit_Accepted_TrayScan.objects.get_or_create(
            lot_id=unload_lot_id,  # Use unload_lot_id
            user=user,
            defaults={'accepted_tray_quantity': total_qty}
        )
        if not created:
            accepted_scan.accepted_tray_quantity = total_qty
            accepted_scan.save(update_fields=['accepted_tray_quantity'])

        # Update JigUnloadAfterTable flags only if it's a final save (not draft)
        if not draft_save:
            jig_unload_record.na_accepted_tray_scan_status = True
            jig_unload_record.next_process_module = "IQF"
            jig_unload_record.last_process_module = "Nickel QC"
            jig_unload_record.na_onhold_picking = False
            jig_unload_record.save(update_fields=[
                'na_accepted_tray_scan_status', 
                'next_process_module', 
                'last_process_module', 
                'na_onhold_picking'
            ])

        return Response({'success': True, 'message': 'Nickel accepted tray scan saved.'})

    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@require_GET
def nickel_check_tray_id(request):
    """
    🔥 UPDATED: Check tray ID for Nickel QC using Nickel_AuditTrayId and JigUnloadAfterTable
    """
    tray_id = request.GET.get('tray_id', '')
    lot_id = request.GET.get('lot_id', '')

    # 🔥 NEW: Find the unload_lot_id
    unload_lot_id = None
    
    # Try direct match first
    jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
    if jig_unload_record:
        unload_lot_id = str(jig_unload_record.lot_id)
    else:
        # Try searching in combine_lot_ids
        for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
            if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                if lot_id in record.combine_lot_ids:
                    unload_lot_id = str(record.lot_id)
                    break

    if not unload_lot_id:
        return JsonResponse({
            'exists': False,
            'error': 'Unload record not found'
        })

    # Check if tray exists in Nickel_AuditTrayId table and lot_id must match
    tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=tray_id, lot_id=unload_lot_id).first()
    exists = bool(tray_obj)
    same_lot = exists and str(tray_obj.lot_id) == str(unload_lot_id)

    # Must NOT be rejected in Nickel QC
    already_rejected = False
    if exists and same_lot and unload_lot_id:
        # Check if rejected in Nickel_AuditTrayId
        nickel_qc_rejected = getattr(tray_obj, 'rejected_tray', False)
        
        # Check if rejected in Nickel_Audit_Rejected_TrayScan for this lot
        nickel_qc_scan_rejected = Nickel_Audit_Rejected_TrayScan.objects.filter(
            lot_id=unload_lot_id,
            rejected_tray_id=tray_id
        ).exists()
        
        already_rejected = nickel_qc_rejected or nickel_qc_scan_rejected

    # Only valid if exists, same lot, and not already rejected
    is_valid = exists and same_lot and not already_rejected

    return JsonResponse({
        'exists': is_valid,
        'already_rejected': already_rejected,
        'not_in_same_lot': exists and not same_lot,
        'rejected_in_nickel_qc': exists and getattr(tray_obj, 'rejected_tray', False),
        'unload_lot_id': unload_lot_id
    })



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nickel_get_rejected_tray_scan_data(request):
    """
    🔥 UPDATED: Get rejected tray scan data for Nickel QC
    """
    lot_id = request.GET.get('lot_id')
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 🔥 NEW: Find the unload_lot_id
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        unload_lot_id = str(record.lot_id)
                        break

        if not unload_lot_id:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)

        rows = []
        for obj in Nickel_Audit_Rejected_TrayScan.objects.filter(lot_id=unload_lot_id):
            rows.append({
                'tray_id': obj.rejected_tray_id,
                'qty': obj.rejected_tray_quantity,
                'reason': obj.rejection_reason.rejection_reason,
                'reason_id': obj.rejection_reason.rejection_reason_id,
            })
        return Response({'success': True, 'rows': rows, 'unload_lot_id': unload_lot_id})
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


class NACompletedView(APIView):
    renderer_classes = [TemplateHTMLRenderer]
    template_name = 'Nickel_Audit/NickelAudit_Completed.html'

    def get(self, request):
        from django.utils import timezone
        from datetime import datetime, timedelta
        import pytz

        user = request.user
        
        # ✅ Date filtering logic
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
                from_date = today - timedelta(days=30)
                to_date = today
        else:
            from_date = today - timedelta(days=30)
            to_date = today

        from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
        to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))

        # ✅ CHANGED: Get all plating_color IDs where jig_unload_zone_1 is True
        allowed_color_ids = Plating_Color.objects.filter(
            jig_unload_zone_1=True
        ).values_list('id', flat=True)

        # ✅ CHANGED: Query JigUnloadAfterTable instead of TotalStockModel with zone filtering
        nq_rejection_qty_subquery = Nickel_Audit_Rejection_ReasonStore.objects.filter(
            lot_id=OuterRef('lot_id')
        ).values('total_rejection_quantity')[:1]

        queryset = JigUnloadAfterTable.objects.select_related(
            'version',
            'plating_color',
            'polish_finish'
        ).prefetch_related(
            'location'  # ManyToManyField requires prefetch_related
        ).filter(
            total_case_qty__gt=0,  # Only show records with quantity > 0
            plating_color_id__in=allowed_color_ids,  # ✅ CHANGED: Only show records for zone 1
            na_last_process_date_time__range=(from_datetime, to_datetime)  # ✅ Filter by audit completion date
        ).annotate(
            nq_rejection_qty=nq_rejection_qty_subquery,
        ).filter(
            # ✅ UPDATED: Filter for completed records using JigUnloadAfterTable fields
            Q(na_qc_accptance=True) |
            Q(na_qc_rejection=True) |
            Q(na_qc_few_cases_accptance=True, na_onhold_picking=False)
        ).order_by('-na_last_process_date_time', '-lot_id')

        print(f"📊 Found {queryset.count()} nickel records in date range {from_date} to {to_date}")
        print("All lot_ids in completed queryset:", list(queryset.values_list('lot_id', flat=True)))

        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(queryset, 10)
        page_obj = paginator.get_page(page_number)

        # ✅ UPDATED: Build master_data from JigUnloadAfterTable records
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
                'tray_type': jig_unload_obj.tray_type or '',
                'tray_capacity': jig_unload_obj.tray_capacity or 0,
                'Moved_to_D_Picker': False,  # Not applicable for JigUnloadAfterTable
                'Draft_Saved': False,  # Not applicable for JigUnloadAfterTable
                'na_qc_rejection': jig_unload_obj.na_qc_rejection,
                'na_qc_accptance': jig_unload_obj.na_qc_accptance,

                # ✅ Stock-related fields from JigUnloadAfterTable
                'stock_lot_id': jig_unload_obj.lot_id,
                'last_process_module': jig_unload_obj.last_process_module or 'Jig Unload',
                'next_process_module': 'Nickel Audit',  # Default next process
                'na_ac_accepted_qty_verified': jig_unload_obj.na_ac_accepted_qty_verified,
                'na_qc_accepted_qty': jig_unload_obj.na_qc_accepted_qty or 0,
                'nq_rejection_qty': jig_unload_obj.nq_rejection_qty,
                'na_missing_qty': jig_unload_obj.na_missing_qty or 0,
                'na_physical_qty': jig_unload_obj.na_physical_qty,
                'na_physical_qty_edited': False,
                'rejected_audit_nickle_ip_stock': jig_unload_obj.rejected_audit_nickle_ip_stock,
                'rejected_ip_stock': jig_unload_obj.rejected_audit_nickle_ip_stock,  # Using same field
                'few_cases_accepted_Ip_stock': jig_unload_obj.na_qc_few_cases_accptance,
                'accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,
                'na_pick_remarks': jig_unload_obj.na_pick_remarks,  # Not applicable for nickel
                'na_qc_accptance': jig_unload_obj.na_qc_accptance,
                'na_accepted_tray_scan_status': jig_unload_obj.na_accepted_tray_scan_status,
                'na_qc_rejection': jig_unload_obj.na_qc_rejection,
                'na_qc_few_cases_accptance': jig_unload_obj.na_qc_few_cases_accptance,
                'na_onhold_picking': jig_unload_obj.na_onhold_picking,
                'total_IP_accpeted_quantity': jig_unload_obj.na_physical_qty,
                'na_last_process_date_time': jig_unload_obj.na_last_process_date_time,
                'na_hold_lot': jig_unload_obj.na_hold_lot,

                # Additional fields from JigUnloadAfterTable
                'plating_stk_no': jig_unload_obj.plating_stk_no or '',
                'polishing_stk_no': jig_unload_obj.polish_stk_no or '',
                'category': jig_unload_obj.category or '',
                'combine_lot_ids': jig_unload_obj.combine_lot_ids,  # Show which lots were combined
                'unload_lot_id': jig_unload_obj.unload_lot_id,  # Additional identifier
                
                # Nickel-specific fields
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
                    print(f"🎯 NA Completed View - Extracted model_no: {model_no_prefix} from plating_stk_no: {plating_stk_no}")
                    
                    try:
                        # Find ModelMaster where model_no matches the prefix for images
                        model_master = ModelMaster.objects.filter(
                            model_no__startswith=model_no_prefix
                        ).prefetch_related('images').first()
                        
                        if model_master:
                            print(f"✅ NA Completed View - Found ModelMaster for images: {model_master.model_no}")
                            # Get images from ModelMaster
                            for img in model_master.images.all():
                                if img.master_image:
                                    images.append(img.master_image.url)
                                    print(f"📸 NA Completed View - Added image from ModelMaster: {img.master_image.url}")
                        else:
                            print(f"⚠️ NA Completed View - No ModelMaster found for model_no: {model_no_prefix}")
                    except Exception as e:
                        print(f"❌ NA Completed View - Error fetching ModelMaster: {e}")

            # Priority 2: Fallback to existing combine_lot_ids logic if no ModelMaster images
            if not images and data['combine_lot_ids']:
                print("🔄 NA Completed View - No ModelMaster images, trying combine_lot_ids fallback")
                first_lot_id = data['combine_lot_ids'][0] if data['combine_lot_ids'] else None
                if first_lot_id:
                    total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
                    if total_stock and total_stock.batch_id:
                        batch_obj = total_stock.batch_id
                        if batch_obj.model_stock_no:
                            for img in batch_obj.model_stock_no.images.all():
                                if img.master_image:
                                    images.append(img.master_image.url)
                                    print(f"📸 NA Completed View - Added image from TotalStockModel: {img.master_image.url}")

            # Priority 3: Use placeholder if no images found
            if not images:
                print("📷 NA Completed View - No images found, using placeholder")
                images = [static('assets/images/imagePlaceholder.png')]
            
            data['model_images'] = images
            print(f"📸 NA Completed View - Final images for lot {jig_unload_obj.lot_id}: {len(images)} images")

            master_data.append(data)

        print(f"[NACompletedView] Total master_data records: {len(master_data)}")
        
        # ✅ Process the data (adapted for JigUnloadAfterTable)
        for data in master_data:
            tray_capacity = data.get('tray_capacity', 0)
            data['vendor_location'] = f"{data.get('vendor_internal', '')}_{data.get('location__location_name', '')}"
            
            lot_id = data.get('stock_lot_id')
            
            # Calculate display_accepted_qty
            total_rejection_qty = 0
            rejection_store = Nickle_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            if rejection_store and rejection_store.total_rejection_quantity:
                total_rejection_qty = rejection_store.total_rejection_quantity

            # Use total_case_qty from JigUnloadAfterTable instead of TotalStockModel
            jig_unload_obj = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            
            data['display_accepted_qty'] = jig_unload_obj.na_physical_qty 

            # Calculate number of trays
            display_qty = data.get('display_accepted_qty', 0)
            if tray_capacity > 0 and display_qty > 0:
                data['no_of_trays'] = math.ceil(display_qty / tray_capacity)
            else:
                data['no_of_trays'] = 0

        print("Processed lot_ids:", [data['stock_lot_id'] for data in master_data])
            
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
    
@method_decorator(csrf_exempt, name='dispatch')
class BrassTrayIdList_Complete_APIView(APIView):
    def get(self, request):
        batch_id = request.GET.get('batch_id')
        stock_lot_id = request.GET.get('stock_lot_id')
        lot_id = request.GET.get('lot_id') or stock_lot_id
        nq_qc_accptance = request.GET.get('nq_qc_accptance', 'false').lower() == 'true'
        na_qc_rejection = request.GET.get('na_qc_rejection', 'false').lower() == 'true'
        na_qc_few_cases_accptance = request.GET.get('na_qc_few_cases_accptance', 'false').lower() == 'true'
        
        if not batch_id:
            return JsonResponse({'success': False, 'error': 'Missing batch_id'}, status=400)
        
        if not lot_id:
            return JsonResponse({'success': False, 'error': 'Missing lot_id or stock_lot_id'}, status=400)
        
        # ✅ UPDATED: Base queryset - exclude trays rejected in Input Screening
        base_queryset = BrassTrayId.objects.filter(
            tray_quantity__gt=0,
            lot_id=lot_id
        ).exclude(
            rejected_tray=True  # ✅ EXCLUDE trays rejected in Input Screening
        )
        
        # Get rejected and accepted trays directly from BrassTrayId table
        rejected_trays = base_queryset.filter(rejected_tray=True)
        accepted_trays = base_queryset.filter(rejected_tray=False)
        
        print(f"Total trays in lot (excluding Input Screening rejected): {base_queryset.count()}")
        print(f"Rejected trays (Brass QC): {rejected_trays.count()}")
        print(f"Accepted trays: {accepted_trays.count()}")
        
        # Apply filtering based on stock status
        if nq_qc_accptance and not na_qc_few_cases_accptance:
            # Show only accepted trays
            queryset = accepted_trays
            print("Filtering for accepted trays only")
        elif na_qc_rejection and not na_qc_few_cases_accptance:
            # Show only rejected trays
            queryset = rejected_trays
            print("Filtering for rejected trays only")
        elif na_qc_few_cases_accptance:
            # Show both accepted and rejected trays
            queryset = base_queryset
            print("Showing both accepted and rejected trays")
        else:
            # Default - show all trays
            queryset = base_queryset
            print("Using default filter - showing all trays")
        
        # Determine top tray based on status
        top_tray = None
        if nq_qc_accptance and not na_qc_few_cases_accptance:
            # For accepted trays, prioritize top_tray, then top_tray
            top_tray = accepted_trays.filter(top_tray=True).first()
            if not top_tray:
                top_tray = accepted_trays.filter(top_tray=True).first()
        else:
            # For all other cases, prioritize ip_top_tray
            top_tray = queryset.filter(ip_top_tray=True).first()
            if not top_tray:
                top_tray = queryset.filter(top_tray=True).first()
        
        # Get other trays (excluding top tray)
        other_trays = queryset.exclude(pk=top_tray.pk if top_tray else None).order_by('id')
        
        data = []
        row_counter = 1

        # Helper function to create tray data
        def create_tray_data(tray_obj, is_top=False):
            nonlocal row_counter
            
            # Get rejection details if tray is rejected
            rejection_details = []
            if tray_obj.rejected_tray:
                # Get rejection details from Brass_QC_Rejected_TrayScan if needed
                rejected_scans = Brass_QC_Rejected_TrayScan.objects.filter(
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
                'rejected_tray': tray_obj.rejected_tray,
                'delink_tray': getattr(tray_obj, 'delink_tray', False),
                'rejection_details': rejection_details,
                'ip_top_tray': getattr(tray_obj, 'ip_top_tray', False),
                'ip_top_tray_qty': getattr(tray_obj, 'ip_top_tray_qty', None),
                'top_tray': getattr(tray_obj, 'top_tray', False),
                'rejected_tray': getattr(tray_obj, 'rejected_tray', False)  # ✅ NEW: Include Input Screening rejection status
            }

        # Add top tray first if it exists
        if top_tray:
            tray_data = create_tray_data(top_tray, is_top=True)
            data.append(tray_data)
            row_counter += 1

        # Add other trays
        for tray in other_trays:
            tray_data = create_tray_data(tray, is_top=False)
            data.append(tray_data)
            row_counter += 1
        
        print(f"Total trays returned: {len(data)}")
        
        # ✅ UPDATED: Get shortage rejections count (trays without tray_id) - use correct model
        shortage_count = Brass_QC_Rejected_TrayScan.objects.filter(
            lot_id=lot_id
        ).filter(
            models.Q(rejected_tray_id__isnull=True) | models.Q(rejected_tray_id='')
        ).count()
        
        # ✅ UPDATED: Get count of Input Screening rejected trays for summary
        input_screening_rejected_count = BrassTrayId.objects.filter(
            lot_id=lot_id,
            tray_quantity__gt=0,
            rejected_tray=True
        ).count()
        
        # Rejection summary
        rejection_summary = {
            'total_rejected_trays': rejected_trays.count(),
            'rejected_tray_ids': list(rejected_trays.values_list('tray_id', flat=True)),
            'shortage_rejections': shortage_count,
            'total_accepted_trays': accepted_trays.count(),
            'accepted_tray_ids': list(accepted_trays.values_list('tray_id', flat=True)),
            'input_screening_rejected_count': input_screening_rejected_count  # ✅ NEW: Count of excluded trays
        }
        
        return JsonResponse({
            'success': True, 
            'trays': data,
            'rejection_summary': rejection_summary
        })

        
@method_decorator(csrf_exempt, name='dispatch')
class BrassTrayValidate_Complete_APIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            batch_id_input = str(data.get('batch_id')).strip()
            tray_id = str(data.get('tray_id')).strip()
            
            # Get stock status parameters (optional, for enhanced validation)
            nq_qc_accptance = data.get('nq_qc_accptance', False)
            na_qc_rejection = data.get('na_qc_rejection', False)
            na_qc_few_cases_accptance = data.get('na_qc_few_cases_accptance', False)

            print(f"[BrassTrayValidate_Complete_APIView] User entered: batch_id={batch_id_input}, tray_id={tray_id}")
            print(f"Stock status: accepted={nq_qc_accptance}, rejected={na_qc_rejection}, few_cases={na_qc_few_cases_accptance}")

            # Base queryset for trays
            base_queryset = BrassTrayId.objects.filter(
                batch_id__batch_id__icontains=batch_id_input,
                tray_quantity__gt=0
            )
            
            # Apply the same filtering logic as the list API
            if nq_qc_accptance and not na_qc_few_cases_accptance:
                # Only validate against accepted trays
                trays = base_queryset.filter(rejected_tray=False)
                print(f"Validating against accepted trays only")
            elif na_qc_rejection and not na_qc_few_cases_accptance:
                # Only validate against rejected trays
                trays = base_queryset.filter(rejected_tray=True)
                print(f"Validating against rejected trays only")
            else:
                # Validate against all trays (few_cases or default)
                trays = base_queryset
                print(f"Validating against all trays")
            
            print(f"Available tray_ids for validation: {[t.tray_id for t in trays]}")

            exists = trays.filter(tray_id=tray_id).exists()
            print(f"Tray ID '{tray_id}' exists in filtered results? {exists}")

            # Get additional info about the tray if it exists
            tray_info = {}
            if exists:
                tray = trays.filter(tray_id=tray_id).first()
                if tray:
                    tray_info = {
                        'rejected_tray': tray.rejected_tray,
                        'tray_quantity': tray.tray_quantity,
                        'ip_top_tray': tray.ip_top_tray,  # ✅ UPDATED: Use ip_top_tray instead of top_tray
                        'ip_top_tray_qty': tray.ip_top_tray_qty  # ✅ UPDATED: Include ip_top_tray_qty
                    }

            return JsonResponse({
                'success': True, 
                'exists': exists,
                'tray_info': tray_info
            })
            
        except Exception as e:
            print(f"[TrayValidate_Complete_APIView] Error: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)    
           
        
@method_decorator(csrf_exempt, name='dispatch')
class BrassGetShortageRejectionsView(APIView):
    def get(self, request):
        lot_id = request.GET.get('lot_id')
        
        if not lot_id:
            return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)
        
        # Get SHORTAGE rejections (where rejected_tray_id is empty or null)
        shortage_rejections = IP_Rejected_TrayScan.objects.filter(
            lot_id=lot_id,
            rejected_tray_id__isnull=True
        ).union(
            IP_Rejected_TrayScan.objects.filter(
                lot_id=lot_id,
                rejected_tray_id=''
            )
        )
        
        shortage_data = []
        for shortage in shortage_rejections:
            shortage_data.append({
                'quantity': shortage.rejected_tray_quantity,
                'reason': shortage.rejection_reason.rejection_reason,
                'user': shortage.user.username if shortage.user else None
            })
        
        return JsonResponse({
            'success': True,
            'shortage_rejections': shortage_data
        })


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class NQBatchRejectionDraftAPIView(APIView):
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

            # Save as draft
            draft_data = {
                'total_qty': total_qty,
                'lot_rejected_comment': lot_rejected_comment,
                'batch_rejection': True,
                'is_draft': is_draft
            }

            # Update or create draft record
            draft_obj, created = Nickel_Audit_Draft_Store.objects.update_or_create(
                lot_id=lot_id,
                draft_type='batch_rejection',
                defaults={
                    'batch_id': batch_id,
                    'user': request.user,
                    'draft_data': draft_data
                }
            )

            return Response({
                'success': True, 
                'message': 'Batch rejection draft saved successfully',
                'draft_id': draft_obj.id
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class BATrayRejectionDraftAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            batch_id = data.get('batch_id')
            tray_rejections = data.get('tray_rejections', [])
            is_draft = data.get('is_draft', True)

            if not lot_id or not tray_rejections:
                return Response({'success': False, 'error': 'Missing lot_id or tray_rejections'}, status=400)

            # Save as draft
            draft_data = {
                'tray_rejections': tray_rejections,
                'batch_rejection': False,
                'is_draft': is_draft
            }

            # Update or create draft record
            draft_obj, created = Nickel_Audit_Draft_Store.objects.update_or_create(
                lot_id=lot_id,
                draft_type='tray_rejection',
                defaults={
                    'batch_id': batch_id,
                    'user': request.user,
                    'draft_data': draft_data
                }
            )

            # ✅ NEW: Update nq_draft in TotalStockModel
            JigUnloadAfterTable.objects.filter(lot_id=lot_id).update(nq_draft=True)

            return Response({
                'success': True, 
                'message': 'Tray rejection draft saved successfully',
                'draft_id': draft_obj.id,
                'total_rejections': len(tray_rejections)
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)
     
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def NA_get_all_drafts(request):
    """Get all draft data for a lot_id"""
    lot_id = request.GET.get('lot_id')
    
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        result = {
            'success': True,
            'batch_rejection_draft': None,
            'tray_rejection_draft': None
        }
        
        # Get batch rejection draft
        batch_draft = Nickel_Audit_Draft_Store.objects.filter(
            lot_id=lot_id,
            draft_type='batch_rejection'
        ).first()
        
        if batch_draft:
            result['batch_rejection_draft'] = {
                'draft_data': batch_draft.draft_data,
                'created_at': batch_draft.created_at,
                'updated_at': batch_draft.updated_at,
                'user': batch_draft.user.username if batch_draft.user else None
            }
        
        # Get tray rejection draft
        tray_draft = Nickel_Audit_Draft_Store.objects.filter(
            lot_id=lot_id,
            draft_type='tray_rejection'
        ).first()
        
        if tray_draft:
            result['tray_rejection_draft'] = {
                'draft_data': tray_draft.draft_data,
                'created_at': tray_draft.created_at,
                'updated_at': tray_draft.updated_at,
                'user': tray_draft.user.username if tray_draft.user else None
            }
        
        return Response(result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'success': False, 'error': str(e)}, status=500)

   
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nickel_get_draft_data(request):
    """Get draft data for a lot_id in Nickel QC"""
    lot_id = request.GET.get('lot_id')
    draft_type = request.GET.get('draft_type', 'tray_rejection')
    
    if not lot_id:
        return Response({'success': False, 'error': 'Missing lot_id'}, status=400)
    
    try:
        # 🔥 NEW: Find the unload_lot_id
        unload_lot_id = None
        
        # Try direct match first
        jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
        if jig_unload_record:
            unload_lot_id = str(jig_unload_record.lot_id)
        else:
            # Try searching in combine_lot_ids
            for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                    if lot_id in record.combine_lot_ids:
                        unload_lot_id = str(record.lot_id)
                        break

        if not unload_lot_id:
            return Response({'success': False, 'error': 'Unload record not found'}, status=404)

        draft_obj = Nickel_Audit_Draft_Store.objects.filter(
            lot_id=unload_lot_id,  # Use unload_lot_id
            draft_type=draft_type
        ).first()
        
        if draft_obj:
            return Response({
                'success': True,
                'has_draft': True,
                'draft_data': draft_obj.draft_data,
                'created_at': draft_obj.created_at,
                'updated_at': draft_obj.updated_at,
                'unload_lot_id': unload_lot_id
            })
        else:
            return Response({
                'success': True,
                'has_draft': False,
                'draft_data': None,
                'unload_lot_id': unload_lot_id
            })
            
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class NickelClearDraftAPIView(APIView):
    """Clear draft data for Nickel QC"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = data.get('lot_id')
            draft_type = data.get('draft_type')

            if not lot_id or not draft_type:
                return Response({'success': False, 'error': 'Missing lot_id or draft_type'}, status=400)

            # 🔥 NEW: Find the unload_lot_id
            unload_lot_id = None
            
            # Try direct match first
            jig_unload_record = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
            if jig_unload_record:
                unload_lot_id = str(jig_unload_record.lot_id)
            else:
                # Try searching in combine_lot_ids
                for record in JigUnloadAfterTable.objects.filter(combine_lot_ids__isnull=False):
                    if record.combine_lot_ids and isinstance(record.combine_lot_ids, list):
                        if lot_id in record.combine_lot_ids:
                            unload_lot_id = str(record.lot_id)
                            break

            if not unload_lot_id:
                return Response({'success': False, 'error': 'Unload record not found'}, status=404)

            # Delete the specific draft type
            deleted_count, _ = Nickel_Audit_Draft_Store.objects.filter(
                lot_id=unload_lot_id,  # Use unload_lot_id
                draft_type=draft_type
            ).delete()

            return Response({
                'success': True, 
                'message': f'Cleared {draft_type} draft for Nickel QC',
                'deleted_count': deleted_count,
                'unload_lot_id': unload_lot_id
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'success': False, 'error': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class PickTrayValidate_Complete_APIView(APIView):
    def post(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body.decode('utf-8'))
            lot_id = str(data.get('lot_id')).strip()
            tray_id = str(data.get('tray_id')).strip()

            if not lot_id:
                return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)
            if not tray_id:
                return JsonResponse({'success': False, 'error': 'Missing tray_id'}, status=400)

            print(f"[PickTrayValidate_Complete_APIView] Checking tray_id '{tray_id}' for lot_id '{lot_id}'")

            # Try Nickel_AuditTrayId first
            tray = Nickel_AuditTrayId.objects.filter(
                lot_id=lot_id,
                tray_id=tray_id
            ).first()

            tray_source = "Nickel_AuditTrayId"

            # If not found, fallback to JigUnload_TrayId
            if tray is None:
                print(f"⚠️ Tray not found in Nickel_AuditTrayId, checking JigUnload_TrayId...")
                tray = NickelQcTrayId.objects.filter(
                    lot_id=lot_id,
                    tray_id=tray_id
                ).first()
                tray_source = "JigUnload_TrayId"

            exists = tray is not None
            tray_info = {}
            if exists:
                tray_info = {
                    'tray_id': tray.tray_id,
                    'tray_quantity': getattr(tray, 'tray_quantity', getattr(tray, 'tray_qty', 0)),
                    'lot_id': tray.lot_id
                }

            return JsonResponse({
                'success': True,
                'exists': exists,
                'tray_info': tray_info,
                'tray_source': tray_source
            })

        except Exception as e:
            print(f"[PickTrayValidate_Complete_APIView] Error: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)             

@method_decorator(csrf_exempt, name='dispatch')
class PickTrayIdList_Complete_APIView(APIView):
    def get(self, request):
        lot_id = request.GET.get('lot_id')
        if not lot_id:
            return JsonResponse({'success': False, 'error': 'Missing lot_id'}, status=400)

        print(f"🔍 [PickTrayIdList_Complete_APIView] Received lot_id: {lot_id}")

        # Fetch ALL trays for lot_id from Nickel_AuditTrayId
        trays = Nickel_AuditTrayId.objects.filter(lot_id=lot_id).order_by('id')
        tray_source = "Nickel_AuditTrayId"

        # If not found, fallback to NickelQcTrayId
        if trays.count() == 0:
            print(f"⚠️ No Nickel_AuditTrayId records found for lot_id: {lot_id}, checking JigUnload_TrayId...")
            trays = NickelQcTrayId.objects.filter(lot_id=lot_id,rejected_tray=False).order_by('id')
            tray_source = "NickelQcTrayId"

        if trays.count() == 0:
            return JsonResponse({
                'success': False,
                'error': f'No tray records found for lot_id: {lot_id}'
            }, status=404)

        # Build response data: include delink_tray and rejected_tray status for each tray
        data = []
        for index, tray in enumerate(trays, 1):
            tray_data = {
                's_no': index,
                'tray_id': tray.tray_id,
                'top_tray': tray.top_tray if hasattr(tray, 'top_tray') else False,
                'tray_quantity': getattr(tray, 'tray_quantity', getattr(tray, 'tray_qty', 0)),
                'delink_tray': getattr(tray, 'delink_tray', False),
                'rejected_tray': getattr(tray, 'rejected_tray', False),
            }
            data.append(tray_data)
            print(f"    - Tray {index}: {tray.tray_id} (qty: {tray_data['tray_quantity']}) top={tray_data['top_tray']} delink={tray_data['delink_tray']} rejected={tray_data['rejected_tray']}")

        return JsonResponse({
            'success': True,
            'trays': data,
            'tray_source': tray_source
        })
        
class NATrayDelinkTopTrayCalcAPIView(APIView):
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
            trays = Nickel_AuditTrayId.objects.filter(
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
            print(f"Error in BrassTrayDelinkTopTrayCalcAPIView: {str(e)}")

            return Response({
                'success': False,
                'error': 'Internal server error occurred while calculating delink requirements'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class NATrayDelinkAndTopTrayUpdateAPIView(APIView):
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
                
                # NickelQcTrayId - Remove from lot completely
                brass_delink_tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if brass_delink_tray_obj:
                    brass_delink_tray_obj.delink_tray = True
                    brass_delink_tray_obj.lot_id = None
                    brass_delink_tray_obj.IP_tray_verified = False
                    brass_delink_tray_obj.top_tray = False
                    brass_delink_tray_obj.save(update_fields=[
                        'delink_tray', 'lot_id','IP_tray_verified', 'top_tray'
                    ])
                    print(f"✅ Delinked NickelQcTrayId tray: {delink_tray_id}")
    
                # IPTrayId - Mark as delinked
                ip_delink_tray_obj = JigUnload_TrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if ip_delink_tray_obj:
                    ip_delink_tray_obj.delink_tray = True
                    ip_delink_tray_obj.save(update_fields=['delink_tray'])
                    print(f"✅ Delinked IPTrayId tray: {delink_tray_id} for lot: {lot_id}")

                # JigUnload_TrayId - Mark as delinked
                jig_unload_delink_tray_obj = JigUnload_TrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if jig_unload_delink_tray_obj:
                    jig_unload_delink_tray_obj.delink_tray = True
                    jig_unload_delink_tray_obj.save(update_fields=['delink_tray'])
                    print(f"✅ Delinked JigUnload_TrayId tray: {delink_tray_id} for lot: {lot_id}")

                # IPTrayId - Mark as delinked
                nq_delink_tray_obj = NickelQcTrayId.objects.filter(tray_id=delink_tray_id, lot_id=lot_id).first()
                if nq_delink_tray_obj:
                    nq_delink_tray_obj.delink_tray = True
                    nq_delink_tray_obj.save(update_fields=['delink_tray'])
                    print(f"✅ Delinked NickelQcTrayId tray: {delink_tray_id} for lot: {lot_id}")

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
                
                # Update Nickel_AuditTrayId for top tray
                top_tray_obj = Nickel_AuditTrayId.objects.filter(tray_id=top_tray_id, lot_id=lot_id).first()
                if top_tray_obj:
                    top_tray_obj.top_tray = True
                    top_tray_obj.tray_quantity = int(top_tray_qty)
                    top_tray_obj.delink_tray = False  # Ensure it's not marked as delink
                    top_tray_obj.save(update_fields=['top_tray', 'tray_quantity', 'delink_tray'])
                    print(f"✅ Updated Nickel_AuditTrayId top tray: {top_tray_id} to qty: {top_tray_qty}")

            # 3. Reset other trays (not delinked or top tray) to full capacity
            other_trays_brass = Nickel_AuditTrayId.objects.filter(
                lot_id=lot_id
            ).exclude(
                tray_id__in=delink_tray_ids + ([top_tray_id] if top_tray_id else [])
            )
            
            other_trays_count = 0
            for tray in other_trays_brass:
                print(f"[OTHER TRAY] Resetting NickelQcTrayId {tray.tray_id} to full capacity: {tray.tray_capacity}")
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
            
class NAValidateTrayIdAPIView(APIView):
    def get(self, request):
        tray_id = request.GET.get('tray_id')
        lot_id = request.GET.get('lot_id')
        exists = Nickel_AuditTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).exists()
        return Response({
            'exists': exists,
            'valid_for_lot': exists
        })


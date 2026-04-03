from django.shortcuts import render
from django.views.generic import TemplateView
from django.http import JsonResponse, HttpResponse
from modelmasterapp.models import *
from Recovery_DP.models import *
from DayPlanning.models import DPTrayId_History
from InputScreening.models import IPTrayId, IP_Accepted_TrayScan, IP_Rejected_TrayScan, IP_Accepted_TrayID_Store
from Brass_QC.models import BrassTrayId, Brass_Qc_Accepted_TrayScan, Brass_QC_Rejected_TrayScan, Brass_Qc_Accepted_TrayID_Store, Brass_QC_Rejection_ReasonStore, Brass_QC_Draft_Store
from IQF.models import IQFTrayId, IQF_Accepted_TrayScan, IQF_Rejected_TrayScan, IQF_Accepted_TrayID_Store
from BrassAudit.models import BrassAuditTrayId, Brass_Audit_Accepted_TrayScan, Brass_Audit_Rejected_TrayScan, Brass_Audit_Accepted_TrayID_Store
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery, Sum, IntegerField, Count
from django.utils import timezone
import pytz
from datetime import timedelta
import pandas as pd
from io import BytesIO
from datetime import datetime

def convert_datetimes(data):
    for item in data:
        for key, value in item.items():
            if isinstance(value, datetime) and value.tzinfo is not None:
                item[key] = value.replace(tzinfo=None)
    return data

class ReportsView(TemplateView):
    template_name = "reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # List of available modules for reports
        context['modules'] = [
            {'value': 'day-planning', 'label': 'Day Planning'},
            {'value': 'input-screening', 'label': 'Input Screening'},
            {'value': 'brass-qc', 'label': 'Brass QC'},
            {'value': 'iqf', 'label': 'IQF'},
            {'value': 'brass-audit', 'label': 'Brass Audit'},
            {'value': 'recovery-day-planning', 'label': 'Recovery Day Planning'},
            {'value': 'recovery-input-screening', 'label': 'Recovery Input Screening'},
            {'value': 'recovery-brass-qc', 'label': 'Recovery Brass QC'},
            {'value': 'recovery-iqf', 'label': 'Recovery IQF'},
            {'value': 'recovery-brass-audit', 'label': 'Recovery Brass Audit'},
            {'value': 'jig-loading', 'label': 'Jig Loading'},
            {'value': 'inprocess-inspection', 'label': 'Inprocess Inspection'},
            {'value': 'jig-unloading', 'label': 'Jig Unloading'},
            {'value': 'nickel-inspection', 'label': 'Nickel Inspection'},
            {'value': 'nickel-audit', 'label': 'Nickel Audit'},
            {'value': 'spider-spindle', 'label': 'Spider Spindle'}
        ]
        return context
    
# Function for "Reports Module" to download Excel report based on selected module
def download_report(request):
    module = request.GET.get('module')
    if not module:
        return HttpResponse("Module not specified", status=400)

    # Create Excel file with multiple sheets
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if module == 'day-planning':
            # Custom format for Day Planning report
            from modelmasterapp.models import ModelMasterCreation
            batches = ModelMasterCreation.objects.filter(total_batch_quantity__gt=0, Moved_to_D_Picker=False).select_related('location', 'version').annotate(
                next_process_module=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('next_process_module')[:1])
            )
            
            report_data = []
            for idx, batch in enumerate(batches, start=1):
                # Determine Lot Status - matching Day Planning pick table values
                if batch.hold_lot:
                    lot_status = "On Hold"
                elif batch.next_process_module:
                    lot_status = "Released"
                else:
                    lot_status = "Yet to Start"
                
                # Tray Cate-Capacity
                tray_cate_capacity = f"{batch.tray_type} - {batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ""
                
                # Combine holding and releasing reasons
                remarks_holding = f"Holding Reason: {batch.holding_reason}" if batch.holding_reason else ""
                remarks_releasing = f"Releasing Reason: {batch.release_reason}" if batch.release_reason else ""
                combined_remarks = "\n".join(filter(None, [remarks_holding, remarks_releasing])) or ""
                
                #Day Planning Excel Columns
                row = {
                    'S.No': idx,
                    'Date & Time': batch.date_time.replace(tzinfo=None) if batch.date_time else None,
                    'Plating Stock No': batch.plating_stk_no or '',
                    'Plating color': batch.plating_color or '',
                    'Lot Status': lot_status,
                    'Remarks (for holding row)': combined_remarks,
                    'Category': batch.category or '',
                    'Tray Cate-Capacity': tray_cate_capacity,
                    #'No of Trays': batch.no_of_trays or 0,
                    'Input Qty': batch.total_batch_quantity or 0,
                    'Current Stage': batch.next_process_module or 'Day Planning',
                    'Remarks (chat)': batch.dp_pick_remarks or ''
                }
                report_data.append(row)
            
            df = pd.DataFrame(report_data)
            df.to_excel(writer, sheet_name='Day Planning Report', index=False)
            
            # Completed Table
            from django.utils import timezone
            tz = pytz.timezone("Asia/Kolkata")
            now_local = timezone.now().astimezone(tz)
            today = now_local.date()
            yesterday = today - timedelta(days=1)
            from_date = yesterday
            to_date = today
            from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
            to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))
            batch_ids_in_range = list(
                TotalStockModel.objects.filter(
                    created_at__range=(from_datetime, to_datetime)
                ).values_list('batch_id__batch_id', flat=True)
            )
            completed_batches = ModelMasterCreation.objects.filter(
                total_batch_quantity__gt=0,
                Moved_to_D_Picker=True,
                batch_id__in=batch_ids_in_range
            ).select_related('location', 'version').annotate(
                next_process_module=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('next_process_module')[:1])
            )
            report_data_completed = []
            for idx, batch in enumerate(completed_batches, start=1):
                lot_status = "Released"
                tray_cate_capacity = f"{batch.tray_type} - {batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ""
                remarks_holding = f"Holding Reason: {batch.holding_reason}" if batch.holding_reason else ""
                remarks_releasing = f"Releasing Reason: {batch.release_reason}" if batch.release_reason else ""
                combined_remarks = "\n".join(filter(None, [remarks_holding, remarks_releasing])) or ""
                row = {
                    'S.No': idx,
                    'Last Updated': batch.date_time.replace(tzinfo=None) if batch.date_time else None,
                    'Plating Stk No': batch.plating_stk_no or '',
                    'Polishing Stk No': batch.polishing_stk_no or '',
                    'Plating Color': batch.plating_color or '',
                    'Category': batch.category or '',
                    'Polish Finish': batch.polish_finish or '',
                    'Version': batch.version.version_name if batch.version else '',
                    'Tray Cate-Capacity': tray_cate_capacity,
                    'Source': f"{batch.vendor_internal}_{batch.location.location_name if batch.location else ''}",
                    'No of Tray': batch.no_of_trays or 0,
                    'Input Qty': batch.total_batch_quantity or 0,
                    'Process Status': 'T',
                    'Lot Status': lot_status,
                    'Current Stage': batch.next_process_module or '',
                    'Remarks': combined_remarks,
                }
                report_data_completed.append(row)
            df_completed = pd.DataFrame(report_data_completed)
            df_completed.to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'input-screening':
            # Import required models and functions
            from modelmasterapp.models import ModelMasterCreation
            from InputScreening.models import IP_Rejection_ReasonStore
            from django.db.models import Q, F, Exists
            from django.utils import timezone
            import math
            from django.templatetags.static import static
            
            # Pick Table - Use same logic as IS_PickTable
            accepted_Ip_stock_subquery = TotalStockModel.objects.filter(
                batch_id=OuterRef('pk')
            ).values('accepted_Ip_stock')[:1]
            
            accepted_tray_scan_status_subquery = TotalStockModel.objects.filter(
                batch_id=OuterRef('pk')
            ).values('accepted_tray_scan_status')[:1]
            
            rejected_ip_stock_subquery = TotalStockModel.objects.filter(
                batch_id=OuterRef('pk')
            ).values('rejected_ip_stock')[:1]
            
            few_cases_accepted_Ip_stock_subquery = TotalStockModel.objects.filter(
                batch_id=OuterRef('pk')
            ).values('few_cases_accepted_Ip_stock')[:1]
            
            ip_onhold_picking_subquery = TotalStockModel.objects.filter(
                batch_id=OuterRef('pk')
            ).values('ip_onhold_picking')[:1]
            
            tray_verify_subquery = TotalStockModel.objects.filter(
                batch_id=OuterRef('pk')
            ).values('tray_verify')[:1]
            
            draft_tray_verify_subquery = TotalStockModel.objects.filter(
                batch_id=OuterRef('pk')
            ).values('draft_tray_verify')[:1]

            tray_scan_exists = Exists(
                TotalStockModel.objects.filter(
                    batch_id=OuterRef('pk'),
                    tray_scan_status=True
                )
            )

            pick_queryset = ModelMasterCreation.objects.filter(
                total_batch_quantity__gt=0,
            ).annotate(
                last_process_module=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('last_process_module')[:1]
                ),
                next_process_module=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('next_process_module')[:1]
                ),
                wiping_required=F('model_stock_no__wiping_required'),
                stock_lot_id=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('lot_id')[:1]
                ),
                ip_person_qty_verified=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('ip_person_qty_verified')[:1]
                ),
                lot_rejected_comment=Subquery(
                    IP_Rejection_ReasonStore.objects.filter(lot_id=OuterRef('stock_lot_id')).values('lot_rejected_comment')[:1]
                ),
                accepted_Ip_stock=accepted_Ip_stock_subquery,
                accepted_tray_scan_status=accepted_tray_scan_status_subquery,
                rejected_ip_stock=rejected_ip_stock_subquery,
                few_cases_accepted_Ip_stock=few_cases_accepted_Ip_stock_subquery,
                ip_onhold_picking=ip_onhold_picking_subquery,
                tray_verify=tray_verify_subquery,
                draft_tray_verify=draft_tray_verify_subquery,
                tray_scan_exists=tray_scan_exists,
                IP_pick_remarks=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('IP_pick_remarks')[:1]
                ),
                created_at=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('created_at')[:1]
                ),
                total_ip_accepted_quantity=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('total_IP_accpeted_quantity')[:1]
                ),
                ip_hold_lot=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('ip_hold_lot')[:1]
                ),
                ip_holding_reason=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('ip_holding_reason')[:1]
                ),
                ip_release_lot=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('ip_release_lot')[:1]
                ),
                ip_release_reason=Subquery(
                    TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('ip_release_reason')[:1]
                ),
                total_rejection_quantity=Subquery(
                    IP_Rejection_ReasonStore.objects.filter(lot_id=OuterRef('stock_lot_id')).values('total_rejection_quantity')[:1]
                ),
            ).filter(
                (Q(accepted_Ip_stock=False) | Q(accepted_Ip_stock__isnull=True)) &
                (Q(rejected_ip_stock=False) | Q(rejected_ip_stock__isnull=True)) &
                (Q(accepted_tray_scan_status=False) | Q(accepted_tray_scan_status__isnull=True)),
                tray_scan_exists=True,
            ).exclude(
                totalstockmodel__remove_lot=True    
            ).order_by('-date_time')

            pick_report_data = []
            for idx, batch in enumerate(pick_queryset, start=1):
                # Determine status based on the same logic as HTML table
                if batch.ip_hold_lot:
                    lot_status = "On Hold"
                elif batch.ip_release_lot:
                    lot_status = "Released"
                else:
                    lot_status = "In Process"
                
                # Calculate derived values
                tray_cate_capacity = f"{batch.tray_type} - {batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ""
                input_source = f"{batch.vendor_internal}_{batch.location.location_name if batch.location else ''}"
                ipa_wiping = "Yes" if batch.wiping_required else "No"
                no_of_trays = math.ceil(batch.total_batch_quantity / batch.tray_capacity) if batch.tray_capacity and batch.tray_capacity > 0 else 0
                lot_qty = batch.total_batch_quantity or 0
                
                # Calculate Accept Qty and Reject Qty
                accept_qty = batch.total_ip_accepted_quantity or 0
                reject_qty = batch.total_rejection_quantity or 0
                
                # Process Status and Current Stage
                process_status = "Draft"  # Default for pick table
                current_stage = batch.next_process_module or 'Input Screening'
                
                # Format Last Updated
                last_updated = ""
                if batch.date_time:
                    dt = batch.date_time.replace(tzinfo=None)
                    last_updated = dt.strftime('%d-%b-%y %I:%M %p')
                
                row = {
                    'S.No': idx,
                    'Last Updated': last_updated,
                    'Plating Stk No': batch.plating_stk_no or '',
                    'Polishing Stk No': batch.polishing_stk_no or '',
                    'Plating Color': batch.plating_color or '',
                    'Category': batch.category or '',
                    'Polish Finish': batch.polish_finish or '',
                    'Tray Cate-Capacity': tray_cate_capacity,
                    'Input Source': input_source,
                    'IPA Wiping': ipa_wiping,
                    'No of Trays': no_of_trays,
                    'LOT Qty': lot_qty,
                    'Accept Qty': accept_qty,
                    'Reject Qty': reject_qty,
                    'Process Status': process_status,
                    'Lot Status': lot_status,
                    'Current Stage': current_stage,
                    'Remarks': batch.IP_pick_remarks or '',
                }
                pick_report_data.append(row)
            
            df_pick = pd.DataFrame(pick_report_data)
            df_pick.to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Completed Table - Use same logic as IS_Completed_Table
            tz = pytz.timezone("Asia/Kolkata")
            now_local = timezone.now().astimezone(tz)
            today = now_local.date()
            yesterday = today - timedelta(days=1)
            from_date = yesterday
            to_date = today
            from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
            to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))

            completed_queryset = TotalStockModel.objects.filter(
                Q(accepted_Ip_stock=True) |
                Q(rejected_ip_stock=True) |
                (Q(few_cases_accepted_Ip_stock=True) & Q(ip_onhold_picking=False)),
                batch_id__total_batch_quantity__gt=0,
                remove_lot=False
            ).select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).annotate(
                batch_model_no=F('batch_id__model_stock_no__model_no'),
                batch_plating_color=F('batch_id__plating_color'),
                batch_polish_finish=F('batch_id__polish_finish'),
                batch_version_name=F('batch_id__version__version_name'),
                batch_version_internal=F('batch_id__version__version_internal'),
                batch_vendor_internal=F('batch_id__vendor_internal'),
                batch_location_name=F('batch_id__location__location_name'),
                batch_tray_type=F('batch_id__tray_type'),
                batch_tray_capacity=F('batch_id__tray_capacity'),
                batch_moved_to_d_picker=F('batch_id__Moved_to_D_Picker'),
                batch_draft_saved=F('batch_id__Draft_Saved'),
                batch_total_batch_quantity=F('batch_id__total_batch_quantity'),
                batch_date_time=F('batch_id__date_time'),
                batch_plating_stk_no=F('batch_id__plating_stk_no'),
                batch_polishing_stk_no=F('batch_id__polishing_stk_no'),
                batch_category=F('batch_id__category')
            ).order_by('-last_process_date_time')

            completed_report_data = []
            for idx, total_stock_obj in enumerate(completed_queryset, start=1):
                # Calculate no_of_trays
                no_of_trays = math.ceil(total_stock_obj.total_stock / total_stock_obj.batch_tray_capacity) if total_stock_obj.batch_tray_capacity and total_stock_obj.batch_tray_capacity > 0 else 0
                
                # Determine status
                if total_stock_obj.accepted_Ip_stock:
                    status = "Accepted"
                elif total_stock_obj.rejected_ip_stock:
                    status = "Rejected"
                elif total_stock_obj.few_cases_accepted_Ip_stock and not total_stock_obj.ip_onhold_picking:
                    status = "Partially Accepted"
                else:
                    status = "Completed"
                
                row = {
                    'S.No': idx,
                    'Date & Time': total_stock_obj.batch_date_time.replace(tzinfo=None) if total_stock_obj.batch_date_time else None,
                    'Plating Stock No': total_stock_obj.batch_plating_stk_no or '',
                    'Polishing Stock No': total_stock_obj.batch_polishing_stk_no or '',
                    'Model No': total_stock_obj.batch_model_no or '',
                    'Plating Color': total_stock_obj.batch_plating_color or '',
                    'Polish Finish': total_stock_obj.batch_polish_finish or '',
                    'Version': total_stock_obj.batch_version_name or '',
                    'Vendor': total_stock_obj.batch_vendor_internal or '',
                    'Location': total_stock_obj.batch_location_name or '',
                    'Tray Type': total_stock_obj.batch_tray_type or '',
                    'Tray Capacity': total_stock_obj.batch_tray_capacity or 0,
                    'No of Trays': no_of_trays,
                    'Total Stock': total_stock_obj.total_stock or 0,
                    'Lot ID': total_stock_obj.lot_id or '',
                    'Status': status,
                    'IP Pick Remarks': total_stock_obj.IP_pick_remarks or '',
                    'Last Process Date Time': total_stock_obj.last_process_date_time.replace(tzinfo=None) if total_stock_obj.last_process_date_time else None,
                }
                completed_report_data.append(row)
            
            df_completed = pd.DataFrame(completed_report_data)
            df_completed.to_excel(writer, sheet_name='Completed Table', index=False)
            
            # Accept Table - Use same logic as IS_AcceptTable
            accept_queryset = TotalStockModel.objects.filter(
                Q(accepted_Ip_stock=True) |  
                (Q(few_cases_accepted_Ip_stock=True) & Q(ip_onhold_picking=False)) |  
                (Q(few_cases_accepted_Ip_stock=True) & Q(ip_onhold_picking=True)),  
                batch_id__total_batch_quantity__gt=0,
                remove_lot=False,  
            ).select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).annotate(
                batch_model_no=F('batch_id__model_stock_no__model_no'),
                batch_plating_color=F('batch_id__plating_color'),
                batch_polish_finish=F('batch_id__polish_finish'),
                batch_version_name=F('batch_id__version__version_name'),
                batch_version_internal=F('batch_id__version__version_internal'),
                batch_vendor_internal=F('batch_id__vendor_internal'),
                batch_location_name=F('batch_id__location__location_name'),
                batch_tray_type=F('batch_id__tray_type'),
                batch_tray_capacity=F('batch_id__tray_capacity'),
                batch_moved_to_d_picker=F('batch_id__Moved_to_D_Picker'),
                batch_draft_saved=F('batch_id__Draft_Saved'),
                batch_total_batch_quantity=F('batch_id__total_batch_quantity'),
                batch_date_time=F('batch_id__date_time'),
                batch_plating_stk_no=F('batch_id__plating_stk_no'),
                batch_polishing_stk_no=F('batch_id__polishing_stk_no'),
                batch_category=F('batch_id__category')
            ).order_by('-last_process_date_time')

            accept_report_data = []
            for idx, total_stock_obj in enumerate(accept_queryset, start=1):
                # Calculate accepted quantity (same logic as IS_AcceptTable)
                total_IP_accpeted_quantity = total_stock_obj.total_IP_accpeted_quantity
                lot_id = total_stock_obj.lot_id
                total_stock = total_stock_obj.total_stock
                
                if total_IP_accpeted_quantity and total_IP_accpeted_quantity > 0:
                    display_accepted_qty = total_IP_accpeted_quantity
                else:
                    total_rejection_qty = 0
                    rejection_store = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
                    if rejection_store and rejection_store.total_rejection_quantity:
                        total_rejection_qty = rejection_store.total_rejection_quantity
                    
                    if total_stock > 0 and total_rejection_qty > 0:
                        display_accepted_qty = max(total_stock - total_rejection_qty, 0)
                    else:
                        display_accepted_qty = 0
                
                # Calculate no_of_trays
                no_of_trays = math.ceil(display_accepted_qty / total_stock_obj.batch_tray_capacity) if total_stock_obj.batch_tray_capacity and total_stock_obj.batch_tray_capacity > 0 else 0
                
                row = {
                    'S.No': idx,
                    'Date & Time': total_stock_obj.batch_date_time.replace(tzinfo=None) if total_stock_obj.batch_date_time else None,
                    'Plating Stock No': total_stock_obj.batch_plating_stk_no or '',
                    'Polishing Stock No': total_stock_obj.batch_polishing_stk_no or '',
                    'Model No': total_stock_obj.batch_model_no or '',
                    'Plating Color': total_stock_obj.batch_plating_color or '',
                    'Polish Finish': total_stock_obj.batch_polish_finish or '',
                    'Version': total_stock_obj.batch_version_name or '',
                    'Vendor': total_stock_obj.batch_vendor_internal or '',
                    'Location': total_stock_obj.batch_location_name or '',
                    'Tray Type': total_stock_obj.batch_tray_type or '',
                    'Tray Capacity': total_stock_obj.batch_tray_capacity or 0,
                    'No of Trays': no_of_trays,
                    'Accept Qty': display_accepted_qty,
                    'Lot ID': total_stock_obj.lot_id or '',
                    'IP Pick Remarks': total_stock_obj.IP_pick_remarks or '',
                    'Last Process Date Time': total_stock_obj.last_process_date_time.replace(tzinfo=None) if total_stock_obj.last_process_date_time else None,
                }
                accept_report_data.append(row)
            
            df_accept = pd.DataFrame(accept_report_data)
            df_accept.to_excel(writer, sheet_name='Accept Table', index=False)
            
            # Reject Table - Use same logic as IS_RejectTable
            reject_queryset = TotalStockModel.objects.filter(
                Q(rejected_ip_stock=True) |  
                (Q(few_cases_accepted_Ip_stock=True) & Q(ip_onhold_picking=False)) |  
                (Q(few_cases_accepted_Ip_stock=True) & Q(ip_onhold_picking=True)),  
                batch_id__total_batch_quantity__gt=0,
                remove_lot=False,  
            ).select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).annotate(
                batch_model_no=F('batch_id__model_stock_no__model_no'),
                batch_plating_color=F('batch_id__plating_color'),
                batch_polish_finish=F('batch_id__polish_finish'),
                batch_version_name=F('batch_id__version__version_name'),
                batch_version_internal=F('batch_id__version__version_internal'),
                batch_vendor_internal=F('batch_id__vendor_internal'),
                batch_location_name=F('batch_id__location__location_name'),
                batch_tray_type=F('batch_id__tray_type'),
                batch_tray_capacity=F('batch_id__tray_capacity'),
                batch_moved_to_d_picker=F('batch_id__Moved_to_D_Picker'),
                batch_draft_saved=F('batch_id__Draft_Saved'),
                batch_total_batch_quantity=F('batch_id__total_batch_quantity'),
                batch_date_time=F('batch_id__date_time'),
                batch_plating_stk_no=F('batch_id__plating_stk_no'),
                batch_polishing_stk_no=F('batch_id__polishing_stk_no'),
                batch_category=F('batch_id__category')
            ).order_by('-last_process_date_time')

            reject_report_data = []
            for idx, total_stock_obj in enumerate(reject_queryset, start=1):
                stock_lot_id = total_stock_obj.lot_id
                
                # Get rejection quantity (same logic as IS_RejectTable)
                rejection_qty = 0
                rejection_record = IP_Rejection_ReasonStore.objects.filter(lot_id=stock_lot_id).first()
                if rejection_record and rejection_record.total_rejection_quantity:
                    rejection_qty = rejection_record.total_rejection_quantity
                
                # Get rejection reasons
                rejection_letters = []
                batch_rejection = False
                lot_rejected_comment = None
                
                if rejection_record:
                    batch_rejection = rejection_record.batch_rejection
                    lot_rejected_comment = rejection_record.lot_rejected_comment
                    reasons = rejection_record.rejection_reason.all()
                    for r in reasons:
                        if r.rejection_reason.upper() != 'SHORTAGE':
                            rejection_letters.append(r.rejection_reason[0].upper())
                
                # Check for SHORTAGE
                shortage_exists = IP_Rejected_TrayScan.objects.filter(
                    lot_id=stock_lot_id,
                    rejection_reason__rejection_reason__iexact='SHORTAGE'
                ).exists()
                if shortage_exists:
                    rejection_letters.append('S')
                
                # Get shortage quantity
                shortage_qty = sum(
                    int(obj.rejected_tray_quantity or 0)
                    for obj in IP_Rejected_TrayScan.objects.filter(
                        lot_id=stock_lot_id,
                        rejection_reason__rejection_reason__iexact='SHORTAGE'
                    )
                )
                
                # Calculate effective stock and trays
                effective_stock = max(rejection_qty - shortage_qty, 0)
                no_of_trays = math.ceil(effective_stock / total_stock_obj.batch_tray_capacity) if total_stock_obj.batch_tray_capacity and total_stock_obj.batch_tray_capacity > 0 else 0
                
                row = {
                    'S.No': idx,
                    'Date & Time': total_stock_obj.batch_date_time.replace(tzinfo=None) if total_stock_obj.batch_date_time else None,
                    'Plating Stock No': total_stock_obj.batch_plating_stk_no or '',
                    'Polishing Stock No': total_stock_obj.batch_polishing_stk_no or '',
                    'Model No': total_stock_obj.batch_model_no or '',
                    'Plating Color': total_stock_obj.batch_plating_color or '',
                    'Polish Finish': total_stock_obj.batch_polish_finish or '',
                    'Version': total_stock_obj.batch_version_name or '',
                    'Vendor': total_stock_obj.batch_vendor_internal or '',
                    'Location': total_stock_obj.batch_location_name or '',
                    'Tray Type': total_stock_obj.batch_tray_type or '',
                    'Tray Capacity': total_stock_obj.batch_tray_capacity or 0,
                    'No of Trays': no_of_trays,
                    'Reject Qty': rejection_qty,
                    'Shortage Qty': shortage_qty,
                    'Rejection Reasons': ','.join(rejection_letters),
                    'Batch Rejection': 'Yes' if batch_rejection else 'No',
                    'Lot Rejected Comment': lot_rejected_comment or '',
                    'Lot ID': total_stock_obj.lot_id or '',
                    'IP Pick Remarks': total_stock_obj.IP_pick_remarks or '',
                    'Last Process Date Time': total_stock_obj.last_process_date_time.replace(tzinfo=None) if total_stock_obj.last_process_date_time else None,
                }
                reject_report_data.append(row)
            
            df_reject = pd.DataFrame(reject_report_data)
            df_reject.to_excel(writer, sheet_name='Reject Table', index=False)

        elif module == 'brass-qc':
            # Import required models and functions
            from modelmasterapp.models import ModelMasterCreation
            from InputScreening.models import IP_Rejection_ReasonStore
            from django.db.models import Q, F, Exists
            from django.utils import timezone
            import math
            from django.templatetags.static import static
            
            # Pick Table - Use same logic as BrassPickTableView
            brass_rejection_qty_subquery = Brass_QC_Rejection_ReasonStore.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('total_rejection_quantity')[:1]

            has_draft_subquery = Exists(
                Brass_QC_Draft_Store.objects.filter(
                    lot_id=OuterRef('lot_id')
                )
            )
            
            draft_type_subquery = Brass_QC_Draft_Store.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('draft_type')[:1]

            pick_queryset = TotalStockModel.objects.select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).filter(
                batch_id__total_batch_quantity__gt=0
            ).annotate(
                wiping_required=F('batch_id__model_stock_no__wiping_required'),
                has_draft=has_draft_subquery,
                draft_type=draft_type_subquery,
                brass_rejection_total_qty=brass_rejection_qty_subquery,
            ).filter(
                (
                    (
                        Q(brass_qc_accptance__isnull=True) | Q(brass_qc_accptance=False)
                    ) &
                    (
                        Q(brass_qc_rejection__isnull=True) | Q(brass_qc_rejection=False)
                    ) &
                    ~Q(brass_qc_few_cases_accptance=True, brass_onhold_picking=False)
                    &
                    (
                        Q(accepted_Ip_stock=True) | 
                        Q(few_cases_accepted_Ip_stock=True, ip_onhold_picking=False)
                    )
                )
                |
                Q(send_brass_qc=True)
                |
                Q(brass_qc_rejection=True, brass_onhold_picking=True)
                |
                Q(send_brass_audit_to_qc=True)
            ).exclude(
                Q(brass_audit_rejection=True)
            ).order_by('-last_process_date_time', '-lot_id')

            pick_report_data = []
            for idx, stock_obj in enumerate(pick_queryset, start=1):
                batch = stock_obj.batch_id
                
                # Calculate derived values
                tray_cate_capacity = f"{batch.tray_type} - {batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ""
                input_source = f"{batch.vendor_internal}_{batch.location.location_name if batch.location else ''}"
                
                # Lot Qty
                lot_qty = batch.total_batch_quantity or 0
                
                # Physical Qty
                physical_qty = stock_obj.brass_physical_qty or 0
                
                # Accept Qty calculation
                total_IP_accpeted_quantity = stock_obj.total_IP_accpeted_quantity or 0
                if total_IP_accpeted_quantity > 0:
                    accept_qty = total_IP_accpeted_quantity
                else:
                    total_rejection_qty = 0
                    rejection_store = IP_Rejection_ReasonStore.objects.filter(lot_id=stock_obj.lot_id).first()
                    if rejection_store and rejection_store.total_rejection_quantity:
                        total_rejection_qty = rejection_store.total_rejection_quantity
                    
                    if stock_obj.total_stock > 0 and total_rejection_qty > 0:
                        accept_qty = max(stock_obj.total_stock - total_rejection_qty, 0)
                    else:
                        accept_qty = 0
                
                # Lot Qty (same as Accept Qty in pick table)
                lot_qty = accept_qty
                
                # Reject Qty
                reject_qty = stock_obj.brass_rejection_total_qty or 0
                
                # No of Trays
                no_of_trays = math.ceil(accept_qty / batch.tray_capacity) if batch.tray_capacity and batch.tray_capacity > 0 and accept_qty > 0 else 0
                
                # Process Status
                process_status = "Draft"  # Default for pick table
                
                # Lot Status
                if stock_obj.brass_hold_lot:
                    lot_status = "On Hold"
                elif stock_obj.brass_release_lot:
                    lot_status = "Released"
                else:
                    lot_status = "In Process"
                
                # Current Stage
                current_stage = stock_obj.next_process_module or 'Brass QC'
                
                # Last Updated
                last_updated = ""
                if stock_obj.last_process_date_time:
                    dt = stock_obj.last_process_date_time.replace(tzinfo=None)
                    last_updated = dt.strftime('%d-%b-%y %I:%M %p')
                
                row = {
                    'S.No': idx,
                    'Last Updated': last_updated,
                    'Plating Stk No': batch.plating_stk_no or '',
                    'Polishing Stk No': batch.polishing_stk_no or '',
                    'Plating Color': batch.plating_color or '',
                    'Category': batch.category or '',
                    'Polish Finish': batch.polish_finish or '',
                    'Tray Cate-Capacity': tray_cate_capacity,
                    'Input Source': input_source,
                    'No of Trays': no_of_trays,
                    'Lot Qty': lot_qty,
                    'Physical Qty': physical_qty,
                    'Accept Qty': accept_qty,
                    'Reject Qty': reject_qty,
                    'Process Status': process_status,
                    'Lot Status': lot_status,
                    'Current Stage': current_stage,
                    'Remarks': stock_obj.Bq_pick_remarks or '',
                }
                pick_report_data.append(row)
            
            df_pick = pd.DataFrame(pick_report_data)
            df_pick.to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Completed Table - Use same logic as BrassCompletedView
            tz = pytz.timezone("Asia/Kolkata")
            now_local = timezone.now().astimezone(tz)
            today = now_local.date()
            yesterday = today - timedelta(days=1)
            from_date = yesterday
            to_date = today
            from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
            to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))

            brass_rejection_qty_subquery = Brass_QC_Rejection_ReasonStore.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('total_rejection_quantity')[:1]

            completed_queryset = TotalStockModel.objects.select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).filter(
                batch_id__total_batch_quantity__gt=0,
                bq_last_process_date_time__range=(from_datetime, to_datetime)
            ).annotate(
                brass_rejection_qty=brass_rejection_qty_subquery,
            ).filter(
                Q(brass_qc_accptance=True) |
                Q(brass_qc_rejection=True) |
                Q(brass_qc_few_cases_accptance=True, brass_onhold_picking=False)
            ).order_by('-bq_last_process_date_time', '-lot_id')

            completed_report_data = []
            for idx, stock_obj in enumerate(completed_queryset, start=1):
                batch = stock_obj.batch_id
                
                # Calculate derived values
                tray_cate_capacity = f"{batch.tray_type} - {batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ""
                input_source = f"{batch.vendor_internal}_{batch.location.location_name if batch.location else ''}"
                
                # Physical Qty
                physical_qty = stock_obj.brass_physical_qty or 0
                
                # Accept Qty calculation
                total_IP_accpeted_quantity = stock_obj.total_IP_accpeted_quantity or 0
                if total_IP_accpeted_quantity > 0:
                    accept_qty = total_IP_accpeted_quantity
                else:
                    total_rejection_qty = 0
                    rejection_store = IP_Rejection_ReasonStore.objects.filter(lot_id=stock_obj.lot_id).first()
                    if rejection_store and rejection_store.total_rejection_quantity:
                        total_rejection_qty = rejection_store.total_rejection_quantity
                    
                    if stock_obj.total_stock > 0 and total_rejection_qty > 0:
                        accept_qty = max(stock_obj.total_stock - total_rejection_qty, 0)
                    else:
                        accept_qty = 0
                
                # Lot Qty
                lot_qty = accept_qty
                
                # Reject Qty
                reject_qty = stock_obj.brass_rejection_qty or 0
                
                # No of Trays
                no_of_trays = math.ceil(accept_qty / batch.tray_capacity) if batch.tray_capacity and batch.tray_capacity > 0 and accept_qty > 0 else 0
                
                # Process Status
                if stock_obj.brass_qc_accptance:
                    process_status = "Accepted"
                elif stock_obj.brass_qc_rejection:
                    process_status = "Rejected"
                elif stock_obj.brass_qc_few_cases_accptance and not stock_obj.brass_onhold_picking:
                    process_status = "Partially Accepted"
                else:
                    process_status = "Completed"
                
                # Lot Status
                if stock_obj.brass_hold_lot:
                    lot_status = "On Hold"
                elif stock_obj.brass_release_lot:
                    lot_status = "Released"
                else:
                    lot_status = "Completed"
                
                # Current Stage
                current_stage = stock_obj.next_process_module or ''
                
                # Last Updated
                last_updated = ""
                if stock_obj.bq_last_process_date_time:
                    dt = stock_obj.bq_last_process_date_time.replace(tzinfo=None)
                    last_updated = dt.strftime('%d-%b-%y %I:%M %p')
                
                row = {
                    'S.No': idx,
                    'Last Updated': last_updated,
                    'Plating Stk No': batch.plating_stk_no or '',
                    'Polishing Stk No': batch.polishing_stk_no or '',
                    'Plating Color': batch.plating_color or '',
                    'Category': batch.category or '',
                    'Polish Finish': batch.polish_finish or '',
                    'Tray Cate-Capacity': tray_cate_capacity,
                    'Input Source': input_source,
                    'No of Trays': no_of_trays,
                    'Lot Qty': lot_qty,
                    'Physical Qty': physical_qty,
                    'Accept Qty': accept_qty,
                    'Reject Qty': reject_qty,
                    'Process Status': process_status,
                    'Lot Status': lot_status,
                    'Current Stage': current_stage,
                    'Remarks': stock_obj.Bq_pick_remarks or '',
                }
                completed_report_data.append(row)
            
            df_completed = pd.DataFrame(completed_report_data)
            df_completed.to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'iqf':
            from modelmasterapp.models import ModelMasterCreation
            # Pick Table
            pick_batches = ModelMasterCreation.objects.select_related('version', 'location').annotate(
                send_brass_audit_to_iqf=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('send_brass_audit_to_iqf')[:1]),
                iqf_hold_lot=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_hold_lot')[:1]),
                iqf_few_cases_acceptance=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_few_cases_acceptance')[:1])
            ).filter(send_brass_audit_to_iqf=True).exclude(lot_id__in=IQF_Accepted_TrayID_Store.objects.values_list('lot_id', flat=True))
            report_data = []
            for idx, batch in enumerate(pick_batches, start=1):
                try:
                    lot_id = batch.lot_id
                    accepted_scans = IQF_Accepted_TrayScan.objects.filter(lot_id=lot_id).values_list('accepted_tray_quantity', flat=True)
                    accept_qty = sum(int(qty) for qty in accepted_scans if qty and qty.isdigit()) or 0
                    rejected_scans = IQF_Rejected_TrayScan.objects.filter(lot_id=lot_id).values_list('rejected_tray_quantity', flat=True)
                    reject_qty = sum(int(qty) for qty in rejected_scans if qty and qty.isdigit()) or 0
                    last_updated = batch.date_time
                    lot_status = 'Hold' if batch.iqf_hold_lot else 'Active'
                    remarks = batch.holding_reason or batch.release_reason or ''
                    tray_cate_capacity = f"{batch.tray_type}-{batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ''
                    info = []
                    if batch.send_brass_audit_to_iqf: info.append("From Brass Audit")
                    if batch.iqf_hold_lot: info.append("Hold")
                    if batch.iqf_few_cases_acceptance: info.append("Few Cases Acceptance")
                    info_str = ', '.join(info)
                    no_of_trays = IQFTrayId.objects.filter(lot_id=lot_id).count()
                    physical_qty = IQFTrayId.objects.filter(lot_id=lot_id).aggregate(Sum('tray_quantity'))['tray_quantity__sum'] or 0
                    input_source = batch.location.location_name if batch.location else ''
                    row = {
                        'S.No': idx,
                        'Info': info_str,
                        'Last Updated': last_updated,
                        'Plating Stk No': batch.plating_stk_no or '',
                        'Polishing Stk No': batch.polishing_stk_no or '',
                        'Plating Color': batch.plating_color or '',
                        'Category': batch.category or '',
                        'Polish Finish': batch.polish_finish or '',
                        'Tray Cate-Capacity': tray_cate_capacity,
                        'Input Source': input_source,
                        'No of Trays': no_of_trays,
                        'RW Qty': batch.total_batch_quantity or 0,
                        'Physical Qty': physical_qty,
                        'Accept Qty': accept_qty,
                        'Reject Qty': reject_qty,
                        'Process Status': 'Pick',
                        'Action': '',
                    }
                    report_data.append(row)
                except Exception as e:
                    continue
            report_data = convert_datetimes(report_data)
            df = pd.DataFrame(report_data)
            if not df.empty:
                df.to_excel(writer, sheet_name='Pick Table', index=False)
            else:
                empty_df = pd.DataFrame(columns=['S.No', 'Info', 'Last Updated', 'Plating Stk No', 'Polishing Stk No', 'Plating Color', 'Category', 'Polish Finish', 'Tray Cate-Capacity', 'Input Source', 'No of Trays', 'RW Qty', 'Physical Qty', 'Accept Qty', 'Reject Qty', 'Process Status', 'Action'])
                empty_df.to_excel(writer, sheet_name='Pick Table', index=False)

            # Completed Table
            completed_lot_ids = IQF_Accepted_TrayID_Store.objects.values_list('lot_id', flat=True).distinct()
            completed_batches = ModelMasterCreation.objects.filter(lot_id__in=completed_lot_ids).select_related('version', 'location').annotate(
                iqf_hold_lot=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_hold_lot')[:1]),
                iqf_few_cases_acceptance=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_few_cases_acceptance')[:1])
            )
            report_data = []
            for idx, batch in enumerate(completed_batches, start=1):
                try:
                    lot_id = batch.lot_id
                    accepted_scans = IQF_Accepted_TrayScan.objects.filter(lot_id=lot_id).values_list('accepted_tray_quantity', flat=True)
                    accept_qty = sum(int(qty) for qty in accepted_scans if qty and qty.isdigit()) or 0
                    rejected_scans = IQF_Rejected_TrayScan.objects.filter(lot_id=lot_id).values_list('rejected_tray_quantity', flat=True)
                    reject_qty = sum(int(qty) for qty in rejected_scans if qty and qty.isdigit()) or 0
                    last_updated = batch.date_time
                    lot_status = 'Hold' if batch.iqf_hold_lot else 'Active'
                    remarks = batch.holding_reason or batch.release_reason or ''
                    tray_cate_capacity = f"{batch.tray_type}-{batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ''
                    info = []
                    if batch.iqf_hold_lot: info.append("Hold")
                    if batch.iqf_few_cases_acceptance: info.append("Few Cases Acceptance")
                    info_str = ', '.join(info)
                    no_of_trays = IQFTrayId.objects.filter(lot_id=lot_id).count()
                    physical_qty = IQFTrayId.objects.filter(lot_id=lot_id).aggregate(Sum('tray_quantity'))['tray_quantity__sum'] or 0
                    input_source = batch.location.location_name if batch.location else ''
                    row = {
                        'S.No': idx,
                        'Info': info_str,
                        'Last Updated': last_updated,
                        'Plating Stk No': batch.plating_stk_no or '',
                        'Polishing Stk No': batch.polishing_stk_no or '',
                        'Plating Color': batch.plating_color or '',
                        'Category': batch.category or '',
                        'Polish Finish': batch.polish_finish or '',
                        'Tray Cate-Capacity': tray_cate_capacity,
                        'Input Source': input_source,
                        'No of Trays': no_of_trays,
                        'RW Qty': batch.total_batch_quantity or 0,
                        'Physical Qty': physical_qty,
                        'Accept Qty': accept_qty,
                        'Reject Qty': reject_qty,
                        'Process Status': 'Completed',
                        'Action': '',
                        'Lot Status': lot_status,
                        'Current Stage': 'IQF Completed',
                        'Remarks': remarks,
                    }
                    report_data.append(row)
                except Exception as e:
                    continue
            report_data = convert_datetimes(report_data)
            df = pd.DataFrame(report_data)
            if not df.empty:
                df.to_excel(writer, sheet_name='Completed Table', index=False)
            else:
                empty_df = pd.DataFrame(columns=['S.No', 'Info', 'Last Updated', 'Plating Stk No', 'Polishing Stk No', 'Plating Color', 'Category', 'Polish Finish', 'Tray Cate-Capacity', 'Input Source', 'No of Trays', 'RW Qty', 'Physical Qty', 'Accept Qty', 'Reject Qty', 'Process Status', 'Action', 'Lot Status', 'Current Stage', 'Remarks'])
                empty_df.to_excel(writer, sheet_name='Completed Table', index=False)

            # Accept Table
            accept_lot_ids = IQF_Accepted_TrayScan.objects.values_list('lot_id', flat=True).distinct()
            accept_batches = ModelMasterCreation.objects.filter(lot_id__in=accept_lot_ids).select_related('version', 'location').annotate(
                iqf_hold_lot=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_hold_lot')[:1]),
                iqf_few_cases_acceptance=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_few_cases_acceptance')[:1])
            )
            report_data = []
            for idx, batch in enumerate(accept_batches, start=1):
                try:
                    lot_id = batch.lot_id
                    accepted_scans = IQF_Accepted_TrayScan.objects.filter(lot_id=lot_id).values_list('accepted_tray_quantity', flat=True)
                    accept_qty = sum(int(qty) for qty in accepted_scans if qty and qty.isdigit()) or 0
                    rejected_scans = IQF_Rejected_TrayScan.objects.filter(lot_id=lot_id).values_list('rejected_tray_quantity', flat=True)
                    reject_qty = sum(int(qty) for qty in rejected_scans if qty and qty.isdigit()) or 0
                    last_updated = batch.date_time
                    tray_cate_capacity = f"{batch.tray_type}-{batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ''
                    info = []
                    if batch.iqf_hold_lot: info.append("Hold")
                    if batch.iqf_few_cases_acceptance: info.append("Few Cases Acceptance")
                    info_str = ', '.join(info)
                    no_of_trays = IQFTrayId.objects.filter(lot_id=lot_id).count()
                    physical_qty = IQFTrayId.objects.filter(lot_id=lot_id).aggregate(Sum('tray_quantity'))['tray_quantity__sum'] or 0
                    input_source = batch.location.location_name if batch.location else ''
                    row = {
                        'S.No': idx,
                        'Info': info_str,
                        'Last Updated': last_updated,
                        'Plating Stk No': batch.plating_stk_no or '',
                        'Polishing Stk No': batch.polishing_stk_no or '',
                        'Plating Color': batch.plating_color or '',
                        'Category': batch.category or '',
                        'Polish Finish': batch.polish_finish or '',
                        'Tray Cate-Capacity': tray_cate_capacity,
                        'Input Source': input_source,
                        'No of Trays': no_of_trays,
                        'RW Qty': batch.total_batch_quantity or 0,
                        'Physical Qty': physical_qty,
                        'Accept Qty': accept_qty,
                        'Reject Qty': reject_qty,
                        'Process Status': 'Accept',
                        'Action': '',
                    }
                    report_data.append(row)
                except Exception as e:
                    continue
            report_data = convert_datetimes(report_data)
            df = pd.DataFrame(report_data)
            if not df.empty:
                df.to_excel(writer, sheet_name='Accept Table', index=False)
            else:
                empty_df = pd.DataFrame(columns=['S.No', 'Info', 'Last Updated', 'Plating Stk No', 'Polishing Stk No', 'Plating Color', 'Category', 'Polish Finish', 'Tray Cate-Capacity', 'Input Source', 'No of Trays', 'RW Qty', 'Physical Qty', 'Accept Qty', 'Reject Qty', 'Process Status', 'Action'])
                empty_df.to_excel(writer, sheet_name='Accept Table', index=False)

            # Reject Table
            reject_lot_ids = IQF_Rejected_TrayScan.objects.values_list('lot_id', flat=True).distinct()
            reject_batches = ModelMasterCreation.objects.filter(lot_id__in=reject_lot_ids).select_related('version', 'location').annotate(
                iqf_hold_lot=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_hold_lot')[:1]),
                iqf_few_cases_acceptance=Subquery(TotalStockModel.objects.filter(batch_id=OuterRef('pk')).values('iqf_few_cases_acceptance')[:1])
            )
            report_data = []
            for idx, batch in enumerate(reject_batches, start=1):
                try:
                    lot_id = batch.lot_id
                    accepted_scans = IQF_Accepted_TrayScan.objects.filter(lot_id=lot_id).values_list('accepted_tray_quantity', flat=True)
                    accept_qty = sum(int(qty) for qty in accepted_scans if qty and qty.isdigit()) or 0
                    rejected_scans = IQF_Rejected_TrayScan.objects.filter(lot_id=lot_id).values_list('rejected_tray_quantity', flat=True)
                    reject_qty = sum(int(qty) for qty in rejected_scans if qty and qty.isdigit()) or 0
                    last_updated = batch.date_time
                    tray_cate_capacity = f"{batch.tray_type}-{batch.tray_capacity}" if batch.tray_type and batch.tray_capacity else ''
                    info = []
                    if batch.iqf_hold_lot: info.append("Hold")
                    if batch.iqf_few_cases_acceptance: info.append("Few Cases Acceptance")
                    info_str = ', '.join(info)
                    no_of_trays = IQFTrayId.objects.filter(lot_id=lot_id).count()
                    physical_qty = IQFTrayId.objects.filter(lot_id=lot_id).aggregate(Sum('tray_quantity'))['tray_quantity__sum'] or 0
                    reject_reasons = IQF_Rejection_ReasonStore.objects.filter(lot_id=lot_id).values_list('rejection_reason__rejection_reason', flat=True)
                    reject_reason_str = ', '.join(reject_reasons) if reject_reasons else ''
                    lot_remark = ''
                    input_source = batch.location.location_name if batch.location else ''
                    row = {
                        'S.No': idx,
                        'Info': info_str,
                        'Last Updated': last_updated,
                        'Plating Stk No': batch.plating_stk_no or '',
                        'Polishing Stk No': batch.polishing_stk_no or '',
                        'Plating Color': batch.plating_color or '',
                        'Polish Finish': batch.polish_finish or '',
                        'Source - Location': input_source,
                        'Tray Type Capacity': tray_cate_capacity,
                        'Tray Cate-Capacity': tray_cate_capacity,
                        'Reject Qty': reject_qty,
                        'Reject Reason': reject_reason_str,
                        'Lot Remark': lot_remark,
                    }
                    report_data.append(row)
                except Exception as e:
                    continue
            report_data = convert_datetimes(report_data)
            df = pd.DataFrame(report_data)
            if not df.empty:
                df.to_excel(writer, sheet_name='Reject Table', index=False)
            else:
                empty_df = pd.DataFrame(columns=['S.No', 'Info', 'Last Updated', 'Plating Stk No', 'Polishing Stk No', 'Plating Color', 'Polish Finish', 'Source - Location', 'Tray Type Capacity', 'Tray Cate-Capacity', 'Reject Qty', 'Reject Reason', 'Lot Remark'])
                empty_df.to_excel(writer, sheet_name='Reject Table', index=False)

        elif module == 'brass-audit':
            from BrassAudit.models import Brass_Audit_Rejection_Table, Brass_Audit_Rejection_ReasonStore, Brass_Audit_Draft_Store
            from django.db.models import Exists, F, Q
            from django.utils import timezone

            # Pick Table - Similar to BrassAuditPickTableView
            brass_rejection_qty_subquery = Brass_Audit_Rejection_ReasonStore.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('total_rejection_quantity')[:1]

            has_draft_subquery = Exists(
                Brass_Audit_Draft_Store.objects.filter(
                    lot_id=OuterRef('lot_id')
                )
            )
            
            draft_type_subquery = Brass_Audit_Draft_Store.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('draft_type')[:1]

            pick_queryset = TotalStockModel.objects.select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).filter(
                batch_id__total_batch_quantity__gt=0
            ).annotate(
                wiping_required=F('batch_id__model_stock_no__wiping_required'),
                has_draft=has_draft_subquery,
                draft_type=draft_type_subquery,
                brass_rejection_total_qty=brass_rejection_qty_subquery,
            ).filter(
                Q(brass_qc_accptance=True, brass_audit_accptance__isnull=True) |
                Q(brass_qc_accptance=True, brass_audit_accptance=False) |
                Q(brass_qc_few_cases_accptance=True, brass_onhold_picking=False)|
                Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=True)
            ).exclude(
                brass_audit_accptance=True
            ).exclude(
                brass_audit_rejection=True
            ).exclude(
                Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False)
            ).order_by('-bq_last_process_date_time', '-lot_id')

            report_data_pick = []
            for idx, stock_obj in enumerate(pick_queryset, start=1):
                batch = stock_obj.batch_id
                no_of_trays = BrassAuditTrayId.objects.filter(lot_id=stock_obj.lot_id).count()
                data = {
                    'S.No': idx,
                    'Last Updated': stock_obj.bq_last_process_date_time.strftime('%d-%b-%y %I:%M %p') if stock_obj.bq_last_process_date_time else '',
                    'Plating Stk No': batch.plating_stk_no,
                    'Polishing Stk No': batch.polishing_stk_no,
                    'Plating Color': batch.plating_color,
                    'Category': batch.category,
                    'Polish Finish': batch.polish_finish,
                    'Tray Cate-Capacity': f"{batch.tray_type}-{batch.tray_capacity}" if batch.tray_type else '',
                    'Input Source': batch.location.location_name if batch.location else '',
                    'No of Trays': no_of_trays,
                    'Lot Qty': stock_obj.brass_qc_accepted_qty or 0,
                    'Physical Qty': stock_obj.brass_audit_physical_qty or 0,
                    'Accept Qty': stock_obj.brass_audit_accepted_qty or 0,
                    'Reject Qty': stock_obj.brass_rejection_total_qty or 0,
                    'Process Status': 'QC',
                    'Action': 'Delete Disabled   View',
                    'Lot Status': 'Yet to Start',
                    'Current Stage': 'Brass QC',
                    'Remarks': stock_obj.BA_pick_remarks or ''
                }
                report_data_pick.append(data)
            
            df_pick = pd.DataFrame(report_data_pick)
            if len(df_pick) > 0:
                df_pick.to_excel(writer, sheet_name='Pick Table', index=False)
            else:
                # Create empty sheet with headers if no data
                empty_df = pd.DataFrame(columns=['S.No', 'Last Updated', 'Plating Stk No', 'Polishing Stk No', 'Plating Color', 'Category', 'Polish Finish', 'Tray Cate-Capacity', 'Input Source', 'No of Trays', 'Lot Qty', 'Physical Qty', 'Accept Qty', 'Reject Qty', 'Process Status', 'Action', 'Lot Status', 'Current Stage', 'Remarks'])
                empty_df.to_excel(writer, sheet_name='Pick Table', index=False)

            # Completed Table - Similar to BrassAuditCompletedView
            tz = pytz.timezone("Asia/Kolkata")
            now_local = timezone.now().astimezone(tz)
            today = now_local.date()
            yesterday = today - timedelta(days=1)
            from_date = yesterday
            to_date = today
            from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
            to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))

            brass_rejection_qty_subquery_comp = Brass_Audit_Rejection_ReasonStore.objects.filter(
                lot_id=OuterRef('lot_id')
            ).values('total_rejection_quantity')[:1]

            completed_queryset = TotalStockModel.objects.select_related(
                'batch_id',
                'batch_id__model_stock_no',
                'batch_id__version',
                'batch_id__location'
            ).filter(
                batch_id__total_batch_quantity__gt=0,
                brass_audit_last_process_date_time__range=(from_datetime, to_datetime)
            ).annotate(
                brass_rejection_qty=brass_rejection_qty_subquery_comp,
            ).filter(
                Q(brass_audit_accptance=True) |
                Q(brass_audit_rejection=True) |
                Q(brass_audit_few_cases_accptance=True, brass_audit_onhold_picking=False) |
                Q(send_brass_audit_to_iqf=True, brass_audit_onhold_picking=False)
            ).order_by('-brass_audit_last_process_date_time')

            report_data_completed = []
            for idx, stock_obj in enumerate(completed_queryset, start=1):
                batch = stock_obj.batch_id
                no_of_trays = BrassAuditTrayId.objects.filter(lot_id=stock_obj.lot_id).count()
                data = {
                    'S.No': idx,
                    'Last Updated': stock_obj.brass_audit_last_process_date_time.strftime('%d-%b-%y %I:%M %p') if stock_obj.brass_audit_last_process_date_time else '',
                    'Plating Stk No': batch.plating_stk_no,
                    'Polishing Stk No': batch.polishing_stk_no,
                    'Plating Color': batch.plating_color,
                    'Category': batch.category,
                    'Polish Finish': batch.polish_finish,
                    'Tray Cate-Capacity': f"{batch.tray_type}-{batch.tray_capacity}" if batch.tray_type else '',
                    'Input Source': batch.location.location_name if batch.location else '',
                    'No of Trays': no_of_trays,
                    'Lot Qty': stock_obj.brass_qc_accepted_qty or 0,
                    'Physical Qty': stock_obj.brass_audit_physical_qty or 0,
                    'Accept Qty': stock_obj.brass_audit_accepted_qty or 0,
                    'Reject Qty': stock_obj.brass_rejection_qty or 0,
                    'Process Status': 'QC',
                    'Action': 'Delete Disabled   View',
                    'Lot Status': 'Completed' if stock_obj.brass_audit_accptance else 'Rejected',
                    'Current Stage': 'Brass Audit',
                    'Remarks': ''
                }
                report_data_completed.append(data)
            
            df_completed = pd.DataFrame(report_data_completed)
            if len(df_completed) > 0:
                df_completed.to_excel(writer, sheet_name='Completed Table', index=False)
            else:
                # Create empty sheet with headers if no data
                empty_df = pd.DataFrame(columns=['S.No', 'Last Updated', 'Plating Stk No', 'Polishing Stk No', 'Plating Color', 'Category', 'Polish Finish', 'Tray Cate-Capacity', 'Input Source', 'No of Trays', 'Lot Qty', 'Physical Qty', 'Accept Qty', 'Reject Qty', 'Process Status', 'Action', 'Lot Status', 'Current Stage', 'Remarks'])
                empty_df.to_excel(writer, sheet_name='Completed Table', index=False)

            # Rejected Table - Aggregated from Brass_Audit_Rejected_TrayScan
            rejected_queryset = Brass_Audit_Rejected_TrayScan.objects.values('lot_id').distinct().order_by('lot_id')

            report_data_rejected = []
            for idx, reject_obj in enumerate(rejected_queryset, start=1):
                # Get batch info from TotalStockModel
                stock_obj = TotalStockModel.objects.filter(lot_id=reject_obj['lot_id']).select_related('batch_id').first()
                if stock_obj:
                    batch = stock_obj.batch_id
                    # Get all rejected trays for this lot
                    rejected_trays = Brass_Audit_Rejected_TrayScan.objects.filter(lot_id=reject_obj['lot_id'])
                    reject_reasons = rejected_trays.values_list('rejection_reason__rejection_reason', flat=True).distinct()
                    # Sum the rejected quantities
                    total_reject_qty = sum(int(tray.rejected_tray_quantity) if tray.rejected_tray_quantity.isdigit() else 0 for tray in rejected_trays)
                    no_of_trays = BrassAuditTrayId.objects.filter(lot_id=reject_obj['lot_id']).count()
                    data = {
                        'S.No': idx,
                        'Last Updated': stock_obj.brass_audit_last_process_date_time.strftime('%d-%b-%y %I:%M %p') if stock_obj.brass_audit_last_process_date_time else '',
                        'Plating Stk No': batch.plating_stk_no,
                        'Polish Stk No': batch.polishing_stk_no,
                        'Plating Color': batch.plating_color,
                        'Polish Finish': batch.polish_finish,
                        'Source - Location': batch.location.location_name if batch.location else '',
                        'Tray Type Capacity': f"{batch.tray_type}-{batch.tray_capacity}" if batch.tray_type else '',
                        'No of Trays': no_of_trays,
                        'Reject Qty': total_reject_qty,
                        'Reject Reason': ', '.join(set(reject_reasons)),
                        'Lot Remark': Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=reject_obj['lot_id']).first().lot_rejected_comment if Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=reject_obj['lot_id']).exists() else ''
                    }
                    report_data_rejected.append(data)
            
            df_rejected = pd.DataFrame(report_data_rejected)
            if len(df_rejected) > 0:
                df_rejected.to_excel(writer, sheet_name='Rejected Table', index=False)
            else:
                # Create empty sheet with headers if no data
                empty_df = pd.DataFrame(columns=['S.No', 'Last Updated', 'Plating Stk No', 'Polish Stk No', 'Plating Color', 'Polish Finish', 'Source - Location', 'Tray Type Capacity', 'No of Trays', 'Reject Qty', 'Reject Reason', 'Lot Remark'])
                empty_df.to_excel(writer, sheet_name='Rejected Table', index=False)

        elif module == 'recovery-day-planning':
            # Pick Table
            from Recovery_DP.models import RecoveryTrayId_History
            dp_trays = convert_datetimes(list(RecoveryTrayId_History.objects.all().values()))
            pd.DataFrame(dp_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Completed Table
            completed_trays = convert_datetimes(list(RecoveryTrayId_History.objects.filter(scanned=True).values()))
            pd.DataFrame(completed_trays).to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'recovery-input-screening':
            # Pick Table
            from Recovery_IS.models import RecoveryIPTrayId
            ip_trays = convert_datetimes(list(RecoveryIPTrayId.objects.all().values()))
            pd.DataFrame(ip_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Accept Table
            from Recovery_IS.models import RecoveryIP_Accepted_TrayScan
            accepted = convert_datetimes(list(RecoveryIP_Accepted_TrayScan.objects.all().values()))
            pd.DataFrame(accepted).to_excel(writer, sheet_name='Accept Table', index=False)
            
            # Reject Table
            from Recovery_IS.models import RecoveryIP_Rejected_TrayScan
            rejected = convert_datetimes(list(RecoveryIP_Rejected_TrayScan.objects.all().values()))
            pd.DataFrame(rejected).to_excel(writer, sheet_name='Reject Table', index=False)
            
            # Completed Table
            from Recovery_IS.models import RecoveryIP_Accepted_TrayID_Store
            completed = convert_datetimes(list(RecoveryIP_Accepted_TrayID_Store.objects.all().values()))
            pd.DataFrame(completed).to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'recovery-brass-qc':
            # Pick Table
            from Recovery_Brass_QC.models import BrassTrayId as RecoveryBrassTrayId
            brass_trays = convert_datetimes(list(RecoveryBrassTrayId.objects.all().values()))
            pd.DataFrame(brass_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Accept Table
            from Recovery_Brass_QC.models import Brass_Qc_Accepted_TrayScan as RecoveryBrass_Qc_Accepted_TrayScan
            accepted = convert_datetimes(list(RecoveryBrass_Qc_Accepted_TrayScan.objects.all().values()))
            pd.DataFrame(accepted).to_excel(writer, sheet_name='Accept Table', index=False)
            
            # Reject Table
            from Recovery_Brass_QC.models import Brass_QC_Rejected_TrayScan as RecoveryBrass_QC_Rejected_TrayScan
            rejected = convert_datetimes(list(RecoveryBrass_QC_Rejected_TrayScan.objects.all().values()))
            pd.DataFrame(rejected).to_excel(writer, sheet_name='Reject Table', index=False)
            
            # Completed Table
            from Recovery_Brass_QC.models import Brass_Qc_Accepted_TrayID_Store as RecoveryBrass_Qc_Accepted_TrayID_Store
            completed = convert_datetimes(list(RecoveryBrass_Qc_Accepted_TrayID_Store.objects.all().values()))
            pd.DataFrame(completed).to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'recovery-iqf':
            # Pick Table
            from Recovery_IQF.models import IQFTrayId as RecoveryIQFTrayId
            iqf_trays = convert_datetimes(list(RecoveryIQFTrayId.objects.all().values()))
            pd.DataFrame(iqf_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Accept Table
            from Recovery_IQF.models import IQF_Accepted_TrayScan as RecoveryIQF_Accepted_TrayScan
            accepted = convert_datetimes(list(RecoveryIQF_Accepted_TrayScan.objects.all().values()))
            pd.DataFrame(accepted).to_excel(writer, sheet_name='Accept Table', index=False)
            
            # Reject Table
            from Recovery_IQF.models import IQF_Rejected_TrayScan as RecoveryIQF_Rejected_TrayScan
            rejected = convert_datetimes(list(RecoveryIQF_Rejected_TrayScan.objects.all().values()))
            pd.DataFrame(rejected).to_excel(writer, sheet_name='Reject Table', index=False)
            
            # Completed Table
            from Recovery_IQF.models import IQF_Accepted_TrayID_Store as RecoveryIQF_Accepted_TrayID_Store
            completed = convert_datetimes(list(RecoveryIQF_Accepted_TrayID_Store.objects.all().values()))
            pd.DataFrame(completed).to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'recovery-brass-audit':
            # Pick Table
            from Recovery_BrassAudit.models import BrassAuditTrayId as RecoveryBrassAuditTrayId
            audit_trays = convert_datetimes(list(RecoveryBrassAuditTrayId.objects.all().values()))
            pd.DataFrame(audit_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Accept Table
            from Recovery_BrassAudit.models import Brass_Audit_Accepted_TrayScan as RecoveryBrass_Audit_Accepted_TrayScan
            accepted = convert_datetimes(list(RecoveryBrass_Audit_Accepted_TrayScan.objects.all().values()))
            pd.DataFrame(accepted).to_excel(writer, sheet_name='Accept Table', index=False)
            
            # Reject Table
            from Recovery_BrassAudit.models import Brass_Audit_Rejected_TrayScan as RecoveryBrass_Audit_Rejected_TrayScan
            rejected = convert_datetimes(list(RecoveryBrass_Audit_Rejected_TrayScan.objects.all().values()))
            pd.DataFrame(rejected).to_excel(writer, sheet_name='Reject Table', index=False)
            
            # Completed Table
            from Recovery_BrassAudit.models import Brass_Audit_Accepted_TrayID_Store as RecoveryBrass_Audit_Accepted_TrayID_Store
            completed = convert_datetimes(list(RecoveryBrass_Audit_Accepted_TrayID_Store.objects.all().values()))
            pd.DataFrame(completed).to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'jig-loading':
            # Pick Table
            from Jig_Loading.models import JigLoadTrayId
            jig_trays = convert_datetimes(list(JigLoadTrayId.objects.all().values()))
            pd.DataFrame(jig_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # For jig loading, completed might be the same as pick table
            completed_trays = convert_datetimes(list(JigLoadTrayId.objects.all().values()))
            pd.DataFrame(completed_trays).to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'inprocess-inspection':
            # Inprocess inspection might not have separate tables, just use a placeholder
            pd.DataFrame([{'message': 'Inprocess Inspection data not implemented yet'}]).to_excel(writer, sheet_name='Data', index=False)

        elif module == 'jig-unloading':
            # Similar to jig loading
            pd.DataFrame([{'message': 'Jig Unloading data not implemented yet'}]).to_excel(writer, sheet_name='Data', index=False)

        elif module == 'nickel-inspection':
            # Pick Table
            from Nickel_Inspection.models import NickelQcTrayId
            nickel_trays = convert_datetimes(list(NickelQcTrayId.objects.all().values()))
            pd.DataFrame(nickel_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Accept Table
            from modelmasterapp.models import Nickle_IP_Accepted_TrayScan
            accepted = convert_datetimes(list(Nickle_IP_Accepted_TrayScan.objects.all().values()))
            pd.DataFrame(accepted).to_excel(writer, sheet_name='Accept Table', index=False)
            
            # Reject Table
            from modelmasterapp.models import Nickle_IP_Rejected_TrayScan
            rejected = convert_datetimes(list(Nickle_IP_Rejected_TrayScan.objects.all().values()))
            pd.DataFrame(rejected).to_excel(writer, sheet_name='Reject Table', index=False)
            
            # Completed Table
            from modelmasterapp.models import Nickle_IP_Accepted_TrayID_Store
            completed = convert_datetimes(list(Nickle_IP_Accepted_TrayID_Store.objects.all().values()))
            pd.DataFrame(completed).to_excel(writer, sheet_name='Completed Table', index=False)

        elif module == 'nickel-audit':
            # Pick Table
            from Nickel_Audit.models import Nickel_AuditTrayId
            nickel_audit_trays = convert_datetimes(list(Nickel_AuditTrayId.objects.all().values()))
            pd.DataFrame(nickel_audit_trays).to_excel(writer, sheet_name='Pick Table', index=False)
            
            # Accept Table
            from modelmasterapp.models import Nickle_Audit_Accepted_TrayScan
            accepted = convert_datetimes(list(Nickle_Audit_Accepted_TrayScan.objects.all().values()))
            pd.DataFrame(accepted).to_excel(writer, sheet_name='Accept Table', index=False)
            
            # Reject Table
            from modelmasterapp.models import Nickle_Audit_Rejected_TrayScan
            rejected = convert_datetimes(list(Nickle_Audit_Rejected_TrayScan.objects.all().values()))
            pd.DataFrame(rejected).to_excel(writer, sheet_name='Reject Table', index=False)
            
            # Completed Table
            from modelmasterapp.models import Nickle_Audit_Accepted_TrayID_Store
            completed = convert_datetimes(list(Nickle_Audit_Accepted_TrayID_Store.objects.all().values()))
            pd.DataFrame(completed).to_excel(writer, sheet_name='Completed Table', index=False)

    output.seek(0)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename={module}_report.xlsx'
    response['Content-Length'] = len(output.getvalue())
    # Clear buffer to prevent buffering
    output.close()
    return response
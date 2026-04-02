from django.urls import path

from DayPlanning import views
from .views import *

urlpatterns = [
    path('brass_audit_picktable/', BrassAuditPickTableView.as_view(), name='brass_audit_picktable'),
    path('brass_audit_completed/', BrassAuditCompletedView.as_view(), name='brass_audit_completed'),
    path('brass_audit_rejection/', BrassAuditRejectTableView.as_view(), name='brass_audit_rejection'),

    path('brass_audit_save_hold_unhold_reason/', BrassAudit_SaveHoldUnholdReasonAPIView.as_view(), name='brass_audit_save_hold_unhold_reason'),
    path('brass_get_tray_capacity_for_lot/', brass_get_tray_capacity_for_lot, name='brass_get_tray_capacity_for_lot'),
    path('brass_audit_save_ip_checkbox/', BrassAudit_SaveIPCheckboxView.as_view(), name='brass_audit_save_ip_checkbox'),
    path('brass_save_ip_pick_remark/', BrassSaveIPPickRemarkAPIView.as_view(), name='brass_save_ip_pick_remark'),
    path('brass_delete_batch/', BQDeleteBatchAPIView.as_view(), name='brass_delete_batch'),
    path('brass_audit_accepted_form/', Brass_Audit_Accepted_form.as_view(), name='brass_audit_accepted_form'),
    
    path('brass_audit_batch_rejection/', BAuditBatchRejectionAPIView.as_view(), name='brass_audit_batch_rejection'),
    path('brass_audit_tray_rejection/', BrassAudit_TrayRejectionAPIView.as_view(), name='brass_audit_tray_rejection'),
    path('brass_audit_reject_check_tray_id/', brass_audit_reject_check_tray_id, name='brass_audit_reject_check_tray_id'),
    path('brass_audit_get_accepted_tray_scan_data/', brass_audit_get_accepted_tray_scan_data, name='brass_audit_get_accepted_tray_scan_data'),
    path('brass_audit_view_tray_list/', brass_audit_view_tray_list, name='brass_audit_view_tray_list'),
    path('brass_audit_save_accepted_tray_scan/', brass_audit_save_accepted_tray_scan, name='brass_audit_save_accepted_tray_scan'),
    path('brass_audit_check_tray_id/', brass_audit_check_tray_id, name='brass_audit_check_tray_id'),
    path('brass_audit_get_rejected_tray_scan_data/', brass_audit_get_rejected_tray_scan_data, name='brass_audit_get_rejected_tray_scan_data'),
    path('brass_audit_tray_validate/', BrassAudit_TrayValidateAPIView.as_view(), name='brass_audit_tray_validate'),
    path('brass_audit_save_single_top_tray_scan/', brass_audit_save_single_top_tray_scan, name='brass_audit_save_single_top_tray_scan'),
    path('brass_audit_reject_check_tray_id_simple/', brass_audit_reject_check_tray_id_simple, name='brass_audit_reject_check_tray_id_simple'),
     
    path('brass_audit_get_delink_tray_data/', brass_audit_get_delink_tray_data, name='brass_audit_get_delink_tray_data'),
    path('brass_audit_delink_check_tray_id/', brass_audit_delink_check_tray_id, name='brass_audit_delink_check_tray_id'),
    
    path('brass_CompleteTable_tray_id_list/', BrassTrayIdList_Complete_APIView.as_view(), name='brass_CompleteTable_tray_id_list'),
    path('brass_complete_tray_validate/', BrassTrayValidate_Complete_APIView.as_view(), name='brass_complete_tray_validate'),

    # Draft functionality endpoints
    path('brass_audit_batch_rejection_draft/', BrassAuditBatchRejectionDraftAPIView.as_view(), name='brass_audit_batch_rejection_draft'),
    path('brass_audit_tray_rejection_draft/', BrassTrayRejectionDraftAPIView.as_view(), name='brass_audit_tray_rejection_draft'),
    path('brass_audit_auto_save_rejection/', BrassAuditAutoSaveRejectionAPIView.as_view(), name='brass_audit_auto_save_rejection'),
    path('brass_get_draft_data/', brass_get_draft_data, name='brass_get_draft_data'),
    path('brass_clear_draft/', BrassClearDraftAPIView.as_view(), name='brass_clear_draft'),
    path('brass_get_all_drafts/', brass_get_all_drafts, name='brass_get_all_drafts'),

    path('brass_audit_get_top_tray_scan_draft/', brass_audit_get_top_tray_scan_draft, name='brass_audit_get_top_tray_scan_draft'),
    path('brass_clear_top_tray_draft/', brass_clear_top_tray_draft, name='brass_clear_top_tray_draft'),
    
    #Pick table Vlaidation
    path('pick_complete_tray_validate/', PickTrayValidate_Complete_APIView.as_view(), name='pick_complete_tray_validate'),
    path('pick_CompleteTable_tray_id_list/', PickTrayIdList_Complete_APIView.as_view(), name='pick_CompleteTable_tray_id_list'),

    #After tray validation  check
    path('AfterCheck_complete_tray_validate/', AfterCheckTrayValidate_Complete_APIView.as_view(), name='AfterCheck_complete_tray_validate'),
    path('AfterCheck_pick_CompleteTable_tray_id_list/', AfterCheckPickTrayIdList_Complete_APIView.as_view(), name='AfterCheck_pick_CompleteTable_tray_id_list'),
    path('RejectTable_tray_id_list/', RejectTableTrayIdListAPIView.as_view(), name='RejectTable_tray_id_list'),
    path('Reject_tray_validate/', RejectCheckTrayValidate_Complete_APIView.as_view(), name='Reject_tray_validate'),

    path('brass_get_rejection_details/', brass_get_rejection_details, name='brass_get_rejection_details'),

    path('brass_audit_tray_delink_top_tray_calc/', BATrayDelinkTopTrayCalcAPIView.as_view(), name='brass_audit_tray_delink_top_tray_calc'),
    path('brass_audit_validate_tray_id/',BAValidateTrayIdAPIView.as_view(), name='brass_audit_validate_tray_id'),
    path('brass_audit_tray_delink_and_top_tray_update/', BATrayDelinkAndTopTrayUpdateAPIView.as_view(), name='brass_audit_tray_delink_and_top_tray_update'),

    # Barcode scanner API endpoint
    path('get_lot_id_for_tray/', get_lot_id_for_tray, name='get_lot_id_for_tray'),

    path('get_tray_details_for_modal/', get_brass_audit_tray_details_for_modal, name='get_brass_audit_tray_details_for_modal'),

]
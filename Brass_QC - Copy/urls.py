from django.urls import path

from DayPlanning import views
from .views import *

urlpatterns = [
    path('brass_picktable/', BrassPickTableView.as_view(), name='BrassPickTableView'),
    path('brass_completed/', BrassCompletedView.as_view(), name='BrassCompletedView'),
    path('brass_save_hold_unhold_reason/', BrassSaveHoldUnholdReasonAPIView.as_view(), name='brass_save_hold_unhold_reason'),
    path('brass_get_tray_capacity_for_lot/', brass_get_tray_capacity_for_lot, name='brass_get_tray_capacity_for_lot'),
    path('brass_save_ip_checkbox/', BrassSaveIPCheckboxView.as_view(), name='brass_save_ip_checkbox'),
    path('brass_save_ip_pick_remark/', BrassSaveIPPickRemarkAPIView.as_view(), name='brass_save_ip_pick_remark'),
    path('brass_delete_batch/', BQDeleteBatchAPIView.as_view(), name='brass_delete_batch'),
    path('brass_accepted_form/', BQ_Accepted_form.as_view(), name='brass_accepted_form'),

    path('brass_batch_rejection/', BQBatchRejectionAPIView.as_view(), name='brass_batch_rejection'),
    path('brass_tray_rejection/', BQTrayRejectionAPIView.as_view(), name='brass_tray_rejection'),
    path('brass_reject_check_tray_id/', brass_reject_check_tray_id, name='brass_reject_check_tray_id'),
    path('brass_get_accepted_tray_scan_data/', brass_get_accepted_tray_scan_data, name='brass_get_accepted_tray_scan_data'),
    path('brass_view_tray_list/', brass_view_tray_list, name='brass_view_tray_list'),
    path('brass_save_accepted_tray_scan/', brass_save_accepted_tray_scan, name='brass_save_accepted_tray_scan'),
    path('brass_check_tray_id/', brass_check_tray_id, name='brass_check_tray_id'),
    path('brass_get_rejected_tray_scan_data/', brass_get_rejected_tray_scan_data, name='brass_get_rejected_tray_scan_data'),
    path('brass_tray_validate/', BrassTrayValidateAPIView.as_view(), name='brass_tray_validate'),
    path('brass_save_single_top_tray_scan/', brass_save_single_top_tray_scan, name='brass_save_single_top_tray_scan'),
    path('brass_reject_check_tray_id_simple/', brass_reject_check_tray_id_simple, name='brass_reject_check_tray_id_simple'),
    path('brass_validate_scenario_reuse/', brass_validate_scenario_reuse, name='brass_validate_scenario_reuse'),
    
    path('brass_get_delink_tray_data/', brass_get_delink_tray_data, name='brass_get_delink_tray_data'),
    path('brass_delink_check_tray_id/', brass_delink_check_tray_id, name='brass_delink_check_tray_id'),
    path('brass_top_tray_check_tray_id/', brass_top_tray_check_tray_id, name='brass_top_tray_check_tray_id'),
    
    path('fetch_delink_calculation_for_batch_rejection/', fetch_delink_calculation_for_batch_rejection, name='fetch_delink_calculation_for_batch_rejection'),
    
    path('brass_CompleteTable_tray_id_list/', BrassTrayIdList_Complete_APIView.as_view(), name='brass_CompleteTable_tray_id_list'),
    path('brass_complete_tray_validate/', BrassTrayValidate_Complete_APIView.as_view(), name='brass_complete_tray_validate'),

    # Draft functionality endpoints
    path('brass_batch_rejection_draft/', BrassBatchRejectionDraftAPIView.as_view(), name='brass_batch_rejection_draft'),
    path('brass_tray_rejection_draft/', BrassTrayRejectionDraftAPIView.as_view(), name='brass_tray_rejection_draft'),
    path('brass_get_draft_data/', brass_get_draft_data, name='brass_get_draft_data'),
    path('brass_clear_draft/', BrassClearDraftAPIView.as_view(), name='brass_clear_draft'),
    path('brass_get_all_drafts/', brass_get_all_drafts, name='brass_get_all_drafts'),

    path('brass_get_top_tray_scan_draft/', brass_get_top_tray_scan_draft, name='brass_get_top_tray_scan_draft'),
    
    #Pick table Vlaidation
    path('pick_complete_tray_validate/', PickTrayValidate_Complete_APIView.as_view(), name='pick_complete_tray_validate'),
    path('pick_CompleteTable_tray_id_list/', PickTrayIdList_Complete_APIView.as_view(), name='pick_CompleteTable_tray_id_list'),

    #After tray validation  check
    path('AfterCheck_complete_tray_validate/', AfterCheckTrayValidate_Complete_APIView.as_view(), name='AfterCheck_complete_tray_validate'),
    path('AfterCheck_pick_CompleteTable_tray_id_list/', AfterCheckPickTrayIdList_Complete_APIView.as_view(), name='AfterCheck_pick_CompleteTable_tray_id_list'),

    path('get_tray_details_for_modal/', get_brass_qc_tray_details_for_modal, name='get_brass_qc_tray_details_for_modal'),
    
    path('brass_tray_delink_top_tray_calc/', BrassTrayDelinkTopTrayCalcAPIView.as_view(), name='brass_tray_delink_calc'),
    path('brass_validate_tray_id/',BrassValidateTrayIdAPIView.as_view(), name='brass_validate_tray_id'),
    path('brass_tray_delink_and_top_tray_update/', BrassTrayDelinkAndTopTrayUpdateAPIView.as_view(), name='brass_tray_delink_and_top_tray_update'),
    
    path('get_rejection_remarks/', brass_get_rejection_remarks, name='brass_get_rejection_remarks'),
    
        # Barcode scanner API endpoint
    path('brass_qc_get_lot_id_for_tray/', brass_qc_get_lot_id_for_tray, name='brass_qc_get_lot_id_for_tray'),
    
    # Auto-save endpoints
    path('brass_save_rejection_draft/', BrassSaveRejectionDraftAPIView.as_view(), name='brass_save_rejection_draft'),
    path('brass_save_accepted_tray_draft/', BrassSaveAcceptedTrayDraftAPIView.as_view(), name='brass_save_accepted_tray_draft'),
    path('brass_set_manual_draft/', BrassSetManualDraftAPIView.as_view(), name='brass_set_manual_draft'),
    
    # Debug endpoint
    # path('brass_debug_remarks/', brass_debug_remarks, name='brass_debug_remarks'),
    

]
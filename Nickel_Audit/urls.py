from django.urls import path

from DayPlanning import views
from .views import *

urlpatterns = [
    path('NA_Inspection/', NA_PickTableView.as_view(), name='NA_Inspection'),
    path('NA_Completed/', NACompletedView.as_view(), name='NA_Completed'),
    path('na_save_hold_unhold_reason/', NASaveHoldUnholdReasonAPIView.as_view(), name='na_save_hold_unhold_reason'),
    path('brass_get_tray_capacity_for_lot/', brass_get_tray_capacity_for_lot, name='brass_get_tray_capacity_for_lot'),
    path('na_save_ip_checkbox/', NASaveIPCheckboxView.as_view(), name='na_save_ip_checkbox'),
    path('na_save_ip_pick_remark/', NASaveIPPickRemarkAPIView.as_view(), name='na_save_ip_pick_remark'),
    path('na_delete_batch/', NADeleteBatchAPIView.as_view(), name='na_delete_batch'),
    path('na_accepted_form/', NA_Accepted_form.as_view(), name='na_accepted_form'),
    
    path('na_batch_rejection/', NABatchRejectionAPIView.as_view(), name='na_batch_rejection'),
    path('na_tray_rejection/', NATrayRejectionAPIView.as_view(), name='na_tray_rejection'),
    path('nickel_qc_reject_check_tray_id/', nickel_qc_reject_check_tray_id, name='nickel_qc_reject_check_tray_id'),
    path('nickel_get_accepted_tray_scan_data/', nickel_get_accepted_tray_scan_data, name='nickel_get_accepted_tray_scan_data'),
    path('nickel_view_tray_list/', nickel_view_tray_list, name='nickel_view_tray_list'),
    path('nickel_save_accepted_tray_scan/', nickel_save_accepted_tray_scan, name='nickel_save_accepted_tray_scan'),
    path('nickel_check_tray_id/', nickel_check_tray_id, name='nickel_check_tray_id'),
    path('nickel_get_rejected_tray_scan_data/', nickel_get_rejected_tray_scan_data, name='nickel_get_rejected_tray_scan_data'),
    path('nickel_qc_tray_validate/', NickelTrayValidateAPIView.as_view(), name='nickel_qc_tray_validate'),
    path('nickel_save_single_top_tray_scan/', nickel_save_single_top_tray_scan, name='nickel_save_single_top_tray_scan'),
    path('nickel_qc_reject_check_tray_id_simple/', nickel_qc_reject_check_tray_id_simple, name='nickel_qc_reject_check_tray_id_simple'),

    path('nickel_qc_get_delink_tray_data/', nickel_qc_get_delink_tray_data, name='nickel_qc_get_delink_tray_data'),
    path('nickel_delink_check_tray_id/', nickel_delink_check_tray_id, name='nickel_delink_check_tray_id'),
    
    path('brass_CompleteTable_tray_id_list/', BrassTrayIdList_Complete_APIView.as_view(), name='brass_CompleteTable_tray_id_list'),
    path('brass_complete_tray_validate/', BrassTrayValidate_Complete_APIView.as_view(), name='brass_complete_tray_validate'),

    # Draft functionality endpoints
    path('na_batch_rejection_draft/', NQBatchRejectionDraftAPIView.as_view(), name='na_batch_rejection_draft'),
    path('na_tray_rejection_draft/', BATrayRejectionDraftAPIView.as_view(), name='na_tray_rejection_draft'),
    path('nickel_get_draft_data/', nickel_get_draft_data, name='nickel_get_draft_data'),
    path('nickel_clear_draft/', NickelClearDraftAPIView.as_view(), name='nickel_clear_draft'),
    path('NA_get_all_drafts/', NA_get_all_drafts, name='NA_get_all_drafts'),
    path('nickel_get_top_tray_scan_draft/', nickel_get_top_tray_scan_draft, name='nickel_get_top_tray_scan_draft'),

    #Pick table Vlaidation
    path('pick_complete_tray_validate/', PickTrayValidate_Complete_APIView.as_view(), name='pick_complete_tray_validate'),
    path('pick_CompleteTable_tray_id_list/', PickTrayIdList_Complete_APIView.as_view(), name='pick_CompleteTable_tray_id_list'),

    path('na_tray_delink_top_tray_calc/', NATrayDelinkTopTrayCalcAPIView.as_view(), name='na_tray_delink_top_tray_calc'),
    path('na_validate_tray_id/',NAValidateTrayIdAPIView.as_view(), name='na_validate_tray_id'),
    path('na_tray_delink_and_top_tray_update/', NATrayDelinkAndTopTrayUpdateAPIView.as_view(), name='na_tray_delink_and_top_tray_update'),

    path('na_get_lot_id_for_tray/', na_get_lot_id_for_tray, name='na_get_lot_id_for_tray'),

]
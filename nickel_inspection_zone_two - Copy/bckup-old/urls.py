from django.urls import path

from DayPlanning import views
from .views import *

urlpatterns = [
    path('NQ_Zone_PickTable/', NQ_Zone_PickTableView.as_view(), name='NQ_Zone_PickTable'),
    path('NQ_Zone_Completed/', NQ_Zone_CompletedView.as_view(), name='NQ_Zone_Completed'),
    path('nq_zone_save_hold_unhold_reason/', NQ_Zone_HoldUnholdReasonAPIView.as_view(), name='nq_zone_save_hold_unhold_reason'),
    path('nq_zone_get_tray_capacity_for_lot/', nq_zone_get_tray_capacity_for_lot, name='nq_zone_get_tray_capacity_for_lot'),
    path('nq_zone_save_ip_checkbox/', NQ_Zone_SaveIPCheckboxView.as_view(), name='nq_zone_save_ip_checkbox'),
    path('nq_zone_save_ip_pick_remark/', NQ_Zone_SaveIPPickRemarkAPIView.as_view(), name='nq_zone_save_ip_pick_remark'),
    path('nq_zone_delete_batch/', NQ_Zone_DeleteBatchAPIView.as_view(), name='nq_zone_delete_batch'),
    path('nq_zone_accepted_form/', NQ_Zone_Accepted_form.as_view(), name='nq_zone_accepted_form'),
    
    path('nq_zone_batch_rejection/', NQ_Zone_BatchRejectionAPIView.as_view(), name='nq_zone_batch_rejection'),
    path('nq_zone_tray_rejection/', NQ_Zone_TrayRejectionAPIView.as_view(), name='nq_zone_tray_rejection'),
    path('nq_zone_reject_check_tray_id/', nq_zone_reject_check_tray_id, name='nq_zone_reject_check_tray_id'),
    path('nq_zone_get_accepted_tray_scan_data/', nq_zone_get_accepted_tray_scan_data, name='nq_zone_get_accepted_tray_scan_data'),
    path('nq_zone_view_tray_list/', nq_zone_view_tray_list, name='nq_zone_view_tray_list'),
    path('nq_zone_save_accepted_tray_scan/', nq_zone_save_accepted_tray_scan, name='nq_zone_save_accepted_tray_scan'),
    path('nq_zone_check_tray_id/', nq_zone_check_tray_id, name='nq_zone_check_tray_id'),
    path('nq_zone_get_rejected_tray_scan_data/', nq_zone_get_rejected_tray_scan_data, name='nq_zone_get_rejected_tray_scan_data'),
    path('nq_zone_tray_validate/', NQ_Zone_TrayValidateAPIView.as_view(), name='nq_zone_tray_validate'),
    path('nq_zone_save_single_top_tray_scan/', nq_zone_save_single_top_tray_scan, name='nq_zone_save_single_top_tray_scan'),
    path('nq_zone_reject_check_tray_id_simple/', nq_zone_reject_check_tray_id_simple, name='nq_zone_reject_check_tray_id_simple'),

    path('nq_zone_get_delink_tray_data/', nq_zone_get_delink_tray_data, name='nq_zone_get_delink_tray_data'),
    path('nq_zone_delink_check_tray_id/', nq_zone_delink_check_tray_id, name='nq_zone_delink_check_tray_id'),

    path('nq_zone_CompleteTable_tray_id_list/', NQ_Zone_TrayIdList_Complete_APIView.as_view(), name='nq_CompleteTable_tray_id_list'),
    path('nq_zone_complete_tray_validate/', NQ_Zone_TrayValidate_Complete_APIView.as_view(), name='nq_zone_complete_tray_validate'),

    # Draft functionality endpoints
    path('nq_zone_batch_rejection_draft/', NQ_Zone_BatchRejectionDraftAPIView.as_view(), name='nq_zone_batch_rejection_draft'),
    path('nq_zone_tray_rejection_draft/', NQ_Zone_TrayRejectionDraftAPIView.as_view(), name='nq_zone_tray_rejection_draft'),
    path('nq_zone_get_draft_data/', nq_zone_get_draft_data, name='nq_zone_get_draft_data'),
    path('nq_zone_get_all_drafts/', nq_zone_get_all_drafts, name='nq_zone_get_all_drafts'),
    path('nq_zone_clear_draft/', NQ_Zone_ClearDraftAPIView.as_view(), name='nq_zone_clear_draft'),

    path('nq_zone_get_top_tray_scan_draft/', nq_zone_get_top_tray_scan_draft, name='nq_zone_get_top_tray_scan_draft'),

    #Pick table Vlaidation
    path('nq_zone_pick_complete_tray_validate/', NQ_Zone_PickTrayValidate_Complete_APIView.as_view(), name='nq_zone_pick_complete_tray_validate'),
    path('nq_zone_pick_CompleteTable_tray_id_list/', NQ_Zone_PickTrayIdList_Complete_APIView.as_view(), name='nq_zone_pick_CompleteTable_tray_id_list'),


    path('nq_zone_tray_delink_top_tray_calc/', NQ_Zone_TrayDelinkTopTrayCalcAPIView.as_view(), name='nq_zone_tray_delink_top_tray_calc'),
    path('nq_zone_validate_tray_id/',NQ_Zone_ValidateTrayIdAPIView.as_view(), name='nq_zone_validate_tray_id'),
    path('nq_zone_tray_delink_and_top_tray_update/', NQ_Zone_TrayDelinkAndTopTrayUpdateAPIView.as_view(), name='nq_zone_tray_delink_and_top_tray_update'),
    path('nq_zone_rejection_table/', NQ_Zone_RejectTableView.as_view(), name='nq_zone_rejection_table'),
    path('nq_zone_delink_selected_trays/', nq_zone_delink_selected_trays, name='nq_zone_delink_selected_trays'),
    path('nq_zone_get_rejection_details/', nq_zone_get_rejection_details, name='nq_zone_get_rejection_details'),

]
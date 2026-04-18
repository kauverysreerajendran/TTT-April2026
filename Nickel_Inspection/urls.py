from django.urls import path

from DayPlanning import views
from .views import *

urlpatterns = [
    path('Nickel_Inspection/', NQ_PickTableView.as_view(), name='Nickel_Inspection'),
    path('NI_Completed/', NQCompletedView.as_view(), name='NI_Completed'),
    path('nq_save_hold_unhold_reason/', NQSaveHoldUnholdReasonAPIView.as_view(), name='nq_save_hold_unhold_reason'),
    path('brass_get_tray_capacity_for_lot/', brass_get_tray_capacity_for_lot, name='brass_get_tray_capacity_for_lot'),
    path('nq_save_ip_checkbox/', NQSaveIPCheckboxView.as_view(), name='nq_save_ip_checkbox'),
    path('nq_save_ip_pick_remark/', NQSaveIPPickRemarkAPIView.as_view(), name='nq_save_ip_pick_remark'),
    path('nq_delete_batch/', NQDeleteBatchAPIView.as_view(), name='nq_delete_batch'),
    path('nq_accepted_form/', NQ_Accepted_form.as_view(), name='nq_accepted_form'),

    path('nq_batch_rejection/', NQBatchRejectionAPIView.as_view(), name='nq_batch_rejection'),
    path('nq_tray_rejection/', NQTrayRejectionAPIView.as_view(), name='nq_tray_rejection'),
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

    path('nickel_CompleteTable_tray_id_list/', NickelQcTrayIdList_Complete_APIView.as_view(), name='nickel_CompleteTable_tray_id_list'),
    path('nickel_complete_tray_validate/', NickelQcTrayValidate_Complete_APIView.as_view(), name='nickel_complete_tray_validate'),

    # Draft functionality endpoints
    path('nq_batch_rejection_draft/', NQBatchRejectionDraftAPIView.as_view(), name='nq_batch_rejection_draft'),
    path('nq_tray_rejection_draft/', NQTrayRejectionDraftAPIView.as_view(), name='nq_tray_rejection_draft'),
    path('nickel_get_draft_data/', nickel_get_draft_data, name='nickel_get_draft_data'),
    path('nickel_clear_draft/', NickelClearDraftAPIView.as_view(), name='nickel_clear_draft'),
    path('nickel_get_all_drafts/', nickel_get_all_drafts, name='nickel_get_all_drafts'),
    path('nickel_get_top_tray_scan_draft/', nickel_get_top_tray_scan_draft, name='nickel_get_top_tray_scan_draft'),

    #Pick table Vlaidation
    path('pick_complete_tray_validate/', PickTrayValidate_Complete_APIView.as_view(), name='pick_complete_tray_validate'),
    path('pick_CompleteTable_tray_id_list/', PickTrayIdList_Complete_APIView.as_view(), name='pick_CompleteTable_tray_id_list'),


    path('nq_tray_delink_top_tray_calc/', NQTrayDelinkTopTrayCalcAPIView.as_view(), name='nq_tray_delink_top_tray_calc'),
    path('nq_validate_tray_id/',NQValidateTrayIdAPIView.as_view(), name='nq_validate_tray_id'),
    path('nq_tray_delink_and_top_tray_update/', NQTrayDelinkAndTopTrayUpdateAPIView.as_view(), name='nq_tray_delink_and_top_tray_update'),

    path('nq_rejection_table/', NickelQcRejectTableView.as_view(), name='nq_rejection_table'),
    path('nickel_qc_delink_selected_trays/', nickel_qc_delink_selected_trays, name='nickel_qc_delink_selected_trays'),
    path('nickel_qc_get_rejection_details/', nickel_qc_get_rejection_details, name='nickel_qc_get_rejection_details'),

    # Auto-save endpoints
    path('nq_autosave/', autosave_nickel_qc, name='autosave_nickel_qc'),
    path('nq_autosave/<str:lot_id>/', load_autosave_nickel_qc, name='load_autosave_nickel_qc'),
    path('nq_autosave/<str:lot_id>/clear/', clear_autosave_nickel_qc, name='clear_autosave_nickel_qc'),

    # Scan button endpoint
    path('nq_get_lot_id_for_tray/', nq_get_lot_id_for_tray, name='nq_get_lot_id_for_tray'),

    # Unified Nickel QC Reject API (Brass QC style)
    path('nq_action/', nickel_qc_action, name='nickel_qc_action'),

]
from django.urls import path

from Brass_QC import views
from .views import * 

urlpatterns = [
    path('iqf_picktable/', IQFPickTableView.as_view(), name='iqf_picktable'),

    path('iqf_rejection_audit_iqf_reject/', iqf_rejection_audit_iqf_reject, name='iqf_rejection_audit_iqf_reject'),
    path('iqf_submit_audit/', iqf_submit_audit, name='iqf_submit_audit'),
    path('iqf_toggle_verified/', iqf_toggle_verified, name='iqf_toggle_verified'),
    path('iqf_save_pick_remark/', iqf_save_pick_remark, name='iqf_save_pick_remark'),
    path('iqf_delete_lot/', iqf_delete_lot, name='iqf_delete_lot'),
    path('iqf_tray_details/', iqf_tray_details, name='iqf_tray_details'),
    path('iqf_accepted_tray_slots/', iqf_accepted_tray_slots, name='iqf_accepted_tray_slots'),
    path('iqf_validate_tray_scan/', iqf_validate_tray_scan, name='iqf_validate_tray_scan'),
    path('iqf_accept_delink_modal/', iqf_accept_delink_modal, name='iqf_accept_delink_modal'),
    path('iqf_verify_trays_confirm/', iqf_verify_trays_confirm, name='iqf_verify_trays_confirm'),
    path('iqf_lot_rejection/', iqf_lot_rejection, name='iqf_lot_rejection'),
    path('iqf_completed_api/', IQFCompletedTableView.as_view(), name='iqf_completed_api'),
    path('iqf_completed_table/', IQFCompletedPageView.as_view(), name='iqf_completed_table'),
    path('iqf_accept_table/', IQFAcceptTablePageView.as_view(), name='iqf_accept_table'),
    path('iqf_rejection_table/', IQFRejectionTableView.as_view(), name='iqf_rejection_table'),

    # ═══ CONSOLIDATED API — SINGLE SOURCE OF TRUTH ═══
    # ALL view icons, tray modals, and table data MUST call this ONE endpoint.
    path('iqf_lot_details/', iqf_lot_details, name='iqf_lot_details'),

    # Backward-compatible aliases — all point to the SAME consolidated handler
    path('iqf_CompleteTable_tray_id_list/', iqf_lot_details, name='iqf_CompleteTable_tray_id_list'),
    path('iqf_accept_CompleteTable_tray_id_list/', iqf_lot_details, name='iqf_accept_CompleteTable_tray_id_list'),
    path('iqf_RejectTable_tray_id_list/', iqf_lot_details, name='iqf_RejectTable_tray_id_list'),
]
from django.urls import path
from .views import *

urlpatterns = [
    # Table Views
    path('brass_audit_picktable/', BrassAuditPickTableView.as_view(), name='brass_audit_picktable'),
    path('brass_audit_completed/', BrassAuditCompletedView.as_view(), name='brass_audit_completed'),
    path('brass_audit_rejection/', BrassAuditRejectTableView.as_view(), name='brass_audit_rejection'),

    # Unified API
    path('api/action/', brass_audit_action, name='brass_audit_action'),
    path('api/submission/', brass_audit_raw_submission, name='brass_audit_raw_submission'),

    # Legacy / Direct endpoints
    path('api/tray-details/', get_audit_tray_details, name='brass_audit_tray_details'),
    path('api/allocate-trays/', allocate_audit_trays, name='brass_audit_allocate_trays'),
    path('api/submit/', submit_brass_audit, name='brass_audit_submit'),
    path('api/toggle-verified/', brass_audit_toggle_verified, name='brass_audit_toggle_verified'),
    path('api/hold-unhold/', brass_audit_hold_unhold, name='brass_audit_hold_unhold'),
    path('api/rejection-reasons/', get_audit_rejection_reasons, name='brass_audit_rejection_reasons'),
    path('api/validate-tray/', validate_audit_tray_id, name='brass_audit_validate_tray'),

    # View icon / modal endpoints
    path('brass_get_rejection_details/', brass_get_rejection_details, name='brass_get_rejection_details'),
    path('get_tray_details_for_modal/', get_brass_audit_tray_details_for_modal, name='get_brass_audit_tray_details_for_modal'),
    path('RejectTable_tray_id_list/', RejectTableTrayIdListAPIView.as_view(), name='RejectTable_tray_id_list'),

    # Barcode scanner
    path('get_lot_id_for_tray/', get_lot_id_for_tray, name='get_lot_id_for_tray'),

]
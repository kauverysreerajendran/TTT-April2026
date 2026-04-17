from django.urls import path
from .views import *

urlpatterns = [
    path('brass_picktable/', BrassPickTableView.as_view(), name='BrassPickTableView'),
    path('brass_completed/', BrassCompletedView.as_view(), name='BrassCompletedView'),
    # ── Unified API — single entry point ──
    path('api/action/', brass_qc_action, name='brass_qc_action'),
    # ── Raw Submission API — stores exact payload ──
    path('api/submission/', brass_qc_raw_submission, name='brass_qc_raw_submission'),
    # ── Legacy endpoints (kept for backward compat, delegate to same logic) ──
    path('api/tray-details/', get_tray_details, name='brass_qc_tray_details'),
    path('api/allocate-trays/', allocate_trays, name='brass_qc_allocate_trays'),
    path('api/submit/', submit_brass_qc, name='brass_qc_submit'),
    path('api/toggle-verified/', brass_qc_toggle_verified, name='brass_qc_toggle_verified'),
    path('api/hold-unhold/', brass_qc_hold_unhold, name='brass_qc_hold_unhold'),
    path('api/rejection-reasons/', get_rejection_reasons, name='brass_qc_rejection_reasons'),
    path('api/validate-tray/', validate_tray_id, name='brass_qc_validate_tray'),
]
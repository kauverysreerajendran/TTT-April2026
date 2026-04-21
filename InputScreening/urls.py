from django.urls import path

from .views import (
    IS_AcceptTable,
    IS_AllocationPreviewAPI,
    IS_Completed_Table,
    IS_GetDPTraysAPI,
    IS_PartialSubmitAPI,
    IS_PartialSubmitV2API,
    IS_PickTable,
    IS_RejectModalContextAPI,
    IS_RejectTable,
    IS_ValidateScanAPI,
    IS_VerifyTrayAPI,
)

# NOTE: URL paths and view names are preserved verbatim for backward
# compatibility with existing templates, links and JS callers.
urlpatterns = [
    path('IS_PickTable/', IS_PickTable.as_view(), name='IS_PickTable'),
    path('IS_AcceptTable/', IS_AcceptTable.as_view(), name='IS_AcceptTable'),
    path('IS_Completed_Table/', IS_Completed_Table.as_view(), name='IS_Completed_Table'),
    path('IS_RejectTable/', IS_RejectTable.as_view(), name='IS_RejectTable'),
    path('get_dp_trays/', IS_GetDPTraysAPI.as_view(), name='IS_GetDPTraysAPI'),
    path('verify_tray/', IS_VerifyTrayAPI.as_view(), name='IS_VerifyTrayAPI'),
    # ── Partial Accept / Partial Reject ──────────────────────────────────
    path(
        'reject_modal_context/',
        IS_RejectModalContextAPI.as_view(),
        name='IS_RejectModalContextAPI',
    ),
    path(
        'allocation_preview/',
        IS_AllocationPreviewAPI.as_view(),
        name='IS_AllocationPreviewAPI',
    ),
    path(
        'partial_submit/',
        IS_PartialSubmitAPI.as_view(),
        name='IS_PartialSubmitAPI',
    ),
    # ── Manual scan flow ────────────────────────────────────────────────
    path(
        'validate_scan/',
        IS_ValidateScanAPI.as_view(),
        name='IS_ValidateScanAPI',
    ),
    path(
        'partial_submit_v2/',
        IS_PartialSubmitV2API.as_view(),
        name='IS_PartialSubmitV2API',
    ),
]

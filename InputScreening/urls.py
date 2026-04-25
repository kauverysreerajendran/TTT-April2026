from django.urls import path

from .views import (
    IS_AcceptTable,
    IS_AllocationPreviewAPI,
    IS_ClearAllVerificationsAPI,
    IS_Completed_Table,
    IS_DeleteBatchAPI,
    IS_DelinkSelectedTraysAPI,
    IS_FullAcceptAPI,
    IS_FullRejectAPI,
    IS_GetDPTraysAPI,
    IS_PartialSubmitAPI,
    IS_PartialSubmitV2API,
    IS_PickTable,
    IS_RejectModalContextAPI,
    IS_RejectTable,
    IS_SaveDraftAPI,
    IS_SaveHoldUnholdAPI,
    IS_SaveIPRemarkAPI,
    IS_SaveTVMDraftAPI,
    IS_SubmittedDetailAPI,
    IS_UnverifyTrayAPI,
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
    path(
        'save_draft/',
        IS_SaveDraftAPI.as_view(),
        name='IS_SaveDraftAPI',
    ),
    path(
        'submitted_detail/',
        IS_SubmittedDetailAPI.as_view(),
        name='IS_SubmittedDetailAPI',
    ),
    # ── Full Accept / Full Reject ───────────────────────────────────────
    path(
        'full_accept/',
        IS_FullAcceptAPI.as_view(),
        name='IS_FullAcceptAPI',
    ),
    path(
        'full_reject/',
        IS_FullRejectAPI.as_view(),
        name='IS_FullRejectAPI',
    ),
    # ── Delink functionality ────────────────────────────────────────────
    path(
        'delink_selected_trays/',
        IS_DelinkSelectedTraysAPI.as_view(),
        name='IS_DelinkSelectedTraysAPI',
    ),
    # ── Unverify tray (redo) ────────────────────────────────────────────
    path(
        'unverify_tray/',
        IS_UnverifyTrayAPI.as_view(),
        name='IS_UnverifyTrayAPI',
    ),
    # ── Save TVM draft (tray verification in progress) ──────────────────
    path(
        'save_tvm_draft/',
        IS_SaveTVMDraftAPI.as_view(),
        name='IS_SaveTVMDraftAPI',
    ),
    # ── Clear all tray verifications for a lot ───────────────────────────
    path(
        'clear_all_verifications/',
        IS_ClearAllVerificationsAPI.as_view(),
        name='IS_ClearAllVerificationsAPI',
    ),
    # ── Hold / Unhold a lot in the pick table ────────────────────────────
    path(
        'ip_save_hold_unhold_reason/',
        IS_SaveHoldUnholdAPI.as_view(),
        name='IS_SaveHoldUnholdAPI',
    ),
    # ── Save pick-table remark for a lot ────────────────────────────────
    path(
        'save_ip_remark/',
        IS_SaveIPRemarkAPI.as_view(),
        name='IS_SaveIPRemarkAPI',
    ),    # ── Admin: hard-delete a batch from IS pick table ─────────────────────
    path(
        'ip_delete_batch/',
        IS_DeleteBatchAPI.as_view(),
        name='IS_DeleteBatchAPI',
    ),]

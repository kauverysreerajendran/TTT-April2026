from django.urls import path

from .views import (
    IS_AcceptTable,
    IS_Completed_Table,
    IS_GetDPTraysAPI,
    IS_PickTable,
    IS_RejectAllocateAPI,
    IS_RejectContextAPI,
    IS_RejectionReasonsAPI,
    IS_RejectSubmitAPI,
    IS_RejectTable,
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
    # Reject window APIs
    path('rejection_reasons/', IS_RejectionReasonsAPI.as_view(), name='IS_RejectionReasonsAPI'),
    path('reject_context/', IS_RejectContextAPI.as_view(), name='IS_RejectContextAPI'),
    path('reject_allocate/', IS_RejectAllocateAPI.as_view(), name='IS_RejectAllocateAPI'),
    path('reject_submit/', IS_RejectSubmitAPI.as_view(), name='IS_RejectSubmitAPI'),
]

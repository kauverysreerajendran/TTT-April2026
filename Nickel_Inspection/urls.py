from django.urls import path
from .views import NQ_PickTableView, NickelQcRejectTableView, NQCompletedView, nq_toggle_verified, nq_action, nq_delink_selected_trays

urlpatterns = [
    path('Nickel_Inspection/', NQ_PickTableView.as_view(), name='Nickel_Inspection'),
    path('NI_Completed/', NQCompletedView.as_view(), name='NI_Completed'),
    path('NickelQc_RejectTable/', NickelQcRejectTableView.as_view(), name='NickelQc_RejectTable'),
    path('nq_rejection_table/', NickelQcRejectTableView.as_view(), name='nq_rejection_table'),
    path('api/toggle-verified/', nq_toggle_verified, name='nq_toggle_verified'),
    path('api/action/', nq_action, name='nq_action'),
    path('nickel_qc_delink_selected_trays/', nq_delink_selected_trays, name='nq_delink_selected_trays'),
]
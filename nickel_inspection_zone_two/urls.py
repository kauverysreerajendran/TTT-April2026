from django.urls import path
from .views import NQ_Zone_PickTableView, NQ_Zone_CompletedView, NQ_Zone_RejectTableView
from Nickel_Inspection.views import nq_toggle_verified, nq_action

urlpatterns = [
    path('NQ_Zone_PickTable/', NQ_Zone_PickTableView.as_view(), name='NQ_Zone_PickTable'),
    path('NQ_Zone_Completed/', NQ_Zone_CompletedView.as_view(), name='NQ_Zone_Completed'),
    path('nq_zone_rejection_table/', NQ_Zone_RejectTableView.as_view(), name='nq_zone_rejection_table'),
    path('api/toggle-verified/', nq_toggle_verified, name='nq_zone_toggle_verified'),
    path('api/action/', nq_action, name='nq_zone_action'),
]
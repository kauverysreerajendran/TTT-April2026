from django.urls import path
from django.views.generic import RedirectView
from .views import NA_PickTableView, NACompletedView, na_toggle_verified, na_action, na_delink_selected_trays

urlpatterns = [
    path('NA_PickTable/', NA_PickTableView.as_view(), name='NA_PickTable'),
    path('NA_Completed/', NACompletedView.as_view(), name='NA_Completed'),
    # Action APIs
    path('api/toggle-verified/', na_toggle_verified, name='na_toggle_verified'),
    path('api/action/', na_action, name='na_action'),
    path('nickel_audit_delink_selected_trays/', na_delink_selected_trays, name='na_delink_selected_trays'),
    # Backward compat redirect
    path('NA_Inspection/', RedirectView.as_view(pattern_name='NA_PickTable', permanent=True)),
]
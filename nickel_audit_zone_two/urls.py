from django.urls import path
from django.views.generic import RedirectView
from .views import NA_Zone_PickTableView, NA_Zone_CompletedView
from Nickel_Audit.views import na_toggle_verified, na_action

urlpatterns = [
    path('NA_Zone_PickTable/', NA_Zone_PickTableView.as_view(), name='NA_Zone_PickTable'),
    path('NA_Zone_Completed/', NA_Zone_CompletedView.as_view(), name='NA_Zone_Completed'),
    # Action APIs (reuse Zone 1 views)
    path('api/toggle-verified/', na_toggle_verified, name='na_zone_toggle_verified'),
    path('api/action/', na_action, name='na_zone_action'),
    # Backward compat redirect
    path('NA_Zone_Inspection/', RedirectView.as_view(pattern_name='NA_Zone_PickTable', permanent=True)),
]
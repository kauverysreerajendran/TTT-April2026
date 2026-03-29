from django.urls import path

from Brass_QC import views
from .views import * 

urlpatterns = [
    path('iqf_picktable/', IQFPickTableView.as_view(), name='iqf_picktable'),

    path('iqf_get_audit_modal_data/', iqf_get_audit_modal_data, name='iqf_get_audit_modal_data'),
    path('iqf_submit_audit/', iqf_submit_audit, name='iqf_submit_audit'),
    path('iqf_toggle_verified/', iqf_toggle_verified, name='iqf_toggle_verified'),
    path('iqf_completed_table/', iqf_completed_table_redirect, name='iqf_completed_table'),
    path('iqf_accept_table/', iqf_accept_table_redirect, name='iqf_accept_table'),
    path('iqf_rejection_table/', iqf_rejection_table_redirect, name='iqf_rejection_table'),

]
from django.urls import path
from . import views
from .views import *
urlpatterns = [
    path('JigView/', JigView.as_view(), name='JigView'),
    path('JigCompletedTable/', JigCompletedTable.as_view(), name='JigCompletedTable'),
    path('tray-info/', TrayInfoView.as_view(), name='tray_info'),
    path('tray-validate/', TrayValidateAPIView.as_view(), name='tray_validate'),
    path('jig-add-modal-data/', JigAddModalDataView.as_view(), name='jig_add_modal_data'),
    path('delink-table/', DelinkTableAPIView.as_view(), name='delink_table_api'),
    path('validate-tray-id/', views.validate_tray_id, name='validate_tray_id'),
    path('manual-draft/', JigLoadingManualDraftAPIView.as_view(), name='jig_loading_manual_draft'),
    path('manual-draft-fetch/', JigLoadingManualDraftFetchAPIView.as_view(), name='jig_loading_manual_draft_fetch'),
    path('jig-submit/', JigSubmitAPIView.as_view(), name='jig_submit'),
    path('validate-lock-jig-id/', views.validate_lock_jig_id, name='validate_lock_jig_id'),
    path('jig_tray_id_list/', views.jig_tray_id_list, name='jig_tray_id_list'),
    path('jig-completed-data/', JigCompletedDataAPIView.as_view(), name='jig_completed_data'),
]
from django.urls import path
from .views import *

urlpatterns = [
    path('index/',IndexView.as_view(),name="index"),
    path('dp_modelmaster/', DP_ModelmasterView.as_view(), name='dp_modelmaster'),
    path('dp_visualaid/', Visual_AidView.as_view(), name='dp-visualaid'),
    path('dp_visualaid/<str:batch_id>/', Visual_AidView.as_view(), name='dp-visualaid-lot'),

    path('rec_dp_visualaid/', Rec_Visual_AidView.as_view(), name='rec-dp-visualaid'),
    path('rec_dp_visualaid/<str:batch_id>/', Rec_Visual_AidView.as_view(), name='rec-dp-visualaid-lot'),

    path('other_visualaid/', Other_Visual_AidView.as_view(), name='other-visualaid'),
    path('other_visualaid/<str:model_no>/', Other_Visual_AidView.as_view(), name='other-visualaid-lot'),

    path('view_master/',DP_ViewmasterView.as_view(), name='view_master'),
    
    # Main Model Master Page
    # Polish Finish APIs
    path('polish-finish/', PolishFinishAPIView.as_view(), name='polish-finish-api'),
    path('polish-finish/<int:pk>/', PolishFinishAPIView.as_view(), name='polish-finish-detail-api'),
    
    # Plating Color APIs
    path('plating-color/', PlatingColorAPIView.as_view(), name='plating-color-api'),
    path('plating-color/<int:pk>/', PlatingColorAPIView.as_view(), name='plating-color-detail-api'),
    
    # Tray Type APIs
    path('tray-type/', TrayTypeAPIView.as_view(), name='tray-type-api'),
    path('tray-type/<int:pk>/', TrayTypeAPIView.as_view(), name='tray-type-detail-api'),
    
    
    # Model Image APIs
    path('model-image/', ModelImageAPIView.as_view(), name='model-image-api'),
    path('model-image/<int:pk>/', ModelImageAPIView.as_view(), name='model-image-detail-api'),
    
    # Model Master APIs
    path('model-master/', ModelMasterAPIView.as_view(), name='model-master-api'),
    path('model-master/<int:pk>/', ModelMasterAPIView.as_view(), name='model-master-detail-api'),
    
    # Dropdown Data API
    path('dropdown-data/', ModelMasterDropdownDataAPIView.as_view(), name='dropdown-data-api'),
    
    # Location APIs
    path('location/', LocationAPIView.as_view(), name='location-api'),
    path('location/<int:pk>/', LocationAPIView.as_view(), name='location-detail-api'),

    # TrayId APIs
    path('tray-id/', TrayIdAPIView.as_view(), name='tray-id-api'),
    path('tray-id/<int:pk>/', TrayIdAPIView.as_view(), name='tray-id-detail-api'),
 
    # Category APIs
    path('category/', CategoryAPIView.as_view(), name='category-api'),
    path('category/<int:pk>/', CategoryAPIView.as_view(), name='category-detail-api'),

    # IP Rejection APIs
    path('ip-rejection/', IPRejectionAPIView.as_view(), name='ip-rejection-api'),
    path('ip-rejection/<int:pk>/', IPRejectionAPIView.as_view(), name='ip-rejection-detail-api'),

    # Brass/IQF Rejection APIs
    path('brass-iqf-rejection/', BrassIQFRejectionAPIView.as_view(), name='brass-iqf-rejection-api'),
    path('brass-iqf-rejection/<int:pk>/', BrassIQFRejectionAPIView.as_view(), name='brass-iqf-rejection-detail-api'),

    # Nickel Audit/QC Rejection APIs
    path('nickel-auditqc-rejection/', NickelAuditQCRejectionAPIView.as_view(), name='nickel-auditqc-rejection-api'),
    path('nickel-auditqc-rejection/<int:pk>/', NickelAuditQCRejectionAPIView.as_view(), name='nickel-auditqc-rejection-detail-api'),

    path('', AdminPortalView.as_view(), name='adminportal'),
    path('api/users/', UserCreateAPIView.as_view(), name='user-create-api'),
    path('api/departments/', DepartmentListAPIView.as_view(), name='departments-api'),
    path('api/roles/', RoleListAPIView.as_view(), name='roles-api'),
    path('api/users/list/', UserListAPIView.as_view(), name='user-list-api'),
    path('api/group-modules/', UserGroupListAPIView.as_view(), name='user-groups-api'),
    path('api/user-allowed-modules/', user_allowed_modules, name='user-allowed-modules'),
    path('api/group-modules/<int:group_id>/', GroupModulesAPIView.as_view(), name='group-modules-detail-api'),
    # path('api/users/<int:user_id>/', UserDeleteAPIView.as_view(), name='user-delete'),
    path('extract_headings/', extract_headings_api, name='extract_headings_api'),
    
    path('swap-login/', swap_login, name='swap_login'),
    path('api/users/<int:user_id>/', UserDetailAPIView.as_view(), name='user-detail-api'),
    # path('dp_picktable/', DP_PickTableView.as_view(), name='dp-picktable'),
    
    path('module-table/', ModuleTableView.as_view(), name='module-table'),
    # or for kwarg style:
    path('module-table/<str:module_name>/', ModuleTableView.as_view(), name='module-table-by-name'),


]




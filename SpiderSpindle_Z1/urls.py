from django.urls import path
from .views import (
    SSZ1PickTableView,
    SSZ1CompletedView,
    SSZ1AddSpiderAPIView,
    SSZ1DelinkAPIView,
    SSZ1SaveRemarksAPIView,
    SSZ1GetTrayIdAPIView,
)

urlpatterns = [
    path('spider_pick_table/', SSZ1PickTableView.as_view(), name='ss_z1_pick_table'),
    path('ss_z1_completed/', SSZ1CompletedView.as_view(), name='ss_z1_completed'),
    path('api/ss_z1_add_spider/', SSZ1AddSpiderAPIView.as_view(), name='ss_z1_add_spider'),
    path('api/ss_z1_delink/', SSZ1DelinkAPIView.as_view(), name='ss_z1_delink'),
    path('api/ss_z1_save_remarks/', SSZ1SaveRemarksAPIView.as_view(), name='ss_z1_save_remarks'),
    path('api/ss_z1_get_tray_id/', SSZ1GetTrayIdAPIView.as_view(), name='ss_z1_get_tray_id'),
]

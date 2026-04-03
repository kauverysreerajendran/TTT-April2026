from django.urls import path
from .views import (
    SSZ2PickTableView,
    SSZ2CompletedView,
    SSZ2AddSpiderAPIView,
    SSZ2DelinkAPIView,
    SSZ2SaveRemarksAPIView,
    SSZ2GetTrayIdAPIView,
)

urlpatterns = [
    path('zone_spider_pick_table/', SSZ2PickTableView.as_view(), name='ss_z2_pick_table'),
    path('ss_z2_completed/', SSZ2CompletedView.as_view(), name='ss_z2_completed'),
    path('api/ss_z2_add_spider/', SSZ2AddSpiderAPIView.as_view(), name='ss_z2_add_spider'),
    path('api/ss_z2_delink/', SSZ2DelinkAPIView.as_view(), name='ss_z2_delink'),
    path('api/ss_z2_save_remarks/', SSZ2SaveRemarksAPIView.as_view(), name='ss_z2_save_remarks'),
    path('api/ss_z2_get_tray_id/', SSZ2GetTrayIdAPIView.as_view(), name='ss_z2_get_tray_id'),
]

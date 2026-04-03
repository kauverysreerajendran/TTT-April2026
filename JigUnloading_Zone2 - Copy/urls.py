from django.urls import path
from .views import *

urlpatterns = [
    path('JU_Zone_MainTable/', JU_Zone_MainTable.as_view(), name='JU_Zone_MainTable'),
    path('JU_Zone_Completedtable/', JU_Zone_Completedtable.as_view(), name='JU_Zone_Completedtable'),
    path('JU_Zone_get_model_details/', JU_Zone_get_model_details, name='JU_Zone_get_model_details'),
    path('JU_Zone_validate_tray_id/', JU_Zone_validate_tray_id, name='JU_Zone_validate_tray_id'),
    path('JU_Zone_validate_tray_id_dynamic/', JU_Zone_validate_tray_id_dynamic, name='JU_Zone_validate_tray_id_dynamic'),
    path('JU_Zone_save_jig_unload_tray_ids/', JU_Zone_save_jig_unload_tray_ids, name='JU_Zone_save_jig_unload_tray_ids'),
    path('JU_Zone_check_unload_status/', JU_Zone_check_unload_status, name='JU_Zone_check_unload_status'),
    path('JU_Zone_view_tray_list/', JU_Zone_ListAPIView.as_view(), name='JU_Zone_view_tray_list'),
    path('JU_Zone_after_view_tray_list/', JU_Zone_after_view_tray_list, name='JU_Zone_after_view_tray_list'),
    path('JU_Zone_after_tray_validate/', JU_Zone_AfterTrayValidateAPIView.as_view(), name='JU_Zone_after_tray_validate'),
    path('JU_Zone_get_model_images/', JU_Zone_get_model_images, name='JU_Zone_get_model_images'),
    path('JU_Zone_unload_save_hold_unhold_reason/', JU_Zone_SaveHoldUnholdReasonAPIView.as_view(), name='JU_Zone_unload_save_hold_unhold_reason'),
    path('JU_Zone_save_jig_pick_remark/', JU_Zone_JigPickRemarkAPIView.as_view(), name='JU_Zone_save_jig_pick_remark'),
    path('JU_Zone_save_jig_unload_draft/', JU_Zone_save_jig_unload_draft, name='JU_Zone_save_jig_unload_draft'),
    path('JU_Zone_load_jig_unload_draft/', JU_Zone_load_jig_unload_draft, name='JU_Zone_load_jig_unload_draft'),
    path('JU_Zone_fix_missing_plating_colors/', JU_Zone_fix_missing_plating_colors, name='JU_Zone_fix_missing_plating_colors'),
    path('delete_jig_details/', JU_Zone_delete_jig_details, name='JU_Zone_delete_jig_details'),
    path('debug_models/', debug_model_availability_zone2, name='debug_model_availability_zone2'),
    # Auto-save endpoints
    path('ju_zone2_autosave/', JU_Zone_autosave_jig_unload, name='JU_Zone_autosave_jig_unload'),
    path('ju_zone2_autosave/<str:main_lot_id>/', JU_Zone_load_autosave_jig_unload, name='JU_Zone_load_autosave_jig_unload'),
    path('ju_zone2_autosave/<str:main_lot_id>/clear/', JU_Zone_clear_autosave_jig_unload, name='JU_Zone_clear_autosave_jig_unload'),
    path('get_jig_for_tray/', JU_Zone_get_jig_for_tray, name='JU_Zone_get_jig_for_tray'),
]
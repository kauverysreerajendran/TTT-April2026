from django.urls import path
from .views import *

urlpatterns = [
    path('bulk_upload/', DPBulkUploadView.as_view(), name='bulk_upload'),
    path('bulk_upload/preview/', DPBulkUploadPreviewView.as_view(), name='bulk_upload_preview'),
    path('download_excel_template/', DownloadExcelTemplateAPIView.as_view(), name='download_excel_template'),
    
    # Auto-fetch APIs for Single Upload
    path('get_plating_colour/', GetPlatingColourAPIView.as_view(), name='get_plating_colour'),
    path('get_categories/', GetCategoriesAPIView.as_view(), name='get_categories'),
    path('get_locations/', GetLocationsAPIView.as_view(), name='get_locations'),
    path('get_allowed_versions/', GetAllowedVersionsAPIView.as_view(), name='get_allowed_versions'),
    path('validate_plating_stk_no/', ValidatePlatingStockNoAPIView.as_view(), name='validate_plating_stk_no'),
       
    
    path('dp_pick_table/', DayPlanningPickTableAPIView.as_view(), name='dp_pick_table'),
    path('tray_scan/', TrayIdScanAPIView.as_view(), name='tray_scan_api'),
    path('top_tray_scan/', TopTrayScanAPIView.as_view(), name='top_tray_scan'),
    path('validate_top_tray/', ValidateTopTrayAPIView.as_view(), name='validate_top_tray'),

    path('tray_id_list/', TrayIdListAPIView.as_view(), name='tray_id_list'),
    path('tray_id_unique_check/', TrayIdUniqueCheckAPIView.as_view(), name='tray_id_unique_check'),
    path('draft_tray/', DraftTrayIdAPIView.as_view(), name='draft_tray'),
    path('draft_tray_id_list/', DraftTrayIdListAPIView.as_view(), name='draft_tray_id_list'),
    path('globally_drafted_trays/', GlobalDraftedTraysAPIView.as_view(), name='globally_drafted_trays'),  # ✅ NEW
    
    path('dp_completed_table/', DPCompletedTableView.as_view(), name='dp_completed_table'),  # <-- Add this
    path('completed_tray_id_list/', CompletedTrayIdListAPIView.as_view(), name='completed_tray_id_list'),
    path('tray_validate/', TrayValidateAPIView.as_view(), name='tray_validate'),

    
    path('delete_batch/', DeleteBatchAPIView.as_view(), name='delete_batch'),
    path('update_batch_quantity_and_color/', UpdateBatchQuantityAndColorAPIView.as_view(), name='update_batch_quantity_and_color'),
    path('get_plating_colors/', GetPlatingColorsAPIView.as_view(), name='get_plating_colors'),
    path('save_dp_pick_remark/', SaveDPPickRemarkAPIView.as_view(), name='save_dp_pick_remark'),
    path('verify_top_tray_qty/', VerifyTopTrayQtyAPIView.as_view(), name='verify_top_tray_qty'),
    path('save_hold_unhold_reason/', SaveHoldUnholdReasonAPIView.as_view(), name='save_hold_unhold_reason'),

    path('tray_auto_save/', TrayAutoSaveAPIView.as_view(), name='tray_auto_save'),
    path('tray_auto_save_cleanup/', TrayAutoSaveCleanupAPIView.as_view(), name='tray_auto_save_cleanup'),
    
    
    path('row_lock/', lock_row_api, name='row_lock_api'),
    path('row_lock/check/', check_row_lock_api, name='check_row_lock_api'),

    path('dget_lot_id_for_tray/', dget_lot_id_for_tray, name='dget_lot_id_for_tray'),
    path('draft_tray_delete/', draft_tray_delete, name='draft_tray_delete'),

]
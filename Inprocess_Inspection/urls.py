from django.urls import path
from . import views

urlpatterns = [
    path('inprocess_inspection_main/', views.InprocessInspectionView.as_view(), name='inprocess_inspection_main'),
    path('complete/', views.InprocessInspectionCompleteView.as_view(), name='inprocess_inspection_complete'),
    path('save_bath_number/', views.save_bath_number, name='save_bath_number'),
    path('save_jig_remarks/', views.save_jig_remarks, name='save_jig_remarks'),  # <-- Add this line
    path('ii_save_ip_pick_remark/', views.IISaveIPPickRemarkAPIView.as_view(), name='ii_save_ip_pick_remark'),
    path('delete_jig_details/', views.JigCompletedDeleteAPIView.as_view(), name='delete_jig_details'),
    path('inprocess_save_hold_unhold_reason/', views.InprocessSaveHoldUnholdReasonAPIView.as_view(), name='inprocess_save_hold_unhold_reason'),
    # Bath number related APIs
    path('get_bath_numbers_by_type/', views.GetBathNumbersByTypeAPIView.as_view(), name='get_bath_numbers_by_type'),
    path('save_bath_number/', views.SaveBathNumberAPIView.as_view(), name='save_bath_number'),
    # JigLot Qty dynamic fetch
    path('get_jig_completed_qty/', views.get_jig_completed_qty, name='get_jig_completed_qty'),
]
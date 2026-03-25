from django.urls import path
from . import views
from .views import *
from .views import JigView, TrayInfoView, JigCompletedTable

urlpatterns = [
	path('JigView/', JigView.as_view(), name='JigView'),
	path('tray-info/', TrayInfoView.as_view(), name='tray-info'),
	path('init-jig-load/', InitJigLoad.as_view(), name='init-jig-load'),
	path('scan-tray/', ScanTray.as_view(), name='scan-tray'),
	path('JigCompletedTable/', JigCompletedTable.as_view(), name='JigCompletedTable'),
]


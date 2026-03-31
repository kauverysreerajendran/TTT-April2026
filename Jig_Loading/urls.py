from django.urls import path
from . import views
from .views import *
from .views import JigView, TrayInfoView, JigCompletedTable
from .views import JigLoadInitAPI, JigLoadUpdateAPI, JigLoadSubmitAPI

urlpatterns = [
	path('JigView/', JigView.as_view(), name='JigView'),
	path('JigCompletedTable/', JigCompletedTable.as_view(), name='JigCompletedTable'),

	# ===== NEW CONSOLIDATED APIs (one API per action) =====
	path('api/load/init/', JigLoadInitAPI.as_view(), name='jig-load-init'),
	path('api/load/update/', JigLoadUpdateAPI.as_view(), name='jig-load-update'),
	path('api/load/submit/', JigLoadSubmitAPI.as_view(), name='jig-load-submit'),

	# ===== DEPRECATED — kept for backward compatibility =====
	path('tray-info/', TrayInfoView.as_view(), name='tray-info'),
	path('init-jig-load/', InitJigLoad.as_view(), name='init-jig-load'),
	path('scan-tray/', ScanTray.as_view(), name='scan-tray'),
]
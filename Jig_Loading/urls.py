from django.urls import path
from . import views
from .views import *
from .views import JigView, TrayInfoView, JigCompletedTable
from .views import JigLoadInitAPI, JigLoadUpdateAPI, JigLoadSubmitAPI
from .views import JigSaveDraftAPI, JigSubmitFinalAPI
from .views import ModelCombinationValidateAPI, JigHoldToggleAPI

urlpatterns = [
        path('JigView/', JigView.as_view(), name='JigView'),
        path('JigCompletedTable/', JigCompletedTable.as_view(), name='JigCompletedTable'),

        # ===== NEW CONSOLIDATED APIs (one API per action) =====
        path('api/load/init/', JigLoadInitAPI.as_view(), name='jig-load-init'),
        path('api/load/update/', JigLoadUpdateAPI.as_view(), name='jig-load-update'),
        path('api/load/submit/', JigLoadSubmitAPI.as_view(), name='jig-load-submit'),

        # ===== NEW CLEAN APIs - exact frontend snapshot storage =====
        path('api/jig/save/', JigSaveDraftAPI.as_view(), name='jig-save-draft'),
        path('api/jig/submit/', JigSubmitFinalAPI.as_view(), name='jig-submit-final'),

        # ===== Model combination validation (Add Model eligibility) =====
        path('api/model-combination/validate/', ModelCombinationValidateAPI.as_view(), name='model-combination-validate'),

        # ===== Hold/Unhold API =====
        path('api/hold-toggle/', JigHoldToggleAPI.as_view(), name='jig-hold-toggle'),

        # ===== Read-only support endpoint (tray modal) =====
        path('tray-info/', TrayInfoView.as_view(), name='tray-info'),
]
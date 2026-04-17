from django.urls import path
from . import views
from .views import *
from .views import JigView, TrayInfoView, JigCompletedTable, ExcessTrayInfoAPI
from .views import JigLoadInitAPI, JigLoadUpdateAPI
from .views import JigSaveAPI, JigValidateAPI
from .views import ModelCombinationValidateAPI, JigHoldToggleAPI
from .views import DeleteJigPickRecordAPI, UpdateRemarkAPI, LotFetchAPI
from .views import jig_get_lot_id_for_tray

urlpatterns = [
        path('JigView/', JigView.as_view(), name='JigView'),
        path('JigCompletedTable/', JigCompletedTable.as_view(), name='JigCompletedTable'),

        # ===== CONSOLIDATED APIs =====
        path('api/load/init/', JigLoadInitAPI.as_view(), name='jig-load-init'),
        path('api/load/update/', JigLoadUpdateAPI.as_view(), name='jig-load-update'),

        # ===== SINGLE UNIFIED API — Draft + Submit (ONE ENDPOINT) =====
        path('api/jig/save/', JigSaveAPI.as_view(), name='jig-save'),

        # ===== Jig ID real-time validation (existence check against Jig master) =====
        path('api/jig/validate/', JigValidateAPI.as_view(), name='jig-validate'),

        # ===== Model combination validation (Add Model eligibility) =====
        path('api/model-combination/validate/', ModelCombinationValidateAPI.as_view(), name='model-combination-validate'),

        # ===== Hold/Unhold API =====
        path('api/hold-toggle/', JigHoldToggleAPI.as_view(), name='jig-hold-toggle'),

        # ===== Delete & Remark APIs =====
        path('api/delete-pick-record/', DeleteJigPickRecordAPI.as_view(), name='jig-delete-pick-record'),
        path('api/update-remark/', UpdateRemarkAPI.as_view(), name='jig-update-remark'),

        # ===== Consolidated Lot Fetch API (backend-driven filtering) =====
        path('api/lots/', LotFetchAPI.as_view(), name='jig-lots-fetch'),

        # ===== Barcode scanner — tray ID to lot ID lookup =====
        path('api/get_lot_id_for_tray/', jig_get_lot_id_for_tray, name='jig-get-lot-id-for-tray'),

        # ===== Read-only support endpoint (tray modal) =====
        path('tray-info/', TrayInfoView.as_view(), name='tray-info'),

        # ===== Excess lot half-filled tray info (lazy-loaded on click) =====
        path('api/excess-tray-info/', ExcessTrayInfoAPI.as_view(), name='excess-tray-info'),
]
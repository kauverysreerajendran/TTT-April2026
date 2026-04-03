from django.urls import path
from .views import *

urlpatterns = [ 
    path('Jig_Unloading_MainTable/', Jig_Unloading_MainTable.as_view(), name='Jig_Unloading_MainTable'),
    path('JigUnloading_Completedtable/', JigUnloading_Completedtable.as_view(), name='JigUnloading_Completedtable'),
    # Zone 1 APIs
    path('api/get_unload_models_z1/', GetUnloadModelsZ1View.as_view(), name='get_unload_models_z1'),
    path('api/save_model_unload_z1/', SaveModelUnloadZ1View.as_view(), name='save_model_unload_z1'),
    path('api/submit_all_unload_z1/', SubmitAllUnloadZ1View.as_view(), name='submit_all_unload_z1'),
    path('api/get_unload_view_z1/', GetUnloadViewZ1View.as_view(), name='get_unload_view_z1'),
]
from django.urls import path
from modelmasterapp.views import *

urlpatterns = [
    path('', LoginAPIView.as_view(), name='login-api'),
    path('base/', BaseAPIView.as_view(), name='base-api'),
    path('logout/', logout_view, name='logout'),
    path('delete_all/', delete_all_tables, name='delete_all_tables'),
    path('get-plating-images/', get_plating_images, name='get_plating_images'),

]
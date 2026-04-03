"""
URL configuration for watchcase_tracker project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.contrib.auth import views as auth_views
from watchcase_tracker import sso
from django.conf.urls import handler404, handler500, handler403, handler400
from django.shortcuts import render
from django.http import HttpResponse



urlpatterns = [
    
    #path('admin/', admin.site.urls),
    path('auth/', include('social_django.urls', namespace='social')),
    # Microsoft Entra ID (Azure AD) SSO endpoints
    path('auth/microsoft/login/', sso.microsoft_login, name='microsoft_login'),
    path('auth/microsoft/callback/', sso.microsoft_callback, name='microsoft_callback'),
    
    path('accounts/profile/', lambda request: HttpResponse('Logged in successfully!')),
    # Use your custom login template here:    
    path('accounts/login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'), 
     
    path('home/', TemplateView.as_view(template_name="index.html"), name="home"),  # Add this line
    path('admin/', admin.site.urls),
    path('',include('modelmasterapp.urls')),
    path('adminportal/',include('adminportal.urls')),
    path('dayplanning/',include('DayPlanning.urls')),
    path('inputscreening/',include('InputScreening.urls')),
    path('recovery_dp/',include('Recovery_DP.urls')),
    path('recovery_is/',include('Recovery_IS.urls')),
    path('recovery_brassqc/',include('Recovery_Brass_QC.urls')),
    path('recovery_brass_audit/',include('Recovery_BrassAudit.urls')),
    path('recovery_iqf/',include('Recovery_IQF.urls')),
    path('brass_qc/',include('Brass_QC.urls')),
    path('brass_audit/',include('BrassAudit.urls')),
    path('iqf/',include('IQF.urls')),
    path('jig_loading/',include('Jig_Loading.urls')),
    path('jig_unloading/',include('Jig_Unloading.urls')),
    path('JigUnloading_Zone2/',include('JigUnloading_Zone2.urls')),
    path('inprocess_inspection/',include('Inprocess_Inspection.urls')),
    path('nickle_inspection/',include('Nickel_Inspection.urls')),
    path('nickle_inspection_zone_two/',include('nickel_inspection_zone_two.urls')),

    path('nickel_audit/',include('Nickel_Audit.urls')),
    path('nickel_audit_zone_two/',include('nickel_audit_zone_two.urls')),

    path('reports_module/', include('ReportsModule.urls', namespace='reports_module')),
    path('spider_spindle/', include('SpiderSpindle_Z1.urls')),
    path('spider_spindle_zone_two/', include('SpiderSpindle_Z2.urls')),
    
    
    
    
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
def custom_404(request, exception):
    return render(request, "pages/samples/error-404.html", status=404)

def custom_500(request):
    return render(request, "pages/samples/error-500.html", status=500)

def custom_403(request, exception):
    return render(request, "pages/samples/error-404.html", status=403)  # You can use a separate 403 template

def custom_400(request, exception):
    return render(request, "pages/samples/error-404.html", status=400)  # You can use a separate 400 template

handler404 = 'watchcase_tracker.urls.custom_404'
handler500 = 'watchcase_tracker.urls.custom_500'
handler403 = 'watchcase_tracker.urls.custom_403'
handler400 = 'watchcase_tracker.urls.custom_400'



from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import HttpResponseServerError
def test_500(request):
    raise Exception("Test 500 error")

def test_403(request):
    raise PermissionDenied("Test 403 error")

def test_400(request):
    raise SuspiciousOperation("Test 400 error")

urlpatterns += [
    path('test500/', test_500),
    path('test403/', test_403),
    path('test400/', test_400),
]
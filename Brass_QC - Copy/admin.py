from django.contrib import admin
from .models import *
# Register your models here.

admin.site.register(BrassTrayId)

admin.site.register(Brass_QC_Rejection_Table)
admin.site.register(Brass_QC_Rejection_ReasonStore)
admin.site.register(Brass_QC_Rejected_TrayScan)
admin.site.register(Brass_Qc_Accepted_TrayScan)
admin.site.register(Brass_Qc_Accepted_TrayID_Store)
admin.site.register(Brass_QC_Draft_Store)
admin.site.register(Brass_TopTray_Draft_Store)
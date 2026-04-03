from django.contrib import admin

from .models import Nickel_QC_Rejection_ReasonStore
from .models import *
# Register your models here.

admin.site.register(NickelQcTrayId)
admin.site.register(Nickel_QC_Rejection_Table)
admin.site.register(Nickel_QC_Rejection_ReasonStore)
admin.site.register(Nickel_QC_Draft_Store)
admin.site.register(Nickel_QC_TopTray_Draft_Store)
admin.site.register(Nickel_QC_Rejected_TrayScan)
admin.site.register(Nickel_Qc_Accepted_TrayScan)
admin.site.register(Nickel_Qc_Accepted_TrayID_Store)
admin.site.register(Nickel_QC_AutoSave)

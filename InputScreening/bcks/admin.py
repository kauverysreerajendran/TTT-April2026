from django.contrib import admin
from .models import *
# Register your models here.

admin.site.register(IPTrayId)
admin.site.register(IP_RejectionGroup)
admin.site.register(IP_Rejection_Table)
admin.site.register(IP_Rejection_ReasonStore)
admin.site.register(IP_Rejected_TrayScan)
admin.site.register(IP_Accepted_TrayScan)
admin.site.register(IP_Accepted_TrayID_Store)
admin.site.register(IP_Rejection_Draft)

from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(JigUnload_TrayId)
admin.site.register(JigUnloadAfterTable)
admin.site.register(JigUnloadDraft)
admin.site.register(JigUnloadAutoSave)
admin.site.register(JUSubmittedZ1)  # ✅ NEW: View Z1 submitted records
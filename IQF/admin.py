from django.contrib import admin
from .models import *
# Register your models here.

admin.site.register(IQFTrayId)
admin.site.register(IQF_Draft_Store)


admin.site.register(IQF_Accepted_TrayScan)
admin.site.register(IQF_Accepted_TrayID_Store)
admin.site.register(IQF_Rejection_ReasonStore)
admin.site.register(IQF_Rejected_TrayScan)
admin.site.register(IQF_Rejection_Table)
admin.site.register(IQF_OptimalDistribution_Draft)


class IQFSubmittedAdmin(admin.ModelAdmin):
	list_display = ('lot_id', 'batch_id', 'original_lot_qty', 'iqf_incoming_qty', 'total_lot_qty', 'accepted_qty', 'rejected_qty', 'submission_type', 'is_completed', 'created_by', 'created_at')
	list_filter = ('submission_type', 'is_completed', 'created_by')
	search_fields = ('lot_id', 'batch_id__batch_id')
	readonly_fields = ('created_at', 'original_data', 'iqf_data', 'full_accept_data', 'partial_accept_data', 'full_reject_data', 'partial_reject_data', 'rejection_details')


admin.site.register(IQF_Submitted, IQFSubmittedAdmin)

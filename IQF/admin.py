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
	list_display = ('lot_id', 'batch_id', 'original_lot_qty', 'iqf_incoming_qty', 'total_lot_qty', 'accepted_qty', 'rejected_qty', 'submission_type', 'remarks', 'is_completed', 'created_by', 'created_at')
	list_filter = ('submission_type', 'is_completed', 'created_by')
	search_fields = ('lot_id', 'batch_id__batch_id')
	readonly_fields = ('created_at',)


admin.site.register(IQF_Submitted, IQFSubmittedAdmin)


# ── IQF Partial Lots ─────────────────────────────────────────────────────────

class IQFPartialAcceptAdmin(admin.ModelAdmin):
	list_display = ('new_lot_id', 'parent_lot_id', 'parent_batch_id',
	                'accepted_qty', 'accept_trays_count', 'created_by', 'created_at')
	list_filter = ('created_at',)
	search_fields = ('new_lot_id', 'parent_lot_id', 'parent_batch_id')
	readonly_fields = ('created_at',)


class IQFPartialRejectAdmin(admin.ModelAdmin):
	list_display = ('new_lot_id', 'parent_lot_id', 'parent_batch_id',
	                'rejected_qty', 'reject_trays_count', 'created_by', 'created_at')
	list_filter = ('created_at',)
	search_fields = ('new_lot_id', 'parent_lot_id', 'parent_batch_id')
	readonly_fields = ('created_at',)


admin.site.register(IQF_PartialAcceptLot, IQFPartialAcceptAdmin)
admin.site.register(IQF_PartialRejectLot, IQFPartialRejectAdmin)

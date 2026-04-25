from django.contrib import admin
from .models import *
# Register your models here.

admin.site.register(BrassAuditTrayId)
admin.site.register(Brass_Audit_Rejection_Table)
admin.site.register(Brass_Audit_Rejection_ReasonStore)
admin.site.register(Brass_Audit_Draft_Store)
admin.site.register(Brass_Audit_TopTray_Draft_Store)
admin.site.register(Brass_Audit_Rejected_TrayScan)
admin.site.register(Brass_Audit_Accepted_TrayScan)
admin.site.register(Brass_Audit_Accepted_TrayID_Store)
admin.site.register(AQLSamplingPlan)


# ── Brass Audit Submission & Partial Lots ────────────────────────────────────

class BrassAuditSubmissionAdmin(admin.ModelAdmin):
    list_display  = ('lot_id', 'batch_id', 'submission_type', 'total_lot_qty',
                     'accepted_qty', 'rejected_qty', 'is_completed', 'created_by', 'created_at')
    list_filter   = ('submission_type', 'is_completed')
    search_fields = ('lot_id', 'batch_id')
    readonly_fields = ('created_at',)


class BrassAuditPartialAcceptAdmin(admin.ModelAdmin):
    list_display  = ('new_lot_id', 'parent_lot_id', 'parent_batch_id',
                     'accepted_qty', 'accept_trays_count', 'created_by', 'created_at')
    list_filter   = ('created_at',)
    search_fields = ('new_lot_id', 'parent_lot_id', 'parent_batch_id')
    readonly_fields = ('created_at',)


class BrassAuditPartialRejectAdmin(admin.ModelAdmin):
    list_display  = ('new_lot_id', 'parent_lot_id', 'parent_batch_id',
                     'rejected_qty', 'reject_trays_count', 'created_by', 'created_at')
    list_filter   = ('created_at',)
    search_fields = ('new_lot_id', 'parent_lot_id', 'parent_batch_id')
    readonly_fields = ('created_at',)


admin.site.register(Brass_Audit_Submission, BrassAuditSubmissionAdmin)
admin.site.register(Brass_Audit_RawSubmission)
admin.site.register(BrassAudit_PartialAcceptLot, BrassAuditPartialAcceptAdmin)
admin.site.register(BrassAudit_PartialRejectLot, BrassAuditPartialRejectAdmin)


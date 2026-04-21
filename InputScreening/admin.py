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


# ============================================================================
# INPUT SCREENING SUBMITTED - ADVANCED ADMIN
# ============================================================================

class InputScreening_SubmittedAdmin(admin.ModelAdmin):
    """
    Admin interface for InputScreening_Submitted records.
    
    Features:
    - Search by lot_id, parent_lot_id, batch_id, plating_stock_no
    - Filter by active status, submission type, split status, date
    - Read-only snapshot fields (JSON)
    - Organized fieldsets for clarity
    - Custom display methods for status
    """

    # Search capabilities
    search_fields = [
        'lot_id',
        'parent_lot_id',
        'batch_id',
        'plating_stock_no',
        'model_no',
        'top_tray_id',
    ]

    # Filtering options
    list_filter = [
        'is_active',
        'is_revoked',
        'is_partial_accept',
        'is_partial_reject',
        'is_full_accept',
        'is_full_reject',
        'is_child_lot',
        'tray_type',
        'created_at',
        'created_by',
    ]

    # Display columns in list view
    list_display = [
        'lot_id',
        'batch_id',
        'get_status_display',
        'submitted_lot_qty',
        'accepted_qty',
        'rejected_qty',
        'is_child_lot_display',
        'created_at',
        'created_by_display',
    ]

    # Read-only fields (snapshots should not be edited)
    readonly_fields = [
        'id',
        'lot_id',
        'created_at',
        'updated_at',
        'all_trays_json_display',
        'accepted_trays_json_display',
        'rejected_trays_json_display',
        'rejection_reasons_json_display',
        'allocation_preview_json_display',
        'delink_trays_json_display',
    ]

    # Organized field grouping
    fieldsets = (
        ('🔑 Core Identifiers', {
            'fields': ('id', 'lot_id', 'parent_lot_id', 'batch_id', 'module_name'),
        }),
        ('📦 Product & Tray Details', {
            'fields': (
                'plating_stock_no',
                'model_no',
                'tray_type',
                'tray_capacity',
            ),
        }),
        ('📊 Quantities', {
            'fields': (
                'original_lot_qty',
                'submitted_lot_qty',
                'accepted_qty',
                'rejected_qty',
            ),
        }),
        ('🎯 Tray Allocation', {
            'fields': (
                'active_trays_count',
                'accept_trays_count',
                'reject_trays_count',
                'has_top_tray',
                'top_tray_id',
                'top_tray_qty',
            ),
        }),
        ('✅ Submission Type', {
            'fields': (
                'is_full_accept',
                'is_full_reject',
                'is_partial_accept',
                'is_partial_reject',
            ),
        }),
        ('🔗 Lot Hierarchy', {
            'fields': (
                'is_child_lot',
                'is_active',
                'is_revoked',
            ),
        }),
        ('💬 Remarks & Audit', {
            'fields': (
                'remarks',
                'created_by',
                'created_at',
                'updated_at',
            ),
        }),
        ('📸 Snapshot: All Trays', {
            'fields': ('all_trays_json_display',),
            'classes': ('collapse',),
        }),
        ('✅ Snapshot: Accepted Trays', {
            'fields': ('accepted_trays_json_display',),
            'classes': ('collapse',),
        }),
        ('❌ Snapshot: Rejected Trays', {
            'fields': ('rejected_trays_json_display',),
            'classes': ('collapse',),
        }),
        ('📋 Snapshot: Rejection Reasons', {
            'fields': ('rejection_reasons_json_display',),
            'classes': ('collapse',),
        }),
        ('🎲 Snapshot: Allocation Preview', {
            'fields': ('allocation_preview_json_display',),
            'classes': ('collapse',),
        }),
        ('♻️ Snapshot: Delink Trays', {
            'fields': ('delink_trays_json_display',),
            'classes': ('collapse',),
        }),
    )

    # Ordering
    ordering = ('-created_at',)

    # Display methods for list view
    def get_status_display(self, obj):
        """Show human-readable status with emoji."""
        return obj.get_display_status()
    get_status_display.short_description = 'Status'

    def is_child_lot_display(self, obj):
        """Show child lot status."""
        return '✓ Child' if obj.is_child_lot else '◻ Root'
    is_child_lot_display.short_description = 'Lot Type'

    def created_by_display(self, obj):
        """Show creator username."""
        return obj.created_by.username if obj.created_by else '—'
    created_by_display.short_description = 'Submitted By'

    # JSON display methods (formatted for readability)
    def all_trays_json_display(self, obj):
        """Display all_trays_json in formatted way."""
        import json
        return json.dumps(obj.all_trays_json, indent=2) if obj.all_trays_json else '[]'
    all_trays_json_display.short_description = 'All Trays'

    def accepted_trays_json_display(self, obj):
        """Display accepted_trays_json in formatted way."""
        import json
        return json.dumps(obj.accepted_trays_json, indent=2) if obj.accepted_trays_json else '[]'
    accepted_trays_json_display.short_description = 'Accepted Trays'

    def rejected_trays_json_display(self, obj):
        """Display rejected_trays_json in formatted way."""
        import json
        return json.dumps(obj.rejected_trays_json, indent=2) if obj.rejected_trays_json else '[]'
    rejected_trays_json_display.short_description = 'Rejected Trays'

    def rejection_reasons_json_display(self, obj):
        """Display rejection_reasons_json in formatted way."""
        import json
        return json.dumps(obj.rejection_reasons_json, indent=2) if obj.rejection_reasons_json else '{}'
    rejection_reasons_json_display.short_description = 'Rejection Reasons'

    def allocation_preview_json_display(self, obj):
        """Display allocation_preview_json in formatted way."""
        import json
        return json.dumps(obj.allocation_preview_json, indent=2) if obj.allocation_preview_json else '{}'
    allocation_preview_json_display.short_description = 'Allocation Preview'

    def delink_trays_json_display(self, obj):
        """Display delink_trays_json in formatted way."""
        import json
        return json.dumps(obj.delink_trays_json, indent=2) if obj.delink_trays_json else '[]'
    delink_trays_json_display.short_description = 'Delink Trays'


admin.site.register(InputScreening_Submitted, InputScreening_SubmittedAdmin)

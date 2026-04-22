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
# INLINE CLASSES — shown on the parent submission change page
# ============================================================================

class IS_PartialAcceptLotInline(admin.StackedInline):
    """Show accept child lot directly on the parent submission page."""
    model = IS_PartialAcceptLot
    fields = ['new_lot_id', 'accepted_qty', 'accept_trays_count', 'trays_snapshot', 'created_at']
    readonly_fields = ['new_lot_id', 'accepted_qty', 'accept_trays_count', 'trays_snapshot', 'created_at']
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name = "Partial Accept Lot"
    verbose_name_plural = "Partial Accept Lots"


class IS_PartialRejectLotInline(admin.StackedInline):
    """Show reject child lot directly on the parent submission page."""
    model = IS_PartialRejectLot
    fields = ['new_lot_id', 'rejected_qty', 'reject_trays_count', 'rejection_reasons', 'trays_snapshot', 'delink_count', 'created_at']
    readonly_fields = ['new_lot_id', 'rejected_qty', 'reject_trays_count', 'rejection_reasons', 'trays_snapshot', 'delink_count', 'created_at']
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name = "Partial Reject Lot"
    verbose_name_plural = "Partial Reject Lots"


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
        'tray_type',
        'created_at',
        'created_by',
    ]

    # Display columns in list view
    list_display = [
        'lot_id',
        'batch_id',
        'get_submission_type_display',
        'original_lot_qty',
        'active_trays_count',
        'created_at',
        'created_by_display',
    ]

    # Read-only fields (should not be edited after creation)
    readonly_fields = [
        'id',
        'lot_id',
        'created_at',
        'updated_at',
    ]

    # Organized field grouping
    fieldsets = (
        ('🔑 Core Identifiers', {
            'fields': ('id', 'lot_id', 'batch_id', 'module_name'),
        }),
        ('📦 Product & Tray Details', {
            'fields': (
                'plating_stock_no',
                'model_no',
                'tray_type',
                'tray_capacity',
            ),
        }),
        ('📊 Original Lot Info', {
            'fields': (
                'original_lot_qty',
                'active_trays_count',
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
        ('🔗 Status', {
            'fields': (
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
        ('📋 Draft State', {
            'fields': (
                'Draft_Saved',
                'is_submitted',
                'submitted_at',
            ),
        }),
    )

    # Ordering
    ordering = ('-created_at',)

    # Child lot inlines
    inlines = [IS_PartialAcceptLotInline, IS_PartialRejectLotInline]

    # Display methods for list view
    def get_submission_type_display(self, obj):
        """Show submission type with emoji."""
        if obj.is_full_accept:
            return '✅ Full Accept'
        elif obj.is_full_reject:
            return '❌ Full Reject'
        elif obj.is_partial_accept:
            return '⚠️ Partial Accept'
        elif obj.is_partial_reject:
            return '⚠️ Partial Reject'
        else:
            return '⏳ Pending'
    get_submission_type_display.short_description = 'Submission Type'

    def created_by_display(self, obj):
        """Show creator username."""
        return obj.created_by.username if obj.created_by else '—'
    created_by_display.short_description = 'Submitted By'


admin.site.register(InputScreening_Submitted, InputScreening_SubmittedAdmin)


# ============================================================================
# PARTIAL ACCEPT LOT - ADMIN
# ============================================================================

class IS_AllocationTrayInlineAccept(admin.TabularInline):
    """Inline admin for allocation trays within partial accept lot."""
    model = IS_AllocationTray
    fields = ['tray_id', 'qty', 'original_qty', 'top_tray', 'created_at']
    readonly_fields = ['created_at']
    extra = 0
    can_delete = False


class IS_PartialAcceptLotAdmin(admin.ModelAdmin):
    """Admin interface for partial accept child lots."""
    inlines = [IS_AllocationTrayInlineAccept]
    
    list_display = ['new_lot_id', 'parent_lot_id', 'accepted_qty', 'accept_trays_count', 'created_at']
    list_filter = ['created_at', 'parent_batch_id']
    search_fields = ['new_lot_id', 'parent_lot_id', 'parent_batch_id']
    
    readonly_fields = ['new_lot_id', 'created_at']
    
    fieldsets = (
        ('🔑 Lot Identifiers', {
            'fields': ('new_lot_id', 'parent_lot_id', 'parent_batch_id', 'parent_submission'),
        }),
        ('📊 Quantity Information', {
            'fields': ('accepted_qty', 'accept_trays_count'),
        }),
        ('� Tray Allocation Snapshot', {
            'fields': ('trays_snapshot',),
            'description': 'Full dict of each accepted tray with qty, top_tray flag and source.',
        }),
        ('�👤 Audit', {
            'fields': ('created_by', 'created_at'),
        }),
    )
    
    ordering = ('-created_at',)


admin.site.register(IS_PartialAcceptLot, IS_PartialAcceptLotAdmin)


# ============================================================================
# PARTIAL REJECT LOT - ADMIN
# ============================================================================

class IS_AllocationTrayInlineReject(admin.TabularInline):
    """Inline admin for allocation trays within partial reject lot."""
    model = IS_AllocationTray
    fields = ['tray_id', 'qty', 'original_qty', 'rejection_reason_id', 'is_delinked', 'created_at']
    readonly_fields = ['created_at']
    extra = 0
    can_delete = False


class IS_PartialRejectLotAdmin(admin.ModelAdmin):
    """Admin interface for partial reject child lots."""
    inlines = [IS_AllocationTrayInlineReject]
    
    list_display = ['new_lot_id', 'parent_lot_id', 'rejected_qty', 'reject_trays_count', 'delink_count', 'created_at']
    list_filter = ['created_at', 'parent_batch_id', 'delink_count']
    search_fields = ['new_lot_id', 'parent_lot_id', 'parent_batch_id']
    
    readonly_fields = ['new_lot_id', 'created_at']
    
    fieldsets = (
        ('🔑 Lot Identifiers', {
            'fields': ('new_lot_id', 'parent_lot_id', 'parent_batch_id', 'parent_submission'),
        }),
        ('📊 Rejection Information', {
            'fields': ('rejected_qty', 'reject_trays_count', 'delink_count', 'rejection_reasons'),
        }),
        ('� Tray Allocation Snapshot', {
            'fields': ('trays_snapshot',),
            'description': 'Full dict of each reject tray with qty, reason_id, reason_text and source.',
        }),
        ('�📝 Remarks', {
            'fields': ('remarks',),
        }),
        ('👤 Audit', {
            'fields': ('created_by', 'created_at'),
        }),
    )
    
    ordering = ('-created_at',)


admin.site.register(IS_PartialRejectLot, IS_PartialRejectLotAdmin)


# ============================================================================
# ALLOCATION TRAY - STANDALONE ADMIN
# ============================================================================

class IS_AllocationTrayAdmin(admin.ModelAdmin):
    """Admin interface for individual allocated trays."""
    
    list_display = ['tray_id', 'qty', 'get_lot_type', 'created_at']
    list_filter = ['created_at', 'is_delinked']
    search_fields = ['tray_id', 'accept_lot__new_lot_id', 'reject_lot__new_lot_id']
    
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('🔑 Tray Identifier', {
            'fields': ('tray_id', 'qty', 'original_qty'),
        }),
        ('🎯 Allocation', {
            'fields': ('accept_lot', 'reject_lot'),
        }),
        ('📋 Rejection Details', {
            'fields': ('rejection_reason_id', 'is_delinked', 'top_tray'),
        }),
        ('👤 Audit', {
            'fields': ('created_at',),
        }),
    )
    
    ordering = ('-created_at',)
    
    def get_lot_type(self, obj):
        """Show lot type (Accept/Reject)."""
        if obj.accept_lot:
            return '✅ Accept'
        elif obj.reject_lot:
            return '❌ Reject'
        else:
            return '⏳ Unassigned'
    get_lot_type.short_description = 'Lot Type'


admin.site.register(IS_AllocationTray, IS_AllocationTrayAdmin)


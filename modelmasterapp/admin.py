from django.contrib import admin
from .models import *
#test
class ModelMasterAdmin(admin.ModelAdmin):
    list_display = ['model_no', 'brand', 'ep_bath_type', 'plating_stk_no']
    search_fields = ['model_no', 'brand', 'plating_stk_no']
    list_filter = ['brand', 'ep_bath_type']

admin.site.register(ModelMaster, ModelMasterAdmin)
admin.site.register(PolishFinishType)
admin.site.register(TrayType)
admin.site.register(Vendor) 
admin.site.register(ModelMasterCreation)
admin.site.register(Version)
admin.site.register(Location)
admin.site.register(Category)
admin.site.register(TrayId)
admin.site.register(DraftTrayId)

admin.site.register(ModelImage)
admin.site.register(Plating_Color)
admin.site.register(TotalStockModel)
admin.site.register(DP_TrayIdRescan)

admin.site.register(TrayAutoSaveData)
admin.site.register(LookLikeModel)


# ── Universal Lot Hierarchy ──────────────────────────────────────────────────

class LotTraySnapshotInline(admin.TabularInline):
    model = LotTraySnapshot
    extra = 0
    readonly_fields = ('tray_id', 'tray_qty', 'tray_order', 'top_tray', 'tray_status', 'created_at')
    ordering = ('tray_order',)
    can_delete = False
    fk_name = 'lot'


class LotMasterAdmin(admin.ModelAdmin):
    list_display  = ('lot_id', 'parent_lot_id', 'root_lot_id', 'module_name',
                     'source_module', 'submission_type', 'total_qty', 'status', 'active',
                     'created_by', 'created_at')
    list_filter   = ('module_name', 'source_module', 'submission_type', 'status', 'active')
    search_fields = ('lot_id', 'parent_lot_id', 'root_lot_id')
    readonly_fields = ('created_at',)
    inlines       = [LotTraySnapshotInline]


class LotTraySnapshotAdmin(admin.ModelAdmin):
    list_display  = ('tray_id', 'tray_qty', 'tray_order', 'top_tray',
                     'tray_status', 'lot', 'created_at')
    list_filter   = ('tray_status', 'top_tray')
    search_fields = ('tray_id', 'lot__lot_id')
    readonly_fields = ('created_at',)
    ordering      = ('lot', 'tray_order')


admin.site.register(LotMaster, LotMasterAdmin)
admin.site.register(LotTraySnapshot, LotTraySnapshotAdmin)

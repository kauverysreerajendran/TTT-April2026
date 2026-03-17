from django.contrib import admin
from .models import *
# Register your models here.

@admin.register(Spider_ID)
class Spider_IDAdmin(admin.ModelAdmin):
    list_display = ('spider_code', 'zone', 'is_active', 'created_at', 'updated_at')
    list_filter = ('zone', 'is_active', 'created_at')
    search_fields = ('spider_code',)
    readonly_fields = ('created_at', 'updated_at', 'id')
    fieldsets = (
        ('Spider ID Information', {
            'fields': ('spider_code', 'zone', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'id'),
            'classes': ('collapse',)
        }),
    )
    ordering = ('zone', 'spider_code')

admin.site.register(SpiderJigDetails)
admin.site.register(Spider_TrayId)
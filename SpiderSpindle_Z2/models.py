from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class SpiderSpindleZ2TrayId(models.Model):
    """Stores tray IDs linked during Spider Spindle Z2 (other colors)."""
    lot_id = models.CharField(max_length=100, help_text="JigUnloadAfterTable lot_id")
    tray_id = models.CharField(max_length=100, help_text="Auto-fetched Tray ID")
    linked_at = models.DateTimeField(default=timezone.now)
    linked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Spider Spindle Z2 Tray"
        verbose_name_plural = "Spider Spindle Z2 Trays"
        unique_together = ['lot_id', 'tray_id']

    def __str__(self):
        return f"{self.tray_id} - {self.lot_id}"

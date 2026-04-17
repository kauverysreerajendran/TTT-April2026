from django.db import models
from modelmasterapp.models import *

# Create your models here.

class BrassTrayId(models.Model):
    """
    BrassTrayId Model
    Represents a tray identifier in the Titan Track and Traceability system.
    """
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100,  help_text="Tray ID")
    tray_quantity = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    batch_id = models.ForeignKey('modelmasterapp.ModelMasterCreation', on_delete=models.CASCADE, blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True)
    top_tray = models.BooleanField(default=False)


    delink_tray = models.BooleanField(default=False, help_text="Is tray delinked")
    delink_tray_qty = models.CharField(max_length=50, null=True, blank=True, help_text="Delinked quantity")
    
    IP_tray_verified= models.BooleanField(default=False, help_text="Is tray verified in IP")
    
    rejected_tray= models.BooleanField(default=False, help_text="Is tray rejected")

    new_tray=models.BooleanField(default=True, help_text="Is tray new")
    
    # Tray configuration fields (filled by admin)
    tray_type = models.CharField(max_length=50, null=True, blank=True, help_text="Type of tray (Jumbo, Normal, etc.) - filled by admin")
    tray_capacity = models.IntegerField(null=True, blank=True, help_text="Capacity of this specific tray - filled by admin")

    def __str__(self):
        return f"{self.tray_id} - {self.lot_id} - {self.tray_quantity}"

    @property
    def is_available_for_scanning(self):
        """
        Check if tray is available for scanning
        Available if: not scanned OR delinked (can be reused)
        """
        return not self.scanned or self.delink_tray

    @property
    def status_display(self):
        """Get human-readable status"""
        if self.delink_tray:
            return "Delinked (Reusable)"
        elif self.scanned:
            return "Already Scanned"
        elif self.batch_id:
            return "In Use"
        else:
            return "Available"

    class Meta:
        verbose_name = "Brass Tray ID"
        verbose_name_plural = "Brass Tray IDs"
        unique_together = ['lot_id', 'tray_id']


class Brass_QC_Rejection_Table(models.Model):
    rejection_reason_id = models.CharField(max_length=10, null=True, blank=True, editable=False)
    rejection_reason = models.TextField(help_text="Reason for rejection")
    date_time = models.DateTimeField(default=now, help_text="Timestamp of the record")
    def save(self, *args, **kwargs):
        if not self.rejection_reason_id:
            last = Brass_QC_Rejection_Table.objects.order_by('-rejection_reason_id').first()
            if last and last.rejection_reason_id.startswith('R'):
                last_num = int(last.rejection_reason_id[1:])
                new_num = last_num + 1
            else:
                new_num = 1
            self.rejection_reason_id = f"R{new_num:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.rejection_reason} "
 
    
class Brass_QC_Rejection_ReasonStore(models.Model):
    rejection_reason = models.ManyToManyField(Brass_QC_Rejection_Table, blank=True)
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    total_rejection_quantity = models.PositiveIntegerField(help_text="Total Rejection Quantity")
    batch_rejection=models.BooleanField(default=False)
    created_at = models.DateTimeField(default=now, help_text="Timestamp of the record")
    lot_rejected_comment = models.CharField(max_length=255,null=True,blank=True)

    def __str__(self):
        return f"{self.user} - {self.total_rejection_quantity} - {self.lot_id}"
    
# Add these new models to your models.py (if not already exist)
class Brass_QC_Draft_Store(models.Model):
    lot_id = models.CharField(max_length=255)
    batch_id = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    draft_type = models.CharField(max_length=50)  # 'batch_rejection' or 'tray_rejection'
    draft_data = models.JSONField()  # Store all draft data as JSON
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['lot_id', 'draft_type']


class Brass_TopTray_Draft_Store(models.Model):
    lot_id = models.CharField(max_length=255)
    batch_id = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tray_id = models.CharField(max_length=255, blank=True, null=True)
    tray_qty = models.IntegerField(blank=True, null=True)
    
    # ✅ UPDATED: Store delink trays with position information
    delink_trays_data = JSONField(blank=True, default=dict)  # Store structured data: {"positions": [{"position": 0, "tray_id": "JB-A00130", "original_capacity": 12}]}
    
    # ✅ KEEP for backward compatibility (but we'll use delink_trays_data going forward)
    delink_tray_ids = ArrayField(models.CharField(max_length=255), blank=True, default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['lot_id']  # Only one draft per lot
        
    def __str__(self):
        return f"Top Tray Draft - {self.lot_id} - {self.tray_id}"
    
    
class Brass_QC_Rejected_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    rejected_tray_quantity = models.CharField(help_text="Rejected Tray Quantity")
    rejected_tray_id= models.CharField(max_length=100, null=True, blank=True, help_text="Rejected Tray ID")
    rejection_reason = models.ForeignKey(Brass_QC_Rejection_Table, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.rejection_reason} - {self.rejected_tray_quantity} - {self.lot_id}"

class Brass_Qc_Accepted_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    accepted_tray_quantity = models.CharField(help_text="Accepted Tray Quantity")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.accepted_tray_quantity} - {self.lot_id}"
    

    
class Brass_Qc_Accepted_TrayID_Store(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100, unique=True)
    tray_qty = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_draft = models.BooleanField(default=False, help_text="Draft Save")
    is_save= models.BooleanField(default=False, help_text="Save")
    
    def __str__(self):
        return f"{self.tray_id} - {self.lot_id}"


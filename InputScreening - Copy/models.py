from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from .models import * 

 
# Create your models here.

 
class IPTrayId(models.Model):
    """
    TrayId Model
    Represents a tray identifier in the Titan Track and Traceability system.
    """
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100,help_text="Tray ID")
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
        verbose_name = "IP Tray ID"
        verbose_name_plural = "IP Tray IDs"
        unique_together = ['lot_id', 'tray_id']



class IP_TrayVerificationStatus(models.Model):
    lot_id = models.CharField(max_length=100)
    tray_id = models.CharField(max_length=100, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    verification_status = models.CharField(max_length=10, choices=[('pass', 'Pass'), ('fail', 'Fail')], null=True, blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    verified_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['lot_id', 'tray_id']
        
    def __str__(self):
        return f"Lot {self.lot_id}  - {self.verification_status}"        
        
class IP_RejectionGroup(models.Model):
    group_name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.group_name

class IP_Rejection_Table(models.Model):
    rejection_reason_id = models.CharField(max_length=10, null=True, blank=True, editable=False)
    rejection_reason = models.TextField(help_text="Reason for rejection")
    date = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self.rejection_reason_id:
            last = IP_Rejection_Table.objects.order_by('-rejection_reason_id').first()
            if last and last.rejection_reason_id.startswith('R'):
                last_num = int(last.rejection_reason_id[1:])
                new_num = last_num + 1
            else:
                new_num = 1
            self.rejection_reason_id = f"R{new_num:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.rejection_reason}"
  
   
# Add this to your models.py

class IP_Rejection_Draft(models.Model):
    """
    Model to store draft rejection data that can be edited later
    """
    lot_id = models.CharField(max_length=50, unique=True, help_text="Lot ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    draft_data = models.JSONField(help_text="JSON data containing rejection details")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    lot_rejection_remarks = models.CharField(max_length=255, null=True, blank=True, help_text="Lot rejection remarks for batch rejection")

    class Meta:
        unique_together = ['lot_id', 'user']
    
    def __str__(self):
        return f"Draft: {self.lot_id} - {self.user.username}"

#rejection reasons stored tabel , fields ared rejection resoon multiple slection from RejectionTable an dlot_id , user, Total_rejection_qunatity
class IP_Rejection_ReasonStore(models.Model):
    rejection_reason = models.ManyToManyField(IP_Rejection_Table, blank=True)
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    total_rejection_quantity = models.PositiveIntegerField(help_text="Total Rejection Quantity")
    batch_rejection=models.BooleanField(default=False)
    lot_rejected_comment = models.CharField(max_length=255,null=True,blank=True)

    def __str__(self):
        return f"{self.user} - {self.total_rejection_quantity} - {self.lot_id}"
    


#give rejected trayscans - fields are lot_id , rejected_tray_quantity , rejected_reson(forign key from RejectionTable), user
class IP_Rejected_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    rejected_tray_quantity = models.CharField(help_text="Rejected Tray Quantity")
    rejected_tray_id= models.CharField(max_length=100, null=True, blank=True, help_text="Rejected Tray ID")
    rejection_reason = models.ForeignKey(IP_Rejection_Table, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.rejection_reason} - {self.rejected_tray_quantity} - {self.lot_id}"

    

#give accpeted tray scan - fields are lot_id , accepted_tray_quantity , user    
class IP_Accepted_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    accepted_tray_quantity = models.CharField(help_text="Accepted Tray Quantity")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.accepted_tray_quantity} - {self.lot_id}"


    
class IP_Accepted_TrayID_Store(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    top_tray_id = models.CharField(max_length=100)
    top_tray_qty = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_draft = models.BooleanField(default=False, help_text="Draft Save")
    is_save = models.BooleanField(default=False, help_text="Save")
    
    # Store as JSON array: [{"tray_id": "JB-A00075", "qty": 8}, ...]
    delink_trays = models.JSONField(default=list, blank=True, help_text="Multiple Delink Trays")
    
    def __str__(self):
        return f"{self.top_tray_id} - {self.lot_id}"
    
    
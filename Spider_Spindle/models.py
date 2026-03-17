from django.db import models
from modelmasterapp.models import *
# Create your models here.

class Spider_ID(models.Model):
    """
    Spider_ID Master Table
    Stores unique Spider IDs for Zone 1 and Zone 2
    """
    ZONE_CHOICES = [
        (1, 'Zone 1'),
        (2, 'Zone 2'),
    ]
    
    spider_code = models.CharField(
        max_length=20,
        unique=True,
        null=False,
        help_text="Unique Spider ID code (e.g., S098-0001, S144-0001)"
    )
    zone = models.IntegerField(
        choices=ZONE_CHOICES,
        null=False,
        help_text="Zone identifier (1 or 2)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, help_text="Is this Spider ID currently active?")

    def __str__(self):
        return f"{self.spider_code} - Zone {self.zone}"

    class Meta:
        verbose_name = "Spider ID"
        verbose_name_plural = "Spider IDs"
        ordering = ['zone', 'spider_code']
        indexes = [
            models.Index(fields=['zone']),
            models.Index(fields=['spider_code']),
        ]


class Spider_TrayId(models.Model):
    """
    Nickel_AuditTrayId Model
    Represents a tray identifier in the Titan Track and Traceability system.
    """
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100,  help_text="Tray ID")
    tray_quantity = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    batch_id = models.ForeignKey(ModelMasterCreation, on_delete=models.CASCADE, blank=True, null=True)
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
        verbose_name = "Spider Tray ID"
        verbose_name_plural = "Spider Tray IDs"



class SpiderJigDetails(models.Model):
    JIG_POSITION_CHOICES = [
        ('Top', 'Top'),
        ('Middle', 'Middle'),
        ('Bottom', 'Bottom'),
    ]
    jig_qr_id = models.CharField(max_length=100)
    faulty_slots = models.IntegerField(default=0)
    jig_type = models.CharField(max_length=50)  # New field
    jig_capacity = models.IntegerField()        # New field
    bath_tub = models.CharField(max_length=100, help_text="Bath Tub",blank=True, null=True)
    plating_color = models.CharField(max_length=50)
    empty_slots = models.IntegerField(default=0)
    ep_bath_type = models.CharField(max_length=50)
    total_cases_loaded = models.IntegerField()
        #JIG Loading Module - Remaining cases
    jig_cases_remaining_count=models.IntegerField(default=0,blank=True,null=True)

    forging = models.CharField(max_length=100)
    no_of_model_cases = ArrayField(models.CharField(max_length=50), blank=True, default=list)  # Correct ArrayField
    no_of_cycle=models.IntegerField(default=1)
    lot_id = models.CharField(max_length=100)
    new_lot_ids = ArrayField(models.CharField(max_length=50), blank=True, default=list)  # Correct ArrayField
    electroplating_only = models.BooleanField(default=False)
    lot_id_quantities = JSONField(blank=True, null=True)
    draft_save = models.BooleanField(default=False, help_text="Draft Save")
    delink_tray_data = models.JSONField(default=list, blank=True, null=True)  # Add this field
    half_filled_tray_data = models.JSONField(default=list, blank=True, null=True)
    date_time = models.DateTimeField(default=timezone.now)
    bath_numbers = models.ForeignKey(
            BathNumbers,
            on_delete=models.SET_NULL,  
            null=True,                  
            blank=True,
            help_text="Related Bath Numbers"
        )   
    
    jig_position = models.CharField(
        max_length=10,
        choices=JIG_POSITION_CHOICES,
        default='Top',
        help_text="Jig position: Top, Middle, or Bottom"
    )
    remarks = models.CharField(
        max_length=50,
        blank=True,
        help_text="Remarks (max 50 words)"
    )
    pick_remarks=models.CharField(
        max_length=50,
        blank=True,
        help_text="Remarks (max 50 words)"
    )
     
    jig_unload_draft = models.BooleanField(default=False)
    combined_lot_ids = ArrayField(models.CharField(max_length=50), blank=True, default=list)  # Correct ArrayField
    jig_loaded_date_time = models.DateTimeField(null=True, blank=True, help_text="Last Process Date/Time")
    IP_loaded_date_time = models.DateTimeField(null=True, blank=True, help_text="Ip last Process Date/Time")
    last_process_module = models.CharField(max_length=100, blank=True, help_text="Last Process Module")
    unload_over=models.BooleanField(default=False)
    Un_loaded_date_time = models.DateTimeField(null=True, blank=True, help_text="Ip last Process Date/Time")

    def __str__(self):
        return f"{self.jig_qr_id} - {self.lot_id} - {self.no_of_cycle}"
    


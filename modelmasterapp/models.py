from django.db import models
from django.utils import timezone
from django.db.models import F
from django.core.exceptions import ValidationError
import datetime
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.db.models import JSONField
from django.contrib.postgres.fields import ArrayField
from IQF.models import IQF_Rejection_ReasonStore, IQF_Accepted_TrayScan, IQF_Accepted_TrayID_Store, IQF_Rejected_TrayScan, IQF_Rejection_Table 
from InputScreening.models import IP_RejectionGroup, IP_Accepted_TrayScan, IP_Rejection_ReasonStore, IP_Rejected_TrayScan ,IP_Accepted_TrayID_Store
from Jig_Loading.models import *
from Brass_QC.models import Brass_QC_Rejection_Table, Brass_QC_Rejection_ReasonStore, Brass_QC_Rejected_TrayScan, Brass_Qc_Accepted_TrayScan, Brass_Qc_Accepted_TrayID_Store


from django.db import models
from django.contrib.auth.models import User

# Model to track row access locks
class RowAccessLock(models.Model):
    batch_id = models.CharField(max_length=100, db_index=True)
    lot_id = models.CharField(max_length=100, db_index=True)
    accessed_by = models.ForeignKey(User, on_delete=models.CASCADE)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('batch_id', 'lot_id')
        
        

# API for Model Images Masters
class ModelImage(models.Model):
  #give master_image field for mulitple image slection
    master_image = models.ImageField(upload_to='model_images/')
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"Master_Image {self.id}"
    
class PolishFinishType(models.Model):
    polish_finish = models.CharField(max_length=255, unique=True, help_text="Type of polish finish")
    polish_internal = models.CharField(
        max_length=255,
        unique=True,
        default="DefaultInternal",
        help_text="Internal name of the Polish Finish"
    )
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)


    def __str__(self):
        return self.polish_finish 
    
class Plating_Color(models.Model):
    #need choices for plating color field -dropdown field
    plating_color = models.CharField(max_length=255, unique=True, help_text="Plating color")
    plating_color_internal = models.CharField(
        max_length=10, 
        help_text="Short internal code used in stock number (e.g., B for Black)", 
    )
    jig_unload_zone_1 = models.BooleanField(default=False, help_text="Indicates if Jig Unload Zone 1 is active")
    jig_unload_zone_2 = models.BooleanField(default=False, help_text="Indicates if Jig Unload Zone 2 is active")
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.plating_color
    
        
class Version(models.Model):
    version_name = models.CharField(max_length=255, unique=True, help_text="Version name")
    version_internal = models.CharField(max_length=255, unique=True,null=True,blank=True, help_text="Version Internal")
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)


    def __str__(self):
        return self.version_name
    
class TrayType(models.Model):
    tray_type = models.CharField(max_length=255, unique=True, help_text="Type of tray")
    tray_capacity = models.IntegerField(help_text="Number of watches the tray can hold")  
    tray_color = models.CharField(max_length=255, help_text="Color of the tray",blank=True, null=True)  
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.tray_type
    
class Vendor(models.Model):
    vendor_name = models.CharField(max_length=255, unique=True, help_text="Name of the vendor")
    vendor_internal = models.CharField(max_length=255, unique=True, help_text="Internal name of the vendor")
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.vendor_name

class Location(models.Model):
    location_name = models.CharField(max_length=255, unique=True, help_text="Name of the location")
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.location_name
    
class Category(models.Model):
    category_name = models.CharField(max_length=255, unique=True, help_text="Name of the location")
    date_time = models.DateTimeField(default=timezone.now)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.category_name
    
    
class ModelMaster(models.Model):
    # Assuming this model holds the reference data for dropdowns and auto-fetch fields
    model_no = models.CharField(max_length=100)
    polish_finish = models.ForeignKey(PolishFinishType, on_delete=models.SET_NULL, null=True, blank=True)
    ep_bath_type = models.CharField(max_length=100)
    tray_type = models.ForeignKey(TrayType, on_delete=models.SET_NULL, null=True, blank=True)
    tray_capacity = models.IntegerField(null=True, blank=True)
    images = models.ManyToManyField(ModelImage, blank=True)  # Allows multiple images
    vendor_internal = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, blank=True)
    brand = models.CharField(max_length=100,null=True, blank=True)
    gender = models.CharField(max_length=50,null=True, blank=True)
    wiping_required = models.BooleanField(default=False)
    date_time = models.DateTimeField(default=timezone.now)
    version = models.TextField()
    plating_stk_no=models.CharField(max_length=50,null=True, blank=True)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)


    def __str__(self):
        if self.model_no and self.plating_stk_no:
            return f"{self.model_no} ({self.plating_stk_no})"
        elif self.model_no:
            return self.model_no
        elif self.plating_stk_no:
            return self.plating_stk_no
        else:
            return f"ModelMaster ID: {self.id}" 
      
        
class LookLikeModel(models.Model):
    """
    Model to store 'Look Like' relationships between plating stock numbers.
    """
    plating_stk_no = models.ManyToManyField(
        ModelMaster,
        related_name='look_like_models',
        verbose_name="Plating Stock Numbers",
        help_text="Select multiple plating stock numbers from ModelMaster"
    )

    same_plating_stk_no = models.ForeignKey(
        ModelMaster,
        on_delete=models.CASCADE,
        related_name='same_plating_stk_no_references',
        verbose_name="Same Plating Stock Number",
        help_text="Select single plating stock number for same model reference"
    )

    text = models.TextField(
        verbose_name="Look Like Model",
        help_text="Description of what this model looks like"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Look Like Model"
        verbose_name_plural = "Look Like Models"
        ordering = ['-created_at']

    def __str__(self):
        # Show only plating_stk_no for same_plating_stk_no
        return f"Look Like: {self.text[:50]}... (Same: {self.same_plating_stk_no.plating_stk_no})"

    def get_plating_stk_no_list(self):
        """Helper method to get comma-separated plating_stk_no values"""
        return ", ".join([model.plating_stk_no for model in self.plating_stk_no.all() if model.plating_stk_no])

    def get_model_count(self):
        """Helper method to get count of associated models"""
        return self.plating_stk_no.count()

class ModelMasterCreation(models.Model):
    
    #unique_id = models.CharField(max_length=100, unique=True,null=True, blank=True) #not in use
    batch_id = models.CharField(max_length=50, unique=True)
    lot_id = models.CharField(max_length=100, unique=True, null=True, blank=True)  # <== ADD THIS LINE
    model_stock_no = models.ForeignKey(ModelMaster, related_name='model_stock_no', on_delete=models.CASCADE)
    polish_finish = models.CharField(max_length=100)
    ep_bath_type = models.CharField(max_length=100)
    plating_color=models.CharField(max_length=100,null=True,blank=True)
    tray_type = models.CharField(max_length=100)
    tray_capacity = models.IntegerField(null=True, blank=True)
    images = models.ManyToManyField(ModelImage, blank=True)  # Store multiple images
    date_time = models.DateTimeField(default=timezone.now)
    version = models.ForeignKey(Version, on_delete=models.CASCADE, help_text="Version")
    total_batch_quantity = models.IntegerField()  
    initial_batch_quantity = models.IntegerField(default=0) #not in use
    current_batch_quantity = models.IntegerField(default=0)  # not in use
    no_of_trays = models.IntegerField(null=True, blank=True)  # Calculated field
    vendor_internal = models.CharField(max_length=100,null=True, blank=True)
    sequence_number = models.IntegerField(default=0)  # Add this field
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)  # Allow null values
    Moved_to_D_Picker = models.BooleanField(default=False, help_text="Moved to D Picker")
    top_tray_qty_verified = models.BooleanField(default=False, help_text="On Hold Picking")
    verified_tray_qty=models.IntegerField(default=0, help_text="Verified Tray Quantity")
    top_tray_qty_modify=models.IntegerField(default=0, help_text="Top Tray Quantity Modified")
    Draft_Saved=models.BooleanField(default=False,help_text="Draft Save")
    dp_pick_remarks=models.CharField(max_length=100,null=True, blank=True)
    category=models.CharField(max_length=100, null=True, blank=True, help_text="Category of the model")
    plating_stk_no=models.CharField(max_length=100, null=True, blank=True, help_text="Plating Stock Number")
    polishing_stk_no=models.CharField(max_length=100,null=True, blank=True)
    holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Reason for holding the batch")  
    release_reason= models.CharField(max_length=255, null=True, blank=True, help_text="Reason for releasing the batch")
    hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold")
    release_lot =models.BooleanField(default=False)
    previous_lot_status = models.CharField(max_length=50, blank=True, null=True)
    changes = models.CharField(max_length=255, blank=True, null=True, default="Outer Groove")
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
    
        if not self.pk:  # Only set the sequence number for new instances
            last_batch = ModelMasterCreation.objects.order_by('-sequence_number').first()
            self.sequence_number = 1 if not last_batch else last_batch.sequence_number + 1
        
        # Fetch related data from ModelMaster
        model_data = self.model_stock_no
        
        
        self.ep_bath_type = model_data.ep_bath_type
        
        # FIXED: Convert tray_type ForeignKey to string
        if model_data.tray_type:
            self.tray_type = model_data.tray_type.tray_type  # Use the actual field value
        else:
            self.tray_type = ""
        
        self.tray_capacity = model_data.tray_capacity

        super().save(*args, **kwargs)
        self.images.set(model_data.images.all())


    def __str__(self):
        return f"{self.model_stock_no} - {self.batch_id}"

        
class TrayId(models.Model):
    """
    TrayId Model
    Represents a tray identifier in the Titan Track and Traceability system.
    """
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100, unique=True, help_text="Tray ID")
    tray_quantity = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    batch_id = models.ForeignKey(ModelMasterCreation, on_delete=models.CASCADE, blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True)
    top_tray = models.BooleanField(default=False)
    ip_top_tray = models.BooleanField(default=False)
    ip_top_tray_qty= models.IntegerField(default=0, help_text="IP Top Tray Quantity")

    brass_top_tray = models.BooleanField(default=False)
    brass_top_tray_qty= models.IntegerField(default=0, help_text="Brass Top Tray Quantity")

    iqf_top_tray = models.BooleanField(default=False)
    iqf_top_tray_qty= models.IntegerField(default=0, help_text="IQF Top Tray Quantity")


    delink_tray = models.BooleanField(default=False, help_text="Is tray delinked")
    delink_tray_qty = models.CharField(max_length=50, null=True, blank=True, help_text="Delinked quantity")
    
    IP_tray_verified= models.BooleanField(default=False, help_text="Is tray verified in IP")
    
    rejected_tray= models.BooleanField(default=False, help_text="Is tray rejected")
    brass_rejected_tray= models.BooleanField(default=False, help_text="Is brass tray rejected")

    new_tray=models.BooleanField(default=True, help_text="Is tray new")
    
    # Tray configuration fields (filled by admin)
    tray_type = models.CharField(max_length=50, null=True, blank=True, help_text="Type of tray (Jumbo, Normal, etc.) - filled by admin")
    tray_capacity = models.IntegerField(null=True, blank=True, help_text="Capacity of this specific tray - filled by admin")
    
    # NEW FIELD: Scanned status tracking
    scanned = models.BooleanField(default=False, help_text="Indicates if the tray has been scanned/used")

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
        verbose_name = "Tray ID"
        verbose_name_plural = "Tray IDs"
       
       
class DraftTrayId(models.Model):
    """
    TrayId Model
    Represents a tray identifier in the Titan Track and Traceability system.
    """
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100, blank=True, help_text="Tray ID")
    tray_quantity = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    batch_id = models.ForeignKey(ModelMasterCreation, on_delete=models.CASCADE, blank=True, null=True)
    position = models.IntegerField(
        help_text="Position/slot number in the tray scan grid",
        null=True,
        blank=True,
        default=None
    )    
    date = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # ✅ NEW: Add delink fields
    delink_tray = models.BooleanField(default=False, help_text="Is tray delinked")
    delink_tray_qty = models.CharField(max_length=50, null=True, blank=True, help_text="Delinked quantity")
    
    class Meta:
        unique_together = ('batch_id', 'position')
        constraints = [
            models.UniqueConstraint(
                fields=['batch_id', 'tray_id'],
                condition=models.Q(tray_id__gt=''),
                name='unique_non_empty_tray_id_per_batch'
            )
        ]
    
    def __str__(self):
        return f"{self.tray_id or 'Empty'} - Position {self.position} - {self.tray_quantity}"  


class TotalStockModel(models.Model):
    """
    This model is for saving overall stock in Day Planning operation form.
  
    """
    batch_id = models.ForeignKey(ModelMasterCreation, on_delete=models.CASCADE, null=True, blank=True)

    model_stock_no = models.ForeignKey(ModelMaster, on_delete=models.CASCADE, help_text="Model Stock Number")
    version = models.ForeignKey(Version, on_delete=models.CASCADE, help_text="Version")
    total_stock = models.IntegerField(help_text="Total stock quantity")
    polish_finish = models.ForeignKey(PolishFinishType, on_delete=models.SET_NULL, null=True, blank=True, help_text="Polish Finish")

    plating_color = models.ForeignKey(Plating_Color, on_delete=models.SET_NULL, null=True, blank=True, help_text="Plating Color")
    location = models.ManyToManyField(Location, blank=True, help_text="Multiple Locations")
    lot_id = models.CharField(max_length=50, unique=True, null=True, blank=True, help_text="Lot ID")
    created_at = models.DateTimeField(default=now, help_text="Timestamp of the record")
    # day planning missing qty in day planning pick table
    dp_missing_qty = models.IntegerField(default=0, help_text="Missing quantity in day planning")
    dp_physical_qty = models.IntegerField(help_text="Original physical quantity", default=0)  # New field
    dp_physical_qty_edited = models.BooleanField(default=False, help_text="Qunatity Edited in IP")
    cumulative_edit_difference = models.IntegerField(default=0)  # Total edit amount
    original_tray_qty = models.IntegerField(null=True, blank=True)  # Original value
    
    brass_missing_qty= models.IntegerField(default=0, help_text="Missing quantity in Brass QC")
    brass_physical_qty= models.IntegerField(help_text="Original physical quantity in Brass QC", default=0)  # New field
    brass_physical_qty_edited = models.BooleanField(default=False, help_text="Qunatity Edited in Brass")

    brass_audit_missing_qty = models.IntegerField(default=0, help_text="Missing quantity in Brass Audit")
    brass_audit_physical_qty = models.IntegerField(help_text="Original physical quantity in Brass Audit", default=0)
    brass_audit_physical_qty_edited = models.BooleanField(default=False, help_text="Qunatity Edited in Brass")

    iqf_missing_qty = models.IntegerField(default=0, help_text="Missing quantity in IQF")
    iqf_physical_qty = models.IntegerField(help_text="Original physical quantity in IQF", default=0)  # New field
    iqf_physical_qty_edited= models.BooleanField(default=False, help_text="Qunatity Edited in IQF")
    
    jig_physical_qty = models.IntegerField(help_text="Original physical quantity in JIG", default=0)  # New field
    jig_physical_qty_edited = models.BooleanField(default=False, help_text="Qunatity Edited in JIG")    
    
    # New fields for process tracking
    last_process_date_time = models.DateTimeField(null=True, blank=True, help_text="Last Process Date/Time")
    last_process_module = models.CharField(max_length=255, null=True, blank=True, help_text="Last Process Module")
    next_process_module = models.CharField(max_length=255, null=True, blank=True, help_text="Next Process Module")



    bq_last_process_date_time = models.DateTimeField(null=True, blank=True, help_text="Last Process Date/Time")
    iqf_last_process_date_time = models.DateTimeField(null=True, blank=True, help_text="Last Process Date/Time")
    brass_audit_last_process_date_time = models.DateTimeField(null=True, blank=True, help_text="Last Process Date/Time")

    #IP Module accept and rejection
    total_IP_accpeted_quantity = models.IntegerField(default=0, help_text="Total accepted quantity")
    total_qty_after_rejection_IP = models.IntegerField(default=0, help_text="Total rejected quantity")
    
    #Brass QC Module accept and rejection
    brass_qc_accepted_qty = models.IntegerField(default=0, help_text="Brass QC Accepted Quantity")  # New field
    brass_qc_after_rejection_qty = models.IntegerField(default=0, help_text="Brass QC Rejected Quantity")  # New field
    
    #IQF Module accept and rejection
    iqf_accept_qty_after_accept_ftn = models.IntegerField(default=0, help_text="IQF Accepted Quantity")  # New field
    iqf_accepted_qty = models.IntegerField(default=0, help_text="IQF Accepted Quantity")  # New field
    iqf_after_rejection_qty = models.IntegerField(default=0, help_text="IQF Rejected Quantity")  # New field
    
    #IP Verification and tray_scan
    tray_scan_status = models.BooleanField(default=False, help_text="Tray scan status")
    ip_person_qty_verified = models.BooleanField(default=False, help_text="IP Person Quantity Verified")  # New field
    draft_tray_verify = models.BooleanField(default=False, help_text="Draft Tray Verified")  # After Verify the qty - Based on this show Draft mode
    accepted_Ip_stock = models.BooleanField(default=False, help_text="Accepted IP Stock")  # New fiel
    few_cases_accepted_Ip_stock = models.BooleanField(default=False, help_text="Few Accepted IP Stock")  # New field
    rejected_ip_stock = models.BooleanField(default=False, help_text="Rejected IP Stock")  # New field
    wiping_status = models.BooleanField(default=False, help_text="Wiping Status")  # New field
    IP_pick_remarks=models.CharField(max_length=100, null=True, blank=True, help_text="IP Pick Remarks")
    Bq_pick_remarks= models.CharField(max_length=100, null=True, blank=True, help_text="BQ Pick Remarks")  # New field
    BA_pick_remarks= models.CharField(max_length=100, null=True, blank=True, help_text="BA Pick Remarks")  # New field
    IQF_pick_remarks= models.CharField(max_length=100, null=True, blank=True, help_text="IQF Pick Remarks")  # New field
    
    rejected_tray_scan_status=models.BooleanField(default=False)
    accepted_tray_scan_status=models.BooleanField(default=False)
    ip_onhold_picking =models.BooleanField(default=False)
    
    #Brass QC Module accept and rejection
    brass_qc_accptance=models.BooleanField(default=False)
    brass_qc_few_cases_accptance=models.BooleanField(default=False)
    brass_qc_rejection=models.BooleanField(default=False)
    brass_rejection_tray_scan_status=models.BooleanField(default=False)
    brass_accepted_tray_scan_status=models.BooleanField(default=False)
    brass_onhold_picking=models.BooleanField(default=False, help_text="Brass QC On Hold Picking")
    brass_draft=models.BooleanField(default=False, help_text="Brass QC Draft Save")
    brass_qc_accepted_qty_verified= models.BooleanField(default=False, help_text="Brass QC Accepted Quantity Verified")  # New field

    #Brass Audit Module accept and rejection
    brass_audit_accptance=models.BooleanField(default=False)
    brass_audit_few_cases_accptance=models.BooleanField(default=False)
    brass_audit_rejection=models.BooleanField(default=False)
    brass_audit_rejection_tray_scan_status=models.BooleanField(default=False)
    brass_audit_accepted_tray_scan_status=models.BooleanField(default=False)
    brass_audit_onhold_picking=models.BooleanField(default=False, help_text="Brass Audit On Hold Picking")
    brass_audit_accepted_qty_verified= models.BooleanField(default=False, help_text="Brass QC Accepted Quantity Verified")  # New field
    brass_audit_accepted_qty = models.IntegerField(default=0, help_text="Brass audit Accepted Quantity")  # New field
    brass_audit_draft=models.BooleanField(default=False, help_text="Brass Audit Draft Save")

    #IQF Module accept and rejection
    iqf_accepted_qty_verified=models.BooleanField(default=False, help_text="IQF Accepted Quantity Verified")  # New field
    iqf_acceptance=models.BooleanField(default=False)
    iqf_few_cases_acceptance=models.BooleanField(default=False)
    iqf_rejection=models.BooleanField(default=False)
    iqf_rejection_tray_scan_status=models.BooleanField(default=False)
    iqf_accepted_tray_scan_status=models.BooleanField(default=False)
    iqf_onhold_picking=models.BooleanField(default=False, help_text="IQF On Hold Picking")
    tray_verify=models.BooleanField(default=False, help_text="Tray Verify")
    #Module is IQF - Acceptance - Send to Brass QC 
    send_brass_qc=models.BooleanField(default=False, help_text="Send to Brass QC")
    send_brass_audit_to_qc=models.BooleanField(default=False, help_text="Send to Brass Audit QC")
    send_brass_audit_to_iqf=models.BooleanField(default=False, help_text="Send to IQF")
    
    jig_lot_status = models.CharField(
        max_length=50,
        choices=[
            ('READY', 'Ready for Jig Loading'),
            ('PARTIAL_DRAFT', 'Partial Draft - Model 2+ in Progress'),
            ('FULL_DRAFT', 'Full Draft - Awaiting Submit'),
            ('SUBMITTED', 'Submitted to IP Inspection'),
        ],
        default='READY',
        help_text='Jig Loading lot status - controls Add Mode eligibility',
    )
    jig_draft=models.BooleanField(default=False, help_text="Jig Draft Save")
    Jig_Load_completed =models.BooleanField(default=False, help_text="Jig Load Completed")
    jig_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Jig Reason for holding the batch")
    jig_release_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Jig Reason for releasing the batch")
    jig_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n Jig")
    jig_release_lot =models.BooleanField(default=False)
    jig_pick_remarks = models.CharField(max_length=255, null=True, blank=True, help_text="Jig Pick Remarks")
    
    inprocess_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Inprocess Reason for holding the batch")
    inprocess_release_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Inprocess Reason for releasing the batch")
    inprocess_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n Inprocess")
    inprocess_release_lot = models.BooleanField(default=False)
    
    ip_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="IP Reason for holding the batch")  
    ip_release_reason= models.CharField(max_length=255, null=True, blank=True, help_text="IP Reason for releasing the batch")
    ip_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n IP")
    ip_release_lot =models.BooleanField(default=False)
    
    brass_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for holding the batch")  
    brass_release_reason= models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for releasing the batch")
    brass_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n Brass")
    brass_release_lot =models.BooleanField(default=False)
    
    brass_audit_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for holding the batch")  
    brass_audit_release_reason= models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for releasing the batch")
    brass_audit_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n Brass")
    brass_audit_release_lot =models.BooleanField(default=False)

    iqf_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="IQF Reason for holding the batch")  
    iqf_release_reason= models.CharField(max_length=255, null=True, blank=True, help_text="IQF Reason for releasing the batch")
    iqf_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n IQF")
    iqf_release_lot =models.BooleanField(default=False)
    
    ip_top_tray_qty_verified = models.BooleanField(default=False, help_text="IP-On Hold Picking")
    ip_verified_tray_qty=models.IntegerField(default=0, help_text="IP-Verified Tray Quantity")
    ip_top_tray_qty_modify=models.IntegerField(default=0, help_text="IP-Top Tray Quantity Modified")

    remove_lot=models.BooleanField(default=False, help_text="Indicates if the lot is to be removed")
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.model_stock_no.model_no} - {self.version.version_name} - {self.lot_id}"

    def delete(self, *args, **kwargs):
        if self.lot_id:
            # Delete related records with the same lot_id
            TrayId.objects.filter(lot_id=self.lot_id).delete()
            DraftTrayId.objects.filter(lot_id=self.lot_id).delete()
            DP_TrayIdRescan.objects.filter(lot_id=self.lot_id).delete()
            IP_Rejection_ReasonStore.objects.filter(lot_id=self.lot_id).delete()
            Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=self.lot_id).delete()
            IQF_Rejection_ReasonStore.objects.filter(lot_id=self.lot_id).delete()
            IP_Rejected_TrayScan.objects.filter(lot_id=self.lot_id).delete()
            Brass_QC_Rejected_TrayScan.objects.filter(lot_id=self.lot_id).delete()
            IQF_Rejected_TrayScan.objects.filter(lot_id=self.lot_id).delete()
            IP_Accepted_TrayScan.objects.filter(lot_id=self.lot_id).delete()
            Brass_Qc_Accepted_TrayScan.objects.filter(lot_id=self.lot_id).delete()
            IQF_Accepted_TrayScan.objects.filter(lot_id=self.lot_id).delete()
            IP_Accepted_TrayID_Store.objects.filter(lot_id=self.lot_id).delete()
            Brass_Qc_Accepted_TrayID_Store.objects.filter(lot_id=self.lot_id).delete()
            IQF_Accepted_TrayID_Store.objects.filter(lot_id=self.lot_id).delete()
        
        super().delete(*args, **kwargs)



class DP_TrayIdRescan(models.Model):
    """
    Stores tray ID rescans during the day planning process.
    """
    tray_id = models.CharField(max_length=100, unique=True)
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    date = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    scan_count = models.PositiveIntegerField(default=1)  # Count how many times scanned

    class Meta:
        unique_together = ('tray_id', 'lot_id')  # Ensure each tray_id and lot_id combination is unique

    def __str__(self):
        return f"{self.tray_id} - {self.lot_id} (Scanned: {self.scan_count})"

     

  
class Nickle_IP_Rejection_Table(models.Model):
    group = models.ForeignKey(IP_RejectionGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='nickle_rejection_reasons')
    rejection_reason_id = models.CharField(max_length=10, null=True, blank=True, editable=False)
    rejection_reason = models.TextField(help_text="Reason for rejection")
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.rejection_reason_id:
            last = Nickle_IP_Rejection_Table.objects.order_by('-rejection_reason_id').first()
            if last and last.rejection_reason_id.startswith('R'):
                last_num = int(last.rejection_reason_id[1:])
                new_num = last_num + 1
            else:
                new_num = 1
            self.rejection_reason_id = f"R{new_num:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.rejection_reason}"

#rejection reasons stored tabel , fields ared rejection resoon multiple slection from RejectionTable an dlot_id , user, Total_rejection_qunatity
class Nickle_IP_Rejection_ReasonStore(models.Model):
    rejection_reason = models.ManyToManyField(Nickle_IP_Rejection_Table, blank=True)
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    total_rejection_quantity = models.PositiveIntegerField(help_text="Total Rejection Quantity")
    batch_rejection=models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.user} - {self.total_rejection_quantity} - {self.lot_id}"
    
#give rejected trayscans - fields are lot_id , rejected_tray_quantity , rejected_reson(forign key from RejectionTable), user
class Nickle_IP_Rejected_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    rejected_tray_quantity = models.CharField(help_text="Rejected Tray Quantity")
    rejected_tray_id= models.CharField(max_length=100, null=True, blank=True, help_text="Rejected Tray ID")
    rejection_reason = models.ForeignKey(Nickle_IP_Rejection_Table, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.rejection_reason} - {self.rejected_tray_quantity} - {self.lot_id}"

class Nickle_IP_Accepted_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    accepted_tray_quantity = models.CharField(help_text="Accepted Tray Quantity")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.accepted_tray_quantity} - {self.lot_id}"
    
class Nickle_IP_Accepted_TrayID_Store(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100, unique=True)
    tray_qty = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_draft = models.BooleanField(default=False, help_text="Draft Save")
    is_save= models.BooleanField(default=False, help_text="Save")
     
    def __str__(self):
        return f"{self.tray_id} - {self.lot_id}"
    
class Nickle_Audit_Rejection_Table(models.Model):
    group = models.ForeignKey(IP_RejectionGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='nickle_audit_rejection_reasons')
    rejection_reason_id = models.CharField(max_length=10, null=True, blank=True, editable=False)
    rejection_reason = models.TextField(help_text="Reason for rejection")
    createdby= models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.rejection_reason_id:
            last = Nickle_Audit_Rejection_Table.objects.order_by('-rejection_reason_id').first()
            if last and last.rejection_reason_id.startswith('R'):
                last_num = int(last.rejection_reason_id[1:])
                new_num = last_num + 1
            else:
                new_num = 1
            self.rejection_reason_id = f"R{new_num:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.rejection_reason}"

#rejection reasons stored tabel , fields ared rejection resoon multiple slection from RejectionTable an dlot_id , user, Total_rejection_qunatity
class Nickle_Audit_Rejection_ReasonStore(models.Model):
    rejection_reason = models.ManyToManyField(Nickle_Audit_Rejection_Table, blank=True)
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    total_rejection_quantity = models.PositiveIntegerField(help_text="Total Rejection Quantity")
    batch_rejection=models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.user} - {self.total_rejection_quantity} - {self.lot_id}"
    
#give rejected trayscans - fields are lot_id , rejected_tray_quantity , rejected_reson(forign key from RejectionTable), user
class Nickle_Audit_Rejected_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    rejected_tray_quantity = models.CharField(help_text="Rejected Tray Quantity")
    rejected_tray_id= models.CharField(max_length=100, null=True, blank=True, help_text="Rejected Tray ID")
    rejection_reason = models.ForeignKey(Nickle_Audit_Rejection_Table, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.rejection_reason} - {self.rejected_tray_quantity} - {self.lot_id}"

class Nickle_Audit_Accepted_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    accepted_tray_quantity = models.CharField(help_text="Accepted Tray Quantity")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.accepted_tray_quantity} - {self.lot_id}"
    
class Nickle_Audit_Accepted_TrayID_Store(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100, unique=True)
    tray_qty = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_draft = models.BooleanField(default=False, help_text="Draft Save")
    is_save= models.BooleanField(default=False, help_text="Save")
     
    def __str__(self):
        return f"{self.tray_id} - {self.lot_id}"
    
    
    
class TrayAutoSaveData(models.Model):
    """
    Model to store auto-save data for tray scan modal
    Supports cross-browser and user-specific auto-save
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tray_autosave')
    batch_id = models.CharField(max_length=100, db_index=True)
    auto_save_data = models.JSONField()  # Stores the complete tray data
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'batch_id']  # One auto-save per user per batch
        db_table = 'tray_auto_save_data'
        indexes = [
            models.Index(fields=['user', 'batch_id']),
            models.Index(fields=['updated_at']),
        ]
    
    def is_expired(self, hours=24):
        """Check if auto-save data is older than specified hours"""
        from datetime import timedelta
        return timezone.now() - self.updated_at > timedelta(hours=hours)
    
    def __str__(self):
        return f"AutoSave: {self.user.username} - {self.batch_id}"
    


from django.db.models.signals import post_delete
from django.dispatch import receiver

@receiver(post_delete, sender=ModelMasterCreation)
def delete_related_trayids(sender, instance, **kwargs):
    TrayId.objects.filter(batch_id=instance).delete()
    DraftTrayId.objects.filter(batch_id=instance).delete()
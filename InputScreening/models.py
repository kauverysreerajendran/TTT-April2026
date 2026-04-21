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
        indexes = [
            models.Index(fields=['lot_id'], name='ip_tray_lot_idx'),
            models.Index(fields=['tray_id'], name='ip_tray_tray_idx'),
            models.Index(fields=['lot_id', 'delink_tray'], name='ip_tray_lot_delink_idx'),
        ]



class IP_TrayVerificationStatus(models.Model):
    lot_id = models.CharField(max_length=100)
    tray_id = models.CharField(max_length=100, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    verification_status = models.CharField(max_length=10, choices=[('pass', 'Pass'), ('fail', 'Fail')], null=True, blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    verified_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['lot_id', 'tray_id']
        indexes = [
            models.Index(fields=['lot_id', 'is_verified'], name='ip_tvs_lot_verified_idx'),
            models.Index(fields=['tray_id'], name='ip_tvs_tray_idx'),
        ]
        
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

    class Meta:
        indexes = [
            models.Index(fields=['lot_id'], name='ip_rej_store_lot_idx'),
        ]

    def __str__(self):
        return f"{self.user} - {self.total_rejection_quantity} - {self.lot_id}"
    


#give rejected trayscans - fields are lot_id , rejected_tray_quantity , rejected_reson(forign key from RejectionTable), user
class IP_Rejected_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    rejected_tray_quantity = models.CharField(help_text="Rejected Tray Quantity")
    rejected_tray_id= models.CharField(max_length=100, null=True, blank=True, help_text="Rejected Tray ID")
    rejection_reason = models.ForeignKey(IP_Rejection_Table, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    class Meta:
        indexes = [
            models.Index(fields=['lot_id'], name='ip_rej_tray_lot_idx'),
        ]
    
    def __str__(self):
        return f"{self.rejection_reason} - {self.rejected_tray_quantity} - {self.lot_id}"

    

#give accpeted tray scan - fields are lot_id , accepted_tray_quantity , user    
class IP_Accepted_TrayScan(models.Model):
    lot_id = models.CharField(max_length=50, null=True, blank=True, help_text="Lot ID")
    accepted_tray_quantity = models.CharField(help_text="Accepted Tray Quantity")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    class Meta:
        indexes = [
            models.Index(fields=['lot_id'], name='ip_acc_tray_lot_idx'),
        ]
    
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
    
    class Meta:
        indexes = [
            models.Index(fields=['lot_id'], name='ip_acc_id_lot_idx'),
        ]
    
    def __str__(self):
        return f"{self.top_tray_id} - {self.lot_id}"


# ============================================================================
# INPUT SCREENING SUBMITTED MODEL - PERMANENT SNAPSHOT OF TRUTH
# ============================================================================

class InputScreening_Submitted(models.Model):
    """
    Permanent immutable snapshot of Input Screening submitted records.
    
    This model acts as the definitive source of truth AFTER submit, storing:
    - Complete state of acceptance/rejection decisions
    - All tray allocations exactly as submitted
    - All rejection reasons with quantities
    - Parent-child lot relationships for splits
    - Atomic transaction safety with no half-saves
    
    Key guarantees:
    - One record per submitted lot (uniqueness via lot_id)
    - Child lots are fully independent after split
    - Parent lot retains only remaining balance
    - Future modules use child lot data, never parent again
    - Fast queries via indexed lot_id, parent_lot_id, batch_id
    - Revokable for audit/rollback scenarios
    """

    # ─────────────────────────────────────────────────────────────────────
    # Core Identifiers
    # ─────────────────────────────────────────────────────────────────────

    id = models.AutoField(primary_key=True, help_text="Auto-generated primary key")
    
    lot_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique lot ID (LID format: LID{uuid})"
    )
    
    parent_lot_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        help_text="Original parent lot if this is a split child (null for unsplit or parent)"
    )
    
    batch_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Batch ID from ModelMasterCreation"
    )
    
    module_name = models.CharField(
        max_length=100,
        default="Input Screening",
        help_text="Module name (always 'Input Screening' for this table)"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Product & Tray Information
    # ─────────────────────────────────────────────────────────────────────

    plating_stock_no = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Plating stock number"
    )
    
    model_no = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Model number"
    )
    
    tray_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Type of tray (Jumbo, Normal, etc.)"
    )
    
    tray_capacity = models.IntegerField(
        null=True,
        blank=True,
        help_text="Capacity of each tray"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Quantity Tracking
    # ─────────────────────────────────────────────────────────────────────

    original_lot_qty = models.IntegerField(
        help_text="Original lot quantity before any submission"
    )
    
    submitted_lot_qty = models.IntegerField(
        help_text="Submitted lot quantity (may differ if partial)"
    )
    
    accepted_qty = models.IntegerField(
        default=0,
        help_text="Total accepted quantity"
    )
    
    rejected_qty = models.IntegerField(
        default=0,
        help_text="Total rejected quantity"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Tray Allocation Summary
    # ─────────────────────────────────────────────────────────────────────

    active_trays_count = models.IntegerField(
        default=0,
        help_text="Count of active trays used in this submission"
    )
    
    reject_trays_count = models.IntegerField(
        default=0,
        help_text="Count of trays holding rejected quantity"
    )
    
    accept_trays_count = models.IntegerField(
        default=0,
        help_text="Count of trays holding accepted quantity"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Top Tray Information
    # ─────────────────────────────────────────────────────────────────────

    top_tray_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="ID of top tray (if used)"
    )
    
    top_tray_qty = models.IntegerField(
        null=True,
        blank=True,
        help_text="Quantity in top tray"
    )
    
    has_top_tray = models.BooleanField(
        default=False,
        help_text="Whether a top tray was used in allocation"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Submission Details
    # ─────────────────────────────────────────────────────────────────────

    remarks = models.TextField(
        null=True,
        blank=True,
        help_text="Operator remarks or comments"
    )

    is_partial_accept = models.BooleanField(
        default=False,
        help_text="True if partial acceptance occurred (split into child lot)"
    )
    
    is_partial_reject = models.BooleanField(
        default=False,
        help_text="True if partial rejection occurred (split into child lot)"
    )
    
    is_full_accept = models.BooleanField(
        default=False,
        help_text="True if entire lot was accepted"
    )
    
    is_full_reject = models.BooleanField(
        default=False,
        help_text="True if entire lot was rejected"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Lot Hierarchy & State
    # ─────────────────────────────────────────────────────────────────────

    is_child_lot = models.BooleanField(
        default=False,
        help_text="True if this lot was created from a parent split"
    )
    
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True if active; False if revoked/superseded"
    )
    
    is_revoked = models.BooleanField(
        default=False,
        help_text="True if this submission was revoked in audit"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Audit Trail
    # ─────────────────────────────────────────────────────────────────────

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who submitted"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp of submission"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp"
    )

    # ─────────────────────────────────────────────────────────────────────
    # JSON Snapshot Fields - Complete Immutable Data
    # ─────────────────────────────────────────────────────────────────────

    all_trays_json = models.JSONField(
        default=list,
        blank=True,
        help_text="""
        Complete list of all trays in this submission.
        Schema: [{"tray_id": "NB-A00181", "qty": 16, "top_tray": true, "type": "Normal"}, ...]
        """
    )
    
    accepted_trays_json = models.JSONField(
        default=list,
        blank=True,
        help_text="""
        Trays allocated to accepted quantity.
        Schema: [{"tray_id": "NB-A00182", "qty": 16, "top_tray": false}, ...]
        """
    )
    
    rejected_trays_json = models.JSONField(
        default=list,
        blank=True,
        help_text="""
        Trays allocated to rejected quantity.
        Schema: [{"tray_id": "NB-A00183", "qty": 16}, ...]
        """
    )
    
    rejection_reasons_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        Rejection reasons with quantities.
        Schema: {"R01": {"reason": "VERSION MIXUP", "qty": 10}, 
                 "R02": {"reason": "MODEL MIXUP", "qty": 6}}
        """
    )
    
    allocation_preview_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        Final allocation preview snapshot.
        Schema: {"total_reject_qty": 16, 
                 "total_accept_qty": 484, 
                 "reusable_trays": [...],
                 "new_trays_required": 30}
        """
    )
    
    delink_trays_json = models.JSONField(
        default=list,
        blank=True,
        help_text="""
        Delinked trays available for reuse.
        Schema: [{"tray_id": "JB-A00075", "qty": 8, "capacity": 20}, ...]
        """
    )

    class Meta:
        verbose_name = "Input Screening Submitted Record"
        verbose_name_plural = "Input Screening Submitted Records"
        ordering = ['-created_at']
        
        # Comprehensive indexing for production scale
        indexes = [
            models.Index(fields=['lot_id'], name='iss_lot_id_idx'),
            models.Index(fields=['parent_lot_id'], name='iss_parent_lot_id_idx'),
            models.Index(fields=['batch_id'], name='iss_batch_id_idx'),
            models.Index(fields=['is_active'], name='iss_is_active_idx'),
            models.Index(fields=['created_at'], name='iss_created_at_idx'),
            models.Index(fields=['lot_id', 'is_active'], name='iss_lot_active_idx'),
            models.Index(fields=['parent_lot_id', 'is_child_lot'], name='iss_parent_child_idx'),
            models.Index(fields=['batch_id', 'is_active'], name='iss_batch_active_idx'),
            models.Index(fields=['is_partial_accept', 'is_partial_reject'], name='iss_split_type_idx'),
        ]

    def __str__(self):
        status = "REVOKED" if self.is_revoked else ("ACTIVE" if self.is_active else "INACTIVE")
        split_marker = " [CHILD]" if self.is_child_lot else ""
        return f"{self.lot_id} ({status}){split_marker} - Batch: {self.batch_id}"

    def get_display_status(self):
        """Human-readable status for templates/admin."""
        if self.is_revoked:
            return "❌ Revoked"
        if self.is_full_accept:
            return "✅ Full Accept"
        if self.is_full_reject:
            return "❌ Full Reject"
        if self.is_partial_accept:
            return "⚠️ Partial Accept + Split"
        if self.is_partial_reject:
            return "⚠️ Partial Reject + Split"
        return "⏳ Pending"

    def generate_child_lot_id(self):
        """
        Generate a new independent lot ID for split child lots.
        Format: LID{uuid.uuid4().hex[:12].upper()}
        
        Used when:
        - Partial accept: creates independent accept lot
        - Partial reject: creates independent reject lot
        """
        import uuid
        return f"LID{uuid.uuid4().hex[:12].upper()}"
    
    
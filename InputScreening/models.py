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

# =============================================================================
# INPUT SCREENING SUBMITTED RECORDS - MATCHING JIG LOADING PATTERN
# =============================================================================

class InputScreening_Submitted(models.Model):
    """
    Parent lot record for Input Screening submissions.
    Stores metadata about the original lot that was processed.
    
    This is the SSOT (Single Source of Truth) for parent lot information.
    Child lots (partial accept/reject) have their own separate records.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Core Identifiers
    # ─────────────────────────────────────────────────────────────────────

    lot_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique parent lot ID (LID format)"
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
    # Product Information
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
    # Quantity Information
    # ─────────────────────────────────────────────────────────────────────

    original_lot_qty = models.IntegerField(
        help_text="Original lot quantity at Input Screening start"
    )

    active_trays_count = models.IntegerField(
        default=0,
        help_text="Count of active trays used"
    )

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
        help_text="Whether a top tray was used"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Submission Metadata
    # ─────────────────────────────────────────────────────────────────────

    remarks = models.TextField(
        null=True,
        blank=True,
        help_text="Operator remarks"
    )

    is_full_accept = models.BooleanField(
        default=False,
        help_text="True if entire lot was accepted"
    )

    is_full_reject = models.BooleanField(
        default=False,
        help_text="True if entire lot was rejected"
    )

    is_partial_accept = models.BooleanField(
        default=False,
        help_text="True if partial accept occurred (has related partial accept lot)"
    )

    is_partial_reject = models.BooleanField(
        default=False,
        help_text="True if partial reject occurred (has related partial reject lot)"
    )

    # ─────────────────────────────────────────────────────────────────────
    # State Flags
    # ─────────────────────────────────────────────────────────────────────

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True if this record is active"
    )

    is_revoked = models.BooleanField(
        default=False,
        help_text="True if revoked in audit"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Draft & Submission State
    # ─────────────────────────────────────────────────────────────────────

    Draft_Saved = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if draft save (not finalized)"
    )

    is_submitted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if final submit completed"
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

    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp of final submission"
    )

    class Meta:
        verbose_name = "Input Screening Submitted Record"
        verbose_name_plural = "Input Screening Submitted Records"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['lot_id'], name='iss_lot_id_idx'),
            models.Index(fields=['batch_id'], name='iss_batch_id_idx'),
            models.Index(fields=['is_active'], name='iss_is_active_idx'),
            models.Index(fields=['created_at'], name='iss_created_at_idx'),
            models.Index(fields=['lot_id', 'is_active'], name='iss_lot_active_idx'),
            models.Index(fields=['batch_id', 'is_active'], name='iss_batch_active_idx'),
        ]

    def __str__(self):
        status = "REVOKED" if self.is_revoked else ("ACTIVE" if self.is_active else "INACTIVE")
        return f"{self.lot_id} ({status}) - Batch: {self.batch_id}"


class IS_PartialAcceptLot(models.Model):
    """
    Partial accept lot — new lot ID created when partial acceptance occurs.
    Stores the accepted quantity and its tray allocation.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Core Identifiers
    # ─────────────────────────────────────────────────────────────────────

    new_lot_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Generated lot ID for partial accept (LID format)"
    )

    parent_lot_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Original parent lot ID"
    )

    parent_batch_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Parent batch ID"
    )

    parent_submission = models.ForeignKey(
        InputScreening_Submitted,
        on_delete=models.CASCADE,
        related_name='partial_accept_lots',
        help_text="Reference to parent submission"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Quantity Information
    # ─────────────────────────────────────────────────────────────────────

    accepted_qty = models.IntegerField(
        help_text="Total accepted quantity for this lot"
    )

    accept_trays_count = models.IntegerField(
        default=0,
        help_text="Count of trays holding accepted quantity"
    )

    trays_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text="Snapshot of accept tray allocations at submission: [{tray_id, qty, top_tray, source}]"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Audit Trail
    # ─────────────────────────────────────────────────────────────────────

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp of creation"
    )

    class Meta:
        verbose_name = "Input Screening Partial Accept Lot"
        verbose_name_plural = "Input Screening Partial Accept Lots"
        indexes = [
            models.Index(fields=['new_lot_id']),
            models.Index(fields=['parent_lot_id']),
            models.Index(fields=['parent_batch_id']),
        ]

    def __str__(self):
        return f"PartialAccept: {self.new_lot_id} (from {self.parent_lot_id}, qty={self.accepted_qty})"


class IS_PartialRejectLot(models.Model):
    """
    Partial reject lot — new lot ID created when partial rejection occurs.
    Stores the rejected quantity, rejection reasons, and tray allocation.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Core Identifiers
    # ─────────────────────────────────────────────────────────────────────

    new_lot_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Generated lot ID for partial reject (LID format)"
    )

    parent_lot_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Original parent lot ID"
    )

    parent_batch_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Parent batch ID"
    )

    parent_submission = models.ForeignKey(
        InputScreening_Submitted,
        on_delete=models.CASCADE,
        related_name='partial_reject_lots',
        help_text="Reference to parent submission"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Quantity Information
    # ─────────────────────────────────────────────────────────────────────

    rejected_qty = models.IntegerField(
        help_text="Total rejected quantity for this lot"
    )

    reject_trays_count = models.IntegerField(
        default=0,
        help_text="Count of trays holding rejected quantity"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Rejection Reasons
    # ─────────────────────────────────────────────────────────────────────

    rejection_reasons = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        Rejection reasons with quantities.
        Schema: {"R01": {"reason": "VERSION MIXUP", "qty": 10}, 
                 "R02": {"reason": "MODEL MIXUP", "qty": 6}}
        """
    )

    delink_count = models.IntegerField(
        default=0,
        help_text="Number of trays delinked for reuse"
    )

    trays_snapshot = models.JSONField(
        default=list,
        blank=True,
        help_text="Snapshot of reject tray allocations at submission: [{tray_id, qty, reason_id, reason_text, source, is_delinked}]"
    )

    remarks = models.TextField(
        null=True,
        blank=True,
        help_text="Rejection remarks"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Audit Trail
    # ─────────────────────────────────────────────────────────────────────

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp of creation"
    )

    class Meta:
        verbose_name = "Input Screening Partial Reject Lot"
        verbose_name_plural = "Input Screening Partial Reject Lots"
        indexes = [
            models.Index(fields=['new_lot_id']),
            models.Index(fields=['parent_lot_id']),
            models.Index(fields=['parent_batch_id']),
        ]

    def __str__(self):
        return f"PartialReject: {self.new_lot_id} (from {self.parent_lot_id}, qty={self.rejected_qty})"


class IS_AllocationTray(models.Model):
    """
    Individual tray allocation records for both accept and reject.
    Links to either IS_PartialAcceptLot or IS_PartialRejectLot.
    """

    # ─────────────────────────────────────────────────────────────────────
    # Identifiers & References
    # ─────────────────────────────────────────────────────────────────────

    tray_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Physical tray ID"
    )

    # Foreign key to either accept or reject lot (nullable, one should be set)
    accept_lot = models.ForeignKey(
        IS_PartialAcceptLot,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='allocation_trays',
        help_text="Reference to accept lot (if this tray is for accepted qty)"
    )

    reject_lot = models.ForeignKey(
        IS_PartialRejectLot,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='allocation_trays',
        help_text="Reference to reject lot (if this tray is for rejected qty)"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Tray Information
    # ─────────────────────────────────────────────────────────────────────

    qty = models.IntegerField(
        help_text="Quantity allocated to this tray"
    )

    original_qty = models.IntegerField(
        default=0,
        help_text="Original tray quantity before any split"
    )

    top_tray = models.BooleanField(
        default=False,
        help_text="Is this the top tray?"
    )

    # For reject trays: which rejection reason applies
    rejection_reason_id = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Rejection reason ID (e.g. R01, R02)"
    )

    rejection_reason_text = models.TextField(
        null=True,
        blank=True,
        help_text="Rejection reason description"
    )

    # For delinked trays
    is_delinked = models.BooleanField(
        default=False,
        help_text="Is this tray delinked (reused)?"
    )

    # ─────────────────────────────────────────────────────────────────────
    # Audit Trail
    # ─────────────────────────────────────────────────────────────────────

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp of allocation"
    )

    class Meta:
        verbose_name = "Input Screening Allocation Tray"
        verbose_name_plural = "Input Screening Allocation Trays"
        indexes = [
            models.Index(fields=['tray_id']),
            models.Index(fields=['accept_lot', 'tray_id']),
            models.Index(fields=['reject_lot', 'tray_id']),
        ]

    def __str__(self):
        lot_type = "Accept" if self.accept_lot else "Reject"
        lot_id = self.accept_lot.new_lot_id if self.accept_lot else self.reject_lot.new_lot_id
        return f"AllocationTray: {self.tray_id} → {lot_id} ({lot_type}, qty={self.qty})"
    
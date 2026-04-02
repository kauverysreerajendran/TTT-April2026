from django.db import models
from django.utils import timezone
from django.db.models import F
from django.core.exceptions import ValidationError
import datetime
from datetime import timedelta
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.db.models import JSONField
from django.contrib.postgres.fields import ArrayField
import uuid

#jig qr model
class Jig(models.Model):
    jig_qr_id = models.CharField(max_length=100, unique=True, help_text="Unique Jig QR ID")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_loaded = models.BooleanField(default=False, help_text="Is this Jig currently loaded?")
    current_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="User currently using this jig")
    locked_at = models.DateTimeField(null=True, blank=True, help_text="When the jig was locked for draft")
    drafted = models.BooleanField(default=False, help_text="Is this Jig currently drafted?")
    batch_id = models.CharField(max_length=100, null=True, blank=True, help_text="Batch ID for which Jig is locked")  
    lot_id = models.CharField(max_length=100, null=True, blank=True, help_text="Lot ID for which Jig is locked")

    def __str__(self):
        return self.jig_qr_id
    
    
    def clear_user_lock(self):
        """Clear user lock when jig is unloaded or draft is cleared"""
        self.current_user = None
        self.locked_at = None
        self.save()
    
    def is_locked_by_other_user(self, user):
        """Check if jig is locked by a different user"""
        return (self.current_user is not None and 
                self.current_user != user and 
                self.has_active_draft())
    
    def has_active_draft(self):
        """Check if jig has active draft that hasn't been unloaded"""
        return JigLoadingManualDraft.objects.filter(
            jig_id=self.jig_qr_id,
            draft_status='active'
        ).exists()

# Create your models here.
class JigLoadTrayId(models.Model):
    """
    BrassTrayId Model
    Represents a tray identifier in the Titan Track and Traceability system.
    """
    lot_id = models.CharField(max_length=50, null=True, blank=True, db_index=True, help_text="Lot ID")
    tray_id = models.CharField(max_length=100,  help_text="Tray ID")
    tray_quantity = models.IntegerField(null=True, blank=True, help_text="Quantity in the tray")
    batch_id = models.ForeignKey('modelmasterapp.ModelMasterCreation', on_delete=models.CASCADE, blank=True, null=True)
    recovery_batch_id = models.ForeignKey('Recovery_DP.RecoveryMasterCreation', on_delete=models.CASCADE, blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True)
    top_tray = models.BooleanField(default=False)


    delink_tray = models.BooleanField(default=False, help_text="Is tray delinked")
    delink_tray_qty = models.CharField(max_length=50, null=True, blank=True, help_text="Delinked quantity")
    
    # Broken hooks segregation fields
    broken_hooks_effective_tray = models.BooleanField(default=False, help_text="Is tray part of effective quantity after broken hooks")
    broken_hooks_excluded_qty = models.IntegerField(default=0, help_text="Quantity excluded due to broken hooks")
    effective_tray_qty = models.IntegerField(null=True, blank=True, help_text="Effective quantity for this tray after broken hooks calculation")
    
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
        Check if tray is available for scanning.
        Available if: not yet delinked (new tray) OR already delinked (can be reused).
        """
        return self.new_tray or self.delink_tray

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
        verbose_name = "Jig Load Tray ID"
        verbose_name_plural = "Jig Load Tray IDs"
        
#jig Loading master
class JigLoadingMaster(models.Model):
    model_stock_no = models.ForeignKey('modelmasterapp.ModelMaster', on_delete=models.CASCADE, help_text="Model Stock Number")
    jig_type = models.CharField(max_length=100, help_text="Jig Type")
    jig_capacity = models.IntegerField(help_text="Jig Capacity")
    forging_info = models.CharField(max_length=100, help_text="Forging Info")
    
    def __str__(self):
        return f"{self.model_stock_no} - {self.jig_type} - {self.jig_capacity}"

class BathNumbers(models.Model):
    BATH_TYPE_CHOICES = [
        ('Bright', 'Bright'),
        ('Semi Bright', 'Semi Bright'),
        ('Dull', 'Dull'),
    ]
    
    bath_number = models.CharField(max_length=100)
    bath_type = models.CharField(
        max_length=20, 
        choices=BATH_TYPE_CHOICES,
        help_text="Type of bath this number belongs to"
    )
    is_active = models.BooleanField(default=True, help_text="Is this bath number active")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['bath_number', 'bath_type']
        verbose_name = "Bath Number"
        verbose_name_plural = "Bath Numbers"
    
    def __str__(self):
        return f"{self.bath_number} ({self.bath_type})"

#  Auto Save Table
class JigAutoSave(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    lot_id = models.CharField(max_length=100, db_index=True)
    batch_id = models.CharField(max_length=100, db_index=True)
    session_key = models.CharField(max_length=40, blank=True)
    auto_save_data = models.JSONField(default=dict, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'batch_id', 'lot_id']
        indexes = [models.Index(fields=['user', 'batch_id', 'lot_id', 'updated_at'])]

    def __str__(self):
        return f"AutoSave: {self.user.username} - {self.batch_id} - {self.lot_id}"
                    
# Manual draft model to save all input fields       
class JigLoadingManualDraft(models.Model):
    batch_id = models.CharField(max_length=100, db_index=True)
    lot_id = models.CharField(max_length=100, db_index=True)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    draft_data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    jig_cases_remaining_count = models.IntegerField(default=0, blank=True, null=True)
    updated_lot_qty = models.IntegerField(default=0, blank=True, null=True)
    original_lot_qty = models.IntegerField(default=0, blank=True, null=True)
    jig_id = models.CharField(max_length=100, blank=True, null=True)
    delink_tray_info = models.JSONField(default=list, blank=True, null=True)
    delink_tray_qty = models.IntegerField(default=0, blank=True, null=True)
    delink_tray_count = models.IntegerField(default=0, blank=True, null=True)
    half_filled_tray_info = models.JSONField(default=list, blank=True, null=True)
    half_filled_tray_qty = models.IntegerField(default=0, blank=True, null=True)
    jig_capacity = models.IntegerField(default=0, blank=True, null=True)
    broken_hooks = models.IntegerField(default=0, blank=True, null=True)
    loaded_cases_qty = models.IntegerField(default=0, blank=True, null=True)
    plating_stock_num = models.CharField(max_length=100, blank=True, null=True)
    draft_status = models.CharField(max_length=20, choices=[('active', 'Active'), ('submitted', 'Submitted')], default='active')
    is_multi_model = models.BooleanField(default=False)
    effective_capacity = models.IntegerField(default=0, blank=True, null=True)
    tray_capacity = models.IntegerField(default=12, blank=True, null=True)
    nickel_bath_type = models.CharField(max_length=100, blank=True, null=True)
    tray_type = models.CharField(max_length=100, blank=True, null=True)
    multi_model_allocation = models.JSONField(default=list, blank=True, null=True, help_text="Full multi-model allocation data")
    scanned_trays = models.JSONField(default=list, blank=True, null=True, help_text="List of scanned tray IDs with qty")
    empty_hooks = models.IntegerField(default=0, blank=True, null=True)
    excess_qty = models.IntegerField(default=0, blank=True, null=True)

    class Meta:
        unique_together = ['batch_id', 'lot_id', 'user']  # <-- FIXED!

    def __str__(self):
        return f"Draft: {self.batch_id} by {self.user.username}"
                    
# Jig Completed model - duplicate of JigLoadingManualDraft
class JigCompleted(models.Model):
    batch_id = models.CharField(max_length=100, db_index=True)
    lot_id = models.CharField(max_length=100, db_index=True)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    draft_data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    jig_cases_remaining_count = models.IntegerField(default=0, blank=True, null=True)
    updated_lot_qty = models.IntegerField(default=0, blank=True, null=True)
    original_lot_qty = models.IntegerField(default=0, blank=True, null=True)
    jig_id = models.CharField(max_length=100, blank=True, null=True)
    delink_tray_info = models.JSONField(default=list, blank=True, null=True)
    delink_tray_qty = models.IntegerField(default=0, blank=True, null=True)
    delink_tray_count = models.IntegerField(default=0, blank=True, null=True)
    half_filled_tray_info = models.JSONField(default=list, blank=True, null=True)
    half_filled_tray_qty = models.IntegerField(default=0, blank=True, null=True)
    jig_capacity = models.IntegerField(default=0, blank=True, null=True)
    broken_hooks = models.IntegerField(default=0, blank=True, null=True)
    loaded_cases_qty = models.IntegerField(default=0, blank=True, null=True)
    plating_stock_num = models.CharField(max_length=100, blank=True, null=True)
    draft_status = models.CharField(max_length=20, choices=[('active', 'Active'), ('submitted', 'Submitted')], default='active')
    hold_status = models.CharField(max_length=20, default='normal', blank=True, null=True)
    is_multi_model = models.BooleanField(default=False)
    jig_position = models.CharField(max_length=100, blank=True, null=True)
    IP_loaded_date_time = models.DateTimeField(blank=True, null=True)
    last_process_module = models.CharField(max_length=100, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    pick_remarks = models.TextField(blank=True, null=True)
    bath_numbers = models.ForeignKey('BathNumbers', on_delete=models.SET_NULL, blank=True, null=True)
    no_of_model_cases = models.TextField(blank=True, null=True)
    partial_lot_id = models.CharField(max_length=100, blank=True, null=True, help_text="New lot ID for remaining cases in partial submission")
    effective_capacity = models.IntegerField(default=0, blank=True, null=True)
    tray_capacity = models.IntegerField(default=12, blank=True, null=True)
    nickel_bath_type = models.CharField(max_length=100, blank=True, null=True)
    tray_type = models.CharField(max_length=100, blank=True, null=True)
    multi_model_allocation = models.JSONField(default=list, blank=True, null=True, help_text="Full multi-model allocation data")
    scanned_trays = models.JSONField(default=list, blank=True, null=True, help_text="List of scanned tray IDs with qty")
    empty_hooks = models.IntegerField(default=0, blank=True, null=True)
    excess_qty = models.IntegerField(default=0, blank=True, null=True)

    class Meta:
        unique_together = ['batch_id', 'lot_id', 'user']
        verbose_name = "Jig Completed"
        verbose_name_plural = "Jig Completed"

    def __str__(self):
        return f"Jig Completed: {self.batch_id} by {self.user.username}"


# =============================================================================
# NEW TABLES: Full snapshot storage (Draft + Submit), Delink, Excess Lot
# =============================================================================

class JigLoadingRecord(models.Model):
    """
    Single table for Draft AND Submit. status_flag differentiates.
    Stores the FULL UI snapshot exactly as displayed — no recomputation on save.
    """
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
    ]

    jig_id = models.CharField(max_length=100, blank=True, null=True, db_index=True, help_text="Jig QR ID (e.g. J098-0001)")
    lot_id = models.CharField(max_length=100, db_index=True, help_text="Primary lot ID")
    batch_id = models.CharField(max_length=100, db_index=True, help_text="Primary batch ID")
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # Scalar snapshot fields (exactly as displayed on UI)
    lot_qty = models.IntegerField(default=0, help_text="Lot Qty shown on UI")
    jig_capacity = models.IntegerField(default=0, help_text="Jig Capacity shown on UI")
    effective_capacity = models.IntegerField(default=0, help_text="Jig Capacity - Broken Hooks")
    broken_hooks = models.IntegerField(default=0, help_text="Broken/Buildup hooks count")
    loaded_cases_qty = models.IntegerField(default=0, help_text="Loaded Cases Qty shown on UI")
    empty_hooks = models.IntegerField(default=0, help_text="Empty Hooks shown on UI")
    nickel_bath_type = models.CharField(max_length=100, blank=True, null=True)
    tray_type = models.CharField(max_length=100, blank=True, null=True)
    tray_capacity = models.IntegerField(default=12, blank=True, null=True)
    plating_stock_num = models.CharField(max_length=100, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    is_multi_model = models.BooleanField(default=False)

    # FULL SNAPSHOT — JSON of entire tray list as displayed
    # Each entry: {tray_id, original_qty, delink_qty, excess_qty, top_tray, model_code, ...}
    tray_data = models.JSONField(default=list, help_text="Full tray snapshot: [{tray_id, original_qty, delink_qty, excess_qty, ...}]")

    # Aggregated totals (stored, NOT recomputed)
    total_delink_qty = models.IntegerField(default=0, help_text="Sum of delink_qty across all trays")
    total_excess_qty = models.IntegerField(default=0, help_text="Sum of excess_qty across all trays")

    # Scanned trays (what user actually scanned — panel + tray_id + qty)
    scanned_trays = models.JSONField(default=list, blank=True, null=True, help_text="[{tray_id, qty, panel, lot_id, batch_id}]")

    # Multi-model allocation snapshot
    multi_model_allocation = models.JSONField(default=list, blank=True, null=True, help_text="Full multi-model allocation data")

    # Half-filled / excess tray info
    half_filled_tray_info = models.JSONField(default=list, blank=True, null=True)

    # Status
    status_flag = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['lot_id', 'batch_id', 'user']
        verbose_name = "Jig Loading Record"
        verbose_name_plural = "Jig Loading Records"
        indexes = [
            models.Index(fields=['lot_id', 'batch_id', 'status_flag']),
            models.Index(fields=['jig_id', 'status_flag']),
        ]

    def __str__(self):
        return f"JigLoadingRecord({self.status_flag}): {self.jig_id or 'NO_JIG'} - {self.lot_id}"


class JigDelinkRecord(models.Model):
    """
    Delink storage — one row per tray with delink_qty > 0.
    Created ONLY on Submit, never on Draft.
    """
    jig_loading_record = models.ForeignKey(JigLoadingRecord, on_delete=models.CASCADE, related_name='delink_records')
    jig_id = models.CharField(max_length=100, db_index=True, help_text="Jig QR ID")
    lot_id = models.CharField(max_length=100, db_index=True, help_text="Parent lot ID")
    batch_id = models.CharField(max_length=100, db_index=True)
    tray_id = models.CharField(max_length=100, db_index=True, help_text="Physical tray ID")
    delink_qty = models.IntegerField(help_text="Quantity delinked from this tray for the jig")
    original_qty = models.IntegerField(default=0, help_text="Original tray quantity before split")
    model_code = models.CharField(max_length=100, blank=True, null=True, help_text="Model plating stock no")
    scanned_tray_id = models.CharField(max_length=100, blank=True, null=True, help_text="Actual scanned tray ID (may differ from tray_id)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Jig Delink Record"
        verbose_name_plural = "Jig Delink Records"
        indexes = [
            models.Index(fields=['jig_id', 'lot_id']),
            models.Index(fields=['tray_id']),
        ]

    def __str__(self):
        return f"Delink: {self.tray_id} → {self.delink_qty} (Jig: {self.jig_id})"


class ExcessLotRecord(models.Model):
    """
    Excess lot created on Submit — represents the overflow quantity
    that did not fit into the jig's effective capacity.
    """
    jig_loading_record = models.ForeignKey(JigLoadingRecord, on_delete=models.CASCADE, related_name='excess_lot_records')
    new_lot_id = models.CharField(max_length=100, unique=True, db_index=True, help_text="Generated lot ID for excess")
    parent_lot_id = models.CharField(max_length=100, db_index=True, help_text="Original lot ID")
    parent_batch_id = models.CharField(max_length=100, db_index=True)
    lot_qty = models.IntegerField(help_text="Total excess qty = sum of excess_qty across all trays")
    jig_id = models.CharField(max_length=100, help_text="Jig from which excess originated")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Excess Lot Record"
        verbose_name_plural = "Excess Lot Records"
        indexes = [
            models.Index(fields=['parent_lot_id']),
            models.Index(fields=['new_lot_id']),
        ]

    def __str__(self):
        return f"ExcessLot: {self.new_lot_id} (from {self.parent_lot_id}, qty={self.lot_qty})"


class ExcessLotTray(models.Model):
    """
    Individual tray records for the excess lot.
    One row per tray where excess_qty > 0.
    """
    excess_lot = models.ForeignKey(ExcessLotRecord, on_delete=models.CASCADE, related_name='excess_trays')
    lot_id = models.CharField(max_length=100, db_index=True, help_text="New excess lot ID")
    tray_id = models.CharField(max_length=100, help_text="Physical tray ID")
    qty = models.IntegerField(help_text="Excess quantity in this tray")
    original_qty = models.IntegerField(default=0, help_text="Original tray quantity before split")
    model_code = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Excess Lot Tray"
        verbose_name_plural = "Excess Lot Trays"

    def __str__(self):
        return f"ExcessTray: {self.tray_id} qty={self.qty} (lot={self.lot_id})"
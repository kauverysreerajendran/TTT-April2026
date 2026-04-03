from django.db import models
from django.utils import timezone
from datetime import timedelta
from modelmasterapp.models import *

# Create your models here.

class JigUnload_TrayId(models.Model):
    tray_id = models.CharField(max_length=100, help_text="Tray ID")
    tray_qty = models.IntegerField(help_text="Quantity in the tray")
    lot_id = models.CharField(max_length=100, help_text="Lot ID")
    draft_save=models.BooleanField(default=False)
    top_tray = models.BooleanField(default=False)
    delink_tray = models.BooleanField(default=False, help_text="Is tray delinked")
    rejected_tray=models.BooleanField(default=False, help_text="Is tray rejected")
    
    def __str__(self):
        return f"{self.tray_id} - {self.tray_qty} - {self.lot_id}"
    


class JigUnloadAfterTable(models.Model):
    jig_qr_id = models.CharField(max_length=100, help_text="Jig QR ID") 
    combine_lot_ids = ArrayField(
        models.CharField(max_length=1000),
        blank=True,
        default=list,
        help_text="List of combined lot IDs"
    )
    lot_id = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        help_text="Auto-generated unique lot ID"
    )
    # ✅ NEW: Additional auto-generated lot ID with different format
    unload_lot_id = models.CharField(
        max_length=50,
        unique=True,
        editable=False,
        null=True,
        blank=True,
        help_text="Auto-generated unload lot ID (format: JUL{YYYYMMDD}{sequence})"
    )
    total_case_qty = models.IntegerField(help_text="Total case quantity")
    unload_missing_qty = models.IntegerField(default=0, help_text="Missing quantity in Jig Unloading")

    # ✅ NEW FIELDS - Auto-populated from combine_lot_ids
    version = models.ForeignKey(
        Version, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="Version (auto-populated from combined lots)"
    )
    location = models.ManyToManyField(
        Location, 
        blank=True, 
        help_text="Locations (auto-populated from combined lots)"
    )
    plating_color = models.ForeignKey(
        Plating_Color, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="Plating Color (auto-populated from combined lots)"
    )
    plating_stk_no = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Plating Stock Number (auto-populated from combined lots)"
    )
    polish_stk_no = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Polish Stock Number (auto-populated from combined lots)"
    )
    polish_finish = models.ForeignKey(
        PolishFinishType, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="Polish Finish (auto-populated from combined lots)"
    )
    plating_stk_no_list = models.JSONField(default=list, blank=True, null=True)
    polish_stk_no_list = models.JSONField(default=list, blank=True, null=True) 
    version_list = models.JSONField(default=list, blank=True, null=True)

    category = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Category (auto-populated from combined lots)"
    )
    tray_type = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        help_text="Tray Type (auto-populated from combined lots)"
    )
    tray_capacity = models.IntegerField(
        null=True, 
        blank=True, 
        help_text="Tray Capacity (auto-populated from combined lots)"
    )

    def save(self, *args, **kwargs):
        # Generate lot_id if not exists
        if not self.lot_id:
            now = timezone.now()
            date_str = now.strftime("%Y%m%d%H%M%S")
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = JigUnloadAfterTable.objects.filter(
                created_at__gte=today_start
            ).count() + 1
            self.lot_id = f"UNLOT{date_str}{today_count:03d}"

        # ✅ Generate unload_lot_id if not exists
        if not self.unload_lot_id:
            now = timezone.now()
            date_str = now.strftime("%Y%m%d")
            # Count records created today for sequence
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = JigUnloadAfterTable.objects.filter(
                created_at__gte=today_start
            ).count() + 1
            self.unload_lot_id = f"JUL{date_str}{today_count:04d}"

        # ✅ AUTO-POPULATE FIELDS from combine_lot_ids
        if self.combine_lot_ids and not self.pk:  # Only on creation
            self._populate_fields_from_combined_lots()

        # Save the instance first (required for ManyToManyField)
        super().save(*args, **kwargs)
        
        # Handle ManyToManyField for locations after saving
        if self.combine_lot_ids and hasattr(self, '_locations_to_set'):
            self.location.set(self._locations_to_set)

    def _populate_fields_from_combined_lots(self):
        """
        Populate fields automatically following this path:
        combine_lot_ids → TotalStockModel → batch_id → ModelMasterCreation → extract fields
        """
        if not self.combine_lot_ids:
            return

        # Get the first lot_id to extract data from
        first_lot_id = self.combine_lot_ids[0]
        
        try:
            # Step 1: Find TotalStockModel record using combine_lot_ids
            total_stock = TotalStockModel.objects.filter(lot_id=first_lot_id).first()
            
            if not total_stock:
                print(f"No TotalStockModel found for lot_id: {first_lot_id}")
                return
                
            # Step 2: Get batch_id from TotalStockModel
            if not total_stock.batch_id:
                print(f"No batch_id found in TotalStockModel for lot_id: {first_lot_id}")
                return
                
            batch_id = total_stock.batch_id
            
            # Step 3: Find ModelMasterCreation using batch_id
            model_master_creation = ModelMasterCreation.objects.select_related(
                'version', 'location', 'model_stock_no__polish_finish', 'model_stock_no__tray_type'
            ).filter(id=batch_id.id).first()
            
            if not model_master_creation:
                print(f"No ModelMasterCreation found for batch_id: {batch_id}")
                return
            
            # Step 4: Extract and populate fields from ModelMasterCreation
            # Version
            self.version = model_master_creation.version
            
            # Location (will be set after save due to ManyToManyField)
            if model_master_creation.location:
                self._locations_to_set = [model_master_creation.location]
            else:
                self._locations_to_set = []
            
            # Plating Color - Try TotalStockModel first, fallback to ModelMasterCreation
            plating_color_assigned = False
            
            # Option 1: Try TotalStockModel.plating_color (ForeignKey)
            if total_stock.plating_color:
                self.plating_color = total_stock.plating_color
                plating_color_assigned = True
                print(f"✅ Auto-populated plating_color from TotalStock: {total_stock.plating_color} (ID: {total_stock.plating_color.id})")
            
            # Option 2: Fallback to ModelMasterCreation.plating_color (string field)
            elif model_master_creation.plating_color:
                try:
                    plating_color_obj = Plating_Color.objects.filter(
                        plating_color=model_master_creation.plating_color
                    ).first()
                    if plating_color_obj:
                        self.plating_color = plating_color_obj
                        plating_color_assigned = True
                        print(f"✅ Auto-populated plating_color from ModelMasterCreation: {plating_color_obj} (ID: {plating_color_obj.id})")
                    else:
                        print(f"⚠️ No Plating_Color found for string: '{model_master_creation.plating_color}'")
                except Exception as e:
                    print(f"❌ Error looking up plating_color '{model_master_creation.plating_color}': {e}")
            
            if not plating_color_assigned:
                print(f"⚠️ No plating_color assigned from either TotalStock or ModelMasterCreation for batch_id: {batch_id}")
                self.plating_color = None
                print(f"⚠️ No plating_color string in ModelMasterCreation for batch_id: {batch_id}")
                self.plating_color = None
            
            # Stock Numbers
            self.plating_stk_no = model_master_creation.plating_stk_no
            self.polish_stk_no = model_master_creation.polishing_stk_no
            
            # Polish Finish - get from ModelMaster through relationship
            if model_master_creation.model_stock_no and model_master_creation.model_stock_no.polish_finish:
                self.polish_finish = model_master_creation.model_stock_no.polish_finish
            else:
                # Fallback: try to get from polish_finish string field
                if model_master_creation.polish_finish:
                    try:
                        polish_finish_obj = PolishFinishType.objects.filter(
                            polish_finish=model_master_creation.polish_finish
                        ).first()
                        self.polish_finish = polish_finish_obj
                    except:
                        self.polish_finish = None
            
            # Category
            self.category = model_master_creation.category
            
            # Tray Type and Capacity
            if model_master_creation.model_stock_no and model_master_creation.model_stock_no.tray_type:
                self.tray_type = model_master_creation.model_stock_no.tray_type.tray_type
                self.tray_capacity = model_master_creation.model_stock_no.tray_capacity
            else:
                # Fallback: use string fields from ModelMasterCreation
                self.tray_type = model_master_creation.tray_type
                self.tray_capacity = model_master_creation.tray_capacity
            
            print(f"✅ Auto-populated fields for JigUnloadAfterTable from batch_id: {batch_id}")
            
            # Optional: Validate consistency across all combined lots
            self._validate_consistency_across_lots()
                
        except Exception as e:
            # Log error but don't prevent saving
            print(f"❌ Error auto-populating fields for JigUnloadAfterTable: {e}")
            import traceback
            traceback.print_exc()

    def _validate_consistency_across_lots(self):
        """
        Check if all combined lots have consistent values by following:
        combine_lot_ids → TotalStockModel → batch_id → ModelMasterCreation
        """
        if len(self.combine_lot_ids) <= 1:
            return
            
        try:
            # Get all TotalStockModel records for combined lot_ids
            total_stocks = TotalStockModel.objects.filter(
                lot_id__in=self.combine_lot_ids
            ).select_related('batch_id')
            
            # Extract batch_ids
            batch_ids = [ts.batch_id.id for ts in total_stocks if ts.batch_id]
            
            if not batch_ids:
                print(f"Warning: No batch_ids found for combined lots {self.combine_lot_ids}")
                return
            
            # Get ModelMasterCreation records
            model_creations = ModelMasterCreation.objects.filter(
                id__in=batch_ids
            ).select_related('version', 'location', 'model_stock_no__polish_finish')
            
            # Check for inconsistencies
            versions = set(mc.version.id for mc in model_creations if mc.version)
            categories = set(mc.category for mc in model_creations if mc.category)
            plating_colors = set(mc.plating_color for mc in model_creations if mc.plating_color)
            polish_finishes = set(mc.polish_finish for mc in model_creations if mc.polish_finish)
            
            # Log warnings for inconsistencies
            if len(versions) > 1:
                print(f"⚠️ Warning: Multiple versions found in combined lots {self.combine_lot_ids}")
            if len(categories) > 1:
                print(f"⚠️ Warning: Multiple categories found in combined lots {self.combine_lot_ids}")
            if len(plating_colors) > 1:
                print(f"⚠️ Warning: Multiple plating colors found in combined lots {self.combine_lot_ids}")
            if len(polish_finishes) > 1:
                print(f"⚠️ Warning: Multiple polish finishes found in combined lots {self.combine_lot_ids}")
                
        except Exception as e:
            print(f"❌ Error validating consistency: {e}")

    # Add a created_at field to support daily sequence
    created_at = models.DateTimeField(default=timezone.now)
    selected_user = models.ForeignKey(User, on_delete=models.CASCADE, help_text="User who created the lot", null=True, blank=True)
    unload_accepted = models.BooleanField(default=False, help_text="Indicates if the unload was accepted")
    accepted_qty = models.IntegerField(default=0, help_text="Accepted quantity during unload")
    
    unload_audit_accepted = models.BooleanField(default=False, help_text="Indicates if the unload was accepted")
    audit_accepted_qty = models.IntegerField(default=0, help_text="Accepted quantity during unload")
    
    last_process_module = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Last Process Module"
    )
    next_process_module = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Next Process Module"
    )
    
    rejected_nickle_ip_stock = models.BooleanField(default=False, help_text="Rejected Nickle IP Stock")
    nq_qc_accepted_qty = models.IntegerField(default=0, help_text="Nq QC Accepted Quantity")  # New field

    rejected_audit_nickle_ip_stock = models.BooleanField(default=False, help_text="Rejected Nickle Audit Stock")
    audit_check = models.BooleanField(default=False, help_text="Audit Check")
    nq_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for holding the batch")  
    nq_release_reason= models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for releasing the batch")
    nq_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n Brass")
    nq_release_lot =models.BooleanField(default=False)
    nq_pick_remarks= models.CharField(max_length=100, null=True, blank=True, help_text="JIG Pick Remarks")  # New field
    nq_missing_qty = models.IntegerField(default=0, help_text="Missing quantity in IQF")
    nq_physical_qty = models.IntegerField(help_text="Original physical quantity in IQF", default=0)  # New field
    nq_qc_accptance=models.BooleanField(default=False)
    nq_qc_few_cases_accptance=models.BooleanField(default=False)
    nq_qc_rejection=models.BooleanField(default=False)
    nq_rejection_tray_scan_status=models.BooleanField(default=False)
    nq_accepted_tray_scan_status=models.BooleanField(default=False)
    nq_onhold_picking=models.BooleanField(default=False, help_text="Nickle QC On Hold Picking")
    nq_draft=models.BooleanField(default=False, help_text="Nickle QC Draft Save")
    nq_qc_accepted_qty_verified= models.BooleanField(default=False, help_text="Nickle QC Accepted Quantity Verified")  # New field
    nq_last_process_date_time = models.DateTimeField(null=True, blank=True, help_text="Last Process Date Time")
    na_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for holding the batch")  
    na_release_reason= models.CharField(max_length=255, null=True, blank=True, help_text="Brass Reason for releasing the batch")
    na_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n Brass")
    na_release_lot =models.BooleanField(default=False)
    na_pick_remarks= models.CharField(max_length=100, null=True, blank=True, help_text="JIG Pick Remarks")  # New field
    na_missing_qty = models.IntegerField(default=0, help_text="Missing quantity in IQF")
    na_physical_qty = models.IntegerField(help_text="Original physical quantity in IQF", default=0)  # New field
    na_qc_accptance=models.BooleanField(default=False)
    na_qc_few_cases_accptance=models.BooleanField(default=False)
    na_qc_rejection=models.BooleanField(default=False)
    na_rejection_tray_scan_status=models.BooleanField(default=False)
    na_accepted_tray_scan_status=models.BooleanField(default=False)
    na_onhold_picking=models.BooleanField(default=False, help_text="Nickle QC On Hold Picking")
    na_draft=models.BooleanField(default=False, help_text="Nickle QC Draft Save")
    na_ac_accepted_qty_verified= models.BooleanField(default=False, help_text="Nickle QC Accepted Quantity Verified")  # New field
    na_last_process_date_time = models.DateTimeField(null=True, blank=True, help_text="Last Process Date Time")
    na_qc_accepted_qty = models.IntegerField(default=0, help_text="NA QC Accepted Quantity")  # New field

    spider_holding_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Spider Reason for holding the batch")
    spider_release_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Spider Reason for releasing the batch")
    spider_hold_lot = models.BooleanField(default=False, help_text="Indicates if the lot is on hold n Spider")
    spider_release_lot = models.BooleanField(default=False)
    spider_pick_remarks= models.CharField(max_length=100, null=True, blank=True, help_text="Spider Pick Remarks")  # New field

    # Spider Spindle Z1 fields
    ss_z1_completed = models.BooleanField(default=False, help_text="Spider Spindle Z1 completed")
    ss_z1_tray_id = models.CharField(max_length=100, null=True, blank=True, help_text="Spider Spindle Z1 Tray ID")
    ss_z1_completed_at = models.DateTimeField(null=True, blank=True, help_text="Spider Spindle Z1 completion time")
    ss_z1_completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ss_z1_completed_lots')

    # Spider Spindle Z2 fields
    ss_z2_completed = models.BooleanField(default=False, help_text="Spider Spindle Z2 completed")
    ss_z2_tray_id = models.CharField(max_length=100, null=True, blank=True, help_text="Spider Spindle Z2 Tray ID")
    ss_z2_completed_at = models.DateTimeField(null=True, blank=True, help_text="Spider Spindle Z2 completion time")
    ss_z2_completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ss_z2_completed_lots')

    send_to_nickel_brass = models.BooleanField(default=False, help_text="Send to Nickel Brass")
    missing_qty = models.IntegerField(default=0)  # ✅ NEW: Add missing_qty field
    Un_loaded_date_time = models.DateTimeField(null=True, blank=True, help_text="Un Loaded Date Time")

    jig_physical_qty = models.IntegerField(help_text="Original physical quantity in IQF", default=0)  # New field
    
    def __str__(self):
        return f"{self.lot_id} | {self.unload_lot_id} - {self.total_case_qty}"

    class Meta:
        verbose_name = "Jig Unload After Table"
        verbose_name_plural = "Jig Unload After Tables" 
        
# Add this to your Jig_Unloading/models.py

class JigUnloadDraft(models.Model):
    draft_id = models.AutoField(primary_key=True)
    main_lot_id = models.CharField(max_length=50)
    model_number = models.CharField(max_length=100)
    total_quantity = models.IntegerField()
    draft_data = models.JSONField()  # Stores all tray data as JSON
    combined_lot_ids = models.JSONField(default=list, blank=True)
    created_by = models.CharField(max_length=100, default='System')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'jig_unload_draft'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Draft-{self.draft_id}: {self.model_number} ({self.total_quantity})"


class JigUnloadAutoSave(models.Model):
    """Auto-save for jig unloading modal inputs"""
    # Allow NULL user so anonymous (session_key) autosaves are supported
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    session_key = models.CharField(max_length=40, blank=True, null=True)  # For anonymous users
    
    # Primary identifiers
    main_lot_id = models.CharField(max_length=100, db_index=True)
    model_number = models.CharField(max_length=100, blank=True)
    
    # Auto-save data fields (matching the manual draft structure)
    total_quantity = models.IntegerField(default=0)
    tray_data = models.JSONField(default=list)  # Stores tray entries
    combined_lot_ids = models.JSONField(default=list)
    tray_type_capacity = models.CharField(max_length=50, default='Normal - 16')
    
    # Additional modal state
    missing_qty = models.IntegerField(default=0)
    jig_id = models.CharField(max_length=100, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'jig_unload_autosave'
        # Enforce uniqueness per user/session and lot_id
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'main_lot_id'],
                condition=models.Q(user__isnull=False),
                name='unique_user_unload_autosave'
            ),
            models.UniqueConstraint(
                fields=['session_key', 'main_lot_id'],
                condition=models.Q(session_key__isnull=False),
                name='unique_session_unload_autosave'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'main_lot_id', 'updated_at']),
            models.Index(fields=['session_key', 'main_lot_id', 'updated_at']),
        ]
    
    def is_expired(self, hours=24):
        return timezone.now() - self.updated_at > timedelta(hours=hours)
    
    def __str__(self):
        user_part = self.user.username if self.user else f"Session:{(self.session_key or '')[:8]}"
        return f"AutoSave({user_part}, {self.main_lot_id}, Model:{self.model_number}, Qty:{self.total_quantity})"
    
    def to_dict(self):
        return {
            'main_lot_id': self.main_lot_id,
            'model_number': self.model_number,
            'total_quantity': self.total_quantity,
            'tray_data': self.tray_data,
            'combined_lot_ids': self.combined_lot_ids,
            'tray_type_capacity': self.tray_type_capacity,
            'missing_qty': self.missing_qty,
            'jig_id': self.jig_id,
        }
    
    def has_meaningful_data(self):
        """Check if this autosave contains meaningful data beyond defaults"""
        return bool(
            self.tray_data or 
            self.total_quantity > 0 or 
            self.combined_lot_ids or
            self.model_number.strip()
        )


class JUSubmittedZ1(models.Model):
    """
    Snapshot storage for submitted Jig Unloading Zone 1 data.
    Stores per-model tray scan results after unloading is complete.
    """
    jig_completed_id = models.IntegerField(db_index=True, help_text="ID of JigCompleted record")
    jig_qr_id = models.CharField(max_length=100, help_text="Jig QR ID")
    model_no = models.CharField(max_length=100, db_index=True, help_text="Plating Stock Number / Model Number")
    lot_id = models.CharField(max_length=100, db_index=True, help_text="Lot ID for this model")
    total_qty = models.IntegerField(help_text="Total quantity for this model")
    tray_type = models.CharField(max_length=50, null=True, blank=True)
    tray_capacity = models.IntegerField(null=True, blank=True)
    tray_code = models.CharField(max_length=10, null=True, blank=True, help_text="Tray code e.g. NR, JB")
    tray_color = models.CharField(max_length=50, null=True, blank=True, help_text="Tray color e.g. Red, Blue")
    num_trays = models.IntegerField(default=0)
    tray_data = models.JSONField(default=list, help_text="List of {tray_id, tray_qty, is_top_tray, top_tray_remark}")
    missing_qty = models.IntegerField(default=0)
    top_tray_remark = models.TextField(null=True, blank=True)
    is_draft = models.BooleanField(default=False, help_text="True if this is a draft save, False if final save")
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ju_submitted_z1'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['jig_completed_id', 'model_no']),
            models.Index(fields=['lot_id']),
        ]

    def __str__(self):
        return f"JU-Z1: {self.jig_qr_id} | {self.model_no} ({self.total_qty})"



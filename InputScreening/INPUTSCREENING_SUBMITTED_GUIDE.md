# InputScreening_Submitted Model & Service Documentation

## Overview

The `InputScreening_Submitted` model is the **permanent source of truth** for all Input Screening submissions. It stores complete immutable snapshots of accepted, rejected, and partial split decisions exactly as submitted by operators.

**Key Purpose:**
- Eliminate data drift between Input Screening live state and downstream modules
- Enable complete audit trail with revocation capabilities
- Support split lot tracking (partial accept/reject creates independent child lots)
- Future modules use submitted snapshot data, never pull live values again

---

## Database Schema

### Core Tables & Relationships

```
InputScreening_Submitted
├── lot_id (UNIQUE, INDEX) ─────> Unique identifier for this submission
├── parent_lot_id (INDEX) ───────> Original lot if this is a split child
├── batch_id (INDEX) ────────────> Reference to ModelMasterCreation
├── module_name (default: "Input Screening")
│
├── [Product Info]
│   ├── plating_stock_no
│   ├── model_no
│   ├── tray_type (Jumbo/Normal)
│   └── tray_capacity
│
├── [Quantities]
│   ├── original_lot_qty ────> Qty before submission
│   ├── submitted_lot_qty ───> Qty submitted
│   ├── accepted_qty
│   └── rejected_qty
│
├── [Tray Allocation]
│   ├── active_trays_count
│   ├── accept_trays_count
│   ├── reject_trays_count
│   ├── top_tray_id
│   ├── top_tray_qty
│   └── has_top_tray (boolean)
│
├── [Submission Type Flags]
│   ├── is_full_accept
│   ├── is_full_reject
│   ├── is_partial_accept ──> Creates independent accept child lot
│   └── is_partial_reject ──> Creates independent reject child lot
│
├── [Lot Hierarchy]
│   ├── is_child_lot ───────> True if created from parent split
│   ├── is_active (INDEX) ──> Live/revoked marker
│   └── is_revoked ────────> Audit revocation marker
│
├── [Audit Trail]
│   ├── created_by (FK to User)
│   ├── created_at (INDEX)
│   ├── updated_at
│   └── remarks (operator comments)
│
└── [JSON Snapshots] ───────────> Immutable complete state
    ├── all_trays_json ───────────────> All trays used
    ├── accepted_trays_json ─────────> Trays for accept qty
    ├── rejected_trays_json ─────────> Trays for reject qty
    ├── rejection_reasons_json ─────> Reason breakdown
    ├── allocation_preview_json ────> Final allocations
    └── delink_trays_json ──────────> Available reusable trays
```

### Indexes for Production Scale

Comprehensive indexes optimized for:
- Fast lot lookup by `lot_id`, `parent_lot_id`, `batch_id`
- Quick filtering by `is_active`, `created_at`
- Split lot tracking queries
- Composite indexes for common access patterns

```sql
-- Fast lot lookup
iss_lot_id_idx (lot_id)
iss_parent_lot_id_idx (parent_lot_id)
iss_batch_id_idx (batch_id)

-- State queries
iss_is_active_idx (is_active)
iss_created_at_idx (created_at)

-- Combined queries
iss_lot_active_idx (lot_id, is_active)
iss_parent_child_idx (parent_lot_id, is_child_lot)
iss_batch_active_idx (batch_id, is_active)
iss_split_type_idx (is_partial_accept, is_partial_reject)
```

---

## Data Flow & Split Lot Management

### Full Accept Flow
```
Original Lot (LID001)
    └─> FULL ACCEPT SUBMITTED
        └─> InputScreening_Submitted Record Created
            ├── lot_id: LID001
            ├── is_full_accept: True
            ├── accepted_qty: 500
            ├── rejected_qty: 0
            ├── is_child_lot: False
            └── [All trays to accepted_trays_json]
```

**Result:** Single submission record, no split.

### Full Reject Flow
```
Original Lot (LID002)
    └─> FULL REJECT SUBMITTED (with reasons)
        └─> InputScreening_Submitted Record Created
            ├── lot_id: LID002
            ├── is_full_reject: True
            ├── accepted_qty: 0
            ├── rejected_qty: 500
            ├── rejection_reasons_json: {"R01": {...}, "R02": {...}}
            └── [All trays to rejected_trays_json]
```

**Result:** Single submission record with rejection reasons logged.

### Partial Accept + Partial Reject Flow (SPLIT)
```
Original Lot (LID003)
    └─> PARTIAL ACCEPT (250) + PARTIAL REJECT (250) SUBMITTED
        └─> ATOMIC TRANSACTION
            ├─> Create ACCEPT Child Lot
            │   ├── lot_id: LID<NEW_UUID1>  [Generated]
            │   ├── parent_lot_id: LID003
            │   ├── is_partial_accept: True
            │   ├── is_child_lot: True
            │   ├── accepted_qty: 250
            │   ├── submitted_lot_qty: 250
            │   └── [250 qty trays only]
            │
            ├─> Create REJECT Child Lot
            │   ├── lot_id: LID<NEW_UUID2>  [Generated]
            │   ├── parent_lot_id: LID003
            │   ├── is_partial_reject: True
            │   ├── is_child_lot: True
            │   ├── rejected_qty: 250
            │   ├── submitted_lot_qty: 250
            │   └── [250 qty trays only]
            │
            └─> Parent (LID003) Status:
                ├── is_active: False (or revoked)
                └── Child lots are now source of truth
```

**Key Guarantees:**
1. **Atomic:** Both children created or none (no half-saves)
2. **Independent:** Child lots have their own lot_ids, never reference parent again
3. **Source of Truth:** Future modules use `LID<NEW_UUID1>` and `LID<NEW_UUID2>`, ignore LID003
4. **Reversible:** Parent can be reactivated, children revoked if needed

---

## API & Service Layer

### Imports
```python
from InputScreening.services_submitted import (
    generate_lot_id,
    create_full_accept_submission,
    create_full_reject_submission,
    create_partial_split_submission,
    get_active_submission,
    get_all_child_lots,
    get_lot_for_next_module,
    get_lot_metadata_for_downstream,
    revoke_submission,
)
```

### Creating Submissions

#### Full Accept
```python
from InputScreening.services_submitted import create_full_accept_submission

record = create_full_accept_submission(
    original_lot_id="LID001",
    batch_id="BATCH123",
    original_qty=500,
    plating_stock_no="PS001",
    model_no="MODEL-A",
    tray_type="Normal",
    tray_capacity=20,
    active_trays_count=25,
    top_tray_id="NB-A00181",
    top_tray_qty=3,
    all_trays_json=[
        {"tray_id": "NB-A00181", "qty": 3, "top_tray": True},
        {"tray_id": "NB-A00182", "qty": 16},
        # ... more trays ...
    ],
    created_by=request.user,
    remarks="All accepted as per quality check",
)

# record.lot_id == "LID001"
# record.is_full_accept == True
```

#### Full Reject
```python
from InputScreening.services_submitted import create_full_reject_submission

record = create_full_reject_submission(
    original_lot_id="LID002",
    batch_id="BATCH124",
    original_qty=500,
    plating_stock_no="PS002",
    model_no="MODEL-B",
    tray_type="Jumbo",
    tray_capacity=30,
    active_trays_count=17,
    top_tray_id="JB-A00075",
    top_tray_qty=8,
    rejected_trays_json=[...],
    rejection_reasons_json={
        "R01": {"reason": "VERSION MIXUP", "qty": 300},
        "R02": {"reason": "MODEL MIXUP", "qty": 200},
    },
    allocation_preview_json={...},
    delink_trays_json=[...],
    created_by=request.user,
    remarks="Full rejection due to version mixup",
)

# record.lot_id == "LID002"
# record.is_full_reject == True
# record.rejection_reasons_json contains reason breakdown
```

#### Partial Accept + Reject (Creates Child Lots)
```python
from InputScreening.services_submitted import create_partial_split_submission

accept_record, reject_record = create_partial_split_submission(
    original_lot_id="LID003",
    batch_id="BATCH125",
    original_qty=500,
    plating_stock_no="PS003",
    model_no="MODEL-C",
    tray_type="Normal",
    tray_capacity=20,
    
    accept_qty=250,
    reject_qty=250,
    accept_trays_json=[
        {"tray_id": "NB-A00182", "qty": 16},
        # ... 250 qty worth of trays ...
    ],
    reject_trays_json=[
        {"tray_id": "NB-A00183", "qty": 16},
        # ... 250 qty worth of trays ...
    ],
    accept_tray_count=16,
    reject_tray_count=16,
    
    accept_top_tray_id="NB-A00181",
    accept_top_tray_qty=3,
    reject_top_tray_id=None,
    reject_top_tray_qty=None,
    
    rejection_reasons_json={"R01": {...}},
    allocation_preview_json={...},
    delink_trays_json=[...],
    
    created_by=request.user,
    remarks="Partial rejection: 250 accepted, 250 model mixup",
)

# accept_record.lot_id == "LID<GENERATED_UUID1>"  [NEW]
# accept_record.parent_lot_id == "LID003"
# accept_record.is_child_lot == True
# accept_record.is_partial_accept == True

# reject_record.lot_id == "LID<GENERATED_UUID2>"  [NEW]
# reject_record.parent_lot_id == "LID003"
# reject_record.is_child_lot == True
# reject_record.is_partial_reject == True

# Original lot (LID003) should be marked inactive/revoked
# Future modules use LID<NEW_UUID1> and LID<NEW_UUID2>
```

### Querying Submissions

#### Get Active Submission
```python
from InputScreening.services_submitted import get_active_submission

record = get_active_submission("LID001")
if record:
    print(f"Status: {record.get_display_status()}")
else:
    print("Not found or revoked")
```

#### Get All Child Lots
```python
from InputScreening.services_submitted import get_all_child_lots

children = get_all_child_lots("LID003")  # Parent lot
for child in children:
    print(f"Child: {child.lot_id}, Qty: {child.submitted_lot_qty}")
    # Output:
    # Child: LID<UUID1>, Qty: 250
    # Child: LID<UUID2>, Qty: 250
```

#### Get Correct Lot for Downstream Modules
```python
from InputScreening.services_submitted import get_lot_for_next_module

record = get_lot_for_next_module("LID003")  # Could be parent or child
# Returns active child if split occurred, parent if no split
# This is what NEXT MODULES should use

metadata = get_lot_metadata_for_downstream("LID003")
# Returns dict with qty, trays, batch_id, etc.
# Exactly what downstream (DayPlanning, BrassQC) needs
```

---

## Integration for Future Modules

### Pattern: Getting Lot Data in Next Module

```python
# In DayPlanning or any downstream module
from InputScreening.services_submitted import get_lot_metadata_for_downstream

def get_lot_data_from_input_screening(lot_id):
    """
    Get correct lot data after Input Screening submission.
    
    If lot_id is parent with children, automatically uses child lot.
    """
    metadata = get_lot_metadata_for_downstream(lot_id)
    
    if not metadata:
        raise ValueError(f"Lot {lot_id} not found in Input Screening")
    
    # Now use this metadata - it's the committed, immutable state
    qty_to_process = metadata['qty']
    trays_to_allocate = metadata['trays']
    parent_reference = metadata['parent_lot_id']  # For audit trail
    
    return {
        'lot_id': metadata['lot_id'],  # Use THIS lot_id!
        'qty': qty_to_process,
        'trays': trays_to_allocate,
        'submission_type': metadata['submission_type'],
    }
```

### Important Rules for Downstream

1. **ALWAYS call `get_lot_metadata_for_downstream(lot_id)` FIRST**
   - Never fetch from live ModelMasterCreation for qty/trays
   - Use submitted snapshot from InputScreening_Submitted

2. **Use the returned `lot_id`**
   - If split occurred, use child lot_id (e.g., LID<NEW_UUID>)
   - Never reference parent_lot_id for processing

3. **Store parent_lot_id for Audit Trail**
   - Keep reference to parent for rollback/audit scenarios
   - But use child lot_id for all API calls

4. **Example: Jig Loading should do this**
   ```python
   # OLD (BAD - pulls live data):
   tray_qty = ModelMasterCreation.objects.get(batch_id=batch_id).total_batch_quantity
   
   # NEW (GOOD - uses committed snapshot):
   metadata = get_lot_metadata_for_downstream(lot_id)
   tray_qty = metadata['qty']
   jig_lot_id = metadata['lot_id']  # Use child if split
   ```

---

## Admin Interface

The model is registered in Django Admin with:

### Searchable Fields
- `lot_id`
- `parent_lot_id`
- `batch_id`
- `plating_stock_no`
- `model_no`
- `top_tray_id`

### Filters
- `is_active` - Show active/inactive submissions
- `is_revoked` - Find revoked records
- `is_partial_accept` / `is_partial_reject` - Find split lots
- `is_full_accept` / `is_full_reject` - Find complete submissions
- `is_child_lot` - Show child lots only
- `tray_type` - Filter by tray type
- `created_at` - Date range filtering
- `created_by` - User filter

### Display Columns
```
Lot ID | Batch ID | Status | Submitted Qty | Accepted Qty | Rejected Qty | Lot Type | Created At | Submitted By
```

### JSON Snapshot Viewing
- Click fieldset title to expand and view full JSON data
- Pretty-printed for readability
- Read-only (snapshots cannot be edited after creation)

---

## Transaction Safety & Atomicity

### Key Guarantee: No Half-Saves

All submissions use `@transaction.atomic()`:

```python
@transaction.atomic
def create_partial_split_submission(...):
    # If ANY error occurs here, BOTH children are rolled back
    # No scenario where 1 child exists without the other
    accept_record.save()  # Line 1
    reject_record.save()  # Line 2
    # Commit happens AFTER both succeed
```

### Database Constraints

- `lot_id` UNIQUE constraint prevents duplicates
- Foreign key to User prevents orphaned records
- Composite indexes prevent stale data queries
- All writes use explicit transactions

---

## Audit & Revocation

### Revoking a Submission

```python
from InputScreening.services_submitted import revoke_submission

revoke_submission(
    lot_id="LID001",
    revocation_reason="Manual audit correction - quantity was wrong"
)

# This:
# 1. Sets is_revoked=True
# 2. Sets is_active=False
# 3. Logs the revocation
# 4. Future modules will skip this lot
```

### Activation of Child Lot

If parent is revoked, activate correct child:

```python
from InputScreening.services_submitted import activate_child_lot

activate_child_lot("LID<NEW_UUID1>")  # Accept child becomes active
```

---

## Performance Characteristics

### Query Time Estimates

| Operation | Query | Indexes Used | Expected Time |
|-----------|-------|-------------|--------------|
| Get by lot_id | `lot_id="LID001"` | `iss_lot_id_idx` | < 1ms |
| Get all children | `parent_lot_id="LID003", is_child_lot=True` | `iss_parent_child_idx` | < 5ms |
| Get active by batch | `batch_id="BATCH1", is_active=True` | `iss_batch_active_idx` | < 5ms |
| List by date range | `created_at BETWEEN t1 AND t2` | `iss_created_at_idx` | < 50ms (100k rows) |

### Storage Estimates

Per record:
- Fixed fields: ~500 bytes
- JSON snapshots (avg): ~2 KB (20-30 trays + reasons)
- Total per record: ~2.5 KB
- Per 1M records: ~2.5 GB

### Scaling Recommendations

- **< 1M records:** No special tuning needed
- **1-10M records:** Consider archiving old records (> 1 year) to separate table
- **> 10M records:** Implement read replicas, consider sharding by batch_id

---

## Migration & Deployment

### Database Migration

```bash
python manage.py makemigrations InputScreening
python manage.py migrate InputScreening
```

### Post-Deployment Steps

1. Verify table exists and indexes are built
2. Test model with sample data:
   ```python
   python manage.py shell
   >>> from InputScreening.services_submitted import create_full_accept_submission
   >>> record = create_full_accept_submission(...)
   >>> print(record)
   ```
3. Monitor query performance with logs
4. Update downstream modules to use new service

---

## Future Enhancements

### Potential Additions

1. **Webhook notifications** - Trigger alerts when child lots created
2. **Automatic archival** - Move old records to archive table after 1 year
3. **Partial resubmission** - Allow editing rejected qty with new reasons
4. **Batch operations** - Bulk revoke/activate records
5. **Reporting** - Built-in reports for acceptance rates, rejection reasons
6. **API endpoints** - REST endpoints for submission lookup

---

## Troubleshooting

### Q: "lot_id is not unique" error on split

**A:** Child lot generation collision (extremely rare).
```python
# services_submitted.py has retry logic:
for _ in range(3):  # Retries
    if validate_lot_id_unique(accept_lot_id):
        break
    accept_lot_id = generate_lot_id()  # Generate new
```

### Q: Child lot not found in next module

**A:** Downstream module not calling `get_lot_for_next_module()`.
```python
# WRONG:
lot_id = original_lot_id  # Old parent

# RIGHT:
lot_data = get_lot_metadata_for_downstream(original_lot_id)
lot_id = lot_data['lot_id']  # Correct child or parent
```

### Q: JSON fields showing empty `[]` or `{}`

**A:** Normal - defaults are used when field not populated. Verify actual data:
```python
record = InputScreening_Submitted.objects.get(lot_id="LID001")
print(len(record.all_trays_json))  # Count of trays
```

---

## Reference

- **Model File:** `InputScreening/models.py` (InputScreening_Submitted class)
- **Service File:** `InputScreening/services_submitted.py`
- **Admin File:** `InputScreening/admin.py` (InputScreening_SubmittedAdmin)
- **Migration:** `InputScreening/migrations/0005_inputscreening_submitted.py`

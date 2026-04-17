# QUICK REFERENCE - Brass QC Raw Submission API

## 🎯 SINGLE API Endpoint
```
POST /brass_qc/api/submission/
```

## 📝 Request Payload
```json
{
  "lot_id": "LOT001",
  "batch_id": "BATCH001",
  "plating_stk_no": "1805NAR02",
  "total_lot_qty": 100,
  "rejection_reasons": [{"reason": "DENT", "qty": 5}],
  "reject_trays": [{"tray_id": "JB-001", "qty": 10, "type": "NEW", "is_top": true}],
  "accept_trays": [{"tray_id": "JB-002", "qty": 12, "type": "REUSED", "is_top": true}],
  "delink_trays": [{"tray_id": "JB-003"}],
  "summary": {"accepted": 65, "rejected": 35, "delinked": 1},
  "remarks": "Quality check completed",
  "submission_type": "DRAFT" | "SUBMIT"
}
```

## ✅ Response (201 Created)
```json
{
  "status": "success",
  "submission_type": "DRAFT|SUBMIT",
  "lot_id": "LOT001",
  "message": "Submission saved successfully",
  "submission_id": 42,
  "created_trays": [{"tray_id": "JB-001", "qty": 10}],
  "summary": {"accepted": 65, "rejected": 35, "delinked": 1},
  "next_module": "Brass Audit" | "IQF" | null
}
```

## 🔴 Errors (400, 404, 500)
```json
{
  "status": "error",
  "message": "Validation failed | Lot not found",
  "errors": ["Qty mismatch", "Remarks mandatory"]
}
```

## 🎮 Behavior Matrix

| submission_type | Validation | Tray Creation | Stage Movement | DB Update |
|---|---|---|---|---|
| DRAFT | ❌ None | ✅ Yes | ❌ No | ✅ Create/Update |
| SUBMIT | ✅ Full | ✅ Yes | ✅ Yes | ✅ Create |

## 📊 Stage Movement (SUBMIT)

| Submission Type | Condition | Next Module | Flag |
|---|---|---|---|
| Full Accept | accepted > 0, rejected = 0 | **Brass Audit** | brass_qc_accptance=True |
| Full Reject | accepted = 0, rejected > 0 | **IQF** | brass_qc_rejection=True |
| Partial | accepted > 0, rejected > 0 | **Brass Audit** | brass_qc_few_cases_accptance=True |

## 🔐 Validation Rules (SUBMIT only)

```
✅ accept_qty + reject_qty == total_lot_qty
✅ max 1 top tray in accept
✅ max 1 top tray in reject
✅ remarks mandatory if rejected_qty == total_qty
```

## 📦 What Happens

### 1. DRAFT Path
```
Payload received
  ↓
Stores in Brass_QC_RawSubmission (update if exists)
  ↓
Auto-creates missing trays in TrayId
  ↓
Response: success
```

### 2. SUBMIT Path
```
Payload received
  ↓
Validates all fields (returns 400 if fails)
  ↓
Stores in Brass_QC_RawSubmission
  ↓
Auto-creates missing trays in TrayId
  ↓
Updates TotalStockModel stage
  ↓
Response: success + next_module
```

## 🧪 Test
```bash
python manage.py shell
exec(open('test_brass_qc_raw_api.py').read())
```

## 🐛 Fixed Bugs

### ERR 2: Clear Button
- ✅ Now clears rejection reason quantities
- File: `Brass_PickTable.html` (line 2740)

### ERR 1: View Icon
- ✅ Enhanced logging to detect visibility issues
- File: `Brass_PickTable.html` (line 2066)
- Check browser console for: `[BrassQC] Found X view icon buttons`

## 📍 Files Changed

1. `Brass_QC/views.py` - NEW function `brass_qc_raw_submission()`
2. `Brass_QC/urls.py` - NEW route
3. `static/templates/Brass_Qc/Brass_PickTable.html` - Bug fixes
4. `test_brass_qc_raw_api.py` - NEW test file

## 💡 Key Principles

✅ **Single API** - One endpoint only
✅ **Exact Storage** - Payload stored as-is, no transformation
✅ **Validate on SUBMIT** - DRAFT bypasses validation
✅ **Auto-Create Trays** - Missing trays created automatically
✅ **Comprehensive Logging** - Every operation logged
✅ **Proper Stage Movement** - Routed to correct module

## 📚 Full Documentation
- See: `BRASS_QC_RAW_SUBMISSION_API_IMPLEMENTATION.md`
- See: `/memories/repo/brass-qc-raw-submission-api.md`


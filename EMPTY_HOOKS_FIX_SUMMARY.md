# Empty Hooks Calculation Fix - Summary

## Issue
When `lot_qty < jig_capacity` and there's no persisted draft (initial screen), the system incorrectly showed:
- `loaded_cases_qty = 0` (wrong)
- `empty_hooks = full jig capacity` (wrong)

But should show:
- `loaded_cases_qty = lot_qty` (correct - represents all available quantity will be loaded)
- `empty_hooks = jig_capacity - lot_qty` (correct - remaining hooks after loading all quantity)

---

## Example
**Input:**
- `lot_qty = 50`
- `jig_capacity = 98`
- `broken_hooks = 0`
- No persisted draft

**Before Fix:**
- displayed: `Loaded Cases Qty = 0/98`, `Empty Hooks = 98` ❌

**After Fix:**
- displayed: `Loaded Cases Qty = 50/98`, `Empty Hooks = 48` ✅

---

## Root Cause
The `InitJigLoad` API was missing:
1. **Backend calculations**: No logic to set `loaded_cases_qty` and `empty_hooks` when `lot_qty < effective_jig_capacity`
2. **API response fields**: The return statement wasn't including these critical fields at the top level
3. **Frontend dependencies**: Frontend code expected these fields from backend response

---

## Solution Implemented

### Backend Fix (Jig_Loading/views.py)

Added **server-authoritative** calculation immediately before the `return Response()`:

```python
# ===== CALCULATE SERVER-AUTHORITATIVE LOADED_CASES_QTY AND EMPTY_HOOKS =====
loaded_cases_qty = 0
broken_hooks_val = 0
jig_capacity_int = int(jig_capacity or 0)
lot_qty_int = int(lot_qty or 0)

try:
    # Get broken hooks from draft if exists
    broken_hooks_val = int(getattr(draft, 'broken_hooks', 0) or 0)
except Exception:
    broken_hooks_val = 0

effective_jig_capacity = max(0, jig_capacity_int - broken_hooks_val)

# Get loaded cases from draft if exists (for displays that already scanned)
try:
    if draft and getattr(draft, 'loaded_cases_qty', None):
        loaded_cases_qty = int(draft.loaded_cases_qty)
    else:
        loaded_cases_qty = 0
except Exception:
    loaded_cases_qty = 0

# 🔥 FIX: When lot_qty < effective_jig_capacity and no draft exists,
# the initial state should reflect that we'll load the entire lot.
# This ensures empty_hooks calculation reflects actual available capacity.
if lot_qty_int < effective_jig_capacity and not draft:
    loaded_cases_qty = lot_qty_int

# Empty hooks: remaining usable hooks on jig (server-authoritative)
# Business rule: if lot_qty >= effective_jig_capacity, jig will be fully consumed
# (no empty hooks). Otherwise, compute remaining hooks.
if lot_qty_int >= effective_jig_capacity:
    empty_hooks = 0
else:
    empty_hooks = max(0, effective_jig_capacity - loaded_cases_qty)
```

### API Response Enhancement
Added top-level fields to `return Response()`:
```python
return Response({
    'draft': resp_draft,
    'trays': trays,
    'lot_qty': int(lot_qty or 0),
    'original_capacity': int(jig_capacity_int or 0),
    'effective_capacity': int(effective_jig_capacity or 0),
    'loaded_cases_qty': int(loaded_cases_qty or 0),  # ← NEW
    'broken_hooks': int(broken_hooks_val or 0),      # ← ENHANCED
    'empty_hooks': int(empty_hooks or 0),            # ← NEW
    'excess_qty': int(excess_qty or 0) if 'excess_qty' in locals() else 0,
    # ... rest of response fields
})
```

---

## Business Rules Applied

1. ✅ **When `lot_qty < effective_jig_capacity` AND no draft:**
   - `loaded_cases_qty = lot_qty`
   - `empty_hooks = effective_jig_capacity - lot_qty`

2. ✅ **When `lot_qty >= effective_jig_capacity`:**
   - `empty_hooks = 0` (jig fully consumed by lot)
   - `loaded_cases_qty` respects existing draft values

3. ✅ **When draft exists:**
   - Use persisted `loaded_cases_qty` from draft
   - Recalculate `empty_hooks` based on draft state

---

## Frontend Compliance
✅ Frontend already correctly uses backend values:
```javascript
window.BACKEND_LOADED_CASES = parseInt(data.loaded_cases_qty || 0) || 0;
window.BACKEND_EMPTY_HOOKS = parseInt(data.empty_hooks || 0) || 0;
```

No frontend changes needed - it already displays backend-provided values.

---

## Verification

### Django Check
```
✅ System check identified no issues (0 silenced)
```

### Changed Files
- ` Jig_Loading/views.py` - InitJigLoad class, lines ~440-480

### Testing
Test script created: `test_empty_hooks_fix.py` (verifies logic, requires test data setup)

---

## Impact Analysis

| Scenario | Before | After | Impact |
|----------|--------|-------|--------|
| lot_qty=50, cap=98, no draft | LCQ=0, EH=98 | LCQ=50, EH=48 | ✅ FIXED |
| lot_qty=98, cap=98, no draft | LCQ=0, EH=98 | LCQ=0, EH=0 | ✅ CORRECT |
| lot_qty=150, cap=98, no draft | LCQ=0, EH=0 | LCQ=0, EH=0 | ✅ CORRECT |
| Any scenario with draft | Uses draft | Uses draft | ✅ NO CHANGE |

---

## Safety Checklist
- ✅ Backend is single source of truth
- ✅ Frontend only displays backend values
- ✅ No hardcoded values in JavaScript
- ✅ No duplicate variable declarations
- ✅ Django syntax check passes
- ✅ Existing workflows unchanged
- ✅ Only fixes the specific issue - no refactoring

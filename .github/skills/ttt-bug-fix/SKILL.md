---
name: ttt-bug-fix
description: "Diagnose and fix bugs in the TTT (Track and Trace) Django watchcase manufacturing system. Use for: wrong quantity displayed, button not working, API returning incorrect data, modal empty or crashing, stale data after reload, tray allocation errors, delink/reject confusion, SSOT violations, frontend doing backend calculations. Covers all modules: IQF, Brass QC, Brass Audit, Jig Loading, Input Screening, Day Planning, Spider Spindle, Jig Unloading."
argument-hint: "Describe the bug symptom or module name (e.g. IQF modal shows wrong qty, Brass QC proceed button disabled)"
---

# TTT Bug Fix Workflow

## Architecture Principles (Non-Negotiable)

1. **Backend is Single Source of Truth (SSOT)** — All calculations, validations, and state decisions live in Django views. Frontend is a pure render layer.
2. **Frontend calls API → displays response** — No quantity math, no business logic in JS templates.
3. **IQF processes rw_qty only** — IQF incoming qty = Brass QC `rw_qty`, NOT `total_batch_quantity`.
4. **`delink_tray ≠ rejected_tray`** — Delinked trays can be reused. Rejected trays are permanently ineligible.
5. **`IQF_Submitted.is_completed=True` is the truth** after IQF finalizes — always check this first.

---

## Step 1 — Classify the Bug

| Symptom | Bug Category | Jump to |
|---------|-------------|---------|
| Wrong number shown (qty, count) | Quantity mismatch | § Qty Bugs |
| Button disabled / not clickable | State flag or JS timing | § Button Bugs |
| Modal empty or missing rows | API returns wrong data | § API / Modal Bugs |
| Crash on submit or proceed | Backend validation error | § Submit Errors |
| Data gone after page reload | Draft/flag not persisted | § Persistence Bugs |
| Tray allocation wrong | Tray data source confusion | § Tray Bugs |
| Lot appears in wrong module | Movement flag wrong | § Movement Bugs |
| Frontend calculates instead of calling API | Architecture violation | § SSOT Fix |

---

## Step 2 — Locate the Relevant Files

### Module → File Map

| Module | Backend View | Template |
|--------|-------------|----------|
| IQF | `IQF/views.py` | `static/templates/IQF/Iqf_PickTable.html` |
| Brass QC | `Brass_QC/views.py` | `static/templates/BrassQC/Brass_Picktable.html` |
| Brass Audit | `BrassAudit/views.py` | `static/templates/BrassAudit/BrassAudit_Picktable.html` |
| Jig Loading | `Jig_Loading/views.py` | `static/templates/JigLoading/Jig_Picktable.html` |
| Input Screening | `InputScreening/views.py` | `static/templates/InputScreening/IS_PickTable.html` |
| Day Planning | `DayPlanning/views.py` | `static/templates/DayPlanning/DP_PickTable.html` |

### Key Model Files

| Model | Purpose |
|-------|---------|
| `modelmasterapp/models.py` → `TotalStockModel` | Master lot state and movement flags |
| `modelmasterapp/models.py` → `ModelMasterCreation` | Batch/lot metadata, qty |
| `IQF/models.py` → `IQF_Submitted` | IQF final decision SSOT (JSON snapshots) |
| `IQF/models.py` → `IQFTrayId` | IQF tray records (`remaining_qty`, `top_tray`, `delink_tray`, `rejected_tray`) |
| `Brass_QC/models.py` → `BrassTrayId` | Brass QC tray records |
| `Brass_QC/models.py` → `Brass_QC_Rejection_ReasonStore` | Brass QC rejection qty (rw_qty source) |

---

## Step 3 — Trace the Data Flow

### Universal Flow for Any Module

```
DB (Model) → Django View (API) → JSON Response → Template JS → DOM render
```

**Read files in this order:**
1. The template JS that triggers the API call (find `fetch(` or `$.ajax(`)
2. The Django URL that maps to the view (`<module>/urls.py`)
3. The view function/class (`<module>/views.py`)
4. The model fields queried (`<module>/models.py` or `modelmasterapp/models.py`)

---

## § Qty Bugs — Quantity Mismatch

**Common root causes:**
- Using `total_batch_quantity` instead of `rw_qty` (IQF domain violation)
- `remaining_qty` vs `tray_quantity` confusion on `IQFTrayId`
- Aggregating across wrong lot_id scope
- Stale `IQF_Submitted` data not checked first

**Fix checklist:**
- [ ] Confirm which qty field the view queries; for IQF use `Brass_QC_Rejection_ReasonStore.total_rejection_quantity` or `IQF_Submitted.iqf_incoming_qty`
- [ ] For tray qty: use `IQFTrayId.remaining_qty` (post-processed), NOT `tray_quantity`
- [ ] If lot has been through IQF before: check `IQF_Submitted.is_completed=True` FIRST and use `iqf_incoming_qty`
- [ ] Verify `lot_id`-scoped queries — never query globally without lot filter

**Pattern:**
```python
# CORRECT (IQF domain)
iqf_sub = IQF_Submitted.objects.filter(lot_id=lot_id, is_completed=True).last()
rw_qty = iqf_sub.iqf_incoming_qty if iqf_sub else qc_store.total_rejection_quantity

# WRONG — never use full batch qty in IQF
rw_qty = ts.total_batch_quantity  # ❌
```

---

## § Button Bugs — Button Disabled / Not Clickable

**Two sub-types:**

### A. Backend state flag wrong
- Look at `build_ui_state()` in `IQF/views.py` or equivalent `get_context_data()` in other modules
- Check which flag controls the button (`can_delete`, `allow_remarks`, `action_type`)
- Trace the flag back to the model field it reads

### B. JavaScript timing (DOM not ready)
- See user memory `javascript-dom-timing-fix.md`
- Buttons discovered via `querySelectorAll` before DOM is ready
- Fix: wrap in `DOMContentLoaded` listener

```javascript
// Fix pattern
document.addEventListener('DOMContentLoaded', function () {
  const btn = document.querySelector('#my-btn');
  btn.addEventListener('click', handler);
});
```

**Validation:** `python manage.py check` confirms no Django errors; browser console confirms button count > 0.

---

## § API / Modal Bugs — Modal Empty or Missing Rows

**Investigation steps:**
1. Open browser DevTools → Network tab → find the failing API call
2. Check response JSON for errors or empty arrays
3. In the view: check the queryset filters — often `lot_id` mismatch or wrong `is_completed` flag
4. Check if the response key name matches what the template JS expects

**Common fixes:**
- Wrong queryset: missing `.filter(lot_id=lot_id)` scope
- Wrong field name in response dict vs JS `data.field_name`
- Pagination cutting off results — check `Paginator` page size
- Serializer missing field — add it to the response dict

---

## § Submit Errors — Crash on Submit or Proceed

**Django-side:**
1. Check server logs or `python manage.py shell` to reproduce
2. Look for `transaction.atomic()` rollback — which model `.save()` failed?
3. Check `IQF_Submitted.clean()` constraint: `accepted_qty + rejected_qty == iqf_incoming_qty`
4. Check `CheckConstraint` in `IQF_Submitted.Meta` — DB-level enforcement

**Common causes:**
- `accepted_qty + rejected_qty ≠ iqf_incoming_qty` → fix calculation before save
- Missing mandatory field (`remarks` is mandatory on Proceed)
- Foreign key `batch_id` is null when model expects a value

---

## § Persistence Bugs — Data Gone After Reload

**Symptoms:** User fills form, refreshes page, data resets.

**Root causes & fixes:**

| Cause | Fix |
|-------|-----|
| Draft saved to session instead of DB | Save to `IQF_Draft_Store` or `TotalStockModel` fields |
| `Draft_Saved` flag not set on `TotalStockModel` | Add `ts.Draft_Saved = True; ts.save()` after draft write |
| `iqf_accepted_qty_verified` not toggled | Call `iqf_toggle_verified` API on checkbox change |
| Frontend-only state (JS variable) | Move to backend field; return from API on re-init |

---

## § Tray Bugs — Wrong Tray Allocation

**Key distinction:**

```python
IQFTrayId.rejected_tray = True   # PERMANENTLY rejected — never reuse
IQFTrayId.delink_tray = True     # DELINKED — can be reused in next cycle
```

**Eligibility query pattern:**
```python
# Eligible trays for IQF acceptance
eligible = IQFTrayId.objects.filter(
    lot_id=lot_id,
    rejected_tray=False  # Not permanently rejected
).exclude(delink_tray=True)  # Exclude delinked
```

**Top tray logic:**
1. Try to preserve existing `top_tray=True` from source module
2. Fallback: `order_by('tray_quantity').first()` — smallest qty = top tray
3. Always `reset all top_tray=False` before reassigning

**Tray data priority (IQF view icon / tray details):**
1. `IQF_Submitted.is_completed=True` → use `full_accept_data` / `partial_accept_data`
2. Fallback: `Brass_Audit_Rejected_TrayScan` (re-entry from Audit)
3. Fallback: `Brass_QC_Rejected_TrayScan` (first cycle)
4. Final fallback: `IQFTrayId.tray_quantity` directly

---

## § Movement Bugs — Lot in Wrong Module

**Movement flags on `TotalStockModel`:**

| Flag | Meaning |
|------|---------|
| `send_brass_qc = True` | Lot moves to Brass QC pick table |
| `send_brass_audit = True` | Lot moves to Brass Audit |
| `iqf_onhold_picking = True` | IQF partial — shows "Verify" button |
| `iqf_acceptance = True` | IQF accepted |
| `iqf_rejection = True` | IQF rejected |
| `last_process_module` | Tracks where lot is now |
| `next_process_module` | Tracks where lot goes next |

**Fix pattern:** Find where the lot transitions; check which flags are set/cleared and in what order.

---

## § SSOT Fix — Frontend Doing Calculations

**Symptom:** JS computes qty / state instead of calling API.

**Fix:**
1. Move calculation to Django view — create or update an API endpoint
2. Return complete computed state in response
3. Strip frontend calculation; replace with `data.field_from_api`
4. Follow `JigLoadingService.get_complete_jig_state()` as reference pattern

---

## Step 4 — Implement the Fix

### Backend (views.py) rules:
- Always use `@transaction.atomic` for multi-model writes
- Return structured response: `{'success': True, 'data': {...}, 'message': '...'}`
- Never return raw model instances — serialize to dict first
- Scope all queries to `lot_id` — never global state

### Frontend (template) rules:
- Never compute qty in JS — read from API response
- Wrap event handlers in `DOMContentLoaded`
- Use `console.log` for debug; remove before committing
- CSRF token in POST: `X-CSRFToken` header from `getCookie('csrftoken')`

---

## Step 5 — Validate

```bash
# Django config check (always run first)
python manage.py check

# Quick shell test for a specific lot
python manage.py shell -c "
from IQF.models import IQF_Submitted
s = IQF_Submitted.objects.filter(lot_id='LID...').first()
print(s)
"

# Template syntax check
python manage.py check --deploy
```

**Browser:**
1. DevTools Console — no JS errors
2. Network tab — API returns expected JSON shape
3. Manual test — trigger the original reported scenario

---

## Common Anti-Patterns to Avoid

| Anti-pattern | Correct approach |
|---|---|
| `ts.total_batch_quantity` used in IQF | Use `IQF_Submitted.iqf_incoming_qty` |
| Frontend qty = `parseInt(input.value)` math | Backend computes, frontend displays |
| Queryset without `lot_id` filter | Always filter by `lot_id` |
| `rejected_tray` checked as delink | These are different flags — check both |
| Save model without `transaction.atomic` | Wrap multi-model writes atomically |
| `IQF_Submitted` created before validation | Validate first, then create/update |

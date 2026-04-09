# Jig Loading Flow – Functional Specification

## 1. Source from Brass Audit
- Accepted, Partial Accepted, and Fully Accepted lots from Brass Audit will move to Jig Loading.

---

## 2. Jig ID Rules
- Jig ID should be accepted only from Master data.
- Example:
  - If capacity = 144 → Accept only `J144`
  - If capacity = 98 → Accept only `J098` series
- Jig ID will be **unmapped only during Jig Unload**.

---

## 3. Loaded Case Quantity Display
- Format: `Loaded Case Qty = X / Y`
  - **Left (X)** → Increases during Delink Scan
  - **Right (Y)** → Jig capacity (dynamic, from Master)

### Special Case:
- If **broken hooks are entered**:
  - Jig capacity (Y) will **decrease dynamically**

---

## 4. Empty Hooks Logic
- Empty hooks = `Lot Quantity - Jig Capacity`

### Conditions:
- If **Empty Hooks < 0**
  → Enable **Add Model**

- If **Empty Hooks > 0**
  → Excess trays must be handled

---

## 5. Excess Tray Handling
- If excess occurs:
  - Excess tray scan will be handled inside **"Add Jig" button modal popup**
  - User must:
    - Select **Top excess tray quantities**
    - Select **Tray IDs using checkboxes**
    - Selection must be **model-specific**

### Important Rule:
- Excess lot handling should be done **only from the latest added model**
- Should NOT be handled from middle models

---

## 6. Delink Process
- After excess tray scan is completed:
  - Remaining excess tray IDs must be verified

- Then:
  - **Delink (DNK) option will be enabled**

### Selection:
- "Select All" checkbox will be available
- User can:
  - Select individually OR
  - Use Select All

---

## 7. Final Submission Flow
- Once all trays are selected:
  - On Submit:
    - Data moves to:
      - **Jig Completed Table**
      - **In-Process Inspection Table**

---

## 8. Key Constraints
- No manual Jig ID entry (only from Master)
- Dynamic capacity update required
- Excess handling strictly controlled
- Latest model priority for excess handling
- Delink enabled only after validation

---

## End of Flow
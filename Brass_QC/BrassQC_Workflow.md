# 📘 Brass QC Module – Functional Documentation

---

## 🔹 Overview

The **Brass QC (Quality Check)** module processes lots received from **Input Screening (IS)**.

It handles:

* Full Acceptance
* Partial Acceptance
* Full Rejection
* Partial Rejection (with reasons)

---

## 🔹 Source

* Lots come from **Input Screening**

  * Fully Accepted Lots
  * Partially Accepted Lots

---

## 🔹 Initial Step: Lot Selection

* User selects lot
* **Lot Quantity Checkbox** must be checked to enable:

  * Accept
  * Reject

---

## 🔹 Actions in Brass QC

---

## ✅ 1. Accept Flow

### ✔ Full Accept

* Entire lot is accepted
* No rejection involved

### ✔ Partial Accept

* Some quantity accepted, rest rejected

### ➡ Outcome:

* Moves to next stage:
  ➤ **Brass Audit**

---

## ❌ 2. Reject Flow

Two types of rejection:

---

## 🔸 A. Lot Rejection (Full Lot Reject)

### Flow:

* User selects: ✔ **Lot Qty Checkbox**
* Enables **Lot Rejection**
* Remarks field is **mandatory**
* Submit rejection

### UI Requirement:

* Remarks must appear in:
  ➤ **Brass QC Completed Table**

  * Under **Remarks Column**
  * As **Info / View Icon**

### Outcome:

* Entire lot is rejected
* Moves to:
  ➤ **IQF Stage**

---

## 🔸 B. Rejection with Reasons (Partial Rejection)

### Flow:

* User enters:

  * Rejection Reason (R01, R02, etc.)
  * Rejection Quantity

---

## 🔹 Tray Segregation Logic

* Based on **Total Rejection Quantity**
* System calculates required tray slots

### 📌 Example:

* Rejection Qty = 25
* Tray Type = Normal (Capacity-based)

➡ System opens:

* **2 tray slots**

---

## 🔹 Tray Selection Rules

### ✔ Flexible Tray Usage

* User can use:

  * Existing trays
  * Any available trays

---

### 🚨 Rule: Prevent Wrong Tray Usage

* If **eligible trays already exist**:

  * Using **new tray** should trigger:
    ➤ **Delink Warning / Prompt**

---

## 🔹 Mixing Allowed

* Unlike Input Screening:

  * Rejection reasons **can be mixed**
  * Multiple reasons can exist in same tray flow

---

## 🔹 Submission Outcome

On submit:

### ✔ System Categorizes Trays:

* ACCEPTED
* REJECTED
* DELINKED

### ✔ Data moves to:

* **Brass QC Completed Table**

With proper labels:

* Accepted
* Rejected
* Delinked

---

## 🔹 Next Stage Routing

### ➤ If Fully / Partially Accepted:

* Move to:
  ✔ **Brass Audit**

---

### ➤ If Fully / Partially Rejected:

* Move to:
  ✔ **IQF**

---

## 🔹 Validation Rules

* Lot checkbox must be selected
* Remarks mandatory for **Lot Rejection**
* Rejection qty ≤ total lot qty
* Tray allocation must match rejection qty
* Prevent unnecessary new tray usage
* Trigger delink logic when required

---

## 🔹 UI Requirements

* Show **Lot Quantity clearly**
* Enable actions only after checkbox selection
* Remarks:

  * Show as **Icon (View/Info)**
  * Not full text
* Clear tray categorization:

  * ACCEPTED
  * REJECTED
  * DELINKED

---

## 🔹 Backend Responsibilities (Strict)

* Compute:

  * Tray split
  * Rejection allocation
  * Delink logic
  * Final tray status

* Provide:

  * Single API response with:

    * tray_id
    * status (ACCEPTED / REJECTED / DELINKED)
    * quantity

---

## 🔹 Frontend Responsibilities

* Fetch API
* Render UI
* No logic / no calculations

---

## 🔹 Final Flow Summary

1. Lot received from Input Screening
2. User selects lot → enables actions
3. Accept / Reject

### If Accept:

→ Brass Audit

### If Reject:

* Lot Reject → IQF
* Partial Reject → Tray split

4. Submit
5. Data shown in Brass QC Completed Table
6. Routing:

   * Accepted → Brass Audit
   * Rejected → IQF

---

## ✅ End of Document

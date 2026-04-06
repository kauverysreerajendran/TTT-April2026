# 📘 Input Screening Module – Functional Documentation

## 🔹 Overview

The **Input Screening (IS)** module is used to validate trays received from **Day Planning** and process them through **verification, acceptance, rejection, and delink flows**.

---

## 🔹 Source

* Batch is received from **Day Planning Module**

---

## 🔹 Initial State

* All trays will have status:
  ➤ **"Not Verified"**

---

## 🔹 Step 1: Tray Verification

* User scans / validates trays
* After successful verification:

  * Status updates from **"Not Verified" → "Verified"**
  * **Accept** and **Reject** actions become enabled

---

## 🔹 Step 2: Actions After Verification

### ✅ Accept (Full Lot Acceptance)

* On clicking **Accept**:

  * Entire lot is accepted
  * No partial handling required
  * Lot is moved to next stage:
    ➤ **Brass QC**

---

### ❌ Reject (Two Types)

---

## 🔸 1. Lot Rejection

**Flow:**

* User selects checkbox: ✔ **Lot Rejection**
* Remarks field becomes **mandatory**
* User submits rejection

**Outcome:**

* Entire lot is rejected
* Record moves to:

  * **IS Complete Table**
  * **Rejection Table**

---

## 🔸 2. Rejection with Reasons (Partial Rejection)

**Flow:**

* User enters:

  * Rejection Reason (e.g., R01, R02)
  * Rejection Quantity

---

### 🔹 Tray Splitting Logic

* Based on rejection quantity:

  * Trays are **split automatically**

#### 📌 Rule 1: No Reason Shuffling

* Each rejection reason must remain isolated
* Cannot mix quantities across reasons

#### 📌 Example:

* If user enters:

  * **24 qty for R01**
  * Tray type: Jumbo tray

➡ System should:

* Allocate **2 tray slots** for R01 (based on capacity)

---

### 🔹 Reuse Logic

* System calculates:

  * How many trays become **0 quantity** after rejection

#### 📌 Rule 2: Reuse Limit

* Only those trays which become **0 qty** can be reused

#### 📌 Example:

* If only **2 trays** become empty:

  * Allow reuse of **maximum 2 trays only**
  * User can choose **any 2 trays**, but not more

---

## 🔹 Delink Logic (NEW)

Delink occurs when trays become empty or need to be removed from the lot.

### 📌 When Delink Happens:

* When trays reach **0 quantity**
* When system detects **extra/unused trays**
* During rejection or reuse scenarios

---

### 📌 Delink Rules:

* Only eligible trays (0 qty) can be delinked
* Delink count must match system-calculated limit
* Cannot delink more trays than allowed

---

### 📌 Delink Outcome:

* Delinked trays will:

  * Be marked as **DELINKED**
  * Appear in **IS Complete Table**
  * Not be counted in accepted/rejected quantities

---

## 🔹 Submission Outcome

* On submit:

  * Partial rejection data moves to:

    * **IS Complete Table**
    * **Rejection Table**

* System categorizes trays as:

  * **ACCEPTED**
  * **REJECTED**
  * **DELINKED**

* Remaining accepted quantity:

  * Gets **consolidated at lot level**
  * Moves to:
    ➤ **Brass QC Stage**

---

## 🔹 Validation Rules

* Remarks mandatory for **Lot Rejection**
* Rejection qty must not exceed total lot qty
* Tray reuse must not exceed calculated empty trays
* No mixing of rejection reasons
* Delink must not exceed allowed limit
* All calculations must be dynamic (based on lot + tray data)

---

## 🔹 UI Expectations

* Show **Lot Quantity at Top (Dynamic)**
* Clear separation:

  * Accept vs Reject flows
* Remarks column:

  * Use **View Icon**
  * Show remarks on hover / click (tooltip or modal)
* Completed table must show:

  * ACCEPTED
  * REJECTED
  * DELINKED (proper labels, no misclassification)

---

## 🔹 API Notes

* Ensure:

  * `total_qty` is correctly fetched and passed

* Validate in:

  * `/inputscreening/batch_rejection/`

* If missing:

  * Fetch from DB using `lot_id`

* Completed Table API must return:

  ```
  {
    tray_id,
    status: "ACCEPTED" | "REJECTED" | "DELINKED",
    qty
  }
  ```

---

## 🔹 Final Flow Summary

1. Batch comes from Day Planning

2. Tray Verification

3. Accept OR Reject

4. Reject:

   * Full Lot → Direct reject
   * Partial → Reason-based tray split

5. Delink handled automatically (if applicable)

6. Submit

7. Data moves to:

   * IS Complete Table
   * Rejection Table

8. Accepted qty → Brass QC

---

## ✅ End of Document

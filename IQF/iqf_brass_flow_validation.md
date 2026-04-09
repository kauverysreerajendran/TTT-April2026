# IQF ↔ Brass QC Flow Data (Exact Scenario)

## Stage 1 — Brass QC

Lot Qty = 100  
No of Trays = 7  

Tray Details:
- NB-A00001 = 4 (Top Tray)
- NB-A00002 = 16
- NB-A00003 = 16
- NB-A00004 = 16
- NB-A00005 = 16
- NB-A00006 = 16
- NB-A00007 = 16

Action:
- Partial Accept = 60
- Partial Reject = 40

Output:
- Accepted → Brass Audit (60)
- Rejected → IQF (40)

---

## Stage 2 — IQF

Lot Qty = 40  
No of Trays = 3  

Tray Details:
- NB-A00001 = 8 (Top Tray)
- NB-A00002 = 16
- NB-A00003 = 16

Action:
- Lot Accept = 40

Output:
- Move to Brass QC (40)

---

## Stage 3 — Brass QC

Lot Qty = 40  
No of Trays = 3  

Tray Details:
- NB-A00001 = 8 (Top Tray)
- NB-A00002 = 16
- NB-A00003 = 16

Action:
- Lot Reject = 40

Output:
- Move to IQF (40)

---

## Stage 4 — IQF

Lot Qty = 40  
No of Trays = 3  

Tray Details:
- NB-A00001 = 8 (Top Tray)
- NB-A00002 = 16
- NB-A00003 = 16

Action:
- Partial Accept = 25
- Partial Reject = 15

Output:
- Accepted → Brass QC (25)
- Rejected → IQF Reject (15, ends here)

---

## Stage 5 — Brass QC

Lot Qty = 25  
No of Trays = 2  

Tray Details:
- NB-A00001 = 9 (Top Tray)
- NB-A00002 = 16

Action:
- Partial Accept = 16
- Partial Reject = 9

Output:
- Accepted → Brass Audit (16)
- Rejected → IQF (9)
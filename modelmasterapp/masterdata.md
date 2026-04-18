# Tray Master Reference (MD File)

## Purpose
This file is the **master reference** for tray handling across modules:

- Jig Loading
- Jig Unloading
- Nickel Wiping
- Nickel Audit
- Brass QC
- IQF
- Tray Validation
- Auto Tray Split Logic

Use this file as **single source of truth** for:

- Tray Code
- Tray Color
- Tray Category
- Max Capacity
- Model Mapping
- Similar Look Models
- Zone Logic

---

# Core Tray Rules

## Nickel Tray Capacity Rules

| Tray Code Prefix | Tray Type | Max Capacity | Color |
|---|---|---:|---|
| JB | Jumbo Blue | 12 | Blue |
| JR | Jumbo Red | 12 | Red |
| JD | Jumbo Dark Green | 12 | D.Green |
| NB | Normal Blue | 20 | Blue |
| NR | Normal Red | 20 | Red |
| ND | Normal Dark Green | 20 | D.Green |
| NL | Normal Light Green | 20 | L.Green |

---

# Module Rules

## Jig Loading

- Use **Tray Cate - Capacity**
- Jumbo = 12
- Normal = 16

## Jig Unloading

- Use **Nickel Tray Cate - Capacity**
- Jumbo = 12
- Normal = 20

## Nickel Wiping / Nickel Audit / Nickel QC

- Use **Nickel Tray Cate - Capacity**
- Jumbo = 12
- Normal = 20

---

# Color Logic

| Plating Color | Tray Color |
|---|---|
| IPS | Red |
| RG | D.Green |
| BLACK | Blue |
| IP-GUN | D.Green |
| IP-BROWN | D.Green |
| RG-BI | L.Green |
| IPG-2N | Red |

---

# Model Master Table

| Plating Stock No | Brand | Gender | Jig Qty | Tray Code | Nickel Tray |
|---|---|---|---:|---|---|
| 2617SAA02 | CPSF | LAD | 144 | NR | Normal Red |
| 2617WAB02 | CPSF | LAD | 144 | ND | Normal D.Green |
| 2617NAD02 | CPSF | LAD | 144 | NB | Normal Blue |
| 2648QAB02/GUN | CPSF | LAD | 144 | ND | Normal D.Green |
| 1805SAA02 | CPSF | GEN | 98 | JR | Jumbo Red |
| 1805NAA02 | CPSF | GEN | 98 | JB | Jumbo Blue |
| 1805WAA02 | CPSF | GEN | 98 | JD | Jumbo D.Green |

---

# Similar Look Models

| Model | Looks Like |
|---|---|
| 2617 | 2648 |
| 2648 | 2617 |
| 1805 | Nil |

Use for:
- Add Model popup
- Similar model merge
- Cross-lot suggestions

---

# Tray Prefix Validation

## Reject Tray Scan

### Allowed:

- JB
- NB

### Not Allowed:

- JR
- NR
- ND
- JD
- Existing production trays

---

# Top Tray Rules

- First tray = Top Tray
- Must belong to current lot
- Reused top tray allowed if same lot
- UI must mark as TOP

---

# Auto Tray Split Rules

## Example: Qty 44 (Normal Tray)

- Tray 1 = 20
- Tray 2 = 20
- Tray 3 = 4

## Example: Qty 44 (Jumbo Tray)

- Tray 1 = 12
- Tray 2 = 12
- Tray 3 = 12
- Tray 4 = 8

---

# Dynamic Tray Fetch Rules

Always fetch from:

1. View Icon Tray List
2. Completed Table Tray IDs
3. Current Lot Tray History

Never use:

- Placeholder trays
- TOP_UNLOT...
- FULL_UNLOT...

---

# Accept / Reject Rules

## Partial Reject

- Delink from existing trays first
- Rejected qty -> reject tray
- Remaining qty -> accept tray

## Full Reject

- Entire lot to reject table

## Full Accept

- Move to next stage as per zone rule

---

# Draft Rules

- Restore same tray IDs
- Restore split qty
- Restore top tray
- Preserve remarks

---

# Development Notes

If any module has wrong tray qty:

## First check:

1. Is module using Tray Cate - Capacity instead of Nickel Tray Cate - Capacity?
2. Is placeholder tray generator active?
3. Is prefix validation wrong?
4. Is old hardcoded 16 still used?

---

# Recommended Use in Code

```python
TRAY_MASTER = {
    "JB": 12,
    "JR": 12,
    "JD": 12,
    "NB": 20,
    "NR": 20,
    "ND": 20,
    "NL": 20
}
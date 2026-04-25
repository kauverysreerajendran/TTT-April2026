# CLAUDE.md

# Project AI Operating Manual
Enterprise Manufacturing Workflow System

---

# 1. Project Overview

This is a production-grade manufacturing workflow application used for lot movement, tray tracking, quality checks, and stage-based processing.

Main Modules:

- Input Screening
- Day Planning
- Brass QC
- Tray Management
- Lot Tracking
- Reject Handling
- Acceptance Processing
- Audit & Reports

Technology Stack:

- Python Django
- HTML / CSS / JavaScript
- SQL Database
- IIS Hosted Environment

---

# 2. Core Engineering Principles

## Golden Rule

Frontend displays. Backend decides.

## Mandatory Rules

- Backend is the only source of truth.
- Frontend must be fetch + render only.
- No business logic in JavaScript.
- No duplicate APIs for same action.
- One API = One responsibility.
- No hardcoded values.
- No hidden calculations in UI.
- Every critical action must be DB-backed.

---

# 3. Django Architecture Pattern

Use strict layered architecture:

- models.py      → DB schema only
- views.py       → HTTP layer only
- selectors.py   → Read queries / reporting
- services.py    → Business logic / writes
- validators.py  → Input validation
- urls.py        → Route mapping

## Rules

- Views must remain thin.
- No ORM-heavy code inside views.
- Business logic belongs only in services.
- Complex reads belong only in selectors.

---

# 4. Coding Standards

## Python

- Use clean readable names
- Keep functions focused
- Reuse existing utilities
- Use logging not print()
- Use transactions for write flows
- Handle exceptions gracefully
- Remove dead code
- Avoid duplicate logic

## Query Optimization

Always prefer:

- select_related()
- prefetch_related()
- exists()
- bulk_create()
- update()

Avoid:

- N+1 queries
- repeated loops hitting DB
- loading unused fields

---

# 5. Frontend Rules

Frontend responsibilities only:

- Capture user input
- Call API
- Render response
- Show loading/error states

Frontend must NOT do:

- Qty calculations
- Tray allocation logic
- Validation logic
- Stage decisions
- API selection logic
- Process rules

## UI Rules

- Do not break existing UI
- Keep styling stable unless requested
- Reuse modal components
- Reuse table patterns
- Use delegated click handlers

---

# 6. Database Standards

All important tables should maintain:

- created_at
- created_by
- updated_at
- updated_by
- is_active
- remarks

Use indexes for:

- lot_id
- tray_id
- batch_id
- created_at
- stage

Use soft delete where possible.

---

# 7. Tray & Lot Business Rules (CRITICAL)

## Tray Ownership Rules

A tray ID cannot be used in:

- another lot
- another stage
- another active transaction

UNLESS:

- tray is officially delinked
- tray is marked reusable
- tray is registered as a new free tray

## Duplicate Prevention

Same tray must never exist as active in:

- two lots
- two modules
- two stages
- accept + reject simultaneously

## Delink Rules

When tray is emptied or released:

- mark as delinked
- store delink timestamp
- store delink reason
- allow reuse only after valid state update

## New Tray Rules

New tray can be used only if:

- exists in tray master
- not occupied
- not linked to lot
- not rejected permanently
- not blocked

---

# 8. Input Screening Rules

Tables:

- Pick Table
- Accept Table
- Completed Table
- Reject Table

Submission Types:

- Full Accept
- Partial Accept
- Full Reject
- Partial Reject
- Draft

## Accept Table Rules

Must show:

- full accept records
- partial accept records

## Reject Table Rules

Must show:

- partial reject
- full reject

## Completed Table Rules

Must show final processed lots only.

## View Icon Rule

Single API only:

/inputscreening/submitted_detail/?lot_id=<lot_id>

Popup must show exact backend tray snapshot:

- tray ids
- qty
- top tray
- accepted/rejected split
- remarks
- timestamps

No frontend-generated tray data.

---

# 9. Quantity Rules

Lot qty must always equal:

Accepted Qty + Rejected Qty + Pending Qty

Never allow:

- negative qty
- over allocation
- duplicate tray qty
- tray qty beyond capacity

Top tray qty must remain accurate.

---

# 10. Reject Rules

- One reject tray should not mix multiple reject reasons unless approved design.
- Reuse emptied trays only within delink limit.
- Reject qty cannot exceed original qty.
- Reason codes mandatory.

---

# 11. API Standards

Every action must have one API only.

## Correct Examples

Accept submit:
POST /inputscreening/full_accept/

Reject submit:
POST /inputscreening/full_reject/

View detail:
GET /inputscreening/submitted_detail/?lot_id=...

## Never Allow

- multiple APIs for same submit
- frontend choosing between APIs
- duplicated overlapping endpoints

---

# 12. Security Rules

- Validate all inputs server-side
- Use authentication on all pages
- Authorize actions by role
- Sanitize remarks/text inputs
- Prevent direct object access
- Protect against duplicate submissions

---

# 13. Logging Standards

Log:

- API request inputs
- user id
- lot id
- tray ids
- validation failures
- submit success
- exceptions
- query timing

Use structured logs.

---

# 14. Performance Targets

- Page load under 2 sec
- Table query under 500 ms
- Modal detail under 1 sec
- No duplicate API calls
- Pagination mandatory for large tables

---

# 15. No Regression Policy

Before any change:

- Check existing flows
- Check tables
- Check modals
- Check exports
- Check permissions
- Check old URLs

Never break working production features.

---

# 16. AI Assistant Working Rules

When asked to fix code:

1. Understand business rule first
2. Find root cause, not symptom
3. Apply minimal isolated fix
4. Preserve architecture
5. Return changed blocks only
6. Mention impact
7. Mention regression risk

If frontend contains business logic:

STOP and move logic to backend.

If duplicate APIs exist:

STOP and consolidate.

---

# 17. Release Checklist

Before deploy:

- migrations checked
- queries optimized
- logs clean
- UI tested
- tray rules tested
- duplicate tray tested
- qty reconciliation tested
- permissions tested

---

# 18. Final Principle

Frontend displays.
Backend decides.
Database remembers.
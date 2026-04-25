"""
IQF Tray Service — tray resolution, allocation, slot computation.

All tray-related logic lives here.
Views and submission_service call these functions.

Rule: No HTTP layer here. Pure data functions.
"""

import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Slot computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_slots(qty, capacity):
    """
    Compute tray slot distribution.

    Pattern: top tray gets the remainder; other trays get full capacity.
    e.g. qty=25, capacity=16 → slots: [9 (top), 16]
    e.g. qty=20, capacity=16 → slots: [4 (top), 16]

    Returns list of {"qty": int, "is_top": bool, "tray_id": None}
    """
    if qty <= 0 or capacity <= 0:
        return []

    full_trays = qty // capacity
    remainder = qty % capacity
    slots = []

    if remainder > 0:
        # Has remainder: first slot is top tray with remainder qty
        slots.append({"qty": remainder, "is_top": True, "tray_id": None})
        for _ in range(full_trays):
            slots.append({"qty": capacity, "is_top": False, "tray_id": None})
    else:
        # No remainder: first full tray is top, rest are non-top
        slots.append({"qty": capacity, "is_top": True, "tray_id": None})
        for _ in range(full_trays - 1):
            slots.append({"qty": capacity, "is_top": False, "tray_id": None})

    return slots


# ─────────────────────────────────────────────────────────────────────────────
# Tray reuse logic
# ─────────────────────────────────────────────────────────────────────────────

def compute_reuse_trays(trays, alloc_qty):
    """
    Deterministic tray reuse logic.

    Only trays that become ZERO after allocation are eligible for reuse.
    Processing order: TOP tray first, then sequential by tray_id.

    Returns:
        {"reuse_trays": [tray_id, ...], "updated_trays": [...]}
    """
    trays_sorted = sorted(
        trays,
        key=lambda x: (not x.get('is_top', False), x.get('tray_id', '')),
    )
    reuse_trays = []
    updated_trays = []
    remaining_alloc = alloc_qty

    for tray in trays_sorted:
        tray_qty = tray.get("qty", 0)
        if remaining_alloc <= 0:
            updated_trays.append({**tray, "remaining_qty": tray_qty})
            continue
        if remaining_alloc >= tray_qty:
            remaining_alloc -= tray_qty
            updated_trays.append({
                **tray,
                "used_qty": tray_qty,
                "remaining_qty": 0,
                "status": "ALLOC_FULL",
            })
            reuse_trays.append(tray["tray_id"])
        else:
            updated_trays.append({
                **tray,
                "used_qty": remaining_alloc,
                "remaining_qty": tray_qty - remaining_alloc,
                "status": "ALLOC_PARTIAL",
            })
            remaining_alloc = 0

    return {"reuse_trays": reuse_trays, "updated_trays": updated_trays}


# ─────────────────────────────────────────────────────────────────────────────
# Tray segregation (for PARTIAL splits)
# ─────────────────────────────────────────────────────────────────────────────

def segregate_trays_for_partial(active_trays, accepted_tray_ids, accepted_qty):
    """
    Segregates trays into accepted vs rejected groups for PARTIAL submission.

    Returns:
        (accepted_trays, rejected_trays)
    """
    accepted_set = set(t.strip().upper() for t in accepted_tray_ids if t and t.strip())
    accepted_trays = []
    rejected_trays = []

    for tray in active_trays:
        tid = tray.get('tray_id', '')
        if tid in accepted_set:
            accepted_trays.append(tray)
        else:
            rejected_trays.append(tray)

    return accepted_trays, rejected_trays

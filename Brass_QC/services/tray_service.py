"""
Brass QC Tray Service — tray resolution, allocation, slot computation.

All tray-related logic lives here.
Views and submission_service call these functions.

Rule: No HTTP layer here. Pure data functions.
"""

import logging

from modelmasterapp.models import TotalStockModel, TrayId
from InputScreening.models import IPTrayId

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tray Resolution — single source of truth
# ─────────────────────────────────────────────────────────────────────────────

def resolve_lot_trays(lot_id):
    """
    Shared tray resolver — single source of truth for tray data.

    Returns: (tray_data_list, source_name, total_qty)

    Priority order:
      0. IQFTrayId         — IQF-returned lots (send_brass_qc=True)
      1. BrassTrayId       — Brass QC's own table
      1.5 IPTrayId         — Input Screening processed tray data
      2. TrayId            — Global tray table fallback
      2.5 BrassAuditTrayId — Brass Audit return fallback
      3. AcceptedStore     — Last-resort fallback
    """
    from ..models import BrassTrayId, Brass_Qc_Accepted_TrayID_Store
    from BrassAudit.models import BrassAuditTrayId
    from InputScreening.models import IS_PartialAcceptLot
    from BrassAudit.models import BrassAudit_PartialAcceptLot

    tray_data = []
    source = "BrassTrayId"

    # Detect IQF-returned lots (send_brass_qc=True) — prioritize IQFTrayId
    is_iqf = False
    try:
        stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
        is_iqf = bool(stock and stock.send_brass_qc)
    except Exception:
        stock = None
        is_iqf = False

    # ─────────────────────────────────────────────────────────────────────
    # Step 0.3 (HIGHEST PRIORITY for partial children) — IS_PartialAcceptLot
    # ─────────────────────────────────────────────────────────────────────
    # When Input Screening did a partial accept, the accept child holds the
    # IMMUTABLE truth of which trays/qtys belong to this lot in Brass QC.
    # We must NOT fall through to BrassTrayId/IPTrayId/TrayId — those still
    # carry the parent's full pre-split tray rows (e.g. 5 trays / 80 qty)
    # and would wrongly overwrite the real 4 trays / 51 qty snapshot.
    #
    # Match rules:
    #   - lot_id is the IS accept child's new_lot_id, OR
    #   - lot_id is the parent_lot_id AND no Brass QC submission has run yet
    #     for this parent (parent stock still flagged few_cases_accepted_Ip_stock).
    if not tray_data and not is_iqf:
        is_pa = IS_PartialAcceptLot.objects.filter(new_lot_id=lot_id).first()
        if not is_pa and stock and getattr(stock, 'few_cases_accepted_Ip_stock', False):
            is_pa = (
                IS_PartialAcceptLot.objects
                .filter(parent_lot_id=lot_id)
                .order_by('-created_at')
                .first()
            )
        if is_pa and is_pa.trays_snapshot:
            source = "IS_PartialAcceptLot"
            tray_data = [
                {
                    "tray_id": t.get("tray_id"),
                    "qty": int(t.get("qty", 0) or 0),
                    "is_rejected": False,
                    "is_top": bool(t.get("top_tray", False)),
                    "is_delinked": False,
                }
                for t in (is_pa.trays_snapshot or [])
                if t.get("tray_id")
            ]
            logger.info(
                f"[resolve_lot_trays] IS partial accept snapshot for {lot_id}: "
                f"child={is_pa.new_lot_id}, trays={len(tray_data)}"
            )

    # ─────────────────────────────────────────────────────────────────────
    # Step 0.4 — BrassAudit_PartialAcceptLot (mirrors Step 0.3 for BA splits)
    # ─────────────────────────────────────────────────────────────────────
    if not tray_data and not is_iqf:
        try:
            ba_pa = BrassAudit_PartialAcceptLot.objects.filter(new_lot_id=lot_id).first()
        except Exception:
            ba_pa = None
        if ba_pa and getattr(ba_pa, 'trays_snapshot', None):
            source = "BrassAudit_PartialAcceptLot"
            tray_data = [
                {
                    "tray_id": t.get("tray_id"),
                    "qty": int(t.get("qty", 0) or 0),
                    "is_rejected": False,
                    "is_top": bool(t.get("top_tray", False)),
                    "is_delinked": False,
                }
                for t in (ba_pa.trays_snapshot or [])
                if t.get("tray_id")
            ]
            logger.info(
                f"[resolve_lot_trays] BA partial accept snapshot for {lot_id}: "
                f"trays={len(tray_data)}"
            )

    # Step 0: IQFTrayId (for IQF-returned lots) — highest priority
    if is_iqf:
        from IQF.models import IQFTrayId as _IQFTrayId
        iqf_trays = _IQFTrayId.objects.filter(
            lot_id=lot_id, rejected_tray=False, delink_tray=False
        ).order_by('-top_tray', 'tray_id')
        if iqf_trays.exists():
            source = "IQFTrayId"
            tray_data = [
                {
                    "tray_id": t.tray_id,
                    "qty": t.tray_quantity or 0,
                    "is_rejected": False,
                    "is_top": t.top_tray,
                    "is_delinked": False,
                }
                for t in iqf_trays
            ]
            logger.info(
                f"[resolve_lot_trays] IQF-returned lot {lot_id}: "
                f"Using IQFTrayId with {len(tray_data)} trays"
            )

    # Step 1: BrassTrayId — skip if IQF found trays above
    if not tray_data:
        trays = BrassTrayId.objects.filter(lot_id=lot_id).order_by('-top_tray', 'tray_id')
        if trays.exists():
            tray_data = [
                {
                    "tray_id": t.tray_id,
                    "qty": t.tray_quantity or 0,
                    "is_rejected": t.rejected_tray,
                    "is_top": t.top_tray,
                    "is_delinked": t.delink_tray,
                }
                for t in trays
            ]

    # Step 1.5: IPTrayId — Input Screening processed tray data (post-IS-rejection)
    if not tray_data:
        ip_trays = IPTrayId.objects.filter(
            lot_id=lot_id, tray_quantity__gt=0, rejected_tray=False, delink_tray=False
        ).order_by('-top_tray', 'tray_id')
        if ip_trays.exists():
            source = "IPTrayId"
            tray_data = [
                {
                    "tray_id": t.tray_id,
                    "qty": t.tray_quantity or 0,
                    "is_rejected": False,
                    "is_top": t.top_tray,
                    "is_delinked": False,
                }
                for t in ip_trays
            ]

    # Step 2: TrayId global table — exclude IS-rejected and delinked
    if not tray_data:
        source = "TrayId"
        trays = TrayId.objects.filter(
            lot_id=lot_id, tray_quantity__gt=0, rejected_tray=False, delink_tray=False
        ).order_by('-top_tray', 'tray_id')
        tray_data = [
            {
                "tray_id": t.tray_id,
                "qty": t.tray_quantity or 0,
                "is_rejected": False,
                "is_top": getattr(t, 'brass_top_tray', False) or t.top_tray,
                "is_delinked": False,
            }
            for t in trays
        ]

    # Step 2.5: BrassAuditTrayId — for lots returned from Brass Audit
    if not tray_data:
        source = "BrassAuditTrayId"
        ba_trays = BrassAuditTrayId.objects.filter(
            lot_id=lot_id, delink_tray=False, rejected_tray=False
        ).order_by('id')
        if ba_trays.exists():
            tray_data = [
                {
                    "tray_id": t.tray_id,
                    "qty": t.tray_quantity or 0,
                    "is_rejected": False,
                    "is_top": bool(t.top_tray),
                    "is_delinked": False,
                }
                for t in ba_trays
            ]

    # Step 3: Final fallback — Accepted Store
    if not tray_data:
        source = "AcceptedStore"
        accepted = Brass_Qc_Accepted_TrayID_Store.objects.filter(lot_id=lot_id)
        tray_data = [
            {
                "tray_id": t.tray_id,
                "qty": t.tray_qty or 0,
                "is_rejected": False,
                "is_top": False,
                "is_delinked": False,
            }
            for t in accepted
        ]

    total_qty = sum(
        t['qty'] for t in tray_data
        if not t.get('is_delinked') and not t.get('is_rejected')
    )

    # Compute backend-driven status for each tray
    for t in tray_data:
        if t.get('is_delinked'):
            t['status'] = 'DELINK'
        elif t.get('is_rejected') and t.get('is_top'):
            t['status'] = 'REJECT_TOP'
        elif t.get('is_rejected'):
            t['status'] = 'REJECT'
        elif t.get('is_top'):
            t['status'] = 'ACCEPT_TOP'
        else:
            t['status'] = 'ACCEPT'

    return tray_data, source, total_qty


def adjust_total_qty_for_is_partial(lot_id, source, stock, total_qty):
    """
    Adjusts total_qty when IS did a partial rejection.
    Original tray quantities are not reduced by IS — we adjust here.

    Skip when source=IPTrayId — those qtys are already post-IS adjusted.

    Returns adjusted total_qty.
    """
    from InputScreening.models import IP_Rejection_ReasonStore
    # Snapshots are already authoritative — do not re-adjust.
    if source in ("IPTrayId", "IS_PartialAcceptLot", "BrassAudit_PartialAcceptLot"):
        return total_qty
    if not getattr(stock, 'few_cases_accepted_Ip_stock', False):
        return total_qty

    _is_rej_store = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
    _is_rej_qty = (
        _is_rej_store.total_rejection_quantity
        if _is_rej_store and _is_rej_store.total_rejection_quantity
        else 0
    )
    _ip_acc_qty = stock.total_IP_accpeted_quantity or 0
    if _ip_acc_qty > 0:
        return max(_ip_acc_qty - _is_rej_qty, 0)
    elif _is_rej_qty > 0:
        return max(total_qty - _is_rej_qty, 0)
    return total_qty


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

def compute_reuse_trays(trays, reject_qty):
    """
    Deterministic tray reuse logic.

    Only trays that become ZERO after rejection allocation are eligible for reuse.
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
    remaining_reject = reject_qty

    for tray in trays_sorted:
        tray_qty = tray["qty"]
        if remaining_reject <= 0:
            updated_trays.append({**tray, "remaining_qty": tray_qty})
            continue
        if remaining_reject >= tray_qty:
            remaining_reject -= tray_qty
            updated_trays.append({
                **tray,
                "used_qty": tray_qty,
                "remaining_qty": 0,
                "status": "REJECT_FULL",
            })
            reuse_trays.append(tray["tray_id"])
        else:
            updated_trays.append({
                **tray,
                "used_qty": remaining_reject,
                "remaining_qty": tray_qty - remaining_reject,
                "status": "REJECT_PARTIAL",
            })
            remaining_reject = 0

    return {"reuse_trays": reuse_trays, "updated_trays": updated_trays}


# ─────────────────────────────────────────────────────────────────────────────
# Tray segregation (for PARTIAL and PROCESS actions)
# ─────────────────────────────────────────────────────────────────────────────

def segregate_trays_for_partial(active_trays, rejected_tray_ids, rejected_qty):
    """
    Splits active trays into accepted_trays and rejected_trays for PARTIAL submission.

    If rejected_tray_ids provided: user-driven. Validates and separates.
    If no rejected_tray_ids: auto-segregation (top tray first).

    Returns: (accepted_trays, rejected_trays, error_str_or_None)
    """
    accepted_trays = []
    rejected_trays = []

    if rejected_tray_ids:
        active_tray_map = {t["tray_id"]: t for t in active_trays}
        invalid_ids = [tid for tid in rejected_tray_ids if tid not in active_tray_map]
        if invalid_ids:
            return [], [], f"Invalid rejected tray IDs: {invalid_ids}"

        for t in active_trays:
            if t["tray_id"] in rejected_tray_ids:
                rejected_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
            else:
                accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
    else:
        # Auto-segregation: top tray first into reject, then remaining
        remaining_reject = rejected_qty
        sorted_trays = sorted(active_trays, key=lambda t: (not t["is_top"]))

        for t in sorted_trays:
            if remaining_reject <= 0:
                accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
            elif remaining_reject >= t["qty"]:
                rejected_trays.append({"tray_id": t["tray_id"], "qty": t["qty"], "is_top": t["is_top"]})
                remaining_reject -= t["qty"]
            else:
                rejected_trays.append({"tray_id": t["tray_id"], "qty": remaining_reject, "is_top": t["is_top"]})
                accepted_trays.append({"tray_id": t["tray_id"], "qty": t["qty"] - remaining_reject, "is_top": False})
                remaining_reject = 0

    return accepted_trays, rejected_trays, None

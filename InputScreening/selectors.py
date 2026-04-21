"""Input Screening – read-side selectors.

All heavy ORM read queries used by Input Screening views live here so the
views stay thin. Behaviour is intentionally identical to the previous
inline implementations – the same fields are annotated and the same
filters applied. The only differences are:

* Subqueries are built once and reused.
* ``select_related`` is added for FK joins to avoid N+1 hits during
  template rendering / row enrichment.
* The list of ``.values(...)`` columns lives in a single constant.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.db.models import Exists, F, OuterRef, Q, QuerySet, Subquery

logger = logging.getLogger(__name__)

# Imported lazily inside functions to avoid heavy import-time fan-out.

PICK_TABLE_COLUMNS = (
    "batch_id",
    "date_time",
    "model_stock_no__model_no",
    "plating_color",
    "polish_finish",
    "version__version_name",
    "vendor_internal",
    "location__location_name",
    "no_of_trays",
    "tray_type",
    "total_batch_quantity",
    "tray_capacity",
    "Moved_to_D_Picker",
    "last_process_module",
    "next_process_module",
    "Draft_Saved",
    "wiping_required",
    "stock_lot_id",
    "ip_person_qty_verified",
    "accepted_Ip_stock",
    "rejected_ip_stock",
    "few_cases_accepted_Ip_stock",
    "accepted_tray_scan_status",
    "IP_pick_remarks",
    "dp_pick_remarks",
    "ip_onhold_picking",
    "created_at",
    "plating_stk_no",
    "polishing_stk_no",
    "category",
    "version__version_internal",
    "total_ip_accepted_quantity",
    "ip_hold_lot",
    "ip_holding_reason",
    "ip_release_lot",
    "ip_release_reason",
    "tray_verify",
    "lot_rejected_comment",
    "draft_tray_verify",
    "has_draft",  # ✅ Added for draft indicator
)

def _latest(field: str):
    """Return a Subquery that pulls ``field`` from the most recent
    ``TotalStockModel`` row for the outer ``ModelMasterCreation``.
    """
    from modelmasterapp.models import TotalStockModel

    return Subquery(
        TotalStockModel.objects.filter(batch_id=OuterRef("pk"))
        .order_by("-id")
        .values(field)[:1]
    )

def pick_table_queryset() -> QuerySet:
    """Build the queryset that powers the Input Screening Pick Table.

    Mirrors the exact filter / annotate / exclude / order chain of the
    legacy view so the page contents are unchanged.
    
    **ERR3 FIX**: Excludes submitted lots (those in InputScreening_Submitted).
    Once a lot is submitted, it moves to the appropriate Completed/Reject table.
    
    **DRAFT SUPPORT**: Lots with active drafts (Draft_Saved=True, is_submitted=False)
    remain in Pick Table so users can continue work. Only final submit removes them.
    """
    from modelmasterapp.models import ModelMasterCreation, TotalStockModel
    from .models import IP_Rejection_ReasonStore, InputScreening_Submitted

    tray_scan_exists = Exists(TotalStockModel.objects.filter(batch_id=OuterRef("pk")))
    
    # Check if this lot_id has been FINALIZED (is_submitted=True)
    # Draft lots (Draft_Saved=True, is_submitted=False) should NOT be excluded
    submitted_lots = Exists(
        InputScreening_Submitted.objects.filter(
            lot_id=OuterRef("stock_lot_id"),
            is_active=True,
            is_submitted=True  # ✅ Only exclude finalized submissions
        )
    )
    
    # Check if this lot has an active draft
    has_draft = Exists(
        InputScreening_Submitted.objects.filter(
            lot_id=OuterRef("stock_lot_id"),
            is_active=True,
            Draft_Saved=True,
            is_submitted=False
        )
    )

    qs = (
        ModelMasterCreation.objects.select_related(
            "model_stock_no",
            "version",
            "location",
        )
        .filter(total_batch_quantity__gt=0)
        .annotate(
            last_process_module=_latest("last_process_module"),
            next_process_module=_latest("next_process_module"),
            wiping_required=F("model_stock_no__wiping_required"),
            stock_lot_id=_latest("lot_id"),
            ip_person_qty_verified=_latest("ip_person_qty_verified"),
            lot_rejected_comment=Subquery(
                IP_Rejection_ReasonStore.objects.filter(
                    lot_id=OuterRef("stock_lot_id")
                ).values("lot_rejected_comment")[:1]
            ),
            accepted_Ip_stock=_latest("accepted_Ip_stock"),
            accepted_tray_scan_status=_latest("accepted_tray_scan_status"),
            rejected_ip_stock=_latest("rejected_ip_stock"),
            few_cases_accepted_Ip_stock=_latest("few_cases_accepted_Ip_stock"),
            ip_onhold_picking=_latest("ip_onhold_picking"),
            tray_verify=_latest("tray_verify"),
            draft_tray_verify=_latest("draft_tray_verify"),
            tray_scan_exists=tray_scan_exists,
            IP_pick_remarks=_latest("IP_pick_remarks"),
            created_at=_latest("created_at"),
            total_ip_accepted_quantity=_latest("total_IP_accpeted_quantity"),
            ip_hold_lot=_latest("ip_hold_lot"),
            ip_holding_reason=_latest("ip_holding_reason"),
            ip_release_lot=_latest("ip_release_lot"),
            ip_release_reason=_latest("ip_release_reason"),
            remove_lot=_latest("remove_lot"),
            submitted=submitted_lots,
            has_draft=has_draft,  # ✅ Indicate if lot has active draft
        )
        .filter(tray_scan_exists=True, Moved_to_D_Picker=True)
        .exclude(
            Q(accepted_Ip_stock=True)
            | Q(accepted_tray_scan_status=True)
            | Q(rejected_ip_stock=True)
            | Q(remove_lot=True)
            | Q(submitted=True)  # ERR3: Exclude submitted lots
        )
        .order_by("-created_at")
    )
    return qs


# ─────────────────────────────────────────────────────────────────────────────
# REJECT MODAL — LOT + TRAY CONTEXT QUERY
# ─────────────────────────────────────────────────────────────────────────────

def get_lot_tray_context(lot_id: str, lock: bool = False) -> Dict[str, Any]:
    """Fetch all tray and lot metadata required for the reject modal and
    allocation engine.

    Args:
        lot_id: Lot ID string (stock_lot_id on ModelMasterCreation).
        lock:   When True, applies ``select_for_update()`` on DPTrayId_History
                rows to prevent concurrent allocation races during final submit.

    Returns:
        {
            found: bool,
            lot_qty: int,
            tray_type: str|None,
            tray_capacity: int,
            active_trays: [{tray_id, qty}],
            batch_id: str|None,
            model_no: str|None,
            plating_stk_no: str|None,
        }
    """
    from DayPlanning.models import DPTrayId_History
    from modelmasterapp.models import ModelMasterCreation, TotalStockModel

    # ``lot_id`` arriving here is the value stored on TotalStockModel.lot_id
    # (the same value rendered as ``data-stock-lot-id`` in the pick table).
    # Resolve to the parent ModelMasterCreation row via the FK on TotalStockModel.
    ts_row = (
        TotalStockModel.objects.filter(lot_id=lot_id)
        .only("batch_id")
        .first()
    )
    if not ts_row or not ts_row.batch_id_id:
        return {"found": False}

    mmc = (
        ModelMasterCreation.objects.filter(pk=ts_row.batch_id_id)
        .select_related("model_stock_no")
        .only(
            "batch_id",
            "total_batch_quantity",
            "tray_capacity",
            "tray_type",
            "plating_stk_no",
            "model_stock_no__model_no",
        )
        .first()
    )

    if not mmc:
        return {"found": False}

    tray_qs = DPTrayId_History.objects.filter(lot_id=lot_id, delink_tray=False)
    if lock:
        tray_qs = tray_qs.select_for_update()

    active_trays: List[Dict[str, Any]] = [
        {
            "tray_id": t["tray_id"],
            "qty": t["tray_quantity"] or 0,
            "top_tray": bool(t.get("top_tray")),
        }
        for t in tray_qs.order_by("id").values(
            "tray_id", "tray_quantity", "top_tray"
        )
    ]

    capacity = (
        mmc.tray_capacity
        or next((t["qty"] for t in active_trays if t["qty"] > 0), 16)
    )
    tray_type_val: Optional[str] = None
    if active_trays:
        first_tray = (
            DPTrayId_History.objects.filter(lot_id=lot_id, delink_tray=False)
            .only("tray_type")
            .first()
        )
        tray_type_val = first_tray.tray_type if first_tray else None

    return {
        "found": True,
        "lot_qty": mmc.total_batch_quantity or 0,
        "tray_type": tray_type_val,
        "tray_capacity": capacity,
        "active_trays": active_trays,
        "batch_id": str(mmc.batch_id) if mmc.batch_id else None,
        "model_no": (
            mmc.model_stock_no.model_no if mmc.model_stock_no_id else None
        ),
        "plating_stk_no": mmc.plating_stk_no,
    }

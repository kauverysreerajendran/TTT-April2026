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

from django.db.models import Exists, F, OuterRef, Q, QuerySet, Subquery

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
    """
    from modelmasterapp.models import ModelMasterCreation, TotalStockModel
    from .models import IP_Rejection_ReasonStore

    tray_scan_exists = Exists(TotalStockModel.objects.filter(batch_id=OuterRef("pk")))

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
        )
        .filter(tray_scan_exists=True, Moved_to_D_Picker=True)
        .exclude(
            Q(accepted_Ip_stock=True)
            | Q(accepted_tray_scan_status=True)
            | Q(rejected_ip_stock=True)
            | Q(remove_lot=True)
        )
        .order_by("-created_at")
    )
    return qs


# ---------------------------------------------------------------------------
# Reject-window selectors
# ---------------------------------------------------------------------------


def get_rejection_reasons():
    """Return [(id, code, reason), ...] used by the IS reject modal.

    Sorted by ``rejection_reason_id`` so the modal renders deterministically
    (R01, R02, ...). Read-only — no side effects.
    """
    from .models import IP_Rejection_Table

    return list(
        IP_Rejection_Table.objects
        .all()
        .order_by("rejection_reason_id")
        .values("id", "rejection_reason_id", "rejection_reason")
    )


def get_lot_reject_context(lot_id: str):
    """Return lot meta required to drive the reject modal header + allocator.

    All values are read-only / cheap aggregates so this is safe to call
    on every modal open. Returns ``None`` if the lot is not found.
    """
    from django.db.models import Sum
    from DayPlanning.models import DPTrayId_History
    from modelmasterapp.models import ModelMasterCreation, TotalStockModel

    stock = (
        TotalStockModel.objects
        .select_related("batch_id")
        .filter(lot_id=lot_id)
        .first()
    )
    if not stock:
        return None

    batch = stock.batch_id
    tray_capacity = (batch.tray_capacity if batch and batch.tray_capacity else 0) or 0
    tray_type = (batch.tray_type if batch and batch.tray_type else "") or ""

    # Source of truth for picker qty: total IP accepted qty when set,
    # otherwise the batch total. Mirrors legacy IS view behaviour.
    accepted_qty = stock.total_IP_accpeted_quantity or 0
    base_qty = (
        accepted_qty
        if accepted_qty > 0
        else (batch.total_batch_quantity if batch else 0)
    )

    # Total qty actually present in the DP trays for this lot — used as a
    # cap so we never allow more rejection than what the scanner counted.
    dp_qty = (
        DPTrayId_History.objects
        .filter(lot_id=lot_id, delink_tray=False)
        .aggregate(s=Sum("tray_quantity"))["s"]
        or 0
    )
    total_qty = base_qty if base_qty else dp_qty

    plating_stk_no = ""
    model_no = ""
    if batch:
        plating_stk_no = batch.plating_stk_no or ""
        if getattr(batch, "model_stock_no", None):
            model_no = getattr(batch.model_stock_no, "model_no", "") or ""

    return {
        "lot_id": lot_id,
        "batch_id": batch.batch_id if batch else None,
        "model_no": model_no,
        "plating_stk_no": plating_stk_no,
        "tray_type": tray_type,
        "tray_capacity": tray_capacity,
        "total_qty": total_qty,
    }


def get_active_dp_trays(lot_id: str):
    """Return active (non-delinked) DP trays for ``lot_id`` ordered by id.

    Used both for displaying the reusable-tray chip strip in the modal and
    by the allocation algorithm to identify the existing top tray.
    """
    from DayPlanning.models import DPTrayId_History

    return list(
        DPTrayId_History.objects
        .filter(lot_id=lot_id, delink_tray=False)
        .order_by("id")
        .values("tray_id", "tray_quantity", "top_tray")
    )


def get_max_tray_serial(prefix: str) -> int:
    """Return the highest numeric suffix used for tray IDs starting with
    ``prefix`` across the DP and IP tray tables.

    Used by the new-tray-id generator in ``services.py`` so freshly minted
    IDs never collide with existing rows. Returns 0 when the prefix has
    no rows yet.
    """
    from DayPlanning.models import DPTrayId_History
    from .models import IPTrayId

    max_n = 0
    for model in (DPTrayId_History, IPTrayId):
        for tid in model.objects.filter(tray_id__startswith=prefix).values_list(
            "tray_id", flat=True
        ):
            tail = (tid or "")[len(prefix):]
            try:
                n = int(tail)
            except (TypeError, ValueError):
                continue
            if n > max_n:
                max_n = n
    return max_n

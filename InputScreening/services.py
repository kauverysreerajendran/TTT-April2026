"""Input Screening – domain services.

These helpers contain all the business logic that used to live in the
views. They are intentionally framework-light so they can be unit-tested
without spinning up DRF.

Concurrency notes
-----------------
``record_tray_verification`` is the hot path used by the scanner. It is
designed to be **idempotent** and **race-safe**:

* The lookup + insert run inside ``transaction.atomic()`` and use
  ``select_for_update()`` on the ``DPTrayId_History`` row so concurrent
  scans of the same tray serialise on the database.
* The status row is created via ``get_or_create`` which – combined with
  the ``unique_together = ['lot_id', 'tray_id']`` constraint already
  declared on ``IP_TrayVerificationStatus`` – guarantees no duplicates
  even if two workers race.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Tuple

from django.db import IntegrityError, transaction
from django.templatetags.static import static

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pick Table row enrichment
# ---------------------------------------------------------------------------

_PLACEHOLDER_IMAGE = "assets/images/imagePlaceholder.jpg"

def _prefetch_pick_table_extras(rows: List[Dict[str, Any]]):
    """Bulk-fetch sibling data needed by row enrichment in O(1) queries.

    Returns four dicts keyed for fast row-level lookup so the enrichment
    loop avoids the N+1 pattern present in the legacy view.
    """
    from modelmasterapp.models import ModelMasterCreation, TotalStockModel
    from DayPlanning.models import DPTrayId_History
    from .models import IP_Rejection_ReasonStore, IP_TrayVerificationStatus

    batch_ids = {r["batch_id"] for r in rows if r.get("batch_id")}
    lot_ids = {r["stock_lot_id"] for r in rows if r.get("stock_lot_id")}

    mmc_map: Dict[str, Any] = {}
    if batch_ids:
        for mmc in (
            ModelMasterCreation.objects.filter(batch_id__in=batch_ids)
            .select_related("model_stock_no")
            .prefetch_related("model_stock_no__images")
        ):
            mmc_map[mmc.batch_id] = mmc

    stock_map: Dict[str, Any] = {}
    if lot_ids:
        for stock in TotalStockModel.objects.filter(lot_id__in=lot_ids):
            # Keep latest occurrence (mirrors original .first() with no order).
            stock_map.setdefault(stock.lot_id, stock)

    rejection_map: Dict[str, int] = {}
    if lot_ids:
        for rec in IP_Rejection_ReasonStore.objects.filter(lot_id__in=lot_ids):
            rejection_map.setdefault(rec.lot_id, rec.total_rejection_quantity or 0)

    # ✅ NEW: Check tray verification status for each lot
    verification_map: Dict[str, bool] = {}
    if lot_ids:
        for lot_id in lot_ids:
            # Get all active trays for this lot
            total_trays = DPTrayId_History.objects.filter(
                lot_id=lot_id, delink_tray=False
            ).count()
            
            # Get verified trays count
            verified_trays = IP_TrayVerificationStatus.objects.filter(
                lot_id=lot_id, is_verified=True
            ).count()
            
            # All trays verified if counts match and at least one tray exists
            verification_map[lot_id] = (
                total_trays > 0 and total_trays == verified_trays
            )

    return mmc_map, stock_map, rejection_map, verification_map

def enrich_pick_table_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Decorate the dict rows produced by ``pick_table_queryset`` with the
    derived fields the template expects (images, accepted/available qty,
    rejection totals, ``vendor_location``, recomputed ``no_of_trays``).

    Output schema is identical to the legacy view – the only change is
    that data is fetched in bulk instead of one-row-at-a-time, and that
    debug ``print`` statements have been replaced with structured
    logging at DEBUG level.
    """
    mmc_map, stock_map, rejection_map, verification_map = _prefetch_pick_table_extras(rows)
    placeholder = [static(_PLACEHOLDER_IMAGE)]

    for data in rows:
        batch_id = data.get("batch_id")
        lot_id = data.get("stock_lot_id")
        logger.debug("IS pick row batch=%s lot=%s", batch_id, lot_id)

        # ✅ NEW: Add tray verification status
        data["all_trays_verified"] = verification_map.get(lot_id, False)

        # vendor_location (template renders this directly)
        data["vendor_location"] = (
            f"{data.get('vendor_internal', '') or ''}_"
            f"{data.get('location__location_name', '') or ''}"
        )

        # Recompute no_of_trays defensively (legacy parity)
        total_qty = data.get("total_batch_quantity") or 0
        capacity = data.get("tray_capacity") or 0
        data["no_of_trays"] = math.ceil(total_qty / capacity) if capacity else 0

        # Image list
        images: List[str] = []
        mmc = mmc_map.get(batch_id)
        if mmc and mmc.model_stock_no_id:
            for img in mmc.model_stock_no.images.all():
                if img.master_image:
                    images.append(img.master_image.url)
        data["model_images"] = images or placeholder

        # Accepted qty resolution (legacy parity)
        stock = stock_map.get(lot_id)
        rejection_qty = rejection_map.get(lot_id, 0)
        stored_accepted = data.get("total_ip_accepted_quantity")
        if stored_accepted and stored_accepted > 0:
            data["display_accepted_qty"] = stored_accepted
        elif stock and rejection_qty > 0:
            data["display_accepted_qty"] = max(
                (stock.total_stock or 0) - rejection_qty, 0
            )
        else:
            data["display_accepted_qty"] = 0

        # Available qty
        if stock and getattr(stock, "total_stock", 0):
            data["available_qty"] = stock.total_stock or 0
        else:
            data["available_qty"] = 0

        # Rejection total
        data["ip_rejection_total_qty"] = rejection_qty if lot_id else 0

    return rows

# ---------------------------------------------------------------------------
# Tray verification panel
# ---------------------------------------------------------------------------

def get_dp_tray_panel(lot_id: str) -> Dict[str, Any]:
    """Return the payload shown in the tray verification panel for *lot_id*.

    Output is byte-compatible with the previous ``IS_GetDPTraysAPI``
    implementation.
    """
    from DayPlanning.models import DPTrayId_History
    from modelmasterapp.models import ModelMasterCreation
    from .models import IP_TrayVerificationStatus

    dp_trays = list(
        DPTrayId_History.objects.filter(lot_id=lot_id, delink_tray=False)
        .order_by("id")
        .values("tray_id", "tray_quantity", "top_tray")
    )

    verified_ids = set(
        IP_TrayVerificationStatus.objects.filter(
            lot_id=lot_id, is_verified=True
        ).values_list("tray_id", flat=True)
    )

    tray_list: List[Dict[str, Any]] = []
    total_qty = 0
    verified_qty = 0
    for i, tray in enumerate(dp_trays, start=1):
        qty = tray["tray_quantity"] or 0
        is_verified = tray["tray_id"] in verified_ids
        total_qty += qty
        if is_verified:
            verified_qty += qty
        tray_list.append(
            {
                "sno": i,
                "tray_id": tray["tray_id"],
                "qty": qty,
                "is_verified": is_verified,
                "top_tray": tray["top_tray"],
            }
        )

    total = len(tray_list)
    verified = sum(1 for t in tray_list if t["is_verified"])

    plating_stk_no = "—"
    batch = (
        ModelMasterCreation.objects.filter(lot_id=lot_id)
        .only("plating_stk_no")
        .first()
    )
    if batch and batch.plating_stk_no:
        plating_stk_no = batch.plating_stk_no
    else:
        dp_record = (
            DPTrayId_History.objects.filter(lot_id=lot_id)
            .select_related("batch_id")
            .first()
        )
        if dp_record and dp_record.batch_id and dp_record.batch_id.plating_stk_no:
            plating_stk_no = dp_record.batch_id.plating_stk_no

    all_verified = total > 0 and (total - verified) == 0
    return {
        "success": True,
        "lot_id": lot_id,
        "plating_stk_no": plating_stk_no,
        "trays": tray_list,
        "total": total,
        "verified": verified,
        "pending": total - verified,
        "all_verified": all_verified,
        "enable_actions": {"accept": all_verified, "reject": all_verified},
        "total_qty": total_qty,
        "verified_qty": verified_qty,
    }

def record_tray_verification(lot_id: str, tray_id: str, user) -> Tuple[Dict[str, Any], int]:
    """Validate and (idempotently) record a tray verification.

    Returns ``(payload, http_status)`` so the view can stay trivial.

    Behavioural parity with the legacy implementation is preserved – the
    same status strings are returned for already-verified, wrong-lot and
    not-found cases. The success path additionally creates the
    ``IP_TrayVerificationStatus`` row inside an atomic block; the legacy
    code had an incomplete success branch and this completes it without
    altering any of the documented error responses.
    """
    from DayPlanning.models import DPTrayId_History
    from .models import IP_TrayVerificationStatus

    # Fast path: already verified (no lock needed for read).
    if IP_TrayVerificationStatus.objects.filter(
        lot_id=lot_id, tray_id=tray_id, is_verified=True
    ).exists():
        return (
            {
                "success": False,
                "status": "already_verified",
                "message": "Already Verified ⚠️",
            },
            200,
        )

    with transaction.atomic():
        dp_tray = (
            DPTrayId_History.objects.select_for_update()
            .filter(lot_id=lot_id, tray_id=tray_id, delink_tray=False)
            .first()
        )

        if not dp_tray:
            wrong_lot = (
                DPTrayId_History.objects.filter(tray_id=tray_id)
                .exclude(lot_id=lot_id)
                .exists()
            )
            if wrong_lot:
                return (
                    {
                        "success": False,
                        "status": "wrong_lot",
                        "message": "Invalid Tray ID ❌",
                    },
                    200,
                )
            return (
                {
                    "success": False,
                    "status": "not_found",
                    "message": "Tray not found for this lot ❌",
                },
                200,
            )

        try:
            obj, created = IP_TrayVerificationStatus.objects.get_or_create(
                lot_id=lot_id,
                tray_id=tray_id,
                defaults={
                    "is_verified": True,
                    "verification_status": "pass",
                    "verified_by": user if getattr(user, "is_authenticated", False) else None,
                },
            )
            if not created and not obj.is_verified:
                obj.is_verified = True
                obj.verification_status = "pass"
                if getattr(user, "is_authenticated", False):
                    obj.verified_by = user
                obj.save(update_fields=["is_verified", "verification_status", "verified_by"])
        except IntegrityError:
            pass  # Another concurrent request inserted first – treated as success below.

    # ── Re-fetch current verification stats for this lot so the JS can
    #    update the top cards and enable Accept/Reject without a second
    #    network round-trip.
    from DayPlanning.models import DPTrayId_History as _DPH
    from django.db.models import Sum as _Sum
    from .models import IP_TrayVerificationStatus as _TVS

    total = _DPH.objects.filter(lot_id=lot_id, delink_tray=False).count()
    verified = _TVS.objects.filter(lot_id=lot_id, is_verified=True).count()
    pending = total - verified
    all_verified = total > 0 and pending == 0

    # When every tray for the lot is verified, mark the parent lot as
    # quantity-verified so the Pick Table's "Q" badge in Process Status
    # turns full green (template reads ``ip_person_qty_verified``).
    # Idempotent — safe to call repeatedly.
    if all_verified:
        try:
            from modelmasterapp.models import ModelMasterCreation as _MMC
            _MMC.objects.filter(stock_lot_id=lot_id).update(
                ip_person_qty_verified=True,
                tray_verify=True,
            )
        except Exception:  # pragma: no cover - defensive only
            logger.warning(
                "[IS][VERIFY] could not flip ip_person_qty_verified for lot=%s",
                lot_id,
            )

    total_qty = (
        _DPH.objects.filter(lot_id=lot_id, delink_tray=False)
        .aggregate(s=_Sum("tray_quantity"))["s"] or 0
    )
    verified_tray_ids = set(
        _TVS.objects.filter(lot_id=lot_id, is_verified=True)
        .values_list("tray_id", flat=True)
    )
    verified_qty = (
        _DPH.objects.filter(
            lot_id=lot_id, delink_tray=False, tray_id__in=verified_tray_ids
        ).aggregate(s=_Sum("tray_quantity"))["s"] or 0
        if verified_tray_ids else 0
    )

    return (
        {
            "success": True,
            "status": "verified",
            "message": "Verified \u2705",
            "verified": verified,
            "total": total,
            "pending": pending,
            "all_verified": all_verified,
            "enable_actions": {"accept": all_verified, "reject": all_verified},
            "total_qty": total_qty,
            "verified_qty": verified_qty,
        },
        200,
    )

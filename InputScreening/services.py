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

    Returns three dicts keyed for fast row-level lookup so the enrichment
    loop avoids the N+1 pattern present in the legacy view.
    """
    from modelmasterapp.models import ModelMasterCreation, TotalStockModel
    from .models import IP_Rejection_ReasonStore

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

    return mmc_map, stock_map, rejection_map


def enrich_pick_table_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Decorate the dict rows produced by ``pick_table_queryset`` with the
    derived fields the template expects (images, accepted/available qty,
    rejection totals, ``vendor_location``, recomputed ``no_of_trays``).

    Output schema is identical to the legacy view – the only change is
    that data is fetched in bulk instead of one-row-at-a-time, and that
    debug ``print`` statements have been replaced with structured
    logging at DEBUG level.
    """
    mmc_map, stock_map, rejection_map = _prefetch_pick_table_extras(rows)
    placeholder = [static(_PLACEHOLDER_IMAGE)]

    for data in rows:
        batch_id = data.get("batch_id")
        lot_id = data.get("stock_lot_id")
        logger.debug("IS pick row batch=%s lot=%s", batch_id, lot_id)

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


# ---------------------------------------------------------------------------
# Reject window – allocation + submit
# ---------------------------------------------------------------------------


def _compute_slots(qty: int, capacity: int) -> List[Dict[str, Any]]:
    """Split ``qty`` into tray slots of ``capacity``.

    The first slot becomes the *top tray* and carries the remainder so the
    factory operator scans the partially-filled tray first. When ``qty``
    divides evenly, the very first capacity-sized slot is marked top.
    """
    if qty <= 0 or capacity <= 0:
        return []
    full = qty // capacity
    rem = qty % capacity
    slots: List[Dict[str, Any]] = []
    if rem > 0:
        slots.append({"qty": rem, "is_top": True})
        slots.extend({"qty": capacity, "is_top": False} for _ in range(full))
    else:
        slots.append({"qty": capacity, "is_top": True})
        slots.extend({"qty": capacity, "is_top": False} for _ in range(full - 1))
    return slots


def _tray_prefix(tray_type: str) -> str:
    """Map the human ``tray_type`` to the 3-char prefix used for IDs.

    Mirrors the convention used across IS / DP / IQF: ``Jumbo`` → ``JB-``,
    everything else (Normal / blank) → ``NB-``.
    """
    t = (tray_type or "").strip().lower()
    if t.startswith("jumbo"):
        return "JB-"
    return "NB-"


def _next_tray_ids(prefix: str, count: int) -> List[str]:
    """Return ``count`` fresh tray IDs that do not collide with existing
    rows in ``DPTrayId_History`` or ``IPTrayId``.

    The numbering format matches the legacy ``XX-A00###`` style produced
    by ``loading_modelmaster``.
    """
    from .selectors import get_max_tray_serial

    if count <= 0:
        return []
    start = get_max_tray_serial(prefix) + 1
    return [f"{prefix}A{(start + i):05d}" for i in range(count)]


def _allocate_one_side(
    slots: List[Dict[str, Any]],
    *,
    reusable: List[Dict[str, Any]],
    new_prefix: str,
    new_id_offset: int,
    reveal_tray_ids: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """Classify each slot as Reused vs New (no tray-ID auto-assignment).

    By default (``reveal_tray_ids=False``) the returned slots carry an
    **empty** ``tray_id`` — the operator must scan or tap a tray on the
    floor before any ID is bound to a slot. The classification is still
    useful for the UI (badge + colour). Pass ``reveal_tray_ids=True`` for
    legacy behaviour (preview shows the candidate ID).

    The ``new_id_offset`` argument is kept for backward compatibility with
    callers that still want to know how many *new* slots exist (so they
    can keep a monotonic ID counter for downstream allocations).
    """
    if not slots:
        return [], 0

    new_needed = max(0, len(slots) - len(reusable))
    new_ids: List[str] = []
    if reveal_tray_ids and new_needed:
        new_ids = _next_tray_ids(new_prefix, new_needed + new_id_offset)[new_id_offset:]

    out: List[Dict[str, Any]] = []
    reuse_idx = 0
    new_idx = 0
    for slot in slots:
        if reuse_idx < len(reusable):
            r = reusable[reuse_idx]
            reuse_idx += 1
            out.append({
                "tray_id": r["tray_id"] if reveal_tray_ids else "",
                "candidate_tray_id": r["tray_id"],  # backend hint only
                "qty": slot["qty"],
                "is_top": slot["is_top"],
                "source": "Reused",
                "reason_id": slot.get("reason_id"),
                "reason_code": slot.get("reason_code"),
            })
        else:
            tray_id = new_ids[new_idx] if new_idx < len(new_ids) else ""
            new_idx += 1
            out.append({
                "tray_id": tray_id,
                "candidate_tray_id": "",
                "qty": slot["qty"],
                "is_top": slot["is_top"],
                "source": "New",
                "reason_id": slot.get("reason_id"),
                "reason_code": slot.get("reason_code"),
            })
    return out, new_idx


def compute_reject_allocation(
    lot_id: str,
    reject_qty: int,
    reasons: Dict[int, int] | None = None,
) -> Dict[str, Any]:
    """Phased reject + accept allocation driven by **physical stock**.

    Algorithm (manufacturing-correct):

    * **Phase A** – Read active lot trays ordered ``top_tray DESC, id ASC``.
    * **Phase B** – Sequentially pull ``reject_qty`` from those trays
      (a tray that is partially consumed splits into a reject portion
      and an accept remainder).
    * **Phase C** – Build ``reject_physical_stock`` and
      ``accept_physical_stock`` from that split.
    * **Phase D** – A tray is *reusable* only when fully drained by the
      reject pull (qty became zero). Partially-consumed and untouched
      trays belong to the accept side and **cannot** be reused for
      reject.
    * **Phase E** – Map operator-supplied ``reasons`` into reject slots.
      Per business rule **R01 will not share a tray with R02** – every
      slot carries exactly one ``reason_id``. Reusable existing trays
      (Phase D) are consumed first; any shortfall becomes "New Tray
      required" so the operator scans a fresh ID on the floor.
    * **Phase F** – Return the structured payload the modal renders.

    The response **never** auto-fills ``tray_id`` for any slot — the
    operator must scan/tap. ``candidate_tray_id`` is provided only as a
    backend hint (drives the chip strip + tap-to-fill UX).
    """
    from .selectors import get_active_dp_trays, get_lot_reject_context

    ctx = get_lot_reject_context(lot_id)
    if ctx is None:
        return {"success": False, "error": "Lot not found"}

    total_qty = ctx["total_qty"]
    capacity = ctx["tray_capacity"]
    if capacity <= 0:
        return {"success": False, "error": "Tray capacity not configured for this lot"}

    if reject_qty < 0 or reject_qty > total_qty:
        return {
            "success": False,
            "error": f"reject_qty must be between 0 and {total_qty}",
        }

    reasons = reasons or {}
    if reasons and sum(reasons.values()) != reject_qty:
        return {
            "success": False,
            "error": "sum of reason quantities must equal reject_qty",
        }

    accept_qty = max(total_qty - reject_qty, 0)

    # ── Phase A: ordered physical trays (top first, then id-asc) ─────
    active = get_active_dp_trays(lot_id)
    active_sorted = sorted(
        active, key=lambda t: (0 if t.get("top_tray") else 1,)
    )  # stable sort preserves id-asc from selector

    # ── Phase B + C: sequential physical split ───────────────────────
    reject_physical: List[Dict[str, Any]] = []
    accept_physical: List[Dict[str, Any]] = []
    rem = reject_qty
    for t in active_sorted:
        tqty = t.get("tray_quantity") or 0
        is_top = bool(t.get("top_tray"))
        tid = t["tray_id"]
        if rem <= 0:
            if tqty > 0:
                accept_physical.append(
                    {"tray_id": tid, "qty": tqty, "is_top": is_top, "partial": False}
                )
        elif rem >= tqty:
            # Whole tray drained → eligible for reuse on the reject side.
            reject_physical.append(
                {"tray_id": tid, "qty": tqty, "is_top": is_top, "consumed": "full"}
            )
            rem -= tqty
        else:
            # Tray splits: rem qty reject, remainder stays on accept side.
            reject_physical.append(
                {"tray_id": tid, "qty": rem, "is_top": is_top, "consumed": "partial"}
            )
            accept_physical.append(
                {
                    "tray_id": tid,
                    "qty": tqty - rem,
                    "is_top": is_top,
                    "partial": True,
                }
            )
            rem = 0

    # ── Phase D: reusable pool = trays fully drained by reject ───────
    reusable_pool = [r["tray_id"] for r in reject_physical if r.get("consumed") == "full"]

    # ── Phase E: reason-segregated reject slots (one reason per tray) ─
    reject_slots: List[Dict[str, Any]] = []
    if reasons:
        from .models import IP_Rejection_Table
        reason_meta = {
            r.id: r for r in IP_Rejection_Table.objects.filter(id__in=reasons.keys())
        }
        for rid in sorted(reasons.keys()):
            qty = reasons[rid]
            if qty <= 0:
                continue
            code = (
                reason_meta[rid].rejection_reason_id if rid in reason_meta else ""
            )
            full, rem_q = divmod(qty, capacity)
            for _ in range(full):
                reject_slots.append({
                    "qty": capacity, "reason_id": rid, "reason_code": code,
                })
            if rem_q:
                reject_slots.append({
                    "qty": rem_q, "reason_id": rid, "reason_code": code,
                })
    else:
        # No per-reason map provided — mirror the physical reject split
        # so the UI still shows the right number of slots.
        for r in reject_physical:
            reject_slots.append({
                "qty": r["qty"], "reason_id": None, "reason_code": "",
            })

    # Assign source classification + candidate hint (NEVER auto-fill tray_id).
    reusable_iter = iter(reusable_pool)
    for slot in reject_slots:
        cand = next(reusable_iter, None)
        slot["tray_id"] = ""              # operator must scan/tap
        slot["candidate_tray_id"] = cand or ""
        slot["source"] = "Reused" if cand else "New"
        slot["is_top"] = False             # TOP badge only on physical accept top

    new_required = max(0, len(reject_slots) - len(reusable_pool))

    # ── Accept slots: physical accept stock keeps original tray IDs. ──
    # Mark TOP on the actual physical top tray that survives (priority:
    # original top tray → first surviving tray). Exactly one TOP badge.
    physical_top_id = None
    for ap in accept_physical:
        if ap.get("is_top"):
            physical_top_id = ap["tray_id"]
            break
    if not physical_top_id and accept_physical:
        physical_top_id = accept_physical[0]["tray_id"]

    accept_slots: List[Dict[str, Any]] = []
    for ap in accept_physical:
        accept_slots.append({
            "tray_id": "",                                   # operator scans
            "candidate_tray_id": ap["tray_id"],
            "qty": ap["qty"],
            "is_top": ap["tray_id"] == physical_top_id,
            "source": "Reused",
            "reason_id": None,
            "reason_code": "",
            "partial": ap.get("partial", False),
        })

    # Delink candidates (separate workflow step on the floor).
    delink_candidates: List[Dict[str, Any]] = []
    try:
        from DayPlanning.models import DPTrayId_History
        delink_candidates = list(
            DPTrayId_History.objects
            .filter(lot_id=lot_id, delink_tray=True)
            .order_by("id")
            .values("tray_id", "tray_quantity")
        )
    except Exception:  # pragma: no cover
        logger.warning("[IS][REJECT] could not load delink candidates for lot=%s", lot_id)

    return {
        "success": True,
        "lot_id": lot_id,
        "model_no": ctx["model_no"],
        "plating_stk_no": ctx["plating_stk_no"],
        "tray_type": ctx["tray_type"],
        "tray_capacity": capacity,
        "total_qty": total_qty,
        "reject_qty": reject_qty,
        "accept_qty": accept_qty,
        # Spec-friendly aliases:
        "reject_total": reject_qty,
        "accept_total": accept_qty,
        "reject_slots": reject_slots,
        "accept_slots": accept_slots,
        "reject_trays": reject_slots,
        "accept_trays": accept_slots,
        "active_trays": [
            {
                "tray_id": t["tray_id"],
                "qty": t.get("tray_quantity") or 0,
                "is_top": bool(t.get("top_tray")),
            }
            for t in active_sorted
        ],
        "reusable_tray_ids": reusable_pool,
        "delink_candidates": delink_candidates,
        "reuse_summary": {
            "reusable_existing": len(reusable_pool),
            "new_required": new_required,
            "delink_available": len(delink_candidates),
        },
        "auto_assign_tray_ids": False,
    }


@transaction.atomic
def submit_partial_reject(payload: Dict[str, Any], user) -> Tuple[Dict[str, Any], int]:
    """Persist the user's reject decision atomically.

    Writes performed (all inside a single transaction):
      * ``IP_Rejection_ReasonStore``  – aggregate row keyed by ``lot_id``.
      * ``IP_Rejected_TrayScan``      – one row per (reason, qty).
      * ``TotalStockModel`` flags     – marks the lot as having a partial
        rejection so the Pick Table / Brass QC selectors react correctly.
    """
    from django.db.models import F
    from modelmasterapp.models import TotalStockModel
    from .models import (
        IP_Rejected_TrayScan,
        IP_Rejection_ReasonStore,
        IP_Rejection_Table,
    )

    lot_id = payload["lot_id"]
    reasons = payload["reasons"]            # {reason_id: qty}
    total_reject = payload["total_reject_qty"]
    remarks = payload["remarks"]
    full_lot = payload["full_lot_rejection"]
    tray_assignments = payload.get("tray_assignments") or []

    # Lock the stock row first to serialise concurrent submits for the
    # same lot (factory worst case: scanner double-tap).
    stock = (
        TotalStockModel.objects
        .select_for_update()
        .filter(lot_id=lot_id)
        .first()
    )
    if not stock:
        return {"success": False, "error": "Lot not found"}, 404

    base_qty = stock.total_IP_accpeted_quantity or (
        stock.batch_id.total_batch_quantity if stock.batch_id else 0
    )
    if total_reject > base_qty:
        return (
            {"success": False, "error": f"reject qty {total_reject} > available {base_qty}"},
            400,
        )

    # Idempotency: refuse duplicate submits for the same lot.
    if IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).exists():
        return {"success": False, "error": "Rejection already recorded for this lot"}, 409

    reason_objs = {
        r.id: r for r in IP_Rejection_Table.objects.filter(id__in=reasons.keys())
    }
    missing = set(reasons.keys()) - set(reason_objs.keys())
    if missing:
        return {"success": False, "error": f"unknown reason_ids: {sorted(missing)}"}, 400

    store = IP_Rejection_ReasonStore.objects.create(
        lot_id=lot_id,
        user=user,
        total_rejection_quantity=total_reject,
        batch_rejection=full_lot,
        lot_rejected_comment=remarks or None,
    )
    store.rejection_reason.set(list(reason_objs.values()))

    # Persist tray scans. Prefer the per-tray ``tray_assignments`` payload
    # (one row per scanned tray, one reason per tray strictly enforced).
    # Fall back to the legacy aggregate (one row per reason, no tray ID)
    # when assignments are not provided so older clients keep working.
    if tray_assignments:
        IP_Rejected_TrayScan.objects.bulk_create([
            IP_Rejected_TrayScan(
                lot_id=lot_id,
                rejected_tray_quantity=str(a["qty"]),
                rejected_tray_id=a["tray_id"],
                rejection_reason=reason_objs[a["reason_id"]],
                user=user,
            )
            for a in tray_assignments
        ])
    else:
        IP_Rejected_TrayScan.objects.bulk_create([
            IP_Rejected_TrayScan(
                lot_id=lot_id,
                rejected_tray_quantity=str(qty),
                rejection_reason=reason_objs[rid],
                user=user,
            )
            for rid, qty in reasons.items()
        ])

    # Update the stock flags so downstream selectors / Brass QC see the
    # correct state. Same field set the legacy view used.
    if full_lot or total_reject >= base_qty:
        stock.rejected_ip_stock = True
        stock.accepted_Ip_stock = False
        stock.few_cases_accepted_Ip_stock = False
    else:
        stock.few_cases_accepted_Ip_stock = True
    stock.ip_onhold_picking = False
    stock.next_process_module = "Brass_QC" if not full_lot else stock.next_process_module
    stock.save()

    logger.info(
        "[IS][REJECT] lot=%s reject=%s reasons=%s full=%s user=%s",
        lot_id, total_reject, list(reasons.keys()), full_lot,
        getattr(user, "username", None),
    )

    return (
        {
            "success": True,
            "lot_id": lot_id,
            "rejected_qty": total_reject,
            "accepted_qty": max(base_qty - total_reject, 0),
            "full_lot_rejection": full_lot,
        },
        200,
    )

"""Input Screening – input validators.

Centralised, side-effect-free helpers for normalising and validating
request payloads. Keeping these out of the views removes duplication and
makes the API surface easier to test.
"""
from __future__ import annotations

from typing import Dict, Tuple


class ValidationError(ValueError):
    """Raised when a request payload fails validation."""


def clean_str(value, max_len: int = 100) -> str:
    """Return a stripped string, defensively coerced.

    Mirrors the existing ``(request.data.get('x') or '').strip()`` pattern
    used throughout the module while clamping length to mitigate
    pathological inputs.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if max_len and len(text) > max_len:
        text = text[:max_len]
    return text


def parse_lot_tray(payload) -> Tuple[str, str]:
    """Extract and validate ``lot_id`` / ``tray_id`` from a request body.

    Returns ``(lot_id, tray_id)``. Raises :class:`ValidationError` if either
    value is empty after trimming.
    """
    lot_id = clean_str(payload.get("lot_id"), max_len=100)
    tray_id = clean_str(payload.get("tray_id"), max_len=100)
    if not lot_id or not tray_id:
        raise ValidationError("lot_id and tray_id are required")
    return lot_id, tray_id


def require_lot_id(value) -> str:
    lot_id = clean_str(value, max_len=100)
    if not lot_id:
        raise ValidationError("lot_id is required")
    return lot_id


# ---------------------------------------------------------------------------
# Reject-window validators
# ---------------------------------------------------------------------------

_MAX_REASONS = 50  # Defensive cap — IS rarely has more than ~12 reasons.


def _coerce_int(value, *, field: str, minimum: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer")
    if n < minimum:
        raise ValidationError(f"{field} must be >= {minimum}")
    return n


def parse_reason_quantities(payload) -> Tuple[Dict[int, int], int]:
    """Validate the ``reasons`` array sent from the reject modal.

    Expected shape::

        {"reasons": [{"reason_id": 7, "qty": 17}, {"reason_id": 8, "qty": 5}]}

    Returns ``({reason_id: qty}, total_reject_qty)``. Reasons with
    ``qty == 0`` are silently dropped — the modal sends every reason row
    so the user can see them all.
    """
    raw = payload.get("reasons")
    if raw is None:
        raise ValidationError("reasons is required")
    if not isinstance(raw, list):
        raise ValidationError("reasons must be a list")
    if len(raw) > _MAX_REASONS:
        raise ValidationError("too many rejection reasons")

    out: Dict[int, int] = {}
    total = 0
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"reasons[{idx}] must be an object")
        rid = _coerce_int(item.get("reason_id"), field=f"reasons[{idx}].reason_id", minimum=1)
        qty = _coerce_int(item.get("qty"), field=f"reasons[{idx}].qty", minimum=0)
        if qty == 0:
            continue
        if rid in out:
            raise ValidationError(f"duplicate reason_id {rid}")
        out[rid] = qty
        total += qty
    return out, total


def parse_reject_allocation_payload(payload) -> Tuple[str, int, Dict[int, int]]:
    """Validate the payload used by the live allocation API.

    Returns ``(lot_id, reject_qty, reasons_map)``. When ``reasons`` is
    omitted from the payload, the map is empty and the backend falls back
    to the single-bucket allocation (no reason segregation).
    """
    lot_id = require_lot_id(payload.get("lot_id"))
    reject_qty = _coerce_int(payload.get("reject_qty"), field="reject_qty", minimum=0)
    reasons: Dict[int, int] = {}
    if payload.get("reasons") is not None:
        reasons, total = parse_reason_quantities(payload)
        if reject_qty == 0 and total > 0:
            reject_qty = total
        elif total and total != reject_qty:
            raise ValidationError(
                "sum of reason quantities must equal reject_qty"
            )
    return lot_id, reject_qty, reasons


def parse_tray_assignments(payload):
    """Validate optional ``tray_assignments`` array sent at submit time.

    Expected shape::

        "tray_assignments": [
            {"tray_id": "NB-A00012", "reason_id": 7, "qty": 17},
            {"tray_id": "NB-A00013", "reason_id": 7, "qty": 25},
            {"tray_id": "NB-A00014", "reason_id": 8, "qty": 5}
        ]

    Enforces the **one-reason-per-tray** business rule: the same
    ``tray_id`` may not appear with two different ``reason_id`` values.
    Returns the cleaned list (empty when omitted).
    """
    raw = payload.get("tray_assignments")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError("tray_assignments must be a list")
    if len(raw) > 200:  # generous defensive cap
        raise ValidationError("too many tray_assignments")

    seen_tray_to_reason: Dict[str, int] = {}
    out = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"tray_assignments[{idx}] must be an object")
        tray_id = clean_str(item.get("tray_id"), max_len=100)
        if not tray_id:
            raise ValidationError(f"tray_assignments[{idx}].tray_id is required")
        rid = _coerce_int(
            item.get("reason_id"),
            field=f"tray_assignments[{idx}].reason_id",
            minimum=1,
        )
        qty = _coerce_int(
            item.get("qty"),
            field=f"tray_assignments[{idx}].qty",
            minimum=1,
        )
        prev = seen_tray_to_reason.get(tray_id)
        if prev is not None and prev != rid:
            raise ValidationError(
                f"tray '{tray_id}' cannot mix reasons "
                f"({prev} and {rid}) — one reason per tray only"
            )
        seen_tray_to_reason[tray_id] = rid
        out.append({"tray_id": tray_id, "reason_id": rid, "qty": qty})
    return out


def parse_reject_submit_payload(payload):
    """Validate the final submit payload sent from the reject modal.

    Expected shape::

        {
            "lot_id": "LID...",
            "reasons": [{"reason_id": 7, "qty": 17}, ...],
            "remarks": "optional",
            "full_lot_rejection": false,
            "tray_assignments": [                        # optional
                {"tray_id": "NB-A00012", "reason_id": 7, "qty": 17}
            ]
        }
    """
    lot_id = require_lot_id(payload.get("lot_id"))
    reasons, total = parse_reason_quantities(payload)
    if total <= 0:
        raise ValidationError("total reject qty must be > 0")
    remarks = clean_str(payload.get("remarks"), max_len=255)
    full_lot = bool(payload.get("full_lot_rejection"))
    if full_lot and not remarks:
        raise ValidationError("remarks are mandatory for full lot rejection")
    tray_assignments = parse_tray_assignments(payload)

    # Cross-check: per-reason tray-assignment totals must match the
    # per-reason qty supplied in ``reasons`` (when assignments provided).
    if tray_assignments:
        per_reason_assigned: Dict[int, int] = {}
        for a in tray_assignments:
            per_reason_assigned[a["reason_id"]] = (
                per_reason_assigned.get(a["reason_id"], 0) + a["qty"]
            )
        for rid, qty in reasons.items():
            assigned = per_reason_assigned.get(rid, 0)
            if assigned and assigned != qty:
                raise ValidationError(
                    f"reason {rid}: assigned tray qty {assigned} "
                    f"!= declared qty {qty}"
                )

    return {
        "lot_id": lot_id,
        "reasons": reasons,
        "total_reject_qty": total,
        "remarks": remarks,
        "full_lot_rejection": full_lot,
        "tray_assignments": tray_assignments,
    }

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


# ─────────────────────────────────────────────────────────────────────────────
# REJECT PAYLOAD VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

def parse_rejection_entries(raw_entries) -> list:
    """Validate and normalise the rejection_entries list from a request body.

    Expected input:
        [{"reason_id": "R01", "reason_text": "SCRATCH", "qty": 10}, ...]

    Returns a list of cleaned dicts.  Raises ``ValidationError`` on any issue.
    """
    if not isinstance(raw_entries, list):
        raise ValidationError("rejection_entries must be a JSON array.")
    if not raw_entries:
        raise ValidationError("rejection_entries cannot be empty.")

    seen_reason_ids: set = set()
    cleaned = []
    for idx, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise ValidationError(
                f"rejection_entries[{idx}] must be an object."
            )

        reason_id = clean_str(entry.get("reason_id"), max_len=20)
        reason_text = clean_str(entry.get("reason_text"), max_len=255)
        qty_raw = entry.get("qty")

        if not reason_id:
            raise ValidationError(
                f"rejection_entries[{idx}]: reason_id is required."
            )
        if reason_id in seen_reason_ids:
            raise ValidationError(
                f"Duplicate reason_id '{reason_id}' in rejection_entries."
            )
        seen_reason_ids.add(reason_id)

        try:
            qty = int(qty_raw)
        except (TypeError, ValueError):
            raise ValidationError(
                f"rejection_entries[{idx}]: qty must be an integer, got {qty_raw!r}."
            )
        if qty <= 0:
            raise ValidationError(
                f"rejection_entries[{idx}]: qty must be > 0, got {qty}."
            )

        cleaned.append(
            {"reason_id": reason_id, "reason_text": reason_text, "qty": qty}
        )

    return cleaned


def parse_delink_count(value) -> int:
    """Parse and validate delink_count from a request body."""
    try:
        count = int(value) if value is not None else 0
    except (TypeError, ValueError):
        raise ValidationError("delink_count must be an integer.")
    if count < 0:
        raise ValidationError("delink_count cannot be negative.")
    return count


def parse_reject_submit_payload(data: dict) -> dict:
    """Parse and validate the full submit payload for partial accept/reject.

    Expected fields:
        lot_id           (str)
        rejection_entries ([{reason_id, reason_text, qty}])
        delink_count     (int, default 0)
        remarks          (str, optional)

    Returns a dict of cleaned values.
    """
    lot_id = clean_str(data.get("lot_id"), max_len=100)
    if not lot_id:
        raise ValidationError("lot_id is required.")

    raw_entries = data.get("rejection_entries")
    entries = parse_rejection_entries(raw_entries)

    delink_count = parse_delink_count(data.get("delink_count", 0))

    remarks = clean_str(data.get("remarks", ""), max_len=500)

    return {
        "lot_id": lot_id,
        "rejection_entries": entries,
        "delink_count": delink_count,
        "remarks": remarks,
    }


def parse_preview_payload(data: dict) -> dict:
    """Parse the live-preview request (same shape as submit minus remarks)."""
    lot_id = clean_str(data.get("lot_id"), max_len=100)
    if not lot_id:
        raise ValidationError("lot_id is required.")

    raw_entries = data.get("rejection_entries", [])
    entries = parse_rejection_entries(raw_entries)

    delink_count = parse_delink_count(data.get("delink_count", 0))

    return {
        "lot_id": lot_id,
        "rejection_entries": entries,
        "delink_count": delink_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL SCAN FLOW VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

_VALID_SLOT_TYPES = {"reject", "delink", "accept"}


def parse_scan_payload(data: dict) -> dict:
    """Validate payload for the per-scan validation endpoint.

    Expected:
        {
            "lot_id": "...",
            "slot_type": "reject" | "delink" | "accept",
            "tray_id": "...",
            "used_tray_ids": ["...", ...]   # optional
        }
    """
    lot_id = clean_str(data.get("lot_id"), max_len=100)
    if not lot_id:
        raise ValidationError("lot_id is required.")

    slot_type = clean_str(data.get("slot_type"), max_len=20).lower()
    if slot_type not in _VALID_SLOT_TYPES:
        raise ValidationError(
            f"slot_type must be one of: {', '.join(sorted(_VALID_SLOT_TYPES))}."
        )

    tray_id = clean_str(data.get("tray_id"), max_len=100)
    if not tray_id:
        raise ValidationError("tray_id is required.")

    raw_used = data.get("used_tray_ids", [])
    if raw_used is None:
        used = []
    elif isinstance(raw_used, list):
        used = [clean_str(t, max_len=100) for t in raw_used if clean_str(t, max_len=100)]
    else:
        raise ValidationError("used_tray_ids must be a list.")

    # Optional – frontend forwards the total reject qty so backend can
    # derive which active trays are physically emptied (drain engine).
    raw_reject_qty = data.get("reject_qty", 0)
    try:
        reject_qty = int(raw_reject_qty or 0)
    except (TypeError, ValueError):
        raise ValidationError("reject_qty must be an integer.")
    if reject_qty < 0:
        raise ValidationError("reject_qty cannot be negative.")

    return {
        "lot_id": lot_id,
        "slot_type": slot_type,
        "tray_id": tray_id,
        "used_tray_ids": used,
        "reject_qty": reject_qty,
    }


def _parse_assignment_list(raw, label: str, allow_reason: bool) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError(f"{label} must be a JSON array.")
    cleaned = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"{label}[{idx}] must be an object.")
        tid = clean_str(item.get("tray_id"), max_len=100)
        if not tid:
            raise ValidationError(f"{label}[{idx}].tray_id is required.")
        entry = {"tray_id": tid}
        if allow_reason:
            rid = clean_str(item.get("reason_id"), max_len=20)
            if rid:
                entry["reason_id"] = rid
        cleaned.append(entry)
    return cleaned


def parse_manual_submit_payload(data: dict) -> dict:
    """Parse the v2 submit payload that carries user-scanned tray IDs.

    Expected:
        {
            "lot_id": "...",
            "rejection_entries": [{reason_id, reason_text, qty}, ...],
            "reject_assignments": [{tray_id, reason_id?}, ...],
            "delink_tray_ids": ["...", ...],
            "accept_assignments": [{tray_id}, ...],
            "remarks": "..."
        }
    """
    lot_id = clean_str(data.get("lot_id"), max_len=100)
    if not lot_id:
        raise ValidationError("lot_id is required.")

    entries = parse_rejection_entries(data.get("rejection_entries"))

    reject_assignments = _parse_assignment_list(
        data.get("reject_assignments"), "reject_assignments", allow_reason=True
    )
    accept_assignments = _parse_assignment_list(
        data.get("accept_assignments"), "accept_assignments", allow_reason=False
    )

    raw_delink = data.get("delink_tray_ids", [])
    if raw_delink is None:
        delink_ids = []
    elif isinstance(raw_delink, list):
        delink_ids = [
            clean_str(t, max_len=100) for t in raw_delink if clean_str(t, max_len=100)
        ]
    else:
        raise ValidationError("delink_tray_ids must be a list.")

    remarks = clean_str(data.get("remarks", ""), max_len=500)

    return {
        "lot_id": lot_id,
        "rejection_entries": entries,
        "reject_assignments": reject_assignments,
        "delink_tray_ids": delink_ids,
        "accept_assignments": accept_assignments,
        "remarks": remarks,
    }







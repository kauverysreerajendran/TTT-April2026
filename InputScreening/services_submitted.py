# ============================================================================
# InputScreening Submission Service – NEW ARCHITECTURE
# ============================================================================
#
# Matches Jig_Loading pattern:
# - InputScreening_Submitted: Parent lot record (SSOT for original lot)
# - IS_PartialAcceptLot: Child lot record for partial accept submissions
# - IS_PartialRejectLot: Child lot record for partial reject submissions
# - IS_AllocationTray: Individual tray records (replaces JSON snapshots)
#
# All lot IDs use the existing LID{YYYYMMDDHHMMSS}{counter} format.
# Each submission is atomic and revokable.
#

from django.db import transaction
from django.utils import timezone
from .models import (
    InputScreening_Submitted,
    IS_PartialAcceptLot,
    IS_PartialRejectLot,
    IS_AllocationTray,
)
import uuid
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# Thread-safe counter for lot ID generation
_lot_id_counter = 0
_lot_id_counter_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────
# LOT ID GENERATION – THREAD-SAFE
# ─────────────────────────────────────────────────────────────────────────

_last_timestamp = None

def generate_lot_id():
    """
    Generate a new lot ID in the existing LID{YYYYMMDDHHMMSS}{counter} format.
    
    Format: LID{YYYYMMDDHHMMSS}{counter:06d}
    Example: LID20260421130738000001
    
    Thread-safe: uses a global lock to ensure uniqueness.
    Counter resets when second changes.
    
    Used for:
    - Partial accept lot IDs
    - Partial reject lot IDs
    - Any new lot needing unique ID
    """
    global _lot_id_counter, _last_timestamp
    
    # Get current timestamp in YYYYMMDDHHMMSS format
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    
    with _lot_id_counter_lock:
        # If this is a new second, reset counter
        if _last_timestamp != timestamp:
            _last_timestamp = timestamp
            _lot_id_counter = 0
        
        # Increment counter for this second
        _lot_id_counter += 1
        counter_val = _lot_id_counter
    
    return f"LID{timestamp}{counter_val:06d}"


def validate_lot_id_unique(lot_id):
    """
    Check if a lot_id is available (not already used).
    Checks both parent and child lot tables.
    
    Returns: True if available, False if already exists
    """
    return (
        not InputScreening_Submitted.objects.filter(lot_id=lot_id).exists()
        and not IS_PartialAcceptLot.objects.filter(new_lot_id=lot_id).exists()
        and not IS_PartialRejectLot.objects.filter(new_lot_id=lot_id).exists()
    )


# ─────────────────────────────────────────────────────────────────────────
# PARENT LOT CREATION – FULL ACCEPT (creates parent record)
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_parent_submission_full_accept(
    parent_lot_id,
    batch_id,
    original_qty,
    plating_stock_no,
    model_no,
    tray_type,
    tray_capacity,
    active_trays_count,
    top_tray_id,
    top_tray_qty,
    created_by,
    remarks=None,
):
    """
    Create parent InputScreening_Submitted record for FULL ACCEPT.
    
    Returns:
        InputScreening_Submitted instance (parent lot record)
    """
    record = InputScreening_Submitted(
        lot_id=parent_lot_id,
        batch_id=batch_id,
        module_name="Input Screening",
        
        plating_stock_no=plating_stock_no,
        model_no=model_no,
        tray_type=tray_type,
        tray_capacity=tray_capacity,
        
        original_lot_qty=original_qty,
        active_trays_count=active_trays_count,
        top_tray_id=top_tray_id,
        top_tray_qty=top_tray_qty,
        has_top_tray=bool(top_tray_id),
        
        is_full_accept=True,
        is_partial_accept=False,
        is_partial_reject=False,
        is_full_reject=False,
        
        is_active=True,
        is_revoked=False,
        
        Draft_Saved=False,
        is_submitted=True,
        submitted_at=timezone.now(),
        
        remarks=remarks,
        created_by=created_by,
    )
    
    record.save()
    logger.info(f"✅ Created parent submission (FULL ACCEPT): {parent_lot_id}")
    
    return record


# ─────────────────────────────────────────────────────────────────────────
# FULL ACCEPT CHILD LOT CREATION
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_full_accept_child_lot(
    parent_lot_id,
    parent_batch_id,
    original_qty,
    all_trays,
    created_by,
    remarks=None,
):
    """
    Create IS_PartialAcceptLot record for FULL ACCEPT.
    
    Copies parent lot info and ALL trays as-is to child lot.
    All trays are marked as accepted.
    
    Args:
        parent_lot_id: Original parent lot ID
        parent_batch_id: Original batch ID  
        original_qty: Total original quantity (all accepted)
        all_trays: List of all trays from parent: 
                   [{"tray_id": "...", "qty": N, "top_tray": False, "original_qty": N}, ...]
        created_by: User object
        remarks: Optional remarks
        
    Returns:
        (IS_PartialAcceptLot instance, new_lot_id)
    """
    # Generate new lot ID for this full accept submission
    new_lot_id = generate_lot_id()
    
    # Get parent submission record
    parent_submission = InputScreening_Submitted.objects.get(
        lot_id=parent_lot_id, batch_id=parent_batch_id
    )
    
    # Create full accept lot record (as child lot in IS_PartialAcceptLot)
    accept_lot = IS_PartialAcceptLot(
        new_lot_id=new_lot_id,
        parent_lot_id=parent_lot_id,
        parent_batch_id=parent_batch_id,
        parent_submission=parent_submission,
        accepted_qty=original_qty,  # Full lot is accepted
        accept_trays_count=len(all_trays),
        trays_snapshot=[
            {
                "tray_id": t["tray_id"],
                "qty": t["qty"],
                "top_tray": bool(t.get("top_tray", False)),
                "source": "existing",
            }
            for t in all_trays
        ],
        created_by=created_by,
    )
    accept_lot.save()
    
    # Create individual tray allocations (copy all parent trays as-is)
    for tray_info in all_trays:
        IS_AllocationTray.objects.create(
            accept_lot=accept_lot,
            tray_id=tray_info['tray_id'],
            qty=tray_info['qty'],
            original_qty=tray_info.get('original_qty', tray_info['qty']),
            top_tray=tray_info.get('top_tray', False),
        )
    
    logger.info(f"✅ Created full accept child lot: {new_lot_id} (from {parent_lot_id}, qty={original_qty})")
    
    return accept_lot, new_lot_id


# ─────────────────────────────────────────────────────────────────────────
# PARENT LOT CREATION – FULL REJECT (creates parent record)
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_parent_submission_full_reject(
    parent_lot_id,
    batch_id,
    original_qty,
    plating_stock_no,
    model_no,
    tray_type,
    tray_capacity,
    active_trays_count,
    created_by,
    remarks=None,
):
    """
    Create parent InputScreening_Submitted record for FULL REJECT.
    
    Returns:
        InputScreening_Submitted instance (parent lot record)
    """
    record = InputScreening_Submitted(
        lot_id=parent_lot_id,
        batch_id=batch_id,
        module_name="Input Screening",
        
        plating_stock_no=plating_stock_no,
        model_no=model_no,
        tray_type=tray_type,
        tray_capacity=tray_capacity,
        
        original_lot_qty=original_qty,
        active_trays_count=active_trays_count,
        
        is_full_accept=False,
        is_partial_accept=False,
        is_partial_reject=False,
        is_full_reject=True,
        
        is_active=True,
        is_revoked=False,
        
        Draft_Saved=False,
        is_submitted=True,
        submitted_at=timezone.now(),
        
        remarks=remarks,
        created_by=created_by,
    )
    
    record.save()
    logger.info(f"✅ Created parent submission (FULL REJECT): {parent_lot_id}")
    
    return record


# ─────────────────────────────────────────────────────────────────────────
# FULL REJECT CHILD LOT CREATION
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_full_reject_child_lot(
    parent_lot_id,
    parent_batch_id,
    original_qty,
    all_trays,
    rejection_reasons,
    created_by,
    remarks=None,
):
    """
    Create IS_PartialRejectLot record for FULL REJECT.
    
    Copies parent lot info and ALL trays as-is to child lot.
    All trays are marked as rejected.
    
    Args:
        parent_lot_id: Original parent lot ID
        parent_batch_id: Original batch ID
        original_qty: Total original quantity (all rejected)
        all_trays: List of all trays from parent: 
                   [{"tray_id": "...", "qty": N, "top_tray": False, "original_qty": N}, ...]
        rejection_reasons: Dict of rejection reasons (can be empty for system reject)
        created_by: User object
        remarks: Optional rejection remarks
        
    Returns:
        (IS_PartialRejectLot instance, new_lot_id)
    """
    # Generate new lot ID for this full reject submission
    new_lot_id = generate_lot_id()
    
    # Get parent submission record
    parent_submission = InputScreening_Submitted.objects.get(
        lot_id=parent_lot_id, batch_id=parent_batch_id
    )
    
    # Create full reject lot record (as child lot in IS_PartialRejectLot)
    reject_lot = IS_PartialRejectLot(
        new_lot_id=new_lot_id,
        parent_lot_id=parent_lot_id,
        parent_batch_id=parent_batch_id,
        parent_submission=parent_submission,
        rejected_qty=original_qty,  # Full lot is rejected
        reject_trays_count=len(all_trays),
        rejection_reasons=rejection_reasons or {},
        delink_count=0,  # No delinks for full reject
        trays_snapshot=[
            {
                "tray_id": t["tray_id"],
                "qty": t["qty"],
                "top_tray": bool(t.get("top_tray", False)),
                "source": "existing",
            }
            for t in all_trays
        ],
        remarks=remarks,
        created_by=created_by,
    )
    reject_lot.save()
    
    # Create individual tray allocations (copy all parent trays as-is)
    for tray_info in all_trays:
        IS_AllocationTray.objects.create(
            reject_lot=reject_lot,
            tray_id=tray_info['tray_id'],
            qty=tray_info['qty'],
            original_qty=tray_info.get('original_qty', tray_info['qty']),
            is_delinked=False,  # Not delinked for full reject
            top_tray=tray_info.get('top_tray', False),
        )
    
    logger.info(f"✅ Created full reject child lot: {new_lot_id} (from {parent_lot_id}, qty={original_qty})")
    
    return reject_lot, new_lot_id


# ─────────────────────────────────────────────────────────────────────────
# PARTIAL ACCEPT LOT CREATION
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_partial_accept_submission(
    parent_lot_id,
    parent_batch_id,
    accepted_qty,
    accepted_trays,
    created_by,
):
    """
    Create IS_PartialAcceptLot record with individual tray allocations.
    
    Args:
        parent_lot_id: Original parent lot ID
        parent_batch_id: Original batch ID
        accepted_qty: Total quantity accepted
        accepted_trays: List of dicts: [{"tray_id": "...", "qty": N, "top_tray": False}, ...]
        created_by: User object
        
    Returns:
        (IS_PartialAcceptLot instance, new_lot_id)
    """
    # Generate new lot ID for this partial accept
    new_lot_id = generate_lot_id()
    
    # Get parent submission record
    parent_submission = InputScreening_Submitted.objects.get(
        lot_id=parent_lot_id, batch_id=parent_batch_id
    )
    
    # Create partial accept lot record
    accept_lot = IS_PartialAcceptLot(
        new_lot_id=new_lot_id,
        parent_lot_id=parent_lot_id,
        parent_batch_id=parent_batch_id,
        parent_submission=parent_submission,
        accepted_qty=accepted_qty,
        accept_trays_count=len(accepted_trays),
        created_by=created_by,
    )
    accept_lot.save()
    
    # Create individual tray allocations
    for tray_info in accepted_trays:
        IS_AllocationTray.objects.create(
            accept_lot=accept_lot,
            tray_id=tray_info['tray_id'],
            qty=tray_info['qty'],
            original_qty=tray_info.get('original_qty', 0),
            top_tray=tray_info.get('top_tray', False),
        )
    
    # Update parent to mark partial accept
    parent_submission.is_partial_accept = True
    parent_submission.save(update_fields=['is_partial_accept'])
    
    logger.info(f"✅ Created partial accept lot: {new_lot_id} (from {parent_lot_id}, qty={accepted_qty})")
    
    return accept_lot, new_lot_id


# ─────────────────────────────────────────────────────────────────────────
# PARTIAL REJECT LOT CREATION
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_partial_reject_submission(
    parent_lot_id,
    parent_batch_id,
    rejected_qty,
    rejection_reasons,
    reject_trays,
    delink_count,
    created_by,
    remarks=None,
):
    """
    Create IS_PartialRejectLot record with individual tray allocations and rejection reasons.
    
    Args:
        parent_lot_id: Original parent lot ID
        parent_batch_id: Original batch ID
        rejected_qty: Total quantity rejected
        rejection_reasons: Dict of rejection reasons: {"R01": {"reason": "...", "qty": N}, ...}
        reject_trays: List of dicts: [{"tray_id": "...", "qty": N, "reason_id": "R01", 
                                       "reason_text": "...", "is_delinked": False}, ...]
        delink_count: Number of trays delinked (reused)
        created_by: User object
        remarks: Optional rejection remarks
        
    Returns:
        (IS_PartialRejectLot instance, new_lot_id)
    """
    # Generate new lot ID for this partial reject
    new_lot_id = generate_lot_id()
    
    # Get parent submission record
    parent_submission = InputScreening_Submitted.objects.get(
        lot_id=parent_lot_id, batch_id=parent_batch_id
    )
    
    # Create partial reject lot record
    reject_lot = IS_PartialRejectLot(
        new_lot_id=new_lot_id,
        parent_lot_id=parent_lot_id,
        parent_batch_id=parent_batch_id,
        parent_submission=parent_submission,
        rejected_qty=rejected_qty,
        reject_trays_count=len(reject_trays),
        rejection_reasons=rejection_reasons,
        delink_count=delink_count,
        remarks=remarks,
        created_by=created_by,
    )
    reject_lot.save()
    
    # Create individual tray allocations
    for tray_info in reject_trays:
        IS_AllocationTray.objects.create(
            reject_lot=reject_lot,
            tray_id=tray_info['tray_id'],
            qty=tray_info['qty'],
            original_qty=tray_info.get('original_qty', 0),
            is_delinked=tray_info.get('is_delinked', False),
            rejection_reason_id=tray_info.get('reason_id'),
            rejection_reason_text=tray_info.get('reason_text'),
        )
    
    # Update parent to mark partial reject
    parent_submission.is_partial_reject = True
    parent_submission.save(update_fields=['is_partial_reject'])
    
    logger.info(f"✅ Created partial reject lot: {new_lot_id} (from {parent_lot_id}, qty={rejected_qty})")
    
    return reject_lot, new_lot_id


# ─────────────────────────────────────────────────────────────────────────
# RETRIEVAL HELPERS
# ─────────────────────────────────────────────────────────────────────────

def get_parent_submission(parent_lot_id):
    """Get parent InputScreening_Submitted record."""
    return InputScreening_Submitted.objects.filter(
        lot_id=parent_lot_id, is_active=True
    ).first()


def get_partial_accept_lot(new_lot_id):
    """Get IS_PartialAcceptLot with all related trays."""
    return IS_PartialAcceptLot.objects.prefetch_related(
        'allocation_trays'
    ).filter(new_lot_id=new_lot_id).first()


def get_partial_reject_lot(new_lot_id):
    """Get IS_PartialRejectLot with all related trays."""
    return IS_PartialRejectLot.objects.prefetch_related(
        'allocation_trays'
    ).filter(new_lot_id=new_lot_id).first()


def get_all_accept_child_lots(parent_lot_id):
    """Get all partial accept child lots for a parent."""
    return IS_PartialAcceptLot.objects.filter(
        parent_lot_id=parent_lot_id
    ).prefetch_related('allocation_trays')


def get_all_reject_child_lots(parent_lot_id):
    """Get all partial reject child lots for a parent."""
    return IS_PartialRejectLot.objects.filter(
        parent_lot_id=parent_lot_id
    ).prefetch_related('allocation_trays')


# ─────────────────────────────────────────────────────────────────────────
# TRAY DATA SERIALIZATION
# ─────────────────────────────────────────────────────────────────────────

def get_accept_lot_with_trays_dict(new_lot_id):
    """
    Get accept lot with all tray info serialized as dict.
    
    Returns:
        {
            "new_lot_id": "LID...",
            "parent_lot_id": "stock_lot_id",
            "accepted_qty": 100,
            "accept_trays_count": 2,
            "trays": [
                {"tray_id": "...", "qty": 50, "original_qty": 50, "top_tray": False},
                {...}
            ]
        }
    """
    accept_lot = get_partial_accept_lot(new_lot_id)
    if not accept_lot:
        return None
    
    trays = []
    for tray in accept_lot.allocation_trays.all():
        trays.append({
            "tray_id": tray.tray_id,
            "qty": tray.qty,
            "original_qty": tray.original_qty,
            "top_tray": tray.top_tray,
        })
    
    return {
        "new_lot_id": accept_lot.new_lot_id,
        "parent_lot_id": accept_lot.parent_lot_id,
        "parent_batch_id": accept_lot.parent_batch_id,
        "accepted_qty": accept_lot.accepted_qty,
        "accept_trays_count": accept_lot.accept_trays_count,
        "trays": trays,
    }


def get_reject_lot_with_trays_dict(new_lot_id):
    """
    Get reject lot with all tray info serialized as dict.
    
    Returns:
        {
            "new_lot_id": "LID...",
            "parent_lot_id": "stock_lot_id",
            "rejected_qty": 100,
            "reject_trays_count": 2,
            "rejection_reasons": {...},
            "delink_count": 0,
            "trays": [
                {"tray_id": "...", "qty": 50, "original_qty": 50, "reason_id": "R01", 
                 "is_delinked": False, "top_tray": False},
                {...}
            ]
        }
    """
    reject_lot = get_partial_reject_lot(new_lot_id)
    if not reject_lot:
        return None
    
    trays = []
    for tray in reject_lot.allocation_trays.all():
        trays.append({
            "tray_id": tray.tray_id,
            "qty": tray.qty,
            "original_qty": tray.original_qty,
            "reason_id": tray.rejection_reason_id,
            "reason_text": tray.rejection_reason_text,
            "is_delinked": tray.is_delinked,
            "top_tray": tray.top_tray,
        })
    
    return {
        "new_lot_id": reject_lot.new_lot_id,
        "parent_lot_id": reject_lot.parent_lot_id,
        "parent_batch_id": reject_lot.parent_batch_id,
        "rejected_qty": reject_lot.rejected_qty,
        "reject_trays_count": reject_lot.reject_trays_count,
        "rejection_reasons": reject_lot.rejection_reasons,
        "delink_count": reject_lot.delink_count,
        "trays": trays,
    }


# ─────────────────────────────────────────────────────────────────────────
# AUDIT & REVOCATION
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def revoke_submission(parent_lot_id):
    """
    Revoke a submission and mark as inactive (for audit/rollback).
    Marks parent and all child lots as revoked.
    """
    parent = get_parent_submission(parent_lot_id)
    if not parent:
        logger.warning(f"⚠️ Submission not found: {parent_lot_id}")
        return False
    
    parent.is_revoked = True
    parent.is_active = False
    parent.save(update_fields=['is_revoked', 'is_active'])
    
    # Revoke all child accept lots
    IS_PartialAcceptLot.objects.filter(parent_lot_id=parent_lot_id).update(
        created_at=timezone.now()  # Just mark as touched
    )
    
    # Revoke all child reject lots
    IS_PartialRejectLot.objects.filter(parent_lot_id=parent_lot_id).update(
        created_at=timezone.now()
    )
    
    logger.info(f"🚫 Revoked submission: {parent_lot_id}")
    
    return True


# ─────────────────────────────────────────────────────────────────────────
# QUERY HELPERS FOR DOWNSTREAM MODULES
# ─────────────────────────────────────────────────────────────────────────

def get_lot_for_next_module(lot_id):
    """
    Get lot metadata for downstream module processing.
    Resolves both parent and child lot types.
    
    Returns:
        dict with lot metadata or None if not found
    """
    # Check if it's a parent lot
    parent = InputScreening_Submitted.objects.filter(
        lot_id=lot_id, is_active=True
    ).values(
        'lot_id', 'batch_id', 'original_lot_qty', 'plating_stock_no',
        'model_no', 'tray_type', 'tray_capacity', 'is_full_accept', 'is_full_reject'
    ).first()
    
    if parent:
        parent['lot_type'] = 'parent'
        return parent
    
    # Check if it's a partial accept child lot
    accept_lot = IS_PartialAcceptLot.objects.filter(
        new_lot_id=lot_id
    ).values(
        'new_lot_id', 'parent_lot_id', 'parent_batch_id', 'accepted_qty'
    ).first()
    
    if accept_lot:
        accept_lot['lot_type'] = 'partial_accept'
        accept_lot['lot_qty'] = accept_lot.pop('accepted_qty')
        return accept_lot
    
    # Check if it's a partial reject child lot
    reject_lot = IS_PartialRejectLot.objects.filter(
        new_lot_id=lot_id
    ).values(
        'new_lot_id', 'parent_lot_id', 'parent_batch_id', 'rejected_qty'
    ).first()
    
    if reject_lot:
        reject_lot['lot_type'] = 'partial_reject'
        reject_lot['lot_qty'] = reject_lot.pop('rejected_qty')
        return reject_lot
    
    return None


# ─────────────────────────────────────────────────────────────────────────
# FULL ACCEPT / FULL REJECT ORCHESTRATORS
# ─────────────────────────────────────────────────────────────────────────
#
# These thin wrappers tie together the existing ``create_parent_*`` and
# ``create_*_child_lot`` helpers, update the master ``TotalStockModel``
# flags so the lot moves to the correct downstream table (Brass QC pick
# table for accept, IS Reject table for reject), and return a JSON-ready
# payload for the API layer. All writes happen inside a single atomic
# transaction so an exception leaves the database untouched.
# ─────────────────────────────────────────────────────────────────────────


def _get_full_lot_context(lot_id):
    """Resolve the lot/batch/tray context required by the full-flow services.

    Raises ``ValueError`` when the lot cannot be resolved or has no active
    trays – mirrors the validation done by the partial flow.
    """
    from .selectors import get_lot_tray_context

    ctx = get_lot_tray_context(lot_id, lock=True)
    if not ctx.get("found"):
        raise ValueError(f"Lot {lot_id} not found.")
    if InputScreening_Submitted.objects.filter(
        lot_id=lot_id, is_active=True
    ).exists():
        raise ValueError(f"Lot {lot_id} is already submitted.")
    if not ctx.get("active_trays"):
        raise ValueError(f"Lot {lot_id} has no active trays to submit.")
    return ctx


def _build_all_trays_payload(active_trays):
    """Convert ``get_lot_tray_context`` rows into the dict shape expected
    by ``create_full_accept_child_lot`` / ``create_full_reject_child_lot``.
    """
    return [
        {
            "tray_id": t["tray_id"],
            "qty": t["qty"],
            "original_qty": t["qty"],
            "top_tray": bool(t.get("top_tray")),
        }
        for t in active_trays
    ]


def _pick_top_tray(active_trays):
    for t in active_trays:
        if t.get("top_tray"):
            return t["tray_id"], t["qty"]
    return None, None


@transaction.atomic
def submit_full_accept(lot_id, remarks, user):
    """Persist a FULL ACCEPT submission for ``lot_id``.

    Flow:
      1. Validate / lock the lot context.
      2. Create parent ``InputScreening_Submitted`` record.
      3. Create the child accept lot + per-tray rows.
      4. Flip ``TotalStockModel`` flags so Brass QC picks up the lot.

    Returns a JSON-friendly dict.
    """
    from modelmasterapp.models import TotalStockModel

    ctx = _get_full_lot_context(lot_id)
    active_trays = ctx["active_trays"]
    lot_qty = ctx["lot_qty"]
    top_id, top_qty = _pick_top_tray(active_trays)
    all_trays = _build_all_trays_payload(active_trays)

    parent = create_parent_submission_full_accept(
        parent_lot_id=lot_id,
        batch_id=ctx.get("batch_id"),
        original_qty=lot_qty,
        plating_stock_no=ctx.get("plating_stk_no"),
        model_no=ctx.get("model_no"),
        tray_type=ctx.get("tray_type"),
        tray_capacity=ctx.get("tray_capacity"),
        active_trays_count=len(active_trays),
        top_tray_id=top_id,
        top_tray_qty=top_qty,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        remarks=remarks or None,
    )

    accept_lot, new_lot_id = create_full_accept_child_lot(
        parent_lot_id=lot_id,
        parent_batch_id=ctx.get("batch_id"),
        original_qty=lot_qty,
        all_trays=all_trays,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        remarks=remarks or None,
    )

    # Move the lot to Brass QC pick table.
    TotalStockModel.objects.filter(lot_id=lot_id).update(
        accepted_Ip_stock=True,
        rejected_ip_stock=False,
        few_cases_accepted_Ip_stock=False,
        total_IP_accpeted_quantity=lot_qty,
        accepted_tray_scan_status=True,
        last_process_module="Input Screening",
        next_process_module="Brass QC",
        last_process_date_time=timezone.now(),
    )

    logger.info(
        "[IS][FULL_ACCEPT] lot=%s submission_id=%s qty=%d user=%s",
        lot_id,
        parent.id,
        lot_qty,
        getattr(user, "username", "anonymous"),
    )

    return {
        "success": True,
        "lot_id": lot_id,
        "new_lot_id": new_lot_id,
        "submission_id": parent.id,
        "accepted_qty": lot_qty,
        "accept_trays": len(all_trays),
    }


@transaction.atomic
def submit_full_reject(lot_id, remarks, user):
    """Persist a FULL REJECT submission for ``lot_id``.

    Mirrors :func:`submit_full_accept` but writes a reject child lot and
    flips the master flags so the lot lands in the IS Reject table.
    """
    from modelmasterapp.models import TotalStockModel
    from DayPlanning.models import DPTrayId_History

    if not (remarks or "").strip():
        raise ValueError("Lot rejection remarks are required.")

    ctx = _get_full_lot_context(lot_id)
    active_trays = ctx["active_trays"]
    lot_qty = ctx["lot_qty"]
    all_trays = _build_all_trays_payload(active_trays)

    parent = create_parent_submission_full_reject(
        parent_lot_id=lot_id,
        batch_id=ctx.get("batch_id"),
        original_qty=lot_qty,
        plating_stock_no=ctx.get("plating_stk_no"),
        model_no=ctx.get("model_no"),
        tray_type=ctx.get("tray_type"),
        tray_capacity=ctx.get("tray_capacity"),
        active_trays_count=len(active_trays),
        created_by=user if getattr(user, "is_authenticated", False) else None,
        remarks=remarks.strip(),
    )

    reject_lot, new_lot_id = create_full_reject_child_lot(
        parent_lot_id=lot_id,
        parent_batch_id=ctx.get("batch_id"),
        original_qty=lot_qty,
        all_trays=all_trays,
        rejection_reasons={},
        created_by=user if getattr(user, "is_authenticated", False) else None,
        remarks=remarks.strip(),
    )

    # All trays of the lot are rejected – delink them so downstream
    # modules do not pick them up.
    DPTrayId_History.objects.filter(lot_id=lot_id).update(delink_tray=True)

    # Mark the lot as fully rejected in the master.
    TotalStockModel.objects.filter(lot_id=lot_id).update(
        accepted_Ip_stock=False,
        rejected_ip_stock=True,
        few_cases_accepted_Ip_stock=False,
        total_IP_accpeted_quantity=0,
        last_process_module="Input Screening",
        next_process_module="Input Screening",
        last_process_date_time=timezone.now(),
    )

    logger.info(
        "[IS][FULL_REJECT] lot=%s submission_id=%s qty=%d user=%s",
        lot_id,
        parent.id,
        lot_qty,
        getattr(user, "username", "anonymous"),
    )

    return {
        "success": True,
        "lot_id": lot_id,
        "new_lot_id": new_lot_id,
        "submission_id": parent.id,
        "rejected_qty": lot_qty,
        "reject_trays": len(all_trays),
    }

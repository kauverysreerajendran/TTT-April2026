# ============================================================================
# InputScreening Submission Service
# ============================================================================
#
# Handles all submission logic for InputScreening_Submitted model:
# - Atomic transaction safety (no half-saves)
# - Automatic child lot ID generation for splits
# - Permanent snapshot creation
# - Parent/child lot relationship management
#

from django.db import transaction
from django.utils import timezone
from .models import InputScreening_Submitted
import uuid
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# LOT ID GENERATION
# ─────────────────────────────────────────────────────────────────────────

_lot_id_counter = 0
_lot_id_counter_lock = None

def _init_counter_lock():
    """Initialize counter lock for thread-safe lot ID generation."""
    global _lot_id_counter_lock
    if _lot_id_counter_lock is None:
        import threading
        _lot_id_counter_lock = threading.Lock()

def generate_lot_id():
    """
    Generate a new child lot ID in the same format as existing lot IDs.
    
    Format: LID{YYYYMMDDHHMMSS}{counter:06d}
    Example: LID20260421130738000001
    
    This maintains consistency with the existing lot ID format while ensuring
    uniqueness via a monotonic counter that increments each time this function
    is called (within the same second) and resets when the second changes.
    
    Used for:
    - Child lots created from partial accept
    - Child lots created from partial reject
    - Any lot needing a new unique identifier
    """
    from datetime import datetime
    import threading
    
    _init_counter_lock()
    global _lot_id_counter
    
    # Get current timestamp in YYYYMMDDHHMMSS format
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    
    with _lot_id_counter_lock:
        # If this is a new second, reset counter
        # (check by comparing with previously generated timestamp)
        if not hasattr(generate_lot_id, '_last_timestamp') or generate_lot_id._last_timestamp != timestamp:
            generate_lot_id._last_timestamp = timestamp
            _lot_id_counter = 0
        
        # Increment counter for this second
        _lot_id_counter += 1
        counter_val = _lot_id_counter
    
    return f"LID{timestamp}{counter_val:06d}"


def validate_lot_id_unique(lot_id):
    """
    Check if a lot_id is available (not already used).
    
    Returns: True if available, False if already exists
    """
    return not InputScreening_Submitted.objects.filter(lot_id=lot_id).exists()


# ─────────────────────────────────────────────────────────────────────────
# SUBMISSION CREATION - ATOMIC TRANSACTION SAFE
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def create_full_accept_submission(
    original_lot_id,
    batch_id,
    original_qty,
    plating_stock_no,
    model_no,
    tray_type,
    tray_capacity,
    active_trays_count,
    top_tray_id,
    top_tray_qty,
    all_trays_json,
    created_by,
    remarks=None,
):
    """
    Create a FULL ACCEPT submission.
    
    - No split occurs (is_child_lot=False)
    - Parent lot is fully accepted
    - All trays go to accepted_trays_json
    
    Args:
        original_lot_id: Parent lot ID from ModelmasterCreation
        batch_id: Batch ID
        original_qty: Complete quantity
        plating_stock_no: Plating stock number
        model_no: Model number
        tray_type: Tray type
        tray_capacity: Capacity per tray
        active_trays_count: Number of trays
        top_tray_id: Top tray if exists
        top_tray_qty: Qty in top tray
        all_trays_json: All trays snapshot
        created_by: User object
        remarks: Optional remarks
        
    Returns:
        InputScreening_Submitted instance (saved to DB)
    """
    record = InputScreening_Submitted(
        lot_id=original_lot_id,
        parent_lot_id=None,  # No parent for full accept
        batch_id=batch_id,
        module_name="Input Screening",
        
        plating_stock_no=plating_stock_no,
        model_no=model_no,
        tray_type=tray_type,
        tray_capacity=tray_capacity,
        
        original_lot_qty=original_qty,
        submitted_lot_qty=original_qty,
        accepted_qty=original_qty,
        rejected_qty=0,
        
        active_trays_count=active_trays_count,
        accept_trays_count=active_trays_count,
        reject_trays_count=0,
        
        top_tray_id=top_tray_id,
        top_tray_qty=top_tray_qty,
        has_top_tray=bool(top_tray_id),
        
        remarks=remarks or "",
        
        is_partial_accept=False,
        is_partial_reject=False,
        is_full_accept=True,
        is_full_reject=False,
        
        is_child_lot=False,
        is_active=True,
        is_revoked=False,
        
        created_by=created_by,
        created_at=timezone.now(),
        
        all_trays_json=all_trays_json,
        accepted_trays_json=all_trays_json,  # All trays are accepted
        rejected_trays_json=[],
        rejection_reasons_json={},
        allocation_preview_json={},
        delink_trays_json=[],
    )
    
    record.save()
    logger.info(f"✅ Full Accept submission created: {record.lot_id}")
    return record


@transaction.atomic
def create_full_reject_submission(
    original_lot_id,
    batch_id,
    original_qty,
    plating_stock_no,
    model_no,
    tray_type,
    tray_capacity,
    active_trays_count,
    top_tray_id,
    top_tray_qty,
    rejected_trays_json,
    rejection_reasons_json,
    allocation_preview_json,
    delink_trays_json,
    created_by,
    remarks=None,
):
    """
    Create a FULL REJECT submission.
    
    - No split occurs (is_child_lot=False)
    - Entire lot is rejected with reasons
    - All trays go to rejected_trays_json
    
    Args:
        Same as full_accept but with rejection-specific fields
        
    Returns:
        InputScreening_Submitted instance (saved to DB)
    """
    record = InputScreening_Submitted(
        lot_id=original_lot_id,
        parent_lot_id=None,
        batch_id=batch_id,
        module_name="Input Screening",
        
        plating_stock_no=plating_stock_no,
        model_no=model_no,
        tray_type=tray_type,
        tray_capacity=tray_capacity,
        
        original_lot_qty=original_qty,
        submitted_lot_qty=original_qty,
        accepted_qty=0,
        rejected_qty=original_qty,
        
        active_trays_count=active_trays_count,
        accept_trays_count=0,
        reject_trays_count=active_trays_count,
        
        top_tray_id=top_tray_id,
        top_tray_qty=top_tray_qty,
        has_top_tray=bool(top_tray_id),
        
        remarks=remarks or "",
        
        is_partial_accept=False,
        is_partial_reject=False,
        is_full_accept=False,
        is_full_reject=True,
        
        is_child_lot=False,
        is_active=True,
        is_revoked=False,
        
        created_by=created_by,
        created_at=timezone.now(),
        
        all_trays_json=rejected_trays_json,  # All trays are rejected
        accepted_trays_json=[],
        rejected_trays_json=rejected_trays_json,
        rejection_reasons_json=rejection_reasons_json,
        allocation_preview_json=allocation_preview_json,
        delink_trays_json=delink_trays_json,
    )
    
    record.save()
    logger.info(f"❌ Full Reject submission created: {record.lot_id}")
    return record


@transaction.atomic
def create_partial_split_submission(
    original_lot_id,
    batch_id,
    original_qty,
    plating_stock_no,
    model_no,
    tray_type,
    tray_capacity,
    accept_qty,
    reject_qty,
    accept_trays_json,
    reject_trays_json,
    accept_tray_count,
    reject_tray_count,
    accept_top_tray_id,
    accept_top_tray_qty,
    reject_top_tray_id,
    reject_top_tray_qty,
    rejection_reasons_json,
    allocation_preview_json,
    delink_trays_json,
    created_by,
    remarks=None,
):
    """
    Create PARTIAL ACCEPT + PARTIAL REJECT split submissions.
    
    This creates TWO independent child lots:
    1. Accept child lot (with generated lot_id)
    2. Reject child lot (with generated lot_id)
    
    Both are marked as:
    - is_child_lot=True
    - parent_lot_id=original_lot_id
    - is_active=True (they are the new source of truth)
    
    After split:
    - Parent lot should be REVOKED or marked with remaining balance
    - Future modules only use child lot data
    
    Args:
        original_lot_id: Parent lot ID from submission
        accept_qty: Accepted quantity
        reject_qty: Rejected quantity
        accept_trays_json: Trays holding accepted qty
        reject_trays_json: Trays holding rejected qty
        accept_tray_count: Count of accept trays
        reject_tray_count: Count of reject trays
        (other params similar to full submissions)
        
    Returns:
        tuple: (accept_record, reject_record) both saved to DB
    """
    
    # Generate new unique lot IDs for children
    accept_lot_id = generate_lot_id()
    reject_lot_id = generate_lot_id()
    
    # Ensure uniqueness (should succeed, but defensive)
    max_retries = 3
    for _ in range(max_retries):
        if validate_lot_id_unique(accept_lot_id) and validate_lot_id_unique(reject_lot_id):
            break
        accept_lot_id = generate_lot_id()
        reject_lot_id = generate_lot_id()
    
    # CREATE ACCEPT CHILD LOT
    accept_record = InputScreening_Submitted(
        lot_id=accept_lot_id,
        parent_lot_id=original_lot_id,
        batch_id=batch_id,
        module_name="Input Screening",
        
        plating_stock_no=plating_stock_no,
        model_no=model_no,
        tray_type=tray_type,
        tray_capacity=tray_capacity,
        
        original_lot_qty=original_qty,  # Store original for reference
        submitted_lot_qty=accept_qty,  # Only accepted qty
        accepted_qty=accept_qty,
        rejected_qty=0,
        
        active_trays_count=accept_tray_count,
        accept_trays_count=accept_tray_count,
        reject_trays_count=0,
        
        top_tray_id=accept_top_tray_id,
        top_tray_qty=accept_top_tray_qty,
        has_top_tray=bool(accept_top_tray_id),
        
        remarks=remarks or "",
        
        is_partial_accept=True,
        is_partial_reject=False,
        is_full_accept=False,
        is_full_reject=False,
        
        is_child_lot=True,
        is_active=True,  # Child is active!
        is_revoked=False,
        
        created_by=created_by,
        created_at=timezone.now(),
        
        all_trays_json=accept_trays_json,
        accepted_trays_json=accept_trays_json,
        rejected_trays_json=[],
        rejection_reasons_json={},
        allocation_preview_json=allocation_preview_json,
        delink_trays_json=delink_trays_json,
    )
    accept_record.save()
    logger.info(f"✅ Partial Accept child lot created: {accept_record.lot_id} (parent: {original_lot_id})")
    
    # CREATE REJECT CHILD LOT
    reject_record = InputScreening_Submitted(
        lot_id=reject_lot_id,
        parent_lot_id=original_lot_id,
        batch_id=batch_id,
        module_name="Input Screening",
        
        plating_stock_no=plating_stock_no,
        model_no=model_no,
        tray_type=tray_type,
        tray_capacity=tray_capacity,
        
        original_lot_qty=original_qty,  # Store original for reference
        submitted_lot_qty=reject_qty,  # Only rejected qty
        accepted_qty=0,
        rejected_qty=reject_qty,
        
        active_trays_count=reject_tray_count,
        accept_trays_count=0,
        reject_trays_count=reject_tray_count,
        
        top_tray_id=reject_top_tray_id,
        top_tray_qty=reject_top_tray_qty,
        has_top_tray=bool(reject_top_tray_id),
        
        remarks=remarks or "",
        
        is_partial_accept=False,
        is_partial_reject=True,
        is_full_accept=False,
        is_full_reject=False,
        
        is_child_lot=True,
        is_active=True,  # Child is active!
        is_revoked=False,
        
        created_by=created_by,
        created_at=timezone.now(),
        
        all_trays_json=reject_trays_json,
        accepted_trays_json=[],
        rejected_trays_json=reject_trays_json,
        rejection_reasons_json=rejection_reasons_json,
        allocation_preview_json=allocation_preview_json,
        delink_trays_json=delink_trays_json,
    )
    reject_record.save()
    logger.info(f"❌ Partial Reject child lot created: {reject_record.lot_id} (parent: {original_lot_id})")
    
    return (accept_record, reject_record)


# ─────────────────────────────────────────────────────────────────────────
# RETRIEVAL HELPERS
# ─────────────────────────────────────────────────────────────────────────

def get_active_submission(lot_id):
    """
    Get active submission record for a given lot_id.
    
    Returns:
        InputScreening_Submitted or None
    """
    try:
        return InputScreening_Submitted.objects.get(lot_id=lot_id, is_active=True)
    except InputScreening_Submitted.DoesNotExist:
        return None


def get_all_child_lots(parent_lot_id):
    """
    Get all child lots created from a parent split.
    
    Args:
        parent_lot_id: Original parent lot ID
        
    Returns:
        QuerySet of InputScreening_Submitted (is_child_lot=True)
    """
    return InputScreening_Submitted.objects.filter(
        parent_lot_id=parent_lot_id,
        is_child_lot=True
    ).order_by('created_at')


def get_parent_lot(child_lot_id):
    """
    Get the parent lot for a child lot.
    
    Args:
        child_lot_id: Child lot ID
        
    Returns:
        InputScreening_Submitted or None
    """
    try:
        child = InputScreening_Submitted.objects.get(lot_id=child_lot_id, is_child_lot=True)
        if child.parent_lot_id:
            return get_active_submission(child.parent_lot_id)
    except InputScreening_Submitted.DoesNotExist:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────
# AUDIT & REVOCATION
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def revoke_submission(lot_id, revocation_reason="Manual audit revoke"):
    """
    Revoke a submission (mark as revoked and inactive).
    
    Used for:
    - Audit corrections
    - Erroneous submissions
    - Rollback scenarios
    
    Args:
        lot_id: Lot ID to revoke
        revocation_reason: Reason for revocation (logged)
        
    Returns:
        Updated InputScreening_Submitted or None
    """
    try:
        record = InputScreening_Submitted.objects.get(lot_id=lot_id)
        record.is_revoked = True
        record.is_active = False
        record.save()
        logger.warning(f"🚫 Submission revoked: {lot_id} - Reason: {revocation_reason}")
        return record
    except InputScreening_Submitted.DoesNotExist:
        logger.error(f"Cannot revoke {lot_id}: Not found")
        return None


@transaction.atomic
def activate_child_lot(lot_id):
    """
    Activate a child lot (mark as active).
    
    Used when parent is revoked and child should take over.
    """
    try:
        record = InputScreening_Submitted.objects.get(lot_id=lot_id, is_child_lot=True)
        record.is_active = True
        record.save()
        logger.info(f"✅ Child lot activated: {lot_id}")
        return record
    except InputScreening_Submitted.DoesNotExist:
        logger.error(f"Cannot activate {lot_id}: Not found or not a child lot")
        return None


# ─────────────────────────────────────────────────────────────────────────
# QUERY HELPERS FOR FUTURE MODULES
# ─────────────────────────────────────────────────────────────────────────

def get_lot_for_next_module(lot_id):
    """
    Get the correct lot record to use in next modules.
    
    IMPORTANT: If lot_id is a parent with active children,
    future modules should use the CHILD lot(s), not the parent.
    
    Args:
        lot_id: Any lot ID (parent or child)
        
    Returns:
        InputScreening_Submitted: The active record to use
    """
    record = get_active_submission(lot_id)
    if not record:
        return None
    
    # If this is a parent with active children, return the appropriate child
    if not record.is_child_lot:
        children = get_all_child_lots(lot_id)
        active_children = children.filter(is_active=True)
        
        if active_children.exists():
            # If multiple children, caller must decide which one
            # (typically they'd have different processing paths)
            logger.warning(f"⚠️ Lot {lot_id} has {active_children.count()} active children. Using first child.")
            return active_children.first()
    
    return record


def get_lot_metadata_for_downstream(lot_id):
    """
    Extract metadata that downstream modules need.
    
    Returns dict with:
    - qty (submitted_lot_qty from child or parent)
    - trays (accepted_trays_json or rejected_trays_json)
    - parent_lot_id (for reference)
    - is_child_lot (marker)
    """
    record = get_lot_for_next_module(lot_id)
    if not record:
        return None
    
    return {
        'lot_id': record.lot_id,
        'parent_lot_id': record.parent_lot_id,
        'batch_id': record.batch_id,
        'qty': record.submitted_lot_qty,
        'accepted_qty': record.accepted_qty,
        'rejected_qty': record.rejected_qty,
        'trays': record.accepted_trays_json if record.accepted_qty > 0 else record.rejected_trays_json,
        'all_trays': record.all_trays_json,
        'is_child_lot': record.is_child_lot,
        'submission_type': 'partial_accept' if record.is_partial_accept else (
            'partial_reject' if record.is_partial_reject else (
                'full_accept' if record.is_full_accept else 'full_reject'
            )
        ),
    }


# ─────────────────────────────────────────────────────────────────────────
# COMPREHENSIVE SUBMISSION HANDLER (ERR4 FIX)
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def handle_submission(
    lot_id,
    batch_id,
    submission_type,  # "full_accept" | "full_reject" | "partial"
    original_qty,
    accept_qty=None,
    reject_qty=None,
    plating_stock_no=None,
    model_no=None,
    tray_type=None,
    tray_capacity=None,
    active_trays_count=None,
    accept_trays_count=None,
    reject_trays_count=None,
    top_tray_id=None,
    top_tray_qty=None,
    accept_top_tray_id=None,
    accept_top_tray_qty=None,
    reject_top_tray_id=None,
    reject_top_tray_qty=None,
    all_trays_json=None,
    accept_trays_json=None,
    reject_trays_json=None,
    rejection_reasons_json=None,
    allocation_preview_json=None,
    delink_trays_json=None,
    remarks=None,
    created_by=None,
):
    """
    **ERR4 FIX**: Unified handler for all submission types.
    
    Stores submission to InputScreening_Submitted based on submission type.
    
    Args:
        lot_id: Original lot ID
        submission_type: "full_accept", "full_reject", or "partial"
        Other args vary by submission_type
        
    Returns:
        dict: {"success": True, "lot_ids": [...], "submission_type": "..."}
              or
              {"success": False, "error": "..."}
    """
    try:
        if submission_type == "full_accept":
            record = create_full_accept_submission(
                original_lot_id=lot_id,
                batch_id=batch_id,
                original_qty=original_qty,
                plating_stock_no=plating_stock_no,
                model_no=model_no,
                tray_type=tray_type,
                tray_capacity=tray_capacity,
                active_trays_count=active_trays_count or 0,
                top_tray_id=top_tray_id,
                top_tray_qty=top_tray_qty,
                all_trays_json=all_trays_json or [],
                created_by=created_by,
                remarks=remarks,
            )
            return {
                "success": True,
                "lot_ids": [record.lot_id],
                "submission_type": "full_accept",
                "message": f"✅ Full accept submitted: {record.lot_id}",
            }
        
        elif submission_type == "full_reject":
            record = create_full_reject_submission(
                original_lot_id=lot_id,
                batch_id=batch_id,
                original_qty=original_qty,
                plating_stock_no=plating_stock_no,
                model_no=model_no,
                tray_type=tray_type,
                tray_capacity=tray_capacity,
                active_trays_count=active_trays_count or 0,
                top_tray_id=top_tray_id,
                top_tray_qty=top_tray_qty,
                rejected_trays_json=reject_trays_json or [],
                rejection_reasons_json=rejection_reasons_json or {},
                allocation_preview_json=allocation_preview_json or {},
                delink_trays_json=delink_trays_json or [],
                created_by=created_by,
                remarks=remarks,
            )
            return {
                "success": True,
                "lot_ids": [record.lot_id],
                "submission_type": "full_reject",
                "message": f"❌ Full reject submitted: {record.lot_id}",
            }
        
        elif submission_type == "partial":
            # Partial split creates TWO child lots
            accept_record, reject_record = create_partial_split_submission(
                original_lot_id=lot_id,
                batch_id=batch_id,
                original_qty=original_qty,
                plating_stock_no=plating_stock_no,
                model_no=model_no,
                tray_type=tray_type,
                tray_capacity=tray_capacity,
                accept_qty=accept_qty or 0,
                reject_qty=reject_qty or 0,
                accept_trays_json=accept_trays_json or [],
                reject_trays_json=reject_trays_json or [],
                accept_tray_count=accept_trays_count or 0,
                reject_tray_count=reject_trays_count or 0,
                accept_top_tray_id=accept_top_tray_id,
                accept_top_tray_qty=accept_top_tray_qty,
                reject_top_tray_id=reject_top_tray_id,
                reject_top_tray_qty=reject_top_tray_qty,
                rejection_reasons_json=rejection_reasons_json or {},
                allocation_preview_json=allocation_preview_json or {},
                delink_trays_json=delink_trays_json or [],
                created_by=created_by,
                remarks=remarks,
            )
            return {
                "success": True,
                "lot_ids": [accept_record.lot_id, reject_record.lot_id],
                "submission_type": "partial",
                "accept_lot_id": accept_record.lot_id,
                "reject_lot_id": reject_record.lot_id,
                "message": f"✅ Partial split submitted: Accept {accept_record.lot_id}, Reject {reject_record.lot_id}",
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown submission_type: {submission_type}",
            }
    
    except Exception as exc:
        logger.exception(f"Submission failed for {lot_id}: {exc}")
        return {
            "success": False,
            "error": str(exc),
        }

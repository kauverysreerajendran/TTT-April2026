# InputScreening_Submitted - Usage Examples
#
# Real-world examples of how to use the model and service in your code.
#

# ============================================================================
# EXAMPLE 1: Full Accept Submission
# ============================================================================

def submit_full_accept_example(request, lot_id, batch_id):
    """
    Example of handling full accept submission.
    
    This would typically be called from IS_RejectSubmitAPI or
    an accept modal submission endpoint.
    """
    from InputScreening.services_submitted import create_full_accept_submission
    from DayPlanning.models import DPTrayId_History
    
    # Get lot data from Day Planning trays
    all_trays = list(
        DPTrayId_History.objects
        .filter(lot_id=lot_id, delink_tray=False)
        .values('tray_id', 'tray_quantity', 'top_tray')
    )
    
    # Calculate totals
    total_qty = sum(t['tray_quantity'] for t in all_trays)
    active_count = len(all_trays)
    
    # Find top tray
    top_tray = next((t for t in all_trays if t['top_tray']), None)
    top_tray_id = top_tray['tray_id'] if top_tray else None
    top_tray_qty = top_tray['tray_quantity'] if top_tray else None
    
    # Format trays as snapshot
    all_trays_json = [
        {
            "tray_id": t["tray_id"],
            "qty": t["tray_quantity"],
            "top_tray": t["top_tray"]
        }
        for t in all_trays
    ]
    
    # Get product info from ModelMasterCreation
    from modelmasterapp.models import ModelMasterCreation
    batch = ModelMasterCreation.objects.get(batch_id=batch_id)
    
    # Create permanent submission record
    record = create_full_accept_submission(
        original_lot_id=lot_id,
        batch_id=batch_id,
        original_qty=total_qty,
        plating_stock_no=batch.plating_stk_no,
        model_no=batch.model_stock_no.model_no,
        tray_type=batch.tray_type,
        tray_capacity=batch.tray_capacity,
        active_trays_count=active_count,
        top_tray_id=top_tray_id,
        top_tray_qty=top_tray_qty,
        all_trays_json=all_trays_json,
        created_by=request.user,
        remarks=request.data.get('remarks', ''),
    )
    
    return {
        'success': True,
        'message': f'Full accept submitted for {lot_id}',
        'submission_id': record.lot_id,
        'qty': record.accepted_qty,
    }


# ============================================================================
# EXAMPLE 2: Full Reject with Reasons
# ============================================================================

def submit_full_reject_example(request, lot_id, batch_id):
    """
    Example of full reject submission with rejection reasons.
    """
    from InputScreening.services_submitted import create_full_reject_submission
    from DayPlanning.models import DPTrayId_History
    
    # Get rejection data from request
    rejection_data = request.data.get('rejection_data', {})
    remarks = request.data.get('remarks', '')
    
    # Get all trays
    all_trays = list(
        DPTrayId_History.objects
        .filter(lot_id=lot_id, delink_tray=False)
        .values('tray_id', 'tray_quantity', 'top_tray')
    )
    
    # Format for storage
    rejected_trays_json = [
        {
            "tray_id": t["tray_id"],
            "qty": t["tray_quantity"],
            "top_tray": t["top_tray"]
        }
        for t in all_trays
    ]
    
    total_qty = sum(t['tray_quantity'] for t in all_trays)
    
    # Build rejection reasons map: {"R01": {"reason": "VERSION MIXUP", "qty": 250}, ...}
    from InputScreening.models import IP_Rejection_Table
    rejection_reasons_json = {}
    
    for reason_id, qty in rejection_data.items():
        reason_obj = IP_Rejection_Table.objects.get(id=reason_id)
        rejection_reasons_json[reason_obj.rejection_reason_id] = {
            "reason": reason_obj.rejection_reason,
            "qty": qty,
        }
    
    # Get product info
    from modelmasterapp.models import ModelMasterCreation
    batch = ModelMasterCreation.objects.get(batch_id=batch_id)
    
    # Get delink trays available for reuse
    from IPTrayId.models import IPTrayId
    delink_trays = list(
        IPTrayId.objects
        .filter(delink_tray=True, new_tray=False)
        .values('tray_id', 'tray_quantity')[:10]
    )
    
    delink_trays_json = [
        {"tray_id": t["tray_id"], "qty": t["tray_quantity"]}
        for t in delink_trays
    ]
    
    record = create_full_reject_submission(
        original_lot_id=lot_id,
        batch_id=batch_id,
        original_qty=total_qty,
        plating_stock_no=batch.plating_stk_no,
        model_no=batch.model_stock_no.model_no,
        tray_type=batch.tray_type,
        tray_capacity=batch.tray_capacity,
        active_trays_count=len(all_trays),
        top_tray_id=next((t['tray_id'] for t in all_trays if t['top_tray']), None),
        top_tray_qty=next((t['tray_quantity'] for t in all_trays if t['top_tray']), None),
        rejected_trays_json=rejected_trays_json,
        rejection_reasons_json=rejection_reasons_json,
        allocation_preview_json={},  # Could include complex allocation info
        delink_trays_json=delink_trays_json,
        created_by=request.user,
        remarks=remarks,
    )
    
    return {
        'success': True,
        'message': f'Full reject submitted for {lot_id}',
        'submission_id': record.lot_id,
        'reasons': rejection_reasons_json,
    }


# ============================================================================
# EXAMPLE 3: Partial Accept + Reject (Creates Child Lots)
# ============================================================================

def submit_partial_split_example(request, lot_id, batch_id):
    """
    Example of partial accept + reject submission.
    
    This creates TWO independent child lots:
    - One for accepted qty with accept trays
    - One for rejected qty with reject trays
    """
    from InputScreening.services_submitted import create_partial_split_submission
    from DayPlanning.models import DPTrayId_History
    
    # Get split quantities from request
    allocation_data = request.data.get('allocation', {})
    accept_qty = allocation_data.get('accept_qty', 0)
    reject_qty = allocation_data.get('reject_qty', 0)
    reject_reasons = allocation_data.get('reject_reasons', {})
    
    # Get product info
    from modelmasterapp.models import ModelMasterCreation
    batch = ModelMasterCreation.objects.get(batch_id=batch_id)
    
    # Get all trays (will be split)
    all_trays = list(
        DPTrayId_History.objects
        .filter(lot_id=lot_id, delink_tray=False)
        .values('tray_id', 'tray_quantity', 'top_tray')
    )
    
    # Split trays into accept and reject based on allocation
    accept_trays = allocation_data.get('accept_trays', [])
    reject_trays = allocation_data.get('reject_trays', [])
    
    # Convert to JSON format
    accept_trays_json = [
        {
            "tray_id": t["tray_id"],
            "qty": t["tray_quantity"],
            "top_tray": t.get("top_tray", False)
        }
        for t in accept_trays
    ]
    
    reject_trays_json = [
        {
            "tray_id": t["tray_id"],
            "qty": t["tray_quantity"],
            "top_tray": t.get("top_tray", False)
        }
        for t in reject_trays
    ]
    
    # Build rejection reasons map
    rejection_reasons_json = {}
    from InputScreening.models import IP_Rejection_Table
    for reason_id, qty in reject_reasons.items():
        reason_obj = IP_Rejection_Table.objects.get(id=reason_id)
        rejection_reasons_json[reason_obj.rejection_reason_id] = {
            "reason": reason_obj.rejection_reason,
            "qty": qty,
        }
    
    # Find top trays in each set
    accept_top = next((t for t in accept_trays if t.get("top_tray")), None)
    reject_top = next((t for t in reject_trays if t.get("top_tray")), None)
    
    # Create split submission (ATOMIC)
    accept_record, reject_record = create_partial_split_submission(
        original_lot_id=lot_id,
        batch_id=batch_id,
        original_qty=accept_qty + reject_qty,
        plating_stock_no=batch.plating_stk_no,
        model_no=batch.model_stock_no.model_no,
        tray_type=batch.tray_type,
        tray_capacity=batch.tray_capacity,
        
        accept_qty=accept_qty,
        reject_qty=reject_qty,
        accept_trays_json=accept_trays_json,
        reject_trays_json=reject_trays_json,
        accept_tray_count=len(accept_trays),
        reject_tray_count=len(reject_trays),
        
        accept_top_tray_id=accept_top["tray_id"] if accept_top else None,
        accept_top_tray_qty=accept_top["tray_quantity"] if accept_top else None,
        reject_top_tray_id=reject_top["tray_id"] if reject_top else None,
        reject_top_tray_qty=reject_top["tray_quantity"] if reject_top else None,
        
        rejection_reasons_json=rejection_reasons_json,
        allocation_preview_json=allocation_data.get('preview', {}),
        delink_trays_json=allocation_data.get('delink_trays', []),
        
        created_by=request.user,
        remarks=request.data.get('remarks', ''),
    )
    
    return {
        'success': True,
        'message': f'Partial split submitted for {lot_id}',
        'accept_child_lot': accept_record.lot_id,
        'reject_child_lot': reject_record.lot_id,
        'accept_qty': accept_record.submitted_lot_qty,
        'reject_qty': reject_record.submitted_lot_qty,
        'note': 'Future modules should use child lot IDs, not parent',
    }


# ============================================================================
# EXAMPLE 4: Using Submitted Data in Next Module (e.g., DayPlanning)
# ============================================================================

def get_lot_for_next_stage(lot_id):
    """
    Example: How DayPlanning should get lot data after Input Screening.
    
    IMPORTANT PATTERN:
    - Call get_lot_metadata_for_downstream() FIRST
    - Use the returned lot_id (may be different if split occurred)
    - Use returned qty and trays (from committed snapshot, not live)
    """
    from InputScreening.services_submitted import get_lot_metadata_for_downstream
    
    # Get correct lot data
    metadata = get_lot_metadata_for_downstream(lot_id)
    
    if not metadata:
        raise ValueError(f"Lot {lot_id} not submitted or revoked")
    
    # Extract what we need
    actual_lot_id = metadata['lot_id']  # May differ from input if split
    qty = metadata['qty']  # Submitted qty (not live)
    trays = metadata['trays']  # Submitted trays (snapshot)
    is_child = metadata['is_child_lot']
    submission_type = metadata['submission_type']
    
    print(f"""
    Processing lot: {actual_lot_id}
    Quantity: {qty}
    Trays: {len(trays)}
    Type: {submission_type}
    Is Child Lot: {is_child}
    """)
    
    # Now process using these values - they are LOCKED IN and won't change
    # (unlike pulling from live ModelMasterCreation)
    
    return {
        'lot_id': actual_lot_id,
        'qty': qty,
        'trays': trays,
    }


# ============================================================================
# EXAMPLE 5: Querying Previous Submissions
# ============================================================================

def get_submission_history(batch_id):
    """
    Example: Get all submissions for a batch (including revoked).
    """
    from InputScreening.models import InputScreening_Submitted
    
    submissions = InputScreening_Submitted.objects.filter(
        batch_id=batch_id
    ).order_by('-created_at')
    
    results = []
    for s in submissions:
        results.append({
            'lot_id': s.lot_id,
            'status': s.get_display_status(),
            'qty': s.submitted_lot_qty,
            'accepted': s.accepted_qty,
            'rejected': s.rejected_qty,
            'is_child': s.is_child_lot,
            'parent': s.parent_lot_id,
            'created_at': s.created_at.isoformat(),
            'created_by': s.created_by.username if s.created_by else 'Unknown',
        })
    
    return results


# ============================================================================
# EXAMPLE 6: Audit - Find All Child Lots from Parent
# ============================================================================

def audit_split_lots(parent_lot_id):
    """
    Example: Audit trail - find all child lots from a split.
    """
    from InputScreening.services_submitted import get_all_child_lots
    
    children = get_all_child_lots(parent_lot_id)
    
    if not children.exists():
        return {'status': 'No children - was not split'}
    
    return {
        'parent': parent_lot_id,
        'children': [
            {
                'lot_id': c.lot_id,
                'type': 'ACCEPT' if c.is_partial_accept else 'REJECT',
                'qty': c.submitted_lot_qty,
                'active': c.is_active,
            }
            for c in children
        ]
    }


# ============================================================================
# EXAMPLE 7: Revocation (Audit Correction)
# ============================================================================

def handle_submission_revocation(lot_id, reason):
    """
    Example: Revoke a submission due to audit finding.
    """
    from InputScreening.services_submitted import revoke_submission
    
    record = revoke_submission(lot_id, reason)
    
    if record:
        return {
            'success': True,
            'message': f'Revoked {lot_id}',
            'was_active': record.is_active,
            'is_now_revoked': record.is_revoked,
        }
    else:
        return {
            'success': False,
            'message': f'Could not revoke {lot_id} - not found',
        }


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    """
    To test these examples in Django shell:
    
    python manage.py shell
    >>> exec(open('InputScreening/services_submitted_examples.py').read())
    
    Or run specific example:
    >>> from InputScreening.services_submitted_examples import submit_full_accept_example
    """
    print("Examples loaded successfully")

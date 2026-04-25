"""
Brass QC Routing — next-stage decisions.

All stage routing logic lives here.
Returns target module names and stock flag dictionaries.

Rule: No DB writes. No HTTP. Pure routing decisions.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Stage routing
# ─────────────────────────────────────────────────────────────────────────────

# Brass QC routing table — single source of truth
_ROUTING_TABLE = {
    "FULL_ACCEPT": "Brass Audit",
    "FULL_REJECT": "IQF",
    "PARTIAL": None,  # Parent is closed — children route independently
}


def get_next_stage(submission_type):
    """
    Returns the next module name for a given submission type.

    FULL_ACCEPT → Brass Audit
    FULL_REJECT → IQF
    PARTIAL     → None (parent closed, children are independent)
    """
    return _ROUTING_TABLE.get(submission_type)


def get_stock_flag_updates(submission_type, accepted_qty, rejected_qty):
    """
    Returns a dict of TotalStockModel field values to update
    based on submission_type.

    Views/submission_service applies these to the stock object.
    No DB write here.
    """
    if submission_type == "FULL_ACCEPT":
        return {
            'brass_qc_accptance': True,
            'brass_qc_rejection': False,
            'brass_qc_few_cases_accptance': False,
            'brass_physical_qty': accepted_qty,
            'brass_qc_accepted_qty': accepted_qty,
            'next_process_module': 'Brass Audit',
            'last_process_module': 'Brass QC',
            'send_brass_audit_to_iqf': False,
        }
    elif submission_type == "FULL_REJECT":
        return {
            'brass_qc_accptance': False,
            'brass_qc_rejection': True,
            'brass_qc_few_cases_accptance': False,
            'brass_physical_qty': 0,
            'brass_qc_accepted_qty': 0,
            'brass_qc_after_rejection_qty': rejected_qty,
            'next_process_module': None,
            'last_process_module': 'Brass QC',
            'is_split': True,
            'remove_lot': True,
            'send_brass_audit_to_iqf': False,
        }
    elif submission_type == "PARTIAL":
        return {
            'brass_qc_few_cases_accptance': True,
            'brass_qc_rejection': True,
            'brass_qc_accptance': False,
            'brass_physical_qty': 0,
            'brass_qc_accepted_qty': accepted_qty,
            'brass_qc_after_rejection_qty': rejected_qty,
            'next_process_module': None,
            'last_process_module': 'Brass QC',
            'is_split': True,
            'remove_lot': True,
            'send_brass_audit_to_iqf': True,
        }
    return {}

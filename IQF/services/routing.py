"""
IQF Routing — next-stage decisions.

All stage routing logic lives here.
Returns target module names and stock flag dictionaries.

Rule: No DB writes. No HTTP. Pure routing decisions.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Stage routing
# ─────────────────────────────────────────────────────────────────────────────

# IQF routing table — single source of truth
_ROUTING_TABLE = {
    "FULL_ACCEPT": "Brass QC",      # Send accepted lot back to Brass QC for audit
    "FULL_REJECT": "IQF",            # Keep in IQF reject table
    "PARTIAL": "Brass QC",           # Parent closed, children route independently
}


def get_next_stage(submission_type):
    """
    Returns the next module name for a given submission type.

    FULL_ACCEPT → Brass QC
    FULL_REJECT → IQF (stays in reject table)
    PARTIAL     → Brass QC (parent closed, children are independent)
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
            'iqf_accptance': True,
            'iqf_rejection': False,
            'iqf_few_cases_accptance': False,
            'brass_physical_qty': accepted_qty,
            'iqf_accepted_qty': accepted_qty,
            'next_process_module': 'Brass QC',
            'last_process_module': 'IQF',
            'send_brass_audit_to_iqf': False,
        }
    elif submission_type == "FULL_REJECT":
        return {
            'iqf_accptance': False,
            'iqf_rejection': True,
            'iqf_few_cases_accptance': False,
            'brass_physical_qty': 0,
            'iqf_accepted_qty': 0,
            'next_process_module': None,  # Stay in IQF reject table
            'last_process_module': 'IQF',
            'send_brass_audit_to_iqf': False,
        }
    elif submission_type == "PARTIAL":
        return {
            'iqf_few_cases_accptance': True,
            'iqf_rejection': True,
            'iqf_accptance': False,
            'brass_physical_qty': 0,
            'iqf_accepted_qty': accepted_qty,
            'iqf_after_rejection_qty': rejected_qty,
            'next_process_module': None,  # Parent closed
            'last_process_module': 'IQF',
            'is_split': True,
            'remove_lot': True,  # Close parent lot
            'send_brass_audit_to_iqf': False,
        }
    return {}

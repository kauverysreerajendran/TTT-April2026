"""
Model Combination Validator — Backend-driven eligibility check for Jig Loading "Add Model" flow.

Architecture:
- NO validation in frontend — frontend only renders the API response.
- Lookalike conflict is DB-driven from LookLikeModel (prefix-level, bidirectional).
- Jig capacity conflict is derived from JigLoadingMaster (model_no → capacity group).
- ep_bath_type conflict is from ModelMaster.
- Returns 200 always; errors are in the response body.
"""
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def _build_lookalike_prefix_map():
    """
    Build a prefix-level bidirectional conflict map from LookLikeModel DB entries.
    Returns: dict[str, set[str]] e.g. {'2617': {'2648'}, '2648': {'2617'}}
    """
    conflict_map = defaultdict(set)
    try:
        from modelmasterapp.models import LookLikeModel
        for ll in LookLikeModel.objects.prefetch_related('plating_stk_no').select_related('same_plating_stk_no'):
            same_mm = ll.same_plating_stk_no
            if not same_mm:
                continue
            same_prefix = (same_mm.model_no or '').strip()
            for other_mm in ll.plating_stk_no.all():
                other_prefix = (other_mm.model_no or '').strip()
                if same_prefix and other_prefix and same_prefix != other_prefix:
                    conflict_map[same_prefix].add(other_prefix)
                    conflict_map[other_prefix].add(same_prefix)  # bidirectional
    except Exception as e:
        logger.exception(f'[LOOKALIKE_MAP] Failed to build lookalike prefix map: {e}')
    return dict(conflict_map)


def _build_jig_capacity_map():
    """
    Build model_no → jig_capacity map from JigLoadingMaster.
    Returns: dict[str, int] e.g. {'2617': 144, '2648': 144, '1805': 98}
    """
    cap_map = {}
    try:
        from Jig_Loading.models import JigLoadingMaster
        for jm in JigLoadingMaster.objects.select_related('model_stock_no').all():
            mm = jm.model_stock_no
            if not mm:
                continue
            prefix = (mm.model_no or '').strip()
            cap = int(jm.jig_capacity or 0)
            if prefix and cap:
                # Keep first value per prefix (all entries for same model_no should be same)
                if prefix not in cap_map:
                    cap_map[prefix] = cap
    except Exception as e:
        logger.exception(f'[CAP_MAP] Failed to build jig capacity map: {e}')
    return cap_map


def _get_all_model_master_entries():
    """
    Return all ModelMaster entries as list of dicts:
    [{'plating_stk_no': str, 'model_no': str, 'ep_bath_type': str}, ...]
    """
    entries = []
    try:
        from modelmasterapp.models import ModelMaster
        for mm in ModelMaster.objects.all().values('plating_stk_no', 'model_no', 'ep_bath_type'):
            psn = (mm.get('plating_stk_no') or '').strip()
            if psn:
                entries.append({
                    'plating_stk_no': psn,
                    'model_no': (mm.get('model_no') or '').strip(),
                    'ep_bath_type': (mm.get('ep_bath_type') or '').strip(),
                })
    except Exception as e:
        logger.exception(f'[MODEL_ENTRIES] Failed to fetch ModelMaster entries: {e}')
    return entries


def validate_model_combination(selected_models):
    """
    Determine which models are eligible / non-eligible to add alongside the selected models.

    Args:
        selected_models: list of plating_stk_no strings (already on the jig)

    Returns dict:
        {
            'eligible_models':     [{'plating_stk_no', 'model_no', 'jig_capacity', 'ep_bath_type'}, ...],
            'non_eligible_models': [{'plating_stk_no', 'model_no', 'reason', 'block_type'}, ...],
            'blocked_lookalike_plating_stk_nos': [...],   # for frontend hide
            'warnings': [...],
            'errors': [...],
        }
    """
    eligible_models = []
    non_eligible_models = []
    blocked_lookalike_plating_stk_nos = []
    warnings = []
    errors = []

    if not selected_models:
        errors.append('No models selected.')
        logger.warning('[VALIDATE] Called with empty selected_models')
        return _make_response(eligible_models, non_eligible_models, blocked_lookalike_plating_stk_nos, warnings, errors)

    # Clean input
    selected_models = [s.strip() for s in selected_models if s and s.strip()]
    logger.info(f'[VALIDATE] selected_models={selected_models}')

    # --- Load DB data ---
    lookalike_prefix_map = _build_lookalike_prefix_map()
    jig_cap_map = _build_jig_capacity_map()
    all_candidates = _get_all_model_master_entries()

    logger.info(f'[VALIDATE] lookalike_prefix_map={dict(lookalike_prefix_map)}')
    logger.info(f'[VALIDATE] jig_cap_map={jig_cap_map}')

    # --- Resolve selected models' attributes ---
    # Map plating_stk_no → {model_no, ep_bath_type}
    all_mm_lookup = {e['plating_stk_no']: e for e in all_candidates}

    selected_meta = []
    for psn in selected_models:
        meta = all_mm_lookup.get(psn)
        if not meta:
            # Partial match fallback (case-insensitive)
            for k, v in all_mm_lookup.items():
                if k.lower() == psn.lower():
                    meta = v
                    break
        if meta:
            selected_meta.append(meta)
        else:
            logger.warning(f'[VALIDATE] selected model not found in ModelMaster: {psn}')

    if not selected_meta:
        errors.append(f'Selected model(s) not found in system: {", ".join(selected_models)}')
        return _make_response(eligible_models, non_eligible_models, blocked_lookalike_plating_stk_nos, warnings, errors)

    # Determine required constraints from selected models
    selected_prefixes = set(m['model_no'] for m in selected_meta if m['model_no'])
    selected_ep_bath_types = set(m['ep_bath_type'] for m in selected_meta if m['ep_bath_type'])
    selected_jig_caps = set(jig_cap_map.get(p, 0) for p in selected_prefixes)
    selected_jig_caps.discard(0)

    # Determine which prefixes are blocked by lookalike rules
    blocked_prefixes = set()
    for prefix in selected_prefixes:
        for conflict_prefix in lookalike_prefix_map.get(prefix, set()):
            blocked_prefixes.add(conflict_prefix)

    logger.info(f'[VALIDATE] selected_prefixes={selected_prefixes} selected_ep_bath_types={selected_ep_bath_types} selected_jig_caps={selected_jig_caps} blocked_prefixes={blocked_prefixes}')

    # --- Evaluate each candidate ---
    for candidate in all_candidates:
        psn = candidate['plating_stk_no']
        prefix = candidate['model_no']
        bath = candidate['ep_bath_type']

        # Skip models already selected (they're already on the jig)
        if psn in selected_models:
            continue

        # Check lookalike block (prefix-level)
        if prefix in blocked_prefixes:
            non_eligible_models.append({
                'plating_stk_no': psn,
                'model_no': prefix,
                'reason': f'Lookalike conflict (model group {prefix} conflicts with {", ".join(selected_prefixes)})',
                'block_type': 'lookalike',
            })
            blocked_lookalike_plating_stk_nos.append(psn)
            continue

        # Check jig capacity mismatch
        candidate_cap = jig_cap_map.get(prefix, 0)
        if selected_jig_caps and candidate_cap and candidate_cap not in selected_jig_caps:
            non_eligible_models.append({
                'plating_stk_no': psn,
                'model_no': prefix,
                'reason': f'Jig capacity conflict ({candidate_cap} vs {", ".join(str(c) for c in selected_jig_caps)})',
                'block_type': 'jig_capacity',
            })
            continue

        # Check ep_bath_type mismatch
        if selected_ep_bath_types and bath and bath not in selected_ep_bath_types:
            non_eligible_models.append({
                'plating_stk_no': psn,
                'model_no': prefix,
                'reason': f'Bath type conflict ({bath} vs {", ".join(selected_ep_bath_types)})',
                'block_type': 'bath_type',
            })
            continue

        # All checks passed — eligible
        eligible_models.append({
            'plating_stk_no': psn,
            'model_no': prefix,
            'jig_capacity': candidate_cap or (list(selected_jig_caps)[0] if selected_jig_caps else 0),
            'ep_bath_type': bath,
        })

    # Version warning (same prefix, different ep_bath_type within eligible)
    eligible_prefixes = set(m['model_no'] for m in eligible_models)
    eligible_bath_types = set(m['ep_bath_type'] for m in eligible_models)
    if len(eligible_bath_types) > 1:
        warnings.append(f'Multiple bath types in eligible models: {", ".join(eligible_bath_types)}')

    # No eligible models → informational error (not a hard failure)
    if not eligible_models:
        errors.append('No compatible models found for this selection. This model may need to be loaded separately.')

    # Sort eligible: same prefix as selected models first
    eligible_models.sort(key=lambda m: (0 if m['model_no'] in selected_prefixes else 1, m['plating_stk_no']))

    logger.info(f'[VALIDATE] Result: eligible={len(eligible_models)}, non_eligible={len(non_eligible_models)}, blocked_lookalike={len(blocked_lookalike_plating_stk_nos)}, errors={errors}')

    return _make_response(eligible_models, non_eligible_models, blocked_lookalike_plating_stk_nos, warnings, errors)


def _make_response(eligible_models, non_eligible_models, blocked_lookalike_plating_stk_nos, warnings, errors):
    return {
        'eligible_models': eligible_models,
        'non_eligible_models': non_eligible_models,
        'blocked_lookalike_plating_stk_nos': blocked_lookalike_plating_stk_nos,
        'warnings': warnings,
        'errors': errors,
    }

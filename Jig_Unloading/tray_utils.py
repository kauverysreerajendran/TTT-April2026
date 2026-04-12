"""
Shared utility for fetching tray data from upstream tables when no tray records
exist in the current stage (NickelQcTrayId, JigUnload_TrayId, etc.).

Used by: Nickel Inspection (Z1/Z2), Nickel Audit (Z1/Z2) PickTrayIdList views.
"""
import logging

logger = logging.getLogger(__name__)


def get_model_master_tray_info(plating_stk_no, fallback_type='', fallback_cap=0):
    """
    Dynamically look up tray type code from ModelMaster by plating stock number.
    Returns (tray_type_str, tray_capacity_int).
    Falls back to provided defaults if lookup fails.
    """
    if plating_stk_no:
        from modelmasterapp.models import ModelMaster
        mm = ModelMaster.objects.select_related('tray_type').filter(
            plating_stk_no=plating_stk_no
        ).first()
        if mm and mm.tray_type:
            return mm.tray_type.tray_type, mm.tray_capacity or fallback_cap
    return fallback_type, fallback_cap


def get_upstream_tray_distribution(lot_id):
    """
    When no tray records exist in the current-stage tables, look up the
    JigUnloadAfterTable for combine_lot_ids, then fetch REAL tray IDs from
    the nearest upstream table that has data.

    Quantities are redistributed to match JigUnloadAfterTable.total_case_qty.

    Returns:
        (list[dict], str) — (tray_data_list, tray_source) on success
        (None, None)      — when no upstream data is available
    """
    from Jig_Unloading.models import JigUnloadAfterTable, JigUnload_TrayId, JUSubmittedZ1
    from BrassAudit.models import BrassAuditTrayId, Brass_Audit_Accepted_TrayID_Store
    from Brass_QC.models import BrassTrayId
    from Jig_Loading.models import JigLoadTrayId

    # 1. Get JigUnloadAfterTable record for this UNLOT lot_id
    juat = JigUnloadAfterTable.objects.filter(lot_id=lot_id).first()
    if not juat:
        return None, None

    combine_lot_ids = juat.combine_lot_ids or []
    if not combine_lot_ids:
        return None, None

    total_qty = juat.total_case_qty or 0
    tray_capacity = juat.tray_capacity or 16

    if total_qty <= 0:
        return None, None

    # 2. Try JigUnload_TrayId with combine_lot_ids first
    for lid in combine_lot_ids:
        trays = JigUnload_TrayId.objects.filter(lot_id=lid).order_by('id')
        if trays.exists():
            data = []
            for idx, t in enumerate(trays, 1):
                data.append({
                    's_no': idx,
                    'tray_id': t.tray_id,
                    'tray_quantity': t.tray_qty or 0,
                    'top_tray': t.top_tray,
                    'delink_tray': t.delink_tray,
                    'rejected_tray': t.rejected_tray,
                })
            logger.info(
                "[upstream_tray] Found %d trays in JigUnload_TrayId for %s (via %s)",
                len(data), lot_id, lid,
            )
            return data, "JigUnload_TrayId (via combine_lot_ids)"

    # 2b. Try JUSubmittedZ1.tray_data (Zone 1 Jig Unloading stores tray scans here)
    for lid in combine_lot_ids:
        ju_sub = JUSubmittedZ1.objects.filter(lot_id=lid, is_draft=False).order_by('-submitted_at').first()
        if ju_sub and ju_sub.tray_data:
            data = []
            for idx, t in enumerate(ju_sub.tray_data, 1):
                tray_id = t.get('tray_id', '')
                if not tray_id:
                    continue
                data.append({
                    's_no': idx,
                    'tray_id': tray_id,
                    'tray_quantity': t.get('qty', t.get('tray_qty', 0)) or 0,
                    'top_tray': t.get('is_top_tray', False),
                    'delink_tray': False,
                    'rejected_tray': False,
                })
            if data:
                logger.info(
                    "[upstream_tray] Found %d trays in JUSubmittedZ1 for %s (via %s)",
                    len(data), lot_id, lid,
                )
                print(f"✅ Found {len(data)} trays from JUSubmittedZ1 (via combine_lot_ids)")
                return data, "JUSubmittedZ1 (via combine_lot_ids)"

    # 3. Search upstream tables for REAL tray IDs
    #    Priority: closest upstream stage → farthest
    upstream_sources = [
        (BrassAuditTrayId, 'tray_quantity', "BrassAuditTrayId"),
        (Brass_Audit_Accepted_TrayID_Store, 'tray_qty', "Brass_Audit_Accepted_TrayID_Store"),
        (BrassTrayId, 'tray_quantity', "BrassTrayId"),
        (JigLoadTrayId, None, "JigLoadTrayId"),  # JigLoadTrayId may not have qty
    ]

    upstream_trays = []
    tray_source = None

    for SourceModel, qty_field, source_name in upstream_sources:
        for lid in combine_lot_ids:
            trays = SourceModel.objects.filter(lot_id=lid).order_by('id')
            if trays.exists():
                upstream_trays = list(trays)
                tray_source = source_name
                break
        if upstream_trays:
            break

    if not upstream_trays:
        logger.warning(
            "[upstream_tray] No upstream tray data for %s (combine_lot_ids=%s)",
            lot_id, combine_lot_ids,
        )
        return None, None

    # 4. Extract real tray IDs (prefer non-rejected, non-delinked)
    active_tray_ids = []
    top_tray_id = None

    for t in upstream_trays:
        is_rejected = getattr(t, 'rejected_tray', False)
        is_delinked = getattr(t, 'delink_tray', False)
        is_top = getattr(t, 'top_tray', False)

        if is_rejected or is_delinked:
            continue

        if is_top:
            top_tray_id = t.tray_id
        else:
            active_tray_ids.append(t.tray_id)

    # If all trays were filtered out, use all of them
    if not active_tray_ids and not top_tray_id:
        for t in upstream_trays:
            is_top = getattr(t, 'top_tray', False)
            if is_top:
                top_tray_id = t.tray_id
            else:
                active_tray_ids.append(t.tray_id)

    # 5. Redistribute quantities based on total_case_qty & tray_capacity
    num_full = total_qty // tray_capacity
    remainder = total_qty % tray_capacity
    num_trays_needed = num_full + (1 if remainder > 0 else 0)

    # Build ordered list of tray IDs: top tray first, then full trays
    ordered_ids = []
    if remainder > 0 and top_tray_id:
        ordered_ids.append(top_tray_id)
    elif remainder > 0 and active_tray_ids:
        # Use first active tray as top if no dedicated top tray
        ordered_ids.append(active_tray_ids.pop(0))

    ordered_ids.extend(active_tray_ids)

    data = []
    for i in range(num_trays_needed):
        if i >= len(ordered_ids):
            break  # Don't fabricate tray IDs

        if remainder > 0 and i == 0:
            qty = remainder
            is_top = True
        else:
            qty = tray_capacity
            is_top = False

        data.append({
            's_no': i + 1,
            'tray_id': ordered_ids[i],
            'tray_quantity': qty,
            'top_tray': is_top,
            'delink_tray': False,
            'rejected_tray': False,
        })

    logger.info(
        "[upstream_tray] Built %d trays from %s for %s (total_qty=%d, cap=%d)",
        len(data), tray_source, lot_id, total_qty, tray_capacity,
    )
    return data, f"upstream ({tray_source})"

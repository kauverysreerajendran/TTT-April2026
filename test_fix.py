from InputScreening.selectors import get_lot_tray_context
from InputScreening.models import IS_PartialAcceptLot
lot = IS_PartialAcceptLot.objects.first()
if lot:
    ctx = get_lot_tray_context(lot.new_lot_id)
    if ctx['found']:
        print(f'PASS: Child lot {lot.new_lot_id} resolved')
        print(f'  Lot Qty: {ctx["lot_qty"]}')
        print(f'  Active Trays: {len(ctx["active_trays"])}')
        print(f'  Expected Qty: {lot.accepted_qty}')
        print(f'  Expected Trays: {len(lot.trays_snapshot or [])}')
    else:
        print(f'FAIL: Child lot {lot.new_lot_id} not found')

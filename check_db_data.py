import os, django, json
os.environ['DJANGO_SETTINGS_MODULE'] = 'watchcase_tracker.settings'
django.setup()
from Jig_Loading.models import JigCompleted

for lid in ['LID010420262138590007', 'LID310320261959260003']:
    recs = JigCompleted.objects.filter(lot_id=lid, draft_status='submitted')
    for r in recs:
        print(f'\n=== {r.lot_id} | batch={r.batch_id} | jig={r.jig_id} ===')
        print(f'  is_multi_model={r.is_multi_model}')
        print(f'  plating_stock_num={r.plating_stock_num}')
        print(f'  loaded_cases_qty={r.loaded_cases_qty}')
        print(f'  original_lot_qty={r.original_lot_qty}')
        print(f'  delink_tray_qty={r.delink_tray_qty}')
        print(f'  excess_qty={r.excess_qty}')
        print(f'  half_filled_tray_qty={r.half_filled_tray_qty}')
        print(f'  half_filled_tray_info={json.dumps(r.half_filled_tray_info)}')
        print(f'  no_of_model_cases={r.no_of_model_cases}')
        mma = r.multi_model_allocation or []
        if mma:
            for m in mma:
                mn = m.get('model_name', '')
                ml = m.get('lot_id', '')
                mq = m.get('allocated_qty', 0)
                print(f'    model={mn} lot={ml} qty={mq}')
        else:
            print('    (no multi_model_allocation)')

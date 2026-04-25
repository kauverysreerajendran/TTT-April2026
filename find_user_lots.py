import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId

# Search for any lot containing 173429
ts = TotalStockModel.objects.filter(lot_id__contains='173429')
print(f"TotalStock records matching '173429':")
for t in ts:
    print(f"  - Lot: {t.lot_id}, Qty: {t.total_stock}, Status: {t.status_of_material}, Next: {t.next_process_module}")
    trays = IQFTrayId.objects.filter(lot_id=t.lot_id)
    print(f"    Trays: {trays.count()}")
    for tr in trays:
        print(f"      - {tr.tray_id}: {tr.tray_quantity}")

# Search for 173409
ts2 = TotalStockModel.objects.filter(lot_id__contains='173409')
print(f"\nTotalStock records matching '173409':")
for t in ts2:
    print(f"  - Lot: {t.lot_id}, Qty: {t.total_stock}, Status: {t.status_of_material}, Next: {t.next_process_module}")
    trays = IQFTrayId.objects.filter(lot_id=t.lot_id)
    print(f"    Trays: {trays.count()}")
    for tr in trays:
        print(f"      - {tr.tray_id}: {tr.tray_quantity}")

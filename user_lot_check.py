import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from InputScreening.models import IS_PartialAcceptLot

# Check if the lot the user is TALKING about exists at all
lot_id = 'LID20260424173409000001'
ts = TotalStockModel.objects.filter(lot_id=lot_id).first()
if ts:
    print(f"FOUND USER'S LOT: {lot_id}")
    print(f"  Qty: {ts.total_stock}")
    trays = IQFTrayId.objects.filter(lot_id=lot_id)
    print(f"  Trays: {trays.count()} (Sum: {sum(t.tray_quantity for t in trays)})")
else:
    print(f"USER'S LOT {lot_id} NOT FOUND")

# Check for the transition lot the user said shows 0
lot_zero = 'LID20260424173429901079'
ts2 = TotalStockModel.objects.filter(lot_id=lot_zero).first()
if ts2:
    print(f"FOUND ZERO QTY LOT: {lot_zero}")
    print(f"  Qty: {ts2.total_stock}")
    trays2 = IQFTrayId.objects.filter(lot_id=lot_zero)
    print(f"  Trays: {trays2.count()}")
else:
    print(f"ZERO QTY LOT {lot_zero} NOT FOUND")

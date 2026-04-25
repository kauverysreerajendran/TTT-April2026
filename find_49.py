import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId

# Search for any lot with tray qty 49 or 5 trays
print("Searching for IQFTrayId with qty=49 or count=5...")
from django.db.models import Count, Sum
lots_with_5_trays = IQFTrayId.objects.values('lot_id').annotate(count=Count('tray_id'), total=Sum('tray_quantity')).filter(count=5)
for lot in lots_with_5_trays:
    print(f"Lot with 5 trays: ID={lot['lot_id']}, TotalQty={lot['total']}")

lots_with_49_qty = TotalStockModel.objects.filter(total_stock=49)
for lot in lots_with_49_qty:
    print(f"TotalStock with 49 qty: ID={lot.lot_id}, Status={lot.status_of_material}")

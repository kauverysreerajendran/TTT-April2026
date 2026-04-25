import os
import django
from django.utils import timezone
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

print("=== SEARCHING TOTAL STOCK FOR USER IDS ===")
ids_to_check = ['LID240420261726140001', 'LID20260424172715000001']

for lot_id in ids_to_check:
    ts = TotalStockModel.objects.filter(lot_id__icontains=lot_id[3:11]).first()
    if ts:
        print(f"Found something similar to {lot_id}: {ts.lot_id}")
    else:
        print(f"No match for substring of {lot_id}")

print("\n=== RECENT TOTAL STOCK RECORDS ===")
recent_stock = TotalStockModel.objects.all().order_by('-created_at')[:5]
for s in recent_stock:
    print(f"Lot: {s.lot_id} | Qty: {s.total_stock} | Created: {s.created_at}")

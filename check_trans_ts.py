import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

lot = 'LID20260424222341025647'
ts = TotalStockModel.objects.filter(lot_id=lot).first()
if ts:
    print(f"TotalStock for {lot}: {ts.total_stock}")
else:
    print(f"No TotalStock for {lot}")

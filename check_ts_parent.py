import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

parent_is = 'LID240420262221087256'
ts = TotalStockModel.objects.filter(lot_id=parent_is).first()
if ts:
    print(f"TotalStock for {parent_is}:")
    for field in ts._meta.fields:
        print(f"  {field.name}: {getattr(ts, field.name)}")
else:
    print(f"No TotalStock for {parent_is}")

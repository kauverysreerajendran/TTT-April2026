import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Submission

child_is = 'LID20260424222207000001'
ts = TotalStockModel.objects.filter(lot_id=child_is).first()
if ts:
    print(f"TotalStock for {child_is}: {ts.total_stock}")
    for field in ts._meta.fields:
        print(f"  {field.name}: {getattr(ts, field.name)}")
else:
    print(f"No TotalStock for {child_is}")

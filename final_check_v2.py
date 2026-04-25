import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from Brass_QC.models import Brass_QC_Submission

print("\n=== RECENT TOTAL STOCK RECORDS ===")
ts_records = TotalStockModel.objects.all().order_by('-id')[:20]
for ts in ts_records:
    # Print all fields to see what's available
    fields = [f.name for f in ts._meta.fields]
    vals = {f: getattr(ts, f) for f in fields}
    print(vals)

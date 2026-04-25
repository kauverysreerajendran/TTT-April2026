import os
import django
from Brass_QC.models import BrassTrayId

records = BrassTrayId.objects.all()
print(f"Total BrassTrayId records: {records.count()}")
for r in records:
    print(f"Lot: {r.lot_id}, Tray: {r.tray_id}")

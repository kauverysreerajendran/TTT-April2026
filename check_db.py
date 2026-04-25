import os
import django
from Brass_QC.models import BrassTrayId

# Check for ANY records to see if the table has data
count = BrassTrayId.objects.count()
print(f"Total BrassTrayId records in DB: {count}")

if count > 0:
    first_few = BrassTrayId.objects.all()[:5]
    print("Example Lot IDs in BrassTrayId:")
    for record in first_few:
        print(f"  - {record.lot_id}")

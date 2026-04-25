import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Brass_QC.models import Brass_QC_Submission, BrassQC_PartialRejectLot
from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId

parent_lot = 'LID24042026132742990107'

# Check if parent lot has trays
trays = IQFTrayId.objects.filter(lot_id=parent_lot)
print(f"Trays for parent lot ({parent_lot}): {trays.count()}")
for t in trays:
    print(f"  - {t.tray_id}: {t.tray_quantity}")

# Check any submission for this parent lot
subs = Brass_QC_Submission.objects.filter(lot_id=parent_lot)
print(f"\nSubmissions found: {subs.count()}")
for sub in subs:
    print(f"  - ID: {sub.id}, Type: {sub.submission_type}, Transition: {sub.transition_lot_id}")
    
    if sub.transition_lot_id:
        trans_trays = IQFTrayId.objects.filter(lot_id=sub.transition_lot_id)
        print(f"    - Transition Trays: {trans_trays.count()}")
        for tt in trans_trays:
            print(f"      - {tt.tray_id}: {tt.tray_quantity}")

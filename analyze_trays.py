import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from Brass_QC.models import Brass_QC_Submission

# Analyze transition lots vs parent lots
print("=== ANALYSIS OF TRANSITION RECORDS ===")
subs = Brass_QC_Submission.objects.filter(submission_type='FULL_REJECT').order_by('-created_at')[:5]
for s in subs:
    print(f"\nSubmission ID: {s.id}")
    print(f"  Parent Lot: {s.lot_id}")
    print(f"  Transition Lot: {s.transition_lot_id}")
    
    # Check parent trays
    p_trays = IQFTrayId.objects.filter(lot_id=s.lot_id)
    print(f"  Parent Trays Count: {p_trays.count()}")
    
    # Check transition trays
    t_trays = IQFTrayId.objects.filter(lot_id=s.transition_lot_id)
    print(f"  Transition Trays Count: {t_trays.count()} (Sum Qty: {sum(x.tray_quantity for x in t_trays)})")
    
    # Check TotalStock
    ts = TotalStockModel.objects.filter(lot_id=s.transition_lot_id).first()
    if ts:
        print(f"  TotalStock for Transition: {ts.total_stock}")
    else:
        print(f"  [x] No TotalStock for transition")

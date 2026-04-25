import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Brass_QC.models import Brass_QC_Submission
from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from InputScreening.models import IS_PartialAcceptLot

# Broader search
print("=== BRASS QC SUBMISSIONS (Last 20) ===")
subs = Brass_QC_Submission.objects.all().order_by('-created_at')[:20]

for sub in subs:
    print(f"\n[Brass_QC_Submission id={sub.id}] lot={sub.lot_id} trans={sub.transition_lot_id} type={sub.submission_type} date={sub.created_at}")
    
    # Check if transition lot has TotalStockModel
    if sub.transition_lot_id:
        ts = TotalStockModel.objects.filter(lot_id=sub.transition_lot_id).first()
        if ts:
            print(f"  [v] TotalStockModel: qty={ts.total_stock}, next={ts.next_process_module}")
        else:
            print(f"  [x] TotalStockModel NOT FOUND")
        
        trays = IQFTrayId.objects.filter(lot_id=sub.transition_lot_id)
        if trays.exists():
            print(f"  [v] IQFTrayId count: {trays.count()}")
        else:
            print(f"  [x] NO IQFTrayId found")

print("\n=== RECENT IS PARTIAL ACCEPT LOTS ===")
is_partial = IS_PartialAcceptLot.objects.all().order_by('-created_at')[:10]
for p in is_partial:
    print(f"[IS_Partial] new={p.new_lot_id} parent={p.parent_lot_id} qty={p.accepted_qty}")

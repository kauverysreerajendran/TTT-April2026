import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Brass_QC.models import Brass_QC_Submission
from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from InputScreening.models import IS_PartialAcceptLot

# Find submissions
print("=== BRASS QC SUBMISSIONS ===")
subs = Brass_QC_Submission.objects.filter(
    Q(transition_lot_id__contains='173429') | 
    Q(transition_lot_id__contains='173409') |
    Q(lot_id__contains='173429') |
    Q(lot_id__contains='173409')
).order_by('-created_at')[:10]

for sub in subs:
    print(f"\n[Brass_QC_Submission id={sub.id}]")
    print(f"  lot_id: {sub.lot_id}")
    print(f"  submission_type: {sub.submission_type}")
    print(f"  transition_lot_id: {sub.transition_lot_id}")
    print(f"  rejected_qty: {sub.rejected_qty}")
    print(f"  created_at: {sub.created_at}")
    
    # Check if transition lot has TotalStockModel
    if sub.transition_lot_id:
        ts = TotalStockModel.objects.filter(lot_id=sub.transition_lot_id).first()
        if ts:
            print(f"  [v] TotalStockModel exists: lot_id={ts.lot_id}, qty={ts.total_stock}, next={ts.next_process_module}, status={ts.status_of_material}")
        else:
            print(f"  [x] TotalStockModel NOT FOUND for transition lot")
        
        # Check IQFTrayId
        trays = IQFTrayId.objects.filter(lot_id=sub.transition_lot_id)
        print(f"  IQFTrayId count: {trays.count()}")
        if trays.exists():
            for t in trays:
                print(f"    - {t.tray_id}: qty={t.tray_quantity}, top={t.top_tray}")

# Check IS partial accept lots
print("\n\n=== IS PARTIAL ACCEPT LOTS ===")
is_partial = IS_PartialAcceptLot.objects.filter(
    Q(new_lot_id__contains='173429') | 
    Q(new_lot_id__contains='173409')
).order_by('-created_at')[:5]

for p in is_partial:
    print(f"\n[IS_PartialAcceptLot]")
    print(f"  new_lot_id: {p.new_lot_id}")
    print(f"  parent_lot_id: {p.parent_lot_id}")
    print(f"  accepted_qty: {p.accepted_qty}")
    print(f"  trays_snapshot: {p.trays_snapshot}")

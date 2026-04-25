import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from Brass_QC.models import Brass_QC_Submission, BrassQC_PartialRejectLot

# Deep dive into ID 112
sub_id = 112
sub = Brass_QC_Submission.objects.get(id=sub_id)
print(f"=== SUBMISSION {sub_id} ===")
print(f"Parent Lot: {sub.lot_id}")
print(f"Transition Lot: {sub.transition_lot_id}")
print(f"Rejected Qty (Main Sub): {sub.rejected_qty}")

pr = BrassQC_PartialRejectLot.objects.filter(parent_submission=sub).first()
if pr:
    print(f"Partial Reject Lot: {pr.new_lot_id}")
    print(f"Partial Reject Qty: {pr.rejected_qty}")

t_trays = IQFTrayId.objects.filter(lot_id=sub.transition_lot_id)
print(f"Transition Trays (Total={t_trays.count()}):")
for t in t_trays:
    print(f"  - {t.tray_id}: {t.tray_quantity}")

ts = TotalStockModel.objects.filter(lot_id=sub.transition_lot_id).first()
print(f"TotalStock for {sub.transition_lot_id}: {ts.total_stock if ts else 'N/A'}")

# Check any other lot where this might be linked
# Like if the child lot has a different ID
# The user mentioned LID20260424173409000001 (49 qty, 5 trays)

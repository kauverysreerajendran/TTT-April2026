import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Brass_QC.models import Brass_QC_Submission, BrassQC_PartialRejectLot
from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId

# Checking FULL_REJECT outcome
sub_id = 112 
sub = Brass_QC_Submission.objects.get(id=sub_id)
print(f"=== SUBMISSION {sub_id} ===")
print(f"Lot ID: {sub.lot_id}")
print(f"Type: {sub.submission_type}")
print(f"Transition Lot: {sub.transition_lot_id}")

trays = IQFTrayId.objects.filter(lot_id=sub.transition_lot_id)
print(f"\nTrays for transition lot ({sub.transition_lot_id}):")
for t in trays:
    print(f"  - Tray: {t.tray_id}, Qty: {t.tray_quantity}, Top: {t.top_tray}")

parent_trays = IQFTrayId.objects.filter(lot_id=sub.lot_id)
print(f"\nTrays for parent lot ({sub.lot_id}):")
for t in parent_trays:
    print(f"  - Tray: {t.tray_id}, Qty: {t.tray_quantity}, Top: {t.top_tray}")

print("\nPartial Reject records for this submission:")
prs = BrassQC_PartialRejectLot.objects.filter(parent_submission=sub)
for pr in prs:
    print(f"  - New Lot: {pr.new_lot_id}, Qty: {pr.rejected_qty}")

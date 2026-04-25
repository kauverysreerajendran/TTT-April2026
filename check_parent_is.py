import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from InputScreening.models import InputScreening_Submitted, IS_PartialAcceptLot
from Brass_QC.models import Brass_QC_Submission

parent_lot = 'LID240420262221087256'

is_sub = InputScreening_Submitted.objects.filter(lot_id=parent_lot).first()
if is_sub:
    print(f"IS Submission for {parent_lot}:")
    print(f"  Accepted Qty: {is_sub.accepted_qty}")
    print(f"  Rejected Qty: {is_sub.rejected_qty}")
    print(f"  Accept Trays: {is_sub.accept_trays_snapshot}")
    print(f"  Reject Trays: {is_sub.reject_trays_snapshot}")
else:
    print(f"No IS Submission for {parent_lot}")

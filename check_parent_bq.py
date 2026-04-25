import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Submission

lot = 'LID240420262221087256'
ts = TotalStockModel.objects.filter(lot_id=lot).first()
if ts:
    print(f"TotalStock for {lot}: {ts.total_stock}")

bq = Brass_QC_Submission.objects.filter(lot_id=lot).first()
if bq:
    print(f"Brass QC Submission for {lot}:")
    print(f"  Type: {bq.submission_type}")
    print(f"  Success Qty: {bq.success_qty}")
    print(f"  Rejected Qty: {bq.rejected_qty}")
    print(f"  Total Qty: {bq.success_qty + bq.rejected_qty}")
    print(f"  Transition Lot: {bq.transition_lot_id}")
    print(f"  Full Reject Data: {bq.full_reject_data}")

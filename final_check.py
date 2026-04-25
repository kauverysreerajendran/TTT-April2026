import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Submission

# Original parent: LID240420262221087256
# Correct IS Child for 44 pcs: LID20260424222207000001
# Incorrect Transition Child in IQF: LID20260424222341025647 (with parent LID240420262221087256)

lot = 'LID240420262221087256'
bq = Brass_QC_Submission.objects.filter(lot_id=lot).first()
if bq:
    print(f"Parent Lot {lot}:")
    print(f"  Total Lot Qty in BQ: {bq.total_lot_qty}")
    print(f"  Rejected Qty: {bq.rejected_qty}")
    print(f"  Transition ID: {bq.transition_lot_id}")
    print(f"  Full Reject Data: {bq.full_reject_data}")

# See if another BQ submission exists for the IS child
child_is = 'LID20260424222207000001'
bq_child = Brass_QC_Submission.objects.filter(lot_id=child_is).first()
if bq_child:
    print(f"\nChild IS {child_is}:")
    print(f"  Total Lot Qty in BQ: {bq_child.total_lot_qty}")
    print(f"  Transition ID: {bq_child.transition_lot_id}")
else:
    print(f"\nNo BQ submission for child {child_is}")

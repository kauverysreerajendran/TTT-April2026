import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Brass_QC.models import Brass_QC_Submission, BrassQC_PartialRejectLot
from InputScreening.models import IS_PartialAcceptLot
from IQF.models import IQFTrayId
from modelmasterapp.models import TotalStockModel

trans_lot = 'LID20260424222341025647'

print(f"=== TRANSITION LOT: {trans_lot} ===")

# Find Brass QC submission
bq_sub = Brass_QC_Submission.objects.filter(transition_lot_id=trans_lot).first()
if bq_sub:
    print(f"OK Brass_QC_Submission found")
    print(f"  Parent lot_id: {bq_sub.lot_id}")
    print(f"  submission_type: {bq_sub.submission_type}")
    print(f"  rejected_qty: {bq_sub.rejected_qty}")
    print(f"  full_reject_data trays: {bq_sub.full_reject_data}")
    
    parent_lot = bq_sub.lot_id
    
    # Check if parent is IS partial accept child
    print(f"\n=== CHECK IF PARENT IS IS PARTIAL ACCEPT CHILD ===")
    is_partial = IS_PartialAcceptLot.objects.filter(new_lot_id=parent_lot).first()
    if is_partial:
        print(f"OK Parent {parent_lot} IS an IS partial accept child")
        print(f"  IS grandparent: {is_partial.parent_lot_id}")
        print(f"  IS accepted_qty: {is_partial.accepted_qty}")
        print(f"  IS trays_snapshot: {is_partial.trays_snapshot}")
        print(f"\n🔍 TOP TRAY FROM IS SNAPSHOT:")
        for tray in is_partial.trays_snapshot:
            if tray.get('top_tray'):
                print(f"    {tray['tray_id']}: qty={tray['qty']} (CORRECT SOURCE)")
    else:
        print(f"X Parent {parent_lot} is NOT an IS partial accept child")
    
    # Check BrassQC_PartialRejectLot for transition lot
    print(f"\n=== BrassQC_PartialRejectLot FOR TRANSITION ===")
    bq_partial = BrassQC_PartialRejectLot.objects.filter(new_lot_id=trans_lot).first()
    if bq_partial:
        print(f"OK BrassQC_PartialRejectLot found")
        print(f"  rejected_qty: {bq_partial.rejected_qty}")
        print(f"  trays_snapshot: {bq_partial.trays_snapshot}")
        print(f"\n🔍 TOP TRAY FROM BRASSQC SNAPSHOT:")
        for tray in bq_partial.trays_snapshot:
            if tray.get('is_top'):
                print(f"    {tray['tray_id']}: qty={tray['qty']}")
    else:
        print(f"X BrassQC_PartialRejectLot NOT found")
    
    # Check IQFTrayId
    print(f"\n=== IQFTrayId FOR TRANSITION ===")
    iqf_trays = IQFTrayId.objects.filter(lot_id=trans_lot)
    print(f"Count: {iqf_trays.count()}")
    for tray in iqf_trays:
        top_marker = " (TOP)" if tray.top_tray else ""
        print(f"  {tray.tray_id}: qty={tray.tray_quantity}{top_marker}")
else:
    print(f"X Brass_QC_Submission NOT found for transition {trans_lot}")

print(f"\n=== DIAGNOSIS ===")
print("If IS snapshot shows top tray qty=8 but IQFTrayId shows qty=3,")
print("then create_full_reject_child() is reading from WRONG source.")

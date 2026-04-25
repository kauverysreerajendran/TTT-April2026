import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from InputScreening.models import IS_PartialAcceptLot
from Brass_QC.models import Brass_QC_Submission, BrassTrayId
from IQF.models import IQFTrayId

parent_lot = 'LID240420261726140001'
accept_child = 'LID20260424172715000001'

print("=== IS PARTIAL ACCEPT CHILD ===")
child_stock = TotalStockModel.objects.filter(lot_id=accept_child).first()
if child_stock:
    print(f"✅ TotalStockModel found: {accept_child}")
    print(f"  total_stock: {child_stock.total_stock}")
    print(f"  next_process_module: {child_stock.next_process_module}")
    print(f"  last_process_module: {child_stock.last_process_module}")
    print(f"  brass_qc_rejection: {child_stock.brass_qc_rejection}")
    print(f"  brass_qc_transition_lot_id: {child_stock.brass_qc_transition_lot_id}")
    print(f"  is_split: {child_stock.is_split}")
    print(f"  remove_lot: {child_stock.remove_lot}")
else:
    print(f"❌ TotalStockModel NOT found for {accept_child}")

print(f"\n=== IS_PartialAcceptLot SNAPSHOT ===")
is_partial = IS_PartialAcceptLot.objects.filter(new_lot_id=accept_child).first()
if is_partial:
    print(f"✅ Found")
    print(f"  parent_lot_id: {is_partial.parent_lot_id}")
    print(f"  accepted_qty: {is_partial.accepted_qty}")
    print(f"  trays_snapshot: {is_partial.trays_snapshot}")
else:
    print(f"❌ NOT found")

print(f"\n=== PARENT LOT ===")
parent_stock = TotalStockModel.objects.filter(lot_id=parent_lot).first()
if parent_stock:
    print(f"✅ TotalStockModel found: {parent_lot}")
    print(f"  total_stock: {parent_stock.total_stock}")
    print(f"  brass_qc_rejection: {parent_stock.brass_qc_rejection}")
    print(f"  send_brass_audit_to_iqf: {parent_stock.send_brass_audit_to_iqf}")
    print(f"  is_split: {parent_stock.is_split}")
    print(f"  remove_lot: {parent_stock.remove_lot}")
    print(f"  next_process_module: {parent_stock.next_process_module}")

print(f"\n=== BRASS QC SUBMISSION FOR CHILD ===")
bq_sub = Brass_QC_Submission.objects.filter(lot_id=accept_child).first()
if bq_sub:
    print(f"✅ Found Brass_QC_Submission")
    print(f"  submission_type: {bq_sub.submission_type}")
    print(f"  transition_lot_id: {bq_sub.transition_lot_id}")
    print(f"  rejected_qty: {bq_sub.rejected_qty}")
    
    # Check transition lot
    if bq_sub.transition_lot_id:
        trans_stock = TotalStockModel.objects.filter(lot_id=bq_sub.transition_lot_id).first()
        if trans_stock:
            print(f"  ✅ Transition TotalStockModel exists: {bq_sub.transition_lot_id}")
            print(f"     total_stock: {trans_stock.total_stock}")
            print(f"     brass_qc_rejection: {trans_stock.brass_qc_rejection}")
            print(f"     next_process_module: {trans_stock.next_process_module}")
        else:
            print(f"  ❌ Transition TotalStockModel NOT found")
        
        trans_trays = IQFTrayId.objects.filter(lot_id=bq_sub.transition_lot_id)
        print(f"  IQFTrayId count for transition: {trans_trays.count()}")
        if trans_trays.exists():
            for t in trans_trays:
                print(f"    - {t.tray_id}: qty={t.tray_quantity}, top={t.top_tray}")
else:
    print(f"❌ No Brass_QC_Submission for {accept_child}")

print(f"\n=== IQF QUERYSET SIMULATION ===")
# Simulate IQF pick table query
iqf_candidates = TotalStockModel.objects.filter(
    Q(send_brass_audit_to_iqf=True) | Q(brass_qc_rejection=True, last_process_module='Brass QC')
).exclude(
    Q(is_split=True) | Q(remove_lot=True)
).exclude(
    brass_qc_transition_reject_lot_id__isnull=False
).filter(
    Q(lot_id=parent_lot) | Q(lot_id=accept_child) | Q(lot_id__contains='172715') | Q(lot_id__contains='172601')
).values_list('lot_id', 'brass_qc_rejection', 'send_brass_audit_to_iqf', 'is_split', 'remove_lot', 'last_process_module')

print(f"IQF candidates matching user's lots:")
for row in iqf_candidates:
    print(f"  {row}")

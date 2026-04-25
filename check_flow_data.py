import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Submission

# From user:
# 1. IS partial submit: parent=LID240420261726140001
# Real match seems to be LID240420262221087256 (ID 38) or similar.
# Let's look at LID240420262215330001 (Parent) -> Partial Accept -> LID20260424221653000001 (Child)

parent_id = 'LID240420262215330001'
child_id = 'LID20260424221653000001'

print(f"--- Checking Flow for Parent {parent_id} and Child {child_id} ---")

# 1. Start: Parent
p_stock = TotalStockModel.objects.filter(lot_id=parent_id).first()
if p_stock:
    print(f"Parent {parent_id}: Split={p_stock.is_split}, Rem={p_stock.remove_lot}, NextProc={p_stock.next_process_module}")

# 2. Child created from IS Partial
c_stock = TotalStockModel.objects.filter(lot_id=child_id).first()
if c_stock:
    print(f"Child {child_id}: Split={c_stock.is_split}, Rem={c_stock.remove_lot}, NextProc={c_stock.next_process_module}, LastProc={c_stock.last_process_module}, BQ_Rej={c_stock.brass_qc_rejection}")

# 3. Brass QC on Child
bq_on_child = Brass_QC_Submission.objects.filter(lot_id=child_id).first()
if bq_on_child:
    print(f"Brass QC Submission on Child found: Type={bq_on_child.submission_type}, Transition={bq_on_child.transition_lot_id}")
    if bq_on_child.transition_lot_id:
        t_stock = TotalStockModel.objects.filter(lot_id=bq_on_child.transition_lot_id).first()
        if t_stock:
             print(f"Transition {bq_on_child.transition_lot_id}: Split={t_stock.is_split}, Rem={t_stock.remove_lot}, NextProc={t_stock.next_process_module}, LastProc={t_stock.last_process_module}, BQ_Rej={t_stock.brass_qc_rejection}")
else:
    print("NO Brass QC submission found for this child.")

# 4. Brass QC on Parent? (The user said IQF is showing parent)
bq_on_parent = Brass_QC_Submission.objects.filter(lot_id=parent_id).first()
if bq_on_parent:
    print(f"Brass QC Submission on Parent found: Type={bq_on_parent.submission_type}, Transition={bq_on_parent.transition_lot_id}")

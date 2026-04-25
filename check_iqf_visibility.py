import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

# Identify current parent and its children from recent records
# Based on previous output:
# ID: 112 | Parent: LID240420262221087256 | Trans: LID20260424222341025647 (FULL REJECT)

parent_lot = 'LID240420262221087256'
trans_lot = 'LID20260424222341025647'

print(f"--- Investigation for Parent: {parent_lot} ---")

# Simulate the IQF queryset logic
def run_iqf_filter():
    return TotalStockModel.objects.filter(
        Q(send_brass_audit_to_iqf=True) | Q(brass_qc_rejection=True, last_process_module='Brass QC')
    ).exclude(
        Q(is_split=True) | Q(remove_lot=True)
    ).exclude(
        brass_qc_transition_reject_lot_id__isnull=False
    )

iqf_set = run_iqf_filter()
print(f"Total IQF Candidates: {iqf_set.count()}")

target_parent = iqf_set.filter(lot_id=parent_lot).first()
if target_parent:
    print(f"❌ Parent {parent_lot} IS in IQF list!")
    print(f"   Fields: send_brass_audit_to_iqf={target_parent.send_brass_audit_to_iqf}, brass_qc_rejection={target_parent.brass_qc_rejection}, last_proc={target_parent.last_process_module}, is_split={target_parent.is_split}, remove_lot={target_parent.remove_lot}")
else:
    print(f"✅ Parent {parent_lot} is NOT in IQF list.")

target_trans = iqf_set.filter(lot_id=trans_lot).first()
if target_trans:
    print(f"✅ Transition {trans_lot} IS in IQF list.")
    print(f"   Fields: send_brass_audit_to_iqf={target_trans.send_brass_audit_to_iqf}, brass_qc_rejection={target_trans.brass_qc_rejection}, last_proc={target_trans.last_process_module}, is_split={target_trans.is_split}, remove_lot={target_trans.remove_lot}")
else:
    print(f"❌ Transition {trans_lot} is NOT in IQF list!")
    # Check why it might be missing
    obj = TotalStockModel.objects.filter(lot_id=trans_lot).first()
    if obj:
        print(f"   Reason investigation for missing transition:")
        print(f"   send_brass_audit_to_iqf={obj.send_brass_audit_to_iqf}")
        print(f"   brass_qc_rejection={obj.brass_qc_rejection}")
        print(f"   last_process_module='{obj.last_process_module}'")
        print(f"   is_split={obj.is_split}")
        print(f"   remove_lot={obj.remove_lot}")
        print(f"   brass_qc_transition_reject_lot_id={obj.brass_qc_transition_reject_lot_id}")

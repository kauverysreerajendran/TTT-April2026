import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

# General check of ALL lots that ARE in the IQF candidate list
def run_iqf_filter():
    return TotalStockModel.objects.filter(
        Q(send_brass_audit_to_iqf=True) | Q(brass_qc_rejection=True, last_process_module='Brass QC')
    ).exclude(
        Q(is_split=True) | Q(remove_lot=True)
    ).exclude(
        brass_qc_transition_reject_lot_id__isnull=False
    )

iqf_candidates = run_iqf_filter()
print(f"Listing all {iqf_candidates.count()} candidates currently visible in IQF:")
for c in iqf_candidates:
    print(f"Lot: {c.lot_id} | Qty: {c.total_stock} | LastProc: {c.last_process_module} | BQ_Rej: {c.brass_qc_rejection} | SendAudit: {c.send_brass_audit_to_iqf}")

print("\nChecking for any lot ending in ...7256 (the parent ID the user mentioned)")
p_any = TotalStockModel.objects.filter(lot_id__contains='7256')
for p in p_any:
    print(f"Lot: {p.lot_id} | Split: {p.is_split} | Rem: {p.remove_lot} | LastProc: {p.last_process_module} | BQ_Rej: {p.brass_qc_rejection}")

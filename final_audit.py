import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Submission

# 1. Any lot visible in IQF?
iqf_visible = TotalStockModel.objects.filter(
    Q(send_brass_audit_to_iqf=True) | Q(brass_qc_rejection=True, last_process_module='Brass QC')
).exclude(
    Q(is_split=True) | Q(remove_lot=True)
)

print(f"Lots currently visible in IQF: {[l.lot_id for l in iqf_visible]}")

# 2. Look for ANY parent-like lot that is NOT split/removed but has brass_qc_rejection
potential_zombies = TotalStockModel.objects.filter(
    brass_qc_rejection=True,
    is_split=False,
    remove_lot=False
).exclude(last_process_module='Brass QC')

print(f"\nPotential zombies (BQ Rej but last proc not BQ, and not split):")
for z in potential_zombies:
    print(f"Lot: {z.lot_id} | LastProc: {z.last_process_module} | SendAudit: {z.send_brass_audit_to_iqf}")

# 3. Last 10 submissions in Brass QC
print(f"\nLast 10 Brass QC Submissions:")
for b in Brass_QC_Submission.objects.all().order_by('-id')[:10]:
    print(f"ID: {b.id} | Parent: {b.lot_id} | Trans: {b.transition_lot_id} | Type: {b.submission_type}")

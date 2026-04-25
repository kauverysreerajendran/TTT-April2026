import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

# Search for any lot that is NOT split and NOT removed, but has Qty 100
matches = TotalStockModel.objects.filter(total_stock=100, is_split=False, remove_lot=False)
print(f"Active lots with Qty 100: {matches.count()}")
for m in matches:
    print(f"Lot: {m.lot_id} | LastProc: {m.last_process_module} | BQ_Rej: {m.brass_qc_rejection} | SendAudit: {m.send_brass_audit_to_iqf}")

# Search for any lot that is NOT split and NOT removed, with last_process_module='Input Screening'
input_s = TotalStockModel.objects.filter(last_process_module='Input Screening', is_split=False, remove_lot=False)
print(f"\nActive Input Screening lots (not split): {input_s.count()}")
for i in input_s:
    print(f"Lot: {i.lot_id} | Qty: {i.total_stock}")


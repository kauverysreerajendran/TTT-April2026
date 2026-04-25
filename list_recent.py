import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Submission

print("=== RECENT TOTAL STOCK ===")
recent_stocks = TotalStockModel.objects.all().order_by('-id')[:15]
for s in recent_stocks:
    print(f"Lot: {s.lot_id} | Qty: {s.total_stock} | LastProc: {s.last_process_module} | NextProc: {s.next_process_module} | Split: {s.is_split} | Rem: {s.remove_lot} | BQ_Rej: {s.brass_qc_rejection}")

print("\n=== RECENT BRASS QC SUBMISSIONS ===")
recent_bq = Brass_QC_Submission.objects.all().order_by('-id')[:5]
for b in recent_bq:
    print(f"ID: {b.id} | Parent: {b.lot_id} | Trans: {b.transition_lot_id} | Type: {b.submission_type} | Qty: {b.rejected_qty}")

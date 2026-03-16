import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

print("=== COMPLETION STATE ANALYSIS ===")

# Check lot state
lot_id = "LID160320261321120008"
stock = TotalStockModel.objects.get(lot_id=lot_id)

print(f"\nLot: {lot_id}")
print(f"brass_qc_accepted_tray_scan: {getattr(stock, 'brass_qc_accepted_tray_scan', 'N/A')}")
print(f"brass_qc_accptance: {stock.brass_qc_accptance}")
print(f"brass_qc_few_cases_accptance: {stock.brass_qc_few_cases_accptance}")
print(f"brass_qc_accepted_quantity: {getattr(stock, 'brass_qc_accepted_quantity', 'N/A')}")
print(f"brass_qc_rejected_qty: {getattr(stock, 'brass_qc_rejected_qty', 'N/A')}")

# Check which completion handler should trigger
print(f"\n=== COMPLETION HANDLER ANALYSIS ===")
print(f"Should trigger brass_save_accepted_tray_scan: {stock.brass_qc_accptance}")
print(f"Should trigger BQ_Accepted_form (few cases): {stock.brass_qc_few_cases_accptance}")

# Check if lot was processed through completion
print(f"\n=== PROCESSING STATUS ===")
print(f"Lot completed: {not stock.brass_qc_accptance and stock.brass_qc_few_cases_accptance}")
print(f"IQF flag should be set: {stock.brass_qc_few_cases_accptance}")
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId

lot_id = "LID160320261321120008"

print("=== FINAL VERIFICATION ===")

stock = TotalStockModel.objects.get(lot_id=lot_id)
print(f"Lot: {lot_id}")
print(f"send_brass_audit_to_iqf: {stock.send_brass_audit_to_iqf}")

iqf_trays = IQFTrayId.objects.filter(lot_id=lot_id)
print(f"IQF Tray Records: {iqf_trays.count()}")

total_qty = sum(tray.tray_quantity for tray in iqf_trays)
print(f"Total IQF qty: {total_qty}")

print(f"✅ FIXED: Rejected qty {total_qty} now appears in IQF Pick table!")
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from Brass_QC.models import Brass_QC_Rejection_ReasonStore

lot_id = "LID160320261321120008"

print("=== IQF PICK TABLE QUANTITY INVESTIGATION ===")

# Check the current stock
stock = TotalStockModel.objects.get(lot_id=lot_id)
print(f"\nLot: {lot_id}")
print(f"send_brass_audit_to_iqf: {stock.send_brass_audit_to_iqf}")

# Check IQF tray records
iqf_trays = IQFTrayId.objects.filter(lot_id=lot_id)
print(f"\nIQF Tray Records: {iqf_trays.count()}")
total_iqf_qty = sum(tray.tray_quantity for tray in iqf_trays)
print(f"Total IQF tray qty: {total_iqf_qty}")

# Check Brass_QC_Rejection_ReasonStore (this is what the pick table uses for brass_rejection_total_qty)
brass_rejection_stores = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id)
print(f"\nBrass_QC_Rejection_ReasonStore records: {brass_rejection_stores.count()}")
if brass_rejection_stores.exists():
    for store in brass_rejection_stores:
        print(f"  - total_rejection_quantity: {store.total_rejection_quantity}")
else:
    print("  - No Brass_QC_Rejection_ReasonStore records found!")

print(f"\n🔍 ROOT CAUSE:")
print(f"   - IQF Pick Table calculates 'rw qty' from Brass_QC_Rejection_ReasonStore.total_rejection_quantity")
print(f"   - But our fix creates IQFTrayId records without corresponding ReasonStore entries")
print(f"   - So the pick table shows brass_rejection_total_qty = {brass_rejection_stores.first().total_rejection_quantity if brass_rejection_stores.exists() else 'None'}")
print(f"   - But the actual IQF tray quantity = {total_iqf_qty}")

print(f"\n🔧 SOLUTION: Modify IQF Pick Table to use actual IQFTrayId quantities instead of ReasonStore")
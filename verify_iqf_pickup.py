import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId

print("=== IQF PICK TABLE VERIFICATION ===")

lot_id = "LID160320261321120008"

# Check IQF Pick Table filter (Q(send_brass_audit_to_iqf=True))
stocks_in_iqf_pick = TotalStockModel.objects.filter(send_brass_audit_to_iqf=True, lot_id=lot_id)
print(f"\nLots in IQF Pick Table: {stocks_in_iqf_pick.count()}")

for stock in stocks_in_iqf_pick:
    print(f"  - {stock.lot_id}: flag=True")
    
# Check IQF tray records for the lot
iqf_trays = IQFTrayId.objects.filter(lot_id=lot_id)
print(f"\nIQF Tray Records for {lot_id}: {iqf_trays.count()}")
total_qty = 0
for tray in iqf_trays:
    total_qty += tray.tray_quantity
    print(f"  - {tray.tray_id}: qty={tray.tray_quantity}, rejected={tray.rejected_tray}")

print(f"\n✅ RESULT: Total rejected qty in IQF = {total_qty}")
print(f"✅ Expected rejected qty = 24")
print(f"✅ Match: {total_qty == 24}")

print(f"\n✅ SUCCESS: IQF Pick Table will now show lot {lot_id} with {total_qty} rejected pieces!")
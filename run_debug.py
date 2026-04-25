import os
import django
from IQF.services.selectors import get_current_trays
from Brass_QC.models import BrassTrayId

lot_id = 'LID240420260921010001'

# First check if BrassTrayId has the trays
brass_trays = BrassTrayId.objects.filter(lot_id=lot_id, rejected_tray=False, delink_tray=False).order_by('tray_id')
print(f"\n=== BrassTrayId Check for {lot_id} ===")
print(f"BrassTrayId records found: {brass_trays.count()}")
for bt in brass_trays:
    print(f"  - {bt.tray_id}: qty={bt.tray_quantity}, top={bt.top_tray}")

# Now test the selector function
tray_data, source, total_qty = get_current_trays(lot_id)

print(f"\n=== get_current_trays Results for {lot_id} ===")
print(f"Source: {source}")
print(f"Tray Count: {len(tray_data)}")
print(f"Total Qty: {total_qty}")
if tray_data:
    for i, tray in enumerate(tray_data, 1):
        print(f"  Tray {i}: {tray['tray_id']} (qty={tray['qty']}, top={tray.get('is_top', False)})")
else:
    print("  No trays found!")

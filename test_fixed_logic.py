import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Rejected_TrayScan, Brass_QC_Rejection_ReasonStore
from BrassAudit.models import Brass_Audit_Rejected_TrayScan, Brass_Audit_Rejection_ReasonStore

print("=== TESTING FIXED LOGIC ===")

lot_id = "LID160320261321120008"

# Replicate the fixed logic from iqf_get_brass_rejection_quantities
stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
use_audit = getattr(stock, 'send_brass_audit_to_iqf', False)

print(f"Lot: {lot_id}")
print(f"send_brass_audit_to_iqf: {use_audit}")

rejection_qty_map = {}

# Check Brass QC rejected trays (primary source for Brass QC → IQF flow)
brass_qc_rejected_trays = Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id)
print(f"\nBrass QC rejected trays: {brass_qc_rejected_trays.count()}")
for tray in brass_qc_rejected_trays:
    reason = tray.rejection_reason.rejection_reason.strip()
    qty = int(tray.rejected_tray_quantity) if tray.rejected_tray_quantity else 0
    print(f"  - {reason}: {qty}")
    if reason in rejection_qty_map:
        rejection_qty_map[reason] += qty
    else:
        rejection_qty_map[reason] = qty

# Check Brass Audit rejected trays (secondary source for Brass Audit → IQF flow)
brass_audit_rejected_trays = Brass_Audit_Rejected_TrayScan.objects.filter(lot_id=lot_id)
print(f"\nBrass Audit rejected trays: {brass_audit_rejected_trays.count()}")
for tray in brass_audit_rejected_trays:
    reason = tray.rejection_reason.rejection_reason.strip()
    qty = int(tray.rejected_tray_quantity) if tray.rejected_tray_quantity else 0
    print(f"  - {reason}: {qty}")
    if reason in rejection_qty_map:
        rejection_qty_map[reason] += qty
    else:
        rejection_qty_map[reason] = qty

# Get lot rejected comment and total from appropriate source
total_rejection_quantity = 0

# Try Brass QC reason store first
brass_qc_reason_store = Brass_QC_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
if brass_qc_reason_store:
    total_rejection_quantity = brass_qc_reason_store.total_rejection_quantity or 0
    print(f"\nBrass QC reason store total: {total_rejection_quantity}")

# Try Brass Audit reason store if no QC data
if total_rejection_quantity == 0:
    brass_audit_reason_store = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).order_by('-id').first()
    if brass_audit_reason_store:
        total_rejection_quantity = brass_audit_reason_store.total_rejection_quantity or 0
        print(f"\nBrass Audit reason store total: {total_rejection_quantity}")

print(f"\n=== RESULT ===")
print(f"rejection_qty_map: {rejection_qty_map}")
print(f"total_rejection_quantity: {total_rejection_quantity}")

total_from_map = sum(rejection_qty_map.values())
print(f"Total from qty_map: {total_from_map}")

if total_rejection_quantity == 24:
    print(f"\n✅ SUCCESS: Fixed logic returns correct rejection quantity = 24!")
    print(f"✅ The 'rw qty' should now display 24 in the IQF Pick Table UI")
else:
    print(f"\n❌ Issue: Logic still returns incorrect quantity: {total_rejection_quantity}")
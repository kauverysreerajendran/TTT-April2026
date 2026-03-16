import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQFTrayId
from Brass_QC.models import Brass_QC_Rejected_TrayScan
from django.contrib.auth.models import User

print("=== TESTING IQF CREATION FIX ===")

lot_id = "LID160320261321120008"

# Get test data
stock = TotalStockModel.objects.get(lot_id=lot_id)
rejected_scans = Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id)

print(f"\nLot: {lot_id}")
print(f"Current state: brass_qc_few_cases_accptance={stock.brass_qc_few_cases_accptance}")
print(f"send_brass_audit_to_iqf={stock.send_brass_audit_to_iqf}")

print("\nRejected scans:")
for scan in rejected_scans:
    print(f"  - {scan.rejected_tray_id}: {scan.rejected_tray_quantity}")

# Get user for testing
user = User.objects.first()

# Simulate the IQF creation logic from BQTrayRejectionAPIView
print("\n=== SIMULATING IQF CREATION ===")
saved_rejections = []
for scan in rejected_scans:
    try:
        qty = int(scan.rejected_tray_quantity or 0)
    except (ValueError, TypeError):
        qty = 0
    if scan.rejected_tray_id and qty > 0:
        saved_rejections.append({'tray_id': scan.rejected_tray_id, 'qty': qty})

print(f"Processed rejections: {saved_rejections}")

if saved_rejections and (stock.brass_qc_few_cases_accptance or stock.brass_qc_rejection):
    # Set the IQF flag 
    stock.send_brass_audit_to_iqf = True
    stock.save(update_fields=['send_brass_audit_to_iqf'])
    print(f"✅ Set send_brass_audit_to_iqf=True")
    
    # Create IQF records for all rejected trays
    iqf_created = 0
    for rejection in saved_rejections:
        tray_id = rejection.get('tray_id')
        qty = rejection.get('qty', 0)
        
        if tray_id and qty > 0:
            # Check if IQF record already exists 
            if not IQFTrayId.objects.filter(lot_id=lot_id, tray_id=tray_id).exists():
                iqf_record = IQFTrayId.objects.create(
                    lot_id=lot_id,
                    tray_id=tray_id,
                    tray_quantity=qty,
                    user=user,
                    rejected_tray=True
                )
                print(f"✅ Created IQFTrayId: {tray_id} (qty={qty})")
                iqf_created += 1
            else:
                print(f"⚠️ IQFTrayId already exists: {tray_id}")
    
    print(f"\n✅ RESULT: Created {iqf_created} IQFTrayId records")

# Verify final state
print(f"\n=== VERIFICATION ===")
iqf_records = IQFTrayId.objects.filter(lot_id=lot_id)
print(f"Total IQFTrayId records: {iqf_records.count()}")
for iqf in iqf_records:
    print(f"  - {iqf.tray_id}: qty={iqf.tray_quantity}, rejected={iqf.rejected_tray}")

print(f"TotalStock.send_brass_audit_to_iqf: {TotalStockModel.objects.get(lot_id=lot_id).send_brass_audit_to_iqf}")
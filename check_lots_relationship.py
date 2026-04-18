import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from BrassAudit.models import Brass_Audit_Submission, Brass_Audit_Rejection_ReasonStore

# Check both lots' full state
for lot_id in ['LID180420261820270011', 'LID613DADF532DC']:
    lot = TotalStockModel.objects.filter(lot_id=lot_id).first()
    if lot:
        print(f"{'='*60}")
        print(f"LOT: {lot_id}")
        print(f"{'='*60}")
        # Print all available fields to avoid AttributeError
        for field in lot._meta.fields:
            name = field.name
            try:
                value = getattr(lot, name)
                if any(x in name for x in ['qty', 'id', 'acceptance', 'module', 'send']):
                    print(f"{name}: {value}")
            except:
                pass
        print()
    else:
        print(f"Lot {lot_id} not found in TotalStockModel")

# Check if there are Brass Audit submissions for these lots
print("\n" + "="*60)
print("BRASS AUDIT SUBMISSIONS")
print("="*60)
for lot_id in ['LID180420261820270011', 'LID613DADF532DC']:
    subs = Brass_Audit_Submission.objects.filter(lot_id=lot_id).order_by('-created_at')
    if subs.exists():
        for sub in subs[:1]:
            print(f"Lot {lot_id}: {sub.submission_type} (created: {sub.created_at})")
    else:
        print(f"Lot {lot_id}: No submissions found")
        
# Check rejection data
print("\n" + "="*60)
print("BRASS AUDIT REJECTION DATA")
print("="*60)
for lot_id in ['LID180420261820270011', 'LID613DADF532DC']:
    rej = Brass_Audit_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
    if rej:
        print(f"Lot {lot_id}: total_rejection={rej.total_rejection_quantity}, batch_rejection={rej.batch_rejection}")
    else:
        print(f"Lot {lot_id}: No rejection data found")

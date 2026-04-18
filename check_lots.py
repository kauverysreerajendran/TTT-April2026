import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel

lots = TotalStockModel.objects.filter(
    lot_id__in=['LID180420261820270011', 'LID613DADF532DC']
).values(
    'lot_id', 'send_brass_audit_to_iqf', 'brass_audit_accptance', 
    'brass_audit_rejection', 'brass_audit_few_cases_accptance'
)

if not lots:
    print("No lots found.")
else:
    for lot in lots:
        print(f"Lot: {lot['lot_id']}")
        print(f"  send_brass_audit_to_iqf: {lot['send_brass_audit_to_iqf']}")
        print(f"  brass_audit_accptance: {lot['brass_audit_accptance']}")
        print(f"  brass_audit_rejection: {lot['brass_audit_rejection']}")
        print(f"  brass_audit_few_cases_accptance: {lot['brass_audit_few_cases_accptance']}")
        print()

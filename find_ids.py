import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from InputScreening.models import IS_PartialAcceptLot, InputScreening_Submitted

# User's mentioned IDs:
# Parent: LID240420261726140001
# Accept Child: LID20260424172715000001

p_id = 'LID240420261726140001'
c_id = 'LID20260424172715000001'

print(f"Searching for Parent like: ...1726140001")
p_match = TotalStockModel.objects.filter(lot_id__contains='1726140001')
for p in p_match:
    print(f"Found: {p.lot_id}")

print(f"\nSearching for Child like: ...172715000001")
c_match = TotalStockModel.objects.filter(lot_id__contains='172715000001')
for c in c_match:
    print(f"Found: {c.lot_id}")

# Check Input Screening Submissions for any lot today
print(f"\nRecent Input Screening Submissions:")
is_subs = InputScreening_Submitted.objects.all().order_by('-id')[:5]
for s in is_subs:
    print(f"ID: {s.id} | Lot: {s.lot_id} | Created: {s.created_at}")

print(f"\nRecent IS Partial Accept records:")
is_parts = IS_PartialAcceptLot.objects.all().order_by('-id')[:5]
for p in is_parts:
    print(f"Parent: {p.parent_lot_id} | New: {p.new_lot_id}")

import os
import django
from django.utils import timezone
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from InputScreening.models import InputScreening_Submitted, IS_PartialAcceptLot

print("=== RECENT IS PARTIAL SUBMISSIONS ===")
recent = InputScreening_Submitted.objects.filter(
    submission_type__icontains='PARTIAL'
).order_by('-created_at')[:10]

for sub in recent:
    print(f"\nIS Submission ID: {sub.id}")
    print(f"  lot_id (parent): {sub.lot_id}")
    print(f"  created_at: {sub.created_at}")
    print(f"  submission_type: {sub.submission_type}")
    
    # Find accept child
    accept_child = IS_PartialAcceptLot.objects.filter(parent_lot_id=sub.lot_id).first()
    if accept_child:
        print(f"  ✅ Accept child: {accept_child.new_lot_id} (qty={accept_child.accepted_qty})")
    
print("\n=== CHECK USER'S REPORTED IDs ===")
user_parent = 'LID240420261726140001'
user_child = 'LID20260424172715000001'

check_parent = InputScreening_Submitted.objects.filter(lot_id=user_parent).first()
if check_parent:
    print(f"✅ Found parent submission: {user_parent}")
    print(f"   created_at: {check_parent.created_at}")
else:
    print(f"❌ Parent NOT found: {user_parent}")

check_child = IS_PartialAcceptLot.objects.filter(new_lot_id=user_child).first()
if check_child:
    print(f"✅ Found accept child: {user_child}")
    print(f"   parent: {check_child.parent_lot_id}")
    print(f"   qty: {check_child.accepted_qty}")
    print(f"   trays: {check_child.accept_trays_count}")
else:
    print(f"❌ Accept child NOT found: {user_child}")

today_str = datetime.now().strftime('%Y%m%d')
print(f"\n=== CHECK LOT ID FORMAT ===")
print(f"Today's date in lot format: {today_str}")
print(f"User's parent lot: {user_parent}")
print(f"User's child lot: {user_child}")

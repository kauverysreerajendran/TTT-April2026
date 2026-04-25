import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from InputScreening.models import IS_PartialAcceptLot, IS_PartialRejectLot

parent_lot = 'LID240420262221087256'

print("--- PARTIAL ACCEPT CHILDREN ---")
pa = IS_PartialAcceptLot.objects.filter(parent_lot_id=parent_lot)
for x in pa:
    print(f"New Lot: {x.new_lot_id}, Qty: {x.accepted_qty}, Trays: {x.trays_snapshot}")

print("\n--- PARTIAL REJECT CHILDREN ---")
pr = IS_PartialRejectLot.objects.filter(parent_lot_id=parent_lot)
for x in pr:
    print(f"New Lot: {x.new_lot_id}, Qty: {x.rejected_qty}, Trays: {x.trays_snapshot}")

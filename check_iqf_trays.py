import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from IQF.models import IQFTrayId

parent_lot = 'LID240420262221087256'
trays = IQFTrayId.objects.filter(lot_id=parent_lot)
print(f"Trays for parent {parent_lot}:")
for t in trays:
    print(f"  {t.tray_id}: qty={t.tray_quantity}, top={t.top_tray}")

child_is = 'LID20260424222207000001'
trays2 = IQFTrayId.objects.filter(lot_id=child_is)
print(f"\nTrays for IS child {child_is}:")
for t in trays2:
    print(f"  {t.tray_id}: qty={t.tray_quantity}, top={t.top_tray}")

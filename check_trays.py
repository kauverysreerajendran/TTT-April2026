import os
import django
from django.db.models import Q

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from IQF.models import IQFTrayId

parent_lot = 'LID240420262221087256'
trans_lot = 'LID20260424222341025647'

print(f"=== Trays for Parent {parent_lot} ===")
p_trays = IQFTrayId.objects.filter(lot_id=parent_lot)
for t in p_trays:
    print(f"  Tray: {t.tray_id} | Qty: {t.tray_quantity} | Top: {t.top_tray}")

print(f"\n=== Trays for Transition {trans_lot} ===")
t_trays = IQFTrayId.objects.filter(lot_id=trans_lot)
for t in t_trays:
    print(f"  Tray: {t.tray_id} | Qty: {t.tray_quantity} | Top: {t.top_tray}")

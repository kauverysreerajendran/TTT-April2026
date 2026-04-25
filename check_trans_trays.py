import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from IQF.models import IQFTrayId

lot = 'LID20260424222341025647'
trays = IQFTrayId.objects.filter(lot_id=lot)
print(f"Trays for transition lot {lot}:")
for t in trays:
    print(f"  {t.tray_id}: qty={t.tray_quantity}, top={t.top_tray}")

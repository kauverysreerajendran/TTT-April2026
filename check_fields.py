import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from InputScreening.models import InputScreening_Submitted

parent_lot = 'LID240420262221087256'
obj = InputScreening_Submitted.objects.filter(lot_id=parent_lot).first()
if obj:
    for field in obj._meta.fields:
        print(f"{field.name}: {getattr(obj, field.name)}")
else:
    print("Not found")

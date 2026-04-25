import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Brass_QC.models import Brass_QC_Submission

lot = 'LID240420262221087256'
obj = Brass_QC_Submission.objects.filter(lot_id=lot).first()
if obj:
    for field in obj._meta.fields:
        print(f"{field.name}: {getattr(obj, field.name)}")
else:
    print("Not found")

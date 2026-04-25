import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Brass_QC.models import Brass_QC_Submission

bq = Brass_QC_Submission.objects.filter(transition_lot_id='LID20260424222341025647').first()
if bq:
    print(f"Lot ID: {bq.lot_id}")
    print(f"Transition Lot ID: {bq.transition_lot_id}")
    print(f"Submission Type: {bq.submission_type}")

import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from InputScreening.models import IS_PartialAcceptLot, InputScreening_Submitted
from Brass_QC.models import Brass_QC_Submission, BrassQC_PartialRejectLot
from IQF.models import IQFTrayId

parent_lot = 'LID240420262221087256'

print('===========================================================')
print(f'PARENT LOT: {parent_lot}')
print('===========================================================')

def print_model_fields(obj):
    if not obj: return
    print(f"--- Fields for {obj._meta.model_name} ---")
    for field in obj._meta.fields:
        val = getattr(obj, field.name)
        print(f"  {field.name}: {val}")

is_sub = InputScreening_Submitted.objects.filter(lot_id=parent_lot).first()
if is_sub:
    print(f'\n[v] IS Submission found')
    print_model_fields(is_sub)
    
    # Check for child lots
    accept_children = IS_PartialAcceptLot.objects.filter(parent_lot_id=parent_lot)
    print(f'\n[box] Accept children: {accept_children.count()}')
    for child in accept_children:
        print_model_fields(child)
        # Check if THIS child lot has TotalStockModel
        child_stock = TotalStockModel.objects.filter(lot_id=child.new_lot_id).first()
        if child_stock:
            print(f'      [v] TotalStockModel exists')
            print_model_fields(child_stock)
            # Check if THIS child was processed by Brass QC
            bq_sub = Brass_QC_Submission.objects.filter(lot_id=child.new_lot_id).first()
            if bq_sub:
                print(f'      [v] Brass_QC_Submission found')
                print_model_fields(bq_sub)
            else:
                print(f'      [x] Brass_QC_Submission NOT found')
        else:
            print(f'      [x] TotalStockModel NOT found')

print(f'\n===========================================================')
print(f'BRASS QC SUBMISSION FOR PARENT: {parent_lot}')
print(f'===========================================================')
bq_parent = Brass_QC_Submission.objects.filter(lot_id=parent_lot).first()
if bq_parent:
    print(f'[v] Found')
    print_model_fields(bq_parent)

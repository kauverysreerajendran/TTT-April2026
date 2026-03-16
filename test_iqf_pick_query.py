import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from modelmasterapp.models import TotalStockModel
from IQF.models import IQF_Rejection_ReasonStore
from Brass_QC.models import Brass_QC_Rejection_ReasonStore
from BrassAudit.models import Brass_Audit_Rejection_ReasonStore
from django.db.models import OuterRef, Subquery, F, Q

lot_id = "LID160320261321120008"

print("=== IQF PICK TABLE QUERY TEST ===")

# Replicate the exact query from IQFPickTableView
brass_rejection_qty_subquery = Brass_QC_Rejection_ReasonStore.objects.filter(
    lot_id=OuterRef('lot_id')
).values('total_rejection_quantity')[:1]

brass_audit_rejection_qty_subquery = Brass_Audit_Rejection_ReasonStore.objects.filter(
    lot_id=OuterRef('lot_id')
).values('total_rejection_quantity')[:1]

iqf_rejection_qty_subquery = IQF_Rejection_ReasonStore.objects.filter(
    lot_id=OuterRef('lot_id')
).values('total_rejection_quantity')[:1]

queryset = TotalStockModel.objects.select_related(
    'batch_id',
    'batch_id__model_stock_no',
    'batch_id__version',
    'batch_id__location'
).filter(
    batch_id__total_batch_quantity__gt=0
).annotate(
    wiping_required=F('batch_id__model_stock_no__wiping_required'),
    brass_rejection_total_qty=brass_rejection_qty_subquery,
    brass_audit_rejection_qty=brass_audit_rejection_qty_subquery,
    iqf_rejection_qty=iqf_rejection_qty_subquery,
).filter(
    Q(send_brass_audit_to_iqf=True)
).exclude(
    Q(brass_audit_accptance=True) |
    Q(iqf_acceptance=True) | 
    Q(iqf_rejection=True) | 
    Q(send_brass_audit_to_iqf=True, brass_audit_onhold_picking=True)|
    Q(iqf_few_cases_acceptance=True, iqf_onhold_picking=False)
)

print(f"Total records in IQF Pick Table query: {queryset.count()}")

# Check our specific lot
our_lot = queryset.filter(lot_id=lot_id).first()
if our_lot:
    print(f"\n✅ Lot {lot_id} FOUND in query!")
    print(f"   brass_rejection_total_qty: {our_lot.brass_rejection_total_qty}")
    print(f"   brass_audit_rejection_qty: {our_lot.brass_audit_rejection_qty}")
    print(f"   iqf_rejection_qty: {our_lot.iqf_rejection_qty}")
    print(f"   send_brass_audit_to_iqf: {our_lot.send_brass_audit_to_iqf}")
    print(f"   brass_audit_accptance: {our_lot.brass_audit_accptance}")
    print(f"   iqf_acceptance: {our_lot.iqf_acceptance}")
    print(f"   iqf_rejection: {our_lot.iqf_rejection}")
    print(f"   brass_audit_onhold_picking: {our_lot.brass_audit_onhold_picking}")
    print(f"   iqf_few_cases_acceptance: {our_lot.iqf_few_cases_acceptance}")
    print(f"   iqf_onhold_picking: {our_lot.iqf_onhold_picking}")
else:
    print(f"\n❌ Lot {lot_id} NOT FOUND in query!")
    
    # Check why it was excluded
    stock = TotalStockModel.objects.get(lot_id=lot_id)
    print(f"\nExclusion checks:")
    print(f"   send_brass_audit_to_iqf: {stock.send_brass_audit_to_iqf}")
    print(f"   brass_audit_accptance: {stock.brass_audit_accptance}")
    print(f"   iqf_acceptance: {stock.iqf_acceptance}")
    print(f"   iqf_rejection: {stock.iqf_rejection}")
    print(f"   brass_audit_onhold_picking: {stock.brass_audit_onhold_picking}")
    print(f"   iqf_few_cases_acceptance: {stock.iqf_few_cases_acceptance}")
    print(f"   iqf_onhold_picking: {stock.iqf_onhold_picking}")
    
    excluded_by_brass_audit = stock.brass_audit_accptance
    excluded_by_iqf_acceptance = stock.iqf_acceptance
    excluded_by_iqf_rejection = stock.iqf_rejection
    excluded_by_onhold = stock.send_brass_audit_to_iqf and stock.brass_audit_onhold_picking
    excluded_by_few_cases = stock.iqf_few_cases_acceptance and not stock.iqf_onhold_picking
    
    print(f"\nExclusion reasons:")
    print(f"   Excluded by brass_audit_accptance: {excluded_by_brass_audit}")
    print(f"   Excluded by iqf_acceptance: {excluded_by_iqf_acceptance}")
    print(f"   Excluded by iqf_rejection: {excluded_by_iqf_rejection}")
    print(f"   Excluded by onhold: {excluded_by_onhold}")
    print(f"   Excluded by few_cases: {excluded_by_few_cases}")

print(f"\nAll lots in IQF Pick Table:")
for item in queryset.values('lot_id', 'brass_rejection_total_qty')[:5]:
    print(f"   {item['lot_id']}: {item['brass_rejection_total_qty']}")
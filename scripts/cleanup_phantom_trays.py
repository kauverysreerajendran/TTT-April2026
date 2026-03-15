"""
One-time cleanup: Remove phantom tray records for lot LID150320262155340004.
JB-A00120 and JB-A00021 were carried over from a previous Brass QC processing
cycle but don't belong to the physical lot (brass_audit_accepted_qty=28).
Run via: manage.py shell < scripts/cleanup_phantom_trays.py
"""
from Jig_Loading.models import JigLoadTrayId
from BrassAudit.models import BrassAuditTrayId
from adminportal.models import TotalStockModel

lot_id = 'LID150320262155340004'
extra_trays = ['JB-A00120', 'JB-A00021']

print('=== BEFORE CLEANUP ===')
jig_before = list(JigLoadTrayId.objects.filter(lot_id=lot_id).values('id', 'tray_id', 'tray_quantity', 'top_tray'))
for t in jig_before:
    print(f"  JigLoadTrayId: id={t['id']} tray={t['tray_id']} qty={t['tray_quantity']} top={t['top_tray']}")

ba_before = list(BrassAuditTrayId.objects.filter(lot_id=lot_id).values('id', 'tray_id', 'tray_quantity', 'top_tray', 'rejected_tray'))
for t in ba_before:
    print(f"  BrassAuditTrayId: id={t['id']} tray={t['tray_id']} qty={t['tray_quantity']} top={t['top_tray']} rej={t['rejected_tray']}")

stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
if stock:
    print(f"\n  TotalStockModel: total_stock={stock.total_stock}, accepted_qty={stock.brass_audit_accepted_qty}, few_cases={stock.brass_audit_few_cases_accptance}")

# --- Cleanup ---
deleted_jig = JigLoadTrayId.objects.filter(lot_id=lot_id, tray_id__in=extra_trays).delete()
print(f'\nDeleted from JigLoadTrayId: {deleted_jig}')

deleted_ba = BrassAuditTrayId.objects.filter(lot_id=lot_id, tray_id__in=extra_trays).delete()
print(f'Deleted from BrassAuditTrayId: {deleted_ba}')

print('\n=== AFTER CLEANUP ===')
jig_after = list(JigLoadTrayId.objects.filter(lot_id=lot_id).values('id', 'tray_id', 'tray_quantity', 'top_tray'))
jig_total = 0
for t in jig_after:
    print(f"  JigLoadTrayId: id={t['id']} tray={t['tray_id']} qty={t['tray_quantity']} top={t['top_tray']}")
    jig_total += t['tray_quantity'] or 0
print(f"  TOTAL qty in JigLoadTrayId: {jig_total}")

ba_after = list(BrassAuditTrayId.objects.filter(lot_id=lot_id).values('id', 'tray_id', 'tray_quantity', 'top_tray', 'rejected_tray'))
ba_total = 0
for t in ba_after:
    print(f"  BrassAuditTrayId: id={t['id']} tray={t['tray_id']} qty={t['tray_quantity']} top={t['top_tray']} rej={t['rejected_tray']}")
    if not t['rejected_tray']:
        ba_total += t['tray_quantity'] or 0
print(f"  Non-rejected total qty in BrassAuditTrayId: {ba_total}")

expected_qty = stock.brass_audit_accepted_qty if stock else None
print(f"\n  Expected (brass_audit_accepted_qty): {expected_qty}")
if expected_qty and jig_total == expected_qty:
    print("  ✅ JigLoadTrayId total matches accepted_qty — cleanup successful!")
else:
    print(f"  ⚠️  Mismatch: JigLoadTrayId={jig_total}, expected={expected_qty}")

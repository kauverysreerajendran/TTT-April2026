from Jig_Loading.models import JigLoadTrayId
from BrassAudit.models import BrassAuditTrayId
lot_id = 'LID150320262155340004'
jig = list(JigLoadTrayId.objects.filter(lot_id=lot_id).values('id', 'tray_id', 'tray_quantity', 'top_tray').order_by('-top_tray', 'tray_id'))
print("JigLoadTrayId:")
total = 0
for t in jig:
    print("  id=%s tray=%s qty=%s top=%s" % (t['id'], t['tray_id'], t['tray_quantity'], t['top_tray']))
    total += t['tray_quantity'] or 0
print("TOTAL = %s (expected 28)" % total)

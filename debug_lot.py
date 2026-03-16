from modelmasterapp.models import TotalStockModel
from Brass_QC.models import Brass_QC_Rejected_TrayScan
from IQF.models import IQFTrayId

lot_id = 'LID160320261321120008'
print(f'=== DEBUGGING LOT {lot_id} ===')

# Check TotalStockModel
stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
if stock:
    print(f'Stock: send_brass_audit_to_iqf={stock.send_brass_audit_to_iqf}')
    print(f'Stock: brass_qc_rejected_qty={getattr(stock, "brass_qc_rejected_qty", "N/A")}')
    print(f'Stock: brass_qc_accptance={stock.brass_qc_accptance}') 
    print(f'Stock: brass_qc_few_cases_accptance={stock.brass_qc_few_cases_accptance}')
else:
    print('No TotalStockModel found')

# Check Brass_QC_Rejected_TrayScan  
rejected_scans = Brass_QC_Rejected_TrayScan.objects.filter(lot_id=lot_id)
print(f'Brass QC Rejected Scans: {rejected_scans.count()}')
for scan in rejected_scans:
    print(f'  - {scan.rejected_tray_id}: {scan.rejected_tray_quantity}')

# Check IQFTrayId
iqf_trays = IQFTrayId.objects.filter(lot_id=lot_id)
print(f'IQF Tray IDs: {iqf_trays.count()}')
for tray in iqf_trays:
    print(f'  - {tray.tray_id}: {tray.tray_quantity} (rejected={tray.rejected_tray})')
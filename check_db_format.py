from Brass_QC.models import BrassTrayId
for r in BrassTrayId.objects.all():
    print(f'START_LOT|{r.lot_id}|END_LOT')

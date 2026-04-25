from Brass_QC.models import BrassTrayId
qs = BrassTrayId.objects.all()
print(f"Queryset length: {len(qs)}")
for r in qs:
    print(r.lot_id)

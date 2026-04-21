from modelmasterapp.models import TrayType
for t in TrayType.objects.all():
    print(f'TrayType: "{t.tray_type}" | capacity: {t.tray_capacity} | color: {t.tray_color}')

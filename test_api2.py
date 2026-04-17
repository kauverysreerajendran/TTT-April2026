import json
from django.test import Client
from django.contrib.auth.models import User

client = Client()
user = User.objects.first()
client.force_login(user)
response = client.get('/brass_qc/api/tray-details/?lot_id=LID160420261628580002', HTTP_ACCEPT='application/json')
print(f'Status: {response.status_code}')
print(f'Content-Type: {response["Content-Type"]}')
body = response.content.decode('utf-8')
print(f'Body length: {len(body)}')
data = json.loads(body)
print(f'Source: {data.get("source")}')
trays = data.get("trays", [])
print(f'Trays: {len(trays)}')
print('Tray details:')
for i, t in enumerate(trays):
    print(f'  [{i}] {t["tray_id"]}: qty={t["qty"]}, top={t["is_top"]}')
print('---')
print('Full JSON:')
print(json.dumps(data, indent=2))

import json
from django.test import RequestFactory, Client
from django.contrib.auth.models import User

# Test via Client (simulates full request cycle with middleware)
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
print(f'Trays: {len(data.get("trays", []))}')
for t in data['trays']:
    print(f'  {t["tray_id"]}: qty={t["qty"]}, top={t["is_top"]}')

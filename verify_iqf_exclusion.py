import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()
from IQF.views import IQFPickTableView
from django.test import RequestFactory
from django.contrib.auth.models import User

# Create a test request
factory = RequestFactory()
request = factory.get('/iqf/iqf_picktable/')
request.user = User.objects.first()

# Get the view response
view = IQFPickTableView()
response = view.get(request)

# Extract master_data from response.data (since it's an APIView with TemplateHTMLRenderer)
try:
    master_data = response.data.get('master_data', [])
    
    print(f"Total lots in IQF Pick Table: {len(master_data)}")
    print()
    
    for data in master_data:
        print(f"Lot ID: {data.get('stock_lot_id')}")
        print(f"  Batch: {data.get('batch_id')}")
        print(f"  Status: {data.get('lot_status')}")
        print(f"  send_brass_audit_to_iqf: {data.get('send_brass_audit_to_iqf')}")
        print()
        
    found_parent = any(data.get('stock_lot_id') == 'LID180420261820270011' for data in master_data)
    found_child = any(data.get('stock_lot_id') == 'LID613DADF532DC' for data in master_data)
    
    print(f"Parent lot LID180420261820270011 excluded: {not found_parent}")
    print(f"Child lot LID613DADF532DC included: {found_child}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

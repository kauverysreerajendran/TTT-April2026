import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from IQF.views import iqf_get_brass_rejection_quantities
from django.test import RequestFactory

print("=== TESTING FIXED API ===")

# Create a mock request
factory = RequestFactory()
request = factory.get('/iqf/iqf_get_brass_rejection_quantities/', {'lot_id': 'LID160320261321120008'})

# Call the API function
response = iqf_get_brass_rejection_quantities(request)

# Handle both Response object and raw data
if hasattr(response, 'data'):
    data = response.data
else:
    # If it's a raw dict response
    data = response

print(f"API Response:")
print(f"  success: {data.get('success') if isinstance(data, dict) else 'N/A'}")
print(f"  total_rejection_quantity: {data.get('total_rejection_quantity') if isinstance(data, dict) else 'N/A'}")
print(f"  brass_rejection_qty_map: {data.get('brass_rejection_qty_map') if isinstance(data, dict) else 'N/A'}")
print(f"  lot_rejected_comment: {data.get('lot_rejected_comment') if isinstance(data, dict) else 'N/A'}")

# Also print response type for debugging
print(f"Response type: {type(response)}")
if hasattr(response, 'data'):
    print(f"Response.data: {response.data}")

if isinstance(data, dict) and data.get('total_rejection_quantity') == 24:
    print(f"\n✅ SUCCESS: API now returns correct rejection quantity = 24!")
    print(f"✅ The 'rw qty' should now display 24 in the IQF Pick Table UI")
else:
    print(f"\n❌ Issue: API still returns incorrect or no data")
import django; django.setup()
from IQF.views import IQFPickTableView
from django.test import RequestFactory
from django.contrib.auth.models import User
factory = RequestFactory()
request = factory.get('/iqf/pick_table/')
request.user = User.objects.first()
view = IQFPickTableView()
view.request = request
view.kwargs = {}
response = view.get(request)
context = response.context_data if hasattr(response, 'context_data') else {}
master_data = context.get('master_data', [])
test_lot = next((d for d in master_data if d.get('stock_lot_id') == 'LID170420262225370001'), None)
if test_lot:
    print(f"FOUND LOT: {test_lot['stock_lot_id']}")
    print(f"   no_of_trays: {test_lot.get('no_of_trays')}")
    print(f"   rw_qty: {test_lot.get('rw_qty')}")
    print(f"   tray_type: {test_lot.get('tray_type')}")
    print(f"   tray_capacity: {test_lot.get('tray_capacity')}")
else:
    print('Lot LID170420262225370001 not found')

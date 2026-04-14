"""Quick profiler for JigView.get_context_data()"""
import os, sys, time, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from Jig_Loading.views import JigView

factory = RequestFactory()
request = factory.get('/Jig_Loading/JigView/')
user = User.objects.first()
request.user = user

t0 = time.time()
view = JigView()
view.request = request
view.kwargs = {}
view.args = ()
ctx = view.get_context_data()
t1 = time.time()

page = ctx.get('page_obj')
count = len(list(page)) if page else 0
print(f"get_context_data total: {t1 - t0:.3f}s")
print(f"page_obj items: {count}")

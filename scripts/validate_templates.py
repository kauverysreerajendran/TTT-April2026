import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'watchcase_tracker.settings'
django.setup()
from django.template.loader import get_template

templates = [
    'IQF/Iqf_PickTable.html',
    'IQF/Iqf_AcceptTable.html',
    'IQF/Iqf_Completed.html',
    'IQF/Iqf_RejectTable.html',
    'IQF/Iqf_RejectionTable.html',
]
for t in templates:
    get_template(t)
    print(f'  OK: {t}')
print('All templates valid.')

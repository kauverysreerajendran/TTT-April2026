import os
import django

# Set up Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')  # Replace 'your_project_name' with 'watchcase_tracker'
django.setup()

from modelmasterapp.models import *
from Jig_Loading.models import *
from Brass_QC.models import *
from BrassAudit.models import *
from InputScreening.models import *
from django.db import transaction
from django.contrib.auth import get_user_model
from datetime import datetime

def clear_database():
    """
    Deletes all records from the specified models.
    """
    # Delete all records
    TotalStockModel.objects.all().delete()
    ModelMasterCreation.objects.all().delete()
    TrayAutoSaveData.objects.all().delete()
    Jig.objects.all().delete()
    JigLoadingManualDraft.objects.all().delete()
    JigCompleted.objects.all().delete()
    JigAutoSave.objects.all().delete()
    Brass_QC_Draft_Store.objects.all().delete()
    TrayId.objects.all().delete()

    # Brass_QC additional tables
    Brass_TopTray_Draft_Store.objects.all().delete()
    Brass_QC_Rejected_TrayScan.objects.all().delete()
    Brass_QC_Rejection_ReasonStore.objects.all().delete()

    # BrassAudit tables
    BrassAuditTrayId.objects.all().delete()
    Brass_Audit_Accepted_TrayID_Store.objects.all().delete()
    Brass_Audit_Rejection_ReasonStore.objects.all().delete()

    # InputScreening tables
    IP_Accepted_TrayID_Store.objects.all().delete()
    IP_Rejected_TrayScan.objects.all().delete()
    IP_Rejection_ReasonStore.objects.all().delete()
    IP_Rejection_Draft.objects.all().delete()

    print("✅ All specified model data deleted successfully.")

def load_trays():
    """
    Create trays for prefixes NR, JR, ND, JD, NL, JL, NB, JB (default 500 each).
    """
    prefixes = ['NR', 'JR', 'ND', 'JD', 'NL', 'JL', 'NB', 'JB']
    per_prefix = 500  # default count

    normal_tt = TrayType.objects.filter(tray_type__iexact='Normal').first()
    jumbo_tt = TrayType.objects.filter(tray_type__iexact='Jumbo').first()
    normal_cap = int(getattr(normal_tt, 'tray_capacity', 16) or 16)
    jumbo_cap = int(getattr(jumbo_tt, 'tray_capacity', 12) or 12)
    normal_label = normal_tt.tray_type if normal_tt else 'Normal'
    jumbo_label = jumbo_tt.tray_type if jumbo_tt else 'Jumbo'
    admin_user = get_user_model().objects.filter(is_superuser=True).first()

    total_created = 0
    with transaction.atomic():
        for p in prefixes:
            cap = normal_cap if p.startswith('N') else jumbo_cap
            label = normal_label if p.startswith('N') else jumbo_label
            to_create = []
            for i in range(1, per_prefix + 1):
                tid = f"{p}-A{i:05d}"
                if TrayId.objects.filter(tray_id=tid).exists():
                    continue
                to_create.append(TrayId(
                    tray_id=tid,
                    tray_type=label,
                    tray_capacity=cap,
                    new_tray=True,
                    scanned=False,
                    user=admin_user,
                ))
            if to_create:
                TrayId.objects.bulk_create(to_create, batch_size=500)
            created = len(to_create)
            print(f'{p}: created {created}')
            total_created += created

    print(f'TOTAL CREATED: {total_created}')

if __name__ == "__main__":
    clear_database()
    load_trays()  # Now attached directly
    
    # Now run all other files
    import subprocess
    import sys
    
    python_exe = sys.executable
    
    scripts_to_run = [
        "Jig_Loading/Jig_Id.py",
    ]
    
    for script in scripts_to_run:
        print(f"Running {script}...")
        try:
            subprocess.run([python_exe, script], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running {script}: {e}")
    
    print("All scripts executed.")
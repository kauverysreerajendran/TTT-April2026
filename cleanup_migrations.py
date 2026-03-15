"""
Django Migration Cleanup Script
Run this from your project root: python cleanup_migrations.py

This will delete all migration files EXCEPT __init__.py in each app
"""
import os
from pathlib import Path

# List of apps to clean
APPS = [
    'Jig_Loading',
    'Jig_Unloading',
    'JigUnloading_Zone2',
    'Recovery_DP',
    'Recovery_IS',
    'Recovery_Brass_QC',
    'Recovery_BrassAudit',
    'Recovery_IQF',
    'Brass_QC',
    'BrassAudit',
    'IQF',
    'DayPlanning',
    'InputScreening',
    'Inprocess_Inspection',
    'Nickel_Inspection',
    'nickel_inspection_zone_two',
    'Nickel_Audit',
    'nickel_audit_zone_two',
    'Spider_Spindle',
    'Spider_Spindle_zone_two',
    'adminportal',
    'modelmasterapp',
    'ReportsModule',
]

def cleanup_migrations():
    """Delete all migration files except __init__.py"""
    deleted_count = 0
    
    for app in APPS:
        migrations_dir = Path(app) / 'migrations'
        
        if not migrations_dir.exists():
            print(f"⚠️  {app}/migrations/ not found, skipping...")
            continue
        
        print(f"\n📂 Checking {app}/migrations/...")
        
        for file in migrations_dir.glob('*.py'):
            if file.name == '__init__.py':
                print(f"   ✓ Keeping {file.name}")
                continue
            
            try:
                file.unlink()
                print(f"   ✗ Deleted {file.name}")
                deleted_count += 1
            except Exception as e:
                print(f"   ❌ Error deleting {file.name}: {e}")
        
        # Also delete .pyc files
        for file in migrations_dir.glob('*.pyc'):
            try:
                file.unlink()
                deleted_count += 1
            except:
                pass
    
    print(f"\n✅ Cleanup complete! Deleted {deleted_count} files.")
    print("\nNext steps:")
    print("1. Drop and recreate your database")
    print("2. Run: python manage.py makemigrations")
    print("3. Run: python manage.py migrate")

if __name__ == '__main__':
    response = input("⚠️  This will DELETE all migration files (except __init__.py). Continue? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        cleanup_migrations()
    else:
        print("Cancelled.")
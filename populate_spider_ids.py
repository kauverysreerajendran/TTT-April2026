"""
Script to populate Spider_ID master table with 200 records
Zone 1: S098-0001 to S098-0100 (100 records)
Zone 2: S144-0001 to S144-0100 (100 records)
"""

import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Spider_Spindle.models import Spider_ID

def populate_spider_ids():
    """Populate Spider_ID table with Zone 1 and Zone 2 IDs"""
    
    print("🔄 Starting Spider_ID population...")
    
    # Check if already populated
    existing_count = Spider_ID.objects.count()
    if existing_count > 0:
        print(f"⚠️  Spider_ID table already has {existing_count} records.")
        response = input("Do you want to continue and add more? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Aborted.")
            return
    
    spider_ids_to_create = []
    
    # Generate Zone 1 IDs (S098-0001 to S098-0100)
    print("\n📍 Generating Zone 1 IDs (S098-0001 to S098-0100)...")
    for i in range(1, 101):
        spider_code = f"S098-{i:04d}"
        spider_ids_to_create.append(
            Spider_ID(spider_code=spider_code, zone=1, is_active=True)
        )
    
    # Generate Zone 2 IDs (S144-0001 to S144-0100)
    print("📍 Generating Zone 2 IDs (S144-0001 to S144-0100)...")
    for i in range(1, 101):
        spider_code = f"S144-{i:04d}"
        spider_ids_to_create.append(
            Spider_ID(spider_code=spider_code, zone=2, is_active=True)
        )
    
    # Bulk create all records
    try:
        print(f"\n💾 Inserting {len(spider_ids_to_create)} records into database...")
        created_objects = Spider_ID.objects.bulk_create(
            spider_ids_to_create,
            batch_size=100,
            ignore_conflicts=True
        )
        
        total_count = Spider_ID.objects.count()
        zone1_count = Spider_ID.objects.filter(zone=1).count()
        zone2_count = Spider_ID.objects.filter(zone=2).count()
        
        print("\n✅ Population completed successfully!")
        print(f"📊 Statistics:")
        print(f"   Total Records: {total_count}")
        print(f"   Zone 1 Records: {zone1_count}")
        print(f"   Zone 2 Records: {zone2_count}")
        
        # Show sample records
        print("\n📌 Sample Records:")
        print("\n   Zone 1 (First 3):")
        for spider_id in Spider_ID.objects.filter(zone=1).order_by('spider_code')[:3]:
            print(f"      {spider_id.spider_code} - Zone {spider_id.zone}")
        
        print("\n   Zone 2 (First 3):")
        for spider_id in Spider_ID.objects.filter(zone=2).order_by('spider_code')[:3]:
            print(f"      {spider_id.spider_code} - Zone {spider_id.zone}")
        
        print("\n   Zone 1 (Last 3):")
        for spider_id in Spider_ID.objects.filter(zone=1).order_by('spider_code').reverse()[:3]:
            print(f"      {spider_id.spider_code} - Zone {spider_id.zone}")
        
        print("\n   Zone 2 (Last 3):")
        for spider_id in Spider_ID.objects.filter(zone=2).order_by('spider_code').reverse()[:3]:
            print(f"      {spider_id.spider_code} - Zone {spider_id.zone}")
        
    except Exception as e:
        print(f"\n❌ Error occurred: {str(e)}")
        raise

if __name__ == '__main__':
    populate_spider_ids()

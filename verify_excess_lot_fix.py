#!/usr/bin/env python3
"""
Verification script for excess lot fixes.
Run this to verify the changes work correctly.
"""

import os
import sys
import django

# Setup Django environment
sys.path.append('a:\\Workspace\\Watchcase\\TTT-Jan2026')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

from Jig_Loading.models import JigCompleted, JigLoadTrayId
from modelmasterapp.models import TotalStockModel

def verify_excess_lot_fixes():
    print("🔍 Verifying Excess Lot Fixes")
    print("=" * 50)
    
    # Find any excess lots (partial_lot_id exists)
    excess_lots = JigCompleted.objects.filter(
        partial_lot_id__isnull=False,
        half_filled_tray_info__isnull=False
    ).exclude(half_filled_tray_info=[])
    
    print(f"Found {excess_lots.count()} excess lots with partial_lot_id:")
    
    for lot in excess_lots:
        print(f"\n📋 Original Lot: {lot.lot_id}")
        print(f"   Excess Lot: {lot.partial_lot_id}")
        print(f"   Batch: {lot.batch_id}")
        
        # Verify half_filled_tray_info structure
        half_filled = lot.half_filled_tray_info or []
        total_cases = sum(t.get('cases', 0) for t in half_filled)
        
        print(f"   Half-filled trays: {len(half_filled)}")
        print(f"   Total cases: {total_cases}")
        
        for i, tray in enumerate(half_filled):
            tray_id = tray.get('tray_id', 'Unknown')
            cases = tray.get('cases', 0)
            top_tray = tray.get('top_tray', False)
            print(f"     Tray {i+1}: {tray_id} → {cases} cases (top_tray: {top_tray})")
        
        # Check if excess lot exists in TotalStockModel
        excess_stock = TotalStockModel.objects.filter(lot_id=lot.partial_lot_id).first()
        if excess_stock:
            print(f"   ✅ Excess lot found in TotalStockModel")
            print(f"   ✅ Stock quantity: {excess_stock.total_stock}")
            print(f"   ✅ Completed status: {excess_stock.Jig_Load_completed}")
        else:
            print(f"   ❌ Excess lot NOT found in TotalStockModel")
        
        # Check JigLoadTrayId entries
        jig_tray_ids = JigLoadTrayId.objects.filter(lot_id=lot.partial_lot_id)
        print(f"   JigLoadTrayId entries: {jig_tray_ids.count()}")
        
        for jtid in jig_tray_ids:
            print(f"     {jtid.tray_id} → {jtid.tray_quantity} (top_tray: {jtid.top_tray})")
    
    if not excess_lots.exists():
        print("ℹ️  No excess lots found. Create one through Jig submission to test.")
    
    print("\n" + "=" * 50)
    print("🔧 Quick Test Commands:")
    print("\n# Test view icon for excess lot:")
    print("curl 'http://127.0.0.1:8000/jig_loading/tray-info/?lot_id=EXCESS_LOT_ID&batch_id=BATCH_ID'")
    print("\n# Check Pick Table for duplicate/missing lots:")
    print("Visit: http://127.0.0.1:8000/jig_loading/")
    
if __name__ == '__main__':
    verify_excess_lot_fixes()
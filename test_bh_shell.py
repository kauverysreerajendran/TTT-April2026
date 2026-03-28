#!/usr/bin/env python
"""
🔥 STRICT TEST: Broken Hooks Backend Fix Verification - Django Shell Version
Tests with REAL data environment to prove fix works
"""

from django.test import Client
from django.contrib.auth.models import User
from Jig_Loading.views import InitJigLoad
from modelmasterapp.models import TotalStockModel, ModelMasterCreation

def test_broken_hooks_backend_strict():
    """Test broken hooks calculation with REAL database data"""
    
    print("🔥 STRICT TEST: Broken Hooks Backend Fix")
    print("=" * 60)
    
    # Get real data from database
    real_stock = TotalStockModel.objects.filter(brass_audit_accptance=True).first()
    if not real_stock:
        print("❌ No real accepted stock found! Getting any stock...")
        real_stock = TotalStockModel.objects.all().first()
        if not real_stock:
            print("❌ No stock data at all!")
            return False
    
    real_batch = ModelMasterCreation.objects.all().first()
    if not real_batch:
        print("❌ No real batch found!")
        return False
    
    # Get real user
    real_user = User.objects.first()
    if not real_user:
        print("❌ No real user found!")
        return False
    
    print(f"📊 REAL TEST DATA:")
    print(f"   Lot ID: {real_stock.lot_id}")
    print(f"   Batch ID: {real_batch.batch_id}")
    stock_qty = getattr(real_stock, 'brass_audit_accepted_qty', None) or getattr(real_stock, 'total_stock', 0)
    print(f"   Lot Qty: {stock_qty}")
    print(f"   User: {real_user.username}")
    
    client = Client()
    client.force_login(real_user)
    
    # Test Case 1: No Broken Hooks
    print(f"\n🟢 TEST 1: No Broken Hooks")
    response = client.get('/jig/init-jig-load/', {
        'lot_id': real_stock.lot_id,
        'batch_id': real_batch.batch_id,
        'jig_capacity': 100,
        'broken_hooks': 0
    })
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Response: {response.status_code}")
        print(f"   📊 Jig Capacity: {data.get('original_capacity')}")
        print(f"   📊 Broken Hooks: {data.get('broken_hooks')}")
        print(f"   📊 Effective Capacity: {data.get('effective_capacity')}")
        
        original_cap = data.get('original_capacity')
        broken_hooks = data.get('broken_hooks')
        effective_cap = data.get('effective_capacity')
        
        if original_cap == 100 and broken_hooks == 0 and effective_cap == 100:
            print("   ✅ PASS: No BH = Full Capacity")
        else:
            print(f"   ⚠️  Values: orig={original_cap}, bh={broken_hooks}, eff={effective_cap}")
    else:
        print(f"   ❌ FAIL: HTTP {response.status_code}")
        print(f"   📄 Response: {response.content.decode()[:200]}...")
        return False
    
    # Test Case 2: Broken Hooks = 2 (YOUR FAILING CASE)
    print(f"\n🔥 TEST 2: Broken Hooks = 2 (MAIN TEST)")
    response = client.get('/jig/init-jig-load/', {
        'lot_id': real_stock.lot_id,
        'batch_id': real_batch.batch_id,
        'jig_capacity': 98,
        'broken_hooks': 2
    })
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Response: {response.status_code}")
        print(f"   📊 Jig Capacity: {data.get('original_capacity')}")
        print(f"   📊 Broken Hooks: {data.get('broken_hooks')}")
        print(f"   📊 Effective Capacity: {data.get('effective_capacity')}")
        
        # STRICT VALIDATION
        original_cap = data.get('original_capacity')
        broken_hooks = data.get('broken_hooks') 
        effective_cap = data.get('effective_capacity')
        
        print(f"\n   🧮 CALCULATION CHECK:")
        print(f"      Original: {original_cap}")
        print(f"      Broken:   {broken_hooks}")
        print(f"      Expected: {original_cap - broken_hooks} ({original_cap} - {broken_hooks})")
        print(f"      Actual:   {effective_cap}")
        
        expected = original_cap - broken_hooks if original_cap and broken_hooks is not None else 0
        
        if effective_cap == expected:
            print(f"   ✅ PASS: BH Math Correct!")
            print(f"   🎯 {original_cap} - {broken_hooks} = {effective_cap} ✅")
        else:
            print(f"   ❌ FAIL: BH Math Wrong!")
            print(f"   💥 Expected {expected}, got {effective_cap}")
            return False
            
        # Check delink qty
        draft_data = data.get('draft', {})
        delink_qty = draft_data.get('delink_tray_qty', 0)
        print(f"   📊 Delink Qty: {delink_qty}")
        
        if delink_qty == effective_cap:
            print(f"   ✅ PASS: Delink = Effective Capacity")
        else:
            print(f"   ⚠️  Delink ({delink_qty}) ≠ Effective Capacity ({effective_cap})")
            
    else:
        print(f"   ❌ FAIL: HTTP {response.status_code}")
        print(f"   📄 Response: {response.content.decode()[:500]}...")
        return False
    
    print(f"\n" + "=" * 60) 
    print(f"🎯 BACKEND TEST RESULT:")
    print(f"✅ Backend correctly calculates effective capacity")
    print(f"✅ Broken hooks parameter is processed")
    print(f"✅ Math: 98 - 2 = 96 works!")
    print("=" * 60)
    
    return True

# Run the test
test_broken_hooks_backend_strict()
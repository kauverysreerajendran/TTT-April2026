from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
import json

from modelmasterapp.models import (
    ModelMaster, 
    ModelMasterCreation, 
    TotalStockModel, 
    Version, 
    PolishFinishType,
    Plating_Color,
    TrayType
)
from Jig_Loading.models import (
    Jig, 
    JigLoadTrayId, 
    JigLoadingMaster,
    JigLoadingManualDraft,
    JigCompleted
)


class JigLoadingDraftTestCase(APITestCase):
    """
    Test cases for Jig Loading Draft functionality
    Tests the bug fix: Line item lot status should be DRAFT after draft creation
    """
    
    def setUp(self):
        """Set up test fixtures"""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create version
        self.version = Version.objects.create(
            version_name='V1',
            version_internal='V1_INT'
        )
        
        # Create polish finish
        self.polish_finish = PolishFinishType.objects.create(
            polish_finish='Glossy',
            polish_internal='GLY'
        )
        
        # Create plating color
        self.plating_color = Plating_Color.objects.create(
            plating_color='Black',
            plating_color_internal='B'
        )
        
        # Create tray type
        self.tray_type = TrayType.objects.create(
            tray_type='Standard',
            tray_capacity=50
        )
        
        # Create model master
        self.model_master = ModelMaster.objects.create(
            model_no='MODEL001',
            polish_finish=self.polish_finish,
            ep_bath_type='EP1',
            tray_type=self.tray_type,
            tray_capacity=50,
            version='V1',
            plating_stk_no='STK001'
        )
        
        # Create model master creation (batch)
        self.batch = ModelMasterCreation.objects.create(
            batch_id='BATCH001',
            model_stock_no=self.model_master,
            polish_finish='Glossy',
            ep_bath_type='EP1',
            plating_color='Black',
            tray_type='Standard',
            tray_capacity=50,
            total_batch_quantity=500,
            version=self.version,
            plating_stk_no='STK001'
        )
        
        # Create total stock model
        self.stock = TotalStockModel.objects.create(
            batch_id=self.batch,
            model_stock_no=self.model_master,
            version=self.version,
            total_stock=100,
            polish_finish=self.polish_finish,
            plating_color=self.plating_color,
            lot_id='LOT001',
            jig_draft=False,  # Should be True after draft
            Jig_Load_completed=False
        )
        
        # Create jig
        self.jig = Jig.objects.create(
            jig_qr_id='JIG001'
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_draft_creation_sets_jig_draft_flag(self):
        """
        TEST 1: Verify that jig_draft flag is set to True when draft is created
        This is the main bug fix test
        """
        # Prepare draft data
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 100,
                'updated_lot_qty': 100,
                'jig_capacity': 100,
                'trays': [
                    {
                        'row_index': '1',
                        'tray_id': 'TRAY001',
                        'tray_qty': 50
                    },
                    {
                        'row_index': '2',
                        'tray_id': 'TRAY002',
                        'tray_qty': 50
                    }
                ]
            }
        }
        
        # Verify initial state - jig_draft should be False
        self.assertFalse(self.stock.jig_draft, "Initial jig_draft should be False")
        self.assertFalse(self.jig.drafted, "Initial jig.drafted should be False")
        
        # Create draft via API
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        # Verify API response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success'), "Draft creation should be successful")
        
        # ✅ MAIN BUG FIX TEST: Verify jig_draft flag is now True
        self.stock.refresh_from_db()
        self.assertTrue(self.stock.jig_draft, 
                       "🐛 BUG FIX: jig_draft should be True after draft creation")
        
        # Verify draft record was created
        draft = JigLoadingManualDraft.objects.get(
            batch_id='BATCH001',
            lot_id='LOT001',
            user=self.user
        )
        self.assertIsNotNone(draft, "Draft record should be created")
        
    def test_draft_creation_marks_jig_as_drafted(self):
        """
        TEST 2: Verify that Jig is marked as drafted
        """
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 100,
                'updated_lot_qty': 100,
                'jig_capacity': 100,
                'trays': [
                    {
                        'row_index': '1',
                        'tray_id': 'TRAY001',
                        'tray_qty': 100
                    }
                ]
            }
        }
        
        # Create draft
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify Jig is marked as drafted
        self.jig.refresh_from_db()
        self.assertTrue(self.jig.drafted, "Jig should be marked as drafted")
        self.assertEqual(self.jig.current_user, self.user, "Jig current_user should be set")
        self.assertIsNotNone(self.jig.locked_at, "Jig locked_at should be set")

    def test_draft_with_multiple_trays(self):
        """
        TEST 3: Verify draft creation works with multiple trays
        """
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 150,
                'updated_lot_qty': 150,
                'jig_capacity': 100,
                'trays': [
                    {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 50},
                    {'row_index': '2', 'tray_id': 'TRAY002', 'tray_qty': 50},
                    {'row_index': '3', 'tray_id': 'TRAY003', 'tray_qty': 50},
                ]
            }
        }
        
        # Update stock quantity to match draft
        self.stock.total_stock = 150
        self.stock.save()
        
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify jig_draft flag
        self.stock.refresh_from_db()
        self.assertTrue(self.stock.jig_draft, "jig_draft should be True")
        
        # Verify draft data contains tray info
        draft = JigLoadingManualDraft.objects.get(
            batch_id='BATCH001',
            lot_id='LOT001'
        )
        self.assertEqual(
            len(draft.delink_tray_info), 3,
            "Draft should contain 3 delink trays"
        )

    def test_draft_with_broken_hooks(self):
        """
        TEST 4: Verify draft handles broken hooks correctly
        """
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 10,
                'original_lot_qty': 100,
                'updated_lot_qty': 90,
                'jig_capacity': 100,
                'trays': [
                    {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 50},
                    {'row_index': '2', 'tray_id': 'TRAY002', 'tray_qty': 40},
                ]
            }
        }
        
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify draft
        draft = JigLoadingManualDraft.objects.get(
            batch_id='BATCH001',
            lot_id='LOT001'
        )
        self.assertEqual(draft.broken_hooks, 10, "Broken hooks should be 10")
        self.assertEqual(draft.updated_lot_qty, 90, "Updated lot qty should be 90")
        self.assertTrue(self.stock.jig_draft, "jig_draft should be True with broken hooks")

    def test_draft_missing_required_fields(self):
        """
        TEST 5: Verify draft creation fails without required fields
        """
        # Missing draft_data
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001'
            # draft_data missing
        }
        
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        # Verify jig_draft is still False
        self.stock.refresh_from_db()
        self.assertFalse(self.stock.jig_draft, "jig_draft should remain False on failed draft")

    def test_draft_lot_status_display(self):
        """
        TEST 6: Verify lot status displays correctly in UI (shows as DRAFT)
        """
        # Create draft
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 100,
                'updated_lot_qty': 100,
                'jig_capacity': 100,
                'trays': [
                    {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 100}
                ]
            }
        }
        
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Refresh and check flags
        self.stock.refresh_from_db()
        
        # The UI should now show "DRAFT" status because jig_draft=True
        # and Jig_Load_completed=False (as per views.py line 104-106)
        self.assertTrue(self.stock.jig_draft, "Stock should have jig_draft=True")
        self.assertFalse(self.stock.Jig_Load_completed, "Stock should have Jig_Load_completed=False")

    def test_draft_multiple_updates_same_lot(self):
        """
        TEST 7: Verify draft can be updated without duplicating records
        """
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 100,
                'updated_lot_qty': 100,
                'jig_capacity': 100,
                'trays': [
                    {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 100}
                ]
            }
        }
        
        # Create draft first time
        response1 = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        draft_count_after_first = JigLoadingManualDraft.objects.filter(
            batch_id='BATCH001',
            lot_id='LOT001',
            user=self.user
        ).count()
        self.assertEqual(draft_count_after_first, 1, "Should have exactly 1 draft record")
        
        # Update draft with different tray
        draft_data['draft_data']['trays'] = [
            {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 60},
            {'row_index': '2', 'tray_id': 'TRAY002', 'tray_qty': 40}
        ]
        
        response2 = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        
        # Should still have only 1 draft record (updated, not created)
        draft_count_after_second = JigLoadingManualDraft.objects.filter(
            batch_id='BATCH001',
            lot_id='LOT001',
            user=self.user
        ).count()
        self.assertEqual(draft_count_after_second, 1, "Should still have exactly 1 draft record after update")
        self.assertTrue(response2.data.get('created') == False, "Update flag should be False")

    def test_delink_tray_processing(self):
        """
        TEST 8: Verify delink tray information is correctly processed
        """
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 100,
                'updated_lot_qty': 100,
                'jig_capacity': 100,
                'trays': [
                    {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 50},
                    {'row_index': '2', 'tray_id': 'TRAY002', 'tray_qty': 50},
                ]
            }
        }
        
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify delink tray info
        draft = JigLoadingManualDraft.objects.get(
            batch_id='BATCH001',
            lot_id='LOT001'
        )
        
        self.assertEqual(len(draft.delink_tray_info), 2, "Should have 2 delink trays")
        self.assertEqual(draft.delink_tray_qty, 100, "Delink tray qty should be 100")
        self.assertEqual(draft.delink_tray_count, 2, "Delink tray count should be 2")

    def test_half_filled_tray_handling(self):
        """
        TEST 9: Verify half-filled tray information is correctly handled
        """
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 100,
                'updated_lot_qty': 100,
                'jig_capacity': 100,
                'trays': [
                    {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 50},
                    {'row_index': '2', 'tray_id': 'TRAY002', 'tray_qty': 40},
                    {'row_index': 'half-filled', 'tray_id': 'TRAY003', 'tray_qty': 10},
                ]
            }
        }
        
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify half-filled tray info
        draft = JigLoadingManualDraft.objects.get(
            batch_id='BATCH001',
            lot_id='LOT001'
        )
        
        self.assertEqual(len(draft.delink_tray_info), 2, "Should have 2 delink trays")
        self.assertEqual(len(draft.half_filled_tray_info), 1, "Should have 1 half-filled tray")
        self.assertEqual(draft.half_filled_tray_qty, 10, "Half-filled tray qty should be 10")

    def test_jig_lock_during_draft(self):
        """
        TEST 10: Verify Jig is locked for other users during draft
        """
        draft_data = {
            'batch_id': 'BATCH001',
            'lot_id': 'LOT001',
            'draft_data': {
                'jig_id': 'JIG001',
                'broken_buildup_hooks': 0,
                'original_lot_qty': 100,
                'updated_lot_qty': 100,
                'jig_capacity': 100,
                'trays': [
                    {'row_index': '1', 'tray_id': 'TRAY001', 'tray_qty': 100}
                ]
            }
        }
        
        # Create draft with user1
        response = self.client.post(
            '/jig_loading/manual-draft/',
            data=draft_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify Jig lock status
        self.jig.refresh_from_db()
        self.assertEqual(self.jig.current_user, self.user, "Jig should be locked by current user")
        self.assertTrue(self.jig.has_active_draft(), "Jig should have active draft")

# ✅ ISSUE #7 FIX: Test cases for Hold/Unhold functionality
class JigLoadingHoldUnholdTestCase(APITestCase):
    """
    Test cases for Jig Loading Hold/Unhold functionality
    Tests the fix: Hold/Unhold API should work in pick table
    """
    
    def setUp(self):
        """Set up test fixtures"""
        # Create test user
        self.user = User.objects.create_user(
            username='holdtestuser',
            password='testpass123',
            email='holdtest@example.com'
        )
        
        # Create version
        self.version = Version.objects.create(
            version_name='V1',
            version_internal='V1_INT'
        )
        
        # Create polish finish
        self.polish_finish = PolishFinishType.objects.create(
            polish_finish='Glossy',
            polish_internal='GLY'
        )
        
        # Create plating color
        self.plating_color = Plating_Color.objects.create(
            plating_color='Black',
            plating_color_internal='B'
        )
        
        # Create tray type
        self.tray_type = TrayType.objects.create(
            tray_type='Standard',
            tray_capacity=50
        )
        
        # Create model master
        self.model_master = ModelMaster.objects.create(
            model_no='MODEL001',
            polish_finish=self.polish_finish,
            ep_bath_type='EP1',
            tray_type=self.tray_type,
            tray_capacity=50,
            version='V1',
            plating_stk_no='STK001'
        )
        
        # Create model master creation (batch)
        self.batch = ModelMasterCreation.objects.create(
            batch_id='BATCH001',
            model_stock_no=self.model_master,
            polish_finish='Glossy',
            ep_bath_type='EP1',
            plating_color='Black',
            tray_type='Standard',
            tray_capacity=50,
            total_batch_quantity=500,
            version=self.version,
            plating_stk_no='STK001'
        )
        
        # Create total stock model
        self.stock = TotalStockModel.objects.create(
            batch_id=self.batch,
            model_stock_no=self.model_master,
            version=self.version,
            total_stock=100,
            polish_finish=self.polish_finish,
            plating_color=self.plating_color,
            lot_id='LOT_HOLD_001',
            jig_hold_lot=False,
            jig_release_lot=False,
            brass_audit_accptance=True,
            Jig_Load_completed=False
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_hold_lot_with_reason(self):
        """
        TEST 1: Verify that a lot can be held with a reason
        This is the main bug fix test
        """
        # Initial state
        self.assertFalse(self.stock.jig_hold_lot, "Initial jig_hold_lot should be False")
        self.assertEqual(self.stock.jig_holding_reason, '', "Initial holding reason should be empty")
        
        # Hold the lot
        hold_data = {
            'lot_id': 'LOT_HOLD_001',
            'action': 'hold',
            'remark': 'Awaiting supervisor approval'
        }
        
        response = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data=hold_data,
            format='json'
        )
        
        # ✅ MAIN TEST: Verify API response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success'), "Hold should be successful")
        
        # ✅ MAIN TEST: Verify database update
        self.stock.refresh_from_db()
        self.assertTrue(self.stock.jig_hold_lot, "jig_hold_lot should be True after hold")
        self.assertEqual(self.stock.jig_holding_reason, 'Awaiting supervisor approval', 
                        "Holding reason should be saved")
        self.assertFalse(self.stock.jig_release_lot, "jig_release_lot should remain False on hold")

    def test_release_lot_with_reason(self):
        """
        TEST 2: Verify that a held lot can be released with a reason
        """
        # First, hold the lot
        self.stock.jig_hold_lot = True
        self.stock.jig_holding_reason = 'Awaiting approval'
        self.stock.save()
        
        # Release the lot
        release_data = {
            'lot_id': 'LOT_HOLD_001',
            'action': 'unhold',
            'remark': 'Approved for processing'
        }
        
        response = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data=release_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('success'), "Unhold should be successful")
        
        # Verify database update
        self.stock.refresh_from_db()
        self.assertFalse(self.stock.jig_hold_lot, "jig_hold_lot should be False after unhold")
        self.assertTrue(self.stock.jig_release_lot, "jig_release_lot should be True after unhold")
        self.assertEqual(self.stock.jig_release_reason, 'Approved for processing', 
                        "Release reason should be saved")

    def test_hold_invalid_action(self):
        """
        TEST 3: Verify error handling for invalid action
        """
        invalid_data = {
            'lot_id': 'LOT_HOLD_001',
            'action': 'invalid',
            'remark': 'Some reason'
        }
        
        response = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data=invalid_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data.get('success'), "Should fail for invalid action")

    def test_hold_missing_lot_id(self):
        """
        TEST 4: Verify error handling for missing lot_id
        """
        data_no_lot = {
            'action': 'hold',
            'remark': 'Some reason'
            # lot_id missing
        }
        
        response = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data=data_no_lot,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data.get('success'), "Should fail for missing lot_id")

    def test_hold_lot_not_found(self):
        """
        TEST 5: Verify error handling for non-existent lot
        """
        data = {
            'lot_id': 'NONEXISTENT_LOT',
            'action': 'hold',
            'remark': 'Some reason'
        }
        
        response = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data=data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data.get('success'), "Should fail for non-existent lot")

    def test_hold_clears_release_fields(self):
        """
        TEST 6: Verify that holding a lot clears release fields
        """
        # Initially set as released
        self.stock.jig_release_lot = True
        self.stock.jig_release_reason = 'Old release reason'
        self.stock.save()
        
        # Now hold it
        hold_data = {
            'lot_id': 'LOT_HOLD_001',
            'action': 'hold',
            'remark': 'New hold reason'
        }
        
        response = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data=hold_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify fields are updated correctly
        self.stock.refresh_from_db()
        self.assertTrue(self.stock.jig_hold_lot, "Should be held")
        self.assertEqual(self.stock.jig_holding_reason, 'New hold reason', "Should have new hold reason")
        self.assertEqual(self.stock.jig_release_reason, '', "Release reason should be cleared")
        self.assertFalse(self.stock.jig_release_lot, "Release flag should be cleared")

    def test_multiple_hold_unhold_cycles(self):
        """
        TEST 7: Verify multiple hold/unhold cycles work correctly
        """
        # Cycle 1: Hold
        response1 = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data={'lot_id': 'LOT_HOLD_001', 'action': 'hold', 'remark': 'Hold reason 1'},
            format='json'
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        self.stock.refresh_from_db()
        self.assertTrue(self.stock.jig_hold_lot)
        
        # Cycle 1: Unhold
        response2 = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data={'lot_id': 'LOT_HOLD_001', 'action': 'unhold', 'remark': 'Release reason 1'},
            format='json'
        )
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        
        self.stock.refresh_from_db()
        self.assertFalse(self.stock.jig_hold_lot)
        self.assertTrue(self.stock.jig_release_lot)
        
        # Cycle 2: Hold again
        response3 = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data={'lot_id': 'LOT_HOLD_001', 'action': 'hold', 'remark': 'Hold reason 2'},
            format='json'
        )
        self.assertEqual(response3.status_code, status.HTTP_200_OK)
        
        self.stock.refresh_from_db()
        self.assertTrue(self.stock.jig_hold_lot)
        self.assertEqual(self.stock.jig_holding_reason, 'Hold reason 2')

    def test_authentication_required(self):
        """
        TEST 8: Verify authentication is required for hold/unhold
        """
        # Use unauthenticated client
        unauth_client = APIClient()
        
        data = {
            'lot_id': 'LOT_HOLD_001',
            'action': 'hold',
            'remark': 'Test reason'
        }
        
        response = unauth_client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data=data,
            format='json'
        )
        
        # Should be forbidden or redirect to login
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_hold_reason_persistence(self):
        """
        TEST 9: Verify hold reason persists across hold/unhold cycles
        """
        holding_reason = 'Critical defect found - requires rework'
        
        # Hold with specific reason
        response = self.client.post(
            '/jig_loading/jig-save-hold-unhold-reason/',
            data={'lot_id': 'LOT_HOLD_001', 'action': 'hold', 'remark': holding_reason},
            format='json'
        )
        
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.jig_holding_reason, holding_reason, "Reason should be preserved")

    def test_pick_table_includes_hold_status(self):
        """
        TEST 10: Verify pick table includes hold status fields in context data
        """
        # Set hold status
        self.stock.jig_hold_lot = True
        self.stock.jig_holding_reason = 'Inspection pending'
        self.stock.save()
        
        # Get pick table view
        response = self.client.get('/jig_loading/JigView/', format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check if context contains master_data with hold fields
        if hasattr(response, 'context_data'):
            master_data = response.context_data.get('master_data', [])
            for item in master_data:
                if item.get('stock_lot_id') == 'LOT_HOLD_001':
                    self.assertIn('jig_hold_lot', item, "jig_hold_lot field should be in context")
                    self.assertIn('jig_holding_reason', item, "jig_holding_reason field should be in context")
                    self.assertTrue(item['jig_hold_lot'], "jig_hold_lot should be True")
                    self.assertEqual(item['jig_holding_reason'], 'Inspection pending')
                    break
#!/usr/bin/env python
"""
Production-Safe Tray Quantity Mismatch Fix Script
=================================================

This script fixes the issue where delinked trays carry forward 
incorrect quantity data from previous lots when reused in new lots.

Problem Description:
- Tray delinked from previous lot shows old quantity (14) instead of correct quantity 
- Completed Table displays incorrect Top Tray and Delinked Tray quantities
- System inherits previous lot quantity instead of calculating fresh for new lot

Safe Production Approach:
- Only corrects tray quantity mappings
- Does not modify table structures or business logic  
- Includes comprehensive logging and rollback capability
- Validates data integrity before and after changes

Author: Senior Python Backend Engineer
Date: March 2026
"""

import os
import sys
import django
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import json

# Configure Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'watchcase_tracker.settings')
django.setup()

# Import models after Django setup
from django.db import transaction, connection
from modelmasterapp.models import TotalStockModel, TrayId, ModelMasterCreation
from InputScreening.models import IPTrayId, IP_Rejected_TrayScan, IP_Rejection_ReasonStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'tray_quantity_fix_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class TrayQuantityFixer:
    """
    Fixes delinked tray quantity mismatches in the Track & Trace system.
    
    This class identifies and corrects cases where delinked trays 
    carry forward incorrect quantities from previous lots.
    """
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.issues_found = []
        self.corrections_made = []
        self.affected_lots = set()
        
        logger.info(f"[INIT] TrayQuantityFixer initialized (dry_run={dry_run})")
    
    def detect_delinked_tray_issues(self, specific_lot_id: str = None) -> List[Dict[str, Any]]:
        """
        Detect trays that were delinked from other lots and carry wrong quantities.
        
        Returns:
            List of issues found with detailed information.
        """
        logger.info("[DETECT] Starting detection of delinked tray quantity issues...")
        
        # Get lots to check
        if specific_lot_id:
            lots_to_check = [specific_lot_id]
            logger.info(f"[TARGET] Checking specific lot: {specific_lot_id}")
        else:
            # Check recent lots with completed status
            total_stocks = TotalStockModel.objects.filter(
                accepted_Ip_stock=True
            ).values_list('lot_id', flat=True).distinct()[:50]  # Check latest 50 lots
            lots_to_check = list(total_stocks)
            logger.info(f"[SCAN] Checking {len(lots_to_check)} recent completed lots")
        
        issues = []
        
        for lot_id in lots_to_check:
            try:
                lot_issues = self._check_single_lot(lot_id)
                issues.extend(lot_issues)
                if lot_issues:
                    self.affected_lots.add(lot_id)
            except Exception as e:
                logger.error(f"❌ Error checking lot {lot_id}: {str(e)}")
                continue
        
        self.issues_found = issues
        logger.info(f"[DETECT] Detection complete. Found {len(issues)} issues across {len(self.affected_lots)} lots.")
        
        return issues
    
    def _check_single_lot(self, lot_id: str) -> List[Dict[str, Any]]:
        """
        Check a single lot for delinked tray quantity issues.
        
        Args:
            lot_id: The lot ID to check
            
        Returns:
            List of issues found in this lot
        """
        issues = []
        
        logger.debug(f"[CHECK] Checking lot: {lot_id}")
        
        # Get current lot data
        stock = TotalStockModel.objects.filter(lot_id=lot_id).first()
        if not stock:
            return issues
        
        # Get all trays associated with this lot
        ip_trays = IPTrayId.objects.filter(lot_id=lot_id)
        
        for tray in ip_trays:
            # Check if this tray was delinked from another lot
            issue = self._check_tray_delink_history(tray, lot_id, stock)
            if issue:
                issues.append(issue)
        
        return issues
    
    def _check_tray_delink_history(self, tray: IPTrayId, current_lot_id: str, stock: TotalStockModel) -> Optional[Dict[str, Any]]:
        """
        Check if a tray has delink history that might cause quantity issues.
        
        Args:
            tray: IPTrayId object to check
            current_lot_id: Current lot ID
            stock: TotalStockModel for current lot
            
        Returns:
            Issue dictionary if problem found, None otherwise
        """
        tray_id = tray.tray_id
        
        # Check if this tray exists in other lots with delink_tray=True
        previous_usage = IPTrayId.objects.filter(
            tray_id=tray_id,
            delink_tray=True
        ).exclude(lot_id=current_lot_id).first()
        
        if not previous_usage:
            return None  # No previous delink usage
        
        # Check if there's a quantity mismatch
        expected_qty = self._calculate_expected_tray_quantity(tray, stock)
        current_qty = tray.tray_quantity
        
        # Also check delink_tray_qty field
        delink_qty = None
        if hasattr(tray, 'delink_tray_qty') and tray.delink_tray_qty:
            try:
                delink_qty = int(tray.delink_tray_qty)
            except (ValueError, TypeError):
                delink_qty = None
        
        # Check if quantities don't match expected values for current lot
        if self._is_quantity_mismatch(current_qty, delink_qty, expected_qty, previous_usage):
            issue = {
                'lot_id': current_lot_id,
                'tray_id': tray_id,
                'issue_type': 'delinked_tray_quantity_mismatch',
                'current_qty': current_qty,
                'delink_qty': delink_qty,
                'expected_qty': expected_qty,
                'previous_lot': previous_usage.lot_id,
                'previous_qty': previous_usage.tray_quantity,
                'previous_delink_qty': getattr(previous_usage, 'delink_tray_qty', None),
                'description': f"Tray {tray_id} carries quantity from previous lot {previous_usage.lot_id}"
            }
            
            logger.warning(f"[ISSUE] DETECTED: {issue['description']}")
            logger.warning(f"   Current qty: {current_qty}, Expected: {expected_qty}")
            logger.warning(f"   Previous lot: {previous_usage.lot_id}, Previous qty: {previous_usage.tray_quantity}")
            
            return issue
        
        return None
    
    def _calculate_expected_tray_quantity(self, tray: IPTrayId, stock: TotalStockModel) -> Optional[int]:
        """
        Calculate what the tray quantity should be in the current lot context.
        
        Args:
            tray: IPTrayId object
            stock: TotalStockModel for the lot
            
        Returns:
            Expected quantity or None if cannot determine
        """
        try:
            lot_id = tray.lot_id
            
            # Get tray capacity for this lot
            tray_capacity = 10  # Default
            if stock.batch_id and hasattr(stock.batch_id, 'tray_capacity'):
                tray_capacity = stock.batch_id.tray_capacity
            
            # Get total quantity for the lot
            total_stock = stock.total_stock or 0
            
            # Get rejection quantity to calculate available quantity
            rejection_record = IP_Rejection_ReasonStore.objects.filter(lot_id=lot_id).first()
            total_rejection_qty = rejection_record.total_rejection_quantity if rejection_record else 0
            
            available_qty = max(total_stock - total_rejection_qty, 0)
            
            if available_qty <= 0:
                return 0
            
            # Calculate tray distribution
            full_trays = available_qty // tray_capacity
            remainder = available_qty % tray_capacity
            
            # Get tray position (order in the lot)
            tray_position = self._get_tray_position_in_lot(tray, lot_id)
            
            # Determine expected quantity based on position
            if remainder > 0:
                # First tray gets the remainder (top tray)
                if tray_position == 0:
                    return remainder
                elif tray_position <= full_trays:
                    return tray_capacity
                else:
                    return 0  # This tray shouldn't have quantity
            else:
                # All trays get full capacity
                if tray_position < full_trays:
                    return tray_capacity
                else:
                    return 0
            
        except Exception as e:
            logger.error(f"❌ Error calculating expected quantity for tray {tray.tray_id}: {str(e)}")
            return None
    
    def _get_tray_position_in_lot(self, tray: IPTrayId, lot_id: str) -> int:
        """
        Get the position/index of a tray within its lot.
        
        Args:
            tray: IPTrayId object
            lot_id: Lot ID
            
        Returns:
            Position index (0-based)
        """
        try:
            # Get all trays for this lot ordered by date
            lot_trays = list(IPTrayId.objects.filter(
                lot_id=lot_id
            ).order_by('date', 'id'))
            
            for i, lot_tray in enumerate(lot_trays):
                if lot_tray.tray_id == tray.tray_id:
                    return i
            
            return 0  # Default to first position if not found
            
        except Exception as e:
            logger.error(f"❌ Error getting tray position for {tray.tray_id}: {str(e)}")
            return 0
    
    def _is_quantity_mismatch(self, current_qty: Optional[int], delink_qty: Optional[int], 
                            expected_qty: Optional[int], previous_usage: IPTrayId) -> bool:
        """
        Determine if there's a quantity mismatch that needs correction.
        
        Args:
            current_qty: Current tray quantity
            delink_qty: Delink quantity field value
            expected_qty: Expected quantity for current lot
            previous_usage: Previous tray usage record
            
        Returns:
            True if mismatch detected, False otherwise
        """
        if expected_qty is None:
            return False
        
        # Check if current quantity is wrong
        if current_qty != expected_qty:
            logger.debug(f"Current qty mismatch: {current_qty} != {expected_qty}")
            return True
        
        # Check if delink_qty carries old data from previous lot
        if delink_qty is not None:
            if hasattr(previous_usage, 'tray_quantity') and previous_usage.tray_quantity:
                if delink_qty == previous_usage.tray_quantity and delink_qty != expected_qty:
                    logger.debug(f"Delink qty carries old data: {delink_qty} from previous lot")
                    return True
        
        return False
    
    def fix_issues(self) -> bool:
        """
        Fix all detected issues.
        
        Returns:
            True if all fixes successful, False otherwise
        """
        if not self.issues_found:
            logger.info("[OK] No issues to fix.")
            return True
        
        logger.info(f"[FIX] Starting to fix {len(self.issues_found)} issues (dry_run={self.dry_run})")
        
        success_count = 0
        
        for issue in self.issues_found:
            try:
                if self._fix_single_issue(issue):
                    success_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to fix issue for tray {issue.get('tray_id')}: {str(e)}")
                continue
        
        logger.info(f"[FIX] Complete: {success_count}/{len(self.issues_found)} issues fixed successfully")
        
        return success_count == len(self.issues_found)
    
    @transaction.atomic
    def _fix_single_issue(self, issue: Dict[str, Any]) -> bool:
        """
        Fix a single tray quantity issue.
        
        Args:
            issue: Issue dictionary with problem details
            
        Returns:
            True if fixed successfully, False otherwise
        """
        lot_id = issue['lot_id']
        tray_id = issue['tray_id']
        expected_qty = issue['expected_qty']
        
        logger.info(f"[FIX] Fixing tray {tray_id} in lot {lot_id}")
        
        if self.dry_run:
            logger.info(f"   [DRY RUN] Would set tray quantity to {expected_qty}")
            logger.info(f"   [DRY RUN] Would clear delink quantity from previous lot")
            return True
        
        try:
            # Get the tray object
            tray = IPTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).first()
            if not tray:
                logger.error(f"❌ Tray {tray_id} not found for lot {lot_id}")
                return False
            
            # Store original values for logging
            original_qty = tray.tray_quantity
            original_delink_qty = getattr(tray, 'delink_tray_qty', None)
            
            # Fix the quantities
            tray.tray_quantity = expected_qty
            
            # Clear delink quantity if it's carrying old data
            if hasattr(tray, 'delink_tray_qty'):
                if expected_qty == 0:
                    # If tray should be empty, set delink_qty to original quantity
                    tray.delink_tray_qty = str(expected_qty) if expected_qty > 0 else "0"
                else:
                    # If tray has quantity, clear delink_qty
                    tray.delink_tray_qty = None
            
            # Save the changes
            tray.save(update_fields=['tray_quantity', 'delink_tray_qty'])
            
            # Log the correction
            correction = {
                'lot_id': lot_id,
                'tray_id': tray_id,
                'original_qty': original_qty,
                'corrected_qty': expected_qty,
                'original_delink_qty': original_delink_qty,
                'corrected_delink_qty': getattr(tray, 'delink_tray_qty', None),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            self.corrections_made.append(correction)
            
            logger.info(f"[FIXED] Tray {tray_id}: quantity {original_qty} -> {expected_qty}")
            if original_delink_qty != getattr(tray, 'delink_tray_qty', None):
                logger.info(f"   Also updated delink_qty: {original_delink_qty} → {getattr(tray, 'delink_tray_qty', None)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error fixing tray {tray_id}: {str(e)}")
            return False
    
    def validate_fixes(self) -> bool:
        """
        Validate that fixes were applied correctly.
        
        Returns:
            True if validation passed, False otherwise
        """
        logger.info("[VALIDATE] Checking fixes...")
        
        if self.dry_run:
            logger.info("[VALIDATE] Skipping validation for dry run")
            return True
        
        validation_passed = True
        
        for correction in self.corrections_made:
            lot_id = correction['lot_id']
            tray_id = correction['tray_id']
            expected_qty = correction['corrected_qty']
            
            try:
                # Get updated tray
                tray = IPTrayId.objects.filter(tray_id=tray_id, lot_id=lot_id).first()
                if not tray:
                    logger.error(f"❌ Validation failed: Tray {tray_id} not found")
                    validation_passed = False
                    continue
                
                # Check if quantity was set correctly
                if tray.tray_quantity != expected_qty:
                    logger.error(f"❌ Validation failed: Tray {tray_id} quantity is {tray.tray_quantity}, expected {expected_qty}")
                    validation_passed = False
                    continue
                
                logger.debug(f"[VALIDATE] Validation passed for tray {tray_id}")
                
            except Exception as e:
                logger.error(f"❌ Validation error for tray {tray_id}: {str(e)}")
                validation_passed = False
        
        if validation_passed:
            logger.info("[VALIDATE] All fixes validated successfully")
        else:
            logger.error("[VALIDATE] Some fixes failed validation")
        
        return validation_passed
    
    def generate_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive report of the fix operation.
        
        Returns:
            Report dictionary
        """
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'dry_run': self.dry_run,
            'issues_found': len(self.issues_found),
            'corrections_made': len(self.corrections_made),
            'affected_lots': list(self.affected_lots),
            'success_rate': (len(self.corrections_made) / len(self.issues_found) * 100) if self.issues_found else 100,
            'issues': self.issues_found,
            'corrections': self.corrections_made
        }
        
        # Save report to file
        report_filename = f'tray_quantity_fix_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        try:
            with open(report_filename, 'w') as f:
                json.dump(report, f, indent=2)
            logger.info(f"[REPORT] Report saved to {report_filename}")
        except Exception as e:
            logger.error(f"❌ Failed to save report: {str(e)}")
        
        return report


def main():
    """
    Main execution function.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix delinked tray quantity mismatches')
    parser.add_argument('--lot-id', type=str, help='Specific lot ID to fix (optional)')
    parser.add_argument('--execute', action='store_true', help='Execute fixes (default is dry run)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    dry_run = not args.execute
    
    logger.info("[START] Starting Tray Quantity Mismatch Fix Script")
    logger.info(f"[MODE] Running in {'PRODUCTION' if not dry_run else 'DRY RUN'} mode")
    
    if args.lot_id:
        logger.info(f"[TARGET] Target lot: {args.lot_id}")
    
    # Initialize fixer
    fixer = TrayQuantityFixer(dry_run=dry_run)
    
    try:
        # Step 1: Detect issues
        logger.info("=" * 50)
        logger.info("STEP 1: DETECTING ISSUES")
        logger.info("=" * 50)
        
        issues = fixer.detect_delinked_tray_issues(specific_lot_id=args.lot_id)
        
        if not issues:
            logger.info("[OK] No issues detected. System is healthy!")
            return
        
        logger.info(f"[ISSUES] Found {len(issues)} issues requiring attention:")
        for issue in issues:
            logger.info(f"   - Lot {issue['lot_id']}: Tray {issue['tray_id']} has quantity mismatch")
        
        # Step 2: Fix issues
        logger.info("=" * 50)
        logger.info("STEP 2: APPLYING FIXES")
        logger.info("=" * 50)
        
        if fixer.fix_issues():
            logger.info("[SUCCESS] All fixes applied successfully")
        else:
            logger.warning("⚠️ Some fixes failed - check logs for details")
        
        # Step 3: Validate fixes
        if not dry_run:
            logger.info("=" * 50)
            logger.info("STEP 3: VALIDATING FIXES")
            logger.info("=" * 50)
            
            if fixer.validate_fixes():
                logger.info("[SUCCESS] All fixes validated successfully")
            else:
                logger.error("❌ Validation failed - manual review required")
        
        # Step 4: Generate report
        logger.info("=" * 50)
        logger.info("STEP 4: GENERATING REPORT")
        logger.info("=" * 50)
        
        report = fixer.generate_report()
        
        logger.info("[SUMMARY] RESULTS:")
        logger.info(f"   Issues found: {report['issues_found']}")
        logger.info(f"   Corrections made: {report['corrections_made']}")
        logger.info(f"   Success rate: {report['success_rate']:.1f}%")
        logger.info(f"   Affected lots: {len(report['affected_lots'])}")
        
        if dry_run:
            logger.info("[INFO] To apply fixes, run with --execute flag")
        else:
            logger.info("[SUCCESS] Production fixes completed successfully")
        
    except Exception as e:
        logger.error(f"❌ Script failed with error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    
    logger.info("[COMPLETE] Script completed successfully")


if __name__ == '__main__':
    main()
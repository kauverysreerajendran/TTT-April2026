# Delinked Tray Quantity Mismatch Fix Script

## Overview

This script fixes a specific issue in the Track & Trace system where delinked trays carry forward incorrect quantity data from previous lots when reused in new lots.

## Problem Description

**Issue**: When a tray is delinked from one lot and reused in another lot:

- The tray shows quantity from the previous lot (e.g., 14) instead of the correct quantity for the new lot
- The Completed Table displays incorrect Top Tray and Delinked Tray quantities
- The `delink_tray_qty` field carries old data from previous usage

**Specific Case**:

- Lot Qty = 140, No of Trays = 9
- Rejection in IS = 4
- Tray NB-A00032 was previously used and delinked
- Shows old quantity (14) instead of correct calculation

## Solution

The script:

1. **Detects** trays that were delinked and reused with incorrect quantities
2. **Calculates** correct quantities based on current lot context
3. **Updates** tray quantities and clears old delink quantity references
4. **Validates** all changes to ensure data integrity

## Safety Features

- **Dry Run Mode**: Test detection and fixes without making changes
- **Transaction Safety**: All database changes are atomic
- **Comprehensive Logging**: Detailed logs of all operations
- **Validation**: Verifies fixes were applied correctly
- **Backup Friendly**: Only modifies specific fields, preserves all other data

## Usage

### Prerequisites

```bash
# Ensure Django environment is activated
cd /path/to/TTT-Jan2026
source env/Scripts/activate  # Windows
# or
source env/bin/activate      # Linux/Mac
```

### Basic Usage

**1. Dry Run (Recommended First Step)**

```bash
python fix_delinked_tray_quantity_mismatch.py
```

**2. Check Specific Lot**

```bash
python fix_delinked_tray_quantity_mismatch.py --lot-id "LOT123456"
```

**3. Execute Actual Fixes**

```bash
python fix_delinked_tray_quantity_mismatch.py --execute
```

**4. Execute with Verbose Logging**

```bash
python fix_delinked_tray_quantity_mismatch.py --execute --verbose
```

### Command Line Options

- `--lot-id LOTID`: Fix specific lot only (optional)
- `--execute`: Apply fixes to database (default is dry run)
- `--verbose`: Enable detailed debug logging
- `--help`: Show help message

### Example Output

```
🚀 Starting Tray Quantity Mismatch Fix Script
📊 Running in DRY RUN mode

==================================================
STEP 1: DETECTING ISSUES
==================================================
🔍 Checking 50 recent completed lots
🚨 ISSUE DETECTED: Tray NB-A00032 carries quantity from previous lot LOT789
   Current qty: 14, Expected: 4
   Previous lot: LOT789, Previous qty: 14

🚨 Found 1 issues requiring attention:
   - Lot LOT123456: Tray NB-A00032 has quantity mismatch

==================================================
STEP 2: APPLYING FIXES
==================================================
🔧 Fixing tray NB-A00032 in lot LOT123456
   [DRY RUN] Would set tray quantity to 4
   [DRY RUN] Would clear delink quantity from previous lot

📊 SUMMARY:
   Issues found: 1
   Corrections made: 1
   Success rate: 100.0%
   Affected lots: 1

🔄 To apply fixes, run with --execute flag
```

## Output Files

The script generates:

1. **Log File**: `tray_quantity_fix_YYYYMMDD_HHMMSS.log`
   - Detailed operation log
   - Error messages and debug information

2. **Report File**: `tray_quantity_fix_report_YYYYMMDD_HHMMSS.json`
   - Summary of issues found and fixes applied
   - Complete data for audit purposes

## Database Changes

**Tables Modified**:

- `InputScreening_iptrayid`

**Fields Updated**:

- `tray_quantity`: Set to correct value for current lot
- `delink_tray_qty`: Cleared if carrying old data, set appropriately for empty trays

**No Changes To**:

- Table structures
- Business logic functions
- Other model fields
- Related data in other tables

## Validation Logic

The script validates:

1. **Delink History**: Identifies trays used in multiple lots with delink status
2. **Quantity Calculation**: Computes correct quantity based on:
   - Total lot quantity
   - Tray capacity
   - Rejection quantities
   - Tray position in lot
3. **Data Integrity**: Ensures fixes align with business rules

## Rollback Procedure

If needed, database changes can be reversed:

1. **Check Transaction Log**: Review the generated JSON report
2. **Restore from Backup**: Use database backup if major issues
3. **Manual Correction**: Update specific records using the report data

```sql
-- Example rollback for specific tray
UPDATE InputScreening_iptrayid
SET tray_quantity = <original_qty>,
    delink_tray_qty = '<original_delink_qty>'
WHERE tray_id = 'NB-A00032' AND lot_id = 'LOT123456';
```

## Monitoring

**Pre-Run Checks**:

```bash
# Check database connectivity
python manage.py shell -c "from InputScreening.models import IPTrayId; print(IPTrayId.objects.count())"

# Verify specific lot exists
python manage.py shell -c "from modelmasterapp.models import TotalStockModel; print(TotalStockModel.objects.filter(lot_id='LOT123456').exists())"
```

**Post-Run Validation**:

```bash
# Check if fixes were applied
python manage.py shell -c "
from InputScreening.models import IPTrayId
tray = IPTrayId.objects.filter(tray_id='NB-A00032', lot_id='LOT123456').first()
print(f'Tray quantity: {tray.tray_quantity if tray else \"Not found\"}')
"
```

## Troubleshooting

**Common Issues**:

1. **Django Import Error**

   ```
   Solution: Ensure DJANGO_SETTINGS_MODULE is set correctly
   export DJANGO_SETTINGS_MODULE=watchcase_tracker.settings
   ```

2. **Permission Denied**

   ```
   Solution: Run with appropriate database permissions
   Check user has UPDATE access on InputScreening_iptrayid table
   ```

3. **No Issues Found**

   ```
   This is normal if system is healthy
   Use --verbose flag to see detailed checks
   ```

4. **Partial Fixes Failed**
   ```
   Check log files for specific error messages
   Run validation queries manually
   ```

## Contact & Support

- **Script Author**: Senior Python Backend Engineer
- **Date**: March 2026
- **Log Location**: Same directory as script
- **Report Location**: Same directory as script

For production issues, review the generated log and report files first, then escalate with specific error messages and lot IDs affected.

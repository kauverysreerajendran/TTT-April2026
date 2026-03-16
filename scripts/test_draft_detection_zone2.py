#!/usr/bin/env python3
"""
Standalone tester for Zone 2 draft-detection logic.
Does not import Django; simulates jig objects and draft data.
"""

from collections import namedtuple

Jig = namedtuple('Jig', ['jig_id', 'lot_id', 'draft_data', 'new_lot_ids'])


def check_drafts_for_jigs(jig_list, saved_draft_main_lot_ids=None):
    saved_draft_main_lot_ids = set(saved_draft_main_lot_ids or [])

    for jig in jig_list:
        has_draft = False
        jig_name = jig.jig_id or jig.lot_id
        print(f"🔍 Zone 2 - Checking jig {jig_name}")

        draft_data = jig.draft_data or {}
        lot_quantities = {}
        if isinstance(draft_data, dict):
            lot_quantities = draft_data.get('lot_id_quantities', {}) or {}

        if lot_quantities:
            print(f"lot_id_quantities keys: {list(lot_quantities.keys())}")
            main_lot = jig.lot_id
            if main_lot and main_lot in lot_quantities:
                has_draft = True
                print(f"\n✅ Zone 2 - JIG {jig_name} DRAFT FOUND\n")

        if not has_draft and jig.new_lot_ids:
            print(f"   - new_lot_ids: {jig.new_lot_ids}")
            for lid in jig.new_lot_ids:
                if lid in lot_quantities or lid in saved_draft_main_lot_ids:
                    has_draft = True
                    print(f"✅ DRAFT MATCH in new_lot_ids: {lid}")
                    break

        if not has_draft and not lot_quantities:
            main_lot = jig.lot_id
            print(f"   - main lot_id fallback: {main_lot}")
            if main_lot and main_lot in saved_draft_main_lot_ids:
                has_draft = True
                print(f"✅ DRAFT MATCH in saved drafts for main lot_id: {main_lot}")

        if not has_draft and not lot_quantities:
            print(f"\n❌ Zone 2 - JIG {jig_name} NO DRAFT\n")

    print("🔍 Draft check complete for test jigs\n")


if __name__ == '__main__':
    # Test Case 1
    print("--- Test Case 1: Single matching lot_id_quantities ---")
    jig1 = Jig(jig_id='J144-0001', lot_id='LID160320261058470004',
               draft_data={'lot_id_quantities': {'LID160320261058470004': 144}},
               new_lot_ids=None)
    check_drafts_for_jigs([jig1], saved_draft_main_lot_ids=[])

    # Test Case 2
    print("--- Test Case 2: Empty lot_id_quantities ---")
    jig2 = Jig(jig_id='J144-0002', lot_id='LID_EMPTY', draft_data={}, new_lot_ids=None)
    check_drafts_for_jigs([jig2], saved_draft_main_lot_ids=[])

    # Test Case 3
    print("--- Test Case 3: Multiple lot_ids ---")
    jig3 = Jig(jig_id='J144-0003', lot_id='LID1',
               draft_data={'lot_id_quantities': {'LID1': 50, 'LID2': 60}},
               new_lot_ids=None)
    check_drafts_for_jigs([jig3], saved_draft_main_lot_ids=[])

    # Combined test: multiple jigs
    print("--- Combined Test: multiple jigs and saved drafts fallback ---")
    jig4 = Jig(jig_id='J144-0004', lot_id='LID_FALLBACK', draft_data=None, new_lot_ids=None)
    check_drafts_for_jigs([jig1, jig2, jig3, jig4], saved_draft_main_lot_ids=['LID_FALLBACK'])

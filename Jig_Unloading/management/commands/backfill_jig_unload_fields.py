"""
Management command: backfill_jig_unload_fields
-----------------------------------------------
Permanently repairs JigUnloadAfterTable records that have:
  - empty jig_qr_id    (caused by broken "-LIDxxx" combine_lot_ids format)
  - no location M2M     (same root cause)

Run dry-run first to preview without changing anything:
    python manage.py backfill_jig_unload_fields --dry-run

Then run for real:
    python manage.py backfill_jig_unload_fields

Optional flags:
    --dry-run         Preview only, no DB writes
    --limit N         Process at most N records (useful for batch testing)
    --fix-all         Also re-process records that already have jig_qr_id/location set
                      (use to correct partially wrong values)
"""

from django.core.management.base import BaseCommand
from django.db import transaction


def _extract_lot_id(combined):
    """Normalise a combine_lot_ids entry to a plain LIDxxx string.
    Handles:
      'JLOT-8CEDE491A4A3-LID040320261002094862' → 'LID040320261002094862'
      '-LID040320261002094862'                  → 'LID040320261002094862'
      'LID040320261002094862'                   → 'LID040320261002094862'
    """
    if not combined:
        return combined
    s = combined.lstrip('-')
    if s.startswith('JLOT-') and '-' in s[5:]:
        return s.rsplit('-', 1)[1]
    return s


def _extract_jlot_prefix(combined):
    """Extract JLOT-xxxxxxx prefix from a combine_lot_ids entry.
    Returns None if entry does not have a valid JLOT prefix.
    """
    if not combined:
        return None
    s = combined.lstrip('-')
    if s.startswith('JLOT-') and '-' in s[5:]:
        return s.rsplit('-', 1)[0]  # e.g. 'JLOT-8CEDE491A4A3'
    return None


class Command(BaseCommand):
    help = "Backfill jig_qr_id and location on JigUnloadAfterTable records."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help="Show what would be fixed without writing to DB.",
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help="Process at most N records (0 = no limit).",
        )
        parser.add_argument(
            '--fix-all',
            action='store_true',
            default=False,
            help="Re-process records that already have values set.",
        )

    def handle(self, *args, **options):
        from Jig_Unloading.models import JigUnloadAfterTable
        from Jig_Loading.models import JigCompleted
        from modelmasterapp.models import TotalStockModel

        dry_run = options['dry_run']
        limit = options['limit']
        fix_all = options['fix_all']

        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY RUN — no changes will be saved ===\n"))

        # Select records that need fixing
        if fix_all:
            qs = JigUnloadAfterTable.objects.prefetch_related('location').all()
        else:
            # Records missing jig_qr_id OR missing location
            from django.db.models import Q
            qs = JigUnloadAfterTable.objects.prefetch_related('location').filter(
                Q(jig_qr_id='') | Q(jig_qr_id__isnull=True)
            )

        if limit:
            qs = qs[:limit]

        total = qs.count() if hasattr(qs, 'count') else len(qs)
        self.stdout.write(f"Found {total} records to process.\n")

        fixed_jig_id = 0
        fixed_location = 0
        skipped = 0
        not_found = 0

        for record in qs:
            combine_lot_ids = record.combine_lot_ids or []
            if not combine_lot_ids:
                self.stdout.write(
                    self.style.WARNING(f"  SKIP  {record.lot_id} — no combine_lot_ids")
                )
                skipped += 1
                continue

            # ── Resolve jig_qr_id ────────────────────────────────────────────
            resolved_jig_qr_id = record.jig_qr_id or ''
            source_jig = 'existing'

            if not resolved_jig_qr_id or fix_all:
                for entry in combine_lot_ids:
                    # 1. Try JLOT prefix directly from the entry
                    jlot = _extract_jlot_prefix(entry)
                    if jlot:
                        resolved_jig_qr_id = jlot
                        source_jig = 'combine_lot_ids prefix'
                        break

                    # 2. Fallback: look up JigCompleted via extracted lot_id
                    actual_lot = _extract_lot_id(entry)
                    if actual_lot:
                        jc = JigCompleted.objects.filter(
                            draft_data__lot_id_quantities__has_key=actual_lot
                        ).first()
                        if jc and jc.jig_id:
                            resolved_jig_qr_id = jc.jig_id
                            source_jig = f'JigCompleted pk={jc.pk}'
                            break

            # ── Resolve location ──────────────────────────────────────────────
            existing_locations = list(record.location.all())
            resolved_locations = existing_locations  # start with what's there
            source_loc = 'existing'

            if not existing_locations or fix_all:
                found_locs = []
                for entry in combine_lot_ids:
                    actual_lot = _extract_lot_id(entry)
                    if not actual_lot:
                        continue
                    tsm = (
                        TotalStockModel.objects
                        .filter(lot_id=actual_lot)
                        .prefetch_related('location')
                        .first()
                    )
                    if tsm:
                        locs = list(tsm.location.all())
                        if locs:
                            found_locs.extend(locs)
                            source_loc = f'TotalStockModel lot_id={actual_lot}'
                        elif tsm.batch_id and getattr(tsm.batch_id, 'location', None):
                            found_locs.append(tsm.batch_id.location)
                            source_loc = f'ModelMasterCreation batch_id={tsm.batch_id_id}'

                if found_locs:
                    # Deduplicate while preserving order
                    seen_ids = set()
                    resolved_locations = []
                    for loc in found_locs:
                        if loc.pk not in seen_ids:
                            seen_ids.add(loc.pk)
                            resolved_locations.append(loc)

            # ── Report / apply ────────────────────────────────────────────────
            needs_jig_update = resolved_jig_qr_id and resolved_jig_qr_id != (record.jig_qr_id or '')
            needs_loc_update = (
                set(loc.pk for loc in resolved_locations) !=
                set(loc.pk for loc in existing_locations)
            )

            if not resolved_jig_qr_id and not resolved_locations:
                self.stdout.write(
                    self.style.ERROR(
                        f"  MISS  {record.lot_id} | combine_lot_ids={combine_lot_ids} "
                        f"— could not resolve jig_qr_id or location"
                    )
                )
                not_found += 1
                continue

            jig_str = f"{record.jig_qr_id or '(empty)'!r} → {resolved_jig_qr_id!r} [{source_jig}]"
            loc_str = (
                f"locations: {[l.location_name for l in existing_locations]} "
                f"→ {[l.location_name for l in resolved_locations]} [{source_loc}]"
            )
            self.stdout.write(
                f"  {'DRY ' if dry_run else 'FIX '} {record.lot_id}\n"
                f"       jig_qr_id : {jig_str}\n"
                f"       {loc_str}"
            )

            if not dry_run:
                with transaction.atomic():
                    save_fields = []
                    if needs_jig_update:
                        record.jig_qr_id = resolved_jig_qr_id
                        save_fields.append('jig_qr_id')
                        fixed_jig_id += 1
                    if needs_loc_update and resolved_locations:
                        record.save(update_fields=save_fields) if save_fields else None
                        record.location.set(resolved_locations)
                        fixed_location += 1
                        save_fields = []  # already saved above or will save below
                    if save_fields:
                        record.save(update_fields=save_fields)
            else:
                if needs_jig_update:
                    fixed_jig_id += 1
                if needs_loc_update and resolved_locations:
                    fixed_location += 1

        self.stdout.write('\n' + '─' * 50)
        self.stdout.write(
            self.style.SUCCESS(
                f"{'[DRY RUN] ' if dry_run else ''}Done.\n"
                f"  jig_qr_id fixed  : {fixed_jig_id}\n"
                f"  location  fixed  : {fixed_location}\n"
                f"  skipped          : {skipped}\n"
                f"  not resolvable   : {not_found}\n"
                f"  total processed  : {total}\n"
            )
        )

from django.core.management.base import BaseCommand
from Jig_Loading.models import BathNumbers


class Command(BaseCommand):
    help = 'Seed default BathNumbers for the Nickel Bath No dropdown'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=5,
            help='Number of bath numbers to create per type (default: 5)',
        )

    def handle(self, *args, **options):
        count = options['count']
        bath_types = ['Bright', 'Semi Bright', 'Dull']
        created = 0
        skipped = 0

        for bath_type in bath_types:
            for i in range(1, count + 1):
                bath_number = f'Bath {i}'
                obj, was_created = BathNumbers.objects.get_or_create(
                    bath_number=bath_number,
                    bath_type=bath_type,
                    defaults={'is_active': True},
                )
                if was_created:
                    created += 1
                    self.stdout.write(f'  ✅ Created: {obj}')
                else:
                    skipped += 1
                    self.stdout.write(f'  ⏭  Exists:  {obj}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone — created {created}, skipped {skipped} existing records.'
        ))
        self.stdout.write(
            'You can add/remove bath numbers at any time via Django admin → Bath Numbers.'
        )

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import Campaign, Expense, InventoryMovement, User

class Command(BaseCommand):
    help = 'Initialize the default 2026 campaign per specification idempotently.'

    def handle(self, *args, **options):
        with transaction.atomic():
            admin_user = User.objects.filter(role='super_admin').first()

            campaign, created = Campaign.objects.get_or_create(
                year=2026,
                defaults={
                    'name': 'Calendar Fund 2026',
                    'printed_quantity': 2000,
                    'cost_price_per_calendar': Decimal('11.00'),
                    'min_expected_collection_per_calendar': Decimal('20.00'),
                    'commission_percentage': Decimal('10.00'),
                    'status': 'active',
                    'created_by': admin_user,
                }
            )

            # Check if printing expense already exists for this campaign
            printing_expense = Expense.objects.filter(
                campaign=campaign,
                category='printing',
                is_voided=False
            ).first()

            if not printing_expense:
                Expense.objects.create(
                    campaign=campaign,
                    category='printing',
                    amount=campaign.proposed_printing_expense,
                    date=timezone.now().date(),
                    description=f"Initial printing expense: {campaign.printed_quantity} calendars @ ₹{campaign.cost_price_per_calendar}",
                    created_by=admin_user,
                )
                self.stdout.write(self.style.SUCCESS(f"Created initial printing expense of ₹{campaign.proposed_printing_expense}"))
            else:
                self.stdout.write(self.style.WARNING(f"Printing expense already exists (₹{printing_expense.amount}), skipping duplicate creation."))

            # Check if opening stock movement exists
            opening_movement = InventoryMovement.objects.filter(
                campaign=campaign,
                movement_type='opening_stock'
            ).first()

            if not opening_movement:
                InventoryMovement.objects.create(
                    campaign=campaign,
                    movement_type='opening_stock',
                    quantity=campaign.printed_quantity,
                    reason="Initial printed calendar stock",
                    created_by=admin_user,
                )
                self.stdout.write(self.style.SUCCESS(f"Created opening inventory movement of {campaign.printed_quantity} calendars"))
            else:
                self.stdout.write(self.style.WARNING(f"Opening stock movement already exists, skipping duplicate."))

            self.stdout.write(self.style.SUCCESS(f"Campaign 2026 initialized successfully."))

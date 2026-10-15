import os
import getpass
from django.core.management.base import BaseCommand
from core.models import User, normalize_phone_number

class Command(BaseCommand):
    help = 'Bootstrap the initial Super Administrator account securely from environment variables or interactive prompt.'

    def add_arguments(self, parser):
        parser.add_argument('--phone', type=str, help='Superadmin phone number (10-digit Indian mobile)')
        parser.add_argument('--name', type=str, help='Superadmin display name')
        parser.add_argument('--password', type=str, help='Superadmin password')

    def handle(self, *args, **options):
        phone = options.get('phone') or os.getenv('SUPERADMIN_PHONE')
        name = options.get('name') or os.getenv('SUPERADMIN_NAME')
        password = options.get('password') or os.getenv('SUPERADMIN_PASSWORD')

        if not phone:
            phone = input("Enter Superadmin 10-digit Indian mobile phone number: ").strip()
        if not name:
            name = input("Enter Superadmin display name (e.g. Super Admin): ").strip()
        if not password:
            password = getpass.getpass("Enter Superadmin password: ").strip()

        try:
            phone = normalize_phone_number(phone)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Validation error: {e}"))
            return

        user, created = User.objects.get_or_create(
            phone_number=phone,
            defaults={
                'display_name': name or 'Super Administrator',
                'role': 'super_admin',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            }
        )

        user.set_password(password)
        user.display_name = name or user.display_name
        user.role = 'super_admin'
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Successfully created Super Administrator {phone} ({user.display_name})"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated existing Super Administrator {phone} ({user.display_name})"))

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Place, Student, ReceiptBook, Campaign, User
from core.services import TripService

class Command(BaseCommand):
    help = 'Seed initial realistic places, students, receipt books, and sample trips for Zainussunna Academy.'

    def handle(self, *args, **options):
        campaign = Campaign.objects.filter(year=2026).first()
        if not campaign:
            self.stderr.write("Campaign 2026 not found. Please run init_campaign_2026 first.")
            return

        superadmin = User.objects.filter(role='super_admin').first()

        places = [
            'Calicut Beach', 'Mananchira Square', 'Mavoor Road',
            'Kuttikkattoor', 'Feroke Bridge', 'Medical College Town',
            'Palayam Market', 'Ramanattukara Junction'
        ]
        created_places = []
        for p in places:
            obj, _ = Place.objects.get_or_create(name=p)
            created_places.append(obj)
        self.stdout.write(f"Seeded {len(created_places)} places.")

        student_names = [
            'Ahmad Bilal', 'Mohammed Rishan', 'Omar Farooq', 'Zaid Ibrahim',
            'Hamza Ali', 'Abdullah Salih', 'Anas Bin Malik', 'Salman Farisi',
            'Khalid Walid', 'Talha Zubair', 'Saad Waqqas', 'Muadh Jabal'
        ]
        created_students = []
        for name in student_names:
            obj, _ = Student.objects.get_or_create(name=name)
            created_students.append(obj)
        self.stdout.write(f"Seeded {len(created_students)} students.")

        books = [
            ('Book RB-01', 1, 100),
            ('Book RB-02', 101, 200),
            ('Book RB-03', 201, 300),
        ]
        created_books = []
        for label, start, end in books:
            b, _ = ReceiptBook.objects.get_or_create(
                campaign=campaign,
                label=label,
                defaults={'first_leaf': start, 'last_leaf': end}
            )
            created_books.append(b)
        self.stdout.write(f"Seeded {len(created_books)} receipt books.")

        self.stdout.write(self.style.SUCCESS("Starter data seeded successfully."))

from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from .models import (
    User, Campaign, Student, Place, ReceiptBook,
    Trip, TripStudent, InventoryMovement, Expense,
    CommissionCalculation, CommissionPayout, AuditLog, ExternalCollection,
    normalize_phone_number, split_amount_in_paise
)
from .services import InventoryService, TripService, FinancialService, ReceiptBookService
from .reports import ReportGenerator


class FinancialRulesAndOperationsTestCase(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(
            phone_number='9876543210',
            password='TestSuperSecretPassword123!',
            display_name='Super Admin'
        )
        self.admin_user = User.objects.create_user(
            phone_number='9123456780',
            password='AdminPassword123!',
            display_name='Admin Staff',
            role='admin'
        )
        self.place1 = Place.objects.create(name='Calicut Beach')
        self.place2 = Place.objects.create(name='Mananchira Square')

        self.student_a = Student.objects.create(name='Student A')
        self.student_b = Student.objects.create(name='Student B')
        self.student_c = Student.objects.create(name='Student C')

        # Create 2026 Campaign
        self.campaign = Campaign.objects.create(
            name='Calendar Fund 2026',
            year=2026,
            printed_quantity=2000,
            cost_price_per_calendar=Decimal('11.00'),
            min_expected_collection_per_calendar=Decimal('20.00'),
            commission_percentage=Decimal('10.00'),
            created_by=self.superadmin,
        )

        self.receipt_book = ReceiptBook.objects.create(
            campaign=self.campaign,
            label='Book-01',
            first_leaf=1,
            last_leaf=100
        )

    def test_phone_normalization(self):
        self.assertEqual(normalize_phone_number('9876543210'), '9876543210')
        self.assertEqual(normalize_phone_number('+91 98765-43210'), '9876543210')
        self.assertEqual(normalize_phone_number('09876543210'), '9876543210')
        with self.assertRaises(ValidationError):
            normalize_phone_number('12345')

    def test_rounding_rule_test_e(self):
        """
        Test E: Divide ₹10 among three students.
        Expected shares: ₹3.34, ₹3.33, ₹3.33. Sum = exactly ₹10.00.
        """
        shares = split_amount_in_paise(Decimal('10.00'), 3)
        self.assertEqual(len(shares), 3)
        self.assertEqual(shares[0], Decimal('3.34'))
        self.assertEqual(shares[1], Decimal('3.33'))
        self.assertEqual(shares[2], Decimal('3.33'))
        self.assertEqual(sum(shares), Decimal('10.00'))

    def test_printing_expense_initialization_test_f(self):
        """
        Test F: Printed quantity 2000, cost per calendar ₹11.
        Expected printing expense: ₹22,000 exactly once without duplicate creation on retry.
        """
        self.assertEqual(self.campaign.proposed_printing_expense, Decimal('22000.00'))

        # Create printing expense
        exp, created = Expense.objects.get_or_create(
            campaign=self.campaign,
            category='printing',
            is_voided=False,
            defaults={
                'amount': self.campaign.proposed_printing_expense,
                'date': timezone.now().date(),
                'description': 'Initial printing expense',
                'created_by': self.superadmin,
            }
        )
        self.assertTrue(created)
        self.assertEqual(exp.amount, Decimal('22000.00'))

        # Retry creating should not create duplicate
        exp2, created2 = Expense.objects.get_or_create(
            campaign=self.campaign,
            category='printing',
            is_voided=False,
            defaults={
                'amount': self.campaign.proposed_printing_expense,
                'date': timezone.now().date(),
                'description': 'Initial printing expense',
                'created_by': self.superadmin,
            }
        )
        self.assertFalse(created2)
        self.assertEqual(Expense.objects.filter(campaign=self.campaign, category='printing').count(), 1)

    def test_two_students_financial_allocation_test_a(self):
        """
        Test A: Two students collect ₹1,000. Fare: ₹100. Food: ₹60.
        Expected:
        - Total collection: ₹1,000.
        - Fare total: ₹100, Food total: ₹60.
        - Net collection: ₹840.
        - Each gross share: ₹500.
        - Each fare share: ₹50.
        - Each food share: ₹30.
        - Each net share: ₹420.
        - Each commission at 10%: ₹42.
        """
        # Dispatch trip
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id, self.student_b.id],
            calendars_issued=100,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('100.00'),
            notes='Initial dispatch',
            user=self.admin_user
        )

        # Settle trip
        TripService.settle_trip(
            trip=trip,
            return_time='14:00:00',
            calendars_sold=50,
            calendars_returned=50,
            cash_collection=Decimal('600.00'),
            gpay_collection=Decimal('400.00'),
            food_expense=Decimal('60.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='All good',
            user=self.admin_user
        )

        trip.refresh_from_db()
        self.assertEqual(trip.total_collection, Decimal('1000.00'))
        self.assertEqual(trip.bus_fare, Decimal('100.00'))
        self.assertEqual(trip.food_expense, Decimal('60.00'))

        parts = list(trip.trip_students.order_by('student__name'))
        self.assertEqual(len(parts), 2)

        # Student A
        self.assertEqual(parts[0].gross_collection_share, Decimal('500.00'))
        self.assertEqual(parts[0].bus_fare_share, Decimal('50.00'))
        self.assertEqual(parts[0].food_expense_share, Decimal('30.00'))
        self.assertEqual(parts[0].net_collection_share, Decimal('420.00'))

        # Student B
        self.assertEqual(parts[1].gross_collection_share, Decimal('500.00'))
        self.assertEqual(parts[1].bus_fare_share, Decimal('50.00'))
        self.assertEqual(parts[1].food_expense_share, Decimal('30.00'))
        self.assertEqual(parts[1].net_collection_share, Decimal('420.00'))

        # Commission earned
        calc_a = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        calc_b = FinancialService.recalculate_student_commission(self.campaign, self.student_b)

        self.assertEqual(calc_a.net_collection, Decimal('420.00'))
        self.assertEqual(calc_a.calculated_commission, Decimal('42.00'))
        self.assertEqual(calc_b.net_collection, Decimal('420.00'))
        self.assertEqual(calc_b.calculated_commission, Decimal('42.00'))

    def test_changing_student_pairs_test_b(self):
        """
        Test B: Changing student pairs:
        Trip 1: A and B collect ₹1,000 (no expenses).
        Trip 2: A and C collect ₹1,000 (no expenses).
        Expected:
        - A's gross and net: ₹1,000.
        - B's gross and net: ₹500.
        - C's gross and net: ₹500.
        - A's commission (10%): ₹100.
        - B's commission (10%): ₹50.
        - C's commission (10%): ₹50.
        """
        # Trip 1: A and B
        trip1 = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id, self.student_b.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip1,
            return_time='12:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('1000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        # Trip 2: A and C
        trip2 = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place2,
            trip_date=timezone.now().date(),
            departure_time='13:00:00',
            student_ids=[self.student_a.id, self.student_c.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=51,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip2,
            return_time='16:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('1000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=51,
            receipt_ending_leaf=100,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        calc_a = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        calc_b = FinancialService.recalculate_student_commission(self.campaign, self.student_b)
        calc_c = FinancialService.recalculate_student_commission(self.campaign, self.student_c)

        self.assertEqual(calc_a.gross_collection, Decimal('1000.00'))
        self.assertEqual(calc_a.net_collection, Decimal('1000.00'))
        self.assertEqual(calc_a.calculated_commission, Decimal('100.00'))

        self.assertEqual(calc_b.gross_collection, Decimal('500.00'))
        self.assertEqual(calc_b.net_collection, Decimal('500.00'))
        self.assertEqual(calc_b.calculated_commission, Decimal('50.00'))

        self.assertEqual(calc_c.gross_collection, Decimal('500.00'))
        self.assertEqual(calc_c.net_collection, Decimal('500.00'))
        self.assertEqual(calc_c.calculated_commission, Decimal('50.00'))

    def test_stock_calculations_test_c(self):
        """
        Test C: Printed 2000, Issued 100, Sold 70, Returned 30.
        Expected: Sold: 70, Available: 1930, In field: 0.
        """
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=100,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )

        # Before settlement: in field = 100, available = 1900
        mid_inv = InventoryService.get_campaign_inventory_summary(self.campaign)
        self.assertEqual(mid_inv['calendars_in_field'], 100)
        self.assertEqual(mid_inv['available_stock'], 1900)

        # Settle
        TripService.settle_trip(
            trip=trip,
            return_time='13:00:00',
            calendars_sold=70,
            calendars_returned=30,
            cash_collection=Decimal('1400.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=70,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        post_inv = InventoryService.get_campaign_inventory_summary(self.campaign)
        self.assertEqual(post_inv['calendars_sold'], 70)
        self.assertEqual(post_inv['calendars_returned'], 30)
        self.assertEqual(post_inv['calendars_in_field'], 0)
        self.assertEqual(post_inv['available_stock'], 1930)

    def test_price_shortfall_warning_test_d(self):
        """
        Test D: Sold 10, min price ₹20 -> expected ₹200. Actual ₹180.
        Settlement proceeds after required explanation note. Revenue remains ₹180 (no fabrication).
        """
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=10,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )

        # Attempt settlement without note when shortfall exists should fail
        with self.assertRaises(ValidationError):
            TripService.settle_trip(
                trip=trip,
                return_time='12:00:00',
                calendars_sold=10,
                calendars_returned=0,
                cash_collection=Decimal('180.00'),
                gpay_collection=Decimal('0.00'),
                food_expense=Decimal('0.00'),
                receipt_book=self.receipt_book,
                receipt_starting_leaf=1,
                receipt_ending_leaf=10,
                voided_leaves='',
                discrepancy_notes='',  # Empty note -> should raise ValidationError
                user=self.admin_user
            )

        # With explanatory note, settlement succeeds
        settled = TripService.settle_trip(
            trip=trip,
            return_time='12:00:00',
            calendars_sold=10,
            calendars_returned=0,
            cash_collection=Decimal('180.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=10,
            voided_leaves='',
            discrepancy_notes='Discounted for local elder',
            user=self.admin_user
        )

        self.assertEqual(settled.status, 'settled')
        self.assertEqual(settled.review_status, 'needs_review')
        self.assertEqual(settled.total_collection, Decimal('180.00'))
        self.assertEqual(settled.collection_shortfall, Decimal('20.00'))

    def test_commission_payout_does_not_double_count_expense_test_g(self):
        """
        Test G: Accrue ₹500 in commission, pay ₹500 payout.
        Expected: Net profit does not decrease a second time when payout is recorded.
        """
        # Trip with A collecting ₹5000 net -> 10% commission = ₹500
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=250,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip,
            return_time='15:00:00',
            calendars_sold=250,
            calendars_returned=0,
            cash_collection=Decimal('5000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        summary_before = FinancialService.get_campaign_financial_summary(self.campaign)
        self.assertEqual(summary_before['total_commission_earned'], Decimal('500.00'))
        self.assertEqual(summary_before['total_commission_paid'], Decimal('0.00'))
        self.assertEqual(summary_before['outstanding_commission'], Decimal('500.00'))
        net_profit_before = summary_before['net_profit']

        # Record payout of ₹500
        payout = FinancialService.record_payout(
            campaign=self.campaign,
            student=self.student_a,
            amount=Decimal('500.00'),
            payment_date=timezone.now().date(),
            payment_method='cash',
            reference='Voucher-001',
            notes='Final payout',
            user=self.superadmin
        )

        summary_after = FinancialService.get_campaign_financial_summary(self.campaign)
        self.assertEqual(summary_after['total_commission_earned'], Decimal('500.00'))
        self.assertEqual(summary_after['total_commission_paid'], Decimal('500.00'))
        self.assertEqual(summary_after['outstanding_commission'], Decimal('0.00'))
        # Crucial check: Net profit MUST NOT decrease by another ₹500!
        self.assertEqual(summary_after['net_profit'], net_profit_before)

        # Payout greater than remaining payable must be rejected
        with self.assertRaises(ValidationError):
            FinancialService.record_payout(
                campaign=self.campaign,
                student=self.student_a,
                amount=Decimal('100.00'),
                payment_date=timezone.now().date(),
                payment_method='cash',
                reference='',
                notes='',
                user=self.superadmin
            )

    def test_negative_trip_net_review_test_h(self):
        """
        Test H: If trip collects less than fare + food expense:
        Flag for review, preserve actual values, require explanation note, commission does not become negative.
        """
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=5,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('150.00'),
            notes='',
            user=self.admin_user
        )

        # Collects only ₹100, expenses are ₹150 + ₹50 = ₹200. Net is negative (-₹100).
        settled = TripService.settle_trip(
            trip=trip,
            return_time='12:00:00',
            calendars_sold=5,
            calendars_returned=0,
            cash_collection=Decimal('100.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('50.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=5,
            voided_leaves='',
            discrepancy_notes='Heavy rain and low footfall',
            user=self.admin_user
        )

        self.assertEqual(settled.review_status, 'needs_review')
        calc = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        self.assertEqual(calc.net_collection, Decimal('-100.00'))
        # Commission cannot be negative!
        self.assertEqual(calc.calculated_commission, Decimal('0.00'))

    def test_campaign_isolation_test_i(self):
        """
        Test I: Two campaigns. Transactions in one do not contaminate the other.
        """
        campaign2 = Campaign.objects.create(
            name='Calendar Fund 2027',
            year=2027,
            printed_quantity=3000,
            cost_price_per_calendar=Decimal('12.00'),
            min_expected_collection_per_calendar=Decimal('25.00'),
            commission_percentage=Decimal('12.00'),
            created_by=self.superadmin,
        )

        # Trip in 2026
        trip2026 = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip2026,
            return_time='12:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('1000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        sum2026 = FinancialService.get_campaign_financial_summary(self.campaign)
        sum2027 = FinancialService.get_campaign_financial_summary(campaign2)

        self.assertEqual(sum2026['total_collections'], Decimal('1000.00'))
        self.assertEqual(sum2027['total_collections'], Decimal('0.00'))
        self.assertEqual(sum2027['open_trips_count'], 0)
        self.assertEqual(sum2027['settled_trips_count'], 0)

    def test_concurrent_or_overissue_dispatch_test_j(self):
        """
        Test J: Attempting to reserve more calendars than remain in stock fails cleanly.
        """
        with self.assertRaises(ValidationError):
            TripService.dispatch_trip(
                campaign=self.campaign,
                place=self.place1,
                trip_date=timezone.now().date(),
                departure_time='09:00:00',
                student_ids=[self.student_a.id],
                calendars_issued=2500,  # Only 2000 available
                receipt_book=self.receipt_book,
                receipt_starting_leaf=1,
                bus_fare=Decimal('0.00'),
                notes='',
                user=self.admin_user
            )

    def test_prevent_duplicate_student_open_trip(self):
        """Student cannot be on two open trips simultaneously."""
        TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=20,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )

        with self.assertRaises(ValidationError):
            TripService.dispatch_trip(
                campaign=self.campaign,
                place=self.place2,
                trip_date=timezone.now().date(),
                departure_time='10:00:00',
                student_ids=[self.student_a.id, self.student_b.id],  # Student A already in open trip!
                calendars_issued=20,
                receipt_book=self.receipt_book,
                receipt_starting_leaf=21,
                bus_fare=Decimal('0.00'),
                notes='',
                user=self.admin_user
            )

    def test_report_exports(self):
        """Verify Excel, CSV, and PDF exports generate valid non-empty responses."""
        res_excel = ReportGenerator.export_excel(self.campaign)
        self.assertEqual(res_excel.status_code, 200)
        self.assertTrue(len(res_excel.content) > 100)

        res_csv = ReportGenerator.export_csv(self.campaign, 'trips')
        self.assertEqual(res_csv.status_code, 200)
        self.assertTrue(len(res_csv.content) > 10)

        res_pdf = ReportGenerator.export_pdf(self.campaign)
        self.assertEqual(res_pdf.status_code, 200)
        self.assertTrue(len(res_pdf.content) > 500)

    def test_changing_student_pairs_cumulative_statements(self):
        """
        Verify cumulative financial tracking when students change partners across trips.
        Trip 1: Student A + Student B.
        Trip 2: Student A + Student C.
        """
        # Trip 1: Student A & B
        trip1 = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id, self.student_b.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('100.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip1,
            return_time='13:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('1000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('60.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        # Trip 2: Student A & C
        trip2 = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place2,
            trip_date=timezone.now().date(),
            departure_time='14:00:00',
            student_ids=[self.student_a.id, self.student_c.id],
            calendars_issued=30,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=51,
            bus_fare=Decimal('40.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip2,
            return_time='18:00:00',
            calendars_sold=30,
            calendars_returned=0,
            cash_collection=Decimal('600.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('20.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=51,
            receipt_ending_leaf=80,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        calc_a = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        calc_b = FinancialService.recalculate_student_commission(self.campaign, self.student_b)
        calc_c = FinancialService.recalculate_student_commission(self.campaign, self.student_c)

        # Student A:
        # Trip 1: Gross 500, Fare 50, Food 30, Net 420
        # Trip 2: Gross 300, Fare 20, Food 10, Net 270
        # Total: Gross 800, Fare 70, Food 40, Net 690, Commission 69.00
        self.assertEqual(calc_a.gross_collection, Decimal('800.00'))
        self.assertEqual(calc_a.fare_share, Decimal('70.00'))
        self.assertEqual(calc_a.food_share, Decimal('40.00'))
        self.assertEqual(calc_a.net_collection, Decimal('690.00'))
        self.assertEqual(calc_a.calculated_commission, Decimal('69.00'))

        # Student B: Gross 500, Fare 50, Food 30, Net 420, Commission 42.00
        self.assertEqual(calc_b.gross_collection, Decimal('500.00'))
        self.assertEqual(calc_b.fare_share, Decimal('50.00'))
        self.assertEqual(calc_b.food_share, Decimal('30.00'))
        self.assertEqual(calc_b.net_collection, Decimal('420.00'))
        self.assertEqual(calc_b.calculated_commission, Decimal('42.00'))

        # Student C: Gross 300, Fare 20, Food 10, Net 270, Commission 27.00
        self.assertEqual(calc_c.gross_collection, Decimal('300.00'))
        self.assertEqual(calc_c.fare_share, Decimal('20.00'))
        self.assertEqual(calc_c.food_share, Decimal('10.00'))
        self.assertEqual(calc_c.net_collection, Decimal('270.00'))
        self.assertEqual(calc_c.calculated_commission, Decimal('27.00'))

    def test_paise_rounding_precision_exhaustive(self):
        """
        Verify paise splitting algorithm across arbitrary student counts without leaking or creating money.
        """
        # Split ₹10.00 among 3: [3.34, 3.33, 3.33]
        s1 = split_amount_in_paise(Decimal('10.00'), 3)
        self.assertEqual(sum(s1), Decimal('10.00'))
        self.assertEqual(s1, [Decimal('3.34'), Decimal('3.33'), Decimal('3.33')])

        # Split ₹100.01 among 7 students
        s2 = split_amount_in_paise(Decimal('100.01'), 7)
        self.assertEqual(sum(s2), Decimal('100.01'))
        # 10001 // 7 = 1428 paise (14.28), remainder = 5 paise
        self.assertEqual(s2.count(Decimal('14.29')), 5)
        self.assertEqual(s2.count(Decimal('14.28')), 2)

        # Split ₹0.05 among 3 students
        s3 = split_amount_in_paise(Decimal('0.05'), 3)
        self.assertEqual(sum(s3), Decimal('0.05'))
        self.assertEqual(s3, [Decimal('0.02'), Decimal('0.02'), Decimal('0.01')])

        # Split ₹0.00 among 4 students
        s4 = split_amount_in_paise(Decimal('0.00'), 4)
        self.assertEqual(sum(s4), Decimal('0.00'))
        self.assertEqual(s4, [Decimal('0.00'), Decimal('0.00'), Decimal('0.00'), Decimal('0.00')])

    def test_duplicate_settlement_rejected(self):
        """Settling an already settled trip must raise ValidationError."""
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=10,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip,
            return_time='11:00:00',
            calendars_sold=10,
            calendars_returned=0,
            cash_collection=Decimal('200.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=10,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        with self.assertRaises(ValidationError) as ctx:
            TripService.settle_trip(
                trip=trip,
                return_time='12:00:00',
                calendars_sold=10,
                calendars_returned=0,
                cash_collection=Decimal('200.00'),
                gpay_collection=Decimal('0.00'),
                food_expense=Decimal('0.00'),
                receipt_book=self.receipt_book,
                receipt_starting_leaf=1,
                receipt_ending_leaf=10,
                voided_leaves='',
                discrepancy_notes='',
                user=self.admin_user
            )
        self.assertIn("already been settled", str(ctx.exception))

    def test_settle_voided_trip_rejected(self):
        """Attempting to settle a voided trip must raise ValidationError."""
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=10,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        TripService.void_trip(trip=trip, reason='Bad weather', user=self.admin_user)

        with self.assertRaises(ValidationError) as ctx:
            TripService.settle_trip(
                trip=trip,
                return_time='11:00:00',
                calendars_sold=10,
                calendars_returned=0,
                cash_collection=Decimal('200.00'),
                gpay_collection=Decimal('0.00'),
                food_expense=Decimal('0.00'),
                receipt_book=self.receipt_book,
                receipt_starting_leaf=1,
                receipt_ending_leaf=10,
                voided_leaves='',
                discrepancy_notes='',
                user=self.admin_user
            )
        self.assertIn("Cannot settle a voided trip", str(ctx.exception))

    def test_inventory_void_reversal_and_boundaries(self):
        """
        Verify:
        1. Voiding an active trip restores stock.
        2. Negative adjustment exceeding stock raises ValidationError.
        """
        initial_stock = InventoryService.get_campaign_inventory_summary(self.campaign)['available_stock']
        self.assertEqual(initial_stock, 2000)

        # Dispatch 50 calendars -> available stock becomes 1950
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        mid_stock = InventoryService.get_campaign_inventory_summary(self.campaign)['available_stock']
        self.assertEqual(mid_stock, 1950)

        # Void trip -> stock restored back to 2000
        TripService.void_trip(trip=trip, reason='Trip cancelled', user=self.admin_user)
        restored_stock = InventoryService.get_campaign_inventory_summary(self.campaign)['available_stock']
        self.assertEqual(restored_stock, 2000)

        # Negative adjustment exceeding stock (e.g. -2500 when 2000 available)
        with self.assertRaises(ValidationError) as ctx:
            InventoryService.record_adjustment(
                campaign=self.campaign,
                quantity=-2500,
                reason='Audit write-off excess',
                user=self.superadmin
            )
        self.assertIn("negative", str(ctx.exception).lower())

    def test_expense_void_reversals(self):
        """Voiding an expense removes it from active operational outflow immediately."""
        exp = Expense.objects.create(
            campaign=self.campaign,
            category='transport',
            amount=Decimal('450.00'),
            date=timezone.now().date(),
            description='Auto rickshaw local transport',
            created_by=self.admin_user
        )
        fin_before = FinancialService.get_campaign_financial_summary(self.campaign)
        self.assertEqual(fin_before['general_expenses'], Decimal('450.00'))

        # Void the expense
        exp.is_voided = True
        exp.voided_reason = 'Double entry'
        exp.voided_at = timezone.now()
        exp.voided_by = self.admin_user
        exp.save()

        fin_after = FinancialService.get_campaign_financial_summary(self.campaign)
        self.assertEqual(fin_after['general_expenses'], Decimal('0.00'))

    def test_commission_payout_sequential_and_boundaries(self):
        """
        Verify:
        1. Cannot disburse payout exceeding remaining payable.
        2. Sequential partial payouts reduce balance to zero.
        3. Payout does not distort net campaign profit.
        """
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('0.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip,
            return_time='13:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('1000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('0.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        calc = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        # Net 1000, 10% = 100.00
        self.assertEqual(calc.calculated_commission, Decimal('100.00'))

        def get_remaining():
            from django.db.models import Sum
            paid = CommissionPayout.objects.filter(
                campaign=self.campaign,
                student=self.student_a
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
            return calc.calculated_commission - paid

        self.assertEqual(get_remaining(), Decimal('100.00'))

        # Attempt payout of ₹150.00 (exceeds ₹100.00)
        with self.assertRaises(ValidationError) as ctx:
            FinancialService.record_payout(
                campaign=self.campaign,
                student=self.student_a,
                amount=Decimal('150.00'),
                payment_date=timezone.now().date(),
                payment_method='cash',
                reference='',
                notes='',
                user=self.superadmin
            )
        self.assertIn("exceeds remaining payable", str(ctx.exception))

        # First partial payout: ₹40.00
        p1 = FinancialService.record_payout(
            campaign=self.campaign,
            student=self.student_a,
            amount=Decimal('40.00'),
            payment_date=timezone.now().date(),
            payment_method='cash',
            reference='VOUCHER-01',
            notes='',
            user=self.superadmin
        )
        self.assertEqual(get_remaining(), Decimal('60.00'))

        # Second payout: remaining ₹60.00
        p2 = FinancialService.record_payout(
            campaign=self.campaign,
            student=self.student_a,
            amount=Decimal('60.00'),
            payment_date=timezone.now().date(),
            payment_method='gpay',
            reference='UPI-7788',
            notes='',
            user=self.superadmin
        )
        self.assertEqual(get_remaining(), Decimal('0.00'))

        # Further payout rejected
        with self.assertRaises(ValidationError):
            FinancialService.record_payout(
                campaign=self.campaign,
                student=self.student_a,
                amount=Decimal('5.00'),
                payment_date=timezone.now().date(),
                payment_method='cash',
                reference='',
                notes='',
                user=self.superadmin
            )

    def test_campaign_settings_update_idempotency_and_boundaries(self):
        """
        Verify:
        1. Updating printed_quantity and cost_price_per_calendar updates the existing printing expense
           without duplicating expense records.
        2. Opening stock movement quantity updates cleanly.
        3. Validating that printed_quantity cannot be reduced below already committed calendars (sold + in_field).
        """
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.superadmin)

        # Initialize opening printing expense for self.campaign
        Expense.objects.get_or_create(
            campaign=self.campaign,
            category='printing',
            is_voided=False,
            defaults={
                'amount': self.campaign.proposed_printing_expense,
                'date': timezone.now().date(),
                'description': f"Initial printing expense: {self.campaign.printed_quantity} calendars @ ₹{self.campaign.cost_price_per_calendar}",
                'created_by': self.superadmin,
            }
        )

        url = f"/api/v1/campaigns/{self.campaign.id}/"

        # Check initial state: 1 printing expense of 2000 * 11 = 22,000
        printing_expenses = Expense.objects.filter(campaign=self.campaign, category='printing', is_voided=False)
        self.assertEqual(printing_expenses.count(), 1)
        self.assertEqual(printing_expenses.first().amount, Decimal('22000.00'))

        # Update via API to 2500 calendars @ ₹12.00
        res = client.patch(url, {
            'printed_quantity': 2500,
            'cost_price_per_calendar': '12.00',
            'min_expected_collection_per_calendar': '22.00',
            'commission_percentage': '12.00',
        }, format='json')
        self.assertEqual(res.status_code, 200)

        # Verify expense count is STILL 1 and amount is updated to 30,000.00 (2500 * 12)
        printing_expenses = Expense.objects.filter(campaign=self.campaign, category='printing', is_voided=False)
        self.assertEqual(printing_expenses.count(), 1)
        self.assertEqual(printing_expenses.first().amount, Decimal('30000.00'))

        # Verify opening stock inventory movement is updated to 2500
        op_movement = InventoryMovement.objects.get(campaign=self.campaign, movement_type='opening_stock')
        self.assertEqual(op_movement.quantity, 2500)

        # Issue 100 calendars to a trip, sell 70
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=100,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('50.00'),
            notes='',
            user=self.admin_user
        )
        TripService.settle_trip(
            trip=trip,
            return_time='13:00:00',
            calendars_sold=70,
            calendars_returned=30,
            cash_collection=Decimal('1540.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('20.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=70,
            voided_leaves='',
            discrepancy_notes='',
            user=self.admin_user
        )

        # Now 70 calendars are sold. Attempting to reduce printed_quantity to 50 must fail validation
        res_fail = client.patch(url, {
            'printed_quantity': 50
        }, format='json')
        self.assertEqual(res_fail.status_code, 400)
        self.assertIn("cannot be lower than calendars already committed", str(res_fail.data))

    def test_campaign_activation_and_close_endpoints(self):
        """Verify activating and closing campaigns via API endpoints."""
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.superadmin)
        url_close = f"/api/v1/campaigns/{self.campaign.id}/close/"
        url_activate = f"/api/v1/campaigns/{self.campaign.id}/activate/"

        # Close campaign
        res_close = client.post(url_close)
        self.assertEqual(res_close.status_code, 200)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'closed')
        self.assertIsNotNone(self.campaign.closed_at)

        # Activate campaign
        res_act = client.post(url_activate)
        self.assertEqual(res_act.status_code, 200)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, 'active')
        self.assertIsNone(self.campaign.closed_at)

    def test_external_collection_creation_and_audit(self):
        """Verify adding an external collection records user, timestamp, and audit trail."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        url = "/api/v1/external-collections/"
        payload = {
            'campaign': self.campaign.id,
            'received_from': 'Haji Usman',
            'amount': '5000.00',
            'date_received': '2026-10-15',
            'notes': 'Direct well-wisher sponsorship'
        }
        res = client.post(url, payload, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['received_from'], 'Haji Usman')
        self.assertEqual(res.data['amount'], '5000.00')
        self.assertEqual(res.data['created_by'], self.admin_user.id)
        self.assertEqual(res.data['created_by_name'], self.admin_user.display_name)
        self.assertIsNotNone(res.data['created_at'])

        # Check AuditLog
        log = AuditLog.objects.filter(
            action='external_collection_create',
            entity_type='ExternalCollection',
            entity_id=str(res.data['id'])
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)
        self.assertEqual(log.after_snapshot['received_from'], 'Haji Usman')
        self.assertEqual(log.after_snapshot['amount'], '5000.00')

    def test_external_collection_validation(self):
        """Verify validation rules on amount, recipient name, and campaign state."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        url = "/api/v1/external-collections/"

        # Negative amount
        res_neg = client.post(url, {
            'campaign': self.campaign.id,
            'received_from': 'Donor A',
            'amount': '-500.00',
            'date_received': '2026-10-15'
        }, format='json')
        self.assertEqual(res_neg.status_code, 400)
        self.assertIn("must be greater than zero", str(res_neg.data))

        # Zero amount
        res_zero = client.post(url, {
            'campaign': self.campaign.id,
            'received_from': 'Donor A',
            'amount': '0.00',
            'date_received': '2026-10-15'
        }, format='json')
        self.assertEqual(res_zero.status_code, 400)
        self.assertIn("must be greater than zero", str(res_zero.data))

        # Empty received_from
        res_empty = client.post(url, {
            'campaign': self.campaign.id,
            'received_from': '   ',
            'amount': '1000.00',
            'date_received': '2026-10-15'
        }, format='json')
        self.assertEqual(res_empty.status_code, 400)
        self.assertTrue('received_from' in res_empty.data)

        # Closed campaign
        self.campaign.status = 'closed'
        self.campaign.save()
        res_closed = client.post(url, {
            'campaign': self.campaign.id,
            'received_from': 'Donor B',
            'amount': '1000.00',
            'date_received': '2026-10-15'
        }, format='json')
        self.assertEqual(res_closed.status_code, 400)
        self.assertIn("closed campaign", str(res_closed.data))

    def test_external_collection_update_and_audit(self):
        """Verify editing/correcting an external collection records updater and audit trail."""
        ec = ExternalCollection.objects.create(
            campaign=self.campaign,
            received_from='Original Name',
            amount=Decimal('2500.00'),
            date_received=timezone.now().date(),
            created_by=self.superadmin
        )
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        url = f"/api/v1/external-collections/{ec.id}/"
        res = client.patch(url, {
            'received_from': 'Corrected Name',
            'amount': '3000.00',
            'notes': 'Typo corrected'
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['received_from'], 'Corrected Name')
        self.assertEqual(res.data['amount'], '3000.00')

        ec.refresh_from_db()
        self.assertEqual(ec.updated_by, self.admin_user)
        self.assertEqual(ec.amount, Decimal('3000.00'))

        log = AuditLog.objects.filter(
            action='external_collection_update',
            entity_type='ExternalCollection',
            entity_id=str(ec.id)
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)
        self.assertEqual(log.before_snapshot['received_from'], 'Original Name')
        self.assertEqual(log.after_snapshot['received_from'], 'Corrected Name')

    def test_external_collection_permissions(self):
        """Verify only authenticated administrators can create and access external collections."""
        client = APIClient()
        url = "/api/v1/external-collections/"

        # Unauthenticated
        res_unauth = client.get(url)
        self.assertEqual(res_unauth.status_code, 401)

        # Authenticated as normal non-admin user
        normal_user = User.objects.create_user(
            phone_number='9999999999',
            password='NormalUserPass123!',
            display_name='Regular User',
            role='viewer',
            is_staff=False
        )
        client.force_authenticate(user=normal_user)
        res_forbidden = client.get(url)
        self.assertEqual(res_forbidden.status_code, 403)

    def test_external_collection_campaign_isolation(self):
        """Verify external collections are strictly isolated by campaign."""
        campaign_2027 = Campaign.objects.create(
            name='Calendar Fund 2027',
            year=2027,
            printed_quantity=2500,
            cost_price_per_calendar=Decimal('12.00'),
            min_expected_collection_per_calendar=Decimal('25.00'),
            commission_percentage=Decimal('10.00'),
            created_by=self.superadmin,
        )
        ec_2026 = ExternalCollection.objects.create(
            campaign=self.campaign,
            received_from='2026 Contributor',
            amount=Decimal('4000.00'),
            date_received=timezone.now().date(),
            created_by=self.superadmin
        )
        ec_2027 = ExternalCollection.objects.create(
            campaign=campaign_2027,
            received_from='2027 Contributor',
            amount=Decimal('8000.00'),
            date_received=timezone.now().date(),
            created_by=self.superadmin
        )

        client = APIClient()
        client.force_authenticate(user=self.admin_user)

        res_2026 = client.get(f"/api/v1/external-collections/?campaign={self.campaign.id}")
        self.assertEqual(res_2026.status_code, 200)
        items_2026 = res_2026.data.get('results', res_2026.data)
        self.assertEqual(len(items_2026), 1)
        self.assertEqual(items_2026[0]['id'], ec_2026.id)

        res_2027 = client.get(f"/api/v1/external-collections/?campaign={campaign_2027.id}")
        self.assertEqual(res_2027.status_code, 200)
        items_2027 = res_2027.data.get('results', res_2027.data)
        self.assertEqual(len(items_2027), 1)
        self.assertEqual(items_2027[0]['id'], ec_2027.id)

    def test_external_collection_financial_reporting_and_exclusion_from_commission(self):
        """
        Verify external collections are included in campaign total-received and net profit,
        while strictly excluded from student trip collections, student net, and student commission.
        """
        # 1. Dispatch and settle a trip with 2 students
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id, self.student_b.id],
            calendars_issued=100,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('600.00'),
            notes='',
            user=self.superadmin
        )

        TripService.settle_trip(
            trip=trip,
            return_time='17:00:00',
            calendars_sold=80,
            calendars_returned=20,
            cash_collection=Decimal('5000.00'),
            gpay_collection=Decimal('5000.00'),
            food_expense=Decimal('400.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=80,
            voided_leaves='',
            discrepancy_notes='',
            user=self.superadmin
        )

        # Before external collection:
        # Trip collections = 10,000 (Cash 5000 + GPay 5000)
        # Deductions = 600 (fare) + 400 (food) = 1000
        # Student A: Gross 5000, Fare 300, Food 200, Net 4500, Comm 450
        # Student B: Gross 5000, Fare 300, Food 200, Net 4500, Comm 450
        # Total Commission = 900
        calc_a_before = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        self.assertEqual(calc_a_before.gross_collection, Decimal('5000.00'))
        self.assertEqual(calc_a_before.net_collection, Decimal('4500.00'))
        self.assertEqual(calc_a_before.calculated_commission, Decimal('450.00'))

        summary_before = FinancialService.get_campaign_financial_summary(self.campaign)
        self.assertEqual(summary_before['student_collections'], Decimal('10000.00'))
        self.assertEqual(summary_before['external_collections'], Decimal('0.00'))
        self.assertEqual(summary_before['total_received'], Decimal('10000.00'))
        self.assertEqual(summary_before['total_commission_earned'], Decimal('900.00'))

        # 2. Now add an External Collection of ₹50,000
        ec = ExternalCollection.objects.create(
            campaign=self.campaign,
            received_from='Generous Patron',
            amount=Decimal('50000.00'),
            date_received=timezone.now().date(),
            notes='Patron donation to campaign',
            created_by=self.superadmin
        )

        # 3. Recalculate student commissions and verify ZERO change
        calc_a_after = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        self.assertEqual(calc_a_after.gross_collection, Decimal('5000.00'))
        self.assertEqual(calc_a_after.fare_share, Decimal('300.00'))
        self.assertEqual(calc_a_after.food_share, Decimal('200.00'))
        self.assertEqual(calc_a_after.net_collection, Decimal('4500.00'))
        self.assertEqual(calc_a_after.calculated_commission, Decimal('450.00'))

        calc_b_after = FinancialService.recalculate_student_commission(self.campaign, self.student_b)
        self.assertEqual(calc_b_after.calculated_commission, Decimal('450.00'))

        # 4. Check campaign financial summary
        summary_after = FinancialService.get_campaign_financial_summary(self.campaign)
        # Student collections must remain exactly 10,000
        self.assertEqual(summary_after['student_collections'], Decimal('10000.00'))
        self.assertEqual(summary_after['total_collections'], Decimal('10000.00'))
        # External collections must be 50,000
        self.assertEqual(summary_after['external_collections'], Decimal('50000.00'))
        # Total received must be exactly 60,000 (no double counting)
        self.assertEqual(summary_after['total_received'], Decimal('60000.00'))
        # Commission must still be 900
        self.assertEqual(summary_after['total_commission_earned'], Decimal('900.00'))
        # Net profit = 60,000 - 600 - 400 - 0 (general) - 900 = 58,100
        expected_net_profit = Decimal('60000.00') - Decimal('600.00') - Decimal('400.00') - Decimal('900.00')
        self.assertEqual(summary_after['net_profit'], expected_net_profit)

    def test_external_collection_calendars_given_and_inventory_deduction(self):
        """Verify calendars given to external donor are subtracted from campaign available inventory."""
        inv_before = InventoryService.get_campaign_inventory_summary(self.campaign)
        initial_available = inv_before['available_stock']
        self.assertEqual(inv_before['calendars_external'], 0)

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        url = "/api/v1/external-collections/"

        # 1. Create with 120 calendars given
        res = client.post(url, {
            'campaign': self.campaign.id,
            'received_from': 'Patron With Calendars',
            'amount': '15000.00',
            'calendars_given': 120,
            'date_received': '2026-10-16',
            'notes': '120 calendars given directly to patron'
        }, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['calendars_given'], 120)

        # 2. Check inventory summary
        inv_after = InventoryService.get_campaign_inventory_summary(self.campaign)
        self.assertEqual(inv_after['calendars_external'], 120)
        self.assertEqual(inv_after['available_stock'], initial_available - 120)

        # 3. Validation: Exceeding available stock
        res_overflow = client.post(url, {
            'campaign': self.campaign.id,
            'received_from': 'Greedy Request',
            'amount': '500000.00',
            'calendars_given': inv_after['available_stock'] + 100,
            'date_received': '2026-10-16'
        }, format='json')
        self.assertEqual(res_overflow.status_code, 400)
        self.assertIn("Insufficient stock", str(res_overflow.data))

    def test_trip_delete_in_progress_and_restore_stock(self):
        """Verify deleting an in-progress trip restores available stock and records audit log."""
        stock_before = InventoryService.get_campaign_inventory_summary(self.campaign)['available_stock']

        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='08:30:00',
            student_ids=[self.student_a.id],
            calendars_issued=60,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('100.00'),
            notes='Test dispatch for deletion',
            user=self.superadmin
        )
        # In field stock is now 60, available stock is reduced by 60
        stock_during = InventoryService.get_campaign_inventory_summary(self.campaign)['available_stock']
        self.assertEqual(stock_during, stock_before - 60)

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        res = client.delete(f"/api/v1/trips/{trip.id}/", {'reason': 'Cancelled dispatch due to rain'}, format='json')
        self.assertIn(res.status_code, [200, 204])

        # Trip must be deleted
        self.assertFalse(Trip.objects.filter(id=trip.id).exists())
        # Inventory movements for this trip must be cleaned up
        self.assertFalse(InventoryMovement.objects.filter(related_trip=trip).exists())
        # Stock must be completely restored
        stock_after = InventoryService.get_campaign_inventory_summary(self.campaign)['available_stock']
        self.assertEqual(stock_after, stock_before)

        # AuditLog recorded with reason
        log = AuditLog.objects.filter(action='trip_delete', entity_id=str(trip.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)
        self.assertEqual(log.reason, 'Cancelled dispatch due to rain')

    def test_trip_delete_settled_and_recalculate_commission(self):
        """Verify deleting a settled trip recalculates participating students' commissions."""
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('200.00'),
            notes='',
            user=self.superadmin
        )
        TripService.settle_trip(
            trip=trip,
            return_time='16:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('5000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('100.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.superadmin
        )

        calc_before = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        self.assertGreater(calc_before.calculated_commission, Decimal('0.00'))

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        res = client.delete(f"/api/v1/trips/{trip.id}/")
        self.assertIn(res.status_code, [200, 204])

        # Commission should now be 0 as there are no settled trips
        calc_after = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        self.assertEqual(calc_after.calculated_commission, Decimal('0.00'))
        self.assertEqual(calc_after.gross_collection, Decimal('0.00'))

    def test_trip_delete_closed_campaign_forbidden(self):
        """Verify trips belonging to closed campaigns cannot be deleted."""
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=20,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('50.00'),
            notes='',
            user=self.superadmin
        )
        self.campaign.status = 'closed'
        self.campaign.save()

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        res = client.delete(f"/api/v1/trips/{trip.id}/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("closed campaign", str(res.data))

    def test_trip_delete_finalized_commission_forbidden(self):
        """Verify settled trips cannot be deleted if commissions have already been finalized."""
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('100.00'),
            notes='',
            user=self.superadmin
        )
        TripService.settle_trip(
            trip=trip,
            return_time='16:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('5000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('100.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.superadmin
        )
        calc = FinancialService.recalculate_student_commission(self.campaign, self.student_a)
        calc.finalization_status = 'finalized'
        calc.save()

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        res = client.delete(f"/api/v1/trips/{trip.id}/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already been finalized", str(res.data))

    def test_trip_delete_disbursed_payout_exceeding_revised_forbidden(self):
        """Verify settled trips cannot be deleted if payouts would exceed the revised earned commission."""
        trip = TripService.dispatch_trip(
            campaign=self.campaign,
            place=self.place1,
            trip_date=timezone.now().date(),
            departure_time='09:00:00',
            student_ids=[self.student_a.id],
            calendars_issued=50,
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            bus_fare=Decimal('100.00'),
            notes='',
            user=self.superadmin
        )
        TripService.settle_trip(
            trip=trip,
            return_time='16:00:00',
            calendars_sold=50,
            calendars_returned=0,
            cash_collection=Decimal('5000.00'),
            gpay_collection=Decimal('0.00'),
            food_expense=Decimal('100.00'),
            receipt_book=self.receipt_book,
            receipt_starting_leaf=1,
            receipt_ending_leaf=50,
            voided_leaves='',
            discrepancy_notes='',
            user=self.superadmin
        )
        # Record payout for student_a
        CommissionPayout.objects.create(
            campaign=self.campaign,
            student=self.student_a,
            amount=Decimal('480.00'),
            payment_date=timezone.now().date(),
            payment_method='cash',
            created_by=self.superadmin
        )

        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        res = client.delete(f"/api/v1/trips/{trip.id}/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already received payout", str(res.data))


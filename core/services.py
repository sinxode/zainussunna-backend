from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Sum, Q, F
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import (
    Campaign, Student, Place, ReceiptBook, Trip, TripStudent,
    InventoryMovement, Expense, CommissionCalculation, CommissionPayout,
    AuditLog, User, split_amount_in_paise
)


class InventoryService:
    @staticmethod
    def get_campaign_inventory_summary(campaign: Campaign) -> dict:
        """
        Calculate authoritative real-time inventory metrics for a campaign.
        Stock available = Printed quantity − Sold quantity − Quantity currently issued and not yet reconciled + Adjustments
        """
        # Calendars currently distributed in open trips
        in_field = Trip.objects.filter(
            campaign=campaign,
            status='in_progress'
        ).aggregate(total=Sum('calendars_issued'))['total'] or 0

        # Settled sales
        sold = Trip.objects.filter(
            campaign=campaign,
            status='settled'
        ).aggregate(total=Sum('calendars_sold'))['total'] or 0

        # Settled returned unsold
        returned = Trip.objects.filter(
            campaign=campaign,
            status='settled'
        ).aggregate(total=Sum('calendars_returned'))['total'] or 0

        # Inventory adjustments
        adjustments = InventoryMovement.objects.filter(
            campaign=campaign,
            movement_type='adjustment'
        ).aggregate(total=Sum('quantity'))['total'] or 0

        printed = campaign.printed_quantity
        available = printed - sold - in_field + adjustments

        return {
            'printed_quantity': printed,
            'calendars_sold': sold,
            'calendars_in_field': in_field,
            'calendars_returned': returned,
            'adjustments': adjustments,
            'available_stock': available,
        }

    @staticmethod
    def assert_stock_available(campaign: Campaign, requested_quantity: int):
        """
        Verify that requested quantity does not exceed currently available stock.
        """
        summary = InventoryService.get_campaign_inventory_summary(campaign)
        if requested_quantity > summary['available_stock']:
            raise ValidationError(
                f"Insufficient stock: requested {requested_quantity}, but only {summary['available_stock']} calendars are available."
            )

    @staticmethod
    def record_adjustment(campaign: Campaign, quantity: int, reason: str, user: User | None) -> InventoryMovement:
        """
        Record a manual inventory adjustment with boundary check preventing negative stock.
        """
        if quantity == 0:
            raise ValidationError("Adjustment quantity cannot be zero.")
        summary = InventoryService.get_campaign_inventory_summary(campaign)
        if summary['available_stock'] + quantity < 0:
            raise ValidationError(
                f"Adjustment would cause available stock to become negative (available: {summary['available_stock']}, requested adjustment: {quantity})."
            )
        movement = InventoryMovement.objects.create(
            campaign=campaign,
            movement_type='adjustment',
            quantity=quantity,
            reason=reason,
            created_by=user,
        )
        AuditLog.objects.create(
            user=user,
            action='inventory_adjustment',
            entity_type='InventoryMovement',
            entity_id=str(movement.id),
            after_snapshot={
                'campaign': campaign.year,
                'quantity': quantity,
                'reason': reason,
            },
            reason=reason,
        )
        return movement


class ReceiptBookService:
    @staticmethod
    def get_next_suggested_leaf(receipt_book: ReceiptBook) -> int:
        """Suggest the next available leaf in the receipt book based on recorded trips."""
        highest_leaf = Trip.objects.filter(
            receipt_book=receipt_book
        ).exclude(status='voided').order_by('-receipt_ending_leaf').first()

        if highest_leaf and highest_leaf.receipt_ending_leaf:
            next_leaf = highest_leaf.receipt_ending_leaf + 1
            if next_leaf <= receipt_book.last_leaf:
                return next_leaf

        return receipt_book.first_leaf

    @staticmethod
    def validate_leaf_range(receipt_book: ReceiptBook, start_leaf: int, end_leaf: int, exclude_trip_id=None):
        if start_leaf < receipt_book.first_leaf or end_leaf > receipt_book.last_leaf:
            raise ValidationError(
                f"Receipt leaf range {start_leaf}-{end_leaf} is outside book range {receipt_book.first_leaf}-{receipt_book.last_leaf}."
            )
        if start_leaf > end_leaf:
            raise ValidationError("Starting leaf cannot be greater than ending leaf.")

        # Check for overlap with existing non-voided trips in the same receipt book
        conflicts = Trip.objects.filter(
            receipt_book=receipt_book,
            receipt_starting_leaf__isnull=False,
            receipt_ending_leaf__isnull=False,
        ).exclude(status='voided')

        if exclude_trip_id:
            conflicts = conflicts.exclude(id=exclude_trip_id)

        for trip in conflicts:
            # Overlap occurs if start <= trip.end and end >= trip.start
            if not (end_leaf < trip.receipt_starting_leaf or start_leaf > trip.receipt_ending_leaf):
                raise ValidationError(
                    f"Receipt leaf range {start_leaf}-{end_leaf} overlaps with Trip #{trip.id} ({trip.receipt_starting_leaf}-{trip.receipt_ending_leaf})."
                )


class TripService:
    @staticmethod
    def dispatch_trip(
        campaign: Campaign,
        place: Place,
        trip_date,
        departure_time,
        student_ids: list[int],
        calendars_issued: int,
        receipt_book: ReceiptBook | None,
        receipt_starting_leaf: int | None,
        bus_fare: Decimal,
        notes: str,
        user: User | None
    ) -> Trip:
        """
        Atomic dispatch of a group of 1 to 3 students.
        Ensures stock availability and prevents double-assignment of students.
        """
        if campaign.status == 'closed':
            raise ValidationError("Cannot dispatch trips for a closed campaign.")

        if not (1 <= len(student_ids) <= 3):
            raise ValidationError("A trip must have between 1 and 3 students.")

        if len(set(student_ids)) != len(student_ids):
            raise ValidationError("Duplicate students cannot be assigned to the same trip.")

        if calendars_issued <= 0:
            raise ValidationError("Issued calendar quantity must be greater than zero.")

        students = list(Student.objects.filter(id__in=student_ids, is_active=True))
        if len(students) != len(student_ids):
            raise ValidationError("One or more selected students are invalid or inactive.")

        with transaction.atomic():
            # Check if any student is currently on an open trip
            open_trips = Trip.objects.filter(
                campaign=campaign,
                status='in_progress',
                trip_students__student__in=students
            ).distinct()

            if open_trips.exists():
                conflict_trip = open_trips.first()
                conflicting_students = Student.objects.filter(
                    trip_participations__trip=conflict_trip,
                    id__in=student_ids
                ).values_list('name', flat=True)
                raise ValidationError(
                    f"Student(s) {', '.join(conflicting_students)} already assigned to active Trip #{conflict_trip.id}."
                )

            # Atomic inventory check
            InventoryService.assert_stock_available(campaign, calendars_issued)

            # Receipt leaf validation if starting leaf provided
            if receipt_book and receipt_starting_leaf:
                if receipt_starting_leaf < receipt_book.first_leaf or receipt_starting_leaf > receipt_book.last_leaf:
                    raise ValidationError(
                        f"Receipt leaf {receipt_starting_leaf} is outside book range {receipt_book.first_leaf}-{receipt_book.last_leaf}."
                    )

            trip = Trip.objects.create(
                campaign=campaign,
                place=place,
                trip_date=trip_date,
                departure_time=departure_time,
                calendars_issued=calendars_issued,
                bus_fare=bus_fare,
                receipt_book=receipt_book,
                receipt_starting_leaf=receipt_starting_leaf,
                discrepancy_notes=notes,
                created_by=user,
                status='in_progress',
            )

            for student in students:
                TripStudent.objects.create(trip=trip, student=student)

            # Record inventory movement
            InventoryMovement.objects.create(
                campaign=campaign,
                movement_type='trip_issue',
                quantity=-calendars_issued,
                related_trip=trip,
                reason=f"Issued for Trip #{trip.id} to {place.name}",
                created_by=user,
            )

            # Audit log
            AuditLog.objects.create(
                user=user,
                action='trip_dispatch',
                entity_type='Trip',
                entity_id=str(trip.id),
                after_snapshot={
                    'trip_id': trip.id,
                    'place': place.name,
                    'calendars_issued': calendars_issued,
                    'students': [s.name for s in students],
                    'bus_fare': str(bus_fare),
                },
                reason="Trip dispatched"
            )

            return trip

    @staticmethod
    def settle_trip(
        trip: Trip,
        return_time,
        calendars_sold: int,
        calendars_returned: int,
        cash_collection: Decimal,
        gpay_collection: Decimal,
        food_expense: Decimal,
        receipt_book: ReceiptBook | None,
        receipt_starting_leaf: int | None,
        receipt_ending_leaf: int | None,
        voided_leaves: str,
        discrepancy_notes: str,
        user: User | None
    ) -> Trip:
        """
        Settle a returned trip atomically.
        Calculates exact shares, checks discrepancies, updates inventory, and recalculates commissions.
        """
        with transaction.atomic():
            trip = Trip.objects.select_for_update().get(id=trip.id)

            if trip.status == 'settled':
                raise ValidationError("This trip has already been settled.")
            if trip.status == 'voided':
                raise ValidationError("Cannot settle a voided trip.")

            if calendars_sold < 0 or calendars_returned < 0:
                raise ValidationError("Sold and returned quantities cannot be negative.")

            if cash_collection < 0 or gpay_collection < 0 or food_expense < 0:
                raise ValidationError("Monetary values cannot be negative.")

            # Validate receipt range if provided
            if receipt_book and receipt_starting_leaf and receipt_ending_leaf:
                ReceiptBookService.validate_leaf_range(
                    receipt_book, receipt_starting_leaf, receipt_ending_leaf, exclude_trip_id=trip.id
                )

            total_collection = cash_collection + gpay_collection
            expected_min_collection = Decimal(calendars_sold) * trip.campaign.min_expected_collection_per_calendar
            shortfall = expected_min_collection - total_collection
            stock_discrepancy = trip.calendars_issued - (calendars_sold + calendars_returned)

            # Determine review status
            needs_review = False
            review_reasons = []

            if shortfall > 0:
                needs_review = True
                review_reasons.append(f"Collection shortfall of ₹{shortfall:.2f} below expected ₹{expected_min_collection:.2f}")

            if stock_discrepancy != 0:
                needs_review = True
                review_reasons.append(f"Stock discrepancy: issued {trip.calendars_issued}, but sold ({calendars_sold}) + returned ({calendars_returned}) = {calendars_sold + calendars_returned}")

            # Check negative trip net: total_collection < bus_fare + food_expense
            if total_collection < (trip.bus_fare + food_expense):
                needs_review = True
                review_reasons.append(f"Negative trip net: collection ₹{total_collection:.2f} is less than expenses ₹{(trip.bus_fare + food_expense):.2f}")

            if needs_review and not discrepancy_notes.strip():
                raise ValidationError(
                    f"Warning: {'; '.join(review_reasons)}. An explanatory note is required to settle this trip."
                )

            review_status = 'needs_review' if needs_review else 'no_review_needed'

            before_snapshot = {
                'status': trip.status,
                'calendars_issued': trip.calendars_issued,
                'bus_fare': str(trip.bus_fare),
            }

            trip.return_time = return_time
            trip.calendars_sold = calendars_sold
            trip.calendars_returned = calendars_returned
            trip.cash_collection = cash_collection
            trip.gpay_collection = gpay_collection
            trip.food_expense = food_expense
            trip.receipt_book = receipt_book or trip.receipt_book
            trip.receipt_starting_leaf = receipt_starting_leaf
            trip.receipt_ending_leaf = receipt_ending_leaf
            trip.voided_leaves = voided_leaves
            trip.discrepancy_notes = discrepancy_notes
            trip.status = 'settled'
            trip.review_status = review_status
            trip.settled_by = user
            trip.settled_at = timezone.now()
            trip.save()

            # Record inventory movements: sold and returned unsold
            if calendars_sold > 0:
                InventoryMovement.objects.create(
                    campaign=trip.campaign,
                    movement_type='trip_sold',
                    quantity=-calendars_sold,
                    related_trip=trip,
                    reason=f"Settled sales from Trip #{trip.id}",
                    created_by=user,
                )

            if calendars_returned > 0:
                InventoryMovement.objects.create(
                    campaign=trip.campaign,
                    movement_type='trip_return_unsold',
                    quantity=calendars_returned,
                    related_trip=trip,
                    reason=f"Returned unsold from Trip #{trip.id}",
                    created_by=user,
                )

            # Allocate trip shares among students
            participations = list(trip.trip_students.select_related('student').order_by('id'))
            count = len(participations)
            if count > 0:
                col_shares = split_amount_in_paise(total_collection, count)
                fare_shares = split_amount_in_paise(trip.bus_fare, count)
                food_shares = split_amount_in_paise(food_expense, count)

                for idx, part in enumerate(participations):
                    part.gross_collection_share = col_shares[idx]
                    part.bus_fare_share = fare_shares[idx]
                    part.food_expense_share = food_shares[idx]
                    part.net_collection_share = col_shares[idx] - fare_shares[idx] - food_shares[idx]
                    part.save()

            # Update or recalculate provisional commission for participating students
            for part in participations:
                FinancialService.recalculate_student_commission(trip.campaign, part.student)

            # Audit log
            after_snapshot = {
                'status': trip.status,
                'calendars_sold': calendars_sold,
                'calendars_returned': calendars_returned,
                'cash_collection': str(cash_collection),
                'gpay_collection': str(gpay_collection),
                'food_expense': str(food_expense),
                'review_status': trip.review_status,
            }

            AuditLog.objects.create(
                user=user,
                action='trip_settle',
                entity_type='Trip',
                entity_id=str(trip.id),
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                reason=f"Trip settled. Notes: {discrepancy_notes}",
            )

            return trip

    @staticmethod
    def void_trip(trip: Trip, reason: str, user: User | None) -> Trip:
        """Void an open or draft trip and return issued stock."""
        with transaction.atomic():
            trip = Trip.objects.select_for_update().get(id=trip.id)
            if trip.status == 'settled':
                raise ValidationError("Cannot void an already settled trip. An authorized adjustment must be used.")
            if trip.status == 'voided':
                return trip

            before_status = trip.status
            trip.status = 'voided'
            trip.discrepancy_notes = f"{trip.discrepancy_notes}\n[VOIDED]: {reason}".strip()
            trip.save()

            # Release reserved inventory
            InventoryMovement.objects.create(
                campaign=trip.campaign,
                movement_type='trip_return_unsold',
                quantity=trip.calendars_issued,
                related_trip=trip,
                reason=f"Voided Trip #{trip.id}: returning issued stock",
                created_by=user,
            )

            AuditLog.objects.create(
                user=user,
                action='trip_void',
                entity_type='Trip',
                entity_id=str(trip.id),
                before_snapshot={'status': before_status},
                after_snapshot={'status': 'voided'},
                reason=reason,
            )

            return trip


class FinancialService:
    @staticmethod
    def recalculate_student_commission(campaign: Campaign, student: Student) -> CommissionCalculation:
        """
        Aggregate a student's net collection across all settled trips in the campaign
        and compute earned commission.
        """
        participations = TripStudent.objects.filter(
            trip__campaign=campaign,
            trip__status='settled',
            student=student
        )

        gross = participations.aggregate(t=Sum('gross_collection_share'))['t'] or Decimal('0.00')
        fare = participations.aggregate(t=Sum('bus_fare_share'))['t'] or Decimal('0.00')
        food = participations.aggregate(t=Sum('food_expense_share'))['t'] or Decimal('0.00')
        net = gross - fare - food

        # Commission rate from campaign
        rate = campaign.commission_percentage
        # Commission is earned on net collection. If net collection is negative, earned commission is 0.
        if net > Decimal('0.00'):
            raw_commission = (net * rate) / Decimal('100.00')
            commission_earned = raw_commission.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            commission_earned = Decimal('0.00')

        calc, _ = CommissionCalculation.objects.get_or_create(
            campaign=campaign,
            student=student,
            defaults={
                'gross_collection': gross,
                'fare_share': fare,
                'food_share': food,
                'net_collection': net,
                'rate': rate,
                'calculated_commission': commission_earned,
                'finalization_status': 'provisional',
            }
        )

        if calc.finalization_status != 'finalized':
            calc.gross_collection = gross
            calc.fare_share = fare
            calc.food_share = food
            calc.net_collection = net
            calc.rate = rate
            calc.calculated_commission = commission_earned
            calc.save()

        return calc

    @staticmethod
    def get_campaign_financial_summary(campaign: Campaign) -> dict:
        """
        Calculates authoritative financial summary for a campaign.
        Net campaign profit = Total actual collections − Total bus fare − Total food expenses − Total general expenses − Total student commission earned.
        """
        settled_trips = Trip.objects.filter(campaign=campaign, status='settled')

        cash_coll = settled_trips.aggregate(t=Sum('cash_collection'))['t'] or Decimal('0.00')
        gpay_coll = settled_trips.aggregate(t=Sum('gpay_collection'))['t'] or Decimal('0.00')
        total_collections = cash_coll + gpay_coll

        total_bus_fare = settled_trips.aggregate(t=Sum('bus_fare'))['t'] or Decimal('0.00')
        total_food_expenses = settled_trips.aggregate(t=Sum('food_expense'))['t'] or Decimal('0.00')
        total_trip_expenses = total_bus_fare + total_food_expenses

        # General expenses (excluding fare and food which are already in trip deductions)
        general_expenses_qs = Expense.objects.filter(
            campaign=campaign,
            is_voided=False
        ).exclude(category__in=['bus_fare', 'food'])

        total_general_expenses = general_expenses_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        # Printing expense
        printing_expense = Expense.objects.filter(
            campaign=campaign,
            category='printing',
            is_voided=False
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        # Total student commission earned across all participating students in settled trips
        # Let's ensure every student who participated in a settled trip has up-to-date calculation
        participating_students = Student.objects.filter(
            trip_participations__trip__campaign=campaign,
            trip_participations__trip__status='settled'
        ).distinct()

        for s in participating_students:
            FinancialService.recalculate_student_commission(campaign, s)

        comm_calcs = CommissionCalculation.objects.filter(campaign=campaign)
        total_commission_earned = comm_calcs.aggregate(t=Sum('calculated_commission'))['t'] or Decimal('0.00')

        # Total payouts recorded
        payouts_qs = CommissionPayout.objects.filter(campaign=campaign)
        total_commission_paid = payouts_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        outstanding_commission = total_commission_earned - total_commission_paid

        # Net Profit Formula: Total collections − Total bus fare − Total food expenses − Total general expenses − Total student commission earned
        net_profit = total_collections - total_bus_fare - total_food_expenses - total_general_expenses - total_commission_earned

        # Break-even indicator
        total_expenses_with_commission = total_trip_expenses + total_general_expenses + total_commission_earned
        break_even_recovered = min(total_collections, total_expenses_with_commission)
        break_even_percentage = (
            (break_even_recovered / total_expenses_with_commission * Decimal('100.00')).quantize(Decimal('0.1'))
            if total_expenses_with_commission > 0 else Decimal('100.0')
        )

        open_trips_count = Trip.objects.filter(campaign=campaign, status='in_progress').count()
        settled_trips_count = settled_trips.count()
        review_trips_count = Trip.objects.filter(campaign=campaign, review_status='needs_review').count()

        return {
            'campaign_id': campaign.id,
            'campaign_year': campaign.year,
            'campaign_status': campaign.status,
            'total_collections': total_collections,
            'cash_collections': cash_coll,
            'gpay_collections': gpay_coll,
            'total_trip_expenses': total_trip_expenses,
            'bus_fare': total_bus_fare,
            'food_expense': total_food_expenses,
            'general_expenses': total_general_expenses,
            'printing_expense': printing_expense,
            'total_commission_earned': total_commission_earned,
            'total_commission_paid': total_commission_paid,
            'outstanding_commission': outstanding_commission,
            'net_profit': net_profit,
            'is_provisional': open_trips_count > 0 or campaign.status == 'active',
            'break_even_target': total_expenses_with_commission,
            'break_even_recovered': break_even_recovered,
            'break_even_percentage': float(break_even_percentage),
            'open_trips_count': open_trips_count,
            'settled_trips_count': settled_trips_count,
            'review_trips_count': review_trips_count,
        }

    @staticmethod
    def finalize_campaign_commission(campaign: Campaign, user: User | None):
        """
        Freeze commission calculations when closing the campaign.
        Requires all trips to be settled.
        """
        open_trips = Trip.objects.filter(campaign=campaign, status='in_progress')
        if open_trips.exists():
            raise ValidationError(f"Cannot finalize commission: {open_trips.count()} trips are still open.")

        with transaction.atomic():
            participating_students = Student.objects.filter(
                trip_participations__trip__campaign=campaign,
                trip_participations__trip__status='settled'
            ).distinct()

            for student in participating_students:
                calc = FinancialService.recalculate_student_commission(campaign, student)
                calc.finalization_status = 'finalized'
                calc.save()

            # Ensure all commission calculation records for this campaign are marked finalized
            CommissionCalculation.objects.filter(
                campaign=campaign,
                finalization_status='provisional'
            ).update(finalization_status='finalized')

            AuditLog.objects.create(
                user=user,
                action='commission_finalize',
                entity_type='Campaign',
                entity_id=str(campaign.id),
                reason=f"Commission finalized for campaign {campaign.year}",
            )

    @staticmethod
    def record_payout(
        campaign: Campaign,
        student: Student,
        amount: Decimal,
        payment_date,
        payment_method: str,
        reference: str,
        notes: str,
        user: User | None
    ) -> CommissionPayout:
        """
        Record a final commission payout to a student.
        Prevents payouts greater than outstanding commission or duplicate payouts.
        """
        if amount <= Decimal('0.00'):
            raise ValidationError("Payout amount must be greater than zero.")

        with transaction.atomic():
            # Get finalized or current commission
            calc = FinancialService.recalculate_student_commission(campaign, student)
            total_paid = CommissionPayout.objects.filter(
                campaign=campaign,
                student=student
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

            remaining = calc.calculated_commission - total_paid

            if amount > remaining:
                raise ValidationError(
                    f"Payout amount ₹{amount} exceeds remaining payable commission ₹{remaining} for {student.name}."
                )

            payout = CommissionPayout.objects.create(
                campaign=campaign,
                student=student,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                reference=reference,
                notes=notes,
                created_by=user,
            )

            AuditLog.objects.create(
                user=user,
                action='commission_payout',
                entity_type='CommissionPayout',
                entity_id=str(payout.id),
                after_snapshot={
                    'student': student.name,
                    'amount': str(amount),
                    'payment_method': payment_method,
                    'reference': reference,
                },
                reason=f"Payout recorded: ₹{amount} to {student.name}",
            )

            return payout

    @staticmethod
    def close_campaign(campaign: Campaign, user: User | None) -> Campaign:
        """
        Close a campaign. Freezes commission, validates no open trips, and sets status to closed.
        """
        with transaction.atomic():
            campaign = Campaign.objects.select_for_update().get(id=campaign.id)
            if campaign.status == 'closed':
                return campaign

            open_trips = Trip.objects.filter(campaign=campaign, status='in_progress')
            if open_trips.exists():
                raise ValidationError(f"Cannot close campaign: {open_trips.count()} trips are still open.")

            FinancialService.finalize_campaign_commission(campaign, user)

            campaign.status = 'closed'
            campaign.closed_at = timezone.now()
            campaign.save()

            AuditLog.objects.create(
                user=user,
                action='campaign_close',
                entity_type='Campaign',
                entity_id=str(campaign.id),
                reason=f"Campaign {campaign.year} closed.",
            )

            return campaign

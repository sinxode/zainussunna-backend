from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Sum, Q, F
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import (
    Campaign, Student, Place, ReceiptBook, Trip, TripStudent, TripReceiptBook,
    InventoryMovement, Expense, CommissionCalculation, CommissionPayout,
    AuditLog, User, ExternalCollection, split_amount_in_paise
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

        # Calendars given via external collections
        external_calendars = ExternalCollection.objects.filter(
            campaign=campaign
        ).aggregate(total=Sum('calendars_given'))['total'] or 0

        printed = campaign.printed_quantity
        available = printed - sold - in_field - external_calendars + adjustments

        return {
            'printed_quantity': printed,
            'calendars_sold': sold,
            'calendars_in_field': in_field,
            'calendars_returned': returned,
            'calendars_external': external_calendars,
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
        highest_leaf_trip = Trip.objects.filter(
            receipt_book=receipt_book
        ).exclude(status='voided').order_by('-receipt_ending_leaf').first()

        highest_from_trip = highest_leaf_trip.receipt_ending_leaf if (highest_leaf_trip and highest_leaf_trip.receipt_ending_leaf) else 0

        highest_trb = TripReceiptBook.objects.filter(
            receipt_book=receipt_book
        ).exclude(trip__status='voided').order_by('-ending_leaf').first()

        highest_from_trb = highest_trb.ending_leaf if (highest_trb and highest_trb.ending_leaf) else 0

        max_ending = max(highest_from_trip, highest_from_trb)
        if max_ending > 0:
            next_leaf = max_ending + 1
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

        # Check for overlap with existing non-voided trips in the same receipt book (via direct trip assignment)
        conflicts = Trip.objects.filter(
            receipt_book=receipt_book,
            receipt_starting_leaf__isnull=False,
            receipt_ending_leaf__isnull=False,
        ).exclude(status='voided')

        if exclude_trip_id:
            conflicts = conflicts.exclude(id=exclude_trip_id)

        for trip in conflicts:
            if not (end_leaf < trip.receipt_starting_leaf or start_leaf > trip.receipt_ending_leaf):
                raise ValidationError(
                    f"Receipt leaf range {start_leaf}-{end_leaf} in {receipt_book.label} overlaps with Trip #{trip.id} ({trip.receipt_starting_leaf}-{trip.receipt_ending_leaf})."
                )

        # Check for overlap with TripReceiptBook assignments
        trb_conflicts = TripReceiptBook.objects.filter(
            receipt_book=receipt_book,
            starting_leaf__isnull=False,
            ending_leaf__isnull=False,
        ).exclude(trip__status='voided')

        if exclude_trip_id:
            trb_conflicts = trb_conflicts.exclude(trip_id=exclude_trip_id)

        for trb in trb_conflicts:
            if not (end_leaf < trb.starting_leaf or start_leaf > trb.ending_leaf):
                raise ValidationError(
                    f"Receipt leaf range {start_leaf}-{end_leaf} in {receipt_book.label} overlaps with Trip #{trb.trip_id} ({trb.starting_leaf}-{trb.ending_leaf})."
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
        user: User | None,
        receipt_books: list[dict] | None = None
    ) -> Trip:
        """
        Atomic dispatch of a group of 1 to 3 students.
        Ensures stock availability and prevents double-assignment of students.
        Supports multiple receipt books per trip.
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

        # Consolidate receipt books list
        rb_list = []
        if receipt_books:
            rb_list = list(receipt_books)
        elif receipt_book:
            rb_list = [{'receipt_book': receipt_book, 'starting_leaf': receipt_starting_leaf}]

        # Validate starting leaves
        for rb_item in rb_list:
            bk = rb_item.get('receipt_book')
            st_leaf = rb_item.get('starting_leaf')
            if bk and st_leaf is not None:
                if st_leaf < bk.first_leaf or st_leaf > bk.last_leaf:
                    raise ValidationError(
                        f"Receipt leaf {st_leaf} is outside book range {bk.first_leaf}-{bk.last_leaf} for {bk.label}."
                    )

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

            # Primary receipt book for backward compatibility
            primary_book = rb_list[0]['receipt_book'] if rb_list else receipt_book
            primary_starting_leaf = rb_list[0].get('starting_leaf') if rb_list else receipt_starting_leaf

            trip = Trip.objects.create(
                campaign=campaign,
                place=place,
                trip_date=trip_date,
                departure_time=departure_time,
                calendars_issued=calendars_issued,
                bus_fare=bus_fare,
                receipt_book=primary_book,
                receipt_starting_leaf=primary_starting_leaf,
                discrepancy_notes=notes,
                created_by=user,
                status='in_progress',
            )

            # Save all TripReceiptBook records
            for rb_item in rb_list:
                TripReceiptBook.objects.create(
                    trip=trip,
                    receipt_book=rb_item['receipt_book'],
                    starting_leaf=rb_item.get('starting_leaf')
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
        user: User | None,
        receipt_books: list[dict] | None = None
    ) -> Trip:
        """
        Settle a returned trip atomically.
        Calculates exact shares, checks discrepancies, updates inventory, and recalculates commissions.
        Supports multiple receipt books per trip.
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

            # Consolidate receipt books list
            rb_list = []
            if receipt_books:
                rb_list = list(receipt_books)
            elif receipt_book:
                rb_list = [{
                    'receipt_book': receipt_book,
                    'starting_leaf': receipt_starting_leaf,
                    'ending_leaf': receipt_ending_leaf,
                    'voided_leaves': voided_leaves,
                }]

            # Validate receipt ranges for all books
            for rb_item in rb_list:
                bk = rb_item.get('receipt_book')
                st_leaf = rb_item.get('starting_leaf')
                end_leaf = rb_item.get('ending_leaf')
                if bk and st_leaf is not None and end_leaf is not None:
                    ReceiptBookService.validate_leaf_range(
                        bk, st_leaf, end_leaf, exclude_trip_id=trip.id
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

            if rb_list:
                primary = rb_list[0]
                trip.receipt_book = primary['receipt_book']
                trip.receipt_starting_leaf = primary.get('starting_leaf')
                trip.receipt_ending_leaf = primary.get('ending_leaf')
                trip.voided_leaves = primary.get('voided_leaves', '')
            else:
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

            # Sync TripReceiptBook records
            if rb_list:
                TripReceiptBook.objects.filter(trip=trip).delete()
                for rb_item in rb_list:
                    TripReceiptBook.objects.create(
                        trip=trip,
                        receipt_book=rb_item['receipt_book'],
                        starting_leaf=rb_item.get('starting_leaf'),
                        ending_leaf=rb_item.get('ending_leaf'),
                        voided_leaves=rb_item.get('voided_leaves', ''),
                    )

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

    @staticmethod
    def delete_trip(trip: Trip, user: User | None, reason: str = '') -> None:
        """
        Permanently delete a trip with full financial integrity:
        - Prevents deletion if campaign is closed.
        - Prevents deletion of settled trips if student commission has already been finalized.
        - Prevents deletion of settled trips if disbursed payouts exceed revised commissions.
        - Reverses inventory deductions and restores available stock.
        - Removes trip participation shares.
        - Recalculates commissions for affected students if trip was settled.
        - Deletes associated expenses and inventory movements.
        - Records an immutable audit log snapshot with reason.
        """
        with transaction.atomic():
            trip = Trip.objects.select_for_update().get(id=trip.id)
            if trip.campaign.status == 'closed':
                raise ValidationError("Cannot delete trips belonging to a closed campaign.")

            trip_id = trip.id
            campaign = trip.campaign
            status_val = trip.status
            students = [ts.student for ts in trip.trip_students.select_related('student').all()]

            if status_val == 'settled':
                # Check 1: Finalized commissions
                if CommissionCalculation.objects.filter(
                    campaign=campaign, student__in=students, finalization_status='finalized'
                ).exists():
                    raise ValidationError(
                        f"Cannot delete settled Trip #{trip_id}: Student commission has already been finalized for this campaign. Reopen or adjust commissions before deleting this trip."
                    )

                # Check 2: Outstanding payouts vs recalculated commission
                for student in students:
                    total_paid = CommissionPayout.objects.filter(
                        campaign=campaign, student=student
                    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

                    if total_paid > Decimal('0.00'):
                        # Calculate projected commission without this trip
                        remaining_participations = TripStudent.objects.filter(
                            trip__campaign=campaign,
                            trip__status='settled',
                            student=student
                        ).exclude(trip=trip)

                        rem_gross = remaining_participations.aggregate(t=Sum('gross_collection_share'))['t'] or Decimal('0.00')
                        rem_fare = remaining_participations.aggregate(t=Sum('bus_fare_share'))['t'] or Decimal('0.00')
                        rem_food = remaining_participations.aggregate(t=Sum('food_expense_share'))['t'] or Decimal('0.00')
                        rem_net = rem_gross - rem_fare - rem_food

                        if rem_net > Decimal('0.00'):
                            projected_comm = ((rem_net * campaign.commission_percentage) / Decimal('100.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        else:
                            projected_comm = Decimal('0.00')

                        if total_paid > projected_comm:
                            raise ValidationError(
                                f"Cannot delete settled Trip #{trip_id}: Student {student.name} has already received payout(s) totaling ₹{total_paid}, which would exceed their revised earned commission of ₹{projected_comm}. Delete or adjust the payout record first."
                            )

            before_snapshot = {
                'id': trip_id,
                'campaign_id': campaign.id,
                'campaign_year': campaign.year,
                'place': trip.place.name if trip.place else None,
                'status': status_val,
                'trip_date': str(trip.trip_date),
                'calendars_issued': trip.calendars_issued,
                'calendars_sold': trip.calendars_sold,
                'calendars_returned': trip.calendars_returned,
                'cash_collection': str(trip.cash_collection),
                'gpay_collection': str(trip.gpay_collection),
                'bus_fare': str(trip.bus_fare),
                'food_expense': str(trip.food_expense),
                'receipt_book': trip.receipt_book.label if trip.receipt_book else None,
                'receipt_starting_leaf': trip.receipt_starting_leaf,
                'receipt_ending_leaf': trip.receipt_ending_leaf,
                'students': [s.name for s in students],
                'deletion_reason': reason.strip() if reason else None,
            }

            # Delete related inventory movements
            InventoryMovement.objects.filter(related_trip=trip).delete()

            # Delete related expenses (if any logged against this trip)
            Expense.objects.filter(related_trip=trip).delete()

            # Record audit log before deleting
            clean_reason = reason.strip() if reason else f"Permanently deleted Trip #{trip_id} to {trip.place.name if trip.place else 'Unknown'}"
            AuditLog.objects.create(
                user=user,
                action='trip_delete',
                entity_type='Trip',
                entity_id=str(trip_id),
                before_snapshot=before_snapshot,
                reason=clean_reason,
            )

            # Delete the trip (cascades TripStudent)
            trip.delete()

            # If the trip was settled, recalculate commissions for participating students
            if status_val == 'settled':
                for student in students:
                    FinancialService.recalculate_student_commission(campaign, student)

    @staticmethod
    def update_trip(trip: Trip, data: dict, user: User | None) -> Trip:
        """
        Atomically update an in-progress or settled trip with complete financial,
        inventory, and commission recalculations.
        """
        with transaction.atomic():
            trip = Trip.objects.select_for_update().get(id=trip.id)
            campaign = trip.campaign

            if campaign.status == 'closed':
                raise ValidationError("Cannot edit trips belonging to a closed campaign.")

            if trip.status == 'voided':
                raise ValidationError("Cannot edit a voided trip.")

            before_snapshot = {
                'id': trip.id,
                'status': trip.status,
                'place': trip.place.name if trip.place else None,
                'trip_date': str(trip.trip_date),
                'calendars_issued': trip.calendars_issued,
                'calendars_sold': trip.calendars_sold,
                'calendars_returned': trip.calendars_returned,
                'bus_fare': str(trip.bus_fare),
                'food_expense': str(trip.food_expense),
                'cash_collection': str(trip.cash_collection),
                'gpay_collection': str(trip.gpay_collection),
                'students': [s.name for s in Student.objects.filter(trip_participations__trip=trip)],
            }

            # Common Dispatch Fields
            if 'place' in data and data['place']:
                trip.place = data['place']
            if 'trip_date' in data and data['trip_date']:
                trip.trip_date = data['trip_date']
            if 'departure_time' in data:
                trip.departure_time = data['departure_time']
            if 'bus_fare' in data and data['bus_fare'] is not None:
                if data['bus_fare'] < Decimal('0.00'):
                    raise ValidationError("Bus fare cannot be negative.")
                trip.bus_fare = data['bus_fare']
            if 'notes' in data and data['notes'] is not None:
                trip.discrepancy_notes = data['notes']

            # Receipt Books Handling (Multiple and Legacy)
            if 'receipt_books' in data:
                rb_list = data['receipt_books']
                for rb_item in rb_list:
                    bk = rb_item.get('receipt_book')
                    st_leaf = rb_item.get('starting_leaf')
                    end_leaf = rb_item.get('ending_leaf')
                    if bk and st_leaf is not None:
                        if st_leaf < bk.first_leaf or st_leaf > bk.last_leaf:
                            raise ValidationError(
                                f"Receipt leaf {st_leaf} is outside book range {bk.first_leaf}-{bk.last_leaf} for {bk.label}."
                            )
                    if bk and st_leaf is not None and end_leaf is not None:
                        ReceiptBookService.validate_leaf_range(
                            bk, st_leaf, end_leaf, exclude_trip_id=trip.id
                        )

                TripReceiptBook.objects.filter(trip=trip).delete()
                for rb_item in rb_list:
                    TripReceiptBook.objects.create(
                        trip=trip,
                        receipt_book=rb_item['receipt_book'],
                        starting_leaf=rb_item.get('starting_leaf'),
                        ending_leaf=rb_item.get('ending_leaf'),
                        voided_leaves=rb_item.get('voided_leaves', ''),
                    )

                if rb_list:
                    primary = rb_list[0]
                    trip.receipt_book = primary['receipt_book']
                    trip.receipt_starting_leaf = primary.get('starting_leaf')
                    if 'ending_leaf' in primary:
                        trip.receipt_ending_leaf = primary.get('ending_leaf')
                    if 'voided_leaves' in primary:
                        trip.voided_leaves = primary.get('voided_leaves', '')
                else:
                    trip.receipt_book = None
                    trip.receipt_starting_leaf = None
                    trip.receipt_ending_leaf = None
                    trip.voided_leaves = ''
            else:
                # Receipt Book & Starting Leaf (Legacy fallback)
                if 'receipt_book' in data:
                    trip.receipt_book = data['receipt_book']
                if 'receipt_starting_leaf' in data:
                    trip.receipt_starting_leaf = data['receipt_starting_leaf']

                if trip.receipt_book and trip.receipt_starting_leaf:
                    if (trip.receipt_starting_leaf < trip.receipt_book.first_leaf or
                        trip.receipt_starting_leaf > trip.receipt_book.last_leaf):
                        raise ValidationError(
                            f"Receipt starting leaf {trip.receipt_starting_leaf} is outside book range {trip.receipt_book.first_leaf}-{trip.receipt_book.last_leaf}."
                        )
                # Keep TripReceiptBook in sync with legacy fields
                if 'receipt_book' in data or 'receipt_starting_leaf' in data:
                    if trip.receipt_book:
                        trb = TripReceiptBook.objects.filter(trip=trip).first()
                        if trb:
                            trb.receipt_book = trip.receipt_book
                            trb.starting_leaf = trip.receipt_starting_leaf
                            trb.save()
                        else:
                            TripReceiptBook.objects.create(
                                trip=trip,
                                receipt_book=trip.receipt_book,
                                starting_leaf=trip.receipt_starting_leaf
                            )

            # Calendars Issued
            if 'calendars_issued' in data and data['calendars_issued'] is not None:
                new_issued = data['calendars_issued']
                if new_issued <= 0:
                    raise ValidationError("Issued calendar quantity must be greater than zero.")
                if new_issued != trip.calendars_issued:
                    diff_issued = new_issued - trip.calendars_issued
                    # Check stock if increasing issued calendars
                    if diff_issued > 0:
                        summary = InventoryService.get_campaign_inventory_summary(campaign)
                        if diff_issued > summary['available_stock']:
                            raise ValidationError(
                                f"Insufficient stock: requesting {diff_issued} additional calendars, but only {summary['available_stock']} are available."
                            )
                    trip.calendars_issued = new_issued

                    # Update or create the trip_issue movement
                    issue_mov = InventoryMovement.objects.filter(related_trip=trip, movement_type='trip_issue').first()
                    if issue_mov:
                        issue_mov.quantity = -new_issued
                        issue_mov.reason = f"Issued for Trip #{trip.id} to {trip.place.name if trip.place else 'destination'} (Updated)"
                        issue_mov.save()
                    else:
                        InventoryMovement.objects.create(
                            campaign=campaign,
                            movement_type='trip_issue',
                            quantity=-new_issued,
                            related_trip=trip,
                            reason=f"Issued for Trip #{trip.id} to {trip.place.name if trip.place else 'destination'}",
                            created_by=user,
                        )

            # Student Assignment Handling
            current_students = list(Student.objects.filter(trip_participations__trip=trip))
            all_affected_students = set(current_students)

            if 'student_ids' in data and data['student_ids'] is not None:
                student_ids = data['student_ids']
                if not (1 <= len(student_ids) <= 3):
                    raise ValidationError("A trip must have between 1 and 3 students.")
                if len(set(student_ids)) != len(student_ids):
                    raise ValidationError("Duplicate students cannot be assigned to the same trip.")
                new_students = list(Student.objects.filter(id__in=student_ids, is_active=True))
                if len(new_students) != len(student_ids):
                    raise ValidationError("One or more selected students are invalid or inactive.")

                # If in_progress, ensure no student is already on another active trip
                if trip.status == 'in_progress':
                    open_conflicts = Trip.objects.filter(
                        campaign=campaign,
                        status='in_progress',
                        trip_students__student__in=new_students
                    ).exclude(id=trip.id).distinct()
                    if open_conflicts.exists():
                        conflict_trip = open_conflicts.first()
                        conflicting = Student.objects.filter(
                            trip_participations__trip=conflict_trip,
                            id__in=student_ids
                        ).values_list('name', flat=True)
                        raise ValidationError(
                            f"Student(s) {', '.join(conflicting)} already assigned to active Trip #{conflict_trip.id}."
                        )

                # Recreate student assignments
                all_affected_students.update(new_students)
                TripStudent.objects.filter(trip=trip).delete()
                for st in new_students:
                    TripStudent.objects.create(trip=trip, student=st)
                current_students = new_students

            # -------------------------------------------------------------
            # Status Specific Logic: IN_PROGRESS
            # -------------------------------------------------------------
            if trip.status == 'in_progress':
                trip.save()

            # -------------------------------------------------------------
            # Status Specific Logic: SETTLED
            # -------------------------------------------------------------
            elif trip.status == 'settled':
                # Finalized commission check
                if CommissionCalculation.objects.filter(
                    campaign=campaign, student__in=all_affected_students, finalization_status='finalized'
                ).exists():
                    raise ValidationError(
                        "Cannot edit settled trip: Student commission has already been finalized for this campaign."
                    )

                # Update settlement fields if passed
                if 'return_time' in data:
                    trip.return_time = data['return_time']
                if 'calendars_sold' in data and data['calendars_sold'] is not None:
                    if data['calendars_sold'] < 0:
                        raise ValidationError("Sold quantity cannot be negative.")
                    trip.calendars_sold = data['calendars_sold']
                if 'calendars_returned' in data and data['calendars_returned'] is not None:
                    if data['calendars_returned'] < 0:
                        raise ValidationError("Returned quantity cannot be negative.")
                    trip.calendars_returned = data['calendars_returned']
                if 'cash_collection' in data and data['cash_collection'] is not None:
                    if data['cash_collection'] < Decimal('0.00'):
                        raise ValidationError("Cash collection cannot be negative.")
                    trip.cash_collection = data['cash_collection']
                if 'gpay_collection' in data and data['gpay_collection'] is not None:
                    if data['gpay_collection'] < Decimal('0.00'):
                        raise ValidationError("GPay collection cannot be negative.")
                    trip.gpay_collection = data['gpay_collection']
                if 'food_expense' in data and data['food_expense'] is not None:
                    if data['food_expense'] < Decimal('0.00'):
                        raise ValidationError("Food expense cannot be negative.")
                    trip.food_expense = data['food_expense']
                if 'receipt_ending_leaf' in data:
                    trip.receipt_ending_leaf = data['receipt_ending_leaf']
                if 'voided_leaves' in data and data['voided_leaves'] is not None:
                    trip.voided_leaves = data['voided_leaves']
                if 'discrepancy_notes' in data and data['discrepancy_notes'] is not None:
                    trip.discrepancy_notes = data['discrepancy_notes']

                # Validate receipt range if ending leaf provided
                if trip.receipt_book and trip.receipt_starting_leaf and trip.receipt_ending_leaf:
                    ReceiptBookService.validate_leaf_range(
                        trip.receipt_book, trip.receipt_starting_leaf, trip.receipt_ending_leaf, exclude_trip_id=trip.id
                    )

                # Discrepancy checks & review status
                total_col = trip.cash_collection + trip.gpay_collection
                expected_min = Decimal(trip.calendars_sold) * campaign.min_expected_collection_per_calendar
                shortfall = expected_min - total_col
                stock_disc = trip.calendars_issued - (trip.calendars_sold + trip.calendars_returned)

                needs_rev = False
                reasons = []
                if shortfall > 0:
                    needs_rev = True
                    reasons.append(f"Collection shortfall of ₹{shortfall:.2f} below expected ₹{expected_min:.2f}")
                if stock_disc != 0:
                    needs_rev = True
                    reasons.append(f"Stock discrepancy: issued {trip.calendars_issued}, but sold ({trip.calendars_sold}) + returned ({trip.calendars_returned}) = {trip.calendars_sold + trip.calendars_returned}")
                if total_col < (trip.bus_fare + trip.food_expense):
                    needs_rev = True
                    reasons.append(f"Negative trip net: collection ₹{total_col:.2f} is less than expenses ₹{(trip.bus_fare + trip.food_expense):.2f}")

                if needs_rev and not trip.discrepancy_notes.strip():
                    raise ValidationError(f"Warning: {'; '.join(reasons)}. An explanatory note is required to save these changes.")

                trip.review_status = 'needs_review' if needs_rev else 'no_review_needed'
                trip.save()

                # Update Inventory Movements for sold and returned
                sold_mov = InventoryMovement.objects.filter(related_trip=trip, movement_type='trip_sold').first()
                if trip.calendars_sold > 0:
                    if sold_mov:
                        sold_mov.quantity = -trip.calendars_sold
                        sold_mov.save()
                    else:
                        InventoryMovement.objects.create(
                            campaign=campaign,
                            movement_type='trip_sold',
                            quantity=-trip.calendars_sold,
                            related_trip=trip,
                            reason=f"Settled sales from Trip #{trip.id}",
                            created_by=user,
                        )
                elif sold_mov:
                    sold_mov.delete()

                ret_mov = InventoryMovement.objects.filter(related_trip=trip, movement_type='trip_return_unsold').first()
                if trip.calendars_returned > 0:
                    if ret_mov:
                        ret_mov.quantity = trip.calendars_returned
                        ret_mov.save()
                    else:
                        InventoryMovement.objects.create(
                            campaign=campaign,
                            movement_type='trip_return_unsold',
                            quantity=trip.calendars_returned,
                            related_trip=trip,
                            reason=f"Returned unsold from Trip #{trip.id}",
                            created_by=user,
                        )
                elif ret_mov:
                    ret_mov.delete()

                # Re-allocate trip shares among current students
                participations = list(trip.trip_students.select_related('student').order_by('id'))
                count = len(participations)
                if count > 0:
                    col_shares = split_amount_in_paise(total_col, count)
                    fare_shares = split_amount_in_paise(trip.bus_fare, count)
                    food_shares = split_amount_in_paise(trip.food_expense, count)

                    for idx, part in enumerate(participations):
                        part.gross_collection_share = col_shares[idx]
                        part.bus_fare_share = fare_shares[idx]
                        part.food_expense_share = food_shares[idx]
                        part.net_collection_share = col_shares[idx] - fare_shares[idx] - food_shares[idx]
                        part.save()

                # Recalculate commissions for all affected students
                for st in all_affected_students:
                    FinancialService.recalculate_student_commission(campaign, st)

                # Verify payout boundaries
                for st in all_affected_students:
                    total_paid = CommissionPayout.objects.filter(
                        campaign=campaign, student=st
                    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
                    calc = CommissionCalculation.objects.filter(campaign=campaign, student=st).first()
                    if calc and calc.calculated_commission < total_paid:
                        raise ValidationError(
                            f"Cannot save changes: Student {st.name} was already paid ₹{total_paid}, but revised commission would be ₹{calc.calculated_commission}."
                        )

            # Audit log
            after_snapshot = {
                'id': trip.id,
                'status': trip.status,
                'place': trip.place.name if trip.place else None,
                'trip_date': str(trip.trip_date),
                'calendars_issued': trip.calendars_issued,
                'calendars_sold': trip.calendars_sold,
                'calendars_returned': trip.calendars_returned,
                'bus_fare': str(trip.bus_fare),
                'food_expense': str(trip.food_expense),
                'cash_collection': str(trip.cash_collection),
                'gpay_collection': str(trip.gpay_collection),
                'students': [s.name for s in Student.objects.filter(trip_participations__trip=trip)],
            }

            AuditLog.objects.create(
                user=user,
                action='trip_edit',
                entity_type='Trip',
                entity_id=str(trip.id),
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                reason=f"Trip #{trip.id} ({trip.status}) updated by {user.display_name if user else 'Admin'}",
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

        # External collections (direct contributions outside student trips)
        external_collections = ExternalCollection.objects.filter(
            campaign=campaign
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        # Total revenue / total received across all sources
        total_received = total_collections + external_collections

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

        # Net Profit Formula: Total received (student collections + external collections) − Total bus fare − Total food expenses − Total general expenses − Total student commission earned
        net_profit = total_received - total_bus_fare - total_food_expenses - total_general_expenses - total_commission_earned

        # Break-even indicator
        total_expenses_with_commission = total_trip_expenses + total_general_expenses + total_commission_earned
        break_even_recovered = min(total_received, total_expenses_with_commission)
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
            'student_collections': total_collections,
            'external_collections': external_collections,
            'total_received': total_received,
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

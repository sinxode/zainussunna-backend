from decimal import Decimal
from django.db import models
from django.db.models import Sum
from rest_framework import serializers
from .models import (
    User, Campaign, Student, Place, ReceiptBook,
    Trip, TripStudent, InventoryMovement, Expense,
    CommissionCalculation, CommissionPayout, AuditLog,
    ExternalCollection, normalize_phone_number
)
from .services import InventoryService, FinancialService, ReceiptBookService


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'phone_number', 'display_name', 'role',
            'is_active', 'must_change_password', 'created_at', 'last_login'
        ]
        read_only_fields = ['id', 'created_at', 'last_login']


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['id', 'phone_number', 'display_name', 'role', 'password']

    def validate_phone_number(self, value):
        return normalize_phone_number(value)

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=6)


class CampaignSerializer(serializers.ModelSerializer):
    proposed_printing_expense = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'year', 'printed_quantity',
            'cost_price_per_calendar', 'min_expected_collection_per_calendar',
            'commission_percentage', 'status', 'created_by',
            'created_at', 'closed_at', 'proposed_printing_expense'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'closed_at', 'proposed_printing_expense']

    def validate_printed_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Printed quantity must be greater than zero.")
        if self.instance:
            inv = InventoryService.get_campaign_inventory_summary(self.instance)
            committed = inv['calendars_sold'] + inv['calendars_in_field']
            if value < committed:
                raise serializers.ValidationError(
                    f"Printed quantity ({value}) cannot be lower than calendars already committed ({committed}: {inv['calendars_sold']} sold + {inv['calendars_in_field']} in field)."
                )
        return value

    def validate_cost_price_per_calendar(self, value):
        if value < Decimal('0.00'):
            raise serializers.ValidationError("Cost price per calendar cannot be negative.")
        return value

    def validate_min_expected_collection_per_calendar(self, value):
        if value < Decimal('0.00'):
            raise serializers.ValidationError("Minimum expected collection price cannot be negative.")
        return value

    def validate_commission_percentage(self, value):
        if value < Decimal('0.00') or value > Decimal('100.00'):
            raise serializers.ValidationError("Commission percentage must be between 0% and 100%.")
        return value

    def validate(self, attrs):
        if self.instance and self.instance.status == 'closed':
            if 'commission_percentage' in attrs and attrs['commission_percentage'] != self.instance.commission_percentage:
                raise serializers.ValidationError({
                    'commission_percentage': "Commission rate cannot be modified on a closed campaign with finalized commission calculations."
                })

        if attrs.get('status') == 'closed' and (not self.instance or self.instance.status != 'closed'):
            if self.instance:
                open_trips = Trip.objects.filter(campaign=self.instance, status='in_progress')
                if open_trips.exists():
                    raise serializers.ValidationError({
                        'status': f"Cannot close campaign: {open_trips.count()} trip(s) are still in progress. Settle or void all open trips first."
                    })
        return attrs


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = ['id', 'name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = ['id', 'name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ReceiptBookSerializer(serializers.ModelSerializer):
    total_leaves = serializers.SerializerMethodField()
    next_suggested_leaf = serializers.SerializerMethodField()
    used_leaves_count = serializers.SerializerMethodField()
    remaining_leaves_count = serializers.SerializerMethodField()

    class Meta:
        model = ReceiptBook
        fields = [
            'id', 'campaign', 'label', 'first_leaf', 'last_leaf',
            'status', 'notes', 'created_at', 'total_leaves',
            'next_suggested_leaf', 'used_leaves_count', 'remaining_leaves_count'
        ]
        read_only_fields = ['id', 'created_at']

    def get_total_leaves(self, obj) -> int:
        return (obj.last_leaf - obj.first_leaf + 1) if obj.last_leaf >= obj.first_leaf else 0

    def get_next_suggested_leaf(self, obj) -> int:
        return ReceiptBookService.get_next_suggested_leaf(obj)

    def get_used_leaves_count(self, obj) -> int:
        trips = Trip.objects.filter(receipt_book=obj).exclude(status='voided')
        used = 0
        for t in trips:
            if t.receipt_starting_leaf and t.receipt_ending_leaf:
                used += (t.receipt_ending_leaf - t.receipt_starting_leaf + 1)
        return used

    def get_remaining_leaves_count(self, obj) -> int:
        total = self.get_total_leaves(obj)
        used = self.get_used_leaves_count(obj)
        return max(0, total - used)


class TripStudentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)

    class Meta:
        model = TripStudent
        fields = [
            'id', 'student', 'student_name',
            'gross_collection_share', 'bus_fare_share',
            'food_expense_share', 'net_collection_share'
        ]


class TripSerializer(serializers.ModelSerializer):
    place_name = serializers.CharField(source='place.name', read_only=True)
    receipt_book_label = serializers.CharField(source='receipt_book.label', read_only=True)
    trip_students = TripStudentSerializer(many=True, read_only=True)
    total_collection = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    expected_minimum_collection = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    stock_discrepancy = serializers.IntegerField(read_only=True)
    collection_shortfall = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)
    settled_by_name = serializers.CharField(source='settled_by.display_name', read_only=True)

    class Meta:
        model = Trip
        fields = [
            'id', 'campaign', 'place', 'place_name', 'trip_date',
            'departure_time', 'return_time', 'status', 'review_status',
            'calendars_issued', 'calendars_sold', 'calendars_returned',
            'bus_fare', 'food_expense', 'cash_collection', 'gpay_collection',
            'total_collection', 'expected_minimum_collection', 'stock_discrepancy',
            'collection_shortfall', 'receipt_book', 'receipt_book_label',
            'receipt_starting_leaf', 'receipt_ending_leaf', 'voided_leaves',
            'discrepancy_notes', 'created_by', 'created_by_name',
            'settled_by', 'settled_by_name', 'created_at', 'settled_at', 'trip_students'
        ]
        read_only_fields = [
            'id', 'created_by', 'settled_by', 'created_at',
            'settled_at', 'total_collection', 'expected_minimum_collection',
            'stock_discrepancy', 'collection_shortfall'
        ]


class TripDispatchSerializer(serializers.Serializer):
    campaign = serializers.PrimaryKeyRelatedField(queryset=Campaign.objects.all())
    place = serializers.PrimaryKeyRelatedField(queryset=Place.objects.all())
    trip_date = serializers.DateField()
    departure_time = serializers.TimeField(required=False, allow_null=True)
    student_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=3)
    calendars_issued = serializers.IntegerField(min_value=1)
    receipt_book = serializers.PrimaryKeyRelatedField(queryset=ReceiptBook.objects.all(), required=False, allow_null=True)
    receipt_starting_leaf = serializers.IntegerField(required=False, allow_null=True)
    bus_fare = serializers.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class TripSettleSerializer(serializers.Serializer):
    return_time = serializers.TimeField(required=False, allow_null=True)
    calendars_sold = serializers.IntegerField(min_value=0)
    calendars_returned = serializers.IntegerField(min_value=0)
    cash_collection = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.00'))
    gpay_collection = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.00'))
    food_expense = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.00'), default=Decimal('0.00'))
    receipt_book = serializers.PrimaryKeyRelatedField(queryset=ReceiptBook.objects.all(), required=False, allow_null=True)
    receipt_starting_leaf = serializers.IntegerField(required=False, allow_null=True)
    receipt_ending_leaf = serializers.IntegerField(required=False, allow_null=True)
    voided_leaves = serializers.CharField(required=False, allow_blank=True, default='')
    discrepancy_notes = serializers.CharField(required=False, allow_blank=True, default='')


class TripReviewSerializer(serializers.Serializer):
    review_status = serializers.ChoiceField(choices=['no_review_needed', 'needs_review', 'reviewed_and_accepted'])
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class TripVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3)


class InventoryMovementSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)
    place_name = serializers.CharField(source='related_trip.place.name', read_only=True)

    class Meta:
        model = InventoryMovement
        fields = [
            'id', 'campaign', 'movement_type', 'quantity',
            'related_trip', 'place_name', 'reason', 'created_by',
            'created_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class InventoryAdjustmentSerializer(serializers.Serializer):
    campaign = serializers.PrimaryKeyRelatedField(queryset=Campaign.objects.all())
    quantity = serializers.IntegerField()  # positive to add, negative to reduce
    reason = serializers.CharField(required=True, min_length=3)


class ExpenseSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'campaign', 'category', 'amount', 'date',
            'description', 'notes', 'related_trip', 'is_voided',
            'voided_reason', 'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_voided', 'voided_reason']


class ExpenseVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3)


class CommissionCalculationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)
    total_paid = serializers.SerializerMethodField()
    remaining_payable = serializers.SerializerMethodField()

    class Meta:
        model = CommissionCalculation
        fields = [
            'id', 'campaign', 'student', 'student_name',
            'gross_collection', 'fare_share', 'food_share',
            'net_collection', 'rate', 'calculated_commission',
            'finalization_status', 'calculation_timestamp',
            'total_paid', 'remaining_payable'
        ]

    def get_total_paid(self, obj) -> Decimal:
        return CommissionPayout.objects.filter(
            campaign=obj.campaign,
            student=obj.student
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    def get_remaining_payable(self, obj) -> Decimal:
        paid = self.get_total_paid(obj)
        rem = obj.calculated_commission - paid
        return rem if rem > Decimal('0.00') else Decimal('0.00')


class CommissionPayoutSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)

    class Meta:
        model = CommissionPayout
        fields = [
            'id', 'campaign', 'student', 'student_name',
            'amount', 'payment_date', 'payment_method',
            'reference', 'notes', 'created_by', 'created_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.display_name', read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'user_name', 'action', 'entity_type',
            'entity_id', 'before_snapshot', 'after_snapshot',
            'reason', 'timestamp'
        ]
        read_only_fields = fields


class ExternalCollectionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)
    updated_by_name = serializers.CharField(source='updated_by.display_name', read_only=True)
    campaign_year = serializers.IntegerField(source='campaign.year', read_only=True)
    calendars_given = serializers.IntegerField(min_value=0, default=0)

    class Meta:
        model = ExternalCollection
        fields = [
            'id', 'campaign', 'campaign_year', 'received_from',
            'amount', 'calendars_given', 'date_received', 'notes',
            'created_by', 'created_by_name',
            'updated_by', 'updated_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_by', 'created_by_name',
            'updated_by', 'updated_by_name',
            'created_at', 'updated_at'
        ]

    def validate_amount(self, value):
        if value <= Decimal('0.00'):
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_received_from(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Person name (received from) is required.")
        return val

    def validate(self, attrs):
        campaign = attrs.get('campaign') or (self.instance.campaign if self.instance else None)
        if campaign and campaign.status == 'closed':
            raise serializers.ValidationError("Cannot add or modify external collections in a closed campaign.")

        calendars_given = attrs.get('calendars_given', self.instance.calendars_given if self.instance else 0)
        if campaign and calendars_given > 0:
            inv = InventoryService.get_campaign_inventory_summary(campaign)
            current_allocated = self.instance.calendars_given if self.instance else 0
            additional_needed = calendars_given - current_allocated
            if additional_needed > inv['available_stock']:
                raise serializers.ValidationError({
                    'calendars_given': f"Insufficient stock: requested {calendars_given} calendars ({additional_needed} additional), but only {inv['available_stock']} calendars are available in this campaign."
                })
        return attrs

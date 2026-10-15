import re
from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from django.core.exceptions import ValidationError


def normalize_phone_number(phone: str) -> str:
    """Normalize phone number to 10-digit Indian mobile number."""
    if not phone:
        return ''
    cleaned = re.sub(r'\D', '', str(phone))
    if len(cleaned) == 12 and cleaned.startswith('91'):
        cleaned = cleaned[2:]
    elif len(cleaned) == 11 and cleaned.startswith('0'):
        cleaned = cleaned[1:]
    if len(cleaned) != 10:
        raise ValidationError("Phone number must be a valid 10-digit Indian mobile number.")
    return cleaned


def split_amount_in_paise(total_amount: Decimal, count: int) -> list[Decimal]:
    """
    Deterministically split an amount into `count` shares using whole paise.
    Any remainder paise is distributed to the first students in order.
    Ensures sum(shares) == total_amount exactly.
    """
    if count <= 0:
        return []
    total_paise = int((total_amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
    base_share_paise = total_paise // count
    remainder = total_paise % count

    shares = []
    for i in range(count):
        paise = base_share_paise + (1 if i < remainder else 0)
        shares.append(Decimal(paise) / Decimal(100))
    return shares


class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('The Phone Number must be set')
        phone_number = normalize_phone_number(phone_number)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'admin')
        user = self.model(phone_number=phone_number, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'super_admin')
        return self.create_user(phone_number, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('super_admin', 'Super Administrator'),
        ('admin', 'Administrator'),
    )

    phone_number = models.CharField(max_length=15, unique=True, db_index=True)
    display_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='admin')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=True)
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['display_name']

    def __str__(self):
        return f"{self.display_name} ({self.phone_number}) [{self.role}]"

    @property
    def is_super_admin(self):
        return self.role == 'super_admin' or self.is_superuser


class Campaign(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('closed', 'Closed'),
    )

    name = models.CharField(max_length=100)
    year = models.PositiveIntegerField(unique=True, db_index=True)
    printed_quantity = models.PositiveIntegerField(default=2000)
    cost_price_per_calendar = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('11.00'))
    min_expected_collection_per_calendar = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('20.00'))
    commission_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_campaigns')
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-year']

    def __str__(self):
        return f"{self.name} ({self.year})"

    @property
    def proposed_printing_expense(self) -> Decimal:
        return Decimal(self.printed_quantity) * self.cost_price_per_calendar


class Student(models.Model):
    name = models.CharField(max_length=150, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Place(models.Model):
    name = models.CharField(max_length=150, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ReceiptBook(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('archived', 'Archived'),
    )

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='receipt_books')
    label = models.CharField(max_length=50)
    first_leaf = models.PositiveIntegerField()
    last_leaf = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('campaign', 'label')
        ordering = ['label']

    def __str__(self):
        return f"{self.label} ({self.first_leaf}-{self.last_leaf})"

    def clean(self):
        if self.first_leaf > self.last_leaf:
            raise ValidationError("Starting leaf cannot exceed ending leaf.")


class Trip(models.Model):
    STATUS_CHOICES = (
        ('in_progress', 'Out / In Progress'),
        ('settled', 'Returned / Settled'),
        ('voided', 'Voided'),
    )
    REVIEW_CHOICES = (
        ('no_review_needed', 'No Review Needed'),
        ('needs_review', 'Needs Review'),
        ('reviewed_and_accepted', 'Reviewed and Accepted'),
    )

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name='trips')
    place = models.ForeignKey(Place, on_delete=models.PROTECT, related_name='trips')
    trip_date = models.DateField(default=timezone.now)
    departure_time = models.TimeField(null=True, blank=True)
    return_time = models.TimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress', db_index=True)
    review_status = models.CharField(max_length=30, choices=REVIEW_CHOICES, default='no_review_needed', db_index=True)

    calendars_issued = models.PositiveIntegerField()
    calendars_sold = models.PositiveIntegerField(default=0)
    calendars_returned = models.PositiveIntegerField(default=0)

    bus_fare = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    food_expense = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    cash_collection = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    gpay_collection = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    receipt_book = models.ForeignKey(ReceiptBook, on_delete=models.PROTECT, null=True, blank=True, related_name='trips')
    receipt_starting_leaf = models.PositiveIntegerField(null=True, blank=True)
    receipt_ending_leaf = models.PositiveIntegerField(null=True, blank=True)
    voided_leaves = models.CharField(max_length=255, blank=True, default='')
    discrepancy_notes = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='dispatched_trips')
    settled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='settled_trips')

    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-trip_date', '-created_at']

    def __str__(self):
        return f"Trip #{self.id} to {self.place.name} on {self.trip_date} [{self.status}]"

    @property
    def total_collection(self) -> Decimal:
        return self.cash_collection + self.gpay_collection

    @property
    def expected_minimum_collection(self) -> Decimal:
        return Decimal(self.calendars_sold) * self.campaign.min_expected_collection_per_calendar

    @property
    def collection_shortfall(self) -> Decimal:
        diff = self.expected_minimum_collection - self.total_collection
        return diff if diff > 0 else Decimal('0.00')

    @property
    def stock_discrepancy(self) -> int:
        return self.calendars_issued - (self.calendars_sold + self.calendars_returned)


class TripStudent(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='trip_students')
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='trip_participations')
    gross_collection_share = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    bus_fare_share = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    food_expense_share = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    net_collection_share = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        unique_together = ('trip', 'student')
        ordering = ['student__name']

    def __str__(self):
        return f"{self.student.name} on Trip #{self.trip_id}"


class InventoryMovement(models.Model):
    MOVEMENT_CHOICES = (
        ('opening_stock', 'Opening Stock'),
        ('trip_issue', 'Trip Issue / Dispatch'),
        ('trip_return_unsold', 'Trip Return Unsold'),
        ('trip_sold', 'Trip Sold Reconciled'),
        ('adjustment', 'Approved Adjustment'),
    )

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='inventory_movements')
    movement_type = models.CharField(max_length=30, choices=MOVEMENT_CHOICES)
    quantity = models.IntegerField()  # Negative for deductions, positive for additions
    related_trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_movements')
    reason = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.movement_type}: {self.quantity} for {self.campaign.year}"


class Expense(models.Model):
    CATEGORY_CHOICES = (
        ('printing', 'Printing'),
        ('bus_fare', 'Bus Fare'),
        ('food', 'Food'),
        ('packaging', 'Packaging'),
        ('transport', 'Transport'),
        ('distribution_materials', 'Distribution Materials'),
        ('other', 'Other'),
    )

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='expenses')
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.now)
    description = models.CharField(max_length=255)
    notes = models.TextField(blank=True, default='')
    related_trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, null=True, blank=True, related_name='linked_expenses')
    is_voided = models.BooleanField(default=False)
    voided_reason = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses_updated')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.category}: ₹{self.amount} ({self.date}) {'[VOIDED]' if self.is_voided else ''}"


class CommissionCalculation(models.Model):
    STATUS_CHOICES = (
        ('provisional', 'Provisional'),
        ('finalized', 'Finalized'),
    )

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='commission_calculations')
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='commission_calculations')
    gross_collection = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    fare_share = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    food_share = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    net_collection = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))
    calculated_commission = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    finalization_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='provisional')
    calculation_timestamp = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('campaign', 'student')
        ordering = ['student__name']

    def __str__(self):
        return f"Commission for {self.student.name}: ₹{self.calculated_commission} [{self.finalization_status}]"


class CommissionPayout(models.Model):
    METHOD_CHOICES = (
        ('cash', 'Cash'),
        ('gpay', 'Google Pay / UPI'),
        ('bank_transfer', 'Bank Transfer'),
        ('other', 'Other'),
    )

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='commission_payouts')
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='commission_payouts')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=30, choices=METHOD_CHOICES, default='cash')
    reference = models.CharField(max_length=100, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f"Payout of ₹{self.amount} to {self.student.name} ({self.payment_date})"


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=50, db_index=True)
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_id = models.CharField(max_length=50)
    before_snapshot = models.JSONField(null=True, blank=True)
    after_snapshot = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default='')
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} on {self.entity_type} #{self.entity_id} at {self.timestamp}"

from django.contrib import admin
from .models import (
    User, Campaign, Student, Place, ReceiptBook,
    Trip, TripStudent, TripReceiptBook, InventoryMovement, Expense,
    CommissionCalculation, CommissionPayout, AuditLog, ExternalCollection
)

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'display_name', 'role', 'is_active', 'is_staff')
    search_fields = ('phone_number', 'display_name')
    list_filter = ('role', 'is_active')

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'year', 'printed_quantity', 'status', 'created_at')
    list_filter = ('status', 'year')

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    search_fields = ('name',)

@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    search_fields = ('name',)

@admin.register(ReceiptBook)
class ReceiptBookAdmin(admin.ModelAdmin):
    list_display = ('label', 'campaign', 'first_leaf', 'last_leaf', 'status')
    list_filter = ('campaign', 'status')

@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('id', 'campaign', 'place', 'trip_date', 'status', 'review_status', 'calendars_issued', 'calendars_sold')
    list_filter = ('campaign', 'status', 'review_status', 'trip_date')

@admin.register(TripStudent)
class TripStudentAdmin(admin.ModelAdmin):
    list_display = ('trip', 'student', 'gross_collection_share', 'net_collection_share')

@admin.register(TripReceiptBook)
class TripReceiptBookAdmin(admin.ModelAdmin):
    list_display = ('trip', 'receipt_book', 'starting_leaf', 'ending_leaf')

@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'movement_type', 'quantity', 'created_at')
    list_filter = ('campaign', 'movement_type')

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('category', 'amount', 'campaign', 'date', 'is_voided')
    list_filter = ('campaign', 'category', 'is_voided')

@admin.register(CommissionCalculation)
class CommissionCalculationAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'student', 'net_collection', 'rate', 'calculated_commission', 'finalization_status')
    list_filter = ('campaign', 'finalization_status')

@admin.register(CommissionPayout)
class CommissionPayoutAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'student', 'amount', 'payment_date', 'payment_method')
    list_filter = ('campaign', 'payment_method')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'entity_type', 'entity_id')
    list_filter = ('action', 'entity_type')

@admin.register(ExternalCollection)
class ExternalCollectionAdmin(admin.ModelAdmin):
    list_display = ('received_from', 'amount', 'campaign', 'date_received', 'created_by')
    list_filter = ('campaign', 'date_received')
    search_fields = ('received_from', 'notes')

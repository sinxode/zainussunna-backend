from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q, Count
from rest_framework import viewsets, status, generics, permissions
from rest_framework.views import APIView
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    User, Campaign, Student, Place, ReceiptBook,
    Trip, TripStudent, InventoryMovement, Expense,
    CommissionCalculation, CommissionPayout, AuditLog,
    normalize_phone_number
)
from .serializers import (
    UserSerializer, UserCreateSerializer, ChangePasswordSerializer,
    CampaignSerializer, StudentSerializer, PlaceSerializer,
    ReceiptBookSerializer, TripSerializer, TripDispatchSerializer,
    TripSettleSerializer, TripVoidSerializer, TripReviewSerializer,
    InventoryMovementSerializer, InventoryAdjustmentSerializer,
    ExpenseSerializer, ExpenseVoidSerializer,
    CommissionCalculationSerializer, CommissionPayoutSerializer,
    AuditLogSerializer
)
from .permissions import IsSuperAdmin, IsAdminUserOrSuperAdmin, IsSuperAdminOrReadOnly
from .services import InventoryService, FinancialService, TripService, ReceiptBookService
from .reports import ReportGenerator


# --- Authentication Views ---

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = 'phone_number'

    def validate(self, attrs):
        phone = attrs.get('phone_number')
        if phone:
            attrs['phone_number'] = normalize_phone_number(phone)
        data = super().validate(attrs)
        data['user'] = {
            'id': self.user.id,
            'phone_number': self.user.phone_number,
            'display_name': self.user.display_name,
            'role': self.user.role,
            'must_change_password': self.user.must_change_password,
        }
        return data


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user

        if not user.check_password(serializer.validated_data['old_password']):
            return Response({'old_password': ['Wrong password.']}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data['new_password'])
        user.must_change_password = False
        user.save()

        AuditLog.objects.create(
            user=user,
            action='password_change',
            entity_type='User',
            entity_id=str(user.id),
            reason='Password changed by user'
        )

        return Response({'detail': 'Password changed successfully.'})


# --- Users Management ViewSet ---

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('-created_at')
    permission_classes = [IsSuperAdmin]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 6:
            return Response({'error': 'Password must be at least 6 characters long.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.must_change_password = True
        user.save()

        AuditLog.objects.create(
            user=request.user,
            action='user_password_reset',
            entity_type='User',
            entity_id=str(user.id),
            reason=f"Password reset by Superadmin {request.user.display_name}"
        )
        return Response({'detail': f'Password for {user.display_name} has been reset.'})

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        if user == request.user:
            return Response({'error': 'You cannot deactivate your own account.'}, status=status.HTTP_400_BAD_REQUEST)

        # Check if user is the last active super admin
        if user.is_super_admin and user.is_active:
            active_super_admins = User.objects.filter(role='super_admin', is_active=True).count()
            if active_super_admins <= 1:
                return Response({'error': 'Cannot deactivate the last active Super Administrator.'}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = not user.is_active
        user.save()

        AuditLog.objects.create(
            user=request.user,
            action='user_toggle_active',
            entity_type='User',
            entity_id=str(user.id),
            reason=f"Account status set to {'active' if user.is_active else 'inactive'}"
        )
        return Response({'detail': f"User is now {'active' if user.is_active else 'inactive'}."})


# --- Campaigns ViewSet ---

class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all().order_by('-year')
    serializer_class = CampaignSerializer

    def get_permissions(self):
        if self.action in ['destroy']:
            return [IsSuperAdmin()]
        return [IsAdminUserOrSuperAdmin()]

    def perform_create(self, serializer):
        with transaction.atomic():
            campaign = serializer.save(created_by=self.request.user)
            # Create opening printing expense exactly once
            Expense.objects.get_or_create(
                campaign=campaign,
                category='printing',
                is_voided=False,
                defaults={
                    'amount': campaign.proposed_printing_expense,
                    'date': timezone.now().date(),
                    'description': f"Initial printing expense: {campaign.printed_quantity} calendars @ ₹{campaign.cost_price_per_calendar}",
                    'created_by': self.request.user,
                }
            )
            # Create opening stock inventory movement
            InventoryMovement.objects.get_or_create(
                campaign=campaign,
                movement_type='opening_stock',
                defaults={
                    'quantity': campaign.printed_quantity,
                    'reason': f"Initial printed calendar stock for {campaign.year}",
                    'created_by': self.request.user,
                }
            )
            AuditLog.objects.create(
                user=self.request.user,
                action='campaign_create',
                entity_type='Campaign',
                entity_id=str(campaign.id),
                reason=f"Campaign {campaign.year} created"
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            old_campaign = Campaign.objects.get(pk=serializer.instance.pk)
            old_qty = old_campaign.printed_quantity
            old_cost = old_campaign.cost_price_per_calendar
            old_status = old_campaign.status

            campaign = serializer.save()

            # If printed_quantity or cost_price_per_calendar changed, update the initial printing expense idempotently
            if old_qty != campaign.printed_quantity or old_cost != campaign.cost_price_per_calendar:
                printing_expense = Expense.objects.filter(
                    campaign=campaign,
                    category='printing',
                    is_voided=False
                ).first()
                if printing_expense:
                    printing_expense.amount = campaign.proposed_printing_expense
                    printing_expense.description = f"Initial printing expense: {campaign.printed_quantity} calendars @ ₹{campaign.cost_price_per_calendar}"
                    printing_expense.save(update_fields=['amount', 'description'])
                else:
                    Expense.objects.create(
                        campaign=campaign,
                        category='printing',
                        is_voided=False,
                        amount=campaign.proposed_printing_expense,
                        date=timezone.now().date(),
                        description=f"Initial printing expense: {campaign.printed_quantity} calendars @ ₹{campaign.cost_price_per_calendar}",
                        created_by=self.request.user
                    )

                # Update opening stock inventory movement if printed_quantity changed
                if old_qty != campaign.printed_quantity:
                    opening_stock = InventoryMovement.objects.filter(
                        campaign=campaign,
                        movement_type='opening_stock'
                    ).first()
                    if opening_stock:
                        opening_stock.quantity = campaign.printed_quantity
                        opening_stock.reason = f"Initial printed calendar stock for {campaign.year} (updated)"
                        opening_stock.save(update_fields=['quantity', 'reason'])
                    else:
                        InventoryMovement.objects.create(
                            campaign=campaign,
                            movement_type='opening_stock',
                            quantity=campaign.printed_quantity,
                            reason=f"Initial printed calendar stock for {campaign.year}",
                            created_by=self.request.user
                        )

            # If status changed to closed
            if old_status != 'closed' and campaign.status == 'closed':
                FinancialService.close_campaign(campaign, self.request.user)

            AuditLog.objects.create(
                user=self.request.user,
                action='campaign_update',
                entity_type='Campaign',
                entity_id=str(campaign.id),
                before_snapshot={
                    'name': old_campaign.name,
                    'year': old_campaign.year,
                    'printed_quantity': old_campaign.printed_quantity,
                    'cost_price_per_calendar': str(old_campaign.cost_price_per_calendar),
                    'min_expected_collection_per_calendar': str(old_campaign.min_expected_collection_per_calendar),
                    'commission_percentage': str(old_campaign.commission_percentage),
                    'status': old_campaign.status,
                },
                after_snapshot={
                    'name': campaign.name,
                    'year': campaign.year,
                    'printed_quantity': campaign.printed_quantity,
                    'cost_price_per_calendar': str(campaign.cost_price_per_calendar),
                    'min_expected_collection_per_calendar': str(campaign.min_expected_collection_per_calendar),
                    'commission_percentage': str(campaign.commission_percentage),
                    'status': campaign.status,
                },
                reason=f"Campaign {campaign.year} settings updated"
            )

    @action(detail=True, methods=['get'], url_path='summary')
    def summary(self, request, pk=None):
        campaign = self.get_object()
        fin = FinancialService.get_campaign_financial_summary(campaign)
        inv = InventoryService.get_campaign_inventory_summary(campaign)
        return Response({
            'financial': fin,
            'inventory': inv,
            'campaign': CampaignSerializer(campaign).data,
        })

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        campaign = self.get_object()
        with transaction.atomic():
            campaign.status = 'active'
            campaign.closed_at = None
            campaign.save(update_fields=['status', 'closed_at'])

            AuditLog.objects.create(
                user=request.user,
                action='campaign_activate',
                entity_type='Campaign',
                entity_id=str(campaign.id),
                reason=f"Campaign {campaign.year} activated by {request.user.display_name}."
            )
            return Response({
                'detail': f"Campaign {campaign.year} activated successfully.",
                'campaign': CampaignSerializer(campaign).data
            })

    @action(detail=True, methods=['post'], url_path='close')
    def close(self, request, pk=None):
        campaign = self.get_object()
        try:
            closed_campaign = FinancialService.close_campaign(campaign, request.user)
            return Response({
                'detail': f"Campaign {closed_campaign.year} closed successfully.",
                'campaign': CampaignSerializer(closed_campaign).data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# --- Students ViewSet ---

class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all().order_by('name')
    serializer_class = StudentSerializer
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        active_only = self.request.query_params.get('active_only')
        if active_only == 'true':
            qs = qs.filter(is_active=True)
        return qs

    @action(detail=True, methods=['get'], url_path='summary')
    def summary(self, request, pk=None):
        student = self.get_object()
        campaign_id = request.query_params.get('campaign_id')
        if campaign_id:
            campaign = Campaign.objects.get(id=campaign_id)
        else:
            campaign = Campaign.objects.filter(status='active').first() or Campaign.objects.first()

        if not campaign:
            return Response({'error': 'No campaign found'}, status=status.HTTP_400_BAD_REQUEST)

        calc = FinancialService.recalculate_student_commission(campaign, student)
        participations = TripStudent.objects.filter(
            trip__campaign=campaign,
            student=student
        ).select_related('trip', 'trip__place').order_by('-trip__trip_date')

        trips_data = []
        for p in participations:
            trips_data.append({
                'trip_id': p.trip.id,
                'trip_date': p.trip.trip_date,
                'place_name': p.trip.place.name,
                'status': p.trip.status,
                'review_status': p.trip.review_status,
                'gross_share': p.gross_collection_share,
                'fare_share': p.bus_fare_share,
                'food_share': p.food_expense_share,
                'net_share': p.net_collection_share,
            })

        payouts = CommissionPayout.objects.filter(campaign=campaign, student=student)
        payouts_data = CommissionPayoutSerializer(payouts, many=True).data
        total_paid = payouts.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        return Response({
            'student': StudentSerializer(student).data,
            'campaign_id': campaign.id,
            'campaign_year': campaign.year,
            'gross_collection': calc.gross_collection,
            'fare_share': calc.fare_share,
            'food_share': calc.food_share,
            'net_collection': calc.net_collection,
            'commission_rate': calc.rate,
            'commission_earned': calc.calculated_commission,
            'commission_paid': total_paid,
            'outstanding_payable': max(Decimal('0.00'), calc.calculated_commission - total_paid),
            'finalization_status': calc.finalization_status,
            'trips_count': len(trips_data),
            'trips': trips_data,
            'payouts': payouts_data,
        })


# --- Places ViewSet ---

class PlaceViewSet(viewsets.ModelViewSet):
    queryset = Place.objects.all().order_by('name')
    serializer_class = PlaceSerializer
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


# --- Receipt Books ViewSet ---

class ReceiptBookViewSet(viewsets.ModelViewSet):
    queryset = ReceiptBook.objects.all().order_by('label')
    serializer_class = ReceiptBookSerializer
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)
        return qs

    @action(detail=True, methods=['get'], url_path='usage')
    def usage(self, request, pk=None):
        book = self.get_object()
        trips = Trip.objects.filter(receipt_book=book).exclude(status='voided').order_by('receipt_starting_leaf')
        ranges = []
        for t in trips:
            if t.receipt_starting_leaf and t.receipt_ending_leaf:
                ranges.append({
                    'trip_id': t.id,
                    'trip_date': t.trip_date,
                    'place': t.place.name,
                    'starting_leaf': t.receipt_starting_leaf,
                    'ending_leaf': t.receipt_ending_leaf,
                    'count': t.receipt_ending_leaf - t.receipt_starting_leaf + 1,
                    'voided_leaves': t.voided_leaves,
                    'status': t.status,
                })

        next_suggested = ReceiptBookService.get_next_suggested_leaf(book)

        return Response({
            'book': ReceiptBookSerializer(book).data,
            'used_ranges': ranges,
            'next_suggested_leaf': next_suggested,
        })


# --- Trips ViewSet ---

class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all().select_related('place', 'receipt_book', 'campaign', 'created_by', 'settled_by').prefetch_related('trip_students__student')
    serializer_class = TripSerializer
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)
        trip_status = self.request.query_params.get('status')
        if trip_status:
            qs = qs.filter(status=trip_status)
        review_status = self.request.query_params.get('review_status')
        if review_status:
            qs = qs.filter(review_status=review_status)
        student_id = self.request.query_params.get('student')
        if student_id:
            qs = qs.filter(trip_students__student_id=student_id)
        place_id = self.request.query_params.get('place')
        if place_id:
            qs = qs.filter(place_id=place_id)
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(place__name__icontains=search) |
                Q(trip_students__student__name__icontains=search) |
                Q(receipt_book__label__icontains=search)
            ).distinct()
        return qs

    def create(self, request, *args, **kwargs):
        """Dispatch a new trip."""
        serializer = TripDispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            trip = TripService.dispatch_trip(
                campaign=data['campaign'],
                place=data['place'],
                trip_date=data['trip_date'],
                departure_time=data.get('departure_time'),
                student_ids=data['student_ids'],
                calendars_issued=data['calendars_issued'],
                receipt_book=data.get('receipt_book'),
                receipt_starting_leaf=data.get('receipt_starting_leaf'),
                bus_fare=data.get('bus_fare', Decimal('0.00')),
                notes=data.get('notes', ''),
                user=request.user
            )
            return Response(TripSerializer(trip).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='settle')
    def settle(self, request, pk=None):
        """Settle a returned trip."""
        trip = self.get_object()
        serializer = TripSettleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            settled_trip = TripService.settle_trip(
                trip=trip,
                return_time=data.get('return_time'),
                calendars_sold=data['calendars_sold'],
                calendars_returned=data['calendars_returned'],
                cash_collection=data['cash_collection'],
                gpay_collection=data['gpay_collection'],
                food_expense=data.get('food_expense', Decimal('0.00')),
                receipt_book=data.get('receipt_book'),
                receipt_starting_leaf=data.get('receipt_starting_leaf'),
                receipt_ending_leaf=data.get('receipt_ending_leaf'),
                voided_leaves=data.get('voided_leaves', ''),
                discrepancy_notes=data.get('discrepancy_notes', ''),
                user=request.user
            )
            return Response(TripSerializer(settled_trip).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='void')
    def void(self, request, pk=None):
        """Void an open trip."""
        trip = self.get_object()
        serializer = TripVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']

        try:
            voided_trip = TripService.void_trip(trip, reason, request.user)
            return Response(TripSerializer(voided_trip).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='review')
    def review(self, request, pk=None):
        """Review discrepancy or accept warnings."""
        trip = self.get_object()
        serializer = TripReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review_status_val = serializer.validated_data['review_status']
        notes = serializer.validated_data.get('notes', '')

        trip.review_status = review_status_val
        if notes:
            trip.discrepancy_notes = f"{trip.discrepancy_notes}\n[REVIEW NOTE]: {notes}".strip()
        trip.save()

        AuditLog.objects.create(
            user=request.user,
            action='trip_review',
            entity_type='Trip',
            entity_id=str(trip.id),
            reason=f"Review status changed to {review_status_val}. Note: {notes}"
        )
        return Response(TripSerializer(trip).data)


# --- Inventory Views ---

class InventorySummaryView(APIView):
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get(self, request, *args, **kwargs):
        campaign_id = request.query_params.get('campaign')
        if campaign_id:
            campaign = Campaign.objects.get(id=campaign_id)
        else:
            campaign = Campaign.objects.filter(status='active').first() or Campaign.objects.first()

        if not campaign:
            return Response({'error': 'No campaign found'}, status=status.HTTP_400_BAD_REQUEST)

        summary = InventoryService.get_campaign_inventory_summary(campaign)
        return Response(summary)


class InventoryMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = InventoryMovement.objects.all().select_related('campaign', 'related_trip', 'created_by')
    serializer_class = InventoryMovementSerializer
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)
        m_type = self.request.query_params.get('movement_type')
        if m_type:
            qs = qs.filter(movement_type=m_type)
        return qs


class InventoryAdjustmentView(generics.CreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = InventoryAdjustmentSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            movement = InventoryService.record_adjustment(
                campaign=data['campaign'],
                quantity=data['quantity'],
                reason=data['reason'],
                user=request.user
            )
        except ValidationError as e:
            return Response({'detail': e.message if hasattr(e, 'message') else str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(InventoryMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


# --- Expenses ViewSet ---

class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all().select_related('campaign', 'related_trip', 'created_by')
    serializer_class = ExpenseSerializer
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        start_date = self.request.query_params.get('start_date')
        if start_date:
            qs = qs.filter(date__gte=start_date)
        end_date = self.request.query_params.get('end_date')
        if end_date:
            qs = qs.filter(date__lte=end_date)
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(description__icontains=search) | Q(notes__icontains=search))
        return qs

    def perform_create(self, serializer):
        expense = serializer.save(created_by=self.request.user)
        AuditLog.objects.create(
            user=self.request.user,
            action='expense_create',
            entity_type='Expense',
            entity_id=str(expense.id),
            after_snapshot={
                'category': expense.category,
                'amount': str(expense.amount),
                'date': str(expense.date),
                'description': expense.description,
            },
            reason="Expense recorded"
        )

    @action(detail=True, methods=['post'], url_path='void')
    def void(self, request, pk=None):
        expense = self.get_object()
        serializer = ExpenseVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']

        if expense.is_voided:
            return Response({'error': 'Expense is already voided.'}, status=status.HTTP_400_BAD_REQUEST)

        expense.is_voided = True
        expense.voided_reason = reason
        expense.updated_by = request.user
        expense.save()

        AuditLog.objects.create(
            user=request.user,
            action='expense_void',
            entity_type='Expense',
            entity_id=str(expense.id),
            reason=reason
        )

        return Response(ExpenseSerializer(expense).data)


# --- Commission Views ---

class CommissionSummaryView(APIView):
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get(self, request, *args, **kwargs):
        campaign_id = request.query_params.get('campaign')
        if campaign_id:
            campaign = Campaign.objects.get(id=campaign_id)
        else:
            campaign = Campaign.objects.filter(status='active').first() or Campaign.objects.first()

        if not campaign:
            return Response({'error': 'No campaign found'}, status=status.HTTP_400_BAD_REQUEST)

        # Trigger refresh calculations for active students
        for student in Student.objects.filter(trip_participations__trip__campaign=campaign, trip_participations__trip__status='settled').distinct():
            FinancialService.recalculate_student_commission(campaign, student)

        calculations = CommissionCalculation.objects.filter(campaign=campaign).select_related('student')
        payouts = CommissionPayout.objects.filter(campaign=campaign)

        total_earned = calculations.aggregate(t=Sum('calculated_commission'))['t'] or Decimal('0.00')
        total_paid = payouts.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        outstanding = max(Decimal('0.00'), total_earned - total_paid)

        return Response({
            'campaign_id': campaign.id,
            'campaign_year': campaign.year,
            'commission_rate': campaign.commission_percentage,
            'campaign_status': campaign.status,
            'total_commission_earned': total_earned,
            'total_commission_paid': total_paid,
            'outstanding_commission': outstanding,
            'students_count': calculations.count(),
            'students': CommissionCalculationSerializer(calculations, many=True).data,
        })


class CommissionFinalizeView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, *args, **kwargs):
        campaign_id = request.data.get('campaign_id')
        if not campaign_id:
            return Response({'error': 'campaign_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            campaign = Campaign.objects.get(id=campaign_id)
            FinancialService.finalize_campaign_commission(campaign, request.user)
            return Response({'detail': f'Commission for campaign {campaign.year} has been finalized.'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CommissionPayoutViewSet(viewsets.ModelViewSet):
    queryset = CommissionPayout.objects.all().select_related('campaign', 'student', 'created_by')
    serializer_class = CommissionPayoutSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsSuperAdmin()]
        return [IsAdminUserOrSuperAdmin()]

    def get_queryset(self):
        qs = super().get_queryset()
        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)
        student_id = self.request.query_params.get('student')
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs

    def create(self, request, *args, **kwargs):
        student_id = request.data.get('student')
        campaign_id = request.data.get('campaign')
        amount = Decimal(str(request.data.get('amount', 0)))
        payment_date = request.data.get('payment_date', timezone.now().date())
        payment_method = request.data.get('payment_method', 'cash')
        reference = request.data.get('reference', '')
        notes = request.data.get('notes', '')

        try:
            student = Student.objects.get(id=student_id)
            campaign = Campaign.objects.get(id=campaign_id)
            payout = FinancialService.record_payout(
                campaign=campaign,
                student=student,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                reference=reference,
                notes=notes,
                user=request.user
            )
            return Response(CommissionPayoutSerializer(payout).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# --- Reports Views ---

class ReportSummaryView(APIView):
    permission_classes = [IsAdminUserOrSuperAdmin]

    def get(self, request, *args, **kwargs):
        campaign_id = request.query_params.get('campaign')
        if campaign_id:
            campaign = Campaign.objects.get(id=campaign_id)
        else:
            campaign = Campaign.objects.filter(status='active').first() or Campaign.objects.first()

        if not campaign:
            return Response({'error': 'No campaign found'}, status=status.HTTP_400_BAD_REQUEST)

        fin = FinancialService.get_campaign_financial_summary(campaign)
        inv = InventoryService.get_campaign_inventory_summary(campaign)

        # Destination performance summary
        places_summary = Place.objects.filter(trips__campaign=campaign, trips__status='settled').annotate(
            trips_count=Count('trips', distinct=True),
            total_sold=Sum('trips__calendars_sold'),
            total_collected=Sum('trips__cash_collection') + Sum('trips__gpay_collection'),
            total_expenses=Sum('trips__bus_fare') + Sum('trips__food_expense'),
        ).values('id', 'name', 'trips_count', 'total_sold', 'total_collected', 'total_expenses')

        return Response({
            'financial': fin,
            'inventory': inv,
            'places': list(places_summary),
        })


class PassthroughRenderer(BaseRenderer):
    media_type = '*/*'
    format = ''
    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class ReportExportView(APIView):
    permission_classes = [IsAdminUserOrSuperAdmin]
    renderer_classes = [PassthroughRenderer, JSONRenderer]

    def perform_content_negotiation(self, request, force=False):
        return (PassthroughRenderer(), '*/*')

    def get(self, request, *args, **kwargs):
        campaign_id = request.query_params.get('campaign')
        fmt = request.query_params.get('export_format') or request.query_params.get('format', 'excel')
        report_type = request.query_params.get('type', 'trips')

        if campaign_id:
            campaign = Campaign.objects.get(id=campaign_id)
        else:
            campaign = Campaign.objects.filter(status='active').first() or Campaign.objects.first()

        if not campaign:
            return Response({'error': 'No campaign found'}, status=status.HTTP_400_BAD_REQUEST)

        if fmt == 'excel':
            return ReportGenerator.export_excel(campaign, report_type)
        elif fmt == 'csv':
            return ReportGenerator.export_csv(campaign, report_type)
        elif fmt == 'pdf':
            return ReportGenerator.export_pdf(campaign)
        else:
            return Response({'error': f'Unsupported export format: {fmt}'}, status=status.HTTP_400_BAD_REQUEST)


# --- Audit Logs ViewSet ---

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all().select_related('user')
    serializer_class = AuditLogSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        action_name = self.request.query_params.get('action')
        if action_name:
            qs = qs.filter(action=action_name)
        entity_type = self.request.query_params.get('entity_type')
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        entity_id = self.request.query_params.get('entity_id')
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        return qs

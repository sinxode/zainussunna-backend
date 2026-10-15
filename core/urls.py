from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    LoginView, MeView, ChangePasswordView,
    UserViewSet, CampaignViewSet, StudentViewSet, PlaceViewSet,
    ReceiptBookViewSet, TripViewSet,
    InventorySummaryView, InventoryMovementViewSet, InventoryAdjustmentView,
    ExpenseViewSet, CommissionSummaryView, CommissionFinalizeView,
    CommissionPayoutViewSet, ReportSummaryView, ReportExportView,
    AuditLogViewSet
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'campaigns', CampaignViewSet, basename='campaign')
router.register(r'students', StudentViewSet, basename='student')
router.register(r'places', PlaceViewSet, basename='place')
router.register(r'receipt-books', ReceiptBookViewSet, basename='receipt-book')
router.register(r'trips', TripViewSet, basename='trip')
router.register(r'inventory/movements', InventoryMovementViewSet, basename='inventory-movement')
router.register(r'expenses', ExpenseViewSet, basename='expense')
router.register(r'commission/payouts', CommissionPayoutViewSet, basename='commission-payout')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')

urlpatterns = [
    # Authentication
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('auth/me/', MeView.as_view(), name='auth-me'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='auth-change-password'),

    # Inventory
    path('inventory/summary/', InventorySummaryView.as_view(), name='inventory-summary'),
    path('inventory/adjustments/', InventoryAdjustmentView.as_view(), name='inventory-adjustments'),

    # Commission
    path('commission/summary/', CommissionSummaryView.as_view(), name='commission-summary'),
    path('commission/finalize/', CommissionFinalizeView.as_view(), name='commission-finalize'),

    # Reports
    path('reports/summary/', ReportSummaryView.as_view(), name='reports-summary'),
    path('reports/export/', ReportExportView.as_view(), name='reports-export'),

    # ViewSet routes
    path('', include(router.urls)),
]

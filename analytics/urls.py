"""
URL Configuration for Analytics API
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SalesAnalyticsViewSet,
    ApplicationFunnelViewSet,
    DeviceEnrollmentViewSet,
    BrandModelAnalyticsViewSet,
    GeographicAnalyticsViewSet,
    FPDAnalyticsViewSet,
    FinancialMetricsViewSet,
    ClerkPerformanceViewSet,
    HourlyAnalyticsViewSet,
    DashboardOverviewViewSet,

    DailyFinanceMetricsViewSet,
    BrandPerformanceMetricsViewSet,
    ProductPerformanceMetricsViewSet,
    SalespersonPerformanceViewSet,
    PaymentCollectionMetricsViewSet,
    RiskAnalysisMetricsViewSet,
    GeographicPerformanceMetricsViewSet,
    DeviceLockPerformanceMetricsViewSet,
    DashboardViewSet
)

router = DefaultRouter()

# Register viewsets
router.register(r'sales', SalesAnalyticsViewSet, basename='sales-analytics')
router.register(r'funnel', ApplicationFunnelViewSet, basename='funnel-analytics')
router.register(r'devices', DeviceEnrollmentViewSet, basename='device-analytics')
router.register(r'brands', BrandModelAnalyticsViewSet, basename='brand-analytics')
router.register(r'geographic', GeographicAnalyticsViewSet, basename='geographic-analytics')
router.register(r'fpd', FPDAnalyticsViewSet, basename='fpd-analytics')
router.register(r'financial', FinancialMetricsViewSet, basename='financial-analytics')
router.register(r'performance', ClerkPerformanceViewSet, basename='performance-analytics')
router.register(r'hourly', HourlyAnalyticsViewSet, basename='hourly-analytics')
router.register(r'dashboard-overview', DashboardOverviewViewSet, basename='dashboard-overview')


router.register(r'charts/daily-metrics', DailyFinanceMetricsViewSet, basename='daily-metrics')
router.register(r'charts/brand-performance', BrandPerformanceMetricsViewSet, basename='brand-performance')
router.register(r'charts/product-performance', ProductPerformanceMetricsViewSet, basename='product-performance')
router.register(r'charts/salesperson-performance', SalespersonPerformanceViewSet, basename='salesperson-performance')
router.register(r'charts/payment-collection', PaymentCollectionMetricsViewSet, basename='payment-collection')
router.register(r'charts/risk-analysis', RiskAnalysisMetricsViewSet, basename='risk-analysis')
router.register(r'charts/geographic-performance', GeographicPerformanceMetricsViewSet, basename='geographic-performance')
router.register(r'charts/device-lock-performance', DeviceLockPerformanceMetricsViewSet, basename='device-lock-performance')
router.register(r'charts/dashboard', DashboardViewSet, basename='dashboard')


urlpatterns = [
    path('', include(router.urls)),
]
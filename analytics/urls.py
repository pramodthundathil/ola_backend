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
    DashboardOverviewViewSet
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
router.register(r'dashboard', DashboardOverviewViewSet, basename='dashboard-overview')

urlpatterns = [
    path('', include(router.urls)),
]
from django.urls import path
from .views import (
    KPIsView, LoanTrendView, CustomerAnalyticsView, CollectionAnalyticsView,
    MerchantAnalyticsView, BranchAnalyticsView, DeviceAnalyticsView,
    GeographyAnalyticsView, FunnelAnalyticsView, RiskAnalyticsView,
    ExecutiveAnalyticsView, OperationsAnalyticsView, ReportsExportView
)

urlpatterns = [
    path('kpis/', KPIsView.as_view(), name='analytics-kpis'),
    path('loan-trend/', LoanTrendView.as_view(), name='analytics-loan-trend'),
    path('customer/', CustomerAnalyticsView.as_view(), name='analytics-customer'),
    path('collection/', CollectionAnalyticsView.as_view(), name='analytics-collection'),
    path('merchant/', MerchantAnalyticsView.as_view(), name='analytics-merchant'),
    path('branch/', BranchAnalyticsView.as_view(), name='analytics-branch'),
    path('device/', DeviceAnalyticsView.as_view(), name='analytics-device'),
    path('geography/', GeographyAnalyticsView.as_view(), name='analytics-geography'),
    path('funnel/', FunnelAnalyticsView.as_view(), name='analytics-funnel'),
    path('risk/', RiskAnalyticsView.as_view(), name='analytics-risk'),
    path('executive/', ExecutiveAnalyticsView.as_view(), name='analytics-executive'),
    path('operations/', OperationsAnalyticsView.as_view(), name='analytics-operations'),
    path('reports/export/', ReportsExportView.as_view(), name='analytics-reports-export'),
]
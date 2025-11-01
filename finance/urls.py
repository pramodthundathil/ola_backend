from django.urls import path
from .import views

urlpatterns = [  
    
    path('auto-plan/', views.AutoFinancePlanView.as_view(), name='finance-auto-plan'),
    path('finance-plan/', views.FinancePlanAPIView.as_view(), name='finance-plan-list'),
    path('finance-plan/<int:plan_id>/', views.FinancePlanDetailAPIView.as_view(), name='finance-plan-detail'), 
    path('analytics/overview/', views.FinanceOverviewAPIView.as_view(), name='finance-overview'),  
    path('analytics/risk-tiers/', views.FinanceRiskTierView.as_view(), name='finance-risk-tier'),
    path("analytics/collections/", views.FinanceCollectionsView.as_view(), name="finance_analytics_collections"),
    path("analytics/overdue/", views.FinanceOverdueView.as_view(), name="finance_analytics_overdue"),
    path("payments/", views.PaymentRecordListCreateView.as_view(), name="payments-record"),  
    path('payments/emi/<int:emi_id>/', views.FinanceInstallmentPaymentView.as_view(), name='emi_payment'), 
    path("reports/common/", views.ReportsAPIView.as_view(), name="common-reports"),
    path("reports/region/", views.RegionWiseReportAPIView.as_view(), name="region-reports"),
       
    # EMI Schedule API
    path('finance/emi-schedule/', views.EMIScheduleAPIView.as_view(), name='emi-schedule'),
    
    # Payment Records API
    path('finance/payments/', views.PaymentRecordAPIView.as_view(), name='payment-records'),
]


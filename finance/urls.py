from django.urls import path
from .import views

urlpatterns = [  
    
    path('plans/', views.FinancePlanView.as_view(), name='finance-plan'),  
    path('analytics/overview/', views.FinanceOverviewAPIView.as_view(), name='finance-overview'),  
    path('analytics/risk-tiers/', views.FinanceRiskTierView.as_view(), name='finance-risk-tier'),
    path("analytics/collections/", views.FinanceCollectionsView.as_view(), name="finance_analytics_collections"),
    path("analytics/overdue/", views.FinanceOverdueView.as_view(), name="finance_analytics_overdue"),
    path("payments/", views.PaymentRecordListCreateView.as_view(), name="payments-record"),  
    path('payments/emi/<int:emi_id>/', views.FinanceInstallmentPaymentView.as_view(), name='emi_payment'),  

]

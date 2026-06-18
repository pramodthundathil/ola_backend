from django.urls import path
from .import views

urlpatterns = [  
    #Finance PLan
    path('auto-plan/', views.AutoFinancePlanView.as_view(), name='finance-auto-plan'),
    path('finance-plan/', views.FinancePlanAPIView.as_view(), name='finance-plan-list'),
    path('finance-plan/<int:plan_id>/', views.FinancePlanDetailAPIView.as_view(), name='finance-plan-detail'), 

    #Analytics
    path('analytics/overview/', views.FinanceOverviewAPIView.as_view(), name='finance-overview'),  
    path('analytics/risk-tiers/', views.FinanceRiskTierView.as_view(), name='finance-risk-tier'),
    path("analytics/collections/", views.FinanceCollectionsView.as_view(), name="finance_analytics_collections"),
    path("analytics/overdue/", views.FinanceOverdueView.as_view(), name="finance_analytics_overdue"),  

    #Report         
    path("reports/", views.FinanceReportAPIView.as_view(), name="finance-report"),
       
    # EMI Schedule API
    path('finance/emi-schedule/', views.EMIScheduleAPIView.as_view(), name='emi-schedule'),
    
    # Payment Records API
    path('payments/emi/<int:emi_id>/', views.FinanceInstallmentPaymentView.as_view(), name='emi_payment'),  
    path("payment-create/", views.PaymentRecordCreateAPIView.as_view(), name="payments-record"), 
    path('payments/', views.PaymentRecordAPIView.as_view(), name='payment-records'),    

    # FINACE MULTIPLE MANAGE
    path('finance-multiples/', views.FinanceMultipleListCreateView.as_view(), name='finance-multiple-list-create'),
    path('finance-multiples/<int:pk>/', views.FinanceMultipleDetailView.as_view(), name='finance-multiple-detail'),
    
    # PAYMENT
    path('pagofacil/api/consulta/', views.VerifyCustomerAPIView.as_view(), name='v2_finance_verify-customer_create'),
    path('pagofacil/api/directa/', views.WesternUnionPaymentAPIView.as_view(), name='v2_finance_directa_create'),
    path('pagofacil/api/reversa/', views.WesternUnionReverseAPIView.as_view(), name='v2_finance_reversa_create'),

    #Finance Complete Details
    path('full-details/admin/',views.FinanceCompleteDetailsAdminAPIView.as_view(),name='finance-full-details'),
    path('full-details/sales-advisor/',views.FinanceCompleteDetailsSalesAdvisorAPIView.as_view(),name='finance-full-details-sales-manager'),
    path('full-details/store-manager/',views.FinanceCompleteDetailsStoreManagerAPIView.as_view(),name='finance-full-details-store-manager'),
    
    # YAPPY PAYMENT
    path("yappy/create-order/", views.YappyCreateOrderView.as_view(), name="yappy-create-order"),
    path("yappy/ipn/", views.YappyIPNView.as_view(), name="yappy-ipn"),




]

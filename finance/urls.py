from django.urls import path
from .import views

urlpatterns = [  
    #Finance PLan
    path('auto-plan/', views.AutoFinancePlanView.as_view(), name='finance-auto-plan'),
    path('finance-plan/', views.FinancePlanAPIView.as_view(), name='finance-plan-list'),
    path('finance-plan/<int:plan_id>/', views.FinancePlanDetailAPIView.as_view(), name='finance-plan-detail'), 
    path('finance-plan/<int:plan_id>/activate/', views.FinancePlanActivateAPIView.as_view(), name='finance-plan-activate'),
    path('configuration/', views.FinanceConfigAPIView.as_view(), name='finance-configuration'), 
    path('generate-plans/', views.FinanceGeneratePlansAPIView.as_view(), name='finance-generate-plans'), 
    path('contracts/', views.FinanceContractsAPIView.as_view(), name='finance-contracts'), 
    path('contracts/download-pdf/', views.FinanceContractsPDFView.as_view(), name='finance-contracts-download-pdf'), 

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

    # ACCOUNTING
    path('accounting-codes/', views.AccountingCodeListAPIView.as_view(), name='accounting-codes-list'),
    path('accounting-codes/create/', views.AccountingCodeCreateAPIView.as_view(), name='accounting-codes-create'),
    path('tax/', views.TaxListCreateAPIView.as_view(), name='tax-list-create'),
    path('bank-accounts/', views.BankAccountListCreateAPIView.as_view(), name='bank-account-list-create'),
    path('bank-accounts/<int:pk>/', views.BankAccountDetailAPIView.as_view(), name='bank-account-detail'),
    path('bank-accounts/<int:bank_account_id>/upload-statement/', views.BankAccountUploadStatementAPIView.as_view(), name='bank-account-upload-statement'),
    path('bank-accounts/<int:bank_account_id>/uncategorized-entries/', views.BankAccountUncategorizedEntriesAPIView.as_view(), name='bank-account-uncategorized-entries'),
    path('bank-accounts/uncategorized-entries/map/', views.UncategorizedBankEntriesBulkMapAPIView.as_view(), name='bank-entries-bulk-map'),
    path('bank-accounts/uncategorized-entries/<int:pk>/map/', views.UncategorizedBankEntryMapAPIView.as_view(), name='bank-entry-map'),
    path('invoices/', views.InvoiceListAPIView.as_view(), name='invoices-list'),
    path('invoices/<int:pk>/', views.InvoiceDetailAPIView.as_view(), name='invoices-detail'),
    path('payment-received/', views.PaymentReceivedListCreateAPIView.as_view(), name='payment-received-list-create'),
    path('payment-received/<int:pk>/', views.PaymentReceivedDetailAPIView.as_view(), name='payment-received-detail'),
    path('ledger-entries/', views.LedgerEntryListAPIView.as_view(), name='ledger-entries-list'),
    path('vendors/', views.VendorListCreateAPIView.as_view(), name='vendors-list-create'),
    path('vendors/<int:pk>/', views.VendorDetailAPIView.as_view(), name='vendors-detail'),
    path('expenses/', views.ExpenseListCreateAPIView.as_view(), name='expenses-list-create'),
    path('expenses/<int:pk>/', views.ExpenseDetailAPIView.as_view(), name='expenses-detail'),
    path('bills/', views.BillListCreateAPIView.as_view(), name='bills-list-create'),
    path('bills/<int:pk>/', views.BillDetailAPIView.as_view(), name='bills-detail'),
    path('payments-made/', views.PaymentMadeListCreateAPIView.as_view(), name='payments-made-list-create'),
    path('payments-made/<int:pk>/', views.PaymentMadeDetailAPIView.as_view(), name='payments-made-detail'),
    path('credit-notes/', views.CreditNoteListCreateAPIView.as_view(), name='credit-notes-list-create'),
    path('journal-entries/', views.JournalEntryListCreateAPIView.as_view(), name='journal-entries-list-create'),
    
    # LOAN ACCOUNTING & LEDGER
    path('disbursements/', views.LoanDisbursementAPIView.as_view(), name='loan-disbursements-list-create'),
    path('disbursements/<int:pk>/reverse/', views.LoanDisbursementReverseAPIView.as_view(), name='loan-disbursement-reverse'),
    path('settlements/', views.MerchantSettlementAPIView.as_view(), name='merchant-settlements-list'),
    path('settlements/<int:pk>/pay/', views.MerchantSettlementPayAPIView.as_view(), name='merchant-settlement-pay'),
    path('settlements/<int:pk>/cancel/', views.MerchantSettlementCancelAPIView.as_view(), name='merchant-settlement-cancel'),
    path('merchant-ledger/<uuid:store_id>/', views.MerchantLedgerAPIView.as_view(), name='merchant-ledger'),
    path('customer-loan-ledger/<int:plan_id>/', views.CustomerLoanLedgerAPIView.as_view(), name='customer-loan-ledger'),
    path('loans/<int:plan_id>/manual-action/', views.LoanManualActionAPIView.as_view(), name='loan-manual-action'),
    path('emi-schedule/<int:emi_id>/create-invoice/', views.EMIInvoiceCreateAPIView.as_view(), name='emi-create-invoice'),
]

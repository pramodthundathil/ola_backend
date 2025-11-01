from django.urls import path
from .import views

urlpatterns = [
    # CUSTOMER 
    path('manage/',views.CustomerManagementView.as_view(), name='customer-manage'),
    path('update-status/', views.CustomerStatusUpdateView.as_view(), name='customer-status-update'),

    # EXPERIAN CREDIT SCORE CHECK
    path('credit-config/',views.CreditConfigGetAPIView.as_view(), name='credit-config'),
    path('credit-config-change/', views.CreditConfigChangeAPIView.as_view(), name='credit-config-change'),
    path('<int:customer_id>/credit-score/', views.CreditScoreCheckAPIView.as_view(), name='credit-score-check'),

    #  CUSTEMER REFENCES
    path('personal-references/<int:customer_id>/', views.PersonalReferenceListCreateAPIView.as_view(), name='personal-reference-list-create'),
    path('personal-references/detail/<int:pk>/', views.PersonalReferenceDetailAPIView.as_view(), name='personal-reference-detail'),

    path("income-sheet/", views.CustomerIncomeFileView.as_view(), name="income-sheet"),


]




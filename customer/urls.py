from django.urls import path
from .import views

urlpatterns = [
    # CUSTOMER 
    path('manage/',views.CustomerManagementView.as_view(), name='customer-manage'),
    path('update-status/', views.CustomerStatusUpdateView.as_view(), name='customer-status-update'),

    # EXPERIAN CREDIT SCORE CHECK
    path('credit-config/', views.CreditConfigAPIView.as_view(), name='credit-config'),
    path('<int:customer_id>/credit-score/', views.CreditScoreCheckAPIView.as_view(), name='credit-score-check'),


]




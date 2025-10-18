from django.urls import path
from .import views

urlpatterns = [
  
    # Metamap verification
    path('metamap/webhook/', views.MetaMapWebhookView.as_view(), name='metamap-webhook'),
    path('generate-verification-link/', views.GenerateVerificationLinkView.as_view(), name='generate-verification-link'),

    path('list/',views.CustomerManagementView.as_view(), name='customer'),



    path('customer/<int:customer_id>/credit-score/', views.CreditScoreCheckAPIView.as_view(), name='credit-score-check'),


]




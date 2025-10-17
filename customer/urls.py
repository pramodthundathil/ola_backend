from django.urls import path

# from .views import MetaMapWebhookView
# from .views import GenerateVerificationLinkView
from .import views

urlpatterns = [
  
    # Metamap verification
    path('metamap/webhook/', views.MetaMapWebhookView.as_view(), name='metamap-webhook'),
    path('generate-verification-link/', views.GenerateVerificationLinkView.as_view(), name='generate-verification-link'),


]



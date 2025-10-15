from django.urls import path
from .views import MetaMapWebhookView
from .views import GenerateVerificationLinkView

urlpatterns = [
    path('api/metamap/webhook/', MetaMapWebhookView.as_view(), name='metamap-webhook'),
    path('api/generate-verification-link/', GenerateVerificationLinkView.as_view(), name='generate-verification-link'),
]
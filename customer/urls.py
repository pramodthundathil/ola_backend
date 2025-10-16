from django.urls import path
# <<<<<<< HEAD

# urlpatterns = [

# ]
# =======
from .views import MetaMapWebhookView
from .views import GenerateVerificationLinkView

urlpatterns = [
    path('metamap/webhook/', MetaMapWebhookView.as_view(), name='metamap-webhook'),
    path('generate-verification-link/', GenerateVerificationLinkView.as_view(), name='generate-verification-link'),
]

# >>>>>>> dilshad/development

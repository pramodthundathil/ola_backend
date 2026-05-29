from django.urls import path
from .punto_pago_views import (
    HealthCheckAPIView,
    PuntoPagoAccountVerifyAPIView,
    PuntoPagoPaymentProcessAPIView,
    PuntoPagoPaymentStatusAPIView,
)

urlpatterns = [
    path('health/', HealthCheckAPIView.as_view(), name='puntopago_health'),
    path('health', HealthCheckAPIView.as_view()),
    path('account/verify/', PuntoPagoAccountVerifyAPIView.as_view(), name='puntopago_account_verify'),
    path('account/verify', PuntoPagoAccountVerifyAPIView.as_view()),
    path('payment/process/', PuntoPagoPaymentProcessAPIView.as_view(), name='puntopago_payment_process'),
    path('payment/process', PuntoPagoPaymentProcessAPIView.as_view()),
    path('payment/status/<str:payment_id>/', PuntoPagoPaymentStatusAPIView.as_view(), name='puntopago_payment_status'),
    path('payment/status/<str:payment_id>', PuntoPagoPaymentStatusAPIView.as_view()),
]

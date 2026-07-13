import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, BasePermission
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.db.models import Sum

from customer.models import Customer
from finance.models import FinancePlan, EMISchedule, PaymentRecord, Invoice, PaymentReceived, AccountingCode, BankAccount, EMIConfiguration
from finance.serializers import PuntoPagoVerifyRequestSerializer, PuntoPagoProcessRequestSerializer

logger = logging.getLogger(__name__)

# ============================================================
# PUNTO PAGO AUTHENTICATION PERMISSION
# ============================================================

class HasPuntoPagoAPIKey(BasePermission):
    """
    Custom permission to validate Punto Pago requests via API key in Authorization header.
    Supports 'Bearer <key>', 'Api-Key <key>', 'ApiKey <key>', or raw key value.
    """
    def has_permission(self, request, view):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            logger.warning("[PuntoPagoAuth] Missing Authorization header.")
            return False
        
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() in ['bearer', 'api-key', 'apikey']:
            token = parts[1]
        else:
            token = auth_header
            
        expected_key = getattr(settings, 'PUNTO_PAGO_API_KEY', 'puntopago_sandbox_secret_2026')
        is_valid = (token == expected_key)
        if not is_valid:
            logger.warning("[PuntoPagoAuth] Invalid API Key received.")
        return is_valid


# ============================================================
# ENDPOINTS
# ============================================================

class HealthCheckAPIView(APIView):
    """
    Recommended Health Check Endpoint.
    Used by Punto Pago or internal monitoring systems.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Health Check",
        operation_description="Returns the status of the integration service.",
        responses={
            200: openapi.Response(
                description="Service is healthy",
                examples={
                    "application/json": {
                        "status": "UP"
                    }
                }
            )
        },
        tags=["Punto Pago Integration"]
    )
    def get(self, request):
        return Response({"status": "UP"}, status=status.HTTP_200_OK)


class PuntoPagoAccountVerifyAPIView(APIView):
    """
    Mandatory Account Verification Endpoint.
    Used by Punto Pago to validate a customer account before accepting payment.
    """
    authentication_classes = []
    permission_classes = [HasPuntoPagoAPIKey]

    @swagger_auto_schema(
        operation_summary="Verify Customer Account",
        operation_description="Validates that a customer account exists and calculates their total outstanding debt.",
        request_body=PuntoPagoVerifyRequestSerializer,
        responses={
            200: openapi.Response(
                description="Customer successfully verified",
                examples={
                    "application/json": {
                        "success": True,
                        "customer_name": "John Doe",
                        "identification": "12345678",
                        "current_debt": 150.75
                    }
                }
            ),
            400: "Invalid parameters",
            401: "Unauthorized",
            404: "Customer account not found"
        },
        tags=["Punto Pago Integration"]
    )
    def post(self, request):
        serializer = PuntoPagoVerifyRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        identification = serializer.validated_data['identification'].strip()
        
        # Search for customer by document number
        customer = Customer.objects.filter(document_number=identification).first()
        if not customer:
            logger.info(f"[PuntoPagoVerify] Customer not found with identification: {identification}")
            return Response({
                "success": False,
                "message": f"Customer not found with identification: {identification}"
            }, status=status.HTTP_404_NOT_FOUND)

        # Sum outstanding balance for unpaid generated invoices
        unpaid_invoices = Invoice.objects.filter(
            customer=customer,
            status__in=['PENDING', 'PARTIAL', 'OVERDUE']
        )
        
        total_debt = unpaid_invoices.aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
        
        customer_name = f"{customer.first_name} {customer.last_name}".strip()
        
        logger.info(f"[PuntoPagoVerify] Verified customer {customer_name} ({identification}), current_debt: {total_debt}")
        
        return Response({
            "success": True,
            "customer_name": customer_name,
            "identification": identification,
            "current_debt": float(total_debt)
        }, status=status.HTTP_200_OK)


class PuntoPagoPaymentProcessAPIView(APIView):
    """
    Mandatory Payment Processing Endpoint.
    Used by Punto Pago to register a payment in the system.
    """
    authentication_classes = []
    permission_classes = [HasPuntoPagoAPIKey]

    @swagger_auto_schema(
        operation_summary="Process Payment",
        operation_description="Registers a payment in the system and allocates it to the customer's unpaid EMIs.",
        request_body=PuntoPagoProcessRequestSerializer,
        responses={
            200: openapi.Response(
                description="Payment processed successfully (Already registered or completed)",
                examples={
                    "application/json": {
                        "success": True,
                        "payment_id": "PAY-987654",
                        "status": "PAID",
                        "message": "Payment registered successfully"
                    }
                }
            ),
            400: "Invalid request data or no active financing plan",
            401: "Unauthorized",
            404: "Customer account not found"
        },
        tags=["Punto Pago Integration"]
    )
    def post(self, request):
        serializer = PuntoPagoProcessRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        identification = serializer.validated_data['identification'].strip()
        payment_reference = serializer.validated_data['payment_reference'].strip()
        amount = Decimal(str(serializer.validated_data['amount']))

        if amount <= 0:
            return Response({
                "success": False,
                "message": "Payment amount must be greater than zero."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Idempotency check: search for existing payment with the same reference
        existing_payment = PaymentRecord.objects.filter(
            transaction_reference=payment_reference,
            payment_method='PUNTO_PAGO',
            payment_status='COMPLETED'
        ).first()

        if existing_payment:
            logger.info(f"[PuntoPagoProcess] Payment already processed for reference: {payment_reference}")
            return Response({
                "success": True,
                "payment_id": f"PAY-{existing_payment.id}",
                "status": "PAID",
                "message": "Payment already registered"
            }, status=status.HTTP_200_OK)

        # Check PaymentReceived for double safety
        existing_received = PaymentReceived.objects.filter(
            transaction_reference=payment_reference,
            payment_method='PUNTO_PAGO'
        ).first()
        if existing_received:
            first_rec = PaymentRecord.objects.filter(payment_received=existing_received).first()
            pid = f"PAY-{first_rec.id}" if first_rec else f"PAY-{existing_received.id}"
            logger.info(f"[PuntoPagoProcess] Payment already processed for reference (PaymentReceived): {payment_reference}")
            return Response({
                "success": True,
                "payment_id": pid,
                "status": "PAID",
                "message": "Payment already registered"
            }, status=status.HTTP_200_OK)

        # Fetch customer
        customer = Customer.objects.filter(document_number=identification).first()
        if not customer:
            logger.info(f"[PuntoPagoProcess] Customer not found with identification: {identification}")
            return Response({
                "success": False,
                "message": f"Customer not found with identification: {identification}"
            }, status=status.HTTP_404_NOT_FOUND)

        # Fetch active plans
        active_plans = FinancePlan.objects.filter(
            credit_application__customer=customer,
            is_active=True
        )
        if not active_plans.exists():
            return Response({
                "success": False,
                "message": "No active financing plan found for this customer."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Retrieve linked BankAccount from dynamic settings or fallback to settings
        bank_account = None
        config = EMIConfiguration.objects.filter(is_active=True).first()
        if config and config.punto_pago_bank_account:
            bank_account = config.punto_pago_bank_account

        if not bank_account:
            pp_bank_acc_num = getattr(settings, 'PUNTO_PAGO_BANK_ACCOUNT_NUMBER', '1234567890')
            bank_account = BankAccount.objects.filter(account_number=pp_bank_acc_num).first()
            if not bank_account:
                # Create standard BankAccount dynamically if not found
                bank_account = BankAccount.objects.create(
                    bank_name="Punto Pago Settlement Bank",
                    account_number=pp_bank_acc_num,
                    account_holder_name="Ola Credit",
                    initial_balance=Decimal('0.00'),
                    status="ACTIVE",
                    account_name="Punto Pago Account"
                )

        deposited_to = bank_account.accounting_code
        if not deposited_to:
            return Response({
                "success": False,
                "message": "Punto Pago bank account is not linked to any accounting code."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Retrieve generated unpaid invoices sequentially (oldest/due date first)
        unpaid_invoices = Invoice.objects.filter(
            customer=customer,
            status__in=['PENDING', 'PARTIAL', 'OVERDUE']
        ).order_by('due_date', 'id')

        total_debt = unpaid_invoices.aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
        if amount > total_debt:
            logger.warning(
                f"[PuntoPagoProcess] Payment amount {amount} exceeds "
                f"total outstanding balance {total_debt} for identification {identification}."
            )
            return Response({
                "success": False,
                "message": f"Payment amount {amount} exceeds the total outstanding balance of {total_debt}."
            }, status=status.HTTP_400_BAD_REQUEST)

        invoices_list = []
        remaining_amount = amount
        for inv in unpaid_invoices:
            if remaining_amount <= 0:
                break
            needed = inv.balance
            if needed <= 0:
                continue
            pay_amount = min(remaining_amount, needed)
            invoices_list.append({
                'invoice_id': inv.id,
                'amount_applied': float(pay_amount)
            })
            remaining_amount -= pay_amount

        # Generate unique PR number
        import random
        date_str = timezone.now().strftime("%Y%m%d")
        rand_str = str(random.randint(1000, 9999))
        payment_number = f"PR-{date_str}-{rand_str}"
        while PaymentReceived.objects.filter(payment_number=payment_number).exists():
            rand_str = str(random.randint(1000, 9999))
            payment_number = f"PR-{date_str}-{rand_str}"

        payment_notes = (
            f"Payment received via Punto Pago (Ref: {payment_reference}). "
            f"Deposited to bank account {bank_account.bank_name} - A/C: {bank_account.account_number} ({deposited_to.name})"
        )

        try:
            created_payments = []
            with transaction.atomic():
                # 1. Create PaymentReceived
                payment = PaymentReceived.objects.create(
                    payment_number=payment_number,
                    customer=customer,
                    amount_received=amount,
                    payment_date=timezone.now(),
                    payment_method='PUNTO_PAGO',
                    transaction_reference=payment_reference,
                    deposited_to=deposited_to,
                    invoices=invoices_list,
                    notes=payment_notes
                )
                # 2. Process payment (updates Invoice balance & status, creates segments, ledger entries)
                payment.process_payment(user=None)

                # Fetch all PaymentRecords created during process_payment
                created_payments = list(PaymentRecord.objects.filter(payment_received=payment).order_by('id'))

                # 3. Handle remaining amount / excess overpaid amount as an advance PaymentRecord
                if remaining_amount > 0:
                    last_invoice = unpaid_invoices.last()
                    last_emi = last_invoice.emi_schedule if last_invoice else EMISchedule.objects.filter(finance_plan__in=active_plans).last()
                    
                    extra_payment = PaymentRecord.objects.create(
                        finance_plan=active_plans.first(),
                        emi_schedule=last_emi,
                        payment_received=payment,
                        payment_type="EMI",
                        payment_method="PUNTO_PAGO",
                        payment_amount=remaining_amount,
                        payment_date=timezone.now(),
                        payment_status="COMPLETED",
                        transaction_reference=payment_reference,
                        notes=f"Excess payment segment received via Punto Pago (Ref: {payment_reference})"
                    )
                    created_payments.append(extra_payment)
                    logger.info(f"[PuntoPagoProcess] Excess amount of {remaining_amount} logged as advance.")

                # If no invoices were cleared at all, created_payments is empty, create a single advance PaymentRecord
                if not created_payments:
                    last_emi = EMISchedule.objects.filter(finance_plan__in=active_plans).last()
                    single_payment = PaymentRecord.objects.create(
                        finance_plan=active_plans.first(),
                        emi_schedule=last_emi,
                        payment_received=payment,
                        payment_type="EMI",
                        payment_method="PUNTO_PAGO",
                        payment_amount=amount,
                        payment_date=timezone.now(),
                        payment_status="COMPLETED",
                        transaction_reference=payment_reference,
                        notes=f"Advance payment received via Punto Pago (Ref: {payment_reference})"
                    )
                    created_payments.append(single_payment)

            main_payment_id = f"PAY-{created_payments[0].id}"

            logger.info(f"[PuntoPagoProcess] Payment processed successfully. Reference: {payment_reference}, Main ID: {main_payment_id}")

            return Response({
                "success": True,
                "payment_id": main_payment_id,
                "status": "PAID",
                "message": "Payment registered successfully"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(f"[PuntoPagoProcess] Failed to process payment {payment_reference}")
            return Response({
                "success": False,
                "message": f"An error occurred while registering payment: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PuntoPagoPaymentStatusAPIView(APIView):
    """
    Recommended Payment Status Endpoint.
    Used by Punto Pago to check the status of a registered payment.
    """
    authentication_classes = []
    permission_classes = [HasPuntoPagoAPIKey]

    @swagger_auto_schema(
        operation_summary="Get Payment Status",
        operation_description="Returns the current status of a payment using the payment_id.",
        responses={
            200: openapi.Response(
                description="Payment status retrieved",
                examples={
                    "application/json": {
                        "payment_id": "PAY-987654",
                        "status": "PAID"
                    }
                }
            ),
            401: "Unauthorized",
            404: "Payment not found"
        },
        tags=["Punto Pago Integration"]
    )
    def get(self, request, payment_id):
        # Extract numerical ID from payment_id string (e.g. PAY-12345)
        clean_id = payment_id
        if payment_id.startswith("PAY-"):
            clean_id = payment_id[4:]

        try:
            payment_record = PaymentRecord.objects.get(id=int(clean_id))
        except (PaymentRecord.DoesNotExist, ValueError):
            logger.warning(f"[PuntoPagoStatus] Payment record not found: {payment_id}")
            return Response({
                "message": f"Payment not found for ID: {payment_id}"
            }, status=status.HTTP_404_NOT_FOUND)

        # Standardize return status
        status_val = "PAID" if payment_record.payment_status == "COMPLETED" else payment_record.payment_status

        return Response({
            "payment_id": payment_id,
            "status": status_val
        }, status=status.HTTP_200_OK)

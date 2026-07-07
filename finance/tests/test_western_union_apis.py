import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import TestCase, override_settings
from datetime import date
from customer.models import Customer, CreditApplication, CreditScore
from products.models import ProductModel, Brand, ProductCategory
from finance.models import FinancePlan, EMISchedule, PaymentRecord, FinanceMultiple

User = get_user_model()

@override_settings(WESTERN_USER="pagofacil", WESTERN_PASS="pagofacil", WESTERN_UTILITY="90061234")
class TestWesternUnionAPIs(TestCase):
    def setUp(self):
        # 1. Create User
        self.user = User.objects.create_user(email="sales@olacredits.com", password="password123", role="salesperson")
        
        # 2. Create ProductCategory & Brand
        self.cat = ProductCategory.objects.create(name="Smartphones")
        self.brand = Brand.objects.create(name="Samsung", category=self.cat)
        
        # 3. Create Product
        self.product = ProductModel.objects.create(
            brand=self.brand,
            model_name="Galaxy S21",
            suggested_price=Decimal("400.00"),
            minimum_price_to_sell=Decimal("300.00")
        )
        
        # 4. Customer & Score
        self.customer = Customer.objects.create(document_number="8-000-000", first_name="John", last_name="Doe")
        self.score = CreditScore.objects.create(customer=self.customer, apc_score=700)
        self.app = CreditApplication.objects.create(customer=self.customer, sales_person=self.user, device_price=Decimal("400.00"))
        
        # Create FinanceMultiple required for 6 months and 30 days
        FinanceMultiple.objects.create(
            term_months=6,
            interval_days=30,
            multiple=Decimal("1.2"),
            is_active=True
        )

        self.plan = FinancePlan.objects.create(
            credit_application=self.app,
            credit_score=self.score,
            apc_score=700,
            risk_tier="TIER_A",
            minimum_down_payment_percentage=Decimal("20.00"),
            device=self.product,
            device_price=Decimal("400.00"),
            actual_down_payment=Decimal("80.00"),
            selected_term=6,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("2000.00"),
            created_by=self.user
        )

        # Clear auto-generated schedules to define our custom ones
        self.plan.emi_schedule.all().delete()

        # 5. Create some EMI schedules
        self.emi1 = EMISchedule.objects.create(
            finance_plan=self.plan,
            installment_number=1,
            due_date=date(2026, 6, 1),
            installment_amount=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
            balance_remaining=Decimal("100.00"),
            status="DUE"
        )
        self.emi2 = EMISchedule.objects.create(
            finance_plan=self.plan,
            installment_number=2,
            due_date=date(2026, 7, 1),
            installment_amount=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
            balance_remaining=Decimal("100.00"),
            status="UPCOMING"
        )

        from finance.signals import seed_default_accounting_codes
        seed_default_accounting_codes()
        from finance.models import Invoice, AccountingCode, BankAccount

        self.invoice1 = Invoice.objects.create(
            invoice_number="INV-WU-01",
            customer=self.customer,
            finance_plan=self.plan,
            emi_schedule=self.emi1,
            due_date=self.emi1.due_date,
            base_amount=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            balance=Decimal("100.00"),
            principal_amount=Decimal("100.00"),
            interest_amount=Decimal("0.00"),
            penalty_amount=Decimal("0.00"),
            status='PENDING'
        )
        self.invoice2 = Invoice.objects.create(
            invoice_number="INV-WU-02",
            customer=self.customer,
            finance_plan=self.plan,
            emi_schedule=self.emi2,
            due_date=self.emi2.due_date,
            base_amount=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            balance=Decimal("100.00"),
            principal_amount=Decimal("100.00"),
            interest_amount=Decimal("0.00"),
            penalty_amount=Decimal("0.00"),
            status='PENDING'
        )
        self.client = APIClient()

    def get_expected_barcode(self, obj):
        utility_str = "90061234"
        id_item_str = str(obj.id).zfill(21)
        monto_abierto_str = "0"
        
        balance = getattr(obj, "balance", getattr(obj, "balance_remaining", Decimal("100.00")))
        cents = int(round(balance * 100))
        importe_str = str(cents).zfill(11)
        
        due_date = obj.due_date
        aa = due_date.strftime("%y")
        jjj = f"{due_date.timetuple().tm_yday:03d}"
        julian_str = f"{aa}{jjj}"
        filler_str = "0" * 13
        return f"{utility_str}{id_item_str}{monto_abierto_str}{importe_str}{julian_str}{filler_str}"

    # ==========================================
    # VERIFY CUSTOMER TESTS
    # ==========================================
    def test_verify_customer_success(self):
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": "8-000-000"}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["tipo_operacion"] == "CashIn"
        assert data["cod_cliente"] == str(self.customer.id)
        assert data["cod_respuesta"] == "0"
        assert data["msg_respuesta"] == "Consulta exitosa"
        assert len(data["items"]) == 1
        assert data["items"][0]["id_item"] == str(self.invoice1.id)
        assert data["items"][0]["importe"] == "10000"

    def test_verify_customer_username_success(self):
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": "8-000-000"}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "username": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "0"

    def test_verify_customer_username_caps_success(self):
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": "8-000-000"}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "userName": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "0"

    def test_verify_customer_by_id_success(self):
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": str(self.customer.id)}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_cliente"] == str(self.customer.id)
        assert data["cod_respuesta"] == "0"

    def test_verify_customer_not_found(self):
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": "9-999-999"}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_cliente"] == ""
        assert data["cod_respuesta"] == "7"
        assert data["msg_respuesta"] == "Cliente no existe"

    def test_verify_customer_no_pending_emi(self):
        # Mark invoice1 as paid
        self.invoice1.status = "PAID"
        self.invoice1.amount_paid = Decimal("100.00")
        self.invoice1.balance = Decimal("0.00")
        self.invoice1.save()
        
        # Mark invoice2 as cancelled so there are no active pending invoices
        self.invoice2.status = "CANCELLED"
        self.invoice2.save()
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": "8-000-000"}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "6"
        assert data["msg_respuesta"] == "No existe registro"
        assert len(data["items"]) == 0

    def test_verify_customer_invalid_credentials(self):
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": "8-000-000"}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "user": "wrong_user",
            "password": "wrong_password"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "9"
        assert response.data["msg_respuesta"] == "Invalid credentials"

    # ==========================================
    # WESTERN UNION PAYMENT TESTS
    # ==========================================
    def test_payment_success(self):
        url = reverse("v2_finance_directa_create")
        barcode = self.get_expected_barcode(self.invoice1)
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": barcode,
            "utility": "90061234",
            "importe": "10000",  # 100.00
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "0"
        assert data["msg_respuesta"] == "Cobranza exitosa"
        
        # Verify database changes
        self.invoice1.refresh_from_db()
        assert self.invoice1.status == "PAID"
        assert self.invoice1.amount_paid == Decimal("100.00")
        assert self.invoice1.balance == Decimal("0.00")
        
        # Verify payment record is created
        assert PaymentRecord.objects.filter(
            transaction_reference="D00561202605261020001125",
            payment_amount=Decimal("100.00"),
            payment_status="COMPLETED"
        ).exists()

    def test_payment_partial_rejected_for_closed_amounts(self):
        url = reverse("v2_finance_directa_create")
        barcode = self.get_expected_barcode(self.invoice1)
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": barcode,
            "utility": "90061234",
            "importe": "4500",  # 45.00 (not 100.00)
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "5"
        assert "must exactly match" in data["msg_respuesta"]

    def test_payment_duplicate_protection(self):
        # Register a completed transaction
        PaymentRecord.objects.create(
            finance_plan=self.plan,
            emi_schedule=self.emi1,
            payment_type="EMI",
            payment_method="WESTERN_UNION",
            payment_amount=Decimal("100.00"),
            payment_date=timezone.now(),
            payment_status="COMPLETED",
            transaction_reference="D00561202605261020001125"
        )
        
        url = reverse("v2_finance_directa_create")
        barcode = self.get_expected_barcode(self.invoice1)
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": barcode,
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "0"
        assert "already processed" in response.data["msg_respuesta"]

    def test_payment_barcode_validation_failure(self):
        url = reverse("v2_finance_directa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": "INVALID_BARCODE",
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "9"
        assert "Barcode validation failed" in response.data["msg_respuesta"]

    def test_payment_customer_validation_failure(self):
        url = reverse("v2_finance_directa_create")
        barcode = self.get_expected_barcode(self.invoice1)
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": "99999", # wrong customer id
            "cod_operacion": "D",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": barcode,
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "9"
        assert "Customer validation failed" in response.data["msg_respuesta"]

    def test_payment_utility_validation_failure(self):
        url = reverse("v2_finance_directa_create")
        barcode = self.get_expected_barcode(self.invoice1)
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": barcode,
            "utility": "88888888", # wrong utility
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "9"
        assert "Invalid utility" in response.data["msg_respuesta"]

    def test_payment_emi_not_found(self):
        url = reverse("v2_finance_directa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": "99999",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": "90061234000232500005656500",
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "9"
        assert "not found" in data["msg_respuesta"]

    # ==========================================
    # REVERSAL TESTS
    # ==========================================
    def test_reversal_success(self):
        # First process payment successfully
        url_pay = reverse("v2_finance_directa_create")
        barcode = self.get_expected_barcode(self.invoice1)
        payload_pay = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": barcode,
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        res_pay = self.client.post(url_pay, payload_pay, format="json")
        assert res_pay.status_code == status.HTTP_200_OK
        
        # Verify payment created and completed
        payment = PaymentRecord.objects.get(transaction_reference="D00561202605261020001125")
        assert payment.payment_status == "COMPLETED"
        assert self.emi1.amount_paid == Decimal("0.00") # Need to refresh first
        self.emi1.refresh_from_db()
        assert self.emi1.amount_paid == Decimal("100.00")
        assert self.emi1.status == "PAID"

        # Now call reversal
        url_rev = reverse("v2_finance_reversa_create")
        payload_rev = payload_pay.copy()
        payload_rev["cod_operacion"] = "R"
        response = self.client.post(url_rev, payload_rev, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "0"
        assert "Reversa exitosa" in response.data["msg_respuesta"]

        # Verify database reverted
        payment.refresh_from_db()
        assert payment.payment_status == "REVERSED"
        self.emi1.refresh_from_db()
        assert self.emi1.amount_paid == Decimal("0.00")
        assert self.emi1.status == "OVERDUE"

    def test_reversal_already_reversed(self):
        # Setup payment record as REVERSED
        PaymentRecord.objects.create(
            finance_plan=self.plan,
            emi_schedule=self.emi1,
            payment_type="EMI",
            payment_method="WESTERN_UNION",
            payment_amount=Decimal("100.00"),
            payment_date=timezone.now(),
            payment_status="REVERSED",
            transaction_reference="D00561202605261020001125"
        )
        
        url_rev = reverse("v2_finance_reversa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "R",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": self.get_expected_barcode(self.invoice1),
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url_rev, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "0"
        assert "already reversed" in response.data["msg_respuesta"]

    def test_reversal_payment_not_found(self):
        url_rev = reverse("v2_finance_reversa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "R",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "NON_EXISTENT_TRX",
            "cod_barra": self.get_expected_barcode(self.invoice1),
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url_rev, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "9"
        assert "record not found" in response.data["msg_respuesta"]

    def test_reversal_wrong_credentials(self):
        url_rev = reverse("v2_finance_reversa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "R",
            "id_item": str(self.invoice1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": self.get_expected_barcode(self.invoice1),
            "utility": "90061234",
            "importe": "10000",
            "medio_pago": "E01",
            "user": "wrong_user",
            "password": "wrong_password"
        }
        response = self.client.post(url_rev, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "9"
        assert "Invalid credentials" in response.data["msg_respuesta"]

    def test_host_bypass_for_western_union_endpoints(self):
        # Verify that requesting a Western Union endpoint with a disallowed host header works (bypassed by middleware)
        url = reverse("v2_finance_verify-customer_create")
        payload = {
            "tipo_operacion": "CashIn",
            "campos_busqueda": [
                {"campo1": "8-000-000"}
            ],
            "utility": "90061234",
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "101940",
            "cod_operacion": "C",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json", HTTP_HOST="unauthorized-domain.com")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["cod_respuesta"] == "0"

        # Verify that requesting a different endpoint with a disallowed host header is rejected with 400 Bad Request
        url_other = reverse("finance-auto-plan")
        response_other = self.client.get(url_other, HTTP_HOST="unauthorized-domain.com")
        assert response_other.status_code == status.HTTP_400_BAD_REQUEST


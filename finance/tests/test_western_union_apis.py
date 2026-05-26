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

@override_settings(WESTERN_USER="pagofacil", WESTERN_PASS="pagofacil")
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
        self.client = APIClient()

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
        assert data["items"][0]["id_item"] == str(self.emi1.id)
        # Importe is 100.00 * 100 = 10000
        assert data["items"][0]["importe"] == "10000"

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
        # Mark emi1 as paid, and emi2 is UPCOMING
        self.emi1.status = "PAID"
        self.emi1.amount_paid = Decimal("100.00")
        self.emi1.balance_remaining = Decimal("0.00")
        self.emi1.save()
        
        # Verify customer should not return emi2 because it is UPCOMING, only DUE, OVERDUE, PARTIALLY_PAID
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
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # ==========================================
    # WESTERN UNION PAYMENT TESTS
    # ==========================================
    def test_payment_success(self):
        url = reverse("v2_finance_directa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.emi1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": "90061234000232500005656500",
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
        self.emi1.refresh_from_db()
        assert self.emi1.status == "PAID"
        assert self.emi1.amount_paid == Decimal("100.00")
        assert self.emi1.balance_remaining == Decimal("0.00")
        
        # Verify payment record is created
        assert PaymentRecord.objects.filter(
            transaction_reference="D00561202605261020001125",
            payment_amount=Decimal("100.00")
        ).exists()

    def test_payment_partial_success(self):
        url = reverse("v2_finance_directa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.emi1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": "90061234000232500005656500",
            "utility": "90061234",
            "importe": "4500",  # 45.00
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "0"
        
        self.emi1.refresh_from_db()
        assert self.emi1.status == "PARTIALLY_PAID"
        assert self.emi1.amount_paid == Decimal("45.00")
        assert self.emi1.balance_remaining == Decimal("55.00")

    def test_payment_overpayment_rejected(self):
        url = reverse("v2_finance_directa_create")
        payload = {
            "tipo_operacion": "CashIn",
            "cod_cliente": str(self.customer.id),
            "cod_operacion": "D",
            "id_item": str(self.emi1.id),
            "terminal": "D00561",
            "fecha": "20260526",
            "hora": "102000",
            "secuencia": "1125",
            "cod_trx": "D00561202605261020001125",
            "cod_barra": "90061234000232500005656500",
            "utility": "90061234",
            "importe": "10500",  # 105.00 > 100.00
            "medio_pago": "E01",
            "user": "pagofacil",
            "password": "pagofacil"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["cod_respuesta"] == "5"
        assert "exceeds pending" in data["msg_respuesta"]

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

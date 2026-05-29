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

@override_settings(PUNTO_PAGO_API_KEY="test_punto_pago_secret")
class TestPuntoPagoAPIs(TestCase):
    def setUp(self):
        # 1. Create User
        self.user = User.objects.create_user(
            email="sales_pp@olacredits.com", 
            password="password123", 
            role="salesperson"
        )
        
        # 2. Create ProductCategory & Brand
        self.cat = ProductCategory.objects.create(name="Smartphones PP")
        self.brand = Brand.objects.create(name="Apple", category=self.cat)
        
        # 3. Create Product
        self.product = ProductModel.objects.create(
            brand=self.brand,
            model_name="iPhone 15",
            suggested_price=Decimal("800.00"),
            minimum_price_to_sell=Decimal("700.00")
        )
        
        # 4. Customer & Score
        self.customer = Customer.objects.create(
            document_number="8-123-456", 
            first_name="John", 
            last_name="Doe"
        )
        self.score = CreditScore.objects.create(
            customer=self.customer, 
            apc_score=750
        )
        self.app = CreditApplication.objects.create(
            customer=self.customer, 
            sales_person=self.user, 
            device_price=Decimal("800.00")
        )
        
        # Create FinanceMultiple required for 6 months and 30 days
        FinanceMultiple.objects.create(
            term_months=6,
            interval_days=30,
            multiple=Decimal("1.0"),
            is_active=True
        )

        self.plan = FinancePlan.objects.create(
            credit_application=self.app,
            credit_score=self.score,
            apc_score=750,
            risk_tier="TIER_A",
            minimum_down_payment_percentage=Decimal("20.00"),
            device=self.product,
            device_price=Decimal("800.00"),
            actual_down_payment=Decimal("200.00"),
            selected_term=6,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("3000.00"),
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
        self.auth_headers = {
            "HTTP_AUTHORIZATION": "Bearer test_punto_pago_secret"
        }

    # ==========================================
    # HEALTH CHECK TEST
    # ==========================================
    def test_health_check(self):
        url = reverse("puntopago_health")
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"status": "UP"}

    # ==========================================
    # ACCOUNT VERIFY TESTS
    # ==========================================
    def test_verify_customer_success(self):
        url = reverse("puntopago_account_verify")
        payload = {
            "identification": "8-123-456"
        }
        response = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["success"] is True
        assert data["customer_name"] == "John Doe"
        assert data["identification"] == "8-123-456"
        # Total debt is 100 (emi1) + 100 (emi2) = 200.0
        assert data["current_debt"] == 200.0

    def test_verify_customer_not_found(self):
        url = reverse("puntopago_account_verify")
        payload = {
            "identification": "9-999-999"
        }
        response = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data["success"] is False

    def test_verify_customer_invalid_auth(self):
        url = reverse("puntopago_account_verify")
        payload = {
            "identification": "8-123-456"
        }
        # Wrong secret
        bad_headers = {"HTTP_AUTHORIZATION": "Bearer wrong_secret"}
        response = self.client.post(url, payload, format="json", **bad_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Missing auth
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    # ==========================================
    # PAYMENT PROCESS TESTS
    # ==========================================
    def test_payment_process_exact_emi_success(self):
        url = reverse("puntopago_payment_process")
        payload = {
            "identification": "8-123-456",
            "payment_reference": "PP-20260530-999",
            "amount": "100.00"
        }
        response = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["success"] is True
        assert data["status"] == "PAID"
        assert data["payment_id"].startswith("PAY-")

        # Verify DB states
        self.emi1.refresh_from_db()
        assert self.emi1.status == "PAID"
        assert self.emi1.amount_paid == Decimal("100.00")
        assert self.emi1.balance_remaining == Decimal("0.00")

        self.emi2.refresh_from_db()
        assert self.emi2.status == "UPCOMING"
        assert self.emi2.amount_paid == Decimal("0.00")

        # Verify Payment Record exists
        assert PaymentRecord.objects.filter(
            transaction_reference="PP-20260530-999",
            payment_amount=Decimal("100.00"),
            payment_method="PUNTO_PAGO"
        ).exists()

    def test_payment_process_excess_allocation(self):
        url = reverse("puntopago_payment_process")
        payload = {
            "identification": "8-123-456",
            "payment_reference": "PP-20260530-888",
            "amount": "150.00"
        }
        response = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response.status_code == status.HTTP_200_OK
        
        self.emi1.refresh_from_db()
        assert self.emi1.status == "PAID"
        
        self.emi2.refresh_from_db()
        # Should get 50.00 allocated, making it partially paid
        assert self.emi2.status == "PARTIALLY_PAID"
        assert self.emi2.amount_paid == Decimal("50.00")
        assert self.emi2.balance_remaining == Decimal("50.00")

    def test_payment_process_idempotency(self):
        url = reverse("puntopago_payment_process")
        payload = {
            "identification": "8-123-456",
            "payment_reference": "PP-20260530-777",
            "amount": "100.00"
        }
        # First call
        response1 = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response1.status_code == status.HTTP_200_OK
        pay_id_1 = response1.data["payment_id"]

        # Second call
        response2 = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response2.status_code == status.HTTP_200_OK
        pay_id_2 = response2.data["payment_id"]

        # IDs should match and not create duplicate records
        assert pay_id_1 == pay_id_2
        assert PaymentRecord.objects.filter(transaction_reference="PP-20260530-777").count() == 1

    # ==========================================
    # PAYMENT STATUS TESTS
    # ==========================================
    def test_payment_status_success(self):
        # Create a payment record first
        payment = PaymentRecord.objects.create(
            finance_plan=self.plan,
            emi_schedule=self.emi1,
            payment_type="EMI",
            payment_method="PUNTO_PAGO",
            payment_amount=Decimal("100.00"),
            payment_date=timezone.now(),
            payment_status="COMPLETED",
            transaction_reference="PP-STATUS-TEST"
        )
        
        url = reverse("puntopago_payment_status", kwargs={"payment_id": f"PAY-{payment.id}"})
        response = self.client.get(url, **self.auth_headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            "payment_id": f"PAY-{payment.id}",
            "status": "PAID"
        }

    def test_payment_status_not_found(self):
        url = reverse("puntopago_payment_status", kwargs={"payment_id": "PAY-999999"})
        response = self.client.get(url, **self.auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_payment_create_with_payment_method(self):
        url = reverse("payments-record")
        payload = {
            "finance_plan": self.plan.id,
            "payment_type": "EMI",
            "payment_amount": "100.00",
            "payment_method": "YAPPY",
            "transaction_reference": "TEST-YAPPY-123"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] == "success"
        assert response.data["data"]["payment_method"] == "YAPPY"
        
        payment_id = int(response.data["data"]["id"])
        payment = PaymentRecord.objects.get(id=payment_id)
        assert payment.payment_method == "YAPPY"

    def test_payment_create_default_payment_method(self):
        url = reverse("payments-record")
        payload = {
            "finance_plan": self.plan.id,
            "payment_type": "EMI",
            "payment_amount": "50.00",
            "transaction_reference": "TEST-CASH-123"
        }
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] == "success"
        assert response.data["data"]["payment_method"] == "CASH"

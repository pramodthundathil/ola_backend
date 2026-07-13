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

        # Seed default accounting codes
        from finance.signals import seed_default_accounting_codes
        seed_default_accounting_codes()

        # Retrieve/create BankAccount for tests matching settings
        from django.conf import settings
        from finance.models import BankAccount, Invoice, LedgerEntry, PaymentReceived
        pp_bank_acc_num = getattr(settings, 'PUNTO_PAGO_BANK_ACCOUNT_NUMBER', '1234567890')
        BankAccount.objects.get_or_create(
            account_number=pp_bank_acc_num,
            defaults={
                "bank_name": "Test Punto Pago Bank",
                "account_holder_name": "Ola Credit",
                "initial_balance": Decimal('0.00'),
                "status": "ACTIVE",
                "account_name": "Punto Pago Account"
            }
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

        # 6. Create Invoices for emi1 and emi2
        self.invoice1 = Invoice.objects.create(
            invoice_number="OLA-EMI-000001",
            customer=self.customer,
            finance_plan=self.plan,
            emi_schedule=self.emi1,
            due_date=self.emi1.due_date,
            base_amount=self.emi1.installment_amount,
            subtotal=self.emi1.installment_amount,
            tax_amount=Decimal("0.00"),
            total_amount=self.emi1.installment_amount,
            balance=self.emi1.installment_amount,
            principal_amount=self.emi1.installment_amount,
            status="PENDING"
        )
        self.invoice2 = Invoice.objects.create(
            invoice_number="OLA-EMI-000002",
            customer=self.customer,
            finance_plan=self.plan,
            emi_schedule=self.emi2,
            due_date=self.emi2.due_date,
            base_amount=self.emi2.installment_amount,
            subtotal=self.emi2.installment_amount,
            tax_amount=Decimal("0.00"),
            total_amount=self.emi2.installment_amount,
            balance=self.emi2.installment_amount,
            principal_amount=self.emi2.installment_amount,
            status="PENDING"
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

    def test_payment_process_exceeds_total_debt(self):
        url = reverse("puntopago_payment_process")
        payload = {
            "identification": "8-123-456",
            "payment_reference": "PP-20260530-EXCEED",
            "amount": "250.00"
        }
        response = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False
        assert "exceeds" in response.data["message"]

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

    def test_payment_process_bank_account_ledger(self):
        from finance.models import PaymentReceived, LedgerEntry, BankAccount
        from django.conf import settings

        url = reverse("puntopago_payment_process")
        payload = {
            "identification": "8-123-456",
            "payment_reference": "PP-LEDGER-TEST-789",
            "amount": "100.00"
        }
        response = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["success"] is True

        # Verify PaymentReceived was created
        payment_received = PaymentReceived.objects.filter(
            transaction_reference="PP-LEDGER-TEST-789",
            payment_method="PUNTO_PAGO"
        ).first()
        assert payment_received is not None
        assert payment_received.amount_received == Decimal("100.00")

        # Verify BankAccount matching settings was resolved
        pp_bank_acc_num = getattr(settings, 'PUNTO_PAGO_BANK_ACCOUNT_NUMBER', '1234567890')
        bank_account = BankAccount.objects.get(account_number=pp_bank_acc_num)
        
        # Verify LedgerEntry (Debit to Bank Account Accounting Code)
        debit_ledger = LedgerEntry.objects.filter(
            payment_received=payment_received,
            accounting_code=bank_account.accounting_code,
            type="DEBIT"
        ).first()
        assert debit_ledger is not None
        assert debit_ledger.amount == Decimal("100.00")
        assert "PUNTO_PAGO" in debit_ledger.description
        assert "PP-LEDGER-TEST-789" in debit_ledger.description

    def test_payment_process_dynamic_bank_account(self):
        from finance.models import PaymentReceived, LedgerEntry, BankAccount, EMIConfiguration
        from django.conf import settings

        # 1. Create a different bank account to be linked dynamically
        dynamic_bank = BankAccount.objects.create(
            bank_name="Dynamic Settlement Bank",
            account_number="9876543210",
            account_holder_name="Ola Credit Dynamic",
            initial_balance=Decimal('0.00'),
            status="ACTIVE",
            account_name="Punto Pago Dynamic Account"
        )

        # 2. Link this dynamic bank account in EMIConfiguration
        emi_config = EMIConfiguration.objects.filter(is_active=True).first()
        if not emi_config:
            emi_config = EMIConfiguration.objects.create(is_active=True)
        emi_config.punto_pago_bank_account = dynamic_bank
        emi_config.save()

        # 3. Call payment process API
        url = reverse("puntopago_payment_process")
        payload = {
            "identification": "8-123-456",
            "payment_reference": "PP-DYNAMIC-TEST-101",
            "amount": "100.00"
        }
        response = self.client.post(url, payload, format="json", **self.auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["success"] is True

        # 4. Verify PaymentReceived was created
        payment_received = PaymentReceived.objects.filter(
            transaction_reference="PP-DYNAMIC-TEST-101",
            payment_method="PUNTO_PAGO"
        ).first()
        assert payment_received is not None

        # 5. Verify LedgerEntry was debited to the dynamic bank account's accounting code
        debit_ledger = LedgerEntry.objects.filter(
            payment_received=payment_received,
            accounting_code=dynamic_bank.accounting_code,
        type="DEBIT"
        ).first()
        assert debit_ledger is not None
        assert debit_ledger.amount == Decimal("100.00")
        assert "PP-DYNAMIC-TEST-101" in debit_ledger.description

    def test_customer_advance_adjustment(self):
        from finance.models import PaymentReceived, LedgerEntry, AccountingCode, BankAccount, Invoice
        from django.urls import reverse

        # 1. Verify initial advance balance is 0
        assert self.customer.advance_balance == Decimal("0.00")

        # 2. Get bank account accounting code
        bank_acc = BankAccount.objects.first()
        dep_code = bank_acc.accounting_code

        # 3. Create a PaymentReceived that has excess amount (creating an advance)
        url = reverse("payment-received-list-create")
        payload = {
            "customer_id": self.customer.id,
            "amount_received": "150.00",
            "payment_method": "CASH",
            "deposited_to": dep_code.id,
            "invoices": [
                {
                    "invoice_id": self.invoice1.id,
                    "amount_applied": "100.00"
                }
            ]
        }
        
        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED

        # 4. Check advance balance is 50.00
        self.customer.refresh_from_db()
        assert self.customer.advance_balance == Decimal("50.00")

        # 5. Check InvoiceSerializer returns customer_advance_balance
        from django.contrib.auth import get_user_model
        User = get_user_model()
        manager = User.objects.create_user(
            email="manager@olacredits.com",
            password="password123",
            role="financial_manager"
        )
        self.client.force_authenticate(user=manager)
        detail_url = reverse("invoices-detail", kwargs={"pk": self.invoice2.id})
        detail_response = self.client.get(detail_url)
        assert detail_response.status_code == status.HTTP_200_OK
        assert detail_response.data["customer_advance_balance"] == 50.0
        # Clean up authentication for subsequent requests
        self.client.force_authenticate(user=None)

        # 6. Pay invoice2 using 70.00 cash + 30.00 advance
        payload2 = {
            "customer_id": self.customer.id,
            "amount_received": "70.00",
            "advance_applied": "30.00",
            "payment_method": "CASH",
            "deposited_to": dep_code.id,
            "invoices": [
                {
                    "invoice_id": self.invoice2.id,
                    "amount_applied": "100.00"
                }
            ]
        }
        
        response2 = self.client.post(url, payload2, format="json")
        assert response2.status_code == status.HTTP_201_CREATED

        # 7. Check advance balance decreases to 20.00
        assert self.customer.advance_balance == Decimal("20.00")

        # 8. Check invoice2 is fully PAID
        self.invoice2.refresh_from_db()
        assert self.invoice2.status == "PAID"
        assert self.invoice2.balance == Decimal("0.00")
        assert self.invoice2.amount_paid == Decimal("100.00")

        # 9. Verify ledger entries for advance DEBIT and receivable CREDIT
        latest_payment = PaymentReceived.objects.order_by("-id").first()
        assert latest_payment.advance_applied == Decimal("30.00")

        debit_advance = LedgerEntry.objects.filter(
            payment_received=latest_payment,
            accounting_code__code="2200",
            type="DEBIT"
        ).first()
        assert debit_advance is not None
        assert debit_advance.amount == Decimal("30.00")

        credit_receivable = LedgerEntry.objects.filter(
            payment_received=latest_payment,
            accounting_code__code="1200",
            type="CREDIT"
        ).first()
        assert credit_receivable is not None
        assert credit_receivable.amount == Decimal("100.00")

        # 10. Attempt to apply advance that exceeds remaining (apply 30.00 when only 20.00 remains)
        payload3 = {
            "customer_id": self.customer.id,
            "amount_received": "0.00",
            "advance_applied": "30.00",
            "payment_method": "CASH",
            "deposited_to": dep_code.id,
            "invoices": [
                {
                    "invoice_id": self.invoice1.id,
                    "amount_applied": "30.00"
                }
            ]
        }
        
        response3 = self.client.post(url, payload3, format="json")
        assert response3.status_code == status.HTTP_400_BAD_REQUEST
        assert "exceeds" in response3.data["error"]

        # 11. Test that string-based invoice_id is correctly parsed and reflected in the serializer
        payload4 = {
            "customer_id": self.customer.id,
            "amount_received": "10.00",
            "advance_applied": "10.00",
            "payment_method": "CASH",
            "deposited_to": dep_code.id,
            "invoices": [
                {
                    "invoice_id": str(self.invoice1.id), # string ID!
                    "amount_applied": "20.00"
                }
            ]
        }
        
        response4 = self.client.post(url, payload4, format="json")
        assert response4.status_code == status.HTTP_201_CREATED
        
        latest_payment_id = PaymentReceived.objects.order_by("-id").first().id
        detail_url2 = reverse("payment-received-detail", kwargs={"pk": latest_payment_id})
        self.client.force_authenticate(user=manager)
        detail_response2 = self.client.get(detail_url2)
        assert detail_response2.status_code == status.HTTP_200_OK
        assert len(detail_response2.data["invoice_details"]) == 1
        assert detail_response2.data["invoice_details"][0]["id"] == self.invoice1.id
        self.client.force_authenticate(user=None)

    def test_customer_serializer_advance_balance(self):
        from customer.serializers import CustomerSerializer
        from decimal import Decimal
        # Initially 0.0
        serializer = CustomerSerializer(self.customer)
        assert serializer.data["advance_balance"] == 0.0

        # Create LedgerEntry under customer to establish positive advance
        from finance.models import LedgerEntry, AccountingCode, PaymentReceived
        dep_code = AccountingCode.objects.filter(category="ASSET").first()
        payment = PaymentReceived.objects.create(
            payment_number="REC-10022",
            customer=self.customer,
            amount_received=Decimal("150.00"),
            payment_date=timezone.now(),
            payment_method="CASH",
            deposited_to=dep_code,
            invoices=[]
        )
        
        # Credit to 2200 (Customer Advance)
        advance_code = AccountingCode.objects.filter(code="2200").first()
        LedgerEntry.objects.create(
            payment_received=payment,
            accounting_code=advance_code,
            type="CREDIT",
            amount=Decimal("150.00"),
            description="Advance received",
            entry_date=timezone.now()
        )

        # Re-check advance_balance serialization
        self.customer.refresh_from_db()
        serializer2 = CustomerSerializer(self.customer)
        assert serializer2.data["advance_balance"] == 150.0

    def test_create_payment_no_invoices(self):
        from django.urls import reverse
        from finance.models import BankAccount, LedgerEntry, PaymentReceived

        # 1. Start with 0.00 advance
        assert self.customer.advance_balance == 0.0

        # 2. Get bank account accounting code
        bank_acc = BankAccount.objects.first()
        dep_code = bank_acc.accounting_code

        # 3. Create a payment received with no invoices
        url = reverse("payment-received-list-create")
        payload = {
            "customer_id": self.customer.id,
            "amount_received": "200.00",
            "payment_method": "CASH",
            "deposited_to": dep_code.id,
            "invoices": []
        }

        response = self.client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED

        # 4. Advance balance should now be 200.00
        self.customer.refresh_from_db()
        assert self.customer.advance_balance == 200.00

        # 5. Ledger entries should show 200 DEBIT to cash/bank and 200 CREDIT to advance code
        latest_payment = PaymentReceived.objects.order_by("-id").first()
        assert latest_payment.amount_received == Decimal("200.00")
        
        debit_cash = LedgerEntry.objects.filter(
            payment_received=latest_payment,
            accounting_code=dep_code,
            type="DEBIT"
        ).first()
        assert debit_cash is not None
        assert debit_cash.amount == Decimal("200.00")

        credit_advance = LedgerEntry.objects.filter(
            payment_received=latest_payment,
            accounting_code__code="2200",
            type="CREDIT"
        ).first()
        assert credit_advance is not None
        assert credit_advance.amount == Decimal("200.00")

    def test_apply_existing_advance(self):
        from django.urls import reverse
        from finance.models import BankAccount, LedgerEntry, PaymentReceived, Invoice

        # 1. Create a payment received with no invoices (Generating $200 customer advance balance)
        bank_acc = BankAccount.objects.first()
        dep_code = bank_acc.accounting_code
        
        url = reverse("payment-received-list-create")
        payload = {
            "customer_id": self.customer.id,
            "amount_received": "200.00",
            "payment_method": "CASH",
            "deposited_to": dep_code.id,
            "invoices": []
        }
        res = self.client.post(url, payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        advance_payment = PaymentReceived.objects.order_by("-id").first()
        assert advance_payment.unused_advance_balance == Decimal("200.00")

        # 2. Allocate $80 from this advance payment to self.invoice1 (balance $100)
        # Using apply_advance_from_payment_id parameter
        payload2 = {
            "customer_id": self.customer.id,
            "amount_received": "0.00",
            "advance_applied": "80.00",
            "payment_method": "CASH",
            "apply_advance_from_payment_id": advance_payment.id,
            "invoices": [
                {
                    "invoice_id": self.invoice1.id,
                    "amount_applied": "80.00"
                }
            ]
        }
        res2 = self.client.post(url, payload2, format="json")
        assert res2.status_code == status.HTTP_201_CREATED

        # 3. Verify no new payment received was created, and old payment is updated
        advance_payment.refresh_from_db()
        assert advance_payment.unused_advance_balance == Decimal("120.00")
        assert advance_payment.advance_applied == Decimal("80.00")
        
        # Verify invoice balance is updated
        self.invoice1.refresh_from_db()
        assert self.invoice1.amount_paid == Decimal("80.00")
        assert self.invoice1.balance == Decimal("20.00")
        
        # Verify ledger entries are correctly created under the existing payment
        # Debit Customer Advance (2200): $80
        # Credit Accounts Receivable (1200) or EMI Receivable: $80
        debit_advance = LedgerEntry.objects.filter(
            payment_received=advance_payment,
            accounting_code__code="2200",
            type="DEBIT"
        ).first()
        assert debit_advance is not None
        assert debit_advance.amount == Decimal("80.00")



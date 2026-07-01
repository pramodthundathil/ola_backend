import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from customer.models import Customer, CreditApplication, CreditScore, CreditConfig
from finance.models import FinancePlan, EMISchedule, AutoFinancePlan, FinanceMultiple
from decimal import Decimal
from unittest.mock import patch

User = get_user_model()

@pytest.mark.django_db
class TestDraftAndActivePlanLogic:
    @pytest.fixture
    def setup_data(self):
        user = User.objects.create_user(email="salesadvisor@example.com", password="password123", role="salesperson")
        customer = Customer.objects.create(
            document_number="8-999-999",
            document_type="PANAMA_ID",
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            phone_number="6666-6666",
            created_by=user,
            otp_verified=True # initially set to verified
        )
        credit_score = CreditScore.objects.create(customer=customer, apc_score=600, is_expired=False)
        credit_app = CreditApplication.objects.create(customer=customer, sales_person=user, status="PRE_QUALIFIED")
        auto_plan = AutoFinancePlan.objects.create(
            credit_application=credit_app,
            credit_score=credit_score,
            customer=customer,
            apc_score=600,
            customer_monthly_income=Decimal("1500.00"),
            payment_capacity_factor=Decimal("0.20"),
            maximum_allowed_installment=Decimal("200.00"),
            minimum_down_payment_percentage=Decimal("20.00"),
            allowed_plans=[]
        )
        # Setup required FinanceMultiple records
        FinanceMultiple.objects.create(term_months=6, interval_days=30, multiple=Decimal("1.2"), is_active=True)
        FinanceMultiple.objects.create(term_months=8, interval_days=15, multiple=Decimal("1.3"), is_active=True)

        # Setup one CreditConfig if not exists
        if not CreditConfig.objects.exists():
            CreditConfig.objects.create(
                tier_a_min_score=600,
                tier_b_min_score=550,
                tier_c_min_score=500
            )

        return {
            "user": user,
            "customer": customer,
            "credit_app": credit_app,
            "auto_plan": auto_plan
        }

    def test_save_and_retrieve_draft_data(self, setup_data):
        client = APIClient()
        client.force_authenticate(user=setup_data["user"])

        # Test 1: Save Step Progress with draft_data
        step_url = reverse("credit-app-step")
        draft_payload = {
            "application_id": setup_data["credit_app"].id,
            "current_step": 5,
            "draft_data": {
                "selectedDevice": {"id": 1, "model_name": "Galaxy S24"},
                "insurance": 10,
                "emiPlans": []
            }
        }
        res = client.post(step_url, draft_payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "success"
        assert res.data["data"]["current_step"] == 5
        assert res.data["data"]["draft_data"]["selectedDevice"]["model_name"] == "Galaxy S24"

        # Test 2: Retrieve via Customer Lookup (CustomerManagementView POST)
        # Verify otp_verified remains True since credit application is in progress
        lookup_url = reverse("customer-manage")
        lookup_payload = {
            "document_type": "PANAMA_ID",
            "document_number": "8-999-999"
        }
        res2 = client.post(lookup_url, lookup_payload, format="json")
        assert res2.status_code == status.HTTP_200_OK
        assert res2.data["draft_data"]["selectedDevice"]["model_name"] == "Galaxy S24"
        assert res2.data["has_active_plan"] is False
        
        # Verify customer's otp_verified flag is still True
        setup_data["customer"].refresh_from_db()
        assert setup_data["customer"].otp_verified is True

    def test_active_plan_detection(self, setup_data):
        client = APIClient()
        client.force_authenticate(user=setup_data["user"])

        # Create active plan (which triggers signal receiver to generate EMISchedules)
        plan = FinancePlan.objects.create(
            credit_application=setup_data["credit_app"],
            credit_score=setup_data["credit_app"].customer.credit_scores.first(),
            apc_score=600,
            risk_tier="TIER_A",
            device_price=Decimal("500.00"),
            actual_down_payment=Decimal("100.00"),
            selected_term=6,
            installment_frequency_days=30,
            monthly_installment=Decimal("70.00"),
            total_amount_payable=Decimal("520.00"),
            customer_monthly_income=Decimal("1500.00"),
            payment_capacity_factor=Decimal("0.20"),
            maximum_allowed_installment=Decimal("300.00"),
            minimum_down_payment_percentage=Decimal("20.00"),
            amount_to_finance=Decimal("400.00"),
            created_by=setup_data["user"],
            status="ACTIVE"
        )

        lookup_url = reverse("customer-manage")
        lookup_payload = {
            "document_type": "PANAMA_ID",
            "document_number": "8-999-999"
        }
        
        # Scenario 1: Plan is ACTIVE with unpaid installments
        res = client.post(lookup_url, lookup_payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["has_active_plan"] is True

        # Scenario 2: All installments paid off
        EMISchedule.objects.filter(finance_plan=plan).update(status="PAID")
        res_paid = client.post(lookup_url, lookup_payload, format="json")
        assert res_paid.status_code == status.HTTP_200_OK
        assert res_paid.data["has_active_plan"] is False

        # Scenario 3: Application is finalized (APPROVED), should not resume
        setup_data["credit_app"].status = "APPROVED"
        setup_data["credit_app"].save()
        res_finalized = client.post(lookup_url, lookup_payload, format="json")
        assert res_finalized.status_code == status.HTTP_200_OK
        assert res_finalized.data["application_id"] is None
        assert res_finalized.data["current_step"] == 0

    def test_draft_repayments_schedule_replacement(self, setup_data):
        # Create draft plan (will trigger signal receiver to generate EMISchedules)
        plan = FinancePlan.objects.create(
            credit_application=setup_data["credit_app"],
            credit_score=setup_data["credit_app"].customer.credit_scores.first(),
            apc_score=600,
            risk_tier="TIER_A",
            device_price=Decimal("500.00"),
            actual_down_payment=Decimal("100.00"),
            selected_term=6,
            installment_frequency_days=30,
            monthly_installment=Decimal("70.00"),
            total_amount_payable=Decimal("520.00"),
            customer_monthly_income=Decimal("1500.00"),
            payment_capacity_factor=Decimal("0.20"),
            maximum_allowed_installment=Decimal("300.00"),
            minimum_down_payment_percentage=Decimal("20.00"),
            amount_to_finance=Decimal("400.00"),
            created_by=setup_data["user"],
            status="DRAFT"
        )

        # Initial schedule count should match selected_term (6 months frequency 30 -> 6 installments)
        assert EMISchedule.objects.filter(finance_plan=plan).count() == 6

        # Update draft plan (e.g. term = 8 months, frequency = 15 -> 16 installments)
        plan.selected_term = 8
        plan.installment_frequency_days = 15
        plan.save()

        # The signal should delete old 6 installments and regenerate 16 new installments
        assert EMISchedule.objects.filter(finance_plan=plan).count() == 16

    def test_dynamic_agreement_template_substitutions(self, setup_data):
        client = APIClient()
        client.force_authenticate(user=setup_data["user"])

        # 1. Update template in CreditConfig
        config = CreditConfig.objects.first()
        config.loan_agreement_template = "Hello {first_name} {last_name}, your Cedula ID is {cedula}."
        config.save()

        # 2. Create a FinancePlan to test placeholders
        plan = FinancePlan.objects.create(
            credit_application=setup_data["credit_app"],
            credit_score=setup_data["credit_app"].customer.credit_scores.first(),
            apc_score=600,
            risk_tier="TIER_A",
            device_price=Decimal("500.00"),
            actual_down_payment=Decimal("100.00"),
            selected_term=6,
            installment_frequency_days=30,
            monthly_installment=Decimal("70.00"),
            total_amount_payable=Decimal("520.00"),
            customer_monthly_income=Decimal("1500.00"),
            payment_capacity_factor=Decimal("0.20"),
            maximum_allowed_installment=Decimal("300.00"),
            minimum_down_payment_percentage=Decimal("20.00"),
            amount_to_finance=Decimal("400.00"),
            created_by=setup_data["user"],
            status="DRAFT"
        )

        from finance.services import ContractService
        text = ContractService.generate_loan_agreement(plan)
        assert text == "Hello John Doe, your Cedula ID is 8-999-999."

    @patch('customer.sms_utils.send_sms')
    @patch('django.core.mail.EmailMessage.send')
    def test_pdf_generation_and_activation_saving(self, mock_email_send, mock_send_sms, setup_data):
        client = APIClient()
        client.force_authenticate(user=setup_data["user"])

        plan = FinancePlan.objects.create(
            credit_application=setup_data["credit_app"],
            credit_score=setup_data["credit_app"].customer.credit_scores.first(),
            apc_score=600,
            risk_tier="TIER_A",
            device_price=Decimal("500.00"),
            actual_down_payment=Decimal("100.00"),
            selected_term=6,
            installment_frequency_days=30,
            monthly_installment=Decimal("70.00"),
            total_amount_payable=Decimal("520.00"),
            customer_monthly_income=Decimal("1500.00"),
            payment_capacity_factor=Decimal("0.20"),
            maximum_allowed_installment=Decimal("300.00"),
            minimum_down_payment_percentage=Decimal("20.00"),
            amount_to_finance=Decimal("400.00"),
            created_by=setup_data["user"],
            status="DRAFT"
        )

        # Test download pdf endpoint
        pdf_url = reverse("finance-contracts-download-pdf")
        res = client.get(f"{pdf_url}?plan_id={plan.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res["Content-Type"] == "application/pdf"
        assert f"loan_agreement_{plan.id}.pdf" in res["Content-Disposition"]

        # Test PDF saving, statuses updates, and notifications trigger on activation
        activate_url = reverse("finance-plan-activate", kwargs={"plan_id": plan.id})
        res2 = client.post(activate_url)
        assert res2.status_code == status.HTTP_200_OK
        
        # Verify statuses updated
        setup_data["credit_app"].refresh_from_db()
        setup_data["customer"].refresh_from_db()
        assert setup_data["credit_app"].status == "APPROVED"
        assert setup_data["customer"].status == "ACTIVE"
        
        # Verify saved PDF
        assert setup_data["credit_app"].loan_agreement_pdf is not None
        assert setup_data["credit_app"].loan_agreement_pdf.name.startswith("loan_agreements/loan_agreement_")

        # Verify notifications called
        assert mock_send_sms.called is True
        assert mock_email_send.called is True

    def test_patch_transient_plan_imei_auto_enrollment(self, setup_data):
        from products.models import ProductCategory, Brand, ProductModel
        from customer_device.models import DeviceEnrollmentCustomer

        # 1. Setup brand and product
        cat = ProductCategory.objects.create(name="Mobile Phones")
        brand = Brand.objects.create(name="Xiaomi", category=cat)
        device = ProductModel.objects.create(
            brand=brand, 
            model_name="Redmi Note 12",
            suggested_price=Decimal("250.00"),
            minimum_price_to_sell=Decimal("200.00")
        )

        # Associate device and details with credit application
        credit_app = setup_data["credit_app"]
        credit_app.device = device
        credit_app.device_price = Decimal("250.00")
        credit_app.initial_payment = Decimal("50.00")
        credit_app.number_of_installments = 6
        credit_app.installment_frequency_days = 30
        credit_app.amount_to_finance = Decimal("200.00")
        credit_app.save()

        client = APIClient()
        client.force_authenticate(user=setup_data["user"])

        # Patch IMEI to the transient plan
        patch_url = reverse("finance-plan-detail", kwargs={"plan_id": credit_app.id})
        res = client.patch(patch_url, {"imei": "987654321012345"}, format="json")
        
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "success"

        # Check that FinancePlan was saved in DB
        assert FinancePlan.objects.filter(id=credit_app.id).exists() is True
        plan = FinancePlan.objects.get(id=credit_app.id)
        assert plan.status == "DRAFT"

        # Check that DeviceEnrollmentCustomer was created
        assert DeviceEnrollmentCustomer.objects.filter(finance_plan=plan).exists() is True
        enrollment = DeviceEnrollmentCustomer.objects.get(finance_plan=plan)
        assert enrollment.imei == "987654321012345"
        assert enrollment.locking_system == "EQUALITY"
        assert enrollment.enrollment_status == "QR_GENERATED"
        assert enrollment.locking_system_id == "EQ-987654321012345"

    def test_patch_transient_plan_imei_samsung_knox_enrollment(self, setup_data):
        from products.models import ProductCategory, Brand, ProductModel
        from customer_device.models import DeviceEnrollmentCustomer

        cat = ProductCategory.objects.create(name="Mobile Phones")
        brand = Brand.objects.create(name="Samsung", category=cat)
        device = ProductModel.objects.create(
            brand=brand, 
            model_name="Galaxy S24",
            suggested_price=Decimal("800.00"),
            minimum_price_to_sell=Decimal("700.00")
        )

        credit_app = setup_data["credit_app"]
        credit_app.device = device
        credit_app.device_price = Decimal("800.00")
        credit_app.initial_payment = Decimal("160.00")
        credit_app.number_of_installments = 6
        credit_app.installment_frequency_days = 30
        credit_app.amount_to_finance = Decimal("640.00")
        credit_app.save()

        client = APIClient()
        client.force_authenticate(user=setup_data["user"])

        # Patch IMEI to the transient plan
        patch_url = reverse("finance-plan-detail", kwargs={"plan_id": credit_app.id})
        
        # Mock KNOXService.enroll_device to return successful mock response
        with patch('customer_device.knox_service.KNOXService.enroll_device') as mock_enroll:
            mock_enroll.return_value = {
                'success': True,
                'enrollment_id': 'KNOX-S24-12345',
                'qr_code': 'https://samsungknox.com/qr/12345',
                'enrollment_link': 'https://samsungknox.com/enroll/12345',
                'error': None
            }
            res = client.patch(patch_url, {"imei": "111112222233333"}, format="json")
            
            assert res.status_code == status.HTTP_200_OK
            assert res.data["status"] == "success"

        # Check that DeviceEnrollmentCustomer was created
        plan = FinancePlan.objects.get(id=credit_app.id)
        enrollment = DeviceEnrollmentCustomer.objects.get(finance_plan=plan)
        assert enrollment.imei == "111112222233333"
        assert enrollment.locking_system == "KNOX"
        assert enrollment.enrollment_status == "QR_GENERATED"

    @patch('customer.sms_utils.send_sms')
    @patch('django.core.mail.EmailMessage.send')
    def test_activation_disbursal_creates_device_enrollment(self, mock_email_send, mock_send_sms, setup_data):
        from products.models import ProductCategory, Brand, ProductModel
        from customer_device.models import DeviceEnrollmentCustomer

        # 1. Setup brand and product
        cat = ProductCategory.objects.create(name="Mobile Phones")
        brand = Brand.objects.create(name="Samsung", category=cat)
        device = ProductModel.objects.create(
            brand=brand, 
            model_name="Galaxy S24",
            suggested_price=Decimal("800.00"),
            minimum_price_to_sell=Decimal("700.00")
        )

        credit_app = setup_data["credit_app"]
        credit_app.device = device
        credit_app.device_price = Decimal("800.00")
        credit_app.initial_payment = Decimal("160.00")
        credit_app.number_of_installments = 6
        credit_app.installment_frequency_days = 30
        credit_app.amount_to_finance = Decimal("640.00")
        credit_app.device_imei = "555556666677777"
        credit_app.save()

        plan = FinancePlan.objects.create(
            credit_application=credit_app,
            credit_score=credit_app.customer.credit_scores.first(),
            apc_score=600,
            risk_tier="TIER_A",
            device=device,
            device_price=Decimal("800.00"),
            actual_down_payment=Decimal("160.00"),
            selected_term=6,
            installment_frequency_days=30,
            monthly_installment=Decimal("120.00"),
            total_amount_payable=Decimal("720.00"),
            customer_monthly_income=Decimal("1500.00"),
            payment_capacity_factor=Decimal("0.20"),
            maximum_allowed_installment=Decimal("300.00"),
            minimum_down_payment_percentage=Decimal("20.00"),
            amount_to_finance=Decimal("640.00"),
            created_by=setup_data["user"],
            status="DRAFT"
        )

        client = APIClient()
        client.force_authenticate(user=setup_data["user"])

        # Test activation / disbursal
        activate_url = reverse("finance-plan-activate", kwargs={"plan_id": plan.id})
        
        with patch('customer_device.knox_service.KNOXService.enroll_device') as mock_enroll:
            mock_enroll.return_value = {
                'success': True,
                'enrollment_id': 'KNOX-ACT-999',
                'qr_code': 'https://samsungknox.com/qr/999',
                'enrollment_link': 'https://samsungknox.com/enroll/999',
                'error': None
            }
            res = client.post(activate_url)
            assert res.status_code == status.HTTP_200_OK

        # Verify DeviceEnrollmentCustomer was created automatically
        assert DeviceEnrollmentCustomer.objects.filter(finance_plan=plan).exists() is True
        enrollment = DeviceEnrollmentCustomer.objects.get(finance_plan=plan)
        assert enrollment.imei == "555556666677777"
        assert enrollment.locking_system == "KNOX"

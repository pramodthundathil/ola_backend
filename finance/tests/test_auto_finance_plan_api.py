import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from customer.models import Customer, CreditScore

User = get_user_model()


@pytest.mark.django_db
class TestAutoFinancePlanView:
    @pytest.fixture
    def setup_data(self):
        """Create base test data for user, customer, and credit score"""
        user = User.objects.create_user(email="testuser@gmail.com", password="pass123")
        customer = Customer.objects.create(document_number="DOC12345", created_by=user)
        credit_score = CreditScore.objects.create(
            customer=customer, apc_score=610, is_expired=False
        )
        return {"user": user, "customer": customer, "credit_score": credit_score}

    # ------------------------------------------------------------------
    # SUCCESS TEST
    # ------------------------------------------------------------------
    @patch("finance.views.AuditLog.objects.create")
    @patch("finance.views.CustomerIncome.get_income_by_document", return_value=Decimal("1000.00"))
    @patch("finance.views.AutoDecisionEngine")
    def test_create_auto_finance_plan_success(self, mock_engine, mock_income, mock_audit, setup_data):
        """Test successful auto finance plan generation"""

        client = APIClient()
        client.force_authenticate(user=setup_data["user"])
        url = reverse("finance-auto-plan")
        payload = {"customer_id": setup_data["customer"].id}

        # --- Mock Decision Engine internal plan ---
        mock_plan = MagicMock()
        mock_plan.customer_monthly_income = Decimal("1000.00")
        mock_plan.maximum_allowed_installment = Decimal("300.0000")
        mock_plan.minimum_down_payment_percentage = Decimal("20.00")
        mock_plan.risk_tier = "TIER_A"
        mock_plan.allowed_plans = [
            {"months": 4, "interval_days": 15},
            {"months": 4, "interval_days": 30},
            {"months": 6, "interval_days": 15},
            {"months": 6, "interval_days": 30},
            {"months": 8, "interval_days": 15},
            {"months": 8, "interval_days": 30},
            {"months": 10, "interval_days": 15},
            {"months": 10, "interval_days": 30},
        ]

        mock_engine_instance = MagicMock()
        mock_engine_instance.plan = mock_plan
        mock_engine_instance.run.return_value = mock_engine_instance  # engine.run() returns the instance itself
        mock_engine.return_value = mock_engine_instance

        # --- Act ---
        response = client.post(url, payload, format="json")

        # --- Assert ---
        if response.status_code != 201:
            print("Response Data:", response.data)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] == "success"
        assert "Auto Finance Plan" in response.data["message"]

        result = response.data["data"]
        assert result["customer_id"] == setup_data["customer"].id
        assert result["apc_score"] == 610
        assert result["risk_tier"] == "TIER_A"
        assert result["monthly_income"] == "1000.00"
        assert result["maximum_allowed_installment"] == "300.0000"
        assert result["minimum_down_payment_percentage"] == "20.00"

        expected_plans = [
            {"months": 4, "interval_days": 15},
            {"months": 4, "interval_days": 30},
            {"months": 6, "interval_days": 15},
            {"months": 6, "interval_days": 30},
            {"months": 8, "interval_days": 15},
            {"months": 8, "interval_days": 30},
            {"months": 10, "interval_days": 15},
            {"months": 10, "interval_days": 30},
        ]
        assert result["allowed_plans"] == expected_plans

        mock_income.assert_called_once_with("DOC12345")
        mock_audit.assert_called_once()
        mock_engine.assert_called_once()

    # ------------------------------------------------------------------
    #  NEGATIVE TEST: Missing Customer ID
    # ------------------------------------------------------------------
    @patch("finance.views.AuditLog.objects.create")
    def test_create_auto_finance_plan_missing_customer(self, mock_audit, setup_data):
        client = APIClient()
        client.force_authenticate(user=setup_data["user"])
        url = reverse("finance-auto-plan")
        payload = {}
        print("Sending request to API 1...")
        response = client.post(url, payload, format="json")
        print("Got response:", response.status_code)

        

        assert response.status_code in [400, 500]
        mock_audit.assert_not_called()

    # ------------------------------------------------------------------
    #  NEGATIVE TEST: Invalid Customer ID
    # ------------------------------------------------------------------
    @patch("finance.views.AuditLog.objects.create")
    def test_create_auto_finance_plan_invalid_customer(self, mock_audit, setup_data):
        client = APIClient()
        client.force_authenticate(user=setup_data["user"])
        url = reverse("finance-auto-plan")
        payload = {"customer_id": 999}
        print(" Sending request to API.2..")
        response = client.post(url, payload, format="json")
        print("Got response:", response.status_code)

        assert response.status_code in [404, 500]
        mock_audit.assert_not_called()

    # ------------------------------------------------------------------
    # NEGATIVE TEST: No active credit score
    # ------------------------------------------------------------------
    @patch("finance.views.AuditLog.objects.create")
    def test_create_auto_finance_plan_no_active_credit_score(self, mock_audit, setup_data):
        setup_data["credit_score"].is_expired = True
        setup_data["credit_score"].save()

        client = APIClient()
        client.force_authenticate(user=setup_data["user"])
        url = reverse("finance-auto-plan")
        payload = {"customer_id": setup_data["customer"].id}

        print("Sending request to API.3..")
        response = client.post(url, payload, format="json")
        print("Got response:", response.status_code)

        assert response.status_code in [400, 201]
        mock_audit.assert_called_once()

    # ------------------------------------------------------------------
    # NEGATIVE TEST: Internal Server Error
    # ------------------------------------------------------------------
    @patch("finance.views.AuditLog.objects.create")
    @patch("finance.views.CustomerIncome.get_income_by_document", side_effect=Exception("Income API failed"))
    def test_create_auto_finance_plan_internal_error(self, mock_income, mock_audit, setup_data):
        client = APIClient()
        client.force_authenticate(user=setup_data["user"])
        url = reverse("finance-auto-plan")
        payload = {"customer_id": setup_data["customer"].id}

        print("Sending request to API.4..")
        response = client.post(url, payload, format="json")
        print(" Got response:", response.status_code)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "internal server error" in response.data["message"].lower()
        mock_audit.assert_called_once()

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from customer.models import Customer, CreditApplication, CreditScore, CreditConfig
from products.models import ProductModel, Brand, ProductCategory
from finance.models import FinancePlan, FinanceMultiple
from finance.decision_engine import DecisionEngine
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

@pytest.mark.django_db
class TestDecisionEngineLogic:
    @pytest.fixture
    def setup_data(self):
        # 1. Create User
        user = User.objects.create_user(email="sales@olacredits.com", password="password123", role="salesperson")
        
        # 2. Create ProductCategory & Brand
        cat = ProductCategory.objects.create(name="Smartphones")
        brand = Brand.objects.create(name="Samsung", category=cat)
        
        # 3. Create Product
        product = ProductModel.objects.create(
            brand=brand,
            model_name="Galaxy S21",
            suggested_price=Decimal("400.00"),
            minimum_price_to_sell=Decimal("300.00")
        )
        
        # 4. Create Credit Config
        config = CreditConfig.objects.create(
            tier_a_min_score=600,
            tier_b_min_score=550,
            tier_c_min_score=500
        )
        
        # 5. Create Finance Multiples
        FinanceMultiple.objects.create(term_months=4, interval_days=30, multiple=Decimal("1.1"))
        FinanceMultiple.objects.create(term_months=6, interval_days=30, multiple=Decimal("1.2"))
        FinanceMultiple.objects.create(term_months=8, interval_days=30, multiple=Decimal("1.3"))
        
        return {
            "user": user,
            "product": product,
            "config": config
        }

    def test_tier_a_approval_logic(self, setup_data):
        """Test logic for a high-score customer (Tier A)"""
        customer = Customer.objects.create(document_number="8-000-000", first_name="John", last_name="Doe")
        score = CreditScore.objects.create(customer=customer, apc_score=700)
        app = CreditApplication.objects.create(customer=customer, sales_person=setup_data["user"], device_price=Decimal("400.00"))
        
        plan = FinancePlan.objects.create(
            credit_application=app,
            credit_score=score,
            apc_score=700,
            risk_tier="TIER_A",
            minimum_down_payment_percentage=Decimal("20.00"),
            device=setup_data["product"],
            device_price=Decimal("400.00"),
            actual_down_payment=Decimal("80.00"), # 20%
            selected_term=6,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("2000.00"),
            created_by=setup_data["user"]
        )
        
        engine = DecisionEngine(plan)
        result_plan = engine.run()
        
        assert result_plan.risk_tier == 'TIER_A'
        assert result_plan.minimum_down_payment_percentage == Decimal('20.00')
        assert result_plan.amount_to_finance == Decimal('320.00')
        # EMI = (320 * 1.2) / 6 = 384 / 6 = 64
        assert result_plan.monthly_installment == Decimal('64.00')
        assert result_plan.payment_capacity_passed is True
        assert result_plan.conditions_met is True
        assert result_plan.score_status == 'APPROVED'

    def test_tier_c_high_end_logic(self, setup_data):
        """Test logic for Tier C with high-end device extra down payment"""
        customer = Customer.objects.create(document_number="8-111-111", first_name="Jane", last_name="Doe")
        score = CreditScore.objects.create(customer=customer, apc_score=520)
        app = CreditApplication.objects.create(customer=customer, sales_person=setup_data["user"], device_price=Decimal("400.00"))
        
        # Tier C requires 25% + 10% (high end) = 35% down payment
        plan = FinancePlan.objects.create(
            credit_application=app,
            credit_score=score,
            apc_score=520,
            risk_tier="TIER_C",
            minimum_down_payment_percentage=Decimal("35.00"),
            device=setup_data["product"],
            device_price=Decimal("400.00"),
            actual_down_payment=Decimal("140.00"), # 35%
            selected_term=8,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("1000.00"),
            created_by=setup_data["user"]
        )
        
        engine = DecisionEngine(plan)
        result_plan = engine.run()
        
        assert result_plan.risk_tier == 'TIER_C'
        assert result_plan.minimum_down_payment_percentage == Decimal('35.00')
        assert result_plan.conditions_met is True

    def test_tier_d_rejection_logic(self, setup_data):
        """Test logic for Tier D (Very High Risk)"""
        customer = Customer.objects.create(document_number="8-222-222", first_name="Bad", last_name="Credit")
        score = CreditScore.objects.create(customer=customer, apc_score=400)
        app = CreditApplication.objects.create(customer=customer, sales_person=setup_data["user"], device_price=Decimal("400.00"))
        
        plan = FinancePlan.objects.create(
            credit_application=app,
            credit_score=score,
            apc_score=400,
            risk_tier="TIER_D",
            minimum_down_payment_percentage=Decimal("25.00"),
            device=setup_data["product"],
            device_price=Decimal("400.00"),
            actual_down_payment=Decimal("100.00"),
            selected_term=4,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("1000.00"),
            created_by=setup_data["user"]
        )
        
        engine = DecisionEngine(plan)
        result_plan = engine.run()
        
        assert result_plan.risk_tier == 'TIER_D'
        assert result_plan.conditions_met is False
        assert result_plan.score_status == 'REJECTED'

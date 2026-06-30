import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from customer.models import Customer, CreditApplication, CreditScore, CreditConfig
from products.models import ProductModel, Brand, ProductCategory
from finance.models import FinancePlan, FinanceMultiple, RiskTier, LoanTerm, ReferenceRule, EMIConfiguration, DecisionRule
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

        # Seed new models for tests
        EMIConfiguration.objects.get_or_create(id=1, defaults={'method': 'FLAT'})
        ReferenceRule.objects.get_or_create(id=1, defaults={'min_references': 0, 'is_active': True})
        
        # Risk Tiers
        RiskTier.objects.get_or_create(code='TIER_A', defaults={
            'name': 'Tier A', 'min_score': 600, 'max_score': 900,
            'min_salary': Decimal('500.00'), 'max_debt_ratio_pct': Decimal('30.00'),
            'min_down_payment_pct': Decimal('20.00'), 'approval_level': 'AUTO', 'is_active': True
        })
        RiskTier.objects.get_or_create(code='TIER_B', defaults={
            'name': 'Tier B', 'min_score': 550, 'max_score': 599,
            'min_salary': Decimal('500.00'), 'max_debt_ratio_pct': Decimal('20.00'),
            'min_down_payment_pct': Decimal('25.00'), 'approval_level': 'FINANCE_ADMIN', 'is_active': True
        })
        RiskTier.objects.get_or_create(code='TIER_C', defaults={
            'name': 'Tier C', 'min_score': 500, 'max_score': 549,
            'min_salary': Decimal('500.00'), 'max_debt_ratio_pct': Decimal('20.00'),
            'min_down_payment_pct': Decimal('35.00'), 'approval_level': 'ADMIN', 'is_active': True
        })
        RiskTier.objects.get_or_create(code='TIER_D', defaults={
            'name': 'Tier D', 'min_score': 0, 'max_score': 499,
            'min_salary': Decimal('0.00'), 'max_debt_ratio_pct': Decimal('0.00'),
            'min_down_payment_pct': Decimal('100.00'), 'approval_level': 'GLOBAL_MANAGER', 'is_active': True
        })
        
        # Loan Terms
        LoanTerm.objects.get_or_create(months=4, defaults={'fortnights': 8, 'multiplier': Decimal('1.1'), 'is_active': True})
        LoanTerm.objects.get_or_create(months=6, defaults={'fortnights': 12, 'multiplier': Decimal('1.2'), 'is_active': True})
        LoanTerm.objects.get_or_create(months=8, defaults={'fortnights': 16, 'multiplier': Decimal('1.3'), 'is_active': True})

        # Decision Rules
        decision_rules = [
            {'key': 'min_score_check', 'desc': 'Score Check', 'val': 'True', 'mand': True},
            {'key': 'min_salary_check', 'desc': 'Salary Check', 'val': 'True', 'mand': True},
            {'key': 'debt_ratio_check', 'desc': 'Debt Check', 'val': 'True', 'mand': True},
            {'key': 'blacklist_check', 'desc': 'Blacklist Check', 'val': 'True', 'mand': True},
            {'key': 'active_loan_check', 'desc': 'Active Loan Check', 'val': 'True', 'mand': True},
            {'key': 'reference_check', 'desc': 'Reference Check', 'val': 'True', 'mand': True}
        ]
        for rule in decision_rules:
            DecisionRule.objects.get_or_create(
                rule_key=rule['key'],
                defaults={'description': rule['desc'], 'value': rule['val'], 'is_mandatory': rule['mand'], 'is_active': True}
            )
        
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
        score = CreditScore.objects.create(customer=customer, apc_score=470)
        app = CreditApplication.objects.create(customer=customer, sales_person=setup_data["user"], device_price=Decimal("400.00"))
        
        # Tier C requires 30% down payment under new Panamanian matrix
        plan = FinancePlan.objects.create(
            credit_application=app,
            credit_score=score,
            apc_score=470,
            risk_tier="TIER_C",
            minimum_down_payment_percentage=Decimal("30.00"),
            device=setup_data["product"],
            device_price=Decimal("400.00"),
            actual_down_payment=Decimal("120.00"), # 30%
            selected_term=8,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("1000.00"),
            created_by=setup_data["user"]
        )
        
        engine = DecisionEngine(plan)
        result_plan = engine.run()
        
        assert result_plan.risk_tier == 'TIER_C'
        assert result_plan.minimum_down_payment_percentage == Decimal('30.00')
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

    def test_draft_finance_plan_no_invoices(self, setup_data):
        """Verify that when a FinancePlan is created as DRAFT, no invoices or ledger entries are created"""
        customer = Customer.objects.create(document_number="8-333-333", first_name="Draft", last_name="User")
        score = CreditScore.objects.create(customer=customer, apc_score=620)
        app = CreditApplication.objects.create(customer=customer, sales_person=setup_data["user"], device_price=Decimal("400.00"))
        
        plan = FinancePlan.objects.create(
            credit_application=app,
            credit_score=score,
            apc_score=620,
            risk_tier="TIER_A",
            minimum_down_payment_percentage=Decimal("20.00"),
            device=setup_data["product"],
            device_price=Decimal("400.00"),
            actual_down_payment=Decimal("80.00"),
            selected_term=6,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("2000.00"),
            created_by=setup_data["user"],
            status="DRAFT"
        )
        
        assert plan.emi_schedule.exists()
        from finance.models import Invoice
        assert not Invoice.objects.filter(finance_plan=plan).exists()

    def test_finance_plan_activation(self, setup_data):
        """Verify that activating a DRAFT FinancePlan updates status to ACTIVE and generates invoices and ledger entries"""
        customer = Customer.objects.create(document_number="8-444-444", first_name="Activate", last_name="User")
        score = CreditScore.objects.create(customer=customer, apc_score=620)
        app = CreditApplication.objects.create(customer=customer, sales_person=setup_data["user"], device_price=Decimal("400.00"))
        
        plan = FinancePlan.objects.create(
            credit_application=app,
            credit_score=score,
            apc_score=620,
            risk_tier="TIER_A",
            minimum_down_payment_percentage=Decimal("20.00"),
            device=setup_data["product"],
            device_price=Decimal("400.00"),
            actual_down_payment=Decimal("80.00"),
            selected_term=6,
            installment_frequency_days=30,
            customer_monthly_income=Decimal("2000.00"),
            created_by=setup_data["user"],
            status="DRAFT"
        )
        
        from finance.models import Invoice
        assert not Invoice.objects.filter(finance_plan=plan).exists()
        
        from rest_framework.test import APIRequestFactory, force_authenticate
        from finance.views import FinancePlanActivateAPIView
        
        factory = APIRequestFactory()
        request = factory.post(f"/api/finance/finance-plan/{plan.id}/activate/")
        force_authenticate(request, user=setup_data["user"])
        
        view = FinancePlanActivateAPIView.as_view()
        response = view(request, plan_id=plan.id)
        
        assert response.status_code == 200
        plan.refresh_from_db()
        assert plan.status == "ACTIVE"
        
        # Verify invoices are generated by running the management command
        from django.core.management import call_command
        call_command("generate_invoices")
        
        assert Invoice.objects.filter(finance_plan=plan).exists()
        assert Invoice.objects.filter(finance_plan=plan).count() == plan.emi_schedule.count()


import pytest
from decimal import Decimal
from django.utils import timezone
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from store.models import Store, Region, Province, District
from customer.models import Customer, CreditApplication
from products.models import Brand, ProductModel, ProductCategory
from finance.models import (
    FinancePlan,
    EMISchedule,
    Invoice,
    FinanceMultiple
)

User = get_user_model()

@pytest.fixture
def test_setup(db):
    region = Region.objects.create(name="Panama Region", code="PAN")
    province = Province.objects.create(region=region, name="Panama Prov", code="PAN-PROV")
    district = District.objects.create(province=province, name="Panama Dist", code="PAN-DIST")
    
    admin_user = User.objects.create_user(
        email="admin@test.com",
        password="password123",
        username="admin_test",
        role="admin",
        first_name="Admin",
        last_name="User"
    )

    store = Store.objects.create(
        name="Test Tech Merchant",
        region=region,
        province=province,
        district=district,
        store_manager=admin_user,
        ruc="12345-6789-9",
        is_active=True
    )

    customer = Customer.objects.create(
        first_name="John",
        last_name="Doe",
        document_number="PE-8-1234",
        phone_number="+50766666666",
        email="john@doe.com"
    )

    cat = ProductCategory.objects.create(name="Smartphones", slug="smartphones")
    brand = Brand.objects.create(name="Apple", category=cat)
    product = ProductModel.objects.create(
        brand=brand,
        model_name="iPhone 15",
        suggested_price=Decimal("999.00"),
        minimum_price_to_sell=Decimal("800.00")
    )

    credit_app = CreditApplication.objects.create(
        customer=customer,
        sales_person=admin_user,
        device=product,
        device_price=Decimal('999.00'),
        initial_payment=Decimal('199.00'),
        amount_to_finance=Decimal('800.00'),
        number_of_installments=12,
        status="APPROVED",
        expires_at=timezone.now() + timezone.timedelta(days=2)
    )

    # Ensure FinanceMultiple exists
    FinanceMultiple.objects.get_or_create(
        term_months=12,
        interval_days=30,
        defaults={"multiple": Decimal("1.2"), "is_active": True}
    )

    plan = FinancePlan.objects.create(
        credit_application=credit_app,
        apc_score=600,
        risk_tier="TIER_A",
        device=product,
        device_price=Decimal("999.00"),
        actual_down_payment=Decimal("199.00"),
        minimum_down_payment_percentage=Decimal("20.00"),
        amount_to_finance=Decimal("800.00"),
        selected_term=12,
        installment_frequency_days=30,
        monthly_installment=Decimal("80.00"),
        total_amount_payable=Decimal("960.00"),
        customer_monthly_income=Decimal("3000.00"),
        payment_capacity_factor=Decimal("0.20"),
        created_by=admin_user,
        store=store,
        status="ACTIVE",
        disbursement_status="PENDING"
    )

    return {
        "admin": admin_user,
        "customer": customer,
        "plan": plan
    }

@pytest.mark.django_db
def test_emi_initial_status_is_draft_when_undisbursed(test_setup):
    plan = test_setup["plan"]
    # Generate schedule
    EMISchedule.objects.filter(finance_plan=plan).delete()
    schedules = EMISchedule.generate_schedule(plan, timezone.now().date(), save=True)
    
    assert len(schedules) == 12
    # Verify all EMIs are created with DRAFT status
    for emi in schedules:
        assert emi.status == "DRAFT"

@pytest.mark.django_db
def test_disbursing_loan_transitions_emis_to_upcoming(test_setup):
    plan = test_setup["plan"]
    # Verify initial DRAFT
    EMISchedule.objects.filter(finance_plan=plan).delete()
    schedules = EMISchedule.generate_schedule(plan, timezone.now().date(), save=True)
    assert all(emi.status == "DRAFT" for emi in schedules)

    client = APIClient()
    client.force_authenticate(user=test_setup["admin"])
    
    # Patch disbursement_status to DISBURSED
    url = reverse("finance-plan-detail", kwargs={"plan_id": plan.id})
    res = client.patch(url, {"disbursement_status": "DISBURSED"}, format="json")
    assert res.status_code == status.HTTP_200_OK
    
    # Check that EMIs are now UPCOMING
    plan.refresh_from_db()
    assert plan.disbursement_status == "DISBURSED"
    assert all(emi.status == "UPCOMING" for emi in plan.emi_schedule.all())

@pytest.mark.django_db
def test_sequential_emi_invoice_generation(test_setup):
    plan = test_setup["plan"]
    EMISchedule.objects.filter(finance_plan=plan).delete()
    schedules = EMISchedule.generate_schedule(plan, timezone.now().date(), save=True)

    client = APIClient()
    client.force_authenticate(user=test_setup["admin"])

    # Attempt generating invoice while undisbursed -> should fail
    emi1 = schedules[0]
    url_invoice = reverse("emi-create-invoice", kwargs={"emi_id": emi1.id})
    res = client.post(url_invoice)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "undisbursed" in res.data["message"].lower()

    # Disburse the loan
    url_plan = reverse("finance-plan-detail", kwargs={"plan_id": plan.id})
    client.patch(url_plan, {"disbursement_status": "DISBURSED"}, format="json")
    
    # Refresh schedules list
    schedules = list(EMISchedule.objects.filter(finance_plan=plan).order_by("installment_number"))

    # Generate invoice for EMI #2 before EMI #1 -> should fail (sequential rule)
    emi2 = schedules[1]
    url_invoice_2 = reverse("emi-create-invoice", kwargs={"emi_id": emi2.id})
    res = client.post(url_invoice_2)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "must have an invoice generated first" in res.data["message"].lower()

    # Generate invoice for EMI #1 -> should succeed
    res = client.post(url_invoice)
    assert res.status_code == status.HTTP_200_OK
    assert Invoice.objects.filter(emi_schedule=emi1).exists()
    
    # Generate invoice for EMI #1 again -> should fail (duplicate rule)
    res = client.post(url_invoice)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "already generated" in res.data["message"].lower()

    # Generate invoice for EMI #2 -> should now succeed (since #1 has invoice)
    res = client.post(url_invoice_2)
    assert res.status_code == status.HTTP_200_OK
    assert Invoice.objects.filter(emi_schedule=emi2).exists()


@pytest.mark.django_db
def test_invoice_list_pagination_out_of_bounds(test_setup):
    admin_user = test_setup["admin"]
    client = APIClient()
    client.force_authenticate(user=admin_user)

    # Fetch invoices list with page=2 which is out of bounds since there are no invoices yet
    url = reverse("invoices-list")
    res = client.get(url, {"page": 2, "page_size": 10})
    
    assert res.status_code == status.HTTP_200_OK
    assert res.data["results"] == []
    assert res.data["count"] == 0
    assert res.data["next"] is None
    assert res.data["previous"] is None

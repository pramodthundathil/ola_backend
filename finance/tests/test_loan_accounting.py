import pytest
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import get_user_model
from store.models import Store, Region, Province, District
from customer.models import Customer, CreditApplication
from products.models import Brand, ProductModel, ProductCategory
from finance.models import (
    FinancePlan,
    BankAccount,
    AccountingCode,
    JournalEntry,
    LedgerEntry,
    LoanDisbursement,
    CustomerLoanLedgerEntry,
    MerchantSettlement,
    MerchantLedgerEntry,
    PaymentReceived,
    FinanceMultiple,
    PaymentMade
)
from finance.accounting_services import AccountingEngineService

User = get_user_model()

@pytest.fixture
def accounting_setup(db):
    # Ensure region, province, district
    region = Region.objects.create(name="Panama Region", code="PAN")
    province = Province.objects.create(region=region, name="Panama Prov", code="PAN-PROV")
    district = District.objects.create(province=province, name="Panama Dist", code="PAN-DIST")
    
    # Store Manager User
    manager = User.objects.create_user(
        email="manager@test.com",
        password="password123",
        username="store_manager_test",
        role="store_manager",
        first_name="Store",
        last_name="Manager"
    )

    # Store (Merchant)
    store = Store.objects.create(
        name="Test Tech Merchant",
        region=region,
        province=province,
        district=district,
        store_manager=manager,
        ruc="12345-6789-9",
        is_active=True
    )
    # Note: save() signal creates the Vendor and AccountingCode automatically.
    
    # Customer
    customer = Customer.objects.create(
        first_name="John",
        last_name="Doe",
        document_number="PE-8-1234",
        phone_number="+50766666666",
        email="john.doe@example.com",
        status="ACTIVE"
    )
    
    # Product
    category = ProductCategory.objects.create(name="Phones", slug="phones")
    brand = Brand.objects.create(name="Samsung", category=category)
    product = ProductModel.objects.create(
        brand=brand,
        model_name="Galaxy S23",
        suggested_price=1000.00,
        minimum_price_to_sell=800.00
    )

    # Credit App
    credit_app = CreditApplication.objects.create(
        customer=customer,
        sales_person=manager,
        device=product,
        device_price=Decimal('1000.00'),
        initial_payment=Decimal('100.00'),
        amount_to_finance=Decimal('900.00'),
        number_of_installments=6,
        status="APPROVED",
        expires_at=timezone.now() + timezone.timedelta(days=2)
    )

    # Finance Multiple
    FinanceMultiple.objects.create(
        term_months=6,
        interval_days=30,
        multiple=Decimal('1.00'),
        is_active=True
    )

    # Finance Plan (Loan)
    plan = FinancePlan.objects.create(
        credit_application=credit_app,
        apc_score=650,
        risk_tier="TIER_A",
        device=product,
        device_price=Decimal('1000.00'),
        actual_down_payment=Decimal('100.00'),
        minimum_down_payment_percentage=Decimal('10.00'),
        amount_to_finance=Decimal('900.00'),
        selected_term=6,
        monthly_installment=Decimal('150.00'),
        total_amount_payable=Decimal('1000.00'),
        customer_monthly_income=Decimal('3000.00'),
        payment_capacity_factor=Decimal('0.20'),
        created_by=manager,
        store=store,
        status="ACTIVE"
    )

    # GL Bank Account & bank accounting code
    bank_gl = AccountingCode.objects.create(
        code="1102",
        name="General Test Bank",
        category="ASSET"
    )
    bank_acc = BankAccount.objects.create(
        bank_name="Test Bank",
        account_number="9988776655",
        account_holder_name="Ola Credit",
        accounting_code=bank_gl,
        initial_balance=Decimal('5000.00'),
        current_balance=Decimal('5000.00'),
        status="ACTIVE"
    )

    # Standard Accounts
    AccountingCode.objects.get_or_create(code="1300", defaults={"name": "Customer Loan Receivable", "category": "ASSET"})
    AccountingCode.objects.get_or_create(code="4200", defaults={"name": "Interest/Financing Revenue", "category": "REVENUE"})
    AccountingCode.objects.get_or_create(code="4300", defaults={"name": "Penalty Revenue", "category": "REVENUE"})
    AccountingCode.objects.get_or_create(code="6200", defaults={"name": "Bad Debt Write-off Expense", "category": "EXPENSE"})

    return {
        "store": store,
        "customer": customer,
        "plan": plan,
        "bank_account": bank_acc,
        "manager": manager
    }

def test_disbursement_and_settlement_posting(accounting_setup):
    plan = accounting_setup["plan"]
    store = accounting_setup["store"]
    bank_acc = accounting_setup["bank_account"]

    # 1. Test Partial Disbursement ($400 out of $900)
    disb1 = AccountingEngineService.disburse_loan(plan.id, 400.00, "First partial disbursement")
    
    assert disb1.status == "COMPLETED"
    assert disb1.amount == Decimal("400.00")
    
    # Assert GL entries
    journal = JournalEntry.objects.get(reference_number=disb1.disbursement_number)
    ledgers = LedgerEntry.objects.filter(journal_entry=journal)
    assert ledgers.count() == 2
    
    dr_entry = ledgers.get(type="DEBIT")
    cr_entry = ledgers.get(type="CREDIT")
    
    assert dr_entry.accounting_code.code == "1300"  # Loan Receivable
    assert dr_entry.amount == Decimal("400.00")
    
    assert cr_entry.accounting_code.code == store.accounting_code.code  # Store Payable
    assert cr_entry.amount == Decimal("400.00")

    # Assert Subledger Entries
    cust_ledger = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).first()
    assert cust_ledger.entry_type == "DISBURSEMENT"
    assert cust_ledger.outstanding_principal == Decimal("400.00")
    assert cust_ledger.outstanding_balance == Decimal("400.00")

    settlement = MerchantSettlement.objects.filter(finance_plan=plan).first()
    assert settlement.status == "PENDING"
    assert settlement.amount == Decimal("400.00")

    merch_ledger = MerchantLedgerEntry.objects.filter(store=store).first()
    assert merch_ledger.entry_type == "SETTLEMENT_CREATION"
    assert merch_ledger.outstanding_balance == Decimal("400.00")

    # 2. Test Settlement Payment
    settled = AccountingEngineService.settle_merchant(
        settlement.id, 
        bank_acc.id, 
        "REF-BANK-998",
        timezone.now()
    )
    
    assert settled.status == "PAID"
    assert BankAccount.objects.get(id=bank_acc.id).current_balance == Decimal("4600.00")  # 5000 - 400

    # Assert PaymentMade is created
    payment_made = PaymentMade.objects.get(payment_number=f"PM-{settled.settlement_number}")
    assert payment_made.amount_paid == Decimal("400.00")
    assert payment_made.vendor.store == store

    # Assert GL for payment
    pay_journal = JournalEntry.objects.get(reference_number=f"STPY-{settled.settlement_number}")
    pay_ledgers = LedgerEntry.objects.filter(journal_entry=pay_journal)
    assert pay_ledgers.count() == 2
    
    pay_dr = pay_ledgers.get(type="DEBIT")
    pay_cr = pay_ledgers.get(type="CREDIT")
    
    assert pay_dr.accounting_code.code == store.accounting_code.code  # Store Payable debit
    assert pay_dr.payment_made == payment_made
    assert pay_cr.accounting_code.code == bank_acc.accounting_code.code  # Bank credit
    assert pay_cr.payment_made == payment_made

    # Assert Merchant outstanding goes to 0
    last_merch = MerchantLedgerEntry.objects.filter(store=store).order_by("-id").first()
    assert last_merch.entry_type == "SETTLEMENT_PAYMENT"
    assert last_merch.outstanding_balance == Decimal("0.00")


def test_customer_loan_adjustments_and_payments(accounting_setup):
    plan = accounting_setup["plan"]
    bank_acc = accounting_setup["bank_account"]

    # Disburse full amount ($900)
    AccountingEngineService.disburse_loan(plan.id, 900.00, "Full disbursement")

    # 1. Charge Penalty ($50)
    AccountingEngineService.charge_interest_or_penalty(plan.id, 50.00, "PENALTY", "Late payment fee")
    
    last_cust = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by("-id").first()
    assert last_cust.entry_type == "PENALTY_CHARGED"
    assert last_cust.outstanding_penalties == Decimal("50.00")
    assert last_cust.outstanding_principal == Decimal("900.00")
    assert last_cust.outstanding_balance == Decimal("950.00")

    # 2. Charge Interest ($20)
    AccountingEngineService.charge_interest_or_penalty(plan.id, 20.00, "INTEREST", "Monthly interest accrual")
    
    last_cust = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by("-id").first()
    assert last_cust.entry_type == "INTEREST_ACCRUAL"
    assert last_cust.outstanding_interest == Decimal("20.00")
    assert last_cust.outstanding_balance == Decimal("970.00")

    # 3. Process Customer Payment of $150
    # Create PaymentReceived record
    payment = PaymentReceived.objects.create(
        payment_number="PR-TEST-123",
        customer=plan.customer,
        amount_received=150.00,
        payment_date=timezone.now(),
        payment_method="CASH",
        deposited_to=bank_acc.accounting_code,
        invoices=[]
    )

    # Penalty is cleared first ($50), then Interest ($20), then Principal ($80)
    # Remaining Principal should be 900 - 80 = 820.
    AccountingEngineService.post_customer_payment(
        finance_plan_id=plan.id,
        payment_received_id=payment.id,
        principal_portion=80.00,
        interest_portion=20.00,
        penalty_portion=50.00
    )

    last_cust = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by("-id").first()
    assert last_cust.entry_type == "EMI_PAYMENT"
    assert last_cust.outstanding_penalties == Decimal("0.00")
    assert last_cust.outstanding_interest == Decimal("0.00")
    assert last_cust.outstanding_principal == Decimal("820.00")
    assert last_cust.outstanding_balance == Decimal("820.00")


def test_loan_write_off(accounting_setup):
    plan = accounting_setup["plan"]
    
    # Disburse
    AccountingEngineService.disburse_loan(plan.id, 900.00, "Disburse all")

    # Write-off remaining outstanding balance
    AccountingEngineService.write_off_loan(plan.id, "Customer bankrupt")

    last_cust = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by("-id").first()
    assert last_cust.entry_type == "WRITE_OFF"
    
    # Assert outstanding balances are zero
    wo_entry = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan, entry_type="WRITE_OFF").first()
    assert wo_entry.outstanding_balance == Decimal("0.00")
    assert wo_entry.outstanding_principal == Decimal("0.00")
    
    assert FinancePlan.objects.get(id=plan.id).status == "CLOSED"


def test_disbursement_reversal(accounting_setup):
    plan = accounting_setup["plan"]
    store = accounting_setup["store"]

    disb = AccountingEngineService.disburse_loan(plan.id, 500.00, "Disburse $500")

    # Reverse disbursement
    reversed_disb = AccountingEngineService.reverse_disbursement(disb.id)
    
    assert reversed_disb.status == "CANCELLED"
    assert MerchantSettlement.objects.filter(finance_plan=plan).first().status == "CANCELLED"

    last_cust = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by("-id").first()
    assert last_cust.entry_type == "REVERSAL"
    assert last_cust.outstanding_principal == Decimal("0.00")
    assert last_cust.outstanding_balance == Decimal("0.00")

    last_merch = MerchantLedgerEntry.objects.filter(store=store).order_by("-id").first()
    assert last_merch.entry_type == "CANCELLATION"
    assert last_merch.outstanding_balance == Decimal("0.00")

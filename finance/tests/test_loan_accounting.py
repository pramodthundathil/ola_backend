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
    assert settlement.bill is not None
    assert settlement.bill.status == "PENDING"

    # Assert Bill GL Journal Entry
    bill_journal = JournalEntry.objects.get(reference_number=f"JR-{settlement.bill.bill_number}")
    bill_ledgers = LedgerEntry.objects.filter(journal_entry=bill_journal)
    assert bill_ledgers.count() == 2
    assert bill_ledgers.filter(type="CREDIT", accounting_code__code="2100", amount=Decimal("400.00")).exists()
    assert bill_ledgers.filter(type="DEBIT", accounting_code__code=store.accounting_code.code, amount=Decimal("400.00")).exists()

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
    
    # Assert connected Bill is paid
    settled.bill.refresh_from_db()
    assert settled.bill.status == "PAID"
    assert settled.bill.balance == Decimal("0.00")

    # Assert PaymentMade is created
    payment_made = PaymentMade.objects.get(payment_number=f"PM-{settled.settlement_number}")
    assert payment_made.amount_paid == Decimal("400.00")
    assert payment_made.vendor.store == store

    # Assert GL for payment (tallied and using 2100 Accounts Payable)
    pay_journal = JournalEntry.objects.get(reference_number=f"JR-{payment_made.payment_number}")
    pay_ledgers = LedgerEntry.objects.filter(journal_entry=pay_journal)
    assert pay_ledgers.count() == 2
    
    pay_dr = pay_ledgers.get(type="DEBIT")
    pay_cr = pay_ledgers.get(type="CREDIT")
    
    assert pay_dr.accounting_code.code == "2100"  # Accounts Payable debit
    assert pay_dr.payment_made == payment_made
    assert pay_dr.settlement == settled
    
    assert pay_cr.accounting_code.code == bank_acc.accounting_code.code  # Bank credit
    assert pay_cr.payment_made == payment_made
    assert pay_cr.settlement == settled

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


def test_emi_invoice_and_payment_clearing_flow(accounting_setup):
    from finance.models import EMISchedule, Invoice, PaymentReceived, LedgerEntry, CustomerLoanLedgerEntry
    plan = accounting_setup["plan"]
    bank_acc = accounting_setup["bank_account"]

    # 1. Disburse the loan first to allow EMI invoicing
    AccountingEngineService.disburse_loan(plan.id, 900.00, "Full disbursement")

    # Clear any auto-generated EMISchedule objects to prevent unique constraint violation
    EMISchedule.objects.filter(finance_plan=plan).delete()

    # 2. Setup an EMI installment schedule with principal = 8000, interest = 1500
    emi = EMISchedule.objects.create(
        finance_plan=plan,
        installment_number=1,
        due_date=timezone.now().date(),
        installment_amount=Decimal("9500.00"),
        principal=Decimal("8000.00"),
        interest=Decimal("1500.00"),
        balance_remaining=Decimal("9500.00"),
        status="UPCOMING"
    )

    # 3. Create the Invoice (base_amount=9500.00, penalty_amount=500.00, total_amount=10000.00)
    invoice = Invoice.objects.create(
        invoice_number="INV-EMI-TEST-001",
        customer=plan.customer,
        finance_plan=plan,
        emi_schedule=emi,
        due_date=emi.due_date,
        base_amount=emi.installment_amount,
        subtotal=Decimal("10000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("10000.00"),
        balance=Decimal("10000.00"),
        amount_paid=Decimal("0.00"),
        principal_amount=emi.principal,
        interest_amount=emi.interest,
        penalty_amount=Decimal("500.00"),
        status="PENDING",
        invoice_type="PLAN"
    )

    # Generate invoice ledger entries
    invoice.generate_ledger_entries()

    # Assert Invoice ledger entries:
    # Dr EMI Receivable (1200) - 10000
    # Cr Installment Due (Principal) / Loan Installment Payable (2500) - 8000
    # Cr Interest Income (4200) - 1500
    # Cr Penalty Income (4300) - 500
    entries = LedgerEntry.objects.filter(invoice=invoice)
    assert entries.count() == 4

    emi_rec = entries.get(accounting_code__code="1200")
    assert emi_rec.type == "DEBIT"
    assert emi_rec.amount == Decimal("10000.00")

    inst_due = entries.get(accounting_code__code="2500")
    assert inst_due.type == "CREDIT"
    assert inst_due.amount == Decimal("8000.00")

    int_inc = entries.get(accounting_code__code="4200")
    assert int_inc.type == "CREDIT"
    assert int_inc.amount == Decimal("1500.00")

    pen_inc = entries.get(accounting_code__code="4300")
    assert pen_inc.type == "CREDIT"
    assert pen_inc.amount == Decimal("500.00")

    # 4. Create customer payment receipt (amount_received = 10000.00)
    payment = PaymentReceived.objects.create(
        payment_number="PR-EMI-TEST-001",
        customer=plan.customer,
        amount_received=Decimal("10000.00"),
        payment_date=timezone.now(),
        payment_method="CASH",
        deposited_to=bank_acc.accounting_code,
        invoices=[{"invoice_id": invoice.id, "amount_applied": 10000.00}]
    )

    # Process payment
    payment.process_payment()

    # Assert Payment ledger entries:
    # Dr Bank (deposited_to) - 10000
    # Cr EMI Receivable (1200) - 10000
    # Dr Installment Due (2500) - 8000 (Principal allocation)
    # Cr Customer Loan Receivable (1300) - 8000 (Principal allocation)
    pay_entries = LedgerEntry.objects.filter(payment_received=payment)
    assert pay_entries.count() == 4

    dr_bank = pay_entries.get(accounting_code=bank_acc.accounting_code)
    assert dr_bank.type == "DEBIT"
    assert dr_bank.amount == Decimal("10000.00")

    cr_emi_rec = pay_entries.get(accounting_code__code="1200")
    assert cr_emi_rec.type == "CREDIT"
    assert cr_emi_rec.amount == Decimal("10000.00")

    dr_inst_due = pay_entries.get(accounting_code__code="2500")
    assert dr_inst_due.type == "DEBIT"
    assert dr_inst_due.amount == Decimal("8000.00")

    cr_loan_rec = pay_entries.get(accounting_code__code="1300")
    assert cr_loan_rec.type == "CREDIT"
    assert cr_loan_rec.amount == Decimal("8000.00")

    # Verify that the CustomerLoanLedgerEntry has updated balances
    last_cust = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan, entry_type="EMI_PAYMENT").first()
    assert last_cust is not None
    assert last_cust.outstanding_principal == Decimal("0.00")


def test_settlement_paid_via_direct_bill_payment(accounting_setup):
    plan = accounting_setup["plan"]
    store = accounting_setup["store"]
    bank_acc = accounting_setup["bank_account"]

    # 1. Disburse loan ($400)
    AccountingEngineService.disburse_loan(plan.id, 400.00, "First partial disbursement")

    settlement = MerchantSettlement.objects.filter(finance_plan=plan).first()
    assert settlement.status == "PENDING"
    assert settlement.bill is not None
    assert settlement.bill.status == "PENDING"

    # 2. Pay the bill directly using PaymentMade
    payment_made = PaymentMade.objects.create(
        payment_number="PM-DIRECT-TEST-999",
        vendor=settlement.bill.vendor,
        amount_paid=Decimal("400.00"),
        payment_date=timezone.now().date(),
        payment_method="BANK_TRANSFER",
        paid_from=bank_acc.accounting_code,
        bills=[{"bill_id": settlement.bill.id, "amount_applied": 400.00}]
    )
    payment_made.process_payment()

    # 3. Verify connected bill, settlement, and bank balance
    settlement.refresh_from_db()
    settlement.bill.refresh_from_db()
    
    assert settlement.status == "PAID"
    assert settlement.bill.status == "PAID"
    assert settlement.payment_reference == "PM-DIRECT-TEST-999"
    assert BankAccount.objects.get(id=bank_acc.id).current_balance == Decimal("4600.00") # 5000 - 400

    # Assert Merchant outstanding subledger balance goes to 0
    last_merch = MerchantLedgerEntry.objects.filter(store=store).order_by("-id").first()
    assert last_merch.entry_type == "SETTLEMENT_PAYMENT"
    assert last_merch.outstanding_balance == Decimal("0.00")

    # Assert traceability ledger links exist
    ledgers = LedgerEntry.objects.filter(payment_made=payment_made)
    assert ledgers.count() == 2
    for le in ledgers:
        assert le.settlement == settlement
        if le.type == "DEBIT":
            assert le.merchant_ledger_entry == last_merch


def test_bank_account_balance_recalculation_signals(accounting_setup):
    from finance.models import BankAccount, LedgerEntry, JournalEntry
    bank_acc = accounting_setup["bank_account"]
    initial_bal = bank_acc.initial_balance  # 5000.00
    
    # Assert initial balance is set correctly
    assert bank_acc.current_balance == initial_bal

    # Create dummy journal entry
    journal = JournalEntry.objects.create(
        reference_number="JR-SIGNAL-TEST",
        entry_date=timezone.now().date(),
        description="Signal test journal"
    )

    # 1. Create a Debit LedgerEntry for the bank account's accounting code
    le1 = LedgerEntry.objects.create(
        journal_entry=journal,
        accounting_code=bank_acc.accounting_code,
        type="DEBIT",
        amount=Decimal("150.00"),
        description="Test debit deposit",
        entry_date=timezone.now()
    )

    # The post-save signal should run and update the current balance (5000 + 150 = 5150)
    bank_acc.refresh_from_db()
    assert bank_acc.current_balance == initial_bal + Decimal("150.00")

    # 2. Create a Credit LedgerEntry for the bank account's accounting code
    le2 = LedgerEntry.objects.create(
        journal_entry=journal,
        accounting_code=bank_acc.accounting_code,
        type="CREDIT",
        amount=Decimal("50.00"),
        description="Test credit withdrawal",
        entry_date=timezone.now()
    )

    # The post-save signal should run and update the current balance (5150 - 50 = 5100)
    bank_acc.refresh_from_db()
    assert bank_acc.current_balance == initial_bal + Decimal("150.00") - Decimal("50.00")

    # 3. Delete the Debit LedgerEntry
    le1.delete()

    # The post-delete signal should run and update the current balance (5000 - 50 = 4950)
    bank_acc.refresh_from_db()
    assert bank_acc.current_balance == initial_bal - Decimal("50.00")


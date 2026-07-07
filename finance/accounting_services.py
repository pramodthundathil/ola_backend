import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
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
    Vendor,
    PaymentReceived,
    PaymentMade,
    Bill
)

logger = logging.getLogger(__name__)

def ensure_chart_accounts():
    """
    Ensures that standard chart of account codes required for loan processing exist.
    """
    from finance.models import AccountingCode
    DEFAULT_CODES = [
        {"code": "1100", "name": "Cash & Bank", "category": "ASSET"},
        {"code": "1200", "name": "EMI Receivable - Customer", "category": "ASSET"},
        {"code": "1300", "name": "Customer Loan Receivable", "category": "ASSET"},
        {"code": "2100", "name": "Accounts Payable", "category": "LIABILITY"},
        {"code": "2500", "name": "Installment Due (Principal) / Loan Installment Payable", "category": "LIABILITY"},
        {"code": "4200", "name": "Interest Income", "category": "REVENUE"},
        {"code": "4300", "name": "Penalty Income", "category": "REVENUE"},
        {"code": "6200", "name": "Bad Debt Write-off Expense", "category": "EXPENSE"},
    ]
    for item in DEFAULT_CODES:
        ac, created = AccountingCode.objects.get_or_create(
            code=item["code"],
            defaults={"name": item["name"], "category": item["category"], "is_active": True}
        )
        if not created and ac.name != item["name"]:
            ac.name = item["name"]
            ac.save(update_fields=["name"])


class AccountingEngineService:

    @staticmethod
    @transaction.atomic
    def disburse_loan(finance_plan_id, amount, description=None):
        """
        Processes a full or partial loan disbursement.
        1. Debits Customer Loan Receivable (1300) - Asset increases.
        2. Credits Merchant Payable (24xx) - Liability increases.
        3. Updates Customer Loan Subledger.
        4. Updates Merchant Subledger & Settlement lists.
        """
        ensure_chart_accounts()
        plan = FinancePlan.objects.select_for_update().get(id=finance_plan_id)
        
        if plan.status == "DRAFT":
            raise ValueError("Cannot disburse a loan in DRAFT status. Please activate the loan first.")

        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Disbursement amount must be greater than zero.")

        # Check that we do not exceed the plan's amount_to_finance
        disbursed_total = LoanDisbursement.objects.filter(
            finance_plan=plan, 
            status='COMPLETED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        if disbursed_total + amount > plan.amount_to_finance:
            raise ValueError(
                f"Cannot disburse {amount}. Already disbursed {disbursed_total} "
                f"out of total amount to finance {plan.amount_to_finance}."
            )

        store = plan.store
        if not store:
            raise ValueError("This loan plan is not linked to any store (merchant).")
        
        if not store.accounting_code:
            store.save()  # Auto-generates accounting_code for the store

        # Generate disbursement numbers
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        disb_num = f"DSB-{plan.id}-{timestamp}"
        
        # Create LoanDisbursement
        disbursement = LoanDisbursement.objects.create(
            finance_plan=plan,
            disbursement_number=disb_num,
            amount=amount,
            disbursed_at=timezone.now(),
            status='COMPLETED',
            description=description or f"Disbursement of {amount} for plan {plan.id}"
        )

        # Update FinancePlan model status fields directly
        plan.disbursement_status = 'DISBURSED'
        plan.disbursed_at = disbursement.disbursed_at
        plan.save(update_fields=['disbursement_status', 'disbursed_at'])

        # Transition related EMI schedules from DRAFT to UPCOMING
        plan.emi_schedule.filter(status='DRAFT').update(status='UPCOMING')

        # Accounts
        ar_loan_code = AccountingCode.objects.get(code="1300")
        ap_merchant_code = store.accounting_code

        # General Ledger Journal Entry
        journal = JournalEntry.objects.create(
            reference_number=disb_num,
            entry_date=timezone.now().date(),
            description=description or f"Disbursement for loan plan ID={plan.id} at Store={store.name}"
        )

        # Ledger Entry: Debit Customer Loan Receivable
        le_dr = LedgerEntry.objects.create(
            journal_entry=journal,
            disbursement=disbursement,
            accounting_code=ar_loan_code,
            type='DEBIT',
            amount=amount,
            description=f"Loan receivable recognized for plan ID={plan.id}",
            entry_date=timezone.now()
        )

        # Ledger Entry: Credit Store Payable
        le_cr = LedgerEntry.objects.create(
            journal_entry=journal,
            disbursement=disbursement,
            accounting_code=ap_merchant_code,
            type='CREDIT',
            amount=amount,
            description=f"Merchant payable recognized for store={store.name} under plan ID={plan.id}",
            entry_date=timezone.now()
        )

        # Customer Loan Subledger Posting
        last_cust_entry = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by('-entry_date', '-id').first()
        if not last_cust_entry:
            op_p = amount
            op_i = Decimal('0.00')
            op_pen = Decimal('0.00')
        else:
            op_p = last_cust_entry.outstanding_principal + amount
            op_i = last_cust_entry.outstanding_interest
            op_pen = last_cust_entry.outstanding_penalties
            
        op_bal = op_p + op_i + op_pen

        cust_ledger = CustomerLoanLedgerEntry.objects.create(
            finance_plan=plan,
            customer=plan.customer,
            entry_type='DISBURSEMENT',
            type='DEBIT',
            amount=amount,
            principal_amount=amount,
            outstanding_principal=op_p,
            outstanding_interest=op_i,
            outstanding_penalties=op_pen,
            outstanding_balance=op_bal,
            reference_number=disb_num,
            description=f"Disbursement of principal amount {amount}",
            entry_date=timezone.now()
        )

        # Merchant Subledger & Settlement Posting
        settlement_num = f"SET-{plan.id}-{timestamp}"
        settlement = MerchantSettlement.objects.create(
            store=store,
            finance_plan=plan,
            settlement_number=settlement_num,
            amount=amount,
            status='PENDING'
        )

        # Create connected Bill
        vendor = getattr(store, 'vendor', None)
        if not vendor:
            vendor_name = store.name
            if len(vendor_name) > 100:
                vendor_name = vendor_name[:100]
            if Vendor.objects.filter(name=vendor_name).exists():
                vendor_name = f"{vendor_name} ({store.code})"
                if len(vendor_name) > 100:
                    vendor_name = vendor_name[:100]
            vendor, _ = Vendor.objects.get_or_create(
                name=vendor_name,
                defaults={
                    "contact_name": getattr(store, 'legal_representative', None) or store.name,
                    "email": store.email,
                    "phone": store.phone,
                    "tax_id": getattr(store, 'ruc', None),
                    "is_active": True
                }
            )
            store.vendor = vendor
            store.save(update_fields=['vendor'])

        bill_num = f"BILL-SET-{plan.id}-{timestamp}"
        line_items_data = [{
            "name": f"Settlement payable for Store {store.name}",
            "qty": 1,
            "unit_price": float(amount),
            "expense_account_id": store.accounting_code.id if store.accounting_code else None,
            "tax_rate_id": None,
            "tax_rate": 0.00,
            "tax_amount": 0.00,
            "total": float(amount)
        }]

        bill = Bill.objects.create(
            bill_number=bill_num,
            vendor=vendor,
            bill_date=timezone.now().date(),
            due_date=timezone.now().date(),
            subtotal=amount,
            tax_amount=Decimal('0.00'),
            total_amount=amount,
            balance=amount,
            amount_paid=Decimal('0.00'),
            status='PENDING',
            line_items=line_items_data,
            notes=f"Connected bill for merchant settlement {settlement_num}"
        )
        bill.generate_ledger_entries()

        settlement.bill = bill
        settlement.save(update_fields=['bill'])

        last_merch_entry = MerchantLedgerEntry.objects.filter(store=store).order_by('-entry_date', '-id').first()
        if not last_merch_entry:
            om_bal = amount
        else:
            om_bal = last_merch_entry.outstanding_balance + amount

        merch_ledger = merch_ledger = MerchantLedgerEntry.objects.create(
            store=store,
            finance_plan=plan,
            settlement=settlement,
            entry_type='SETTLEMENT_CREATION',
            type='CREDIT',
            amount=amount,
            outstanding_balance=om_bal,
            description=f"Settlement creation for loan disbursement {disb_num}",
            entry_date=timezone.now()
        )

        # Link bill's ledger entries to settlement and merch_ledger
        for le in LedgerEntry.objects.filter(bill=bill):
            le.settlement = settlement
            if le.type == 'DEBIT':
                le.merchant_ledger_entry = merch_ledger
            le.save(update_fields=['settlement', 'merchant_ledger_entry'])

        # Link trace entries back to GL
        le_dr.customer_loan_ledger_entry = cust_ledger
        le_dr.save(update_fields=['customer_loan_ledger_entry'])
        le_cr.merchant_ledger_entry = merch_ledger
        le_cr.save(update_fields=['merchant_ledger_entry'])

        logger.info(f"Disbursed {amount} for plan {plan.id}. Created disb={disb_num}, settlement={settlement_num}")
        return disbursement

    @staticmethod
    @transaction.atomic
    def settle_merchant(settlement_id, bank_account_id, payment_reference, date_val=None):
        """
        Settles a pending merchant payable balance via bank transfer.
        1. Debits Merchant Payable (24xx) - Liability decreases.
        2. Credits Bank Account GL - Asset decreases.
        3. Updates Merchant subledger.
        """
        settlement = MerchantSettlement.objects.select_for_update().get(id=settlement_id)
        if settlement.status != 'PENDING':
            raise ValueError(f"Settlement is not in PENDING state (current: {settlement.status}).")

        bank_acc = BankAccount.objects.select_for_update().get(id=bank_account_id)
        if not bank_acc.accounting_code:
            raise ValueError(f"Bank Account {bank_acc.account_name} does not have an accounting code.")

        amount = settlement.amount
        if bank_acc.current_balance < amount:
            logger.warning(f"Bank Account {bank_acc.account_name} has insufficient balance ({bank_acc.current_balance} < {amount}). Proceeding anyway.")

        # Update settlement details
        settlement.status = 'PAID'
        settlement.payment_reference = payment_reference
        settlement.settled_at = date_val or timezone.now()
        settlement.bank_account = bank_acc
        settlement.save()

        store = settlement.store
        ap_merchant_code = store.accounting_code
        bank_gl_code = bank_acc.accounting_code
        vendor = getattr(store, 'vendor', None)
        if not vendor:
            vendor, _ = Vendor.objects.get_or_create(
                name=store.name,
                defaults={'code': f"VND-{store.code or store.id[:8]}"}
            )

        # Create PaymentMade object
        payment_num = f"PM-{settlement.settlement_number}"
        payment_made = PaymentMade.objects.create(
            payment_number=payment_num,
            vendor=vendor,
            amount_paid=amount,
            payment_date=(date_val or timezone.now()).date(),
            payment_method='BANK_TRANSFER',
            paid_from=bank_gl_code,
            bills=[{"bill_id": settlement.bill.id, "amount_applied": float(amount)}] if settlement.bill else [],
            notes=f"Merchant settlement payment to Store={store.name} Ref={payment_reference}"
        )

        # Update Merchant Subledger
        last_merch_entry = MerchantLedgerEntry.objects.filter(store=store).order_by('-entry_date', '-id').first()
        om_bal = (last_merch_entry.outstanding_balance if last_merch_entry else Decimal('0.00')) - amount

        merch_ledger = MerchantLedgerEntry.objects.create(
            store=store,
            finance_plan=settlement.finance_plan,
            settlement=settlement,
            entry_type='SETTLEMENT_PAYMENT',
            type='DEBIT',
            amount=amount,
            payment_reference=payment_reference,
            outstanding_balance=om_bal,
            description=f"Settlement payment cleared via Bank={bank_acc.bank_name} Ref={payment_reference}",
            entry_date=date_val or timezone.now()
        )

        if settlement.bill:
            payment_made.process_payment()
            # Update the created ledger entries with settlement and merchant_ledger_entry references
            for le in LedgerEntry.objects.filter(payment_made=payment_made):
                le.settlement = settlement
                if le.type == 'DEBIT':
                    le.merchant_ledger_entry = merch_ledger
                le.save(update_fields=['settlement', 'merchant_ledger_entry'])
        else:
            # Legacy logic
            # Journal Entry
            payment_num_str = f"STPY-{settlement.settlement_number}"
            journal = JournalEntry.objects.create(
                reference_number=payment_num_str,
                entry_date=(date_val or timezone.now()).date(),
                description=f"Merchant settlement payment to Store={store.name} Ref={payment_reference}"
            )

            # Debit: Store Payable GL (reduces liability)
            le_dr = LedgerEntry.objects.create(
                journal_entry=journal,
                settlement=settlement,
                payment_made=payment_made,
                accounting_code=ap_merchant_code,
                type='DEBIT',
                amount=amount,
                description=f"Merchant payable cleared for settlement {settlement.settlement_number}",
                entry_date=date_val or timezone.now()
            )

            # Credit: Bank Account GL (reduces asset)
            le_cr = LedgerEntry.objects.create(
                journal_entry=journal,
                settlement=settlement,
                payment_made=payment_made,
                accounting_code=bank_gl_code,
                type='CREDIT',
                amount=amount,
                description=f"Settlement payment disbursed from Bank={bank_acc.bank_name}",
                entry_date=date_val or timezone.now()
            )

            # Link trace entries
            le_dr.merchant_ledger_entry = merch_ledger
            le_dr.save(update_fields=['merchant_ledger_entry'])
        
        # Update Bank Account Balance (only for legacy flow, since process_payment handles it otherwise)
        if not settlement.bill:
            bank_acc.recalculate_balance()

        logger.info(f"Settled merchant store={store.name} for amount={amount}. Bank={bank_acc.account_name}")
        return settlement

    @staticmethod
    @transaction.atomic
    def post_customer_payment(finance_plan_id, payment_received_id, principal_portion, interest_portion, penalty_portion):
        """
        Posts customer loan repayment subledger and GL entries.
        1. Debits Bank Account (deposited_to) - Asset increases.
        2. Credits Customer Loan Receivable (1300) - Asset decreases.
        3. Credits Interest/Financing Revenue (4200) - Revenue increases.
        4. Credits Penalty Revenue (4300) - Revenue increases.
        """
        ensure_chart_accounts()
        plan = FinancePlan.objects.select_for_update().get(id=finance_plan_id)
        payment = PaymentReceived.objects.get(id=payment_received_id)

        principal_portion = Decimal(str(principal_portion))
        interest_portion = Decimal(str(interest_portion))
        penalty_portion = Decimal(str(penalty_portion))
        total_applied = principal_portion + interest_portion + penalty_portion

        last_cust_entry = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by('-entry_date', '-id').first()
        if not last_cust_entry:
            raise ValueError(f"No disbursement ledger entry exists for plan ID={plan.id}. Repayment rejected.")

        op_p = max(Decimal('0.00'), last_cust_entry.outstanding_principal - principal_portion)
        op_i = max(Decimal('0.00'), last_cust_entry.outstanding_interest - interest_portion)
        op_pen = max(Decimal('0.00'), last_cust_entry.outstanding_penalties - penalty_portion)
        op_bal = op_p + op_i + op_pen

        # Customer Loan Subledger posting
        cust_ledger = CustomerLoanLedgerEntry.objects.create(
            finance_plan=plan,
            customer=plan.customer,
            entry_type='EMI_PAYMENT',
            type='CREDIT',
            amount=total_applied,
            principal_amount=principal_portion,
            interest_amount=interest_portion,
            penalty_amount=penalty_portion,
            outstanding_principal=op_p,
            outstanding_interest=op_i,
            outstanding_penalties=op_pen,
            outstanding_balance=op_bal,
            reference_number=payment.payment_number,
            description=f"Repayment: Principal={principal_portion}, Interest={interest_portion}, Penalty={penalty_portion}",
            entry_date=payment.payment_date
        )

        # General Ledger balanced entry
        journal = JournalEntry.objects.create(
            reference_number=f"LNPAY-{payment.payment_number}",
            entry_date=payment.payment_date.date(),
            description=f"Loan payment for customer={plan.customer.first_name} plan ID={plan.id}"
        )

        # Debit: Bank Account GL (Asset increases)
        le_dr = LedgerEntry.objects.create(
            journal_entry=journal,
            payment_received=payment,
            customer_loan_ledger_entry=cust_ledger,
            accounting_code=payment.deposited_to,
            type='DEBIT',
            amount=total_applied,
            description=f"Bank deposit from customer payment {payment.payment_number}",
            entry_date=payment.payment_date
        )

        # Credit EMI Receivable (1200) - Asset decreases by the total applied amount
        LedgerEntry.objects.create(
            journal_entry=journal,
            payment_received=payment,
            customer_loan_ledger_entry=cust_ledger,
            accounting_code=AccountingCode.objects.get(code="1200"),
            type='CREDIT',
            amount=total_applied,
            description=f"EMI Receivable reduction for plan ID={plan.id} via payment {payment.payment_number}",
            entry_date=payment.payment_date
        )

        # Principal Allocation clearing logic:
        if principal_portion > 0:
            # Debit: Principal Due (2500)
            LedgerEntry.objects.create(
                journal_entry=journal,
                payment_received=payment,
                customer_loan_ledger_entry=cust_ledger,
                accounting_code=AccountingCode.objects.get(code="2500"),
                type='DEBIT',
                amount=principal_portion,
                description=f"Principal allocation from clearing account for plan ID={plan.id}",
                entry_date=payment.payment_date
            )

            # Credit: Customer Loan Receivable (1300) - reduces outstanding loan principal
            LedgerEntry.objects.create(
                journal_entry=journal,
                payment_received=payment,
                customer_loan_ledger_entry=cust_ledger,
                accounting_code=AccountingCode.objects.get(code="1300"),
                type='CREDIT',
                amount=principal_portion,
                description=f"Principal loan receivable reduction for plan ID={plan.id}",
                entry_date=payment.payment_date
            )

        # Check closure
        if op_bal <= 0:
            plan.status = "CLOSED"
            plan.save(update_fields=['status'])
            
            CustomerLoanLedgerEntry.objects.create(
                finance_plan=plan,
                customer=plan.customer,
                entry_type='CLOSURE',
                type='CREDIT',
                amount=Decimal('0.00'),
                outstanding_principal=Decimal('0.00'),
                outstanding_interest=Decimal('0.00'),
                outstanding_penalties=Decimal('0.00'),
                outstanding_balance=Decimal('0.00'),
                description="Loan marked as CLOSED. Fully settled.",
                entry_date=timezone.now()
            )
            logger.info(f"Loan plan ID={plan.id} has been fully settled and closed.")

        return cust_ledger

    @staticmethod
    @transaction.atomic
    def charge_interest_or_penalty(finance_plan_id, amount, charge_type, description=None):
        """
        Manually charges customer loan interest or penalties.
        1. Debits Customer Loan Receivable (1300) - Asset increases.
        2. Credits Interest Revenue (4200) or Penalty Revenue (4300) - Revenue increases.
        3. Updates Customer Loan Subledger.
        """
        ensure_chart_accounts()
        plan = FinancePlan.objects.select_for_update().get(id=finance_plan_id)
        
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Charge amount must be greater than zero.")

        last_cust_entry = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by('-entry_date', '-id').first()
        if not last_cust_entry:
            raise ValueError(f"Cannot charge fees/interest on plan ID={plan.id} because it has not been disbursed.")

        import random
        rand_suffix = str(random.randint(1000, 9999))
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
        ref_num = f"CHG-{plan.id}-{timestamp}-{rand_suffix}"

        if charge_type == 'INTEREST':
            op_p = last_cust_entry.outstanding_principal
            op_i = last_cust_entry.outstanding_interest + amount
            op_pen = last_cust_entry.outstanding_penalties
            entry_t = 'INTEREST_ACCRUAL'
            gl_rev_code = "4200"
            desc = description or f"Accrued interest of {amount}"
        elif charge_type == 'PENALTY':
            op_p = last_cust_entry.outstanding_principal
            op_i = last_cust_entry.outstanding_interest
            op_pen = last_cust_entry.outstanding_penalties + amount
            entry_t = 'PENALTY_CHARGED'
            gl_rev_code = "4300"
            desc = description or f"Charged penalty of {amount}"
        else:
            raise ValueError("Invalid charge_type. Must be INTEREST or PENALTY.")

        op_bal = op_p + op_i + op_pen

        # Subledger entry
        cust_ledger = CustomerLoanLedgerEntry.objects.create(
            finance_plan=plan,
            customer=plan.customer,
            entry_type=entry_t,
            type='DEBIT',
            amount=amount,
            principal_amount=Decimal('0.00'),
            interest_amount=amount if charge_type == 'INTEREST' else Decimal('0.00'),
            penalty_amount=amount if charge_type == 'PENALTY' else Decimal('0.00'),
            outstanding_principal=op_p,
            outstanding_interest=op_i,
            outstanding_penalties=op_pen,
            outstanding_balance=op_bal,
            reference_number=ref_num,
            description=desc,
            entry_date=timezone.now()
        )

        # GL Journal Entry
        journal = JournalEntry.objects.create(
            reference_number=ref_num,
            entry_date=timezone.now().date(),
            description=desc
        )

        # Debit: Customer Loan Receivable
        LedgerEntry.objects.create(
            journal_entry=journal,
            customer_loan_ledger_entry=cust_ledger,
            accounting_code=AccountingCode.objects.get(code="1300"),
            type='DEBIT',
            amount=amount,
            description=f"Accrued debt balance increase for plan ID={plan.id}",
            entry_date=timezone.now()
        )

        # Credit: Revenue account
        LedgerEntry.objects.create(
            journal_entry=journal,
            customer_loan_ledger_entry=cust_ledger,
            accounting_code=AccountingCode.objects.get(code=gl_rev_code),
            type='CREDIT',
            amount=amount,
            description=f"Revenue recognized for fee/interest on plan ID={plan.id}",
            entry_date=timezone.now()
        )

        logger.info(f"Charged {charge_type} of {amount} to plan ID={plan.id}. New balance={op_bal}")
        return cust_ledger

    @staticmethod
    @transaction.atomic
    def write_off_loan(finance_plan_id, reason=None):
        """
        Writes off all outstanding principal, interest, and penalties to zero.
        1. Debits Bad Debt Write-off Expense (6200) - Expense increases.
        2. Credits Customer Loan Receivable (1300) - Asset decreases.
        3. Updates Customer Loan Subledger.
        """
        ensure_chart_accounts()
        plan = FinancePlan.objects.select_for_update().get(id=finance_plan_id)
        
        last_cust_entry = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by('-entry_date', '-id').first()
        if not last_cust_entry or last_cust_entry.outstanding_balance <= 0:
            raise ValueError(f"No outstanding debt to write off on plan ID={plan.id}.")

        write_off_amt = last_cust_entry.outstanding_balance
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        ref_num = f"WO-{plan.id}-{timestamp}"

        # Subledger entry
        cust_ledger = CustomerLoanLedgerEntry.objects.create(
            finance_plan=plan,
            customer=plan.customer,
            entry_type='WRITE_OFF',
            type='CREDIT',
            amount=write_off_amt,
            principal_amount=last_cust_entry.outstanding_principal,
            interest_amount=last_cust_entry.outstanding_interest,
            penalty_amount=last_cust_entry.outstanding_penalties,
            outstanding_principal=Decimal('0.00'),
            outstanding_interest=Decimal('0.00'),
            outstanding_penalties=Decimal('0.00'),
            outstanding_balance=Decimal('0.00'),
            reference_number=ref_num,
            description=reason or f"Loan write off of total balance {write_off_amt}",
            entry_date=timezone.now()
        )

        # GL Journal
        journal = JournalEntry.objects.create(
            reference_number=ref_num,
            entry_date=timezone.now().date(),
            description=f"Bad debt write-off for plan ID={plan.id}. Reason: {reason}"
        )

        # Debit: Write-off expense
        LedgerEntry.objects.create(
            journal_entry=journal,
            customer_loan_ledger_entry=cust_ledger,
            accounting_code=AccountingCode.objects.get(code="6200"),
            type='DEBIT',
            amount=write_off_amt,
            description=f"Write-off expense recorded for plan ID={plan.id}",
            entry_date=timezone.now()
        )

        # Credit: Customer Loan Receivable
        LedgerEntry.objects.create(
            journal_entry=journal,
            customer_loan_ledger_entry=cust_ledger,
            accounting_code=AccountingCode.objects.get(code="1300"),
            type='CREDIT',
            amount=write_off_amt,
            description=f"Receivable cleared via bad-debt write-off for plan ID={plan.id}",
            entry_date=timezone.now()
        )

        plan.status = "CLOSED"
        plan.save(update_fields=['status'])

        logger.info(f"Loan ID={plan.id} written off. Amount={write_off_amt}")
        return cust_ledger

    @staticmethod
    @transaction.atomic
    def reverse_disbursement(disbursement_id):
        """
        Reverses a completed disbursement and cancels the associated merchant settlement.
        1. Debits Merchant Payable (24xx) - Liability decreases.
        2. Credits Customer Loan Receivable (1300) - Asset decreases.
        3. Updates subledgers.
        """
        disb = LoanDisbursement.objects.select_for_update().get(id=disbursement_id)
        if disb.status != 'COMPLETED':
            raise ValueError(f"Disbursement is not in COMPLETED state (current: {disb.status}).")

        plan = disb.finance_plan
        store = plan.store

        # Check if merchant settlement has already been paid
        settlements = MerchantSettlement.objects.filter(finance_plan=plan, amount=disb.amount, status='PENDING')
        if not settlements.exists():
            # Check if any matching settlement was paid
            paid_settlements = MerchantSettlement.objects.filter(finance_plan=plan, amount=disb.amount, status='PAID')
            if paid_settlements.exists():
                raise ValueError("Cannot reverse disbursement because merchant settlement has already been paid. Reverse settlement first.")
            raise ValueError("No matching pending merchant settlement found for this disbursement.")

        settlement = settlements.first()

        # Update statuses
        disb.status = 'CANCELLED'
        disb.save()

        settlement.status = 'CANCELLED'
        settlement.save()

        # GL Reversal Entry
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        ref_num = f"REV-{disb.disbursement_number}"
        journal = JournalEntry.objects.create(
            reference_number=ref_num,
            entry_date=timezone.now().date(),
            description=f"Reversal of disbursement {disb.disbursement_number}"
        )

        # Debit: Store Payable ( Liability Decreases)
        LedgerEntry.objects.create(
            journal_entry=journal,
            disbursement=disb,
            accounting_code=store.accounting_code,
            type='DEBIT',
            amount=disb.amount,
            description=f"Reversal of store payable for cancelled disbursement {disb.disbursement_number}",
            entry_date=timezone.now()
        )

        # Credit: Customer Loan Receivable (Asset Decreases)
        LedgerEntry.objects.create(
            journal_entry=journal,
            disbursement=disb,
            accounting_code=AccountingCode.objects.get(code="1300"),
            type='CREDIT',
            amount=disb.amount,
            description=f"Reversal of customer loan receivable for cancelled disbursement {disb.disbursement_number}",
            entry_date=timezone.now()
        )

        # Update Customer Subledger
        last_cust_entry = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by('-entry_date', '-id').first()
        op_p = max(Decimal('0.00'), last_cust_entry.outstanding_principal - disb.amount)
        op_i = last_cust_entry.outstanding_interest
        op_pen = last_cust_entry.outstanding_penalties
        op_bal = op_p + op_i + op_pen

        CustomerLoanLedgerEntry.objects.create(
            finance_plan=plan,
            customer=plan.customer,
            entry_type='REVERSAL',
            type='CREDIT',
            amount=disb.amount,
            principal_amount=disb.amount,
            outstanding_principal=op_p,
            outstanding_interest=op_i,
            outstanding_penalties=op_pen,
            outstanding_balance=op_bal,
            reference_number=ref_num,
            description=f"Reversal of disbursement {disb.disbursement_number}",
            entry_date=timezone.now()
        )

        # Update Merchant Subledger
        last_merch_entry = MerchantLedgerEntry.objects.filter(store=store).order_by('-entry_date', '-id').first()
        om_bal = max(Decimal('0.00'), (last_merch_entry.outstanding_balance if last_merch_entry else Decimal('0.00')) - disb.amount)

        MerchantLedgerEntry.objects.create(
            store=store,
            finance_plan=plan,
            settlement=settlement,
            entry_type='CANCELLATION',
            type='DEBIT',
            amount=disb.amount,
            outstanding_balance=om_bal,
            description=f"Cancellation of settlement {settlement.settlement_number} due to disbursement reversal",
            entry_date=timezone.now()
        )

        logger.info(f"Successfully reversed disbursement {disb.disbursement_number}")
        return disb

    @staticmethod
    @transaction.atomic
    def cancel_settlement(settlement_id):
        """
        Cancels a pending settlement, clearing the merchant outstanding balance.
        """
        settlement = MerchantSettlement.objects.select_for_update().get(id=settlement_id)
        if settlement.status != 'PENDING':
            raise ValueError(f"Cannot cancel settlement in state {settlement.status}.")

        store = settlement.store
        settlement.status = 'CANCELLED'
        settlement.save()

        # Update subledger
        last_merch_entry = MerchantLedgerEntry.objects.filter(store=store).order_by('-entry_date', '-id').first()
        om_bal = max(Decimal('0.00'), (last_merch_entry.outstanding_balance if last_merch_entry else Decimal('0.00')) - settlement.amount)

        MerchantLedgerEntry.objects.create(
            store=store,
            finance_plan=settlement.finance_plan,
            settlement=settlement,
            entry_type='CANCELLATION',
            type='DEBIT',
            amount=settlement.amount,
            outstanding_balance=om_bal,
            description=f"Manual cancellation of settlement {settlement.settlement_number}",
            entry_date=timezone.now()
        )

        # Create GL journal entry to reverse the merchant payable balance
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        ref_num = f"CSL-{settlement.settlement_number}"
        journal = JournalEntry.objects.create(
            reference_number=ref_num,
            entry_date=timezone.now().date(),
            description=f"Cancellation of merchant settlement {settlement.settlement_number}"
        )

        # Debit: Store Payable GL ( Liability Decreases)
        LedgerEntry.objects.create(
            journal_entry=journal,
            settlement=settlement,
            accounting_code=store.accounting_code,
            type='DEBIT',
            amount=settlement.amount,
            description=f"Merchant payable debit adjustment for cancelled settlement {settlement.settlement_number}",
            entry_date=timezone.now()
        )

        # Credit: Bad Debt or Loan Adjustment account or write back to customer loan receivable?
        # Standard: since it is a settlement cancellation without disbursement reversal, we credit Customer Loan Receivable or an adjustment account
        LedgerEntry.objects.create(
            journal_entry=journal,
            settlement=settlement,
            accounting_code=AccountingCode.objects.get(code="1300"),
            type='CREDIT',
            amount=settlement.amount,
            description=f"Receivable credit adjustment due to merchant settlement cancellation {settlement.settlement_number}",
            entry_date=timezone.now()
        )

        logger.info(f"Cancelled merchant settlement {settlement.settlement_number}")
        return settlement

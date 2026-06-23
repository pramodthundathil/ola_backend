import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from finance.models import FinancePlan, EMISchedule

logger = logging.getLogger(__name__)

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from finance.models import FinancePlan, EMISchedule
from django.db import transaction

logger = logging.getLogger(__name__)

def seed_default_accounting_codes():
    from finance.models import AccountingCode
    DEFAULT_CODES = [
        {"code": "1100", "name": "Cash & Bank", "category": "ASSET"},
        {"code": "1200", "name": "Accounts Receivable", "category": "ASSET"},
        {"code": "2100", "name": "Accounts Payable", "category": "LIABILITY"},
        {"code": "2200", "name": "Advance Received From Customer", "category": "LIABILITY"},
        {"code": "2300", "name": "Tax Payable", "category": "LIABILITY"},
        {"code": "4100", "name": "Sales/Rental Income", "category": "REVENUE"},
        {"code": "4200", "name": "Interest/Financing Revenue", "category": "REVENUE"},
    ]
    for item in DEFAULT_CODES:
        AccountingCode.objects.get_or_create(
            code=item["code"],
            defaults={"name": item["name"], "category": item["category"]}
        )

@receiver(post_save, sender=FinancePlan)
def create_emi_schedule(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.emi_schedule.exists():
        logger.warning(f"[EMI SKIP] FinancePlan ID={instance.id} already has EMI schedules.")
        return

    frequency = instance.installment_frequency_days or 30
    first_due_date = timezone.now().date() + timedelta(days=frequency)

    try:
        with transaction.atomic():
            if frequency in [10, 15, 30]:
                EMISchedule.generate_schedule(instance, first_due_date)
                logger.info(f"[EMI CREATED] {frequency}-day EMI schedule for FinancePlan ID={instance.id}")
            else:
                # fallback to monthly installments
                EMISchedule.generate_schedule_emi(instance, first_due_date)
                logger.info(f"[EMI CREATED] Monthly EMI schedule for FinancePlan ID={instance.id}")

            # --- Seed accounting codes and generate Invoices/Ledgers
            seed_default_accounting_codes()

            from finance.models import Invoice
            from decimal import Decimal

            emis = instance.emi_schedule.all()
            for emi in emis:
                invoice_num = f"INV-FP{instance.id}-{emi.installment_number}"
                
                # 7% tax calculation
                tax_rate = Decimal('0.07')
                total = emi.installment_amount
                base = total / (Decimal('1.00') + tax_rate)
                base = base.quantize(Decimal('0.01'))
                tax = total - base

                invoice = Invoice.objects.create(
                    invoice_number=invoice_num,
                    customer=instance.customer,
                    finance_plan=instance,
                    emi_schedule=emi,
                    due_date=emi.due_date,
                    base_amount=base,
                    tax_amount=tax,
                    total_amount=total,
                    balance=total,
                    status='PENDING'
                )
                # Generate double-entry ledger entries for the invoice
                invoice.generate_ledger_entries()
                logger.info(f"[INVOICE CREATED] Generated invoice {invoice_num} for EMI installment {emi.installment_number}")

    except Exception as e:
        logger.exception(f"[EMI ERROR] Failed to generate EMI schedule or invoices for FinancePlan ID={instance.id}: {e}")
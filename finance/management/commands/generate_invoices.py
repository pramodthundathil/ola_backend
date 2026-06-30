import logging
from django.core.management.base import BaseCommand
from decimal import Decimal
from finance.models import FinancePlan, Invoice
from finance.signals import seed_default_accounting_codes

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Generate invoices for active finance plans EMIs'

    def handle(self, *args, **options):
        seed_default_accounting_codes()
        active_plans = FinancePlan.objects.filter(status='ACTIVE')
        self.stdout.write(f"Found {active_plans.count()} active plans.")
        
        invoices_created = 0
        for plan in active_plans:
            emis = plan.emi_schedule.all()
            for emi in emis:
                invoice_num = f"INV-FP{plan.id}-{emi.installment_number}"
                
                if Invoice.objects.filter(invoice_number=invoice_num).exists():
                    continue

                tax_rate = Decimal('0.07')
                total = emi.installment_amount
                base = total / (Decimal('1.00') + tax_rate)
                base = base.quantize(Decimal('0.01'))
                tax = total - base

                invoice = Invoice.objects.create(
                    invoice_number=invoice_num,
                    customer=plan.customer,
                    finance_plan=plan,
                    emi_schedule=emi,
                    due_date=emi.due_date,
                    base_amount=base,
                    tax_amount=tax,
                    total_amount=total,
                    balance=total,
                    status='PENDING'
                )
                invoice.generate_ledger_entries()
                invoices_created += 1
                logger.info(f"[CRON] Generated invoice {invoice_num} for FinancePlan ID={plan.id}")

        self.stdout.write(f"Successfully generated {invoices_created} invoices.")

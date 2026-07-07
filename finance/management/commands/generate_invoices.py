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
                if Invoice.objects.filter(emi_schedule=emi).exists():
                    continue

                # Generate unique sequential EMI invoice number
                invoice_number = None
                while not invoice_number:
                    last_inv = Invoice.objects.filter(invoice_number__startswith='OLA-EMI-').order_by('-id').first()
                    if last_inv:
                        try:
                            last_num = int(last_inv.invoice_number.split('-')[-1])
                            next_num = last_num + 1
                        except (ValueError, IndexError):
                            next_num = 1
                    else:
                        next_num = 1
                    candidate = f"OLA-EMI-{next_num:06d}"
                    if not Invoice.objects.filter(invoice_number=candidate).exists():
                        invoice_number = candidate

                total = emi.installment_amount
                tax = Decimal('0.00')
 
                invoice = Invoice.objects.create(
                    invoice_number=invoice_number,
                    customer=plan.customer,
                    finance_plan=plan,
                    emi_schedule=emi,
                    due_date=emi.due_date,
                    base_amount=total,
                    subtotal=total,
                    tax_amount=tax,
                    total_amount=total,
                    balance=total,
                    principal_amount=emi.principal,
                    interest_amount=emi.interest,
                    penalty_amount=Decimal('0.00'),
                    status='PENDING'
                )
                invoice.generate_ledger_entries()
                invoices_created += 1
                logger.info(f"[CRON] Generated invoice {invoice_number} for FinancePlan ID={plan.id}")

        self.stdout.write(f"Successfully generated {invoices_created} invoices.")

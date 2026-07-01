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
    if not created and instance.status != "DRAFT":
        return

    if not created and instance.status == "DRAFT":
        instance.emi_schedule.all().delete()
        logger.info(f"[EMI UPDATED] Cleared old EMI schedules for updated draft FinancePlan ID={instance.id}")

    if instance.emi_schedule.exists():
        logger.warning(f"[EMI SKIP] FinancePlan ID={instance.id} already has EMI schedules.")
        return

    frequency = instance.installment_frequency_days or 30
    first_due_date = timezone.now().date() + timedelta(days=frequency)

    try:
        with transaction.atomic():
            if frequency in [3, 7, 10, 15, 30]:
                EMISchedule.generate_schedule(instance, first_due_date)
                logger.info(f"[EMI CREATED] {frequency}-day EMI schedule for FinancePlan ID={instance.id}")
            else:
                # fallback to monthly installments
                EMISchedule.generate_schedule_emi(instance, first_due_date)
                logger.info(f"[EMI CREATED] Monthly EMI schedule for FinancePlan ID={instance.id}")



    except Exception as e:
        logger.exception(f"[EMI ERROR] Failed to generate EMI schedule or invoices for FinancePlan ID={instance.id}: {e}")


@receiver(post_save, sender='store.Store')
def create_store_vendor(sender, instance, created, **kwargs):
    if created:
        from finance.models import Vendor
        vendor_name = instance.name
        if len(vendor_name) > 100:
            vendor_name = vendor_name[:100]
            
        if Vendor.objects.filter(name=vendor_name).exists():
            vendor_name = f"{vendor_name} ({instance.code})"
            if len(vendor_name) > 100:
                vendor_name = vendor_name[:100]

        vendor, _ = Vendor.objects.get_or_create(
            name=vendor_name,
            defaults={
                "contact_name": instance.legal_representative or instance.name,
                "email": instance.email,
                "phone": instance.phone,
                "tax_id": instance.ruc,
                "is_active": True
            }
        )
        
        instance.vendor = vendor
        instance.save(update_fields=['vendor'])
        logger.info(f"[Store Signal] Linked Vendor ID={vendor.id} to Store ID={instance.id}")
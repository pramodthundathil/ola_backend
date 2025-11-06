import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from finance.models import FinancePlan, EMISchedule

logger = logging.getLogger(__name__)

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
        if frequency in [10, 15, 30]:
            EMISchedule.generate_schedule(instance, first_due_date)
            logger.info(f"[EMI CREATED] {frequency}-day EMI schedule for FinancePlan ID={instance.id}")
        else:
            # fallback to monthly installments
            EMISchedule.generate_schedule_emi(instance, first_due_date)
            logger.info(f"[EMI CREATED] Monthly EMI schedule for FinancePlan ID={instance.id}")

    except Exception as e:
        logger.exception(f"[EMI ERROR] Failed to generate EMI schedule for FinancePlan ID={instance.id}: {e}")
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from customer.models import Customer, CreditApplication
from finance.models import FinancePlan, PaymentRecord, EMISchedule
from analytics.tasks import (
    update_customer_analytics_task,
    update_daily_analytics_task,
    update_merchant_analytics_task,
    update_branch_analytics_task,
    update_device_analytics_task,
    update_risk_analytics_task,
    update_executive_analytics_task,
    update_collection_analytics_task
)

logger = logging.getLogger(__name__)


def safe_delay(task, *args, **kwargs):
    """
    Safely trigger a Celery task, catching any exceptions (e.g., Celery/Redis connection issues)
    to avoid blocking the main database transaction or request-response cycle.
    """
    try:
        task.delay(*args, **kwargs)
    except Exception as e:
        logger.error(
            f"Failed to queue celery task {task.__name__} asynchronously. "
            f"Error: {e}",
            exc_info=True
        )


@receiver(post_save, sender=Customer)
def customer_saved_handler(sender, instance, created, **kwargs):
    """Trigger update of customer metrics on customer creation"""
    date_str = timezone.now().strftime('%Y-%m-%d')
    safe_delay(update_customer_analytics_task, date_str)


@receiver(post_save, sender=CreditApplication)
def credit_application_saved_handler(sender, instance, created, **kwargs):
    """Trigger update of daily and executive funnel analytics"""
    date_str = instance.application_date.strftime('%Y-%m-%d') if getattr(instance, 'application_date', None) else timezone.now().strftime('%Y-%m-%d')
    safe_delay(update_daily_analytics_task, date_str)
    safe_delay(update_executive_analytics_task, date_str)


@receiver(post_save, sender=FinancePlan)
def finance_plan_saved_handler(sender, instance, created, **kwargs):
    """Trigger update of daily, store, and device aggregates on loan events"""
    date_str = instance.created_at.strftime('%Y-%m-%d') if getattr(instance, 'created_at', None) else timezone.now().strftime('%Y-%m-%d')
    safe_delay(update_daily_analytics_task, date_str)
    safe_delay(update_merchant_analytics_task, date_str)
    safe_delay(update_branch_analytics_task, date_str)
    safe_delay(update_device_analytics_task, date_str)


@receiver(post_save, sender=PaymentRecord)
def payment_record_saved_handler(sender, instance, created, **kwargs):
    """Trigger collections, merchant, branch, and risk updates on payment events"""
    date_str = instance.payment_date.strftime('%Y-%m-%d') if getattr(instance, 'payment_date', None) else timezone.now().strftime('%Y-%m-%d')
    safe_delay(update_collection_analytics_task, date_str)
    safe_delay(update_merchant_analytics_task, date_str)
    safe_delay(update_branch_analytics_task, date_str)
    safe_delay(update_risk_analytics_task, date_str)


@receiver(post_save, sender=EMISchedule)
def emi_schedule_saved_handler(sender, instance, created, **kwargs):
    """Trigger risk and collection analytics updates on EMI status updates"""
    date_str = timezone.now().strftime('%Y-%m-%d')
    safe_delay(update_risk_analytics_task, date_str)
    safe_delay(update_collection_analytics_task, date_str)

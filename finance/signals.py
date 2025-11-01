from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from finance.models import FinancePlan, EMISchedule
from products.models import ProductModel

@receiver(post_save, sender=ProductModel)
def clear_device_price_cache(sender, instance, **kwargs):
    cache_key = f"device_price_{instance.id}"
    cache.delete(cache_key)

# ============================================================
# SIGNAL: Auto-generate EMI schedule after FinancePlan creation
# ============================================================
@receiver(post_save, sender=FinancePlan)
def create_emi_schedule(sender, instance, created, **kwargs):
    """
    Automatically generate EMI schedule when a FinancePlan is created.
    """
    print("🚀 finance.signals module loaded")

    if created:
        print("🧮 Creating EMI schedule...")
        # Only generate if EMI schedule doesn't already exist
        if not instance.emi_schedule.exists():
            print("🧮 Creating EMI schedule...222b")
            # Calculate first due date (example: 30 days from today)
            first_due_date = timezone.now().date() + timedelta(days=30)

            # Choose appropriate schedule generator
            if instance.installment_frequency_days == 15:
                EMISchedule.generate_schedule(instance, first_due_date)
            else:
                EMISchedule.generate_schedule_emi(instance, first_due_date)

            print(f"✅ EMI schedule created for FinancePlan ID {instance.id}")


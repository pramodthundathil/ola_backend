from django.db.models.signals import post_save
from django.dispatch import receiver
from products.models import ProductModel
from django.core.cache import cache

@receiver(post_save, sender=ProductModel)
def clear_device_price_cache(sender, instance, **kwargs):
    cache_key = f"device_price_{instance.id}"
    cache.delete(cache_key)

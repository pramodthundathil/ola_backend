# finance/cache_utils.py

from django.core.cache import cache
from functools import wraps
from decimal import Decimal
from rest_framework.response import Response

# finance/cache_utils.py
from django.core.cache import cache
from functools import wraps
from rest_framework.response import Response

# finance/cache_utils.py
from django.core.cache import cache
from functools import wraps
from rest_framework.response import Response

def cache_response(timeout=300):
    """
    Decorator to cache DRF GET responses (stores only .data to avoid render issues).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            if request.method != "GET":
                return func(self, request, *args, **kwargs)

            cache_key = f"api_cache:{request.get_full_path()}"
            cached_data = cache.get(cache_key)

            if cached_data:
                # Return a fresh Response using cached JSON data
                return Response(cached_data)

            # Execute original view logic
            response = func(self, request, *args, **kwargs)

            # Cache only serializable response data
            if isinstance(response, Response) and response.status_code == 200:
                try:
                    cache.set(cache_key, response.data, timeout)
                except Exception as e:
                    # Fail silently if caching fails
                    import logging
                    logging.exception(f"[CacheError] Failed to cache response: {e}")

            return response
        return wrapper
    return decorator


# ========================================
# Helper Function for Device Price
# ========================================
def get_device_price_with_cache(device):
    cache_key = f"device_price_{device.id}"
    price = cache.get(cache_key)
    if not price:
        base_price = device.suggested_price
        price = base_price + (base_price * Decimal("0.07"))  # Add ITBMS tax
        cache.set(cache_key, price, timeout=3600)
    return price

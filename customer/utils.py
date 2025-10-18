import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)






# ========================== EXPERIAN ACCESSTOKEN===================


TOKEN_CACHE_KEY = "experian_access_token"

def get_experian_access_token():
    """
    Get valid access token from cache.
    If expired, use refresh token to get a new access token.
    If no token exists, request a new one using username/password.
    """
    token_data = cache.get(TOKEN_CACHE_KEY)

    if token_data:
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_at = token_data.get("expires_at")

        # Check if token is still valid
        if access_token and expires_at > timezone.now():
            return access_token

        # Access token expired → try using refresh token
        if refresh_token:
            try:
                response = requests.post(
                    f"{settings.EXPERIAN_BASE_URL}/oauth2/v1/token",
                    json={
                        "client_id": settings.EXPERIAN_CLIENT_ID,
                        "client_secret": settings.EXPERIAN_CLIENT_SECRET,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                access_token = data["access_token"]
                refresh_token = data.get("refresh_token", refresh_token)
                expires_in = int(data.get("expires_in", 1800))

                # Cache new token
                cache.set(
                    TOKEN_CACHE_KEY,
                    {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_at": timezone.now() + timedelta(seconds=expires_in - 120)
                    },
                    timeout=expires_in
                )
                return access_token

            except requests.RequestException as e:
                logger.error(f"Experian refresh token error: {str(e)}")

    # No cached token → request a new token using username/password
    try:
        response = requests.post(
            f"{settings.EXPERIAN_BASE_URL}/oauth2/v1/token",
            json={
                "client_id": settings.EXPERIAN_CLIENT_ID,
                "client_secret": settings.EXPERIAN_CLIENT_SECRET,
                "grant_type": "password",
                "username": settings.EXPERIAN_USERNAME,
                "password": settings.EXPERIAN_PASSWORD,
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        access_token = data["access_token"]
        refresh_token = data.get("refresh_token")
        expires_in = int(data.get("expires_in", 1800))

        # Cache new token
        cache.set(
            TOKEN_CACHE_KEY,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": timezone.now() + timedelta(seconds=expires_in - 120)
            },
            timeout=expires_in
        )
        return access_token

    except requests.RequestException as e:
        logger.error(f"Experian access token request error: {str(e)}")
        return None








# ========== EXPERIAN CREDIT SCORE CHECK================



def fetch_credit_score_from_experian(customer):
    """Call Experian API to get credit score."""
    access_token = get_experian_access_token()
    if not access_token:
        logger.error(f"No valid Experian access token available for customer {customer.id}")
        return None

    payload = {
        "customer_id": customer.id,
        "document_number": customer.document_number,
        "document_type": customer.document_type,
        "first_name": customer.first_name,
        "last_name": customer.last_name,
        "email": customer.email,
        "phone_number": customer.phone_number,
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            f"{settings.EXPERIAN_BASE_URL}/credit-score/v1/check",
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return {
            "apc_score": data.get("apc_score"),
            "apc_consultation_id": data.get("apc_consultation_id"),
            "apc_status": data.get("apc_status"),
            "score_valid_until": timezone.now() + timedelta(days=30),
            "updated_from_experian": True
        }
    except requests.RequestException as e:
        logger.error(f"Experian API error for customer {customer.id}: {str(e)}")
        return None


























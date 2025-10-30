# services/nuovopay_service.py

import requests
import logging
from django.conf import settings
logger = logging.getLogger(__name__)

class NuovoPayService:
    """
    NuovoPay Device Management Integration Service
    For Android devices (non-Samsung)
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'NUOVOPAY_API_BASE_URL', 'https://api.nuovopay.com')
        self.api_key = getattr(settings, 'NUOVOPAY_API_KEY', '')
        self.merchant_id = getattr(settings, 'NUOVOPAY_MERCHANT_ID', '')
    
    def enroll_device(self, imei, device_model, customer_phone=None):
        """
        Enroll device in NuovoPay
        
        Args:
            imei: Device IMEI number
            device_model: Device model name
            customer_phone: Customer phone number
        
        Returns:
            dict: {'success': bool, 'enrollment_id': str, 'qr_code': str, 'error': str}
        """
        try:
            url = f"{self.base_url}/v1/devices/enroll"
            headers = {
                'X-API-Key': self.api_key,
                'Content-Type': 'application/json'
            }
            
            payload = {
                'merchant_id': self.merchant_id,
                'imei': imei,
                'device_model': device_model,
                'phone': customer_phone
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            logger.info(f"[NuovoPay] Device enrolled successfully: IMEI={imei}")
            
            return {
                'success': True,
                'enrollment_id': data.get('device_id', ''),
                'qr_code': data.get('qr_code_data', ''),
                'enrollment_link': data.get('enrollment_link', ''),
                'error': None
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[NuovoPay] Enrollment failed for IMEI={imei}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def lock_device(self, enrollment_id, imei):
        """
        Lock device using NuovoPay
        
        Args:
            enrollment_id: NuovoPay device ID
            imei: Device IMEI
        
        Returns:
            dict: {'success': bool, 'message': str, 'error': str}
        """
        try:
            url = f"{self.base_url}/v1/devices/{enrollment_id}/lock"
            headers = {
                'X-API-Key': self.api_key,
                'Content-Type': 'application/json'
            }
            
            payload = {
                'merchant_id': self.merchant_id,
                'imei': imei,
                'action': 'lock'
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            logger.info(f"[NuovoPay] Device locked successfully: IMEI={imei}")
            
            return {
                'success': True,
                'message': 'Device locked successfully',
                'error': None
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[NuovoPay] Lock failed for IMEI={imei}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def unlock_device(self, enrollment_id, imei):
        """
        Unlock device using NuovoPay
        
        Args:
            enrollment_id: NuovoPay device ID
            imei: Device IMEI
        
        Returns:
            dict: {'success': bool, 'message': str, 'error': str}
        """
        try:
            url = f"{self.base_url}/v1/devices/{enrollment_id}/unlock"
            headers = {
                'X-API-Key': self.api_key,
                'Content-Type': 'application/json'
            }
            
            payload = {
                'merchant_id': self.merchant_id,
                'imei': imei
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            logger.info(f"[NuovoPay] Device unlocked successfully: IMEI={imei}")
            
            return {
                'success': True,
                'message': 'Device unlocked successfully',
                'error': None
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[NuovoPay] Unlock failed for IMEI={imei}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_device_status(self, enrollment_id):
        """
        Get device status from NuovoPay
        
        Returns:
            dict: Device status information
        """
        try:
            url = f"{self.base_url}/v1/devices/{enrollment_id}/status"
            headers = {
                'X-API-Key': self.api_key
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[NuovoPay] Status check failed: {str(e)}")
            return {'success': False, 'error': str(e)}
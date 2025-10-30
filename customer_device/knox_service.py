# services/knox_service.py
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class KNOXService:
    """
    Samsung KNOX Mobile Enrollment (KME) Integration Service
    Documentation: https://docs.samsungknox.com/admin/knox-mobile-enrollment/
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'KNOX_API_BASE_URL', 'https://www.samsungknox.com/api')
        self.client_id = getattr(settings, 'KNOX_CLIENT_ID', '')
        self.client_secret = getattr(settings, 'KNOX_CLIENT_SECRET', '')
        self.access_token = None
    
    def authenticate(self):
        """Get KNOX API access token"""
        try:
            url = f"{self.base_url}/oauth2/token"
            payload = {
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
            
            response = requests.post(url, data=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            self.access_token = data.get('access_token')
            
            logger.info("[KNOX] Authentication successful")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[KNOX] Authentication failed: {str(e)}")
            return False
    
    def enroll_device(self, imei, device_model, customer_email=None):
        """
        Enroll device in KNOX
        
        Args:
            imei: Device IMEI number
            device_model: Device model name
            customer_email: Customer email (optional)
        
        Returns:
            dict: {'success': bool, 'enrollment_id': str, 'qr_code': str, 'error': str}
        """
        try:
            if not self.access_token:
                if not self.authenticate():
                    return {'success': False, 'error': 'Authentication failed'}
            
            url = f"{self.base_url}/v1/kme/devices/enroll"
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'imei': imei,
                'model': device_model,
                'email': customer_email
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            logger.info(f"[KNOX] Device enrolled successfully: IMEI={imei}")
            
            return {
                'success': True,
                'enrollment_id': data.get('device_id', ''),
                'qr_code': data.get('qr_code', ''),
                'enrollment_link': data.get('enrollment_url', ''),
                'error': None
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[KNOX] Enrollment failed for IMEI={imei}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def lock_device(self, enrollment_id, imei):
        """
        Lock device using KNOX
        
        Args:
            enrollment_id: KNOX device/enrollment ID
            imei: Device IMEI
        
        Returns:
            dict: {'success': bool, 'message': str, 'error': str}
        """
        try:
            if not self.access_token:
                if not self.authenticate():
                    return {'success': False, 'error': 'Authentication failed'}
            
            url = f"{self.base_url}/v1/kme/devices/{enrollment_id}/lock"
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'imei': imei,
                'lock_type': 'full'
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            logger.info(f"[KNOX] Device locked successfully: IMEI={imei}")
            
            return {
                'success': True,
                'message': 'Device locked successfully',
                'error': None
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[KNOX] Lock failed for IMEI={imei}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def unlock_device(self, enrollment_id, imei):
        """
        Unlock device using KNOX
        
        Args:
            enrollment_id: KNOX device/enrollment ID
            imei: Device IMEI
        
        Returns:
            dict: {'success': bool, 'message': str, 'error': str}
        """
        try:
            if not self.access_token:
                if not self.authenticate():
                    return {'success': False, 'error': 'Authentication failed'}
            
            url = f"{self.base_url}/v1/kme/devices/{enrollment_id}/unlock"
            headers = {
                'Authorization': f'Bearer {self.access_token}'
            }
            
            response = requests.post(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            logger.info(f"[KNOX] Device unlocked successfully: IMEI={imei}")
            
            return {
                'success': True,
                'message': 'Device unlocked successfully',
                'error': None
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[KNOX] Unlock failed for IMEI={imei}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_device_status(self, enrollment_id):
        """
        Get device status from KNOX
        
        Returns:
            dict: Device status information
        """
        try:
            if not self.access_token:
                if not self.authenticate():
                    return {'success': False, 'error': 'Authentication failed'}
            
            url = f"{self.base_url}/v1/kme/devices/{enrollment_id}"
            headers = {
                'Authorization': f'Bearer {self.access_token}'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[KNOX] Status check failed: {str(e)}")
            return {'success': False, 'error': str(e)}



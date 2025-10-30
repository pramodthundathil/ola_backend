from django.db import models
from django.utils import timezone
from finance.models import FinancePlan
from products.models import ProductModel, Brand
from customer.models import Customer

class DeviceEnrollmentCustomer(models.Model):
    """
    Manages device enrollment and locking system integration.
    
    Integrations:
    - Samsung KNOX for Samsung devices
    - NuovoPay for other Android devices
    """
    
    ENROLLMENT_STATUS_CHOICES = [
        ('NOT_STARTED', 'Not Started'),
        ('QR_GENERATED', 'QR Code Generated'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    LOCKING_SYSTEM_CHOICES = [
        ('KNOX', 'Samsung KNOX'),
        ('NUOVOPAY', 'NuovoPay'),
        ('NONE', 'None'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    
    finance_plan = models.OneToOneField(
        FinancePlan,
        on_delete=models.CASCADE,
        related_name='device_enrollment_customer'
    )
    
    # Device Information
    imei = models.CharField(max_length=20, unique=True)
    device_brand_name = models.CharField(
        max_length=100,
        help_text="Brand name from ProductModel (e.g., Samsung, Apple, Xiaomi)"
    )
    device_model = models.ForeignKey(
        ProductModel, 
        on_delete=models.DO_NOTHING,
        help_text="Auto-populated from FinancePlan"
    )
    
    # Enrollment Process
    enrollment_status = models.CharField(
        max_length=20,
        choices=ENROLLMENT_STATUS_CHOICES,
        default='NOT_STARTED'
    )
    enrollment_qr_code = models.TextField(
        null=True,
        blank=True,
        help_text="QR code for device enrollment"
    )
    enrollment_link = models.URLField(null=True, blank=True)
    
    # Locking System Integration
    locking_system = models.CharField(
        max_length=20,
        choices=LOCKING_SYSTEM_CHOICES,
        default='NONE'
    )
    locking_system_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Reference ID from KNOX or NuovoPay"
    )
    is_locked = models.BooleanField(default=False)
    lock_applied_at = models.DateTimeField(null=True, blank=True)
    
    # Verification
    imei_verified = models.BooleanField(default=False)
    device_has_internet = models.BooleanField(
        default=False,
        help_text="Device must have internet to complete enrollment"
    )
    
    enrollment_completed_at = models.DateTimeField(null=True, blank=True)
    enrollment_failed_reason = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'device_enrollment_customer'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['imei']),
            models.Index(fields=['enrollment_status']),
            models.Index(fields=['finance_plan']),
            models.Index(fields=['customer']),
        ]
    
    def __str__(self):
        return f"Enrollment for IMEI {self.imei} - {self.enrollment_status}"
    
    def determine_locking_system(self):
        """Determine which locking system to use based on device brand"""
        brand_lower = self.device_brand_name.lower()
        
        if 'samsung' in brand_lower:
            self.locking_system = 'KNOX'
        elif 'apple' in brand_lower or 'iphone' in brand_lower or 'ipad' in brand_lower:
            # Apple devices typically don't use these systems
            self.locking_system = 'NONE'
        else:
            # All other Android devices
            self.locking_system = 'NUOVOPAY'
        
        return self.locking_system
    
    def save(self, *args, **kwargs):
        # Auto-determine locking system when creating
        if not self.pk:  # Only on creation
            self.determine_locking_system()
        
        super().save(*args, **kwargs)
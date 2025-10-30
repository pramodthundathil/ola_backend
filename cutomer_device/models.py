from django.db import models
from finance.models import FinancePlan
from products.models import ProductModel, Brand

# Create your models here.
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

    DEVICE_BRAND_CHOICES = [
        ('samsung', 'Samsung'),
        ('apple', 'Apple'),
        ('huawei', 'Huawei'),
        ('xiaomi', 'Xiaomi'),
        ('oppo', 'Oppo'),
        ('vivo', 'Vivo'),
        ('realme', 'Realme'),
        ('tecno', 'Tecno'),
        ('infinix', 'Infinix'),
        ('itel', 'Itel'),
        ('other', 'Other'),
    ]
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit_application = models.OneToOneField(
        FinancePlan,
        on_delete=models.CASCADE,
        related_name='device_enrollment_customer'
    )
    
    # Device Information
    imei = models.CharField(max_length=20, unique=True)
    device_brand = models.CharField(max_length=100, choices=DEVICE_BRAND_CHOICES)
    device_model = models.ForeignKey(ProductModel, on_delete=models.DO_NOTHING)
    
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
        db_table = 'device_enrollments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['imei']),
            models.Index(fields=['enrollment_status']),
        ]
    
    def __str__(self):
        return f"Enrollment for IMEI {self.imei} - {self.enrollment_status}"
    
    def determine_locking_system(self):
        """Determine which locking system to use based on device brand"""
        if 'samsung' in self.device_brand.lower():
            self.locking_system = 'KNOX'
        else:
            self.locking_system = 'NUOVOPAY'
        return self.locking_system


from django.db import models
from django.core.validators import RegexValidator
from home.models import CustomUser
import uuid


class Region(models.Model):
    """
    Geographical region for organizing stores.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'regions'
        ordering = ['name']
        verbose_name = 'Region'
        verbose_name_plural = 'Regions'
    
    def __str__(self):
        return self.name


class Province(models.Model):
    """
    Province within a region.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='provinces')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'provinces'
        ordering = ['region', 'name']
        unique_together = ['region', 'name']
        verbose_name = 'Province'
        verbose_name_plural = 'Provinces'
    
    def __str__(self):
        return f"{self.name} ({self.region.name})"


class District(models.Model):
    """
    District within a province.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    province = models.ForeignKey(Province, on_delete=models.CASCADE, related_name='districts')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'districts'
        ordering = ['province', 'name']
        unique_together = ['province', 'name']
        verbose_name = 'District'
        verbose_name_plural = 'Districts'
    
    def __str__(self):
        return f"{self.name} ({self.province.name})"


class Corregimiento(models.Model):
    """
    Corregimiento (township) within a district.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='corregimientos')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'corregimientos'
        ordering = ['district', 'name']
        unique_together = ['district', 'name']
        verbose_name = 'Corregimiento'
        verbose_name_plural = 'Corregimientos'
    
    def __str__(self):
        return f"{self.name} ({self.district.name})"


class Store(models.Model):
    """
    Physical store location with complete details.
    """
    CHANNEL_CHOICES = [
        ('retail', 'Retail'),
        ('wholesale', 'Wholesale'),
        ('franchise', 'Franchise'),
        ('corporate', 'Corporate'),
        ('online', 'Online'),
    ]
    
    phone_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."
    )
    
    # Primary Key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic Information
    name = models.CharField(max_length=200, verbose_name='Store Name')
    code = models.CharField(max_length=50, unique=True, verbose_name='Store Code')
    
    # Geographical Information
    region = models.ForeignKey(
        Region, 
        on_delete=models.PROTECT, 
        related_name='stores',
        verbose_name='Region'
    )
    province = models.ForeignKey(
        Province, 
        on_delete=models.PROTECT, 
        related_name='stores',
        verbose_name='Province'
    )
    district = models.ForeignKey(
        District, 
        on_delete=models.PROTECT, 
        related_name='stores',
        verbose_name='District'
    )
    corregimiento = models.ForeignKey(
        Corregimiento, 
        on_delete=models.PROTECT, 
        related_name='stores',
        verbose_name='Corregimiento',
        null=True,
        blank=True
    )
    
    # Management
    sales_advisor = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='advised_stores',
        limit_choices_to={'role': 'sales_advisor'},
        verbose_name='Sales Advisor'
    )
    store_manager = models.OneToOneField(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_store',
        limit_choices_to={'role': 'store_manager'},
        verbose_name='Store Manager'
    )
    
    # Contact Information
    phone = models.CharField(
        validators=[phone_regex],
        max_length=17,
        blank=True,
        null=True,
        verbose_name='Phone Number'
    )
    email = models.EmailField(blank=True, null=True, verbose_name='Email')
    
    # Business Details
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default='retail',
        verbose_name='Sales Channel'
    )
    ruc = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='RUC (Tax ID)',
        help_text='Registro Único de Contribuyente'
    )
    
    # Location Coordinates
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name='Latitude'
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name='Longitude'
    )
    
    # Media
    image = models.ImageField(
        upload_to='store_images/',
        blank=True,
        null=True,
        verbose_name='Store Image'
    )
    
    # Address Details
    address = models.TextField(blank=True, null=True, verbose_name='Full Address')
    
    # Status and Metrics
    is_active = models.BooleanField(default=True, verbose_name='Active Status')
    opening_date = models.DateField(null=True, blank=True, verbose_name='Opening Date')
    monthly_target = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        verbose_name='Monthly Sales Target'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_stores',
        verbose_name='Created By'
    )
    
    class Meta:
        db_table = 'stores'
        ordering = ['-created_at']
        verbose_name = 'Store'
        verbose_name_plural = 'Stores'
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['region', 'province']),
            models.Index(fields=['is_active']),
            models.Index(fields=['store_manager']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.code})"
    
    def get_full_address(self):
        """Return complete formatted address."""
        parts = [
            self.address,
            self.corregimiento.name if self.corregimiento else None,
            self.district.name,
            self.province.name,
            self.region.name
        ]
        return ", ".join([p for p in parts if p])
    
    def get_salespersons(self):
        """Get all salespersons assigned to this store."""
        return CustomUser.objects.filter(
            role='salesperson',
            store_id=str(self.id),
            is_active=True
        )
    
    def get_salespersons_count(self):
        """Get count of active salespersons in this store."""
        return self.get_salespersons().count()
    
    def can_user_access(self, user):
        """Check if a user has access to this store."""
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            return True
        if user.role == 'sales_advisor' and self.sales_advisor == user:
            return True
        if user.role == 'store_manager' and self.store_manager == user:
            return True
        if user.role == 'salesperson' and str(user.store_id) == str(self.id):
            return True
        return False
    
    def save(self, *args, **kwargs):
        """Override save to update store_manager's store_id."""
        super().save(*args, **kwargs)
        
        # Update store_manager's store_id
        if self.store_manager:
            if self.store_manager.store_id != str(self.id):
                self.store_manager.store_id = str(self.id)
                self.store_manager.save(update_fields=['store_id'])


class StorePerformance(models.Model):
    """
    Monthly performance tracking for stores.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='performances')
    month = models.DateField(verbose_name='Month')
    
    # Sales Metrics
    total_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_applications = models.IntegerField(default=0)
    approved_applications = models.IntegerField(default=0)
    rejected_applications = models.IntegerField(default=0)
    pending_applications = models.IntegerField(default=0)
    
    # Financial Metrics
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_commissions = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    collections = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    defaults = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Customer Metrics
    new_customers = models.IntegerField(default=0)
    returning_customers = models.IntegerField(default=0)
    
    # Performance Indicators
    target_achievement_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00
    )
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'store_performances'
        ordering = ['-month']
        unique_together = ['store', 'month']
        verbose_name = 'Store Performance'
        verbose_name_plural = 'Store Performances'
    
    def __str__(self):
        return f"{self.store.name} - {self.month.strftime('%B %Y')}"
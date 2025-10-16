# home/models.py (FIXED VERSION)
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
import uuid


class CustomUserManager(BaseUserManager):
    """
    Custom user manager for the phone financing platform.
    Handles user creation with email as the unique identifier.
    """
    
    def create_user(self, email, password=None, **extra_fields):
        """
        Create and save a regular user with the given email and password.
        """
        if not email:
            raise ValueError('Users must have an email address')
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create and save a superuser with the given email and password.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', CustomUser.ADMIN)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        
        return self.create_user(email, password, **extra_fields)
    
    def get_by_natural_key(self, email):
        """
        Allow authentication using email.
        """
        return self.get(email=email)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for the phone financing platform.
    Uses email as the primary authentication field.
    Includes role-based access control for different user types.
    """
    
    # User Roles
    SALESPERSON = 'salesperson'
    STORE_MANAGER = 'store_manager'
    GLOBAL_MANAGER = 'global_manager'
    FINANCIAL_MANAGER = 'financial_manager'
    SALES_ADVISOR = 'sales_advisor'
    ADMIN = 'admin'
    
    ROLE_CHOICES = [
        (SALESPERSON, 'Salesperson'),
        (STORE_MANAGER, 'Store Manager'),
        (GLOBAL_MANAGER, 'Global Manager'),
        (FINANCIAL_MANAGER, 'Financial Manager'),
        (SALES_ADVISOR, 'Sales Advisor'),
        (ADMIN, 'Administrator'),
    ]
    
    # Phone number validator
    phone_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."
    )
    
    
    email = models.EmailField(
        verbose_name='email address',
        max_length=255,
        unique=True,
        db_index=True,
    )
    username = models.CharField(
        max_length=150,
        unique=True,
        blank=True,
        null=True,
        help_text='Optional username. Email will be used for login if not provided.'
    )
    
    # Personal Information
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(
        validators=[phone_regex],
        max_length=17,
        blank=True,
        null=True,
        help_text='Contact phone number'
    )
    phone_number = models.CharField(  # Added for backward compatibility
        validators=[phone_regex],
        max_length=17,
        blank=True,
        null=True,
        help_text='Contact phone number (alternative field)'
    )
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True
    )
    
    # Role and Permissions
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=SALESPERSON,
        help_text='User role in the system'
    )
    
    # Store Assignment
    store_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='Associated store ID for salespeople and managers'
    )
    
    # Status Fields
    is_active = models.BooleanField(
        default=True,
        help_text='Designates whether this user should be treated as active.'
    )
    is_staff = models.BooleanField(
        default=False,
        help_text='Designates whether the user can log into admin site.'
    )
    is_verified = models.BooleanField(
        default=False,
        help_text='Designates whether the user has verified their email.'
    )
    
    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Additional Fields
    employee_id = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        help_text='Unique employee identification number'
    )
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text='Commission rate for salespeople (percentage)'
    )
    
    # FIX: Add related_name to avoid conflicts with default User model
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='customuser_set',  # Changed from default 'user_set'
        related_query_name='customuser',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='customuser_set',  # Changed from default 'user_set'
        related_query_name='customuser',
    )
    
    # Manager Configuration
    objects = CustomUserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    
    class Meta:
        db_table = 'custom_users'
        verbose_name = 'user'
        verbose_name_plural = 'users'
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['role']),
            models.Index(fields=['store_id']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"
    
    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email
    
    def get_short_name(self):
        """
        Return the short name for the user.
        """
        return self.first_name or self.email.split('@')[0]
    
    # Role Check Methods
    def is_salesperson(self):
        """Check if user is a salesperson."""
        return self.role == self.SALESPERSON
    
    def is_store_manager(self):
        """Check if user is a store manager."""
        return self.role == self.STORE_MANAGER
    
    def is_global_manager(self):
        """Check if user is a global manager."""
        return self.role == self.GLOBAL_MANAGER
    
    def is_financial_manager(self):
        """Check if user is a financial manager."""
        return self.role == self.FINANCIAL_MANAGER
    
    def is_sales_advisor(self):
        """Check if user is a sales advisor."""
        return self.role == self.SALES_ADVISOR
    
    def is_admin_user(self):
        """Check if user is an administrator."""
        return self.role == self.ADMIN
    
    def can_approve_applications(self):
        """
        Check if user has permission to approve credit applications.
        """
        return self.role in [
            self.STORE_MANAGER,
            self.GLOBAL_MANAGER,
            self.FINANCIAL_MANAGER,
            self.ADMIN
        ]
    
    def can_manage_store(self):
        """
        Check if user can manage store operations.
        """
        return self.role in [
            self.STORE_MANAGER,
            self.GLOBAL_MANAGER,
            self.ADMIN
        ]
    
    def can_view_all_stores(self):
        """
        Check if user can view all stores data.
        """
        return self.role in [
            self.GLOBAL_MANAGER,
            self.FINANCIAL_MANAGER,
            self.ADMIN
        ]
    
    def can_configure_system(self):
        """
        Check if user can configure system settings.
        """
        return self.role in [
            self.FINANCIAL_MANAGER,
            self.ADMIN
        ]
    
    def get_accessible_stores(self):
        """
        Get list of stores this user can access.
        """
        if self.can_view_all_stores():
            return None  # All stores
        elif self.store_id:
            return [self.store_id]
        return []
    
    def save(self, *args, **kwargs):
        """
        Override save to auto-generate username from email if not provided.
        """
        if not self.username:
            self.username = self.email.split('@')[0]
        
        # Sync phone and phone_number fields
        if self.phone and not self.phone_number:
            self.phone_number = self.phone
        elif self.phone_number and not self.phone:
            self.phone = self.phone_number
        
        # Auto-assign is_staff for certain roles
        if self.role in [self.ADMIN, self.FINANCIAL_MANAGER, self.GLOBAL_MANAGER]:
            self.is_staff = True
        
        super().save(*args, **kwargs)




# stores/models.py
from django.db import models
from django.core.validators import RegexValidator
from home.models import CustomUser
import uuid


class Region(models.Model):
    """
    Geographical region for organizing stores.
    """
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
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
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
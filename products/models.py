"""
Django Models for Product Catalog & Financing System

This module contains models for managing a comprehensive product catalog
for the Ola Credits financing application.

Hierarchy: Category > Brand > Product Model

Key Features:
- Multi-category support (Phones, Laptops, Tablets, etc.)
- Brand management under each category
- Product models with detailed specifications
- Auto-generated OLA codes (5 digits starting with OLA)
- Single retail price per model
- Multiple images and documentation support
"""

from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.utils.text import slugify
from decimal import Decimal
import uuid
import random
from django.contrib.auth import get_user_model

User = get_user_model()

# ========================================
# PRODUCT CATEGORY MODEL
# ========================================

class ProductCategory(models.Model):
    """
    Main product categories for the financing system
    
    Examples: Mobile Phones, Laptops, Tablets, Smart Watches, 
              TVs, Gaming Consoles, Cameras, Appliances, etc.
    """
    
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Category name (e.g., Mobile Phones, Laptops, Tablets)"
    )
    
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="URL-friendly version of name"
    )
    
    icon = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Icon class or emoji for the category (e.g., 📱, 💻, 📺)"
    )
    
    image = models.ImageField(
        upload_to='categories/',
        null=True,
        blank=True,
        help_text="Category banner/image"
    )
    
    description = models.TextField(
        null=True,
        blank=True,
        help_text="Category description for customers"
    )
    
    # Display Settings
    is_active = models.BooleanField(
        default=True,
        help_text="Is this category currently available?"
    )
    
    is_featured = models.BooleanField(
        default=False,
        help_text="Show in featured categories?"
    )
    
    display_order = models.IntegerField(
        default=0,
        help_text="Order in which category appears (lower = higher priority)"
    )
    
    # SEO
    meta_title = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="SEO meta title"
    )
    
    meta_description = models.TextField(
        null=True,
        blank=True,
        help_text="SEO meta description"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product_categories'
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
            models.Index(fields=['display_order']),
        ]
        verbose_name = 'Product Category'
        verbose_name_plural = 'Product Categories'
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def get_active_brands_count(self):
        """Get count of active brands in this category"""
        return self.brands.filter(is_active=True).count()
    
    def get_active_products_count(self):
        """Get total count of active products in this category"""
        return ProductModel.objects.filter(
            brand__category=self,
            is_active=True
        ).count()


# ========================================
# BRAND MODEL
# ========================================

class Brand(models.Model):
    """
    Product brands/manufacturers under each category
    
    Examples under Mobile Phones: Samsung, Apple, Xiaomi, etc.
    Examples under Laptops: Dell, HP, Lenovo, Apple, etc.
    """
    
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='brands',
        help_text="Parent category this brand belongs to"
    )
    
    name = models.CharField(
        max_length=100,
        help_text="Brand name (e.g., Samsung, Apple, Dell, Sony)"
    )
    
    slug = models.SlugField(
        max_length=150,
        help_text="URL-friendly version of name"
    )
    
    logo = models.ImageField(
        upload_to='brands/logos/',
        null=True,
        blank=True,
        help_text="Brand logo image"
    )
    
    banner_image = models.ImageField(
        upload_to='brands/banners/',
        null=True,
        blank=True,
        help_text="Brand banner for brand page"
    )
    
    country_of_origin = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Country where brand originated"
    )
    
    website = models.URLField(
        null=True,
        blank=True,
        help_text="Official brand website"
    )
    
    description = models.TextField(
        null=True,
        blank=True,
        help_text="Brand description and history"
    )
    
    # Display Settings
    is_active = models.BooleanField(
        default=True,
        help_text="Is this brand currently available for financing?"
    )
    
    is_featured = models.BooleanField(
        default=False,
        help_text="Show this brand in featured listings?"
    )
    
    display_order = models.IntegerField(
        default=0,
        help_text="Order in which brand appears in listings (lower = higher priority)"
    )
    
    # SEO
    meta_title = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="SEO meta title"
    )
    
    meta_description = models.TextField(
        null=True,
        blank=True,
        help_text="SEO meta description"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'brands'
        ordering = ['category', 'display_order', 'name']
        unique_together = [['category', 'name']]
        indexes = [
            models.Index(fields=['category', 'name']),
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
            models.Index(fields=['display_order']),
        ]
        verbose_name = 'Brand'
        verbose_name_plural = 'Brands'
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.category.name}-{self.name}")
        super().save(*args, **kwargs)
    
    def get_active_models_count(self):
        """Get count of active product models for this brand"""
        return self.products.filter(is_active=True).count()
    
    def get_models_by_price_range(self, min_price=None, max_price=None):
        """Get models within a specific price range"""
        queryset = self.products.filter(is_active=True)
        if min_price:
            queryset = queryset.filter(suggested_price__gte=min_price)
        if max_price:
            queryset = queryset.filter(suggested_price__lte=max_price)
        return queryset


# ========================================
# PRODUCT MODEL
# ========================================

class ProductModel(models.Model):
    """
    Individual product model with complete specifications and pricing
    
    Business Rules:
    - Auto-generates unique OLA code (OLA + 5 digits)
    - Stores comprehensive product specifications
    - Single retail price for financing calculations
    - Supports multiple images and documents
    - Each variant (specs combination) is a separate model
    """
    
    CONDITION_CHOICES = [
        ('NEW', 'Brand New'),
        ('REFURBISHED', 'Refurbished'),
        ('LIKE_NEW', 'Like New'),
        ('USED', 'Used - Good Condition'),
    ]
    
    # ============ PRIMARY IDENTIFIERS ============
    
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    ola_code = models.CharField(
        max_length=8,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Auto-generated unique code: OLA + 5 digits (e.g., OLA12345)"
    )
    
    # ============ CATEGORY AND BRAND ============
    
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name='products',
        help_text="Product brand/manufacturer"
    )
    
    model_name = models.CharField(
        max_length=200,
        help_text="Product model name (e.g., Galaxy S23 Ultra, MacBook Pro 14, iPad Air)"
    )
    
    model_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Manufacturer's model number (e.g., SM-S918B, MNW83LL/A)"
    )
    
    release_year = models.IntegerField(
        null=True,
        blank=True,
        help_text="Year the model was released"
    )
    
    sku = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        unique=True,
        help_text="Stock Keeping Unit (optional internal reference)"
    )
    
    # ============ IMAGES ============
    
    primary_image = models.ImageField(
        upload_to='products/primary/',
        null=True,
        blank=True,
        help_text="Main product image (displayed in listings)"
    )
    
    # ============ PRODUCT SPECIFICATIONS (Flexible JSON) ============
    
    specifications = models.JSONField(
        default=dict,
        help_text="""Product specifications as JSON. Structure by category:
        {
            "Display": {"Screen Size": "6.7 inches", "Resolution": "1440x3088"},
            "Performance": {"RAM": "12GB", "Storage": "256GB", "Processor": "Snapdragon 8 Gen 2"},
            "Camera": {"Rear": "200MP + 12MP + 10MP", "Front": "12MP"},
            "Battery": {"Capacity": "5000mAh", "Fast Charging": "45W"},
            "Connectivity": {"Network": "5G", "WiFi": "Wi-Fi 6E", "Bluetooth": "5.3"}
        }"""
    )
    
    # ============ KEY SPECS (For Quick Filters/Display) ============
    # These are commonly used specs that need to be searchable/filterable
    
    # For Phones, Tablets, Laptops
    ram = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="RAM capacity (e.g., 8GB, 16GB, 32GB)"
    )
    
    storage = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Storage capacity (e.g., 256GB, 512GB, 1TB)"
    )
    
    processor = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Processor/chipset (e.g., M2 Pro, Core i7-13700H, Snapdragon 8 Gen 2)"
    )
    
    screen_size = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Screen/Display size (e.g., 6.7 inches, 14 inches, 55 inches)"
    )
    
    # Operating System
    operating_system = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="OS and version (e.g., Android 14, iOS 17, Windows 11, macOS Sonoma)"
    )
    
    # Color
    color = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Product color/finish (e.g., Midnight Black, Space Gray, Silver)"
    )
    
    # Physical
    weight = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Weight (e.g., 168g, 1.5kg, 15kg)"
    )
    
    dimensions = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Dimensions (e.g., 146.7 x 71.5 x 7.6 mm, 31.26 x 21.83 x 1.55 cm)"
    )
    
    # ============ CONDITION & WARRANTY ============
    
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default='NEW',
        help_text="Product condition"
    )
    
    warranty_period = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Warranty period (e.g., 1 year manufacturer warranty, 2 years)"
    )
    
    warranty_provider = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Warranty provider (e.g., Manufacturer, Retailer, Extended)"
    )
    
    # ============ PRICING ============
    
    suggested_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="suggested Retail price (used for financing calculations)"
    )
    
    
    
    minimum_price_to_sell = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
        help_text="minimum price"
    )
    
    maximum_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="maximum price"
    )
    
    currency = models.CharField(
        max_length=3,
        default='USD',
        help_text="Currency code (e.g., USD, EUR, GBP)"
    )
    
    # ============ CONTENT & MARKETING ============
    
    description = models.TextField(
        null=True,
        blank=True,
        help_text="Detailed product description for customers"
    )
    
    key_features = models.TextField(
        null=True,
        blank=True,
        help_text="Bullet points of key features (one per line)"
    )
    
    whats_in_box = models.TextField(
        null=True,
        blank=True,
        help_text="Box contents (e.g., Device, Charger, USB Cable, Documentation)"
    )
    
    specifications_pdf = models.FileField(
        upload_to='products/specs/',
        null=True,
        blank=True,
        help_text="Detailed specifications PDF document"
    )
    
    user_manual_pdf = models.FileField(
        upload_to='products/manuals/',
        null=True,
        blank=True,
        help_text="User manual PDF"
    )
    
    # ============ STATUS & DISPLAY ============
    
    is_active = models.BooleanField(
        default=True,
        help_text="Is this product available for financing?"
    )
    
    is_featured = models.BooleanField(
        default=False,
        help_text="Show this product in featured listings?"
    )
    
    is_new_arrival = models.BooleanField(
        default=False,
        help_text="Mark as new arrival?"
    )
    
    is_bestseller = models.BooleanField(
        default=False,
        help_text="Mark as bestseller?"
    )
    
    display_order = models.IntegerField(
        default=0,
        help_text="Order in listings (lower = higher priority)"
    )
    
    # ============ SEO & METADATA ============
    
    slug = models.SlugField(
        max_length=250,
        unique=True,
        help_text="URL-friendly version"
    )
    
    meta_title = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="SEO meta title"
    )
    
    meta_description = models.TextField(
        null=True,
        blank=True,
        help_text="SEO meta description"
    )
    
    tags = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Comma-separated tags (e.g., flagship, gaming, budget, 5g, ultrabook)"
    )
    
    # ============ TIMESTAMPS ============
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product_models'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ola_code']),
            models.Index(fields=['brand', 'model_name']),
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['suggested_price']),
            models.Index(fields=['display_order']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['slug']),
        ]
        verbose_name = 'Product Model'
        verbose_name_plural = 'Product Models'
    
    def __str__(self):
        specs = []
        if self.ram:
            specs.append(self.ram)
        if self.storage:
            specs.append(self.storage)
        
        spec_str = f" ({'/'.join(specs)})" if specs else ""
        return f"{self.brand.name} {self.model_name}{spec_str} - {self.ola_code}"
    
    def save(self, *args, **kwargs):
        # Auto-generate OLA code if not set
        if not self.ola_code:
            self.ola_code = self.generate_ola_code()
        
        # Auto-generate slug if not set
        if not self.slug:
            base_slug = slugify(f"{self.brand.name}-{self.model_name}")
            self.slug = self.generate_unique_slug(base_slug)
        
        
        
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_ola_code():
        """Generate unique OLA code (OLA + 5 random digits)"""
        max_attempts = 100
        for _ in range(max_attempts):
            random_number = random.randint(10000, 99999)
            ola_code = f"OLA{random_number}"
            
            if not ProductModel.objects.filter(ola_code=ola_code).exists():
                return ola_code
        
        raise ValueError("Unable to generate unique OLA code after maximum attempts")
    
    def generate_unique_slug(self, base_slug):
        """Generate unique slug by appending number if needed"""
        slug = base_slug
        counter = 1
        
        while ProductModel.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        return slug
    
    def get_full_name(self):
        """Get full descriptive name"""
        specs = []
        if self.ram:
            specs.append(self.ram)
        if self.storage:
            specs.append(self.storage)
        
        spec_str = f" ({'/'.join(specs)})" if specs else ""
        return f"{self.brand.name} {self.model_name}{spec_str}"
    
    def get_category(self):
        """Get product category through brand"""
        return self.brand.category
    
   
    
    def get_tag_list(self):
        """Get tags as a list"""
        if self.tags:
            return [tag.strip() for tag in self.tags.split(',')]
        return []
    
    def get_specification_by_category(self, category_name):
        """Get specifications for a specific category"""
        return self.specifications.get(category_name, {})
    
    def get_all_specification_categories(self):
        """Get all specification category names"""
        return list(self.specifications.keys())


# ========================================
# PRODUCT IMAGE MODEL
# ========================================

class ProductImage(models.Model):
    """
    Multiple high-quality images for product models
    
    Allows uploading multiple images from different angles
    and perspectives for better customer experience
    """
    
    IMAGE_TYPE_CHOICES = [
        ('FRONT', 'Front View'),
        ('BACK', 'Back View'),
        ('SIDE', 'Side View'),
        ('TOP', 'Top View'),
        ('BOTTOM', 'Bottom View'),
        ('ANGLE', 'Angled View'),
        ('DISPLAY', 'Display/Screen On'),
        ('DETAIL', 'Detail Close-up'),
        ('PORTS', 'Ports and Buttons'),
        ('COLORS', 'Color Variants'),
        ('LIFESTYLE', 'Lifestyle Shot'),
        ('BOX', 'Box Contents'),
        ('COMPARISON', 'Size Comparison'),
        ('OTHER', 'Other'),
    ]
    
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    product = models.ForeignKey(
        ProductModel,
        on_delete=models.CASCADE,
        related_name='images'
    )
    
    image = models.ImageField(
        upload_to='products/gallery/',
        help_text="High-resolution product image"
    )
    
    image_type = models.CharField(
        max_length=20,
        choices=IMAGE_TYPE_CHOICES,
        default='OTHER',
        help_text="Type/angle of the image"
    )
    
    caption = models.CharField(
        max_length=300,
        null=True,
        blank=True,
        help_text="Image caption or description"
    )
    
    alt_text = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Alt text for accessibility and SEO"
    )
    
    display_order = models.IntegerField(
        default=0,
        help_text="Order in which image appears in gallery"
    )
    
    is_primary = models.BooleanField(
        default=False,
        help_text="Use as primary image if product.primary_image is not set?"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'product_images'
        ordering = ['display_order', 'created_at']
        indexes = [
            models.Index(fields=['product', 'display_order']),
        ]
        verbose_name = 'Product Image'
        verbose_name_plural = 'Product Images'
    
    def __str__(self):
        return f"{self.product.ola_code} - {self.image_type} (Order: {self.display_order})"
    
    def save(self, *args, **kwargs):
        # Set alt text from caption if not provided
        if not self.alt_text and self.caption:
            self.alt_text = self.caption
        elif not self.alt_text:
            self.alt_text = f"{self.product.get_full_name()} - {self.get_image_type_display()}"
        
        super().save(*args, **kwargs)


# ========================================
# PRODUCT REVIEW MODEL
# ========================================

class ProductReview(models.Model):
    """
    Customer reviews and ratings for products
    """
    
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    product = models.ForeignKey(
        ProductModel,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    
    customer_name = models.CharField(
        max_length=200,
        help_text="Customer name (can be anonymized)"
    )
    
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MinValueValidator(5)],
        help_text="Rating from 1 to 5 stars"
    )
    
    title = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Review title/headline"
    )
    
    review_text = models.TextField(
        help_text="Review content"
    )
    
    verified_purchase = models.BooleanField(
        default=False,
        help_text="Is this from a verified purchase?"
    )
    
    is_approved = models.BooleanField(
        default=False,
        help_text="Has this review been approved for display?"
    )
    
    helpful_count = models.IntegerField(
        default=0,
        help_text="Number of users who found this helpful"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product_reviews'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['is_approved']),
            models.Index(fields=['rating']),
        ]
        verbose_name = 'Product Review'
        verbose_name_plural = 'Product Reviews'
    
    def __str__(self):
        return f"{self.customer_name} - {self.product.ola_code} ({self.rating}★)"


# ========================================
# SPECIFICATION TEMPLATE MODEL (Optional)
# ========================================

class SpecificationTemplate(models.Model):
    """
    Templates for common specification structures by category
    
    Helps maintain consistency when adding products
    """
    
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='spec_templates'
    )
    
    name = models.CharField(
        max_length=200,
        help_text="Template name (e.g., 'Standard Smartphone Specs', 'Laptop Specifications')"
    )
    
    template_structure = models.JSONField(
        help_text="""Specification structure template:
        {
            "Display": ["Screen Size", "Resolution", "Type", "Refresh Rate"],
            "Performance": ["Processor", "RAM", "Storage", "GPU"],
            "Camera": ["Rear Camera", "Front Camera", "Video Recording"],
            "Battery": ["Capacity", "Fast Charging", "Wireless Charging"]
        }"""
    )
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'specification_templates'
        ordering = ['category', 'name']
        verbose_name = 'Specification Template'
        verbose_name_plural = 'Specification Templates'
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
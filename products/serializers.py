from rest_framework import serializers
from .models import ProductCategory, Brand, ProductModel 

# ============================================================
# Product Category Serializer
# ============================================================
class ProductCategorySerializer(serializers.ModelSerializer):
    """
    Serializer for product category model
    Handles validation and serialization of category data.
    """
    image = serializers.ImageField(use_url=True, required=False)
    class Meta:
        model=ProductCategory        
        fields=[
            'id',
            'name',
            'slug',
            'icon',
            'image',
            'description',
            'is_active',
            'is_featured',
            'display_order',
            'meta_title',
            'meta_description',
            'created_at',
            'updated_at'
        ]
        read_only_fields=['id','slug','created_at','updated_at']

    def validate_name(self, value):
        """
        Ensure 'name' is unique during creation and valid during updates.
        """
        # Get the instance (if updating)
        instance = getattr(self, 'instance', None)

        # If creating a new category (no instance yet)
        if instance is None:
            if ProductCategory.objects.filter(name__iexact=value).exists():
                raise serializers.ValidationError("A category with this name already exists.")
        else:
            # If updating, check only if name is changed
            if ProductCategory.objects.filter(name__iexact=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError("A category with this name already exists.")
        
        return value
    

# ============================================================
# Product Brand Serializer
# ============================================================    
class ProductBrandSerializer(serializers.ModelSerializer):
    """
    Serializer for product brand model
    Handles validation and serialization of brand data.
    """
    # Display image URLs instead of raw file names
    logo = serializers.ImageField(required=False, allow_null=True, use_url=True)
    banner_image = serializers.ImageField(required=False, allow_null=True, use_url=True)
    
    class Meta:
        model = Brand
        fields = [
            'id',
            'category', # ID of ProductCategory
            'name',
            'slug',
            'logo',
            'banner_image',
            'country_of_origin',
            'website',
            'description',
            'is_active',
            'is_featured',
            'display_order',
            'meta_title',
            'meta_description',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']

    def validate(self, attrs):
        """Ensure brand name is unique per category."""
        category = attrs.get('category') or getattr(self.instance, 'category', None)
        name = attrs.get('name') or getattr(self.instance, 'name', None)

        if Brand.objects.exclude(pk=getattr(self.instance, 'pk', None)).filter(category=category, name=name).exists():
            raise serializers.ValidationError({"name": "A brand with this name already exists in this category."})
        return attrs


# ============================================================
# Product Brand Model Serializer
# ============================================================  
class ProductModelSerializer(serializers.ModelSerializer):
    """
    Serializer for ProductModel
    Handles full CRUD with nested brand/category context.
    """
    # Readable fields for brand/category
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    category_name = serializers.CharField(source='brand.category.name', read_only=True)

    # File fields (support URL display)
    primary_image = serializers.ImageField(required=False, allow_null=True, use_url=True)
    specifications_pdf = serializers.FileField(required=False, allow_null=True, use_url=True)
    user_manual_pdf = serializers.FileField(required=False, allow_null=True, use_url=True)

    class Meta:
        model = ProductModel
        fields = [
            'id',
            'ola_code',
            'brand',
            'brand_name',
            'category_name',
            'model_name',
            'model_number',
            'release_year',
            'sku',
            'primary_image',
            'specifications',
            'ram',
            'storage',
            'processor',
            'screen_size',
            'operating_system',
            'color',
            'weight',
            'dimensions',
            'condition',
            'warranty_period',
            'warranty_provider',
            'suggested_price',
            'minimum_price_to_sell',
            'maximum_price',
            'currency',
            'description',
            'key_features',
            'whats_in_box',
            'specifications_pdf',
            'user_manual_pdf',
            'is_active',
            'is_featured',
            'is_new_arrival',
            'is_bestseller',
            'display_order',
            'slug',
            'meta_title',
            'meta_description',
            'tags',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['ola_code', 'slug', 'created_at', 'updated_at']

    def validate(self, attrs):
        """
        Validate SKU unique slug constraints.
        """
        sku = attrs.get('sku') or getattr(self.instance, 'sku', None)
        if sku and ProductModel.objects.exclude(pk=getattr(self.instance, 'pk', None)).filter(sku=sku).exists():
            raise serializers.ValidationError({"sku": "This SKU already exists."})
        return attrs

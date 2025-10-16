from rest_framework import serializers
from .models import ProductCategory, Brand 

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

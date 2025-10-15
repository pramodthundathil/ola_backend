from rest_framework import serializers
from .models import ProductCategory


class ProductCategorySerializer(serializers.ModelSerializer):
    """
    Serializer for product category model
    Handles validation and serialization of category data.
    """
    image = serializers.ImageField(required=False, allow_null=True, use_url=True)
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
        Ensure the category name is unique(case-insensitive).
        """
        if ProductCategory.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError("A category with this name is already exists.")
        return value
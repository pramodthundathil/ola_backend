
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser as User


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for User model - used for user profile display.
    """
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    
    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'username',
            'first_name',
            'last_name',
            'full_name',
            'phone',
            'profile_picture',
            'role',
            'store_id',
            'is_verified',
            'employee_id',
            'commission_rate',
            'date_joined'
        ]
        read_only_fields = ['id', 'date_joined', 'full_name']


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration.
    """
    store_id = serializers.UUIDField(write_only=True, required=True)
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    
    class Meta:
        model = User
        fields = [
            'email',
            'password',
            'password_confirm',
            'first_name',
            'last_name',
            'phone',
            'role',
            'store_id'
        ]
    
    def validate(self, attrs):
        """
        Verify that passwords match.
        """
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password": "Password fields didn't match."
            })
        return attrs
    
    def create(self, validated_data):
        """
        Create user with encrypted password.
        """
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for password change endpoint.
    """
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(required=True, write_only=True)
    
    def validate(self, attrs):
        """
        Verify that new passwords match.
        """
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                "new_password": "New password fields didn't match."
            })
        return attrs
    
    def validate_old_password(self, value):
        """
        Verify that old password is correct.
        """
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating user profile.
    """
    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'phone',
            'profile_picture'
        ]



# ==================== Serializers for store manager and sales persons MANAGEMENT ====================

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import CustomUser
from store.models import Store


class StoreManagerSerializerCreate(serializers.ModelSerializer):
    """
    Serializer for creating Store Managers.
    Only accessible by Global Managers, Financial Managers, Sales Advisors, and Admins.
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    store_id = serializers.UUIDField(write_only=True, required=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'username', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone', 'phone_number',
            'employee_id', 'commission_rate', 'store_id',
            'store_name', 'store_code', 'is_active', 'date_joined'
        ]
        read_only_fields = ['id', 'date_joined', 'store_name', 'store_code']
    
    def validate_store_id(self, value):
        """Validate that the store exists and is active."""
        try:
            store = Store.objects.get(id=value, is_active=True)
            
            # Check if store already has a manager
            if hasattr(store, 'store_manager') and store.store_manager:
                raise serializers.ValidationError(
                    f"Store '{store.name}' already has a manager assigned."
                )
            
            return value
        except Store.DoesNotExist:
            raise serializers.ValidationError("Store does not exist or is inactive.")
    
    def validate(self, attrs):
        """Validate password confirmation and permissions."""
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError({
                "password_confirm": "Passwords do not match."
            })
        
        # Check if email already exists
        if CustomUser.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({
                "email": "A user with this email already exists."
            })
        
        return attrs
    
    def create(self, validated_data):
        """Create store manager and assign to store."""
        store_id = validated_data.pop('store_id')
        password = validated_data.pop('password')
        
        # Create the store manager
        store_manager = CustomUser.objects.create_user(
            password=password,
            role=CustomUser.STORE_MANAGER,
            is_staff=False,
            is_active=validated_data.get('is_active', True),
            **validated_data
        )
        
        # Assign store to manager
        store = Store.objects.get(id=store_id)
        store_manager.store = store
        store_manager.save()
        
        # Assign manager to store
        store.store_manager = store_manager
        store.save()
        
        return store_manager


class SalespersonSerializerCreate(serializers.ModelSerializer):
    """
    Serializer for creating Salespersons under a Store Manager.
    Store is automatically assigned from the store manager's store.
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'username', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone', 'phone_number',
            'employee_id', 'commission_rate', 'store_name', 'store_code',
            'is_active', 'date_joined'
        ]
        read_only_fields = ['id', 'date_joined', 'store_name', 'store_code']
    
    def validate(self, attrs):
        """Validate password confirmation."""
        if attrs['password'] != attrs.pop('password_confirm'):
            raise serializers.ValidationError({
                "password_confirm": "Passwords do not match."
            })
        
        # Check if email already exists
        if CustomUser.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({
                "email": "A user with this email already exists."
            })
        
        return attrs
    
    def create(self, validated_data):
        """
        Create salesperson and automatically assign to store manager's store.
        """
        password = validated_data.pop('password')
        request = self.context.get('request')
        
        # Get the store from the requesting user (store manager)
        if not request or not request.user.store:
            raise serializers.ValidationError(
                "Store manager must be assigned to a store."
            )
        
        # Create the salesperson
        salesperson = CustomUser.objects.create_user(
            password=password,
            role=CustomUser.SALESPERSON,
            is_staff=False,
            is_active=validated_data.get('is_active', True),
            store=request.user.store,  # Automatically assign store
            **validated_data
        )
        
        return salesperson


class StoreManagerListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing store managers."""
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'full_name', 'first_name', 'last_name',
            'phone', 'employee_id', 'store_name', 'store_code',
            'is_active', 'date_joined'
        ]
    
    def get_full_name(self, obj):
        return obj.get_full_name()


class SalespersonListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing salespersons."""
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'full_name', 'first_name', 'last_name',
            'phone', 'employee_id', 'commission_rate', 'store_name',
            'store_code', 'is_active', 'date_joined'
        ]
    
    def get_full_name(self, obj):
        return obj.get_full_name()
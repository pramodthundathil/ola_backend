
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser as User
from rest_framework import serializers
from store.models import Store


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for User model - used for user profile display.
    """
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    store_details = serializers.SerializerMethodField(read_only=True)
    
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
            'store_details',
            'is_verified',
            'employee_id',
            'commission_rate',
            'date_joined'
        ]
        read_only_fields = ['id', 'date_joined', 'full_name']

    def get_store_details(self, obj):
        if obj.store:
            return {
                'id': str(obj.store.id),
                'name': obj.store.name,
                'code': obj.store.code,
                'region_name': obj.store.region.name if obj.store.region else None,
                'province_name': obj.store.province.name if obj.store.province else None,
                'district_name': obj.store.district.name if obj.store.district else None,
                'corregimiento_name': obj.store.corregimiento.name if obj.store.corregimiento else None,
            }
        return None





class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration.
    Requires store field only for store_manager and salesperson roles.
    """
    store = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.all(),
        required=False,
        allow_null=True,
        help_text="Required for store managers and salespersons"
    )
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
            'store'
        ]
        extra_kwargs = {
            'email': {'required': True},
            'first_name': {'required': True},
            'last_name': {'required': True},
        }

    def validate(self, attrs):
        """
        Validate password match and conditional store requirement.
        """
        # Check password match
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password": "Password fields didn't match."
            })

        # Get role and store from validated data
        role = attrs.get('role')
        store = attrs.get('store')

        # Roles that require store assignment
        STORE_REQUIRED_ROLES = [
            User.STORE_MANAGER,  # 'store_manager'
            User.SALESPERSON,     # 'salesperson'
        ]

        # Enforce store requirement for specific roles
        if role in STORE_REQUIRED_ROLES and not store:
            raise serializers.ValidationError({
                "store": f"Store assignment is required for {role} role."
            })

        # Prevent store assignment for roles that don't need it
        if role not in STORE_REQUIRED_ROLES and store:
            raise serializers.ValidationError({
                "store": f"Store assignment is not allowed for {role} role."
            })

        return attrs

    def create(self, validated_data):
        """
        Create user with encrypted password.
        """
        # Remove password_confirm as it's not needed for user creation
        validated_data.pop('password_confirm')

        # Extract password for separate handling
        password = validated_data.pop('password')

        # Remove store if role doesn't require it
        role = validated_data.get('role')
        STORE_REQUIRED_ROLES = [User.STORE_MANAGER, User.SALESPERSON]
        
        if role not in STORE_REQUIRED_ROLES:
            validated_data.pop('store', None)

        # Create user with hashed password
        user = User.objects.create_user(
            password=password,
            **validated_data
        )
        
        return user

    def to_representation(self, instance):
        """
        Customize output representation.
        """
        representation = super().to_representation(instance)
        
        # Add store details if store exists
        if instance.store:
            representation['store'] = {
                'id': str(instance.store.id),
                'name': instance.store.name,
            }
        
        return representation


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

        store = request.user.store  
        is_active = validated_data.pop('is_active', True)

        # Create the salesperson (store not passed here)
        salesperson = CustomUser.objects.create_user(
            password=password,
            role=CustomUser.SALESPERSON,
            is_staff=False,
            is_active=is_active,
            **validated_data
        )

        # Assign store explicitly
        salesperson.store = store   
        salesperson.save()

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


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.all(),
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = User
        fields = [
            'email',
            'first_name',
            'last_name',
            'phone',
            'role',
            'store',
            'is_verified',
            'employee_id',
            'commission_rate',
            'is_active'
        ]
        
    def validate(self, attrs):
        instance = self.instance
        role = attrs.get('role', instance.role if instance else None)
        store = attrs.get('store', instance.store if instance else None)
        email = attrs.get('email')
        employee_id = attrs.get('employee_id')
        
        # Unique email validation excluding current user
        if email and User.objects.exclude(pk=instance.pk).filter(email=email).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
            
        # Unique employee_id validation excluding current user
        if employee_id and User.objects.exclude(pk=instance.pk).filter(employee_id=employee_id).exists():
            raise serializers.ValidationError({"employee_id": "A user with this employee ID already exists."})
            
        # Role-based store validation
        STORE_REQUIRED_ROLES = [User.STORE_MANAGER, User.SALESPERSON]
        if role in STORE_REQUIRED_ROLES and not store:
            raise serializers.ValidationError({"store": f"Store assignment is required for {role} role."})
            
        if role not in STORE_REQUIRED_ROLES and store:
            raise serializers.ValidationError({"store": f"Store assignment is not allowed for {role} role."})
            
        # If role is store_manager and store changes, make sure the store doesn't already have a manager
        if role == User.STORE_MANAGER and store:
            existing_manager = getattr(store, 'store_manager', None)
            if existing_manager and existing_manager != instance:
                raise serializers.ValidationError({"store": f"Store '{store.name}' already has a manager assigned."})
                
        return attrs

    def update(self, instance, validated_data):
        old_role = instance.role
        old_store = instance.store
        
        # Perform standard update
        user = super().update(instance, validated_data)
        
        new_role = user.role
        new_store = user.store
        
        # Clean up database relations
        
        # 1. If role is changing from sales_advisor to something else, clear advised_stores
        if old_role == User.SALES_ADVISOR and new_role != User.SALES_ADVISOR:
            Store.objects.filter(sales_advisor=user).update(sales_advisor=None)
            
        # 2. If role is changing from store_manager to something else, clear store_manager on old store
        if old_role == User.STORE_MANAGER and new_role != User.STORE_MANAGER:
            Store.objects.filter(store_manager=user).update(store_manager=None)
            
        # 3. If role is store_manager, manage the OneToOne relationship on Store
        if new_role == User.STORE_MANAGER:
            if old_role != User.STORE_MANAGER or old_store != new_store:
                # Clear old store manager assignment
                if old_store:
                    old_store.store_manager = None
                    old_store.save(update_fields=['store_manager'])
                
                # Assign new store manager assignment
                if new_store:
                    new_store.store_manager = user
                    new_store.save(update_fields=['store_manager'])
                    
        # 4. If role changed from store_manager, or store changed, clear manager link on old store
        elif old_role == User.STORE_MANAGER and old_store and old_store != new_store:
            old_store.store_manager = None
            old_store.save(update_fields=['store_manager'])
            
        # Sync phone/phone_number field
        if user.phone and not user.phone_number:
            user.phone_number = user.phone
            user.save(update_fields=['phone_number'])
        elif user.phone_number and not user.phone:
            user.phone = user.phone_number
            user.save(update_fields=['phone'])
            
        return user
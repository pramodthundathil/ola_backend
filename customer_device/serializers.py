# serializers.py
from rest_framework import serializers
from .models import DeviceEnrollmentCustomer
from finance.models import FinancePlan
from products.models import ProductModel
from customer.models import Customer


# --------------------------------------------------------
# Device Enrollment Create Serializer
# --------------------------------------------------------
class DeviceEnrollmentCreateSerializer(serializers.Serializer):
    finance_plan_id = serializers.IntegerField(
        help_text="Finance Plan ID - required"
    )
    imei = serializers.CharField(
        max_length=20,
        help_text="Device IMEI number - required and must be unique"
    )
    
    def validate_finance_plan_id(self, value):
        """Validate that finance plan exists and has a device"""
        try:
            finance_plan = FinancePlan.objects.get(id=value)
            if not finance_plan.device:
                raise serializers.ValidationError(
                    "Finance plan must have a device associated with it"
                )
        except FinancePlan.DoesNotExist:
            raise serializers.ValidationError(
                f"Finance plan with ID {value} does not exist"
            )
        
        return value
    
    def validate_imei(self, value):
        """Validate IMEI format and uniqueness"""
        # Check IMEI length (should be 15 digits)
        if not value.isdigit() or len(value) != 15:
            raise serializers.ValidationError(
                "IMEI must be exactly 15 digits"
            )
        
        # Check uniqueness
        if DeviceEnrollmentCustomer.objects.filter(imei=value).exists():
            raise serializers.ValidationError(
                f"Device with IMEI {value} is already enrolled"
            )
        
        return value


# --------------------------------------------------------
# Device Enrollment Detail Serializer
# --------------------------------------------------------
class DeviceEnrollmentSerializer(serializers.ModelSerializer):
    # Customer details
    customer_id = serializers.IntegerField(source='customer.id', read_only=True)
    customer_name = serializers.SerializerMethodField()
    customer_document = serializers.CharField(
        source='customer.document_number', 
        read_only=True
    )
    customer_phone = serializers.SerializerMethodField()
    
    # Finance plan details
    finance_plan_id = serializers.IntegerField(
        source='finance_plan.id', 
        read_only=True
    )
    
    # Device details
    device_name = serializers.SerializerMethodField()
    device_ola_code = serializers.CharField(
        source='device_model.ola_code', 
        read_only=True
    )
    device_brand = serializers.CharField(
        source='device_model.brand.name',
        read_only=True
    )
    
    # Display values
    locking_system_display = serializers.CharField(
        source='get_locking_system_display', 
        read_only=True
    )
    enrollment_status_display = serializers.CharField(
        source='get_enrollment_status_display', 
        read_only=True
    )
    
    # Status indicators
    can_be_locked = serializers.SerializerMethodField()
    enrollment_days_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = DeviceEnrollmentCustomer
        fields = [
            'id',
            'customer_id',
            'customer_name',
            'customer_document',
            'customer_phone',
            'finance_plan_id',
            'imei',
            'device_brand_name',
            'device_brand',
            'device_model',
            'device_name',
            'device_ola_code',
            'enrollment_status',
            'enrollment_status_display',
            'enrollment_qr_code',
            'enrollment_link',
            'locking_system',
            'locking_system_display',
            'locking_system_id',
            'is_locked',
            'lock_applied_at',
            'imei_verified',
            'device_has_internet',
            'enrollment_completed_at',
            'enrollment_failed_reason',
            'can_be_locked',
            'enrollment_days_ago',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 
            'created_at', 
            'updated_at',
            'enrollment_completed_at',
            'lock_applied_at'
        ]
    
    def get_customer_name(self, obj):
        """Get customer full name"""
        return f"{obj.customer.first_name} {obj.customer.last_name}"
    
    def get_customer_phone(self, obj):
        """Get customer phone number"""
        if hasattr(obj.customer, 'phone_number'):
            return obj.customer.phone_number
        return None
    
    def get_device_name(self, obj):
        """Get device full name"""
        return obj.device_model.get_full_name()
    
    def get_can_be_locked(self, obj):
        """Check if device can be locked"""
        return (
            obj.enrollment_status == 'COMPLETED' and
            not obj.is_locked and
            obj.locking_system in ['KNOX', 'NUOVOPAY']
        )
    
    def get_enrollment_days_ago(self, obj):
        """Get days since enrollment was created"""
        if obj.created_at:
            from django.utils import timezone
            delta = timezone.now() - obj.created_at
            return delta.days
        return None


# --------------------------------------------------------
# Device Enrollment Update Serializer
# --------------------------------------------------------
class DeviceEnrollmentUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating enrollment status and details"""
    
    class Meta:
        model = DeviceEnrollmentCustomer
        fields = [
            'enrollment_status',
            'enrollment_qr_code',
            'enrollment_link',
            'locking_system_id',
            'is_locked',
            'imei_verified',
            'device_has_internet',
            'enrollment_failed_reason'
        ]
    
    def validate_enrollment_status(self, value):
        """Validate status transitions"""
        instance = self.instance
        
        if instance:
            current_status = instance.enrollment_status
            
            # Don't allow reverting from COMPLETED to other statuses
            if current_status == 'COMPLETED' and value != 'COMPLETED':
                raise serializers.ValidationError(
                    "Cannot change status from COMPLETED to another status"
                )
        
        return value
    
    def validate(self, data):
        """Cross-field validation"""
        # If status is FAILED, require a reason
        if data.get('enrollment_status') == 'FAILED':
            if not data.get('enrollment_failed_reason'):
                raise serializers.ValidationError({
                    'enrollment_failed_reason': 'This field is required when status is FAILED'
                })
        
        return data


# --------------------------------------------------------
# Device Lock Serializer
# --------------------------------------------------------
class DeviceLockSerializer(serializers.Serializer):
    """Serializer for lock/unlock operations"""
    enrollment_id = serializers.IntegerField(
        help_text="Device Enrollment ID"
    )
    
    def validate_enrollment_id(self, value):
        """Validate that enrollment exists"""
        try:
            enrollment = DeviceEnrollmentCustomer.objects.get(id=value)
            
            # Additional validations can be added here
            if enrollment.locking_system == 'NONE':
                raise serializers.ValidationError(
                    "This device does not have a locking system configured"
                )
            
        except DeviceEnrollmentCustomer.DoesNotExist:
            raise serializers.ValidationError(
                f"Enrollment with ID {value} does not exist"
            )
        
        return value


# --------------------------------------------------------
# Device Enrollment List Serializer (Compact)
# --------------------------------------------------------
class DeviceEnrollmentListSerializer(serializers.ModelSerializer):
    """Compact serializer for list views"""
    customer_name = serializers.SerializerMethodField()
    device_name = serializers.SerializerMethodField()
    enrollment_status_display = serializers.CharField(
        source='get_enrollment_status_display', 
        read_only=True
    )
    locking_system_display = serializers.CharField(
        source='get_locking_system_display', 
        read_only=True
    )
    
    class Meta:
        model = DeviceEnrollmentCustomer
        fields = [
            'id',
            'customer_name',
            'imei',
            'device_name',
            'enrollment_status',
            'enrollment_status_display',
            'locking_system',
            'locking_system_display',
            'is_locked',
            'created_at',
        ]
    
    def get_customer_name(self, obj):
        return f"{obj.customer.first_name} {obj.customer.last_name}"
    
    def get_device_name(self, obj):
        return obj.device_model.get_full_name()
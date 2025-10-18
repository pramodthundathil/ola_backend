from rest_framework import serializers
from .models import Region, Province, District, Corregimiento, Store, StorePerformance
from home.models import CustomUser


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ['id', 'name', 'code', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class ProvinceSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source='region.name', read_only=True)
    
    class Meta:
        model = Province
        fields = ['id', 'region', 'region_name', 'name', 'code', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class DistrictSerializer(serializers.ModelSerializer):
    province_name = serializers.CharField(source='province.name', read_only=True)
    region_name = serializers.CharField(source='province.region.name', read_only=True)
    
    class Meta:
        model = District
        fields = ['id', 'province', 'province_name', 'region_name', 'name', 'code', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class CorregimientoSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    
    class Meta:
        model = Corregimiento
        fields = ['id', 'district', 'district_name', 'name', 'code', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class StoreManagerSerializer(serializers.ModelSerializer):
    """Minimal serializer for store manager info."""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    
    class Meta:
        model = CustomUser
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'phone', 'employee_id']
        read_only_fields = ['id']


class SalespersonSerializer(serializers.ModelSerializer):
    """Serializer for salesperson info."""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name', 
            'phone', 'employee_id', 'commission_rate', 'is_active', 'date_joined'
        ]
        read_only_fields = ['id', 'date_joined']


class StoreListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for store listings."""
    region_name = serializers.CharField(source='region.name', read_only=True)
    province_name = serializers.CharField(source='province.name', read_only=True)
    district_name = serializers.CharField(source='district.name', read_only=True)
    store_manager_name = serializers.CharField(source='store_manager.get_full_name', read_only=True)
    sales_advisor_name = serializers.CharField(source='sales_advisor.get_full_name', read_only=True)
    salespersons_count = serializers.IntegerField(source='get_salespersons_count', read_only=True)
    
    class Meta:
        model = Store
        fields = [
            'id', 'name', 'code', 'region_name', 'province_name', 'district_name',
            'store_manager_name', 'sales_advisor_name', 'channel', 'phone', 'email',
            'is_active', 'salespersons_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class StoreDetailSerializer(serializers.ModelSerializer):
    """Complete store information with all details."""
    region_details = RegionSerializer(source='region', read_only=True)
    province_details = ProvinceSerializer(source='province', read_only=True)
    district_details = DistrictSerializer(source='district', read_only=True)
    corregimiento_details = CorregimientoSerializer(source='corregimiento', read_only=True)
    
    store_manager_details = StoreManagerSerializer(source='store_manager', read_only=True)
    sales_advisor_details = StoreManagerSerializer(source='sales_advisor', read_only=True)
    
    salespersons = serializers.SerializerMethodField()
    salespersons_count = serializers.IntegerField(source='get_salespersons_count', read_only=True)
    full_address = serializers.CharField(source='get_full_address', read_only=True)
    
    class Meta:
        model = Store
        fields = [
            'id', 'name', 'code',
            'region', 'region_details',
            'province', 'province_details',
            'district', 'district_details',
            'corregimiento', 'corregimiento_details',
            'sales_advisor', 'sales_advisor_details',
            'store_manager', 'store_manager_details',
            'phone', 'email', 'channel', 'ruc',
            'latitude', 'longitude', 'image', 'address', 'full_address',
            'is_active', 'opening_date', 'monthly_target',
            'salespersons', 'salespersons_count',
            'created_at', 'updated_at', 'created_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']
    
    def get_salespersons(self, obj):
        """Get all salespersons for this store."""
        salespersons = obj.get_salespersons()
        return SalespersonSerializer(salespersons, many=True).data


class StoreCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating stores."""
    
    class Meta:
        model = Store
        fields = [
            'name', 'code', 'region', 'province', 'district', 'corregimiento',
            'sales_advisor', 'store_manager', 'phone', 'email', 'channel', 'ruc',
            'latitude', 'longitude', 'image', 'address', 'is_active', 
            'opening_date', 'monthly_target'
        ]
    
    def validate_code(self, value):
        """Ensure store code is unique."""
        if self.instance:
            if Store.objects.exclude(pk=self.instance.pk).filter(code=value).exists():
                raise serializers.ValidationError("Store with this code already exists.")
        else:
            if Store.objects.filter(code=value).exists():
                raise serializers.ValidationError("Store with this code already exists.")
        return value
    
    def validate_ruc(self, value):
        """Ensure RUC is unique."""
        if self.instance:
            if Store.objects.exclude(pk=self.instance.pk).filter(ruc=value).exists():
                raise serializers.ValidationError("Store with this RUC already exists.")
        else:
            if Store.objects.filter(ruc=value).exists():
                raise serializers.ValidationError("Store with this RUC already exists.")
        return value
    
    def validate_store_manager(self, value):
        """Validate store manager assignment."""
        if value:
            # Check if user has store_manager role
            if value.role != 'store_manager':
                raise serializers.ValidationError("Selected user is not a store manager.")
            
            # Check if manager is already assigned to another store
            if self.instance:
                existing_store = Store.objects.exclude(pk=self.instance.pk).filter(
                    store_manager=value
                ).first()
            else:
                existing_store = Store.objects.filter(store_manager=value).first()
            
            if existing_store:
                raise serializers.ValidationError(
                    f"This manager is already assigned to store: {existing_store.name}"
                )
        return value
    
    def validate_sales_advisor(self, value):
        """Validate sales advisor assignment."""
        if value and value.role != 'sales_advisor':
            raise serializers.ValidationError("Selected user is not a sales advisor.")
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        # Validate geographical hierarchy
        if 'province' in attrs and 'region' in attrs:
            if attrs['province'].region != attrs['region']:
                raise serializers.ValidationError(
                    "Selected province does not belong to the selected region."
                )
        
        if 'district' in attrs and 'province' in attrs:
            if attrs['district'].province != attrs['province']:
                raise serializers.ValidationError(
                    "Selected district does not belong to the selected province."
                )
        
        if 'corregimiento' in attrs and attrs['corregimiento'] and 'district' in attrs:
            if attrs['corregimiento'].district != attrs['district']:
                raise serializers.ValidationError(
                    "Selected corregimiento does not belong to the selected district."
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create store and assign created_by."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        return super().create(validated_data)


class AddSalespersonSerializer(serializers.Serializer):
    """Serializer for adding a salesperson to a store."""
    email = serializers.EmailField(required=True)
    first_name = serializers.CharField(max_length=150, required=True)
    last_name = serializers.CharField(max_length=150, required=True)
    phone = serializers.CharField(max_length=17, required=False, allow_blank=True)
    employee_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    commission_rate = serializers.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        required=False, 
        default=0.00
    )
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    
    def validate_email(self, value):
        """Check if email already exists."""
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("User with this email already exists.")
        return value
    
    def validate_employee_id(self, value):
        """Check if employee_id already exists."""
        if value and CustomUser.objects.filter(employee_id=value).exists():
            raise serializers.ValidationError("User with this employee ID already exists.")
        return value


class StorePerformanceSerializer(serializers.ModelSerializer):
    """Serializer for store performance metrics."""
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    month_display = serializers.SerializerMethodField()
    
    class Meta:
        model = StorePerformance
        fields = [
            'id', 'store', 'store_name', 'store_code', 'month', 'month_display',
            'total_sales', 'total_applications', 'approved_applications',
            'rejected_applications', 'pending_applications', 'total_revenue',
            'total_commissions', 'collections', 'defaults', 'new_customers',
            'returning_customers', 'target_achievement_percentage', 'approval_rate',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_month_display(self, obj):
        """Return formatted month."""
        return obj.month.strftime('%B %Y')
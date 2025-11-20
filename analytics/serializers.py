"""
Serializers for Analytics API
"""

from rest_framework import serializers
from .models import (
    SalesAnalytics, ApplicationFunnelAnalytics, DeviceEnrollmentAnalytics,
    BrandModelAnalytics, GeographicAnalytics, FPDAnalytics,
    FinancialMetrics, StoreRetentionAnalytics, ClerkPerformanceAnalytics,
    HourlyAnalytics
)
from store.models import Store


class SalesAnalyticsSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    salesperson_name = serializers.SerializerMethodField()
    
    class Meta:
        model = SalesAnalytics
        fields = [
            'id', 'date', 'store', 'store_name', 'salesperson', 'salesperson_name',
            'total_sales', 'total_sales_amount', 'active_stores_count',
            'avg_retail_price', 'avg_finance_amount', 'avg_down_payment_pct',
            'sales_per_active_store', 'created_at', 'updated_at'
        ]
    
    def get_salesperson_name(self, obj):
        if obj.salesperson:
            return obj.salesperson.get_full_name()
        return None


class ApplicationFunnelSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    salesperson_name = serializers.SerializerMethodField()
    
    class Meta:
        model = ApplicationFunnelAnalytics
        fields = [
            'id', 'date', 'store', 'store_name', 'salesperson', 'salesperson_name',
            'applications', 'kyc_completed', 'approved', 'sales',
            'kyc_success_rate', 'approval_rate', 'take_rate', 'conversion_rate',
            'created_at', 'updated_at'
        ]
    
    def get_salesperson_name(self, obj):
        if obj.salesperson:
            return obj.salesperson.get_full_name()
        return None


class DeviceEnrollmentSerializerAnalytics(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    lock_distribution = serializers.SerializerMethodField()
    
    class Meta:
        model = DeviceEnrollmentAnalytics
        fields = [
            'id', 'date', 'store', 'store_name',
            'lock_base_android', 'lock_android_dlc', 'lock_kpe', 'lock_kg',
            'lock_base_android_frp', 'lock_access', 'total_devices_enrolled',
            'lock_distribution', 'created_at', 'updated_at'
        ]
    
    def get_lock_distribution(self, obj):
        if obj.total_devices_enrolled == 0:
            return {}
        
        return {
            'BASEANDROID': round((obj.lock_base_android / obj.total_devices_enrolled) * 100, 2),
            'ANDROID_DLC': round((obj.lock_android_dlc / obj.total_devices_enrolled) * 100, 2),
            'KPE': round((obj.lock_kpe / obj.total_devices_enrolled) * 100, 2),
            'KG': round((obj.lock_kg / obj.total_devices_enrolled) * 100, 2),
            'BASEANDROID_FRP': round((obj.lock_base_android_frp / obj.total_devices_enrolled) * 100, 2),
            'ACCESS': round((obj.lock_access / obj.total_devices_enrolled) * 100, 2),
        }


class BrandModelAnalyticsSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = BrandModelAnalytics
        fields = [
            'date', 'store', 'store_name', 'brand', 'brand_name', 
            'device', 'model_name', 'sales_count', 'total_amount'
        ]

class GeographicAnalyticsSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source='region.name', read_only=True)
    
    class Meta:
        model = GeographicAnalytics
        fields = [
            'id', 'date', 'region', 'region_name', 'province_name', 'district_name',
            'sales_count', 'total_amount', 'created_at', 'updated_at'
        ]


class FPDAnalyticsSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = FPDAnalytics
        fields = [
            'id', 'date', 'store', 'store_name',
            'fpd_3_rate', 'fpd_7_rate', 'fpd_15_rate',
            'early_inactive_rate', 'pay_40_at_60_rate',
            'total_contracts', 'created_at', 'updated_at'
        ]


class FinancialMetricsSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    salesperson_name = serializers.SerializerMethodField()
    
    class Meta:
        model = FinancialMetrics
        fields = [
            'id', 'date', 'store', 'store_name', 'salesperson', 'salesperson_name',
            'total_revenue', 'total_financed_amount', 'total_down_payment',
            'avg_multiple', 'avg_term_months',
            'collections_received', 'outstanding_amount',
            'created_at', 'updated_at'
        ]
    
    def get_salesperson_name(self, obj):
        if obj.salesperson:
            return obj.salesperson.get_full_name()
        return None


class StoreRetentionSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = StoreRetentionAnalytics
        fields = [
            'id', 'date', 'store', 'store_name',
            'new_stores', 'existing_stores', 'returning_stores', 'churned_stores',
            'net_retention', 'created_at', 'updated_at'
        ]


class ClerkPerformanceSerializer(serializers.ModelSerializer):
    # Salesperson details
    salesperson_id = serializers.UUIDField(source='salesperson.id', read_only=True)
    salesperson_name = serializers.CharField(source='salesperson.get_full_name', read_only=True)
    salesperson_email = serializers.EmailField(source='salesperson.email', read_only=True)
    salesperson_phone = serializers.SerializerMethodField()
    
    # Store details
    store_id = serializers.UUIDField(source='store.id', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    
    class Meta:
        model = ClerkPerformanceAnalytics
        fields = [
            # Don't expose internal ID, use salesperson_id instead
            'date',
            
            # Salesperson info (for navigation)
            'salesperson_id',
            'salesperson_name',
            'salesperson_email',
            'salesperson_phone',
            
            # Store info (for navigation)
            'store_id',
            'store_name',
            'store_code',
            
            # Performance metrics
            'total_sales',
            'total_sales_amount',
            'applications_created',
            'applications_approved',
            'approval_rate',
            
            # Rankings
            'rank_in_store',
            'rank_overall',
            
            # Timestamps
            'created_at',
            'updated_at'
        ]
    
    def get_salesperson_phone(self, obj):
        """Get phone number, preferring 'phone' over 'phone_number'"""
        if obj.salesperson:
            return obj.salesperson.phone or obj.salesperson.phone_number
        return None


from home .models import CustomUser

class SalespersonDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for salesperson info"""
    store_id = serializers.UUIDField(source='store.id', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    phone = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = [
            'id',
            'email',
            'full_name',
            'first_name',
            'last_name',
            'phone',
            'employee_id',
            'commission_rate',
            'store_id',
            'store_name',
            'store_code',
            'is_active',
            'date_joined'
        ]
    
    def get_phone(self, obj):
        return obj.phone or obj.phone_number


class StorePerformanceSummarySerializer(serializers.ModelSerializer):
    """Store summary with performance metrics"""
    total_salespersons = serializers.IntegerField(read_only=True)
    total_sales = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    average_approval_rate = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    
    class Meta:
        model = Store
        fields = [
            'id',
            'name',
            'code',
            'total_salespersons',
            'total_sales',
            'total_amount',
            'average_approval_rate'
        ]


class HourlyAnalyticsSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = HourlyAnalytics
        fields = [
            'id', 'date', 'store', 'store_name', 'hour', 'day_of_week',
            'sales_count', 'created_at', 'updated_at'
        ]


# Summary Serializers for Dashboard Overview
class DashboardOverviewSerializer(serializers.Serializer):
    """Overall dashboard metrics"""
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    
    total_sales = serializers.IntegerField()
    total_sales_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_applications = serializers.IntegerField()
    
    avg_approval_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    avg_conversion_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    
    active_stores = serializers.IntegerField()
    active_salespersons = serializers.IntegerField()
    
    avg_fpd_3 = serializers.DecimalField(max_digits=5, decimal_places=2)
    avg_fpd_7 = serializers.DecimalField(max_digits=5, decimal_places=2)
    avg_fpd_15 = serializers.DecimalField(max_digits=5, decimal_places=2)
    
    total_financed_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    collections_received = serializers.DecimalField(max_digits=12, decimal_places=2)


class TopPerformerSerializer(serializers.Serializer):
    """Top performing entities"""
    type = serializers.CharField()  # 'store', 'salesperson', 'brand'
    name = serializers.CharField()
    sales_count = serializers.IntegerField()
    sales_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    rank = serializers.IntegerField()




"""
Django REST Framework Serializers for Analytics Dashboard
File: analytics/serializers.py
"""

from rest_framework import serializers
from .models import (
    DailyFinanceMetrics,
    BrandPerformanceMetrics,
    ProductPerformanceMetrics,
    SalespersonPerformance,
    PaymentCollectionMetrics,
    RiskAnalysisMetrics,
    GeographicPerformanceMetrics,
    DeviceLockPerformanceMetrics
)
from store.models import Store, Region
from products.models import Brand, ProductModel
from django.contrib.auth import get_user_model

User = get_user_model()


# ========================================
# DAILY FINANCE METRICS SERIALIZER
# ========================================

class DailyFinanceMetricsSerializer(serializers.ModelSerializer):
    """
    Serializer for daily finance metrics with computed fields
    """
    store_name = serializers.CharField(source='store.name', read_only=True)
    region_name = serializers.CharField(source='region.name', read_only=True)
    province_name = serializers.CharField(source='province.name', read_only=True)
    district_name = serializers.CharField(source='district.name', read_only=True)
    salesperson_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = DailyFinanceMetrics
        fields = [
            'id',
            'date',
            'store',
            'store_name',
            'region',
            'region_name',
            'province',
            'province_name',
            'district',
            'district_name',
            'created_by',
            'salesperson_name',
            
            # Application Metrics
            'total_applications',
            'approved_applications',
            'rejected_applications',
            'pending_applications',
            
            # Customer Metrics
            'new_customers',
            'returning_customers',
            'unique_customers',
            'kyc_completed',
            'kyc_success_rate',
            
            # Financial Metrics
            'total_sales_value',
            'total_financed_amount',
            'total_down_payment',
            'average_ticket_size',
            'average_finance_amount',
            'average_down_payment_pct',
            
            # Risk Tier Distribution
            'tier_a_count',
            'tier_b_count',
            'tier_c_count',
            'tier_d_count',
            
            # Payment Performance
            'total_payments_received',
            'total_payments_overdue',
            'fpd_3_rate',
            'fpd_7_rate',
            'fpd_15_rate',
            
            # Conversion Rates
            'approval_rate',
            'take_rate',
            'conversion_rate',
            
            # Device Lock Metrics
            'devices_enrolled',
            'devices_locked',
            
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# BRAND PERFORMANCE SERIALIZER
# ========================================

class BrandPerformanceMetricsSerializer(serializers.ModelSerializer):
    """
    Serializer for brand performance metrics
    """
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    brand_logo = serializers.ImageField(source='brand.logo', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True, allow_null=True)
    region_name = serializers.CharField(source='region.name', read_only=True, allow_null=True)
    
    class Meta:
        model = BrandPerformanceMetrics
        fields = [
            'id',
            'date',
            'brand',
            'brand_name',
            'brand_logo',
            'store',
            'store_name',
            'region',
            'region_name',
            'total_units_sold',
            'total_revenue',
            'average_price',
            'top_models',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# PRODUCT PERFORMANCE SERIALIZER
# ========================================

class ProductPerformanceMetricsSerializer(serializers.ModelSerializer):
    """
    Serializer for product performance metrics
    """
    product_name = serializers.CharField(source='product.model_name', read_only=True)
    product_ola_code = serializers.CharField(source='product.ola_code', read_only=True)
    brand_name = serializers.CharField(source='product.brand.name', read_only=True)
    product_image = serializers.ImageField(source='product.primary_image', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True, allow_null=True)
    region_name = serializers.CharField(source='region.name', read_only=True, allow_null=True)
    
    class Meta:
        model = ProductPerformanceMetrics
        fields = [
            'id',
            'date',
            'product',
            'product_name',
            'product_ola_code',
            'brand_name',
            'product_image',
            'store',
            'store_name',
            'region',
            'region_name',
            'units_sold',
            'revenue',
            'average_finance_term',
            'average_down_payment',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# SALESPERSON PERFORMANCE SERIALIZER
# ========================================

class SalespersonPerformanceSerializer(serializers.ModelSerializer):
    """
    Serializer for salesperson performance metrics
    """
    salesperson_name = serializers.CharField(source='salesperson.get_full_name', read_only=True)
    salesperson_email = serializers.EmailField(source='salesperson.email', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True, allow_null=True)
    
    class Meta:
        model = SalespersonPerformance
        fields = [
            'id',
            'date',
            'salesperson',
            'salesperson_name',
            'salesperson_email',
            'store',
            'store_name',
            'applications_created',
            'applications_approved',
            'applications_rejected',
            'total_sales',
            'total_financed',
            'commission_earned',
            'approval_rate',
            'average_processing_time',
            'new_customers_acquired',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# PAYMENT COLLECTION METRICS SERIALIZER
# ========================================

class PaymentCollectionMetricsSerializer(serializers.ModelSerializer):
    """
    Serializer for payment collection metrics
    """
    store_name = serializers.CharField(source='store.name', read_only=True, allow_null=True)
    region_name = serializers.CharField(source='region.name', read_only=True, allow_null=True)
    
    class Meta:
        model = PaymentCollectionMetrics
        fields = [
            'id',
            'date',
            'store',
            'store_name',
            'region',
            'region_name',
            'total_due',
            'total_collected',
            'total_overdue',
            'cash_collected',
            'yappy_collected',
            'punto_pago_collected',
            'western_union_collected',
            'bank_transfer_collected',
            'collection_rate',
            'on_time_payment_rate',
            'accounts_overdue',
            'accounts_30_days_overdue',
            'accounts_60_days_overdue',
            'accounts_90_days_plus_overdue',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# RISK ANALYSIS METRICS SERIALIZER
# ========================================

class RiskAnalysisMetricsSerializer(serializers.ModelSerializer):
    """
    Serializer for risk analysis metrics
    """
    store_name = serializers.CharField(source='store.name', read_only=True, allow_null=True)
    region_name = serializers.CharField(source='region.name', read_only=True, allow_null=True)
    risk_tier_display = serializers.CharField(source='get_risk_tier_display', read_only=True)
    
    class Meta:
        model = RiskAnalysisMetrics
        fields = [
            'id',
            'date',
            'risk_tier',
            'risk_tier_display',
            'store',
            'store_name',
            'region',
            'region_name',
            'total_accounts',
            'new_accounts',
            'active_accounts',
            'total_portfolio_value',
            'total_outstanding',
            'accounts_in_default',
            'default_rate',
            'average_days_overdue',
            'fpd_3_count',
            'fpd_7_count',
            'fpd_15_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# GEOGRAPHIC PERFORMANCE SERIALIZER
# ========================================

class GeographicPerformanceMetricsSerializer(serializers.ModelSerializer):
    """
    Serializer for geographic performance metrics
    """
    region_name = serializers.CharField(source='region.name', read_only=True)
    province_name = serializers.CharField(source='province.name', read_only=True, allow_null=True)
    district_name = serializers.CharField(source='district.name', read_only=True, allow_null=True)
    
    class Meta:
        model = GeographicPerformanceMetrics
        fields = [
            'id',
            'date',
            'region',
            'region_name',
            'province',
            'province_name',
            'district',
            'district_name',
            'active_stores',
            'total_stores',
            'total_applications',
            'total_sales',
            'average_ticket_size',
            'approval_rate',
            'collection_rate',
            'market_share_percentage',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# DEVICE LOCK PERFORMANCE SERIALIZER
# ========================================

class DeviceLockPerformanceMetricsSerializer(serializers.ModelSerializer):
    """
    Serializer for device lock performance metrics
    """
    store_name = serializers.CharField(source='store.name', read_only=True, allow_null=True)
    region_name = serializers.CharField(source='region.name', read_only=True, allow_null=True)
    
    class Meta:
        model = DeviceLockPerformanceMetrics
        fields = [
            'id',
            'date',
            'lock_system',
            'store',
            'store_name',
            'region',
            'region_name',
            'devices_enrolled',
            'enrollment_success_rate',
            'devices_locked',
            'devices_unlocked',
            'devices_active',
            'lock_failures',
            'unlock_requests',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ========================================
# AGGREGATED DASHBOARD SERIALIZER
# ========================================

class DashboardSummarySerializer(serializers.Serializer):
    """
    Comprehensive dashboard summary combining multiple metrics
    """
    date_range = serializers.DictField(child=serializers.DateField())
    
    # Summary KPIs
    total_applications = serializers.IntegerField()
    total_sales_value = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_customers = serializers.IntegerField()
    approval_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    
    # Trend Data (time series)
    sales_trend = serializers.ListField(child=serializers.DictField())
    applications_trend = serializers.ListField(child=serializers.DictField())
    
    # Risk Distribution
    risk_distribution = serializers.DictField()
    
    # Top Performers
    top_brands = serializers.ListField(child=serializers.DictField())
    top_products = serializers.ListField(child=serializers.DictField())
    top_stores = serializers.ListField(child=serializers.DictField())
    
    # Payment Performance
    collection_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    fpd_rates = serializers.DictField()
    
    # Geographic Distribution
    regional_performance = serializers.ListField(child=serializers.DictField())


# ========================================
# FILTER PARAMETERS SERIALIZER
# ========================================

class AnalyticsFilterSerializer(serializers.Serializer):
    """
    Serializer for validating analytics filter parameters
    """
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)
    store_id = serializers.UUIDField(required=False, allow_null=True)
    region_id = serializers.UUIDField(required=False, allow_null=True)
    province_id = serializers.UUIDField(required=False, allow_null=True)
    district_id = serializers.UUIDField(required=False, allow_null=True)
    salesperson_id = serializers.IntegerField(required=False, allow_null=True)
    risk_tier = serializers.ChoiceField(
        choices=['TIER_A', 'TIER_B', 'TIER_C', 'TIER_D'],
        required=False,
        allow_null=True
    )
    brand_id = serializers.IntegerField(required=False, allow_null=True)
    product_id = serializers.IntegerField(required=False, allow_null=True)
    
    def validate(self, data):
        """
        Validate date range
        """
        if data['start_date'] > data['end_date']:
            raise serializers.ValidationError({
                'end_date': 'End date must be after start date'
            })
        return data


# ========================================
# EXPORT SERIALIZER
# ========================================

class MetricsExportSerializer(serializers.Serializer):
    """
    Serializer for exporting metrics data
    """
    format = serializers.ChoiceField(choices=['csv', 'excel', 'pdf'], default='csv')
    metrics_type = serializers.ChoiceField(choices=[
        'daily_finance',
        'brand_performance',
        'product_performance',
        'salesperson_performance',
        'payment_collection',
        'risk_analysis',
        'geographic_performance',
        'device_lock_performance'
    ])
    filters = AnalyticsFilterSerializer()
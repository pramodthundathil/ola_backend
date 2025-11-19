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
            'id', 'date', 'store', 'store_name', 'brand_name', 'model_name',
            'sales_count', 'total_amount', 'created_at', 'updated_at'
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
    salesperson_name = serializers.CharField(source='salesperson.get_full_name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = ClerkPerformanceAnalytics
        fields = [
            'id', 'date', 'salesperson', 'salesperson_name', 'store', 'store_name',
            'total_sales', 'total_sales_amount', 'applications_created',
            'applications_approved', 'approval_rate',
            'rank_in_store', 'rank_overall', 'created_at', 'updated_at'
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
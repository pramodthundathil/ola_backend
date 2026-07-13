from rest_framework import serializers
from .models import (
    DailyAnalytics, MerchantAnalytics, BranchAnalytics, DeviceAnalytics,
    CustomerAnalytics, RiskAnalytics, ExecutiveAnalytics, CollectionAnalytics,
    DashboardSummary
)


class DailyAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyAnalytics
        fields = '__all__'


class MerchantAnalyticsSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)

    class Meta:
        model = MerchantAnalytics
        fields = '__all__'


class BranchAnalyticsSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_code = serializers.CharField(source='store.code', read_only=True)

    class Meta:
        model = BranchAnalytics
        fields = '__all__'


class DeviceAnalyticsSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    device_model = serializers.CharField(source='device.model_name', read_only=True)
    device_code = serializers.CharField(source='device.ola_code', read_only=True)

    class Meta:
        model = DeviceAnalytics
        fields = '__all__'


class CustomerAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAnalytics
        fields = '__all__'


class RiskAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskAnalytics
        fields = '__all__'


class ExecutiveAnalyticsSerializer(serializers.ModelSerializer):
    executive_name = serializers.CharField(source='executive.get_full_name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)

    class Meta:
        model = ExecutiveAnalytics
        fields = '__all__'


class CollectionAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollectionAnalytics
        fields = '__all__'


class DashboardSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardSummary
        fields = '__all__'


class AnalyticsFilterSerializer(serializers.Serializer):
    """
    Serializer to validate global filters for the dashboard
    """
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    branch = serializers.UUIDField(required=False)
    merchant = serializers.UUIDField(required=False)
    sales_executive = serializers.IntegerField(required=False)
    risk_category = serializers.CharField(required=False)
    device_model = serializers.IntegerField(required=False)
    brand = serializers.IntegerField(required=False)
    state = serializers.CharField(required=False)
    city = serializers.CharField(required=False)


class MetricsExportSerializer(serializers.Serializer):
    """
    Serializer to validate report export parameters
    """
    format = serializers.ChoiceField(choices=['csv', 'excel', 'pdf'], default='csv')
    report_type = serializers.ChoiceField(
        choices=['kpis', 'loans', 'customers', 'collections', 'risk', 'merchants', 'branches', 'devices'],
        default='kpis'
    )
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
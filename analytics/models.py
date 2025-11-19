"""
Analytics Models for Mobile Financing Application
Aggregated data models for dashboard analytics
"""

from django.db import models
from django.utils import timezone
from decimal import Decimal
from store.models import Store, Region
from home.models import CustomUser


class SalesAnalytics(models.Model):
    """
    Daily aggregated sales analytics
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='sales_analytics')
    salesperson = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sales_analytics', null=True, blank=True)
    
    # Sales Metrics
    total_sales = models.IntegerField(default=0, help_text="Number of sales")
    total_sales_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    active_stores_count = models.IntegerField(default=0)
    
    # Average Metrics
    avg_retail_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    avg_finance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    avg_down_payment_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Sales per Active Store
    sales_per_active_store = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sales_analytics'
        ordering = ['-date']
        unique_together = ['date', 'store', 'salesperson']
        indexes = [
            models.Index(fields=['date', 'store']),
            models.Index(fields=['date', 'salesperson']),
        ]


class ApplicationFunnelAnalytics(models.Model):
    """
    Daily application funnel metrics
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='funnel_analytics')
    salesperson = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='funnel_analytics', null=True, blank=True)
    
    # Funnel Stages
    applications = models.IntegerField(default=0)
    kyc_completed = models.IntegerField(default=0)
    approved = models.IntegerField(default=0)
    sales = models.IntegerField(default=0)
    
    # Conversion Rates
    kyc_success_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    take_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    conversion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'application_funnel_analytics'
        ordering = ['-date']
        unique_together = ['date', 'store', 'salesperson']


class DeviceEnrollmentAnalytics(models.Model):
    """
    Device enrollment and lock analytics
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='device_analytics')
    
    # Lock Type Distribution
    lock_base_android = models.IntegerField(default=0)
    lock_android_dlc = models.IntegerField(default=0)
    lock_kpe = models.IntegerField(default=0)
    lock_kg = models.IntegerField(default=0)
    lock_base_android_frp = models.IntegerField(default=0)
    lock_access = models.IntegerField(default=0)
    
    # Total Devices
    total_devices_enrolled = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'device_enrollment_analytics'
        ordering = ['-date']
        unique_together = ['date', 'store']


class BrandModelAnalytics(models.Model):
    """
    Sales by brand and model analytics
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='brand_analytics')
    
    # Brand name
    brand_name = models.CharField(max_length=100)
    model_name = models.CharField(max_length=200, null=True, blank=True)
    
    # Sales count
    sales_count = models.IntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'brand_model_analytics'
        ordering = ['-date', '-sales_count']
        indexes = [
            models.Index(fields=['date', 'brand_name']),
            models.Index(fields=['date', 'store']),
        ]


class GeographicAnalytics(models.Model):
    """
    Sales by geographic location (Department/City)
    """
    date = models.DateField(db_index=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='geographic_analytics', null=True)
    province_name = models.CharField(max_length=100, null=True, blank=True)
    district_name = models.CharField(max_length=100, null=True, blank=True)
    
    sales_count = models.IntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'geographic_analytics'
        ordering = ['-date', '-sales_count']


class FPDAnalytics(models.Model):
    """
    First Payment Default (FPD) Analytics
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='fpd_analytics')
    
    # FPD Metrics
    fpd_3_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    fpd_7_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    fpd_15_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Early Inactive
    early_inactive_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Pay 40 at 60 days
    pay_40_at_60_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Sample size
    total_contracts = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'fpd_analytics'
        ordering = ['-date']
        unique_together = ['date', 'store']


class FinancialMetrics(models.Model):
    """
    Financial performance metrics
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='financial_metrics')
    salesperson = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='financial_metrics', null=True, blank=True)
    
    # Revenue Metrics
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_financed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_down_payment = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Average Metrics
    avg_multiple = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    avg_term_months = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Collection Metrics
    collections_received = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    outstanding_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'financial_metrics'
        ordering = ['-date']
        unique_together = ['date', 'store', 'salesperson']


class StoreRetentionAnalytics(models.Model):
    """
    Store retention and churn analytics
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='retention_analytics')
    
    # Store Status
    new_stores = models.IntegerField(default=0)
    existing_stores = models.IntegerField(default=0)
    returning_stores = models.IntegerField(default=0)
    churned_stores = models.IntegerField(default=0)
    
    # Net Retention
    net_retention = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'store_retention_analytics'
        ordering = ['-date']
        unique_together = ['date', 'store']


class ClerkPerformanceAnalytics(models.Model):
    """
    Individual salesperson/clerk performance
    """
    date = models.DateField(db_index=True)
    salesperson = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='clerk_performance')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='clerk_performance')
    
    # Sales Metrics
    total_sales = models.IntegerField(default=0)
    total_sales_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Application Metrics
    applications_created = models.IntegerField(default=0)
    applications_approved = models.IntegerField(default=0)
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Ranking
    rank_in_store = models.IntegerField(null=True, blank=True)
    rank_overall = models.IntegerField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'clerk_performance_analytics'
        ordering = ['-date', '-total_sales']
        unique_together = ['date', 'salesperson']


class HourlyAnalytics(models.Model):
    """
    Sales by hour of day and day of week
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='hourly_analytics')
    hour = models.IntegerField()  # 0-23
    day_of_week = models.CharField(max_length=10)  # Monday, Tuesday, etc.
    
    sales_count = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'hourly_analytics'
        ordering = ['-date', 'hour']
        unique_together = ['date', 'store', 'hour']
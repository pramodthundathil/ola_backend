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
    lock_knox = models.IntegerField(default=0)  # ADD THIS FIELD
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
    avg_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))  # ADD THIS
    
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
    
    # FPD Metrics - Rates
    fpd_3_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    fpd_7_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    fpd_15_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # FPD Metrics - Counts (NEW FIELDS)
    fpd_3_count = models.IntegerField(default=0, help_text="Number of contracts in FPD-3")
    fpd_7_count = models.IntegerField(default=0, help_text="Number of contracts in FPD-7")
    fpd_15_count = models.IntegerField(default=0, help_text="Number of contracts in FPD-15")
    
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
    store = models.ForeignKey(Store, on_delete=models.SET_NULL, related_name='clerk_performance', null = True,blank = True )
    
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





"""
Django Models for Analytics Dashboard
File: analytics/models.py

Provides aggregated data models for efficient dashboard queries
with role-based access control
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Sum, Avg, Count, Q, F
from decimal import Decimal
from datetime import timedelta
from customer.models import Customer, CreditApplication, CreditScore
from finance.models import FinancePlan, PaymentRecord, EMISchedule
from store.models import Store, Region, Province, District
from products.models import ProductModel, Brand

User = get_user_model()


# ========================================
# DAILY AGGREGATED METRICS
# ========================================

class DailyFinanceMetrics(models.Model):
    """
    Daily aggregated metrics for finance performance
    Pre-calculated for fast dashboard loading
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, null=True, blank=True)
    province = models.ForeignKey(Province, on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Application Metrics
    total_applications = models.IntegerField(default=0)
    approved_applications = models.IntegerField(default=0)
    rejected_applications = models.IntegerField(default=0)
    pending_applications = models.IntegerField(default=0)
    
    # Customer Metrics
    new_customers = models.IntegerField(default=0)
    returning_customers = models.IntegerField(default=0)
    unique_customers = models.IntegerField(default=0)
    kyc_completed = models.IntegerField(default=0)
    kyc_success_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Financial Metrics
    total_sales_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_financed_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_down_payment = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    average_ticket_size = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    average_finance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    average_down_payment_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Risk Tier Distribution
    tier_a_count = models.IntegerField(default=0)
    tier_b_count = models.IntegerField(default=0)
    tier_c_count = models.IntegerField(default=0)
    tier_d_count = models.IntegerField(default=0)
    
    # Payment Performance
    total_payments_received = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_payments_overdue = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fpd_3_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    fpd_7_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    fpd_15_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Conversion Rates
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    take_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    conversion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Device Lock Metrics
    devices_enrolled = models.IntegerField(default=0)
    devices_locked = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'daily_finance_metrics'
        ordering = ['-date']
        unique_together = ['date', 'store', 'region']
        indexes = [
            models.Index(fields=['date', 'store']),
            models.Index(fields=['date', 'region']),
            models.Index(fields=['created_by', 'date']),
        ]
    
    def __str__(self):
        location = self.store.name if self.store else self.region.name if self.region else "Global"
        return f"{location} - {self.date}"


# ========================================
# BRAND & PRODUCT PERFORMANCE
# ========================================

class BrandPerformanceMetrics(models.Model):
    """
    Track sales performance by brand
    """
    date = models.DateField(db_index=True)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, null=True, blank=True)
    
    # Sales Metrics
    total_units_sold = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    average_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Popular Models (JSON)
    top_models = models.JSONField(default=list, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'brand_performance_metrics'
        ordering = ['-date', '-total_revenue']
        unique_together = ['date', 'brand', 'store']
        indexes = [
            models.Index(fields=['date', 'brand']),
            models.Index(fields=['brand', '-total_revenue']),
        ]
    
    def __str__(self):
        return f"{self.brand.name} - {self.date}"


class ProductPerformanceMetrics(models.Model):
    """
    Track sales performance by product model
    """
    date = models.DateField(db_index=True)
    product = models.ForeignKey(ProductModel, on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, null=True, blank=True)
    
    # Sales Metrics
    units_sold = models.IntegerField(default=0)
    revenue = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    average_finance_term = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    average_down_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product_performance_metrics'
        ordering = ['-date', '-units_sold']
        unique_together = ['date', 'product', 'store']
        indexes = [
            models.Index(fields=['date', 'product']),
            models.Index(fields=['product', '-units_sold']),
        ]
    
    def __str__(self):
        return f"{self.product.ola_code} - {self.date}"


# ========================================
# SALESPERSON PERFORMANCE
# ========================================

class SalespersonPerformance(models.Model):
    """
    Track individual salesperson performance
    """
    date = models.DateField(db_index=True)
    salesperson = models.ForeignKey(User, on_delete=models.CASCADE, related_name='performance_metrics')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    
    # Activity Metrics
    applications_created = models.IntegerField(default=0)
    applications_approved = models.IntegerField(default=0)
    applications_rejected = models.IntegerField(default=0)
    
    # Financial Metrics
    total_sales = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_financed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    commission_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Efficiency Metrics
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    average_processing_time = models.IntegerField(default=0, help_text="Minutes")
    
    # Customer Metrics
    new_customers_acquired = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'salesperson_performance'
        ordering = ['-date', '-total_sales']
        unique_together = ['date', 'salesperson']
        indexes = [
            models.Index(fields=['date', 'salesperson']),
            models.Index(fields=['salesperson', '-total_sales']),
            models.Index(fields=['store', 'date']),
        ]
    
    def __str__(self):
        return f"{self.salesperson.get_full_name()} - {self.date}"


# ========================================
# PAYMENT COLLECTION METRICS
# ========================================

class PaymentCollectionMetrics(models.Model):
    """
    Track payment collection performance
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, null=True, blank=True)
    
    # Collection Metrics
    total_due = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_overdue = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Payment Methods
    cash_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    yappy_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    punto_pago_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    western_union_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    bank_transfer_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Performance Indicators
    collection_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    on_time_payment_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Delinquency
    accounts_overdue = models.IntegerField(default=0)
    accounts_30_days_overdue = models.IntegerField(default=0)
    accounts_60_days_overdue = models.IntegerField(default=0)
    accounts_90_days_plus_overdue = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payment_collection_metrics'
        ordering = ['-date']
        unique_together = ['date', 'store', 'region']
        indexes = [
            models.Index(fields=['date', 'store']),
            models.Index(fields=['date', 'region']),
        ]
    
    def __str__(self):
        location = self.store.name if self.store else self.region.name if self.region else "Global"
        return f"{location} - {self.date}"


# ========================================
# RISK ANALYSIS METRICS
# ========================================

class RiskAnalysisMetrics(models.Model):
    """
    Track risk distribution and performance by tier
    """
    date = models.DateField(db_index=True)
    risk_tier = models.CharField(max_length=10, choices=[
        ('TIER_A', 'Tier A'),
        ('TIER_B', 'Tier B'),
        ('TIER_C', 'Tier C'),
        ('TIER_D', 'Tier D'),
    ])
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, null=True, blank=True)
    
    # Volume Metrics
    total_accounts = models.IntegerField(default=0)
    new_accounts = models.IntegerField(default=0)
    active_accounts = models.IntegerField(default=0)
    
    # Financial Metrics
    total_portfolio_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_outstanding = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Risk Metrics
    accounts_in_default = models.IntegerField(default=0)
    default_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    average_days_overdue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Performance
    fpd_3_count = models.IntegerField(default=0)
    fpd_7_count = models.IntegerField(default=0)
    fpd_15_count = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'risk_analysis_metrics'
        ordering = ['-date', 'risk_tier']
        unique_together = ['date', 'risk_tier', 'store']
        indexes = [
            models.Index(fields=['date', 'risk_tier']),
            models.Index(fields=['risk_tier', 'store']),
        ]
    
    def __str__(self):
        location = self.store.name if self.store else self.region.name if self.region else "Global"
        return f"{self.risk_tier} - {location} - {self.date}"


# ========================================
# GEOGRAPHIC PERFORMANCE METRICS
# ========================================

class GeographicPerformanceMetrics(models.Model):
    """
    Track performance by geographic location
    """
    date = models.DateField(db_index=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE)
    province = models.ForeignKey(Province, on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, null=True, blank=True)
    
    # Store Metrics
    active_stores = models.IntegerField(default=0)
    total_stores = models.IntegerField(default=0)
    
    # Sales Metrics
    total_applications = models.IntegerField(default=0)
    total_sales = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    average_ticket_size = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Performance
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    collection_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Market Penetration
    market_share_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'geographic_performance_metrics'
        ordering = ['-date', 'region']
        unique_together = ['date', 'region', 'province', 'district']
        indexes = [
            models.Index(fields=['date', 'region']),
            models.Index(fields=['region', 'province']),
        ]
    
    def __str__(self):
        location = f"{self.region.name}"
        if self.province:
            location += f" - {self.province.name}"
        if self.district:
            location += f" - {self.district.name}"
        return f"{location} - {self.date}"


# ========================================
# DEVICE LOCK PERFORMANCE
# ========================================

class DeviceLockPerformanceMetrics(models.Model):
    """
    Track device locking system performance
    """
    date = models.DateField(db_index=True)
    lock_system = models.CharField(max_length=20, choices=[
        ('KNOX', 'Samsung KNOX'),
        ('NUOVOPAY', 'NuovoPay'),
        ('BASEANDROID', 'Base Android'),
        ('ACCESS', 'Access Control'),
    ])
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, null=True, blank=True)
    
    # Enrollment Metrics
    devices_enrolled = models.IntegerField(default=0)
    enrollment_success_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Lock Status
    devices_locked = models.IntegerField(default=0)
    devices_unlocked = models.IntegerField(default=0)
    devices_active = models.IntegerField(default=0)
    
    # Performance
    lock_failures = models.IntegerField(default=0)
    unlock_requests = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'device_lock_performance_metrics'
        ordering = ['-date', 'lock_system']
        unique_together = ['date', 'lock_system', 'store']
        indexes = [
            models.Index(fields=['date', 'lock_system']),
            models.Index(fields=['lock_system', 'store']),
        ]
    
    def __str__(self):
        location = self.store.name if self.store else self.region.name if self.region else "Global"
        return f"{self.lock_system} - {location} - {self.date}"


# ========================================
# HELPER MANAGER FOR AGGREGATIONS
# ========================================

class MetricsAggregator:
    """
    Helper class to aggregate metrics for different time periods and scopes
    """
    
    @staticmethod
    def aggregate_daily_metrics(date, store=None, region=None, user=None):
        """
        Aggregate and create/update daily metrics
        """
        filters = {'created_at__date': date}
        
        if store:
            filters['finance_plan__store'] = store
        elif region:
            filters['finance_plan__store__region'] = region
        elif user and user.role == User.SALESPERSON:
            filters['finance_plan__created_by'] = user
        
        # Get finance plans for the date
        finance_plans = FinancePlan.objects.filter(**filters)
        
        # Calculate metrics
        total_apps = finance_plans.count()
        approved = finance_plans.filter(conditions_met=True).count()
        rejected = finance_plans.filter(requires_adjustment=True).count()
        
        metrics_data = {
            'date': date,
            'store': store,
            'region': region,
            'created_by': user,
            'total_applications': total_apps,
            'approved_applications': approved,
            'rejected_applications': rejected,
            'total_sales_value': finance_plans.aggregate(total=Sum('device_price'))['total'] or 0,
            'total_financed_amount': finance_plans.aggregate(total=Sum('amount_to_finance'))['total'] or 0,
            'average_ticket_size': finance_plans.aggregate(avg=Avg('device_price'))['avg'] or 0,
            'approval_rate': (approved / total_apps * 100) if total_apps > 0 else 0,
        }
        
        # Create or update metrics
        daily_metric, created = DailyFinanceMetrics.objects.update_or_create(
            date=date,
            store=store,
            region=region,
            defaults=metrics_data
        )
        
        return daily_metric
from django.db import models
from django.contrib.auth import get_user_model
from decimal import Decimal
from store.models import Store
from products.models import Brand, ProductModel

User = get_user_model()


class DailyAnalytics(models.Model):
    """
    Daily aggregated sales, applications, and funnel analytics
    """
    date = models.DateField(unique=True, db_index=True)
    
    # Application Metrics
    total_applications = models.IntegerField(default=0)
    approved_applications = models.IntegerField(default=0)
    rejected_applications = models.IntegerField(default=0)
    pending_applications = models.IntegerField(default=0)
    
    # Financial metrics
    disbursed_loans = models.IntegerField(default=0)
    total_loan_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_disbursed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    outstanding_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_collection = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    interest_earned = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    processing_fees = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    profit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # PDF Specific Metrics
    active_stores = models.IntegerField(default=0)
    sales_per_active_store = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    avg_retail_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    avg_finance_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    avg_down_payment_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Funnel and Conversion Rates
    kyc_success_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    take_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    conversion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Store Retention Details (New, Existing, Returning, Churned)
    store_retention_new = models.IntegerField(default=0)
    store_retention_existing = models.IntegerField(default=0)
    store_retention_returning = models.IntegerField(default=0)
    store_retention_churned = models.IntegerField(default=0)
    
    # Hourly & Day of Week sales counts (Heatmap data: { 'Sunday': [0...23], 'Monday': [0...23], ... })
    sales_by_hour_day = models.JSONField(default=dict)
    
    # Funnel Stages detail
    funnel_stages_count = models.JSONField(default=dict)
    
    # Operations
    avg_approval_time = models.IntegerField(default=0, help_text="in seconds")
    avg_disbursement_time = models.IntegerField(default=0, help_text="in seconds")
    avg_payment_delay = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'), help_text="in days")
    avg_recovery_time = models.IntegerField(default=0, help_text="in days")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'daily_analytics'
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"Daily Analytics for {self.date}"


class MerchantAnalytics(models.Model):
    """
    Merchant (store) performance analytics aggregated daily
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='merchant_analytics_records')
    
    total_applications = models.IntegerField(default=0)
    approved_applications = models.IntegerField(default=0)
    rejected_applications = models.IntegerField(default=0)
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    total_sales = models.IntegerField(default=0)
    total_sales_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_collections = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    commission = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    default_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    growth_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_analytics'
        unique_together = ['date', 'store']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'store']),
        ]

    def __str__(self):
        return f"Merchant Analytics for {self.store.name} on {self.date}"


class BranchAnalytics(models.Model):
    """
    Branch performance metrics aggregated daily
    """
    date = models.DateField(db_index=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='branch_analytics_records')
    
    total_applications = models.IntegerField(default=0)
    approved_applications = models.IntegerField(default=0)
    disbursed_loans = models.IntegerField(default=0)
    total_disbursed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    collections = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    recovery_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    profit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    ranking = models.IntegerField(default=0)
    
    # Regional dimensions for fast geographic sorting/filtering
    region_name = models.CharField(max_length=100, null=True, blank=True)
    province_name = models.CharField(max_length=100, null=True, blank=True)
    district_name = models.CharField(max_length=100, null=True, blank=True)
    city_name = models.CharField(max_length=100, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'branch_analytics'
        unique_together = ['date', 'store']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'store']),
            models.Index(fields=['region_name']),
            models.Index(fields=['city_name']),
        ]

    def __str__(self):
        return f"Branch Analytics for {self.store.name} on {self.date}"


class DeviceAnalytics(models.Model):
    """
    Device and OEM sales / defaults analytics aggregated daily
    """
    date = models.DateField(db_index=True)
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE)
    device = models.ForeignKey(ProductModel, on_delete=models.CASCADE)
    
    units_sold = models.IntegerField(default=0)
    total_sales_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    avg_price = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    avg_down_payment = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    avg_finance_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Lock types distribution
    lock_base_android = models.IntegerField(default=0)
    lock_dlc = models.IntegerField(default=0)
    lock_kpe = models.IntegerField(default=0)
    lock_kg = models.IntegerField(default=0)
    lock_knox = models.IntegerField(default=0)
    lock_base_android_frp = models.IntegerField(default=0)
    lock_access = models.IntegerField(default=0)
    
    default_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'device_analytics'
        unique_together = ['date', 'brand', 'device']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'brand', 'device']),
        ]

    def __str__(self):
        return f"Device Analytics for {self.brand.name} {self.device.ola_code} on {self.date}"


class CustomerAnalytics(models.Model):
    """
    Customer demographics and BI metrics aggregated daily
    """
    date = models.DateField(unique=True, db_index=True)
    
    new_customers = models.IntegerField(default=0)
    returning_customers = models.IntegerField(default=0)
    repeat_financing_count = models.IntegerField(default=0)
    
    # Demographics histograms stored as JSON objects
    age_distribution = models.JSONField(default=dict)
    gender_distribution = models.JSONField(default=dict)
    employment_distribution = models.JSONField(default=dict)
    income_distribution = models.JSONField(default=dict)
    credit_score_distribution = models.JSONField(default=dict)
    
    customer_lifetime_value_avg = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_analytics'
        ordering = ['-date']

    def __str__(self):
        return f"Customer Demographics for {self.date}"


class RiskAnalytics(models.Model):
    """
    Risk and credit portfolio metrics aggregated daily
    """
    date = models.DateField(unique=True, db_index=True)
    
    high_risk_customers_count = models.IntegerField(default=0)
    low_risk_customers_count = models.IntegerField(default=0)
    
    credit_score_distribution = models.JSONField(default=dict)
    default_probability_avg = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    fraud_detected_count = models.IntegerField(default=0)
    early_delinquency_count = models.IntegerField(default=0)
    
    # Portfolio At Risk (PAR)
    par_30_count = models.IntegerField(default=0)
    par_60_count = models.IntegerField(default=0)
    par_90_count = models.IntegerField(default=0)
    par_30_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    par_60_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    par_90_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Non Performing Assets (NPA)
    npa_count = models.IntegerField(default=0)
    npa_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    default_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # First Payment Default (FPD) Rates and Delinquency
    fpd_3_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    fpd_7_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    fpd_15_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    early_inactive_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    pay_40_at_60_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # OEM & Model Specific FPD Rates
    fpd_by_oem = models.JSONField(default=dict)
    fpd_by_model = models.JSONField(default=dict)
    
    recovery_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    recovery_trend = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'risk_analytics'
        ordering = ['-date']

    def __str__(self):
        return f"Risk Analytics for {self.date}"


class ExecutiveAnalytics(models.Model):
    """
    Sales Executive performance BI aggregated daily
    """
    date = models.DateField(db_index=True)
    executive = models.ForeignKey(User, on_delete=models.CASCADE, related_name='executive_analytics')
    store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True)
    
    applications = models.IntegerField(default=0)
    approvals = models.IntegerField(default=0)
    sales_count = models.IntegerField(default=0)
    sales_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    collections = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    recovery_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    conversion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'executive_analytics'
        unique_together = ['date', 'executive']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'executive']),
        ]

    def __str__(self):
        return f"Executive Performance for {self.executive.get_full_name()} on {self.date}"


class CollectionAnalytics(models.Model):
    """
    Re-payment and Collections statistics aggregated daily
    """
    date = models.DateField(unique=True, db_index=True)
    
    emi_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    principal_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    interest_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    penalty_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    collection_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    recovery_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    missed_payments_count = models.IntegerField(default=0)
    late_payments_count = models.IntegerField(default=0)
    
    outstanding_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Collections breakdown by payment modes
    cash_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    yappy_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    punto_pago_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    western_union_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    bank_transfer_collected = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'collection_analytics'
        ordering = ['-date']

    def __str__(self):
        return f"Collections Summary for {self.date}"


class DashboardSummary(models.Model):
    """
    Global KPIs for executive summary dashboard cards
    """
    date = models.DateField(unique=True, db_index=True)
    
    # KPI metrics (Summary cards)
    total_applications = models.IntegerField(default=0)
    total_customers = models.IntegerField(default=0)
    active_loans = models.IntegerField(default=0)
    closed_loans = models.IntegerField(default=0)
    pending_applications = models.IntegerField(default=0)
    approved_applications = models.IntegerField(default=0)
    rejected_applications = models.IntegerField(default=0)
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    total_loan_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_disbursed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    outstanding_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_collection = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    interest_earned = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    processing_fees = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    profit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    collection_today = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    collection_this_month = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_emi_due = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_overdue_emi = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    par_30 = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    par_60 = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    par_90 = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    npa_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    default_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dashboard_summary'
        ordering = ['-date']

    def __str__(self):
        return f"Executive Summary for {self.date}"
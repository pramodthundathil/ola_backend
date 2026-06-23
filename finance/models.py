from django.db import models 
from django.contrib.auth import get_user_model
from datetime import timedelta
from customer.models import CreditApplication, Customer
from django.core.cache import cache
from store.models import Store

from decimal import Decimal, ROUND_UP, InvalidOperation
from django.core.exceptions import ValidationError
User = get_user_model()


# ========================================
# PAYMENT RECORD MODEL
# ========================================

# class PaymentRecord(models.Model):
#     """
#     Tracks all payments made by customers.
    
#     Payment Methods:
#     - Punto Pago
#     - Yappy
#     - Western Union
#     """
    
#     PAYMENT_METHOD_CHOICES = [
#         ('PUNTO_PAGO', 'Punto Pago'),
#         ('YAPPY', 'Yappy'),
#         ('WESTERN_UNION', 'Western Union'),
#         ('CASH', 'Cash'),
#         ('OTHER', 'Other'),
#     ]
    
#     PAYMENT_STATUS_CHOICES = [
#         ('PENDING', 'Pending'),
#         ('COMPLETED', 'Completed'),
#         ('FAILED', 'Failed'),
#         ('REFUNDED', 'Refunded'),
#     ]
    
#    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     credit_application = models.ForeignKey(
#         CreditApplication,
#         on_delete=models.CASCADE,
#         related_name='payments'
#     )
    
#     payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
#     payment_amount = models.DecimalField(max_digits=10, decimal_places=2)
#     payment_date = models.DateTimeField()
#     payment_status = models.CharField(
#         max_length=20,
#         choices=PAYMENT_STATUS_CHOICES,
#         default='PENDING'
#     )
    
#     transaction_reference = models.CharField(
#         max_length=100,
#         null=True,
#         blank=True,
#         help_text="External payment reference number"
#     )
    
#     is_initial_payment = models.BooleanField(
#         default=False,
#         help_text="True if this is the initial/down payment"
#     )
#     installment_number = models.IntegerField(
#         null=True,
#         blank=True,
#         help_text="Which installment number this payment covers"
#     )
    
#     notes = models.TextField(null=True, blank=True)
    
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
    
#     class Meta:
#         db_table = 'payment_records'
#         ordering = ['-payment_date']
#         indexes = [
#             models.Index(fields=['credit_application', '-payment_date']),
#             models.Index(fields=['payment_status']),
#         ]
    
#     def __str__(self):
#         return f"Payment {self.payment_amount} for App {self.credit_application.id}"


# ========================================
# AUDIT LOG MODEL
# ========================================

class AuditLog(models.Model):
    """
    Tracks all important actions in the system for compliance and debugging.
    """
    
    ACTION_TYPE_CHOICES = [
        ('CUSTOMER_CREATED', 'Customer Created'),
        ('CREDIT_SCORE_CHECKED', 'Credit Score Checked'),
        ('APC_CONSULTED', 'APC Consulted'),
        ('IDENTITY_VERIFIED', 'Identity Verified'),
        ('APPLICATION_CREATED', 'Application Created'),
        ('APPLICATION_APPROVED', 'Application Approved'),
        ('APPLICATION_REJECTED', 'Application Rejected'),
        ('DEVICE_ENROLLED', 'Device Enrolled'),
        ('PAYMENT_RECEIVED', 'Payment Received'),
        ('DEVICE_LOCKED', 'Device Locked'),
        ('DEVICE_UNLOCKED', 'Device Unlocked'),
        ('AUTO_FINANCE_PLAN_CREATED', 'Auto Finance Plan Created'),
        ('FINANCE_PLAN_CREATED', 'Finance Plan Created'),
        ('FINANCE_PLAN_VIEWED', 'Finance Plan Viewed'),
        ('FINANCE_REPORT_VIEWED','Finance Report Viewed'),
        ('CREATE_PAYMENT','Create Payment'),
        ('PAYMENT_VIEWED','Payment Viewed'),
        ('CREATE_EMI_PAYMENT', 'Create EMI Payment'),
        ('VIEW_EMI_SCHEDULE','View EMI Schedule'),
        ('COMPLETE_FINANCE_VIEWED','Complete Finance Viewed'),


    ]
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    action_type = models.CharField(max_length=50, choices=ACTION_TYPE_CHOICES)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs'
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs'
    )
    credit_application = models.ForeignKey(
        CreditApplication,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs'
    )
    
    description = models.TextField()
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional data related to the action"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action_type']),
        ]
    
    def __str__(self):
        return f"{self.action_type} by {self.user} at {self.created_at}"


from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from customer.models import CreditApplication, Customer, CreditScore
from django.contrib.auth import get_user_model
from products.models import ProductModel

User = get_user_model()


# ========================================
# FINANCE PLAN MODEL
# ========================================

class FinancePlan(models.Model):
    """
    Manages financing plans with EMI calculation based on APC risk tiers.
    
    Risk Tiers:
    - Tier A (Low Risk): APC ≥ 600
    - Tier B (Medium): APC 550-599
    - Tier C (High): APC 500-549
    - Tier D (Very High): APC < 500
    
    Business Rules:
    - EMI calculation based on risk tier
    - Payment capacity: monthly_installment ≤ k × monthly_income
    - Minimum down payment varies by tier
    - Interest-free financing (0% interest)
    """
    
    RISK_TIER_CHOICES = [
        ('TIER_A', 'Tier A - Low Risk (APC ≥ 600)'),
        ('TIER_B', 'Tier B - Medium Risk (APC 550-599)'),
        ('TIER_C', 'Tier C - High Risk (APC 500-549)'),
        ('TIER_D', 'Tier D - Very High Risk (APC < 500)'),
    ]
    
    TERM_CHOICES = [
        (4, '4 Months'),
        (6, '6 Months'),
        (8, '8 Months'),
    ]
    FREQUENCY_CHOICES = [
        (10, '10 Days'),
        (15, '15 Days (Bi-Monthly)'),
        (30, '30 Days (Monthly)'),
    ]
    
    # String reference: AutoFinancePlan defined below FinancePlan
    auto_plan = models.ForeignKey("AutoFinancePlan", on_delete=models.SET_NULL, null=True, blank=True)
   
    credit_application = models.OneToOneField(
        CreditApplication,
        on_delete=models.CASCADE,
        related_name='finance_plan'
    )
    credit_score = models.ForeignKey(
        CreditScore,
        on_delete=models.SET_NULL,
        null=True,
        related_name='finance_plans'
    )
    
    # Risk Assessment
    apc_score = models.IntegerField(help_text="APC score from credit bureau")
    risk_tier = models.CharField(max_length=10, choices=RISK_TIER_CHOICES)
    
    # Device and Pricing
    device_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total device price including 7% ITBMS tax"
    )

    device = models.ForeignKey(ProductModel, on_delete=models.DO_NOTHING, null=True, blank = True)
    is_high_end_device = models.BooleanField(
        default=False,
        help_text="Device price > $300"
    )
    
    # Down Payment
    minimum_down_payment_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Minimum % required based on risk tier"
    )
    actual_down_payment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Actual down payment amount"
    )
    down_payment_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Actual down payment %"
    )
    
    # Financing Amount
    amount_to_finance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Device price - down payment"
    )
    
    # Term and Installments
    allowed_terms = models.JSONField(
        help_text="List of allowed terms based on risk tier",
        default=list
    )
    selected_term = models.IntegerField(
        choices=TERM_CHOICES,
        help_text="Selected term in months"
    )
    installment_frequency_days = models.IntegerField(
        choices=FREQUENCY_CHOICES,
        default=30,
        help_text="Installment frequency: 10 days or 15 days (bi-monthly) or 30 days (monthly)"
    )
    
    # EMI Calculation (Interest-Free)
    monthly_installment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Monthly EMI amount (rounded, no cents)"
    )
    total_amount_payable = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total amount = down payment + (EMI × term)"
    )
    
    # Payment Capacity Check
    customer_monthly_income = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Validated or declared monthly income"
    )
    payment_capacity_factor = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="k factor based on risk tier (0.10-0.30)"
    )
    maximum_allowed_installment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="k × monthly_income"
    )
    installment_to_income_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Actual EMI / monthly_income"
    )
    payment_capacity_passed = models.BooleanField(default=False)
    
    # Approval Status
    conditions_met = models.BooleanField(default=False)
    requires_adjustment = models.BooleanField(default=False)
    adjustment_notes = models.TextField(null=True, blank=True)
    
    # Scoring
    final_score = models.IntegerField(
        null=True,
        blank=True,
        help_text="Weighted final score (0-100)"
    )
    score_status = models.CharField(
        max_length=20,
        choices=[
            ('APPROVED', 'Approved (≥80)'),
            ('CONDITIONAL', 'Approved with Conditions (60-79)'),
            ('REJECTED', 'Rejected (<60)'),
        ],
        null=True,
        blank=True
    )
    # new ly added fields for easy calculation of finance by store and creator    
    store = models.ForeignKey(Store, on_delete=models.DO_NOTHING, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.DO_NOTHING)
    status = models.CharField(max_length=20, choices=[("ACTIVE", "Active"), ("CLOSED", "Closed")]) 
    is_active = models.BooleanField(default=True) 

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'finance_plans'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['credit_application']),
            models.Index(fields=['risk_tier']),
            models.Index(fields=['apc_score']),
        ]
    
    def __str__(self):
        return f"Finance Plan for App {self.credit_application.id} - {self.risk_tier}"
    
    def determine_risk_tier(self, tier_a_min_score = 600,tier_b_min_score = 550, tier_c_min_score = 500):
        """Determine risk tier based on APC score"""        
        if self.apc_score >= tier_a_min_score:
            self.risk_tier = 'TIER_A'
        elif self.apc_score >= tier_b_min_score:
            self.risk_tier = 'TIER_B'
        elif self.apc_score >= tier_c_min_score:
            self.risk_tier = 'TIER_C'
        else:
            self.risk_tier = 'TIER_D'
            
        return self.risk_tier
    
    def get_tier_rules(self):
        """Get financing rules based on risk tier"""
        tier_rules = {
            'TIER_A': {
                'min_down_payment': Decimal('20.00'),
                'allowed_terms': [4, 6, 8],
                'payment_capacity_factor': Decimal('0.30'),
                'high_end_extra': Decimal('0.00'),
            },
            'TIER_B': {
                'min_down_payment': Decimal('20.00'),
                'allowed_terms': [6, 8],
                'payment_capacity_factor': Decimal('0.20'),
                'high_end_extra': Decimal('5.00'),  # Extra 5% for high-end
            },
            'TIER_C': {
                'min_down_payment': Decimal('25.00'),
                'allowed_terms': [8],
                'payment_capacity_factor': Decimal('0.15'),
                'high_end_extra': Decimal('10.00'),  # Extra 10% for high-end
            },
            'TIER_D': {
                'min_down_payment': Decimal('100.00'),  # Reject
                'allowed_terms': [],
                'payment_capacity_factor': Decimal('0.00'),
                'high_end_extra': Decimal('0.00'),
            },
        }
        return tier_rules.get(self.risk_tier, tier_rules['TIER_D'])
    
    def calculate_minimum_down_payment(self):
        """Calculate minimum down payment based on tier and device type"""
        rules = self.get_tier_rules()
        min_percentage = rules['min_down_payment']
        
        # Add extra percentage for high-end devices in Tier B/C
        if self.is_high_end_device and self.risk_tier in ['TIER_B', 'TIER_C']:
            min_percentage += rules['high_end_extra']
        
        self.minimum_down_payment_percentage = min_percentage
        return (self.device_price * min_percentage) / Decimal('100')

    def calculate_emi(self):
        """
        Calculate EMI using:
        monthly payment = (amount_to_finance × multiple) / (term)
        Includes validation for all required fields.
        """
        if not self.selected_term:
            raise ValidationError("Selected term is missing for finance plan.")
        if not self.amount_to_finance or self.amount_to_finance <= 0:
            raise ValidationError("Amount to finance must be greater than zero.")
        if not self.installment_frequency_days:
            raise ValidationError("Installment frequency (interval days) is missing.")

        multiple = FinanceMultiple.objects.filter(
            term_months=self.selected_term,
            interval_days=self.installment_frequency_days,
            is_active=True
        ).values_list("multiple", flat=True).first()

        if not multiple:
            raise ValidationError(
                f"No FinanceMultiple configuration found for term {self.selected_term} months "
                f"and {self.installment_frequency_days} days."
            )

        try:
            emi = (self.amount_to_finance * Decimal(str(multiple))) / (Decimal(str(self.selected_term)))
            self.monthly_installment = emi.quantize(Decimal('1'), rounding=ROUND_UP)
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("Invalid EMI calculation. Please check your finance configuration.")

        return self.monthly_installment


    
    def check_payment_capacity(self):
        """
        Check if EMI is within payment capacity
        Rule: monthly_installment ≤ k × monthly_income
        """
        rules = self.get_tier_rules()
        self.payment_capacity_factor = rules['payment_capacity_factor']

        
        if self.risk_tier == 'TIER_D':
            self.maximum_allowed_installment = Decimal('0.00')
            self.installment_to_income_ratio = Decimal('0.00')
            self.payment_capacity_passed = False
            return False
        
        self.maximum_allowed_installment = (
            self.customer_monthly_income * self.payment_capacity_factor
        )
        

        if self.monthly_installment is not None and self.monthly_installment > 0:
            self.installment_to_income_ratio = (
                (self.monthly_installment / self.customer_monthly_income) * Decimal('100')
            )
        if self.monthly_installment is not None:
            self.payment_capacity_passed = (
                self.monthly_installment <= self.maximum_allowed_installment
            )
        else:
            self.payment_capacity_passed = False 
        return self.payment_capacity_passed
    
    def validate_conditions(self):
        """Validate all financing conditions"""
        rules = self.get_tier_rules()
        
        # Check 1: Down payment meets minimum
        min_down = self.calculate_minimum_down_payment()
        down_payment_ok = self.actual_down_payment >= min_down
        
        # Check 2: Term is allowed for this tier
        term_ok = self.selected_term in rules['allowed_terms']
        # Check 3: Payment capacity
        capacity_ok = self.check_payment_capacity()
        
        # Check 4: High-end device restrictions
        high_end_ok = True
        if self.is_high_end_device and self.risk_tier in ['TIER_B', 'TIER_C']:
            # Must meet higher down payment
            high_end_ok = down_payment_ok
        
        self.conditions_met = all([down_payment_ok, term_ok, capacity_ok, high_end_ok])
        
        if not self.conditions_met:
            self.requires_adjustment = True
            notes = []
            if not down_payment_ok:
                notes.append(f"Down payment must be ≥ {self.minimum_down_payment_percentage}%")
            if not term_ok:
                notes.append(f"Term must be one of: {rules['allowed_terms']} months")
            if not capacity_ok:
                notes.append(f"EMI exceeds {self.payment_capacity_factor * 100}% of income")
            if not high_end_ok:
                notes.append("High-end device requires higher down payment")
            self.adjustment_notes = "; ".join(notes)
        
        return self.conditions_met
    
    

    def calculate_final_score(self, biometric_confidence=0, references_score=0, geo_behavior=0):
        """
        Calculate weighted final score
        Formula: 0.30*apc_norm + 0.30*capacity_norm + 0.20*biometric + 0.10*references + 0.10*geo
        Fully debugged with prints for easy tracing.
        """

        # APC normalization (500-800 → 0-100)
        apc_norm = min(100, max(0, ((Decimal(self.apc_score) - 500) / 300) * 100))

        # Capacity normalization
        if self.maximum_allowed_installment > 0 and self.monthly_installment is not None:
            # Convert both to float for safe calculation
            max_installment_f = Decimal(self.maximum_allowed_installment)
            monthly_installment_f = Decimal(self.monthly_installment)

            capacity_norm = min(100, ((max_installment_f - monthly_installment_f) / max_installment_f * 100))

        else:
            capacity_norm = 0

        # Convert biometric, references, geo_behavior to float to be safe
        biometric_f = Decimal(biometric_confidence)
        references_f = Decimal(references_score)
        geo_f = Decimal(geo_behavior)
        
        # Calculate final score
        self.final_score = int(
            (Decimal('0.30') * apc_norm) +
            (Decimal('0.30') * capacity_norm) +
            (Decimal('0.20') * biometric_f) +
            (Decimal('0.10') * references_f) +
            (Decimal('0.10') * geo_f)
        )


        # Determine score status
        if self.final_score >= 80:
            self.score_status = 'APPROVED'
        elif self.final_score >= 60:
            self.score_status = 'CONDITIONAL'
        else:
            self.score_status = 'REJECTED'

        return self.final_score


    def calculate_device_price(self):
        """
        Automatically calculate device price from ProductModel including 7% ITBMS tax
        Formula: device_price = suggested_price + (suggested_price × 0.07)
        """
        if self.device:
            base_price = self.device.suggested_price
            tax = base_price * Decimal('0.07')
            self.device_price = base_price 
        return self.device_price

    def save(self, *args, **kwargs):
        # Auto-calculate fields before saving
        user = kwargs.pop('user', None)

        # --- Auto-assign created_by and store based on the user role ---
        if not self.pk and user:  # only when creating new record
            self.created_by = user

            if user.role in [user.SALESPERSON, user.STORE_MANAGER]:
                self.store = user.store
            else:
                self.store = None

        if self.device and not self.device_price:
            self.calculate_device_price()

        # if self.apc_score:
        #     self.determine_risk_tier()
        
        if self.device_price:
            self.is_high_end_device = self.device_price > Decimal('300.00')
        
        if self.actual_down_payment and self.device_price:
            self.down_payment_percentage = (
                (self.actual_down_payment / self.device_price) * Decimal('100')
            )
            self.amount_to_finance = self.device_price - self.actual_down_payment
        
        if self.selected_term and self.amount_to_finance:
            self.calculate_emi()
            self.total_amount_payable = (
                self.actual_down_payment + (self.monthly_installment * self.selected_term)
            )
        
        if self.customer_monthly_income:
            self.check_payment_capacity()
        
        # Set allowed terms
        rules = self.get_tier_rules()
        self.allowed_terms = rules['allowed_terms']
        
        super().save(*args, **kwargs)


# ========================================
# EMI SCHEDULE MODEL
# ========================================

class EMISchedule(models.Model):
    """
    Stores the complete EMI payment schedule for a finance plan.
    
    Business Rules:
    - One schedule entry per installment
    - Payment due date is set when schedule is created
    - Tracks payment status per installment
    """
    
    STATUS_CHOICES = [
        ('UPCOMING', 'Upcoming'),
        ('DUE', 'Due'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('PARTIALLY_PAID', 'Partially Paid'),
    ]
    
    finance_plan = models.ForeignKey(
        FinancePlan,
        on_delete=models.CASCADE,
        related_name='emi_schedule'
    )
    
    installment_number = models.IntegerField(
        help_text="Installment sequence number (1, 2, 3...)"
    )
    due_date = models.DateField(help_text="Payment due date")
    installment_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="EMI amount for this installment"
    )
    
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Amount paid towards this installment"
    )
    balance_remaining = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Remaining balance for this installment"
    )
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UPCOMING')
    paid_date = models.DateField(null=True, blank=True)
    days_overdue = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'emi_schedules'
        ordering = ['finance_plan', 'installment_number']
        unique_together = ['finance_plan', 'installment_number']
        indexes = [
            models.Index(fields=['finance_plan', 'installment_number']),
            models.Index(fields=['due_date']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"EMI {self.installment_number} for Finance Plan {self.finance_plan.id}"
    
    def update_status(self):
        """Update EMI status based on payment and date"""
        today = timezone.now().date()
        
        if self.amount_paid >= self.installment_amount:
            self.status = 'PAID'
            self.balance_remaining = Decimal('0.00')
        elif self.amount_paid > 0:
            self.status = 'PARTIALLY_PAID'
            self.balance_remaining = self.installment_amount - self.amount_paid
        elif today > self.due_date:
            self.status = 'OVERDUE'
            self.days_overdue = (today - self.due_date).days
            self.balance_remaining = self.installment_amount
        elif today == self.due_date:
            self.status = 'DUE'
            self.balance_remaining = self.installment_amount
        else:
            self.status = 'UPCOMING'
            self.balance_remaining = self.installment_amount
        
        return self.status
    
    @classmethod
    def generate_schedule_emi(cls, finance_plan, first_due_date):
        """
        Generate complete EMI schedule for a finance plan
        
        Args:
            finance_plan: FinancePlan instance
            first_due_date: Date for first EMI payment
        """
        schedules = []
        
        for i in range(1, finance_plan.selected_term + 1):
            due_date = first_due_date + relativedelta(months=i-1)
            
            schedule = cls(
                finance_plan=finance_plan,
                installment_number=i,
                due_date=due_date,
                installment_amount=finance_plan.monthly_installment,
                balance_remaining=finance_plan.monthly_installment
            )
            schedules.append(schedule)
        
        # Bulk create all schedules
        cls.objects.bulk_create(schedules)
        return schedules
    
    
    @classmethod
    def generate_schedule(cls, finance_plan, first_due_date):
        """
        Generate EMI schedule for any frequency (10, 15, 30 days).
        """
        schedules = []
        total_installments = finance_plan.selected_term
        emi_amount = finance_plan.monthly_installment
        frequency_days = finance_plan.installment_frequency_days or 30  # Default 30 days

        for i in range(1, total_installments + 1):
            due_date = first_due_date + timedelta(days=(i - 1) * frequency_days)
            schedules.append(
                cls(
                    finance_plan=finance_plan,
                    installment_number=i,
                    due_date=due_date,
                    installment_amount=emi_amount,
                    balance_remaining=emi_amount
                )
            )

        cls.objects.bulk_create(schedules)
        return schedules 


# ========================================
# UPDATED PAYMENT RECORD MODEL
# ========================================

class PaymentRecord(models.Model):
    """
    Tracks all payments made by customers with EMI linking.
    
    Payment Methods:
    - Punto Pago
    - Yappy
    - Western Union
    - Cash
    """
    
    PAYMENT_METHOD_CHOICES = [
        ('PUNTO_PAGO', 'Punto Pago'),
        ('YAPPY', 'Yappy'),
        ('WESTERN_UNION', 'Western Union'),
        ('CASH', 'Cash'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('OTHER', 'Other'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
        ('CANCELLED', 'Cancelled'),
        ('REVERSED', 'Reversed'),
    ]
    
    PAYMENT_TYPE_CHOICES = [
        ('DOWN_PAYMENT', 'Down Payment'),
        ('EMI', 'EMI Payment'),
        ('LATE_FEE', 'Late Fee'),
        ('FULL_SETTLEMENT', 'Full Settlement'),
    ]
    
    finance_plan = models.ForeignKey(
        FinancePlan,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    emi_schedule = models.ForeignKey(
        EMISchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        help_text="Link to specific EMI installment"
    )
    payment_received = models.ForeignKey(
        "PaymentReceived",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_records",
        help_text="Link to accounting PaymentReceived record"
    )
    
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField()
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='PENDING'
    )
    
    transaction_reference = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="External payment reference number"
    )
    receipt_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True
    )
    
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processed_payments'
    )
    
    notes = models.TextField(null=True, blank=True)
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional payment metadata"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payment_records'
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['finance_plan', '-payment_date']),
            models.Index(fields=['emi_schedule']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['payment_date']),
        ]
    
    def __str__(self):
        return f"Payment {self.payment_amount} - {self.payment_type} for Finance Plan {self.finance_plan.id}"
    
    def apply_to_emi(self):
        """Apply this payment to linked EMI schedule"""
        if self.emi_schedule and self.payment_status == 'COMPLETED':
            self.emi_schedule.amount_paid += self.payment_amount
            self.emi_schedule.update_status()
            
            if self.emi_schedule.status == 'PAID':
                self.emi_schedule.paid_date = self.payment_date.date()
            
            self.emi_schedule.save()


# ========================================
# BASIC FINANCE PLAN MODEL
# ========================================
class AutoFinancePlan(models.Model):
    """
    Temporary Finance Plan holding pre-calculated financial data
    before creating actual FinancePlan terms.
    """
    RISK_TIER_CHOICES = [
        ('TIER_A', 'Tier A - Low Risk (APC ≥ 600)'),
        ('TIER_B', 'Tier B - Medium Risk (APC 550-599)'),
        ('TIER_C', 'High Risk (APC 500-549)'),
        ('TIER_D', 'Very High Risk (APC < 500)'),
    ]
    customer = models.ForeignKey(
    Customer,
    on_delete=models.CASCADE,
    related_name='auto_finance_plans'
    )
    credit_application = models.ForeignKey(
        CreditApplication,
        on_delete=models.CASCADE,
        related_name='auto_finance_plan'
    )
    credit_score = models.ForeignKey(
        CreditScore,
        on_delete=models.SET_NULL,
        null=True,
        related_name='auto_finance_plans'
    )      
    # Risk Assessment
    apc_score = models.IntegerField(help_text="APC score from credit bureau")
    risk_tier = models.CharField(max_length=10, choices=RISK_TIER_CHOICES)
    
    # Payment Capacity Check
    customer_monthly_income = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Validated or declared monthly income"
    )
    payment_capacity_factor = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="k factor based on risk tier (0.10-0.30)"
    )
    maximum_allowed_installment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="k × monthly_income"
    )
    # Down Payment
    minimum_down_payment_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Minimum % required based on risk tier"
    )
       
    # Now stores EMI details for different terms & frequencies
    allowed_plans = models.JSONField(default=list, blank=True)
    
    high_end_extra_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    has_finance_plan = models.BooleanField(default=False)

    def __str__(self):
        return f"AutoFinancePlan - {self.customer.document_number if self.customer else 'N/A'}"
    
    def determine_risk_tier(self, tier_a_min_score = 600,tier_b_min_score = 550, tier_c_min_score = 500):
        """Determine risk tier based on APC score"""
        if self.apc_score >= tier_a_min_score:
            self.risk_tier = 'TIER_A'
        elif self.apc_score >= tier_b_min_score:
            self.risk_tier = 'TIER_B'
        elif self.apc_score >= tier_c_min_score:
            self.risk_tier = 'TIER_C'
        else:
            self.risk_tier = 'TIER_D'
        return self.risk_tier

    
    def get_tier_rules(self):
        """Get financing rules based on risk tier"""
        tier_rules = {
            'TIER_A': {
                'min_down_payment': Decimal('20.00'),
                'allowed_terms': [4, 6, 8],
                'payment_capacity_factor': Decimal('0.30'),
                'high_end_extra': Decimal('0.00'),
            },
            'TIER_B': {
                'min_down_payment': Decimal('20.00'),
                'allowed_terms': [6, 8],
                'payment_capacity_factor': Decimal('0.20'),
                'high_end_extra': Decimal('5.00'),  # Extra 5% for high-end
            },
            'TIER_C': {
                'min_down_payment': Decimal('25.00'),
                'allowed_terms': [8],
                'payment_capacity_factor': Decimal('0.15'),
                'high_end_extra': Decimal('10.00'),  # Extra 10% for high-end
            },
            'TIER_D': {
                'min_down_payment': Decimal('100.00'),  # Reject
                'allowed_terms': [],
                'payment_capacity_factor': Decimal('0.00'),
                'high_end_extra': Decimal('0.00'),
            },
        }
        return tier_rules.get(self.risk_tier, tier_rules['TIER_D'])


# ========================================
# MODEL FOR INTREST (MULTIPLE) DYNAMICALLY
# ========================================

class FinanceMultiple(models.Model):
    """
    Stores business-defined multiples for EMI calculation
    (used in FinancePlan calculations).
    Example: 4 months / 15 days -> 1.7, 6 months / 15 days -> 1.8, etc.
    """

    TERM_CHOICES = [
        (4, '4 Months'),
        (6, '6 Months'),
        (8, '8 Months'),
    ]

    INTERVAL_CHOICES = [
        (15, 'Every 15 Days'),
        (30, 'Every 30 Days'),
    ]

    term_months = models.PositiveIntegerField(choices=TERM_CHOICES)
    interval_days = models.PositiveIntegerField(choices=INTERVAL_CHOICES)
    multiple = models.DecimalField(max_digits=5, decimal_places=2)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_multiples"
        unique_together = ('term_months', 'interval_days')
        ordering = ['term_months', 'interval_days']

    def __str__(self):
        return f"{self.term_months} months / {self.interval_days} days → {self.multiple}"
    
    # --------- FOR GET MULTIPLE---------------
    
    def get_multiple(self, term_months, interval_days):
        """
        Returns the multiple for the given term and interval.
        Example:
            obj.get_multiple(4, 15) → Decimal('1.70')
        """
        try:
            record = FinanceMultiple.objects.get(
                term_months=term_months,
                interval_days=interval_days,
                is_active=True
            )
            return record.multiple
        except FinanceMultiple.DoesNotExist:
            return None


# ========================================
# ACCOUNTING MODELS (OLA CARS STYLE)
# ========================================

class AccountingCode(models.Model):
    """
    Accounting code representing accounts in Chart of Accounts
    """
    CATEGORY_CHOICES = [
        ('ASSET', 'Asset'),
        ('LIABILITY', 'Liability'),
        ('EQUITY', 'Equity'),
        ('REVENUE', 'Revenue'),
        ('EXPENSE', 'Expense'),
    ]

    code = models.CharField(max_length=20, unique=True, help_text="Unique account code (e.g. 1100)")
    name = models.CharField(max_length=100, help_text="Account name (e.g. Cash & Bank)")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounting_codes'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name} ({self.category})"

class Tax(models.Model):
    """
    Tax rate used in invoicing
    """
    name = models.CharField(max_length=50, unique=True)
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Tax percentage rate (e.g. 7.00 for 7%)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'taxes'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class BankAccount(models.Model):
    """
    Bank / Cash account linked to an accounting code
    """
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50, unique=True)
    account_holder_name = models.CharField(max_length=100)
    swift_code = models.CharField(max_length=20, blank=True, null=True)
    currency = models.CharField(max_length=10, default="USD")
    initial_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, default="ACTIVE")
    account_type = models.CharField(max_length=20, default="Bank") # Bank, Cash, Credit Card
    account_name = models.CharField(max_length=100)
    accounting_code = models.ForeignKey(AccountingCode, on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_accounts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bank_accounts'
        ordering = ['account_name']

    def __str__(self):
        return f"{self.account_name} - {self.bank_name} ({self.account_number})"


class Invoice(models.Model):
    """
    Customer invoice representing an installment bill or manual bill
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partial'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled'),
    ]

    INVOICE_TYPE_CHOICES = [
        ('PLAN', 'Financing Plan EMI'),
        ('MANUAL', 'Manual Invoice'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='invoices')
    finance_plan = models.ForeignKey(FinancePlan, on_delete=models.CASCADE, related_name='invoices', null=True, blank=True)
    emi_schedule = models.ForeignKey(EMISchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    due_date = models.DateField()
    base_amount = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPE_CHOICES, default='PLAN')
    line_items = models.JSONField(default=list, blank=True, help_text="Split items for manual invoices")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True, null=True, help_text="Internal notes or memo")
    generated_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'invoices'
        ordering = ['-due_date', '-id']

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.customer.first_name} {self.customer.last_name} ({self.status})"

    def generate_ledger_entries(self):
        """
        Generates double-entry ledger records for the invoice
        Debit Accounts Receivable (1200), Credit Sales/Rental Income (4100), Credit Tax Payable (2300)
        """
        # Find Accounting Codes
        ar_code = AccountingCode.objects.filter(code="1200").first()
        sales_code = AccountingCode.objects.filter(code="4100").first()
        tax_code = AccountingCode.objects.filter(code="2300").first()

        if not ar_code:
            return

        # Leg 1: Debit Accounts Receivable (Asset Increases)
        LedgerEntry.objects.create(
            invoice=self,
            accounting_code=ar_code,
            type='DEBIT',
            amount=self.total_amount,
            description=f"Invoice {self.invoice_number} generated for {self.customer.first_name} {self.customer.last_name}",
            entry_date=self.generated_at
        )

        if self.invoice_type == 'MANUAL' and self.line_items:
            for item in self.line_items:
                # Find custom account code if selected, fallback to standard sales account
                account_id = item.get('sales_account_id')
                custom_sales_code = None
                if account_id:
                    custom_sales_code = AccountingCode.objects.filter(id=account_id).first()
                if not custom_sales_code:
                    custom_sales_code = sales_code

                qty = Decimal(str(item.get('qty', 1)))
                unit_price = Decimal(str(item.get('unit_price', 0)))
                line_subtotal = qty * unit_price

                # Leg 2: Credit custom Sales account (Revenue Increases)
                if custom_sales_code and line_subtotal > 0:
                    LedgerEntry.objects.create(
                        invoice=self,
                        accounting_code=custom_sales_code,
                        type='CREDIT',
                        amount=line_subtotal,
                        description=f"Revenue recognized for {item.get('name', 'Line Item')} in manual invoice {self.invoice_number}",
                        entry_date=self.generated_at
                    )

                # Leg 3: Credit Tax Payable (Liability Increases)
                line_tax = Decimal(str(item.get('tax_amount', 0)))
                if line_tax > 0 and tax_code:
                    LedgerEntry.objects.create(
                        invoice=self,
                        accounting_code=tax_code,
                        type='CREDIT',
                        amount=line_tax,
                        description=f"Tax liability recorded for {item.get('name', 'Line Item')} in manual invoice {self.invoice_number}",
                        entry_date=self.generated_at
                    )
        else:
            # Leg 2: Credit Sales/Rental Income (Revenue Increases)
            if sales_code:
                LedgerEntry.objects.create(
                    invoice=self,
                    accounting_code=sales_code,
                    type='CREDIT',
                    amount=self.base_amount,
                    description=f"Revenue recognized for invoice {self.invoice_number}",
                    entry_date=self.generated_at
                )

            # Leg 3: Credit Tax Payable (Liability Increases)
            if self.tax_amount > 0 and tax_code:
                LedgerEntry.objects.create(
                    invoice=self,
                    accounting_code=tax_code,
                    type='CREDIT',
                    amount=self.tax_amount,
                    description=f"Tax liability recorded for invoice {self.invoice_number}",
                    entry_date=self.generated_at
                )


class PaymentReceived(models.Model):
    """
    Payment receipt representing money paid against one or more invoices
    """
    payment_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payments_received')
    amount_received = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=50, default='CASH')
    transaction_reference = models.CharField(max_length=100, null=True, blank=True)
    deposited_to = models.ForeignKey(AccountingCode, on_delete=models.PROTECT, related_name='deposits')
    invoices = models.JSONField(help_text="List of {invoice_id, amount_applied}")
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments_received'
        ordering = ['-payment_date']

    def __str__(self):
        return f"PaymentReceived {self.payment_number} - {self.amount_received} from {self.customer.first_name}"

    def process_payment(self, user=None):
        """
        Processes the payment:
        1. Updates Invoice balances & statuses
        2. Dispatches payment to financing EMI schedule logic (updates EMISchedule, creates PaymentRecord)
        3. Creates double-entry ledger entries: Debit Cash/Bank, Credit Accounts Receivable
        """
        from decimal import Decimal
        ar_code = AccountingCode.objects.filter(code="1200").first()
        
        # Leg 1: Debit Cash/Bank (Asset Increases)
        LedgerEntry.objects.create(
            payment_received=self,
            accounting_code=self.deposited_to,
            type='DEBIT',
            amount=self.amount_received,
            description=f"Payment received {self.payment_number} via {self.payment_method}. Ref: {self.transaction_reference or 'N/A'}",
            entry_date=self.payment_date
        )

        total_applied = Decimal('0.00')

        # Apply to invoices
        for item in self.invoices:
            inv_id = item.get('invoice_id')
            applied_amount = Decimal(str(item.get('amount_applied', 0)))
            if not inv_id or applied_amount <= 0:
                continue

            try:
                invoice = Invoice.objects.get(id=inv_id)
                invoice.amount_paid += applied_amount
                invoice.balance = invoice.total_amount - invoice.amount_paid
                if invoice.balance <= 0:
                    invoice.status = 'PAID'
                else:
                    invoice.status = 'PARTIAL'
                invoice.save()

                total_applied += applied_amount

                # Credit Accounts Receivable (Asset Decreases) for the applied amount
                if ar_code:
                    LedgerEntry.objects.create(
                        payment_received=self,
                        accounting_code=ar_code,
                        type='CREDIT',
                        amount=applied_amount,
                        description=f"AR cleared for invoice {invoice.invoice_number} via payment {self.payment_number}",
                        entry_date=self.payment_date
                    )

                # Dispatch to financing logic
                if invoice.emi_schedule:
                    # Create a standard PaymentRecord linking to this EMISchedule
                    payment_rec = PaymentRecord.objects.create(
                        finance_plan=invoice.finance_plan,
                        emi_schedule=invoice.emi_schedule,
                        payment_received=self,
                        payment_type='EMI',
                        payment_method=self.payment_method,
                        payment_amount=applied_amount,
                        payment_date=self.payment_date,
                        payment_status='COMPLETED',
                        transaction_reference=self.transaction_reference or self.payment_number,
                        receipt_number=self.payment_number,
                        processed_by=user,
                        notes=self.notes or f"Paid via Invoice Payment {self.payment_number}"
                    )
                    # Trigger the EMI schedule updates and financing logic (device lock/unlock etc.)
                    payment_rec.apply_to_emi()

            except Invoice.DoesNotExist:
                pass

        # Handle any excess amount as credit/advance received
        excess = self.amount_received - total_applied
        if excess > 0:
            advance_code = AccountingCode.objects.filter(code="2200").first()
            if advance_code:
                LedgerEntry.objects.create(
                    payment_received=self,
                    accounting_code=advance_code,
                    type='CREDIT',
                    amount=excess,
                    description=f"Excess payment recorded as Customer Advance under payment {self.payment_number}",
                    entry_date=self.payment_date
                )


class LedgerEntry(models.Model):
    """
    Double-entry ledger entries for all transactions
    """
    TYPE_CHOICES = [
        ('DEBIT', 'Debit'),
        ('CREDIT', 'Credit'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    payment_received = models.ForeignKey(PaymentReceived, on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    expense = models.ForeignKey('Expense', on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    bill = models.ForeignKey('Bill', on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    payment_made = models.ForeignKey('PaymentMade', on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    credit_note = models.ForeignKey('CreditNote', on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    journal_entry = models.ForeignKey('JournalEntry', on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    
    accounting_code = models.ForeignKey(AccountingCode, on_delete=models.PROTECT, related_name='ledger_entries')
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    entry_date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ledger_entries'
        ordering = ['-entry_date', '-id']

    def __str__(self):
        return f"{self.type} of {self.amount} on {self.accounting_code.code} ({self.entry_date})"


class Vendor(models.Model):
    name = models.CharField(max_length=100, unique=True)
    contact_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendors'
        ordering = ['name']

    def __str__(self):
        return self.name


class Expense(models.Model):
    expense_number = models.CharField(max_length=50, unique=True)
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=50, default='CASH')
    paid_from = models.ForeignKey(AccountingCode, on_delete=models.PROTECT, related_name='expense_payments_made')
    expense_category = models.ForeignKey(AccountingCode, on_delete=models.PROTECT, related_name='expense_categories')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expenses'
        ordering = ['-payment_date', '-id']

    def __str__(self):
        return f"Expense {self.expense_number} - {self.amount}"

    def generate_ledger_entries(self):
        import datetime
        date_val = self.payment_date
        if isinstance(date_val, str):
            date_val = datetime.datetime.strptime(date_val[:10], "%Y-%m-%d").date()
        elif isinstance(date_val, datetime.datetime):
            date_val = date_val.date()
        dt = timezone.make_aware(datetime.datetime.combine(date_val, datetime.time.min))
        
        # Debit: Expense Category (increases expense)
        LedgerEntry.objects.create(
            expense=self,
            accounting_code=self.expense_category,
            type='DEBIT',
            amount=self.amount,
            description=f"Expense recorded: {self.notes or 'N/A'}",
            entry_date=dt
        )
        # Credit: Cash/Bank (decreases asset)
        LedgerEntry.objects.create(
            expense=self,
            accounting_code=self.paid_from,
            type='CREDIT',
            amount=self.amount,
            description=f"Paid from {self.paid_from.name} for expense {self.expense_number}",
            entry_date=dt
        )


class Bill(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partial'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
    ]

    bill_number = models.CharField(max_length=50, unique=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='bills')
    bill_date = models.DateField()
    due_date = models.DateField()
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    notes = models.TextField(blank=True, null=True)
    line_items = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bills'
        ordering = ['-due_date', '-id']

    def __str__(self):
        return f"Bill {self.bill_number} - {self.vendor.name} ({self.status})"

    def generate_ledger_entries(self):
        import datetime
        ap_code = AccountingCode.objects.filter(code="2100").first() # Accounts Payable
        if not ap_code:
            return

        date_val = self.bill_date
        if isinstance(date_val, str):
            date_val = datetime.datetime.strptime(date_val[:10], "%Y-%m-%d").date()
        elif isinstance(date_val, datetime.datetime):
            date_val = date_val.date()
        dt = timezone.make_aware(datetime.datetime.combine(date_val, datetime.time.min))

        # Credit leg: Accounts Payable (Liability Increases)
        LedgerEntry.objects.create(
            bill=self,
            accounting_code=ap_code,
            type='CREDIT',
            amount=self.total_amount,
            description=f"Bill {self.bill_number} from vendor {self.vendor.name}",
            entry_date=dt
        )

        # Debit legs for each line item
        for item in self.line_items:
            qty = Decimal(str(item.get('qty', 1)))
            unit_price = Decimal(str(item.get('unit_price', 0)))
            line_subtotal = qty * unit_price
            
            # Find expense/asset GL code from item
            expense_code_id = item.get('expense_account_id')
            expense_code = None
            if expense_code_id:
                expense_code = AccountingCode.objects.filter(id=expense_code_id).first()
            
            if not expense_code:
                expense_code = AccountingCode.objects.filter(category="EXPENSE").first()

            if expense_code and line_subtotal > 0:
                LedgerEntry.objects.create(
                    bill=self,
                    accounting_code=expense_code,
                    type='DEBIT',
                    amount=line_subtotal,
                    description=f"Purchase expense recognized for {item.get('name', 'Line Item')} in bill {self.bill_number}",
                    entry_date=dt
                )

            # Tax tracking if tax is present
            line_tax = Decimal(str(item.get('tax_amount', 0)))
            tax_code = AccountingCode.objects.filter(code="2300").first() # Tax Payable
            if line_tax > 0 and tax_code:
                LedgerEntry.objects.create(
                    bill=self,
                    accounting_code=tax_code,
                    type='DEBIT',
                    amount=line_tax,
                    description=f"Tax recorded for {item.get('name', 'Line Item')} in bill {self.bill_number}",
                    entry_date=dt
                )


class PaymentMade(models.Model):
    payment_number = models.CharField(max_length=50, unique=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='payments_made')
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=50, default='CASH')
    paid_from = models.ForeignKey(AccountingCode, on_delete=models.PROTECT, related_name='payments_made_from')
    bills = models.JSONField(help_text="List of {bill_id, amount_applied}")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments_made'
        ordering = ['-payment_date', '-id']

    def __str__(self):
        return f"PaymentMade {self.payment_number} - {self.amount_paid} to {self.vendor.name}"

    def process_payment(self):
        import datetime
        ap_code = AccountingCode.objects.filter(code="2100").first() # Accounts Payable
        date_val = self.payment_date
        if isinstance(date_val, str):
            date_val = datetime.datetime.strptime(date_val[:10], "%Y-%m-%d").date()
        elif isinstance(date_val, datetime.datetime):
            date_val = date_val.date()
        dt = timezone.make_aware(datetime.datetime.combine(date_val, datetime.time.min))

        # Credit leg: Bank/Cash (Asset Decreases)
        LedgerEntry.objects.create(
            payment_made=self,
            accounting_code=self.paid_from,
            type='CREDIT',
            amount=self.amount_paid,
            description=f"Payment {self.payment_number} made to vendor {self.vendor.name}",
            entry_date=dt
        )

        total_applied = Decimal('0.00')

        for item in self.bills:
            bill_id = item.get('bill_id')
            applied_amount = Decimal(str(item.get('amount_applied', 0)))
            if not bill_id or applied_amount <= 0:
                continue

            try:
                bill = Bill.objects.get(id=bill_id)
                bill.amount_paid += applied_amount
                bill.balance = bill.total_amount - bill.amount_paid
                if bill.balance <= 0:
                    bill.status = 'PAID'
                else:
                    bill.status = 'PARTIAL'
                bill.save()

                total_applied += applied_amount

                # Debit leg: Accounts Payable (Liability Decreases)
                if ap_code:
                    LedgerEntry.objects.create(
                        payment_made=self,
                        accounting_code=ap_code,
                        type='DEBIT',
                        amount=applied_amount,
                        description=f"Accounts Payable cleared for bill {bill.bill_number} via payment {self.payment_number}",
                        entry_date=dt
                    )

            except Bill.DoesNotExist:
                pass


class CreditNote(models.Model):
    STATUS_CHOICES = [
        ('UNAPPLIED', 'Unapplied'),
        ('APPLIED', 'Applied'),
        ('VOID', 'Void'),
    ]

    credit_note_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='credit_notes')
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNAPPLIED')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'credit_notes'
        ordering = ['-date', '-id']

    def __str__(self):
        return f"Credit Note {self.credit_note_number} - {self.amount}"

    def generate_ledger_entries(self):
        import datetime
        ar_code = AccountingCode.objects.filter(code="1200").first() # Accounts Receivable
        sales_code = AccountingCode.objects.filter(code="4100").first() # Sales
        date_val = self.date
        if isinstance(date_val, str):
            date_val = datetime.datetime.strptime(date_val[:10], "%Y-%m-%d").date()
        elif isinstance(date_val, datetime.datetime):
            date_val = date_val.date()
        dt = timezone.make_aware(datetime.datetime.combine(date_val, datetime.time.min))

        if ar_code:
            # Credit leg: Accounts Receivable (Asset Decreases)
            LedgerEntry.objects.create(
                credit_note=self,
                accounting_code=ar_code,
                type='CREDIT',
                amount=self.amount,
                description=f"Credit note {self.credit_note_number} issued to customer {self.customer.first_name} {self.customer.last_name}",
                entry_date=dt
            )

        if sales_code:
            # Debit leg: Sales Revenue (Revenue Decreases)
            LedgerEntry.objects.create(
                credit_note=self,
                accounting_code=sales_code,
                type='DEBIT',
                amount=self.amount,
                description=f"Revenue reversal via credit note {self.credit_note_number}",
                entry_date=dt
            )


class JournalEntry(models.Model):
    reference_number = models.CharField(max_length=50, unique=True)
    entry_date = models.DateField()
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'journal_entries'
        ordering = ['-entry_date', '-id']

    def __str__(self):
        return f"Journal Entry {self.reference_number} ({self.entry_date})"



from django.db import models 
from django.contrib.auth import get_user_model
from datetime import timedelta
from customer.models import CreditApplication, Customer

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
    
    def determine_risk_tier(self):
        """Determine risk tier based on APC score"""
        if self.apc_score >= 600:
            self.risk_tier = 'TIER_A'
        elif self.apc_score >= 550:
            self.risk_tier = 'TIER_B'
        elif self.apc_score >= 500:
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
        Calculate EMI (Interest-Free)
        Formula: EMI = amount_to_finance / term
        Rounded to whole number (no cents)
        """
        if self.selected_term and self.amount_to_finance:
            raw_emi = self.amount_to_finance / Decimal(str(self.selected_term))
            self.monthly_installment = raw_emi.quantize(Decimal('1'), rounding='ROUND_UP')
        else:
            self.monthly_installment = Decimal('0') 
        return self.monthly_installment

    
    def check_payment_capacity(self):
        """
        Check if EMI is within payment capacity
        Rule: monthly_installment ≤ k × monthly_income
        """

        rules = self.get_tier_rules()
        self.payment_capacity_factor = rules['payment_capacity_factor']
        
        if self.risk_tier == 'TIER_D':
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




    def save(self, *args, **kwargs):
        # Auto-calculate fields before saving
        if self.apc_score:
            self.determine_risk_tier()
        
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
        Generate EMI schedule — supports 15-day (biweekly) payments.
        """
        schedules = []

        for i in range(1, finance_plan.selected_term + 1):
            due_date = first_due_date + timedelta(days=(i - 1) * 15)
            schedule = cls(
                finance_plan=finance_plan,
                installment_number=i,
                due_date=due_date,
                installment_amount=finance_plan.monthly_installment,
                balance_remaining=finance_plan.monthly_installment
            )
            schedules.append(schedule)

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
    credit_application = models.OneToOneField(
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

    def __str__(self):
        return f"AutoFinancePlan - {self.customer.document_number if self.customer else 'N/A'}"

    def determine_risk_tier(self):
        """Determine risk tier based on APC score"""
        if self.apc_score >= 600:
            self.risk_tier = 'TIER_A'
        elif self.apc_score >= 550:
            self.risk_tier = 'TIER_B'
        elif self.apc_score >= 500:
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

"""
Django Models for Ola Credits - Customer Verification & Credit Scoring System

This module contains all Django models for managing the customer verification
and credit scoring workflow for Ola Credits sales process.

Key Features:
- Customer management with document verification
- Biometric validation via MetaMap integration
- Credit score tracking (APC/Experian + Internal scoring)
- Credit application workflow (valid for 2 days)
- Credit score caching (valid for 30 days)
- Decision engine for loan approval
- Device enrollment and tracking
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
# from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()
# ========================================
# CUSTOMER MODEL
# ========================================

class Customer(models.Model):
    """
    Core customer model storing basic customer information.
    
    Business Rules:
    - Document number must be unique
    - Customer can have multiple credit applications
    - Each customer can only have one active identity verification
    """
    
    DOCUMENT_TYPE_CHOICES = [
        ('PANAMA_ID', 'Panamanian ID Card'),
        ('PASSPORT', 'Passport'),
        ('FOREIGNER_ID', 'Foreigner ID Card'),
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('BLOCKED', 'Blocked'),
    ]
    
    
    document_number = models.CharField(
        max_length=50, 
        unique=True,
        help_text="ID card with hyphens (e.g., 8-123-456) or passport number"
    )
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Salesperson who created this customer
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='customers_created'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'customers'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document_number']),
            models.Index(fields=['email']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.document_number})"
    
    def get_latest_credit_score(self):
        """Get the most recent credit score that is still valid (within 30 days)"""
        return self.credit_scores.filter(
            score_valid_until__gte=timezone.now()
        ).order_by('-created_at').first()
    
    def needs_credit_score_check(self):
        """Check if customer needs a new credit score (older than 30 days)"""
        latest_score = self.get_latest_credit_score()
        return latest_score is None or latest_score.is_expired


# ========================================
# IDENTITY VERIFICATION MODEL
# ========================================

class IdentityVerification(models.Model):
    """
    Manages customer identity verification process including:
    - Document upload
    - Biometric validation via MetaMap
    - Phone and email verification
    
    Business Rules:
    - One active verification per customer
    - Verification link expires after 24 hours
    - All steps must be completed for approval
    """
    
    BIOMETRIC_STATUS_CHOICES = [
        ('NOT_STARTED', 'Not Started'),
        ('QR_GENERATED', 'QR Code Generated'),
        ('SMS_SENT', 'SMS Sent'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    VERIFICATION_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired'),
    ]
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.OneToOneField(
        Customer, 
        on_delete=models.CASCADE,
        related_name='identity_verification'
    )
    
    # Document Upload
    document_front_image = models.ImageField(
        upload_to='documents/front/',
        help_text="Front side of ID/Passport"
    )
    document_back_image = models.ImageField(
        upload_to='documents/back/',
        null=True,
        blank=True,
        help_text="Back side of ID (if applicable)"
    )
    document_uploaded_at = models.DateTimeField(auto_now_add=True)
    
    # Biometric Validation (MetaMap Integration)
    biometric_status = models.CharField(
        max_length=20,
        choices=BIOMETRIC_STATUS_CHOICES,
        default='NOT_STARTED'
    )
    metamap_verification_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Reference ID from MetaMap API"
    )
    selfie_image = models.ImageField(
        upload_to='biometrics/selfies/',
        null=True,
        blank=True
    )
    liveness_check_passed = models.BooleanField(default=False)
    face_match_score = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Face matching confidence score (0-100)"
    )
    biometric_verified_at = models.DateTimeField(null=True, blank=True)
    
    # Contact Verification
    phone_verification_code = models.CharField(max_length=6, null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    email_verification_code = models.CharField(max_length=6, null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    
    # QR Code / Link for customer self-verification
    verification_qr_code = models.TextField(
        null=True,
        blank=True,
        help_text="Base64 encoded QR code image"
    )
    verification_link = models.URLField(
        null=True,
        blank=True,
        help_text="Unique link for customer to complete verification"
    )
    verification_link_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Overall Status
    overall_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='PENDING'
    )
    verification_completed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'identity_verifications'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Verification for {self.customer.document_number} - {self.overall_status}"
    
    def is_link_expired(self):
        """Check if verification link has expired"""
        if self.verification_link_expires_at:
            return timezone.now() > self.verification_link_expires_at
        return False
    
    def is_fully_verified(self):
        """Check if all verification steps are completed"""
        return (
            self.phone_verified_at is not None and
            self.email_verified_at is not None and
            self.liveness_check_passed and
            self.biometric_status == 'COMPLETED' and
            self.overall_status == 'VERIFIED'
        )


# ========================================
# CREDIT SCORE MODEL
# ========================================

class CreditScore(models.Model):
    """
    Stores customer credit scores from multiple sources.
    
    Business Rules:
    - Credit score is valid for 30 days (1 month)
    - If customer returns within 30 days, use cached score from DB
    - If older than 30 days, fetch new score from APC/Experian
    - APC Score ≥500 = Approved, <499 = Rejected
    - Installment must be ≤30% of income
    """
    
    APC_STATUS_CHOICES = [
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('PENDING', 'Pending'),
    ]
    
    PAYMENT_CAPACITY_CHOICES = [
        ('SUFFICIENT', 'Sufficient'),
        ('INSUFFICIENT', 'Insufficient'),
    ]
    
    CREDIT_STATUS_CHOICES = [
        ('PRE_QUALIFIED', 'Pre-Qualified'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('PENDING_APPROVAL', 'Pending Approval'),
    ]
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='credit_scores'
    )
    
    # APC Score (Experian API Integration)
    apc_score = models.IntegerField(
        null=True,
        blank=True,
        help_text="Credit bureau score from Experian"
    )
    apc_score_date = models.DateTimeField(default=timezone.now)
    apc_consultation_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Reference ID from Experian API call"
    )
    apc_status = models.CharField(
        max_length=20,
        choices=APC_STATUS_CHOICES,
        default='PENDING'
    )
    
    # Internal Score (Ola Cell Payment History)
    internal_score = models.IntegerField(
        null=True,
        blank=True,
        help_text="Internal scoring based on payment history with Ola"
    )
    good_payment_history_points = models.IntegerField(default=0)
    delinquency_penalty_points = models.IntegerField(default=0)
    number_of_previous_loans = models.IntegerField(default=0)
    
    # Payment Capacity (CSS Base)
    declared_income = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Income declared by customer"
    )
    validated_income = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Income validated through CSS base"
    )
    monthly_expenses = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    max_installment_capacity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum monthly installment (30% of income)"
    )
    payment_capacity_status = models.CharField(
        max_length=20,
        choices=PAYMENT_CAPACITY_CHOICES,
        default='SUFFICIENT'
    )
    
    # Combined Decision
    final_credit_status = models.CharField(
        max_length=20,
        choices=CREDIT_STATUS_CHOICES,
        default='PENDING_APPROVAL'
    )
    credit_limit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum credit amount approved"
    )
    
    # Validity and Authorization
    score_valid_until = models.DateTimeField(
        help_text="Score is valid for 30 days from creation"
    )
    is_expired = models.BooleanField(default=False)
    verbal_authorization_given = models.BooleanField(
        default=False,
        help_text="Customer gave verbal consent to check APC"
    )
    
    # Tracking
    consulted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='credit_scores_consulted'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'credit_scores'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['score_valid_until']),
            models.Index(fields=['apc_status']),
        ]
    
    def __str__(self):
        return f"Credit Score for {self.customer.document_number} - {self.final_credit_status}"
    
    def save(self, *args, **kwargs):
        # Set score validity for 30 days if not set
        if not self.score_valid_until:
            self.score_valid_until = timezone.now() + timedelta(days=30)
        
        # Check if score is expired
        self.is_expired = timezone.now() > self.score_valid_until
        
        # Calculate max installment capacity (30% of income)
        if self.validated_income or self.declared_income:
            income = self.validated_income or self.declared_income
            self.max_installment_capacity = income * 0.30
        
        super().save(*args, **kwargs)
    
    def check_apc_approval(self):
        """Check if APC score meets approval criteria (≥500)"""
        if self.apc_score is not None:
            return self.apc_score >= 500
        return False


# ========================================
# PERSONAL REFERENCE MODEL
# ========================================

class PersonalReference(models.Model):
    """
    Stores personal references for customers.
    
    Business Rules:
    - Minimum 2 valid references required
    - References cannot have duplicate phone numbers
    """
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='personal_references'
    )
    
    full_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20)
    relationship = models.CharField(
        max_length=100,
        help_text="Relationship to customer (e.g., friend, family, colleague)"
    )
    is_valid = models.BooleanField(default=True)
    validation_notes = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'personal_references'
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.full_name} - Reference for {self.customer.document_number}"


# ========================================
# CREDIT APPLICATION MODEL
# ========================================

class CreditApplication(models.Model):
    """
    Manages the entire credit application workflow.
    
    Business Rules:
    - Application is valid for 2 days to complete
    - Only the salesperson who created it can continue the application
    - One application can contain one device purchase
    """
    
    STATUS_CHOICES = [
        ('PRE_QUALIFIED', 'Pre-Qualified'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('PENDING_APPROVAL', 'Pending Approval'),
        ('EXPIRED', 'Expired'),
    ]
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='credit_applications'
    )
    sales_person = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='credit_applications'
    )
    
    # Application Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING_APPROVAL'
    )
    application_date = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        help_text="Application expires 2 days after creation"
    )
    
    # Pre-qualification
    pre_qualification_passed = models.BooleanField(default=False)
    pre_qualification_date = models.DateTimeField(null=True, blank=True)
    
    # Device Selection
    device_brand = models.CharField(max_length=100, null=True, blank=True)
    device_model = models.CharField(max_length=100, null=True, blank=True)
    device_reference = models.CharField(max_length=100, null=True, blank=True)
    device_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price with 7% tax included"
    )
    device_imei = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        unique=True,
        help_text="Device IMEI number"
    )
    
    # Financing Details
    initial_payment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    amount_to_finance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    number_of_installments = models.IntegerField(null=True, blank=True)
    installment_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Rounded amount, no cents"
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'credit_applications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['sales_person']),
            models.Index(fields=['status']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Application {self.id} - {self.customer.document_number} - {self.status}"
    
    def save(self, *args, **kwargs):
        # Set expiration date (2 days from creation)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=2)
        
        # Calculate amount to finance
        if self.device_price and self.initial_payment:
            self.amount_to_finance = self.device_price - self.initial_payment
        
        super().save(*args, **kwargs)
    
    def is_expired(self):
        """Check if application has expired (older than 2 days)"""
        return timezone.now() > self.expires_at
    
    def can_be_continued_by(self, user):
        """Check if user can continue this application"""
        return self.sales_person == user and not self.is_expired()


# ========================================
# DECISION ENGINE RESULT MODEL
# ========================================

class DecisionEngineResult(models.Model):
    """
    Stores the comprehensive decision engine evaluation results.
    
    The decision engine evaluates 7 key factors:
    1. APC Score (≥500 required)
    2. Internal Score (payment history with Ola)
    3. Identity Validation (MetaMap biometrics)
    4. Payment Capacity (≤30% of income)
    5. Personal References (2 valid required)
    6. Anti-fraud Rules
    7. Commercial Conditions
    """
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit_application = models.OneToOneField(
        CreditApplication,
        on_delete=models.CASCADE,
        related_name='decision_engine_result'
    )
    
    # 1. APC Score Check
    apc_score_value = models.IntegerField()
    apc_score_passed = models.BooleanField(default=False)
    apc_score_weight = models.IntegerField(default=30)
    
    # 2. Internal Score Check
    internal_score_value = models.IntegerField(null=True, blank=True)
    internal_score_passed = models.BooleanField(default=False)
    internal_score_weight = models.IntegerField(default=20)
    
    # 3. Identity Validation (MetaMap)
    document_valid = models.BooleanField(default=False)
    biometric_valid = models.BooleanField(default=False)
    liveness_check_passed = models.BooleanField(default=False)
    identity_validation_passed = models.BooleanField(default=False)
    identity_validation_weight = models.IntegerField(default=15)
    
    # 4. Payment Capacity
    income_amount = models.DecimalField(max_digits=10, decimal_places=2)
    installment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    installment_to_income_ratio = models.DecimalField(max_digits=5, decimal_places=2)
    payment_capacity_passed = models.BooleanField(default=False)
    payment_capacity_weight = models.IntegerField(default=15)
    
    # 5. Personal References
    valid_references_count = models.IntegerField(default=0)
    references_passed = models.BooleanField(default=False)
    references_weight = models.IntegerField(default=10)
    
    # 6. Anti-fraud Checks
    duplicate_id_check = models.BooleanField(default=True)
    duplicate_phone_check = models.BooleanField(default=True)
    duplicate_imei_check = models.BooleanField(default=True)
    anti_fraud_passed = models.BooleanField(default=False)
    anti_fraud_weight = models.IntegerField(default=10)
    anti_fraud_notes = models.TextField(null=True, blank=True)
    
    # 7. Commercial Conditions
    initial_payment_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    loan_term_months = models.IntegerField()
    is_high_end_device = models.BooleanField(default=False)
    commercial_conditions_passed = models.BooleanField(default=False)
    commercial_conditions_weight = models.IntegerField(default=10)
    
    # Final Decision
    total_score = models.IntegerField(help_text="Weighted total of all factors")
    final_decision = models.CharField(
        max_length=20,
        choices=[
            ('APPROVED', 'Approved'),
            ('REJECTED', 'Rejected'),
            ('MANUAL_REVIEW', 'Manual Review Required'),
        ]
    )
    rejection_reasons = models.JSONField(
        null=True,
        blank=True,
        help_text="List of reasons for rejection"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'decision_engine_results'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Decision for App {self.credit_application.id} - {self.final_decision}"
    
    def calculate_total_score(self):
        """Calculate weighted total score"""
        score = 0
        
        if self.apc_score_passed:
            score += self.apc_score_weight
        if self.internal_score_passed:
            score += self.internal_score_weight
        if self.identity_validation_passed:
            score += self.identity_validation_weight
        if self.payment_capacity_passed:
            score += self.payment_capacity_weight
        if self.references_passed:
            score += self.references_weight
        if self.anti_fraud_passed:
            score += self.anti_fraud_weight
        if self.commercial_conditions_passed:
            score += self.commercial_conditions_weight
        
        self.total_score = score
        return score


# ========================================
# DEVICE ENROLLMENT MODEL
# ========================================

class DeviceEnrollment(models.Model):
    """
    Manages device enrollment and locking system integration.
    
    Integrations:
    - Samsung KNOX for Samsung devices
    - NuovoPay for other Android devices
    """
    
    ENROLLMENT_STATUS_CHOICES = [
        ('NOT_STARTED', 'Not Started'),
        ('QR_GENERATED', 'QR Code Generated'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    LOCKING_SYSTEM_CHOICES = [
        ('KNOX', 'Samsung KNOX'),
        ('NUOVOPAY', 'NuovoPay'),
        ('NONE', 'None'),
    ]
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit_application = models.OneToOneField(
        CreditApplication,
        on_delete=models.CASCADE,
        related_name='device_enrollment'
    )
    
    # Device Information
    imei = models.CharField(max_length=20, unique=True)
    device_brand = models.CharField(max_length=100)
    device_model = models.CharField(max_length=100)
    
    # Enrollment Process
    enrollment_status = models.CharField(
        max_length=20,
        choices=ENROLLMENT_STATUS_CHOICES,
        default='NOT_STARTED'
    )
    enrollment_qr_code = models.TextField(
        null=True,
        blank=True,
        help_text="QR code for device enrollment"
    )
    enrollment_link = models.URLField(null=True, blank=True)
    
    # Locking System Integration
    locking_system = models.CharField(
        max_length=20,
        choices=LOCKING_SYSTEM_CHOICES,
        default='NONE'
    )
    locking_system_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Reference ID from KNOX or NuovoPay"
    )
    is_locked = models.BooleanField(default=False)
    lock_applied_at = models.DateTimeField(null=True, blank=True)
    
    # Verification
    imei_verified = models.BooleanField(default=False)
    device_has_internet = models.BooleanField(
        default=False,
        help_text="Device must have internet to complete enrollment"
    )
    
    enrollment_completed_at = models.DateTimeField(null=True, blank=True)
    enrollment_failed_reason = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'device_enrollments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['imei']),
            models.Index(fields=['enrollment_status']),
        ]
    
    def __str__(self):
        return f"Enrollment for IMEI {self.imei} - {self.enrollment_status}"
    
    def determine_locking_system(self):
        """Determine which locking system to use based on device brand"""
        if 'samsung' in self.device_brand.lower():
            self.locking_system = 'KNOX'
        else:
            self.locking_system = 'NUOVOPAY'
        return self.locking_system


# ========================================
# PAYMENT RECORD MODEL
# ========================================

class PaymentRecord(models.Model):
    """
    Tracks all payments made by customers.
    
    Payment Methods:
    - Punto Pago
    - Yappy
    - Western Union
    """
    
    PAYMENT_METHOD_CHOICES = [
        ('PUNTO_PAGO', 'Punto Pago'),
        ('YAPPY', 'Yappy'),
        ('WESTERN_UNION', 'Western Union'),
        ('CASH', 'Cash'),
        ('OTHER', 'Other'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    
   # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit_application = models.ForeignKey(
        CreditApplication,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    
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
    
    is_initial_payment = models.BooleanField(
        default=False,
        help_text="True if this is the initial/down payment"
    )
    installment_number = models.IntegerField(
        null=True,
        blank=True,
        help_text="Which installment number this payment covers"
    )
    
    notes = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payment_records'
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['credit_application', '-payment_date']),
            models.Index(fields=['payment_status']),
        ]
    
    def __str__(self):
        return f"Payment {self.payment_amount} for App {self.credit_application.id}"


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
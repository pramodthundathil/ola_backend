from django.contrib import admin
from .models import (
    AuditLog, FinancePlan, EMISchedule, PaymentRecord, AutoFinancePlan,
    RiskTier, LoanTerm, InterestPlan, EmployerRule, ApprovalRule,
    DecisionRule, ReferenceRule, EMIConfiguration
)

@admin.register(RiskTier)
class RiskTierAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'min_score', 'max_score', 'min_salary', 'max_debt_ratio_pct', 'min_down_payment_pct', 'approval_level', 'is_active')
    list_filter = ('approval_level', 'is_active')
    search_fields = ('code', 'name')

@admin.register(LoanTerm)
class LoanTermAdmin(admin.ModelAdmin):
    list_display = ('months', 'fortnights', 'multiplier', 'is_active')
    list_filter = ('is_active',)

@admin.register(InterestPlan)
class InterestPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'loan_term', 'interest_rate_pct', 'processing_fee', 'insurance_fee', 'risk_multiplier', 'is_active')
    list_filter = ('loan_term', 'is_active')
    search_fields = ('name',)

@admin.register(EmployerRule)
class EmployerRuleAdmin(admin.ModelAdmin):
    list_display = ('employer_name', 'min_employment_duration_months', 'is_blacklisted', 'max_loan_multiplier', 'is_active')
    list_filter = ('is_blacklisted', 'is_active')
    search_fields = ('employer_name',)

@admin.register(ApprovalRule)
class ApprovalRuleAdmin(admin.ModelAdmin):
    list_display = ('risk_tier', 'min_down_payment_pct', 'max_loan_amount', 'is_active')
    list_filter = ('is_active',)

@admin.register(DecisionRule)
class DecisionRuleAdmin(admin.ModelAdmin):
    list_display = ('rule_key', 'description', 'value', 'is_mandatory', 'is_active')
    list_filter = ('is_mandatory', 'is_active')
    search_fields = ('rule_key', 'description')

@admin.register(ReferenceRule)
class ReferenceRuleAdmin(admin.ModelAdmin):
    list_display = ('min_references', 'require_verification', 'is_active')

@admin.register(EMIConfiguration)
class EMIConfigurationAdmin(admin.ModelAdmin):
    list_display = ('method', 'processing_fee_default', 'insurance_fee_default', 'tax_rate_pct', 'is_active')

@admin.register(FinancePlan)
class FinancePlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'credit_application', 'risk_tier', 'device', 'device_price', 'total_price', 'actual_down_payment', 'selected_term', 'score_status', 'created_at')
    list_filter = ('risk_tier', 'score_status')
    search_fields = ('credit_application__customer__document_number', 'device__model_name')

@admin.register(EMISchedule)
class EMIScheduleAdmin(admin.ModelAdmin):
    list_display = ('id', 'installment_number', 'due_date', 'principal', 'interest', 'insurance', 'fees', 'balance', 'status')
    list_filter = ('status',)

admin.site.register(AuditLog)
admin.site.register(AutoFinancePlan)
admin.site.register(PaymentRecord)

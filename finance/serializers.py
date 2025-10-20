# ========================================
# STANDARD LIBRARY IMPORTS
# ========================================
from datetime import date

# ========================================
# DJANGO / THIRD-PARTY IMPORTS
# ========================================
from rest_framework import serializers

# ========================================
# LOCAL APP IMPORTS
# ========================================
from .models import FinancePlan, EMISchedule, PaymentRecord

# ========================================
# FINANCE PLAN SERIALIZER
# ========================================
class FinancePlanSerializer(serializers.ModelSerializer):
    """
    Serializer for FinancePlan model.
    
    - Includes all fields from the model.
    - Certain fields are read-only because they are calculated automatically:
      risk_tier, monthly_installment, total_amount_payable, conditions_met, 
      requires_adjustment, adjustment_notes, final_score, score_status, allowed_terms.
    - Automatically generates EMI schedule upon creation.
    """
    class Meta:
        model = FinancePlan
        fields = '__all__'
        read_only_fields = [
            'risk_tier',
            'monthly_installment',
            'total_amount_payable',
            'conditions_met',
            'requires_adjustment',
            'adjustment_notes',
            'final_score',
            'score_status',
            'allowed_terms'
        ]

    def create(self, validated_data):
        """
        Override create to:
        1. Save the finance plan instance.
        2. Generate the full EMI schedule starting from today's date.
        """
        finance_plan = FinancePlan.objects.create(**validated_data)
        
        # Generate EMI schedule
        first_due_date = date.today()  # Can be replaced with business logic
        EMISchedule.generate_schedule(finance_plan, first_due_date)        
        return finance_plan


# ========================================
# EMI SCHEDULE SERIALIZER
# ========================================
class EMIScheduleSerializer(serializers.ModelSerializer):
    """
    Serializer for EMISchedule model.
    
    - Includes all fields.
    - Used for viewing or managing individual EMI installments.
    """
    class Meta:
        model = EMISchedule
        fields = '__all__'


# ========================================
# PAYMENT RECORD SERIALIZER
# ========================================
class PaymentRecordSerializer(serializers.ModelSerializer): 
    class Meta: 
        model = PaymentRecord 
        fields = '__all__'


# ========================================
# FINANCE PLANS ANALYTICS OVERVIEW SERIALIZER
# ========================================
class FinanceOverviewSerializer(serializers.Serializer):
    """
    Serializer for Finance Analytics Overview.
    
    Returns dashboard-style summary of all finance plans:
    - Total plans, total customers, approved/rejected counts
    - Total financed amount, average EMI, average APC score
    - Risk tier distribution
    """
    total_finance_plans = serializers.IntegerField()
    total_customers = serializers.IntegerField()
    total_approved = serializers.IntegerField()
    total_rejected = serializers.IntegerField()
    total_amount_financed = serializers.FloatField()
    average_installment = serializers.FloatField()
    avg_apc_score = serializers.FloatField()
    avg_risk_tier = serializers.DictField(child=serializers.IntegerField())


# ========================================
# FINANCE RISK TIER ANALYTICS SERIALIZER
# ========================================
class FinanceRiskTierSerializer(serializers.Serializer):
    """
    Serializer for Risk Tier analytics.
    Returns aggregated data grouped by each risk tier.
    """
    risk_tier = serializers.CharField()
    total_customers = serializers.IntegerField()
    total_finance_plans = serializers.IntegerField()
    total_amount_financed = serializers.FloatField()
    average_installment = serializers.FloatField()


# ========================================
# FINANCE Collection SERIALIZER
# ========================================
class FinanceCollectionSerializer(serializers.Serializer):
    """
    Serializer for finance collections summary.
    """
    total_installments = serializers.IntegerField()
    total_collected = serializers.FloatField()
    total_pending = serializers.FloatField()
    collection_rate = serializers.FloatField()


# ========================================
# FINANCE INSTALLMENT OVERDUE SERIALIZER
# ========================================
class FinanceOverdueSerializer(serializers.Serializer):
    """
    Analytics for overdue EMIs
    """
    total_overdue_installments = serializers.IntegerField()
    total_overdue_amount = serializers.FloatField()
    customers_with_overdue = serializers.IntegerField()

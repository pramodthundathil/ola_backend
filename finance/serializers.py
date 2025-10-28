from datetime import date
from rest_framework import serializers
from .models import FinancePlan, EMISchedule, PaymentRecord, AutoFinancePlan


# --------------------------------------------------------
# Finance Plan Create from AutoFinancePlan Serializer
# --------------------------------------------------------
class FinancePlanCreateSerializer(serializers.Serializer):
    temp_plan_id = serializers.IntegerField()
    device_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    actual_down_payment = serializers.DecimalField(max_digits=10, decimal_places=2)
    choosed_allowed_plans = serializers.DictField(
        child=serializers.IntegerField(),
        help_text='Example: {"selected_term": 6, "installment_frequency_days": 30}'
    )


# --------------------------------------------------------
# Finance Plan Create from AutoFinancePlan Serializer
# --------------------------------------------------------
class FinancePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancePlan
        fields = '__all__'


# --------------------------------------------------------
# Auto Finance Plan Serializer (for output)
# --------------------------------------------------------
class AutoFinancePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutoFinancePlan
        fields = [
            "id",
            "credit_application",
            "credit_score",
            "apc_score",
            "risk_tier",
            "customer_monthly_income",
            "payment_capacity_factor",
            "maximum_allowed_installment",
            "minimum_down_payment_percentage",
            "allowed_plans",
            "high_end_extra_percentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# --------------------------------------------------------
# Input Serializer (for creating temp finance plan)
# --------------------------------------------------------
class AutoFinancePlanCreateSerializer(serializers.Serializer):
    """
    Input: customer_id only
    Used to fetch credit application, score, etc.
    """
    customer_id = serializers.IntegerField()


# ------------------------------
# EMI Schedule Serializer
# ------------------------------
class EMIScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = EMISchedule
        fields = '__all__'


# ------------------------------
# Payment Record Serializer
# ------------------------------
class PaymentRecordSerializer(serializers.ModelSerializer):
    finance_plan_id = serializers.UUIDField(write_only=True)
    emi_schedule_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = PaymentRecord
        fields = [
            'id', 'finance_plan_id', 'emi_schedule_id',
            'payment_type', 'payment_method', 'payment_amount',
            'payment_date', 'payment_status', 'transaction_reference',
            'receipt_number', 'notes', 'metadata', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def create(self, validated_data):
        finance_plan_id = validated_data.pop('finance_plan_id')
        emi_schedule_id = validated_data.pop('emi_schedule_id', None)

        finance_plan = FinancePlan.objects.get(id=finance_plan_id)
        emi_schedule = EMISchedule.objects.get(id=emi_schedule_id) if emi_schedule_id else None

        payment = PaymentRecord.objects.create(
            finance_plan=finance_plan,
            emi_schedule=emi_schedule,
            **validated_data
        )

        if payment.payment_status == 'COMPLETED' and emi_schedule:
            payment.apply_to_emi()

        return payment


# ------------------------------
# Finance Analytics Serializers
# ------------------------------
class FinanceOverviewSerializer(serializers.Serializer):
    total_finance_plans = serializers.IntegerField()
    total_customers = serializers.IntegerField()
    total_approved = serializers.IntegerField()
    total_rejected = serializers.IntegerField()
    total_amount_financed = serializers.FloatField()
    average_installment = serializers.FloatField()
    avg_apc_score = serializers.FloatField()
    avg_risk_tier = serializers.DictField(child=serializers.IntegerField())


# ------------------------------
# Finance Risk Tier Serializers
# ------------------------------
class FinanceRiskTierSerializer(serializers.Serializer):
    risk_tier = serializers.CharField()
    total_customers = serializers.IntegerField()
    total_finance_plans = serializers.IntegerField()
    total_amount_financed = serializers.FloatField()
    average_installment = serializers.FloatField()


# ------------------------------
# Finance AnalytCollection Serializers
# ------------------------------
class FinanceCollectionSerializer(serializers.Serializer):
    total_installments = serializers.IntegerField()
    total_collected = serializers.FloatField()
    total_pending = serializers.FloatField()
    collection_rate = serializers.FloatField()


class FinanceOverdueSerializer(serializers.Serializer):
    total_overdue_installments = serializers.IntegerField()
    total_overdue_amount = serializers.FloatField()
    customers_with_overdue = serializers.IntegerField()


# --------------------------------------
# Common Report Serializers
# --------------------------------------
class ApplicationSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    approved = serializers.IntegerField()
    rejected = serializers.IntegerField()
    pending = serializers.IntegerField()


class FinancingSummarySerializer(serializers.Serializer):
    total_financed = serializers.DecimalField(max_digits=12, decimal_places=2)
    average_down_payment = serializers.DecimalField(max_digits=5, decimal_places=2)


class RiskTierSerializer(serializers.Serializer):
    risk_tier = serializers.CharField()
    count = serializers.IntegerField()


class CommonReportSerializer(serializers.Serializer):
    customers = serializers.IntegerField()
    applications = ApplicationSummarySerializer()
    financing = FinancingSummarySerializer()
    risk_tiers = RiskTierSerializer(many=True)

# --------------------------------------
# Region-wise Report Serializers
# --------------------------------------
class RegionSalesSummarySerializer(serializers.Serializer):
    region = serializers.CharField()
    total_customers = serializers.IntegerField()
    total_applications = serializers.IntegerField()
    approved = serializers.IntegerField()
    rejected = serializers.IntegerField()


class RegionFinanceSummarySerializer(serializers.Serializer):
    region = serializers.CharField()
    total_financed = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    avg_down_payment = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


class RegionWiseReportSerializer(serializers.Serializer):
    sales_summary = RegionSalesSummarySerializer(many=True)
    finance_summary = RegionFinanceSummarySerializer(many=True)
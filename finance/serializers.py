from datetime import date
from rest_framework import serializers
from .models import FinancePlan, EMISchedule, PaymentRecord


# ------------------------------
# Finance Plan Serializer
# ------------------------------
class FinancePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancePlan
        fields = [
            'credit_application',
            'credit_score',
            'apc_score',
            'device_price',
            'is_high_end_device',
            'selected_term',
            'customer_monthly_income',
            'payment_capacity_factor',
        ]
        read_only_fields = []

    def create(self, validated_data):
        finance_plan = FinancePlan.objects.create(**validated_data)
        first_due_date = date.today()
        EMISchedule.generate_schedule(finance_plan, first_due_date)
        return finance_plan


# Minimal input serializer for creating finance plan
class FinancePlanCreateSerializer(serializers.Serializer):
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

from datetime import date
from rest_framework import serializers
from .models import FinancePlan, EMISchedule, PaymentRecord, AutoFinancePlan,FinanceMultiple
from products.serializers import ProductModelSerializer
from products.models import ProductModel


# --------------------------------------------------------
# Finance Plan Create from AutoFinancePlan Serializer
# --------------------------------------------------------
class FinancePlanCreateSerializer(serializers.Serializer):
    temp_plan_id = serializers.IntegerField()
    device = serializers.PrimaryKeyRelatedField(
        queryset=ProductModel.objects.all(),
        help_text='Product model ID - required'
    )
    device_price = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text='Optional - will be auto-calculated from device if not provided'
    )
    actual_down_payment = serializers.DecimalField(max_digits=10, decimal_places=2)
    choosed_allowed_plans = serializers.DictField(
        child=serializers.IntegerField(),
        help_text='Example: {"selected_term": 6, "installment_frequency_days": 30}'
    )


# --------------------------------------------------------
# Finance Plan Create from AutoFinancePlan Serializer
# --------------------------------------------------------
class FinancePlanSerializer(serializers.ModelSerializer):
    device = serializers.PrimaryKeyRelatedField(
        queryset=ProductModel.objects.all(),
        required=True
    )
    device_price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = FinancePlan
        fields = '__all__'
    
    def create(self, validated_data):
        user = self.context['request'].user
        instance = FinancePlan(**validated_data)
        instance.save(user=user)  #  pass logged-in user to model save
        return instance
    

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


# --------------------------------------------------------
# EMI Schedule Serializer
# --------------------------------------------------------
class EMIScheduleSerializerPlan(serializers.ModelSerializer):
    finance_plan_id = serializers.IntegerField(source='finance_plan.id', read_only=True)
    customer_name = serializers.SerializerMethodField()
    
    class Meta:
        model = EMISchedule
        fields = '__all__'
    
    def get_customer_name(self, obj):
        return f"{obj.finance_plan.credit_application.customer.first_name} {obj.finance_plan.credit_application.customer.last_name}"


# ----------------------------------
# Extented Payment Record Serializer
# ----------------------------------
class FinancePlanNestedSerializer(FinancePlanSerializer):
    """
    Extended serializer for FinancePlan with nested device and customer details.
    """
    device = ProductModelSerializer(read_only=True)
    customer = serializers.SerializerMethodField()

    class Meta(FinancePlanSerializer.Meta):
        fields = '__all__'

    def get_customer(self, obj):
        credit_app = getattr(obj, "credit_application", None)
        if not credit_app or not hasattr(credit_app, "customer"):
            return None
        customer = credit_app.customer
        return {
            "id": customer.id,
            "name": f"{customer.first_name} {customer.last_name}",
            "email": getattr(customer, "email", None),
            "phone": getattr(customer, "phone_number", None),
        }
    

#-----------------------------------------------------  
# Payment → FinancePlan → Device → Customer Serializer
#-------------------------------------------------------
class PaymentRecord3DSerializer(serializers.ModelSerializer):
    """
    Serializer for PaymentRecord with full 3D relational context:
    Payment → FinancePlan → Device → Customer
    """
    finance_plan = FinancePlanNestedSerializer(read_only=True)

    class Meta:
        model = PaymentRecord
        fields = [
            "id",
            "finance_plan",
            "payment_type",
            "payment_method",
            "payment_amount",
            "payment_status",
            "payment_date",
            "transaction_reference",
            "created_at",
        ]


# ------------------------------
# Payment Record Serializer
# ------------------------------
class PaymentCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating PaymentRecord entries.    """

    finance_plan = serializers.PrimaryKeyRelatedField(
        queryset=FinancePlan.objects.all(),
        required=True,
        help_text="ID of the related Finance Plan."
    )
    payment_type = serializers.ChoiceField(
        choices=[
            ("EMI", "EMI"),
            ("DOWN_PAYMENT", "Down Payment"),
            ("FULL_SETTLEMENT", "Full Settlement"),
            ("LATE_FEE", "Late Fee"),
        ],
        required=True,
        help_text="Type of payment (EMI, DOWN_PAYMENT, FULL_SETTLEMENT, LATE_FEE)."
    )
    payment_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=True,
        help_text="Amount paid by the customer."
    )
    transaction_reference = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional transaction reference from gateway (e.g., YAPPY-TRX-784923)."
    )

    class Meta:
        model = PaymentRecord
        fields = [
            "finance_plan",
            "payment_type",
            "payment_amount",
            "transaction_reference",
        ]

    def validate_finance_plan(self, value):
        """Ensure finance plan is active or valid."""
        if not value.is_active:
            raise serializers.ValidationError("Selected finance plan is inactive or closed.")
        return value

    def validate_payment_amount(self, value):
        """Ensure positive amount."""
        if value <= 0:
            raise serializers.ValidationError("Payment amount must be greater than zero.")
        return value

    def validate(self, attrs):
        """Cross-field validation logic."""
        finance_plan = attrs.get("finance_plan")
        payment_type = attrs.get("payment_type")

        # Example: restrict FULL_SETTLEMENT if plan already paid off
        if payment_type == "FULL_SETTLEMENT" and getattr(finance_plan, "is_settled", False):
            raise serializers.ValidationError("Finance plan already fully settled.")

        return attrs

    def create(self, validated_data):
        """
        Create and return a new PaymentRecord instance.
        """
        # Automatically set derived fields (others handled in view)
        return PaymentRecord.objects.create(**validated_data)


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


# ============================================================
# Finance Collection Analytics Serializer (for Dashboard / Reports)
# ============================================================
class FinanceCollectionAnalyticsSerializer(serializers.Serializer):
    total_installments = serializers.IntegerField(help_text="Total number of installments created.")
    total_collected = serializers.DecimalField(max_digits=12, decimal_places=2, help_text="Total amount collected so far.")
    total_pending = serializers.DecimalField(max_digits=12, decimal_places=2, help_text="Total amount still pending.")
    total_overdue = serializers.DecimalField(max_digits=12, decimal_places=2, help_text="Total overdue amount.")
    total_overdue_installments = serializers.IntegerField(help_text="Number of overdue installments.")
    collection_rate = serializers.DecimalField(max_digits=5, decimal_places=2, help_text="Percentage of collection achieved.")
    customers_with_overdue = serializers.IntegerField(help_text="Number of customers having overdue installments.")
    regions_summary = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Optional breakdown by region: [{'region': 'Kochi', 'collected': 50000, 'pending': 10000}]"
    )

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


# --------------------------------------------------------
# Payment Record Serializer
# --------------------------------------------------------
class PaymentRecordSerializerPlan(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    finance_plan_id = serializers.IntegerField(source='finance_plan.id', read_only=True)
    emi_installment_number = serializers.IntegerField(source='emi_schedule.installment_number', read_only=True, allow_null=True)
    processed_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentRecord
        fields = '__all__'
    
    def get_customer_name(self, obj):
        return f"{obj.finance_plan.credit_application.customer.first_name} {obj.finance_plan.credit_application.customer.last_name}"
    
    def get_processed_by_name(self, obj):
        if obj.processed_by:
            return f"{obj.processed_by.first_name} {obj.processed_by.last_name}"
        return None
    
# ============================================================
# Main Serializer — PaymentRecord3DSerializer
# ============================================================

class PaymentRecord3DSerializer(serializers.ModelSerializer):
    finance_plan = FinancePlanNestedSerializer(read_only=True)
    emi_schedule = EMIScheduleSerializer(read_only=True)

    # Include related payments under same plan (for transaction history)
    related_payments = serializers.SerializerMethodField()

    class Meta:
        model = PaymentRecord
        fields = [
            "id",
            "finance_plan",
            "emi_schedule",
            "payment_type",
            "payment_method",
            "payment_amount",
            "payment_status",
            "payment_date",
            "transaction_reference",
            "processed_by",
            "related_payments",
            "created_at",
            "updated_at",
        ]

    def get_related_payments(self, obj):
        """
        Return other payments of the same FinancePlan (excluding this one).
        """
        qs = PaymentRecord.objects.filter(finance_plan=obj.finance_plan).exclude(id=obj.id)
        return [
            {
                "id": p.id,
                "type": p.payment_type,
                "amount": str(p.payment_amount),
                "status": p.payment_status,
                "date": p.payment_date,
                "transaction_reference": p.transaction_reference,
            }
            for p in qs.order_by("-payment_date")[:5]  # last 5 transactions
        ]
    


# ============================================================
# FOR DYNAMIC INTREST (MULTIPLE) 
# ============================================================

class FinanceMultipleSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceMultiple
        fields = [
            'id', 
            'term_months', 
            'interval_days', 
            'multiple', 
            'is_active', 
            'created_at', 
            'updated_at'
            ]
        read_only_fields = ['created_at', 'updated_at']


# ============================================================
# FOR EMI PAYMENT 
# ============================================================
class EMIPaymentRequestSerializer(serializers.Serializer):
    amount_paid = serializers.DecimalField(max_digits=10, decimal_places=2)
    payment_method = serializers.CharField(max_length=50)

# ========== SERIALIZER FOR WESTERN UNION VERIFY CUSTOMER=============

class VerifyCustomerSerializer(serializers.Serializer):
    customer_id = serializers.CharField()
    operation_type = serializers.CharField()
    utility = serializers.CharField()
    terminal_id = serializers.CharField()
    date = serializers.CharField()
    time = serializers.CharField()
    operation_code = serializers.CharField()
    user = serializers.CharField()
    password = serializers.CharField()


# ============================================================
# FOR GETTING COMPLETE FINANCE DETAILS
# ============================================================
class FinanceFullDetailsSerializer(serializers.Serializer):
    finance_plan = FinancePlanNestedSerializer()
    emi_schedule = EMIScheduleSerializer(many=True)
    overdue_details = FinanceOverdueSerializer()
    payments = PaymentRecordSerializerPlan(many=True)
    interest_details = serializers.DictField(required=False)
    total_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_outstanding = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_emis_count = serializers.IntegerField()
    paid_emis_count = serializers.IntegerField()
    overdue_emis_count = serializers.IntegerField()

    def to_representation(self, instance):
        data = super().to_representation(instance)

        finance_plan = instance["finance_plan"]

        # include region_id and store_id
        data["region_id"] = (
            finance_plan.store.region_id if finance_plan.store else None
        )
        data["store_id"] = (
            finance_plan.store.id if finance_plan.store else None
        )

        # Interest logic
        multiple = FinanceMultiple.objects.filter(
            term_months=finance_plan.selected_term,
            interval_days=finance_plan.installment_frequency_days,
            is_active=True
        ).first()

        if multiple:
            principal = float(finance_plan.device_price)
            interest_amount = principal * (float(multiple.multiple) - 1)
            total_payable = principal + interest_amount

            emi_count = getattr(finance_plan, "total_installments", None)
            if not emi_count:
                emi_count = int(finance_plan.selected_term * 30 /
                                finance_plan.installment_frequency_days)

            emi_amount = total_payable / emi_count

            data["interest_details"] = {
                "term_months": finance_plan.selected_term,
                "interval_days": finance_plan.installment_frequency_days,
                "multiple": float(multiple.multiple),
                "principal_amount": principal,
                "interest_amount": interest_amount,
                "total_payable": total_payable,
                "emi_count": emi_count,
                "emi_amount": emi_amount,
            }
        else:
            data["interest_details"] = None

        return data
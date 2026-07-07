from datetime import date
from rest_framework import serializers
from .models import FinancePlan, EMISchedule, PaymentRecord, AutoFinancePlan,FinanceMultiple, LoanDisbursement, CustomerLoanLedgerEntry, MerchantLedgerEntry, MerchantSettlement
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
    imei = serializers.CharField(required=False, allow_blank=True, allow_null=True)


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
    device_details = serializers.SerializerMethodField()
    store_details = serializers.SerializerMethodField()
    sales_person_details = serializers.SerializerMethodField()
    customer_details = serializers.SerializerMethodField()
    emi_schedule = serializers.SerializerMethodField()
    
    class Meta:
        model = FinancePlan
        fields = '__all__'
    
    def create(self, validated_data):
        user = self.context['request'].user
        instance = FinancePlan(**validated_data)
        instance.save(user=user)  #  pass logged-in user to model save
        return instance

    def get_device_details(self, obj):
        try:
            if obj.device:
                imei = None
                if obj.credit_application:
                    imei = obj.credit_application.device_imei
                return {
                    "id": obj.device.id,
                    "brand": obj.device.brand.name if obj.device.brand else None,
                    "model_name": obj.device.model_name,
                    "color": obj.device.color,
                    "ram": obj.device.ram,
                    "storage": obj.device.storage,
                    "imei": imei,
                }
        except Exception:
            pass
        return None

    def get_store_details(self, obj):
        try:
            if obj.store:
                return {
                    "id": str(obj.store.id),
                    "name": obj.store.name,
                    "code": obj.store.code,
                    "region_name": obj.store.region.name if obj.store.region else None,
                    "province_name": obj.store.province.name if obj.store.province else None,
                    "district_name": obj.store.district.name if obj.store.district else None,
                    "corregimiento_name": obj.store.corregimiento.name if obj.store.corregimiento else None,
                    "sales_advisor": f"{obj.store.sales_advisor.first_name} {obj.store.sales_advisor.last_name}" if obj.store.sales_advisor else None,
                }
        except Exception:
            pass
        return None

    def get_sales_person_details(self, obj):
        try:
            if obj.created_by:
                return {
                    "id": obj.created_by.id,
                    "first_name": obj.created_by.first_name,
                    "last_name": obj.created_by.last_name,
                    "username": obj.created_by.username,
                    "email": obj.created_by.email,
                }
        except Exception:
            pass
        return None

    def get_customer_details(self, obj):
        if obj.credit_application and obj.credit_application.customer:
            c = obj.credit_application.customer
            return {
                "id": c.id,
                "first_name": c.first_name,
                "last_name": c.last_name,
                "email": c.email,
                "phone_number": c.phone_number,
                "document_number": c.document_number,
                "document_type": c.document_type,
                "status": c.status,
                "otp_verified": c.otp_verified,
                "latitude": float(c.latitude) if c.latitude else None,
                "longitude": float(c.longitude) if c.longitude else None,
            }
        return None

    def get_emi_schedule(self, obj):
        return EMIScheduleSerializer(obj.emi_schedule.all(), many=True).data
    

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
    amount = serializers.DecimalField(source='installment_amount', max_digits=10, decimal_places=2, read_only=True)
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
    payment_method = serializers.ChoiceField(
        choices=[
            ('PUNTO_PAGO', 'Punto Pago'),
            ('YAPPY', 'Yappy'),
            ('WESTERN_UNION', 'Western Union'),
            ('CASH', 'Cash'),
            ('BANK_TRANSFER', 'Bank Transfer'),
            ('OTHER', 'Other'),
        ],
        default="CASH",
        required=False,
        help_text="Payment method used (e.g. CASH, YAPPY, PUNTO_PAGO, WESTERN_UNION)."
    )

    class Meta:
        model = PaymentRecord
        fields = [
            "finance_plan",
            "payment_type",
            "payment_amount",
            "transaction_reference",
            "payment_method",
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
    tipo_operacion = serializers.CharField(required=True)
    campos_busqueda = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        required=True
    )
    utility = serializers.CharField(required=True)
    terminal = serializers.CharField(required=True)
    fecha = serializers.CharField(required=True)
    hora = serializers.CharField(required=True)
    cod_operacion = serializers.CharField(required=True)
    user = serializers.CharField(required=False, default='pagofacil')
    username = serializers.CharField(required=False, default='pagofacil')
    userName = serializers.CharField(required=False, default='pagofacil')
    password = serializers.CharField(required=False, default='pagofacil')


# ========== SERIALIZER FOR WESTERN UNION PAYMENT (DIRECTA) =============

class WesternUnionPaymentSerializer(serializers.Serializer):
    tipo_operacion = serializers.CharField(required=True)
    cod_cliente = serializers.CharField(required=True, allow_null=True, allow_blank=True)
    cod_operacion = serializers.CharField(required=True)
    id_item = serializers.CharField(required=True, allow_null=True, allow_blank=True)
    terminal = serializers.CharField(required=True)
    fecha = serializers.CharField(required=True)
    hora = serializers.CharField(required=True)
    secuencia = serializers.CharField(required=True)
    cod_trx = serializers.CharField(required=True)
    cod_barra = serializers.CharField(required=True)
    utility = serializers.CharField(required=True)
    importe = serializers.CharField(required=True)
    medio_pago = serializers.CharField(required=True)
    user = serializers.CharField(required=False, default='pagofacil')
    username = serializers.CharField(required=False, default='pagofacil')
    userName = serializers.CharField(required=False, default='pagofacil')
    password = serializers.CharField(required=False, default='pagofacil')


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


# ============================================================
# FOR PUNTO PAGO INTEGRATION
# ============================================================

class PuntoPagoVerifyRequestSerializer(serializers.Serializer):
    identification = serializers.CharField(
        required=True, 
        help_text="Customer ID/Document number to verify"
    )


class PuntoPagoProcessRequestSerializer(serializers.Serializer):
    identification = serializers.CharField(
        required=True, 
        help_text="Customer ID/Document number"
    )
    payment_reference = serializers.CharField(
        required=True, 
        help_text="Unique external payment transaction reference"
    )
    amount = serializers.DecimalField(
        required=True, 
        max_digits=10, 
        decimal_places=2, 
        help_text="Payment amount"
    )


# ========================================
# ACCOUNTING SERIALIZERS (OLA CARS STYLE)
# ========================================

from .models import AccountingCode, Invoice, PaymentReceived, LedgerEntry, Tax, BankAccount, Vendor, Expense, Bill, PaymentMade, CreditNote, JournalEntry

class AccountingCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingCode
        fields = '__all__'


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_document = serializers.SerializerMethodField()
    device_name = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = '__all__'

    def get_customer_name(self, obj):
        return f"{obj.customer.first_name} {obj.customer.last_name}"

    def get_customer_document(self, obj):
        return obj.customer.document_number

    def get_device_name(self, obj):
        if obj.finance_plan and obj.finance_plan.device:
            return f"{obj.finance_plan.device.brand.name} {obj.finance_plan.device.model_name}"
        return "N/A"

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        from datetime import date, datetime
        due_date = instance.due_date
        if isinstance(due_date, str):
            try:
                due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        if instance.status in ['PENDING', 'PARTIAL'] and due_date and due_date < date.today():
            ret['status'] = 'OVERDUE'
        return ret


class PaymentReceivedSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    deposited_to_name = serializers.SerializerMethodField()
    invoice_details = serializers.SerializerMethodField()

    class Meta:
        model = PaymentReceived
        fields = '__all__'

    def get_customer_name(self, obj):
        return f"{obj.customer.first_name} {obj.customer.last_name}"

    def get_deposited_to_name(self, obj):
        return f"{obj.deposited_to.code} - {obj.deposited_to.name}"

    def get_invoice_details(self, obj):
        details = []
        if not obj.invoices:
            return details
        invoice_ids = [item.get('invoice_id') for item in obj.invoices if item.get('invoice_id')]
        if not invoice_ids:
            return details
        from .models import Invoice
        invoices_map = {inv.id: inv for inv in Invoice.objects.filter(id__in=invoice_ids)}
        for item in obj.invoices:
            inv_id = item.get('invoice_id')
            applied = item.get('amount_applied', 0)
            inv = invoices_map.get(inv_id)
            if inv:
                details.append({
                    'id': inv.id,
                    'invoice_number': inv.invoice_number,
                    'amount_applied': float(applied)
                })
        return details


class LedgerEntrySerializer(serializers.ModelSerializer):
    accounting_code_details = serializers.SerializerMethodField()
    reference_document = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = '__all__'

    def get_accounting_code_details(self, obj):
        return {
            "code": obj.accounting_code.code,
            "name": obj.accounting_code.name,
            "category": obj.accounting_code.category
        }

    def get_reference_document(self, obj):
        if obj.invoice:
            return f"Invoice {obj.invoice.invoice_number}"
        elif obj.payment_received:
            return f"Payment {obj.payment_received.payment_number}"
        elif obj.expense:
            return f"Expense {obj.expense.expense_number}"
        elif obj.bill:
            return f"Bill {obj.bill.bill_number}"
        elif obj.payment_made:
            return f"Vendor Pay {obj.payment_made.payment_number}"
        elif obj.credit_note:
            return f"Credit Note {obj.credit_note.credit_note_number}"
        elif obj.journal_entry:
            return f"Journal {obj.journal_entry.reference_number}"
        elif obj.disbursement:
            return f"Disbursement {obj.disbursement.disbursement_number}"
        elif obj.settlement:
            return f"Settlement {obj.settlement.settlement_number}"
        elif obj.customer_loan_ledger_entry:
            return f"Cust Loan Entry {obj.customer_loan_ledger_entry.id}"
        elif obj.merchant_ledger_entry:
            return f"Merch Entry {obj.merchant_ledger_entry.id}"
        return "N/A"


class TaxSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tax
        fields = '__all__'


class BankAccountSerializer(serializers.ModelSerializer):
    accounting_code_name = serializers.SerializerMethodField()

    class Meta:
        model = BankAccount
        fields = '__all__'

    def get_accounting_code_name(self, obj):
        if obj.accounting_code:
            return f"{obj.accounting_code.code} - {obj.accounting_code.name}"
        return "N/A"


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = '__all__'


class ExpenseSerializer(serializers.ModelSerializer):
    paid_from_name = serializers.SerializerMethodField()
    expense_category_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = '__all__'

    def get_paid_from_name(self, obj):
        if obj.paid_from:
            return f"{obj.paid_from.code} - {obj.paid_from.name}"
        return "N/A"

    def get_expense_category_name(self, obj):
        if obj.expense_category:
            return f"{obj.expense_category.code} - {obj.expense_category.name}"
        return "N/A"


class BillSerializer(serializers.ModelSerializer):
    vendor_name = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = '__all__'

    def get_vendor_name(self, obj):
        return obj.vendor.name if obj.vendor else "N/A"


class PaymentMadeSerializer(serializers.ModelSerializer):
    vendor_name = serializers.SerializerMethodField()
    paid_from_name = serializers.SerializerMethodField()

    class Meta:
        model = PaymentMade
        fields = '__all__'

    def get_vendor_name(self, obj):
        return obj.vendor.name if obj.vendor else "N/A"

    def get_paid_from_name(self, obj):
        if obj.paid_from:
            return f"{obj.paid_from.code} - {obj.paid_from.name}"
        return "N/A"


class CreditNoteSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = CreditNote
        fields = '__all__'

    def get_customer_name(self, obj):
        return f"{obj.customer.first_name} {obj.customer.last_name}" if obj.customer else "N/A"


class JournalEntrySerializer(serializers.ModelSerializer):
    ledger_entries = LedgerEntrySerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = '__all__'


class LoanDisbursementSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()

    class Meta:
        model = LoanDisbursement
        fields = '__all__'

    def get_customer_name(self, obj):
        c = obj.finance_plan.customer
        return f"{c.first_name} {c.last_name}" if c else "N/A"

    def get_store_name(self, obj):
        s = obj.finance_plan.store
        return s.name if s else "N/A"


class CustomerLoanLedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerLoanLedgerEntry
        fields = '__all__'


class MerchantSettlementSerializer(serializers.ModelSerializer):
    store_name = serializers.SerializerMethodField()
    bank_account_name = serializers.SerializerMethodField()
    bill_number = serializers.SerializerMethodField()
    bill_status = serializers.SerializerMethodField()

    class Meta:
        model = MerchantSettlement
        fields = '__all__'

    def get_store_name(self, obj):
        return obj.store.name if obj.store else "N/A"

    def get_bank_account_name(self, obj):
        return obj.bank_account.account_name if obj.bank_account else "N/A"

    def get_bill_number(self, obj):
        return obj.bill.bill_number if obj.bill else None

    def get_bill_status(self, obj):
        return obj.bill.status if obj.bill else None


class MerchantLedgerEntrySerializer(serializers.ModelSerializer):
    store_name = serializers.SerializerMethodField()

    class Meta:
        model = MerchantLedgerEntry
        fields = '__all__'

    def get_store_name(self, obj):
        return obj.store.name if obj.store else "N/A"


from .models import UncategorizedBankEntry

class UncategorizedBankEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = UncategorizedBankEntry
        fields = '__all__'
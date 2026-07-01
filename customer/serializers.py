from rest_framework import serializers
from .models import ( Customer,CreditScore,
                     CreditConfig,PersonalReference,
                     CustomerIncomeFile,
                     )





# =========== customer serializers for CRUD (except block customer) ==========#

  
class CustomerSerializer(serializers.ModelSerializer):
    created_by_details = serializers.SerializerMethodField()
    apc_score = serializers.SerializerMethodField()
    registration_status = serializers.SerializerMethodField()
    next_step_label = serializers.SerializerMethodField()
    next_step_url = serializers.SerializerMethodField()
    salary = serializers.SerializerMethodField()
    employer = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id',
            'document_number',
            'document_type', 
            'first_name', 
            'last_name', 
            'email', 
            'phone_number', 
            'employer',
            'salary',
            'status',
            'otp_verified',
            'latitude',
            'longitude',
            'created_by',
            'created_by_details',
            'apc_score',
            'registration_status',
            'next_step_label',
            'next_step_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'first_name': {'required': False, 'allow_blank': True},
            'last_name': {'required': False, 'allow_blank': True},
            'email': {'required': False, 'allow_blank': True},
            'phone_number': {'required': False, 'allow_blank': True},
            'latitude': {'required': False},
            'longitude': {'required': False},
        }

    def create(self, validated_data):
        user = self.context['request'].user
        return Customer.objects.create(created_by=user, **validated_data)

    def get_created_by_details(self, obj):
        if not obj.created_by:
            return None
        
        user = obj.created_by
        data = {
            'id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'role': user.role,
        }
        
        if hasattr(user, 'store') and user.store:
            store = user.store
            data['store'] = {
                'id': str(store.id),
                'name': store.name,
                'code': store.code,
                'region': store.region.name if store.region else None,
                'province': store.province.name if store.province else None,
                'district': store.district.name if store.district else None,
                'corregimiento': store.corregimiento.name if store.corregimiento else None,
                'sales_advisor': f"{store.sales_advisor.first_name} {store.sales_advisor.last_name}" if store.sales_advisor else None,
            }
        else:
            data['store'] = None
            
        return data

    def get_apc_score(self, obj):
        latest_score = obj.credit_scores.order_by('-created_at').first()
        return latest_score.apc_score if latest_score else None

    def get_salary(self, obj):
        from customer.models import CustomerIncome
        income_obj = CustomerIncome.objects.filter(document_id=obj.document_number).first()
        if income_obj:
            return float(income_obj.monthly_income)
        # Fallback to SQLite cache database
        from customer.utils import get_customer_monthly_income
        val = get_customer_monthly_income(obj.document_number)
        return float(val) if val else 0.0

    def get_employer(self, obj):
        from customer.models import CustomerIncome
        income_obj = CustomerIncome.objects.filter(document_id=obj.document_number).first()
        if income_obj:
            return income_obj.employer
        # Fallback to SQLite cache database
        from django.conf import settings
        import sqlite3
        db_path = getattr(settings, "EXCEL_CACHE_DB", None)
        if db_path:
            try:
                conn = sqlite3.connect(db_path, timeout=5)
                cur = conn.cursor()
                cur.execute("SELECT employer FROM income_data WHERE TRIM(document_id)=? LIMIT 1", (str(obj.document_number).strip(),))
                row = cur.fetchone()
                conn.close()
                if row:
                    return row[0] or ""
            except Exception:
                pass
        return ""

    def _get_registration_details(self, obj):
        if hasattr(obj, '_cached_registration_details'):
            return obj._cached_registration_details

        # Fetch latest application
        latest_app = obj.credit_applications.order_by('-created_at').first()

        # 1. OTP Check (Not Verified status)
        otp_is_verified = latest_app.otp_verified if latest_app else obj.otp_verified
        if not otp_is_verified:
            res = {
                "status": "Not Verified",
                "next_step_label": "Verify OTP",
                "next_step_url": "/sellerPortal/createApplicant"
            }
            obj._cached_registration_details = res
            return res
 
        # 2. Credit Score check (OTP Verified status)
        latest_score = obj.credit_scores.order_by('-created_at').first()
        if not latest_score:
            res = {
                "status": "OTP Verified",
                "next_step_label": "Check Credit Score",
                "next_step_url": "/sellerPortal/createApplicant"
            }
            obj._cached_registration_details = res
            return res
 
        # Check if rejected at credit score level
        if latest_score.apc_status == "REJECTED" or latest_score.final_credit_status == "REJECTED" or (latest_score.apc_score and latest_score.apc_score < 500):
            res = {
                "status": "Rejected",
                "next_step_label": "Rejected",
                "next_step_url": None
            }
            obj._cached_registration_details = res
            return res
 
        # 3. Credit Application check (APC Checked status)
        if not latest_app:
            res = {
                "status": "APC Checked",
                "next_step_label": "Resume Application",
                "next_step_url": "/sellerPortal/createApplicant"
            }
            obj._cached_registration_details = res
            return res

        # Check application status
        if latest_app.status == "REJECTED":
            res = {
                "status": "Rejected",
                "next_step_label": "Rejected",
                "next_step_url": None
            }
            obj._cached_registration_details = res
            return res
        elif latest_app.status == "EXPIRED":
            res = {
                "status": "Expired",
                "next_step_label": "Restart Application",
                "next_step_url": "/sellerPortal/createApplicant"
            }
            obj._cached_registration_details = res
            return res

        # Map status dynamically on each customer based on latest_app.current_step
        step = latest_app.current_step
        
        has_disbursement = False
        if latest_app.status == "APPROVED" and latest_app.device_imei:
            from finance.models import LoanDisbursement
            if hasattr(latest_app, 'finance_plan') and latest_app.finance_plan:
                has_disbursement = LoanDisbursement.objects.filter(
                    finance_plan=latest_app.finance_plan,
                    status='COMPLETED'
                ).exists()

        if latest_app.status == "APPROVED":
            if not latest_app.device_imei:
                status_str = "Device Enrollment Pending"
            elif has_disbursement:
                status_str = "Disbursed"
            else:
                status_str = "Approved"
        elif step == 1 or step == 2:
            status_str = "APC Checked"
        elif step == 3:
            status_str = "Salary Checked"
        elif step == 4:
            status_str = "Identity Verified"
        elif step == 5:
            status_str = "Device Selected"
        elif step == 6:
            status_str = "Draft Plan Created"
        elif step == 7:
            status_str = "Device IMEI Enrolled"
        elif step == 8:
            status_str = "Personal References Added"
        else:
            status_str = "APC Checked"

        if status_str in ["Approved", "Disbursed"]:
            res = {
                "status": status_str,
                "next_step_label": "Completed",
                "next_step_url": None
            }
        else:
            res = {
                "status": status_str,
                "next_step_label": "Resume",
                "next_step_url": "/sellerPortal/createApplicant"
            }
        
        obj._cached_registration_details = res
        return res

    def get_registration_status(self, obj):
        return self._get_registration_details(obj)["status"]

    def get_next_step_label(self, obj):
        return self._get_registration_details(obj)["next_step_label"]

    def get_next_step_url(self, obj):
        return self._get_registration_details(obj)["next_step_url"]



# =========== customer serializers for status change ==========#


class CustomerStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['status']

    def validate_status(self, value):
        allowed = ['ACTIVE', 'INACTIVE', 'BLOCKED']
        value_upper = value.upper()
        if value_upper not in allowed:
            raise serializers.ValidationError(f"Status must be one of {allowed}")
        return value_upper





# =================CREDIT SCORE SERIALIZERS=========================





class CreditScoreSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    consulted_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = CreditScore
        fields = [
            'id',
            'customer',
            'apc_score',
            'apc_score_date',
            'apc_consultation_id',
            'apc_status',
            'internal_score',
            'good_payment_history_points',
            'delinquency_penalty_points',
            'number_of_previous_loans',
            'declared_income',
            'validated_income',
            'monthly_expenses',
            'max_installment_capacity',
            'payment_capacity_status',
            'final_credit_status',
            'credit_limit',
            'score_valid_until',
            'is_expired',
            'verbal_authorization_given',
            'consulted_by',
            'risk_category',
            'existing_monthly_debt',
            'existing_loans_count',
            'late_payments_count',
            'bureau_recommendation',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'apc_score_date',
            'max_installment_capacity',
            'score_valid_until',
            'is_expired',
            'created_at',
            'updated_at',
        ]


# ========== SERIALZER FOR SET CREDIT THRESHOLD=============    

class CreditConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditConfig
        fields = [
            "id",
            "tier_a_min_score",
            "tier_b_min_score",
            "tier_c_min_score",
            "loan_agreement_template",
            "updated_at",
            "created_at",
        ]


# ================SERIALZER FOR PERSONAL REFERENCES======


class PersonalReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonalReference
        fields = [
            "id",
            "full_name",
            "phone_number",
            "relationship",
            "is_valid",
            "validation_notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_phone_number(self, value):
        """
        Ensure the phone number is unique for this customer.
        """
        customer = self.instance.customer if self.instance else self.initial_data.get('customer')
        if not customer:
            return value  

        qs = PersonalReference.objects.filter(customer=customer, phone_number=value)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError("This phone number is already used for another reference.")
        return value



# ========== SERAILIZER FOR ADD/UPDATE INCOME FILE=========

class CustomerIncomeFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerIncomeFile
        fields = ['id', 'file', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']

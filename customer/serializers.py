from rest_framework import serializers
from .models import ( Customer,CreditScore,
                     CreditConfig,PersonalReference,
                     CustomerIncomeFile,
                     CreditApplication,
                     )





# =========== customer serializers for CRUD (except block customer) ==========#

  
class CustomerSerializer(serializers.ModelSerializer):
    created_by_details = serializers.SerializerMethodField()
    apc_score = serializers.SerializerMethodField()
    registration_status = serializers.SerializerMethodField()
    latest_application_id = serializers.SerializerMethodField()
    device_imei = serializers.SerializerMethodField()
    device_brand = serializers.SerializerMethodField()
    device_model = serializers.SerializerMethodField()
    next_step_label = serializers.SerializerMethodField()
    next_step_url = serializers.SerializerMethodField()
    salary = serializers.SerializerMethodField()
    employer = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    store_code = serializers.SerializerMethodField()
    region_name = serializers.SerializerMethodField()
    province_name = serializers.SerializerMethodField()
    district_name = serializers.SerializerMethodField()
    corregimiento_name = serializers.SerializerMethodField()
    amount_to_finance = serializers.SerializerMethodField()
    loan_account_number = serializers.SerializerMethodField()
    advance_balance = serializers.SerializerMethodField()

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
            'latest_application_id',
            'device_imei',
            'device_brand',
            'device_model',
            'store_name',
            'store_code',
            'region_name',
            'province_name',
            'district_name',
            'corregimiento_name',
            'next_step_label',
            'next_step_url',
            'amount_to_finance',
            'loan_account_number',
            'advance_balance',
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

    def get_latest_application_id(self, obj):
        latest = obj.credit_applications.order_by('-created_at').first()
        return latest.id if latest else None

    def get_device_imei(self, obj):
        latest = obj.credit_applications.order_by('-created_at').first()
        return latest.device_imei if latest else None

    def get_device_brand(self, obj):
        latest = obj.credit_applications.order_by('-created_at').first()
        return latest.device.brand.name if latest and latest.device and latest.device.brand else None

    def get_device_model(self, obj):
        latest = obj.credit_applications.order_by('-created_at').first()
        return latest.device.model_name if latest and latest.device else None

    def get_store_name(self, obj):
        if obj.created_by and getattr(obj.created_by, 'store', None):
            return obj.created_by.store.name
        return None

    def get_store_code(self, obj):
        if obj.created_by and getattr(obj.created_by, 'store', None):
            return obj.created_by.store.code
        return None

    def get_region_name(self, obj):
        if obj.created_by and getattr(obj.created_by, 'store', None) and obj.created_by.store.region:
            return obj.created_by.store.region.name
        return None

    def get_province_name(self, obj):
        if obj.created_by and getattr(obj.created_by, 'store', None) and obj.created_by.store.province:
            return obj.created_by.store.province.name
        return None

    def get_district_name(self, obj):
        if obj.created_by and getattr(obj.created_by, 'store', None) and obj.created_by.store.district:
            return obj.created_by.store.district.name
        return None

    def get_corregimiento_name(self, obj):
        if obj.created_by and getattr(obj.created_by, 'store', None) and obj.created_by.store.corregimiento:
            return obj.created_by.store.corregimiento.name
        return None

    def get_next_step_label(self, obj):
        return self._get_registration_details(obj)["next_step_label"]

    def get_next_step_url(self, obj):
        return self._get_registration_details(obj)["next_step_url"]

    def get_amount_to_finance(self, obj):
        latest = obj.credit_applications.order_by('-created_at').first()
        return latest.amount_to_finance if latest else None

    def get_loan_account_number(self, obj):
        latest = obj.credit_applications.order_by('-created_at').first()
        if latest and hasattr(latest, 'finance_plan') and latest.finance_plan:
            return latest.finance_plan.loan_account_number
        return None

    def get_advance_balance(self, obj):
        return float(obj.advance_balance)



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


# ========================================
#  SERIALIZER FOR NOTIFICATIONS
# ========================================

from .models import Notification

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'user', 'title', 'message', 'is_read', 'customer_id', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class CreditApplicationAsCustomerSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='customer.id', read_only=True)
    document_number = serializers.CharField(source='customer.document_number', read_only=True)
    document_type = serializers.CharField(source='customer.document_type', read_only=True)
    first_name = serializers.CharField(source='customer.first_name', read_only=True)
    last_name = serializers.CharField(source='customer.last_name', read_only=True)
    email = serializers.CharField(source='customer.email', read_only=True)
    phone_number = serializers.CharField(source='customer.phone_number', read_only=True)
    status = serializers.CharField(source='customer.status', read_only=True)
    created_by = serializers.IntegerField(source='customer.created_by.id', read_only=True, allow_null=True)
    
    created_by_details = serializers.SerializerMethodField()
    apc_score = serializers.SerializerMethodField()
    registration_status = serializers.SerializerMethodField()
    latest_application_id = serializers.IntegerField(source='id', read_only=True)
    device_imei = serializers.CharField(read_only=True)
    device_brand = serializers.SerializerMethodField()
    device_model = serializers.SerializerMethodField()
    next_step_label = serializers.SerializerMethodField()
    next_step_url = serializers.SerializerMethodField()
    
    amount_to_finance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    loan_account_number = serializers.SerializerMethodField()
    
    store_name = serializers.SerializerMethodField()
    store_code = serializers.SerializerMethodField()
    region_name = serializers.SerializerMethodField()
    province_name = serializers.SerializerMethodField()
    district_name = serializers.SerializerMethodField()
    corregimiento_name = serializers.SerializerMethodField()

    class Meta:
        model = CreditApplication
        fields = [
            'id',
            'document_number',
            'document_type', 
            'first_name', 
            'last_name', 
            'email', 
            'phone_number', 
            'status',
            'created_by',
            'created_by_details',
            'apc_score',
            'registration_status',
            'latest_application_id',
            'device_imei',
            'device_brand',
            'device_model',
            'store_name',
            'store_code',
            'region_name',
            'province_name',
            'district_name',
            'corregimiento_name',
            'next_step_label',
            'next_step_url',
            'amount_to_finance',
            'loan_account_number',
            'created_at',
            'updated_at',
        ]

    def get_created_by_details(self, obj):
        if not obj.customer or not obj.customer.created_by:
            return None
        user = obj.customer.created_by
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
        latest_score = obj.customer.credit_scores.order_by('-created_at').first()
        return latest_score.apc_score if latest_score else None

    def _get_registration_details(self, obj):
        if hasattr(obj, '_cached_registration_details'):
            return obj._cached_registration_details

        # 1. OTP Check
        otp_is_verified = obj.otp_verified
        if not otp_is_verified:
            res = {
                "status": "Not Verified",
                "next_step_label": "Verify OTP",
                "next_step_url": "/sellerPortal/createApplicant"
            }
            obj._cached_registration_details = res
            return res
 
        # 2. Credit Score check
        latest_score = obj.customer.credit_scores.order_by('-created_at').first()
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

        # Check application status
        if obj.status == "REJECTED":
            res = {
                "status": "Rejected",
                "next_step_label": "Rejected",
                "next_step_url": None
            }
            obj._cached_registration_details = res
            return res
        elif obj.status == "EXPIRED":
            res = {
                "status": "Expired",
                "next_step_label": "Restart Application",
                "next_step_url": "/sellerPortal/createApplicant"
            }
            obj._cached_registration_details = res
            return res

        # Map status dynamically on each customer based on current_step
        step = obj.current_step
        
        has_disbursement = False
        if obj.status == "APPROVED" and obj.device_imei:
            from finance.models import LoanDisbursement
            if hasattr(obj, 'finance_plan') and obj.finance_plan:
                has_disbursement = LoanDisbursement.objects.filter(
                    finance_plan=obj.finance_plan,
                    status='COMPLETED'
                ).exists()

        if obj.status == "APPROVED":
            if not obj.device_imei:
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

    def get_device_brand(self, obj):
        if obj.device and obj.device.brand:
            return obj.device.brand.name
        return obj.device_brand

    def get_device_model(self, obj):
        if obj.device:
            return obj.device.model_name
        return obj.device_model

    def get_store_name(self, obj):
        if hasattr(obj, 'finance_plan') and obj.finance_plan and obj.finance_plan.store:
            return obj.finance_plan.store.name
        elif obj.sales_person and getattr(obj.sales_person, 'store', None):
            return obj.sales_person.store.name
        return None

    def get_store_code(self, obj):
        if hasattr(obj, 'finance_plan') and obj.finance_plan and obj.finance_plan.store:
            return obj.finance_plan.store.code
        elif obj.sales_person and getattr(obj.sales_person, 'store', None):
            return obj.sales_person.store.code
        return None

    def get_region_name(self, obj):
        if hasattr(obj, 'finance_plan') and obj.finance_plan and obj.finance_plan.store and obj.finance_plan.store.region:
            return obj.finance_plan.store.region.name
        elif obj.sales_person and getattr(obj.sales_person, 'store', None) and obj.sales_person.store.region:
            return obj.sales_person.store.region.name
        return None

    def get_province_name(self, obj):
        if hasattr(obj, 'finance_plan') and obj.finance_plan and obj.finance_plan.store and obj.finance_plan.store.province:
            return obj.finance_plan.store.province.name
        elif obj.sales_person and getattr(obj.sales_person, 'store', None) and obj.sales_person.store.province:
            return obj.sales_person.store.province.name
        return None

    def get_district_name(self, obj):
        if hasattr(obj, 'finance_plan') and obj.finance_plan and obj.finance_plan.store and obj.finance_plan.store.district:
            return obj.finance_plan.store.district.name
        elif obj.sales_person and getattr(obj.sales_person, 'store', None) and obj.sales_person.store.district:
            return obj.sales_person.store.district.name
        return None

    def get_corregimiento_name(self, obj):
        if hasattr(obj, 'finance_plan') and obj.finance_plan and obj.finance_plan.store and obj.finance_plan.store.corregimiento:
            return obj.finance_plan.store.corregimiento.name
        elif obj.sales_person and getattr(obj.sales_person, 'store', None) and obj.sales_person.store.corregimiento:
            return obj.sales_person.store.corregimiento.name
        return None

    def get_loan_account_number(self, obj):
        if hasattr(obj, 'finance_plan') and obj.finance_plan:
            return obj.finance_plan.loan_account_number
        return None


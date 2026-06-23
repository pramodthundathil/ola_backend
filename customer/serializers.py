from rest_framework import serializers
from .models import ( Customer,CreditScore,
                     CreditConfig,PersonalReference,
                     CustomerIncomeFile,
                     )





# =========== customer serializers for CRUD (except block customer) ==========#

  
class CustomerSerializer(serializers.ModelSerializer):
    created_by_details = serializers.SerializerMethodField()

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
            'status',
            'otp_verified',
            'latitude',
            'longitude',
            'created_by',
            'created_by_details',
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

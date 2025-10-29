from rest_framework import serializers
from .models import ( Customer,CreditScore,
                     CreditConfig,PersonalReference
                     )





# =========== customer serializers for CRUD (except block customer) ==========#


class CustomerSerializer(serializers.ModelSerializer):
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
            'latitude',
            'longitude',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'status', 'created_by', 'created_at', 'updated_at']

    def create(self, validated_data):
        user = self.context['request'].user
        return Customer.objects.create(created_by=user, **validated_data)    


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

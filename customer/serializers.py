from rest_framework import serializers
from .models import  Customer,CreditScore





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
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'status', 'created_by', 'created_at', 'updated_at']

    def create(self, validated_data):
        user = self.context['request'].user
        return Customer.objects.create(created_by=user, **validated_data)    





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
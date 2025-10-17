from rest_framework import serializers
from .models import IdentityVerification, Customer

class GenerateVerificationLinkSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()


class MetaMapWebhookSerializer(serializers.Serializer):
    identityId = serializers.CharField()
    verificationId = serializers.CharField()
    status = serializers.CharField()
    face_match_score = serializers.FloatField(required=False)
    selfie_image_url = serializers.URLField(required=False)
    rejection_reason = serializers.CharField(required=False)
    steps = serializers.ListField(child=serializers.DictField(),required=False)






# =========== customer serializers for post/get/delete ==========#


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

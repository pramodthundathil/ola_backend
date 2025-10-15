from rest_framework import serializers
from .models import IdentityVerification, Customer

class GenerateVerificationLinkSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()

# class MetaMapWebhookSerializer(serializers.Serializer):
#     identityId = serializers.CharField()
#     status = serializers.CharField()
#     steps = serializers.ListField(child=serializers.DictField(), required=False)


class MetaMapWebhookSerializer(serializers.Serializer):
    identityId = serializers.CharField()
    verificationId = serializers.CharField()
    status = serializers.CharField()
    face_match_score = serializers.FloatField(required=False)
    selfie_image_url = serializers.URLField(required=False)
    rejection_reason = serializers.CharField(required=False)
import requests
from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import IdentityVerification, Customer
from .serializers import GenerateVerificationLinkSerializer, MetaMapWebhookSerializer


import base64

import qrcode
from io import BytesIO
from django.core.files.base import ContentFile
import logging

logger = logging.getLogger(__name__)



# -------------------------------
# Generate Verification Link / QR
# -------------------------------


class GenerateVerificationLinkView(APIView):
    """
    Generates a MetaMap verification link or QR code for the customer.
    """
    def post(self, request):
        # request.data= {"user_id": 25}
        serializer = GenerateVerificationLinkSerializer(data=request.data)
        if serializer.is_valid():
            user_id = serializer.validated_data['user_id']
        else:
            return Response(serializer.errors, status=400)
        

        try:
            customer = Customer.objects.get(id=user_id) 
        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)


        #  Prevent duplicate verification 

        existing_verification = getattr(customer, 'identity_verification', None)
        if existing_verification and existing_verification.overall_status in ['PENDING', 'IN_PROGRESS']:
            return Response({
                "message": "Verification already exists",
                "verification_link": existing_verification.verification_link,
                "qr_code_base64": existing_verification.verification_qr_code
            }, status=200)

        
        #  Validate email 
        
        if not customer.email:
            return Response({"error": "Customer email not found"}, status=400)


        
        #=========== Step 1: Get Access Token ===========


        # MetaMap credentials and flow
        client_id = settings.METAMAP_CLIENT_ID
        client_secret = settings.METAMAP_CLIENT_SECRET
        flow_id = settings.METAMAP_FLOW_ID


        token_url = "https://api.prod.metamap.com/oauth/"
        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret
        }
        try:
            token_response  = requests.post(token_url, json=token_payload, timeout=10)
            token_response .raise_for_status()
            token_data = token_response .json()
            access_token = token_data.get("access_token")
            if not access_token:
                return Response({"error": "Failed to retrieve access token"}, status=500)            
        except requests.RequestException as e:
            logger.error(f"MetaMap token request failed: {e}")
            return Response({"error": "MetaMap token request failed", "details": str(e)}, status=500)




        #=========== Step 2: Get Identity data ==============

        identity_url = "https://api.getmati.com/v2/identities"
        identity_payload = {
            "flowId": flow_id,
            "metadata": {"user_id": str(user_id), "email": customer.email}
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }        

        try:
            identity_response  = requests.post(identity_url, json=identity_payload, headers=headers, timeout=10)
            identity_response.raise_for_status()
            identity_data = identity_response.json()
            identity_id = identity_data.get("id")
            if not identity_id:
                return Response({"error": "Identity creation failed: no ID returned"}, status=500)            

        except requests.RequestException as e:
            logger.error(f"MetaMap identity request failed: {e}")
            return Response({"error": "MetaMap identity request failed", "details": str(e)}, status=500)


    # =============Step 3: Start Verification ===================

        verification_url = "https://api.getmati.com/v2/verifications"
        verification_payload = {
            "identityId": identity_id,
            "metadata": {"user_id": str(user_id)}
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        try:
            verification_response  = requests.post(verification_url, json=verification_payload, headers=headers,timeout=10)
            verification_response.raise_for_status()
            verification_data = verification_response.json()
            verification_id = verification_data.get("id")
            if not verification_id:
                return Response({"error": "Verification creation failed: no ID returned"}, status=500)            

        except requests.RequestException as e:
            logger.error(f"MetaMap verification request failed: {e}")
            return Response({"error": "MetaMap verification request failed", "details": str(e)}, status=500)


        
        #============== Step 4: Generate QR Code =================
        
        verification_link = f"https://verify.getmati.com/verify/{flow_id}/{identity_id}"

        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(verification_link)
        qr.make(fit=True)
        img = qr.make_image(fill="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()



       # ==============Step 5: Save or update in DB ==============



        verification, created = IdentityVerification.objects.get_or_create(
            customer=customer,
            defaults={
                "metamap_verification_id": identity_id,
                "verification_link": verification_link,
                "verification_qr_code": qr_code_base64,
                "biometric_status": "QR_GENERATED",
                "overall_status": "PENDING",
                "verification_link_expires_at": timezone.now() + timezone.timedelta(hours=24)
            }
        )
        if not created:
            verification.metamap_verification_id = identity_id
            verification.verification_link = verification_link
            verification.verification_qr_code = qr_code_base64
            verification.biometric_status = "QR_GENERATED"
            verification.verification_link_expires_at = timezone.now() + timezone.timedelta(hours=24)
            verification.save()


        return Response({
            "message": "Verification link and QR generated successfully",
            "identity_id": identity_id,
            "verification_id": verification_id,
            "verification_link": verification_link,
            "qr_code_base64": qr_code_base64
        }, status=status.HTTP_201_CREATED)



class MetaMapWebhookView(APIView):
    """
    Webhook endpoint to receive MetaMap verification results and update IdentityVerification.
    """
    def post(self, request):
        serializer = MetaMapWebhookSerializer(data=request.data.get("data", {}))
        if serializer.is_valid():
            data = serializer.validated_data
        else:
            return Response({"error": "Invalid webhook payload", "details": serializer.errors}, status=400)        

        identity_id = data.get("identityId")
        status_result = data.get("status")
        steps = data.get("steps", [])
        rejection_reason = data.get("rejection_reason", "")

        try:
            verification = IdentityVerification.objects.get(metamap_verification_id=identity_id)

            # Update status
            if status_result.lower() == "approved":
                verification.biometric_status = "COMPLETED"
            else:
                verification.biometric_status = "FAILED"

            # Extract face match score & liveness
            for step in steps:
                if step.get("name") == "selfie-check":
                    confidence = step.get("metadata", {}).get("confidence", 0)
                    verification.face_match_score = confidence * 100
                    verification.liveness_check_passed = step.get("result") == "approved"

                    selfie_url =step.get("metadata", {}).get("selfie_image_url")

                    # add document images

                    if selfie_url:
                        response = requests.get(selfie_url)
                        if response.status_code == 200:
                            verification.selfie_image.save(f"{identity_id}.jpg", ContentFile(response.content), save=False)

            # Minimum 85% confidence check
            if verification.face_match_score is not None and verification.face_match_score < 85:
                verification.overall_status = "REJECTED"
                verification.rejection_reason = rejection_reason or "Face match below 85%"
            else:
                verification.overall_status = "VERIFIED" if verification.biometric_status == "COMPLETED" else "REJECTED"
                verification.rejection_reason = rejection_reason if verification.overall_status == "REJECTED" else ""

            verification.verification_completed_at = timezone.now()    

            verification.biometric_verified_at = timezone.now()
            verification.save()

            return Response({"message": "Webhook processed successfully"}, status=200)

        except IdentityVerification.DoesNotExist:
            return Response({"error": "Verification not found"}, status=404)

        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            return Response({"error": str(e)}, status=500)

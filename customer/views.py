# Django Imports
from django.conf import settings
from django.utils import timezone
from django.core.files.base import ContentFile

# Django REST Framework Imports
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

# Local  Imports
from .models import IdentityVerification, Customer
from .serializers import (
     GenerateVerificationLinkSerializer, MetaMapWebhookSerializer,CustomerSerializer
     )

# Standard Library Imports
import base64
import logging
from io import BytesIO

# External Library Imports
import qrcode
import requests

# Logger Setup
logger = logging.getLogger(__name__)

# swagger settup
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

# permisions
from .permissions import IsAuthenticatedUser


# -------------------------------
# Generate Verification Link / QR
# -------------------------------


class GenerateVerificationLinkView(APIView):
    permission_classes=[IsAuthenticatedUser]
    """
    Generates a MetaMap verification link or QR code for the customer.
    """


    @swagger_auto_schema(
        operation_summary="Generate MetaMap verification link",
        operation_description="Generates a MetaMap verification link or QR code for a customer using their customer ID.",
        tags=["customer"], 
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['user_id'],
            properties={
                'user_id': openapi.Schema(type=openapi.TYPE_INTEGER, description='ID of the customer')
            }
        ),
        responses={
            201: openapi.Response(
                description="Verification link and QR generated successfully",
                examples={
                    "application/json": {
                        "message": "Verification link and QR generated successfully",
                        "identity_id": "abc123",
                        "verification_id": "def456",
                        "verification_link": "https://verify.getmati.com/verify/flow_id/identity_id",
                        "qr_code_base64": "base64string..."
                    }
                }
            ),
            400: "Invalid input",
            404: "Customer not found",
            500: "MetaMap API error"
        }
    )







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
    permission_classes=[]
    """
    Webhook endpoint to receive MetaMap verification results and update IdentityVerification.
    """



    @swagger_auto_schema(
        operation_summary="MetaMap webhook endpoint",
        operation_description="Receives verification results from MetaMap and updates the IdentityVerification model.",
        tags=["customer"],
        responses={
            200: openapi.Response(
                description="Webhook processed successfully",
                examples={
                    "application/json": {
                        "message": "Webhook processed successfully",
                        "overall_status": "VERIFIED",
                        "biometric_status": "COMPLETED",
                        "verification_completed_at": "2025-10-16T09:45:00Z"
                    }
                }
            ),
            400: "Invalid payload",
            404: "Verification not found",
            500: "Server error"
        }
    )



    def post(self, request):

            # --- webhook permission check -----
        token = request.headers.get("X-MetaMap-Token")
        if token != settings.METAMAP_WEBHOOK_SECRET:
            return Response({"error": "Unauthorized"}, status=401)

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

            # --Update status---
            if status_result.lower() == "approved":
                verification.biometric_status = "COMPLETED"
            else:
                verification.biometric_status = "FAILED"

            # ----Extract face match score & liveness----
            for step in steps:

                # ----selfie check----
                if step.get("name") == "selfie-check":
                    confidence = step.get("metadata", {}).get("confidence", 0)
                    verification.face_match_score = confidence * 100

                    verification.liveness_check_passed = step.get("result") == "approved"

                     # ---Minimum 85% confidence check---
                    if (verification.face_match_score is not None 
                        and verification.face_match_score < 85 
                        and verification.overall_status != "REJECTED"):

                        verification.overall_status = "REJECTED"
                        verification.rejection_reason = rejection_reason or "Face match below 85%"

                    

                    selfie_url =step.get("metadata", {}).get("selfie_image_url")

                    if selfie_url:
                        try:
                            response = requests.get(selfie_url, timeout=10)
                            response.raise_for_status()
                            verification.selfie_image.save(f"{identity_id}.jpg", ContentFile(response.content), save=False)
                        except requests.RequestException:
                            logger.warning(f"Failed to download selfie image for {identity_id}")


                    #---- document verification ----
                elif step.get("name") == "document-check":

                    if step.get("result") != "approved" and verification.overall_status != "REJECTED":
                        verification.overall_status = "REJECTED"
                        verification.rejection_reason = rejection_reason or "Document verification failed"


                    front_url = step.get("metadata", {}).get("front_image_url")
                    back_url = step.get("metadata", {}).get("back_image_url")
                    
                    if front_url:
                        try:
                            response = requests.get(front_url, timeout=10)
                            response.raise_for_status()
                            verification.document_front_image.save(f"{identity_id}_front.jpg", ContentFile(response.content), save=False)
                        except requests.RequestException:
                            logger.warning(f"Failed to download front document image for {identity_id}")
                    
                    if back_url:
                        try:
                            response = requests.get(back_url, timeout=10)
                            response.raise_for_status()
                            verification.document_back_image.save(f"{identity_id}_back.jpg", ContentFile(response.content), save=False)
                        except requests.RequestException:
                            logger.warning(f"Failed to download back document image for {identity_id}")


            

            if verification.overall_status != "REJECTED":
                verification.overall_status = "VERIFIED" if verification.biometric_status == "COMPLETED" else "REJECTED"
                verification.rejection_reason = "" if verification.overall_status == "VERIFIED" else rejection_reason


            verification.verification_completed_at = timezone.now()    

            verification.biometric_verified_at = timezone.now()
            verification.save()

            return Response({"message": "Webhook processed successfully"}, status=200)

        except IdentityVerification.DoesNotExist:
            return Response({"error": "Verification not found"}, status=404)

        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            return Response({"error": str(e)}, status=500)









# -------------------------------
#   customer creation View
# -------------------------------



class CustomerManagementView(APIView):
        
        permission_classes=[IsAuthenticatedUser]


        @swagger_auto_schema(
            operation_summary="Create a new customer",
            operation_description="Creates a new customer in the system. The authenticated user is automatically set as the creator.",
            tags=["customer"], 
            request_body=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                required=['document_number', 'document_type', 'first_name', 'last_name', 'email', 'phone_number'],
                properties={
                    'document_number': openapi.Schema(type=openapi.TYPE_STRING, description="ID card with hyphens (e.g., 8-123-456) or passport number"),
                    'document_type': openapi.Schema(type=openapi.TYPE_STRING, description="Type of document: PANAMA_ID, PASSPORT, FOREIGNER_ID"),
                    'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                    'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                    'email': openapi.Schema(type=openapi.TYPE_STRING, format='email'),
                    'phone_number': openapi.Schema(type=openapi.TYPE_STRING),
                }
            ),
            responses={
                201: openapi.Response(
                    description="Customer created successfully",
                    schema=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'document_number': openapi.Schema(type=openapi.TYPE_STRING),
                            'document_type': openapi.Schema(type=openapi.TYPE_STRING),
                            'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                            'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                            'email': openapi.Schema(type=openapi.TYPE_STRING, format='email'),
                            'phone_number': openapi.Schema(type=openapi.TYPE_STRING),
                            'status': openapi.Schema(type=openapi.TYPE_STRING),
                            'created_by': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'created_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                            'updated_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                        }
                    )
                ),
                400: "Validation error"
            }
        )


        def post(self, request):
            serializer = CustomerSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                customer = serializer.save()
                return Response(CustomerSerializer(customer).data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
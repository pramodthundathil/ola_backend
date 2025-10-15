import requests
from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import IdentityVerification, Customer
from .serializers import GenerateVerificationLinkSerializer, MetaMapWebhookSerializer



import qrcode
from io import BytesIO
import base64


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
            #  {"user_id": ["This field is required."]}
        

        try:
            customer = Customer.objects.get(id=user_id) 
        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)
            # {"error": "Customer not found"}


        # -----------------------------
        # Step 1.1: Get Access Token
        # -----------------------------
        token_url = "https://api.prod.metamap.com/oauth/"
        token_payload = {
            "client_id": settings.METAMAP_CLIENT_ID,
            "client_secret": settings.METAMAP_CLIENT_SECRET
        }
        try:
            response = requests.post(token_url, json=token_payload)
            token_data = response.json()
            access_token = token_data.get("access_token", "")
        except:
            access_token = "dummy-access-token"


        # MetaMap credentials and flow
        client_id = settings.METAMAP_CLIENT_ID
        client_secret = settings.METAMAP_CLIENT_SECRET
        flow_id = settings.METAMAP_FLOW_ID


        # -----------------------------
        # Step 1.1: Get Identity data
        # -----------------------------

        # Create MetaMap identity (using a sample API or placeholder)
        identity_url = "https://api.getmati.com/v2/identities"
        identity_payload = {
            "flowId": flow_id,
            "metadata": {"user_id": str(user_id), "email": customer.email}
        }
        # headers = {
        #     "Content-Type": "application/json",
        #     "Authorization": f"Basic {client_id}:{client_secret}"
        # }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }        


        # Send request to MetaMap (sample API, does not need to actually work)
        try:
            # response = requests.post(url, json=payload, headers=headers)
            response = requests.post(identity_url, json=identity_payload, headers=headers)
            identity_data = response.json() if response.status_code in [200, 201] else {}
            # data = response.json() if response.status_code == 201 else {}
        except:
            # If API fails, use dummy identityId
            # data = {"id": f"identity-dummy-{user_id}"}
            identity_data = {"id": f"identity-dummy-{user_id}"}

        # identity_id = data.get("id", f"identity-dummy-{user_id}")
        identity_id = identity_data.get("id", f"identity-dummy-{user_id}")

    # -----------------------------
    # Step 2: Start Verification
    # -----------------------------

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
            # response = requests.post(verification_url, json=verification_payload, headers=headers)
            response = requests.post(verification_url, json=verification_payload, headers=headers)
            verification_data = response.json() if response.status_code in [200, 201] else {}
        except:
            # Dummy verificationId for testing
            verification_data = {"id": f"verification-dummy-{user_id}"}

        verification_id = verification_data.get("id", f"verification-dummy-{user_id}")

        # -----------------------------
        # Step 1.4: Generate QR Code
        # -----------------------------
        
        verification_link = f"https://verify.getmati.com/verify/{flow_id}/{identity_id}"

        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(verification_link)
        qr.make(fit=True)
        img = qr.make_image(fill="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()


    # -----------------------------
    # Step 3: Save or update in DB
    # ----------------------------- 

        # Create or update IdentityVerification record
        verification, created = IdentityVerification.objects.get_or_create(
            customer=customer,
            defaults={
                "metamap_verification_id": identity_id,
                "verification_link": verification_link,
                "verification_qr_code": qr_code_base64,
                "biometric_status": "QR_GENERATED",
                "overall_status": "PENDING",
            }
        )
        if not created:
            verification.metamap_verification_id = identity_id
            verification.verification_link = verification_link
            verification.verification_qr_code = qr_code_base64
            verification.biometric_status = "QR_GENERATED"
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
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        identity_id = data.get("identityId")
        status_result = data.get("status")
        steps = data.get("steps", [])

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

            # Minimum 85% confidence check
            if verification.face_match_score is not None and verification.face_match_score < 85:
                verification.overall_status = "REJECTED"
            else:
                verification.overall_status = "VERIFIED" if verification.biometric_status == "COMPLETED" else "REJECTED"

            verification.biometric_verified_at = timezone.now()
            verification.save()

            return Response({"message": "Webhook processed successfully"}, status=200)

        except IdentityVerification.DoesNotExist:
            return Response({"error": "Verification not found"}, status=404)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

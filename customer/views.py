from django.shortcuts import render


import requests
from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from rest_framework import status

from .models import IdentityVerification


class GetMetaMapAccessToken(APIView):
    """
    API endpoint to request an access token from MetaMap.
    This token is required to create verification instances and send user data.
    """

    def post(self, request):
        # MetaMap OAuth endpoint
        url = "https://api.prod.metamap.com/oauth/"

        payload = {
            "client_id": settings.METAMAP_CLIENT_ID,
            "client_secret": settings.METAMAP_CLIENT_SECRET
        }

        try:
            response = requests.post(url, json=payload)
            response.raise_for_status() 

            return Response(response.json(), status=response.status_code)

        except requests.exceptions.RequestException as e:
            return Response(
                {"error": "Failed to get MetaMap access token", "details": str(e)},
                status=500
            )
        



class CreateMetaMapVerification(APIView):
    """
    Create a new verification instance for a user in MetaMap.
    Returns identityId which is used for sending user documents and biometrics.
    """

    def post(self, request):
        # Get user details from request (optional metadata)
        user_id = request.data.get("user_id")
        email = request.data.get("email")

        # MetaMap verification instance endpoint
        url = "https://api.prod.metamap.com/v2/verifications"

        access_token = request.data.get("access_token")  

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "metamap_id": settings.METAMAP_FLOW_ID,
            "metadata": {"user_id": user_id, "email": email}  # optional
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return Response(response.json(), status=response.status_code)

        except requests.exceptions.RequestException as e:
            return Response(
                {"error": "Failed to create MetaMap verification", "details": str(e)},
                status=500
            )


class SendMetaMapInputs(APIView):
    """
    Send user inputs (biometrics/documents) to MetaMap for verification.
    Example: Selfie image or document (id card, Passport, etc.)
    """

    def post(self, request):
        # Inputs from frontend
        identity_id = request.data.get("identity_id")  # from CreateMetaMapVerification
        access_token = request.data.get("access_token")
        selfie_file = request.FILES.get("selfie")  # file input (optional)
        document_file = request.FILES.get("document")  # file input (optional)

        if not identity_id or not access_token:
            return Response({"error": "identity_id and access_token required"}, status=400)

        url = f"https://api.prod.metamap.com/v2/identities/{identity_id}/send-input"

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        # Prepare multipart/form-data for file upload
        files = {}
        if selfie_file:
            files["selfie"] = selfie_file
        if document_file:
            files["document"] = document_file

        try:
            response = requests.post(url, files=files, headers=headers)
            response.raise_for_status()
            return Response(response.json(), status=response.status_code)

        except requests.exceptions.RequestException as e:
            return Response(
                {"error": "Failed to send inputs to MetaMap", "details": str(e)},
                status=500
            )




class MetaMapWebhookView(APIView):
    """
    Receives webhook callbacks from MetaMap after verification is completed.
    MetaMap sends verification status, confidence score, and other details.
    """

    def post(self, request):
        # The payload sent by MetaMap
        data = request.data

            # Example payload MetaMap sends:
            # {
            #   "identityId": "abc12345",
            #   "status": "verified",
            #   "confidence_score": 0.91,
            #   "steps": {
            #       "face_match": "success",
            #       "document_check": "success"
            #   },
            #   "timestamp": "2025-10-15T10:13:22Z"
            # }

        metamap_id = data.get("identityId")
        status = data.get("status")
        confidence = data.get("confidence_score", 0)
        steps = data.get("steps", {})    


        try:
            verification = IdentityVerification.objects.get(metamap_verification_id=metamap_id)
            verification.face_match_score = confidence * 100  
            verification.biometric_status = (
                "COMPLETED" if status == "verified" else "FAILED"
            )
            verification.overall_status = (
                "VERIFIED" if confidence >= 0.85 else "REJECTED"
            )
            verification.liveness_check_passed = steps.get("liveness_check") == "success"
            verification.biometric_verified_at = timezone.now()
            verification.save()

            return Response({"message": "MetaMap result updated successfully"}, status=200)

        except IdentityVerification.DoesNotExist:
            return Response({"error": "Verification not found"}, status=404)        






class GenerateVerificationLinkView(APIView):
    """
    API View to generate MetaMap verification link (QR Code URL)
    for a user's identity verification process.
    """

    def post(self, request):
        # Step 1: Collect the required inputs
        user_id = request.data.get("user_id")

        if not user_id:
            return Response({"error": "user_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Step 2: Define MetaMap credentials and flow details
        client_id = settings.METAMAP_CLIENT_ID
        client_secret = settings.METAMAP_CLIENT_SECRET
        flow_id = settings.METAMAP_FLOW_ID

        # Step 3: Prepare API endpoint and headers
        url = f"https://api.getmati.com/v2/identities"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {client_id}:{client_secret}"
        }

        # Step 4: Create a new MetaMap identity for this user
        body = {
            "flowId": flow_id,
            "metadata": {
                "user_id": str(user_id)
            }
        }

        response = requests.post(url, json=body, headers=headers)

        if response.status_code == 201:
            data = response.json()
            identity_id = data.get("id")
            verification_link = f"https://verify.getmati.com/verify/{flow_id}/{identity_id}"

            # Step 5: Save or update IdentityVerification record
            verification, created = IdentityVerification.objects.get_or_create(
                user_id=user_id,
                defaults={
                    "metamap_verification_id": identity_id,
                    "verification_qr_code": verification_link,
                    "overall_status": "PENDING",
                }
            )

            if not created:
                # Update existing record with latest link
                verification.metamap_verification_id = identity_id
                verification.verification_qr_code = verification_link
                verification.save()

            # Step 6: Send success response
            return Response(
                {
                    "message": "Verification link generated successfully",
                    "verification_link": verification_link,
                    "identity_id": identity_id,
                },
                status=status.HTTP_201_CREATED
            )

        else:
            return Response(
                {
                    "error": "Failed to generate verification link",
                    "details": response.text,
                },
                status=response.status_code
            )

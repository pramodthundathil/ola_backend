# Django Imports
from django.conf import settings
from django.utils import timezone


# Django REST Framework Imports
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

# Local  Imports
from .models import Customer,CreditScore
from .serializers import (
     CustomerSerializer,
     CreditScoreSerializer,
     )
from .utils import fetch_credit_score_from_experian

# Standard Library Imports
import logging

# External Library Imports
import requests

# Logger Setup
logger = logging.getLogger(__name__)

# swagger settup
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

# permisions
from .permissions import IsAuthenticatedUser






# ============================================
#   customer creation View
# ============================================



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




# =================================
# CREDIT SCORE CHECK VIEW
# =================================



class CreditScoreCheckAPIView(APIView):
    permission_classes=[IsAuthenticatedUser]
    """Check a customer's credit score (cached or Experian)."""

    @swagger_auto_schema(
        operation_summary="Check Customer Credit Score",
        operation_description="Fetches a customer's credit score. Returns cached score if available and valid; otherwise fetches a new score from Experian and stores it.",
        responses={
            200: openapi.Response(
                description="Credit score fetched successfully",
                examples={
                    "application/json": {
                        "source": "cache",
                        "credit_score": {
                            "customer": {
                                "id": 1,
                                "first_name": "John",
                                "last_name": "Doe",
                                "email": "john.doe@example.com",
                            },
                            "apc_score": 520,
                            "apc_consultation_id": "ABC123",
                            "apc_status": "APPROVED",
                            "internal_score": 85,
                            "max_installment_capacity": 15000.00,
                            "payment_capacity_status": "SUFFICIENT",
                            "final_credit_status": "APPROVED",
                            "score_valid_until": "2025-11-16T14:30:00Z",
                            "consulted_by": 2
                        }
                    }
                }
            ),
            404: openapi.Response(
                description="Customer not found",
                examples={"application/json": {"error": "Customer not found"}}
            ),
            500: openapi.Response(
                description="Failed to fetch credit score from Experian",
                examples={"application/json": {"error": "Failed to fetch credit score from Experian"}}
            ),
        },
        manual_parameters=[
            openapi.Parameter(
                name='customer_id',
                in_=openapi.IN_PATH,
                type=openapi.TYPE_INTEGER,
                description='ID of the customer to fetch credit score for',
                required=True
            ),
        ],
        tags=['customer']
    )




    def get(self, request, customer_id):
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

        # 1️= Check if recent score exists (within 30 days)
        latest_score = customer.get_latest_credit_score()
        if latest_score:
            serializer = CreditScoreSerializer(latest_score)
            return Response({"source": "cache", "credit_score": serializer.data})

        # 2️= Fetch new score from Experian
        experian_data = fetch_credit_score_from_experian(customer)
        if not experian_data:
            return Response({"error": "Failed to fetch credit score from Experian"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 3️= Save new score in DB

        # Check if the credit score with same consultation ID exists
        credit_score = CreditScore.objects.filter(
            customer=customer,
            apc_consultation_id=experian_data["apc_consultation_id"]
        ).first()

        if credit_score:
            # Update existing record
            credit_score.apc_score = experian_data["apc_score"]
            credit_score.apc_status = experian_data["apc_status"]
            credit_score.score_valid_until = experian_data["score_valid_until"]

            credit_score.save()

        else:
            credit_score = CreditScore(
            customer=customer,
            apc_score=experian_data["apc_score"],
            apc_consultation_id=experian_data["apc_consultation_id"],
            apc_status=experian_data["apc_status"],
            score_valid_until=experian_data["score_valid_until"],
            )
            credit_score.save()

        serializer = CreditScoreSerializer(credit_score)
        return Response({"source": "experian", "credit_score": serializer.data})



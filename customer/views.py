# Django Imports
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.cache import cache


# Django REST Framework Imports
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status


# Local  Imports
from .models import ( Customer,CreditScore,
                     CreditConfig,PersonalReference,
                     CustomerIncomeFile,CustomerIncome,
                     )
from .serializers import (
     CustomerSerializer,
     CreditScoreSerializer,
     CustomerStatusSerializer,
     CreditConfigSerializer,
     PersonalReferenceSerializer,
     CustomerIncomeFileSerializer,
     )
from .utils import fetch_credit_score_from_experian
from .sms_utils import send_sms

# Standard Library Imports
import logging
import random


# External Library Imports
import requests

# Logger Setup
logger = logging.getLogger(__name__)

# swagger settup
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

# permisions
from .permissions import IsAuthenticatedUser
from products.permissions import IsAdminOrGlobalManager


from rest_framework.pagination import PageNumberPagination
from django.db.models import Q


import os
import sqlite3
import pandas as pd
from django.conf import settings
  

# ============================================
#   customer creation View
# ============================================



# ============= Pagination Settings===============

class CustomerPagination(PageNumberPagination):
    """Custom pagination settings"""
    page_size = 10  # Default per page
    page_size_query_param = 'page_size'
    max_page_size = 100



class CustomerManagementView(APIView):
        
        permission_classes=[IsAuthenticatedUser]


        # ---------- GET ----------

        pagination_class = CustomerPagination

        @swagger_auto_schema(
            operation_summary="Retrieve customers",
            operation_description="""
            GET /api/customers/manage/ → Retrieve all customers (paginated)
            GET /api/customers/manage/?search=<query> → Search by first name, last name, email, or document number (paginated)
            GET /api/customers/manage/?id=<id> → Retrieve single customer by ID
            """,
            tags=["customer"],
            manual_parameters=[
                openapi.Parameter(
                    'id', openapi.IN_QUERY,
                    description='Customer ID to retrieve a single customer',
                    type=openapi.TYPE_INTEGER
                ),
                openapi.Parameter(
                    'search', openapi.IN_QUERY,
                    description='Search term for first name, last name, email, or document number',
                    type=openapi.TYPE_STRING
                ),
                openapi.Parameter(
                    'page', openapi.IN_QUERY,
                    description='Page number for pagination',
                    type=openapi.TYPE_INTEGER
                ),
                openapi.Parameter(
                    'page_size', openapi.IN_QUERY,
                    description='Number of results per page',
                    type=openapi.TYPE_INTEGER
                ),
            ],
            responses={
                200: openapi.Response(
                    description="Customer data retrieved successfully",
                    schema=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'count': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'next': openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_URI, nullable=True),
                            'previous': openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_URI, nullable=True),
                            'results': openapi.Schema(
                                type=openapi.TYPE_ARRAY,
                                items=openapi.Schema(
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
                                        'created_by': openapi.Schema(type=openapi.TYPE_INTEGER, nullable=True),
                                        'created_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                                        'updated_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                                    }
                                )
                            )
                        }
                    )
                ),
                404: "Customer not found",
            }
        )

        def get(self, request):
            """
            Handles:
            - GET /api/customers/ → list (paginated)
            - GET /api/customers/?search=John → search by name/email/document
            - GET /api/customers/?id=<id> → get individual customer
            """
            customer_id = request.query_params.get('id')
            search_query = request.query_params.get('search', '').strip()

            # Base queryset
            queryset = Customer.objects.all().order_by('-created_at')

            # ---- SINGLE CUSTOMER ----
            if customer_id:
                customer = (
                    queryset
                    .prefetch_related(
                        "credit_applications__finance_plan__device__credithistory"
                    )
                    .filter(id=customer_id)
                    .first()
                )

                if not customer:
                    return Response({
                        "status": "error",
                        "message": "Customer not found",
                        "data": None
                    }, status=status.HTTP_404_NOT_FOUND)

                serializer = CustomerSerializer(customer)
                return Response({
                    "status": "success",
                    "message": "Data fetched successfully.",
                    "data": serializer.data
                }, status=status.HTTP_200_OK)


            # ---- LIST / SEARCH ----
            if search_query:
                queryset = queryset.filter(
                    Q(first_name__icontains=search_query) |
                    Q(last_name__icontains=search_query) |
                    Q(email__icontains=search_query) |
                    Q(document_number__icontains=search_query) |
                    Q(phone_number__icontains=search_query)
                )

            queryset = queryset.prefetch_related(
                "credit_applications__finance_plan__device__credithistory"
            )

            paginator = self.pagination_class()
            paginated_qs = paginator.paginate_queryset(queryset, request)
            serializer = CustomerSerializer(paginated_qs, many=True)

            paginated_response = paginator.get_paginated_response(serializer.data)
            paginated_data = paginated_response.data

            return Response({
                "status": "success",
                "message": "Customer list fetched successfully.",
                "data": paginated_data
            }, status=status.HTTP_200_OK)
        
        # ---------POST METHOD-----------------

        @swagger_auto_schema(
            operation_summary="Create or fetch a customer by document details",
            operation_description="""
            Creates a new customer if not existing, using only `document_type` and `document_number`.
            If a customer with the same document already exists, returns that existing record instead.
            
            **Frontend Workflow**
            - If `newly_created_customer = true` → open page to fill remaining details.
            - If `newly_created_customer = false` → customer already exists, skip additional steps.
            """,
            tags=["customer"],
            request_body=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                required=['document_type', 'document_number'],
                properties={
                    'document_type': openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Document type: PANAMA_ID, PASSPORT, FOREIGNER_ID"
                    ),
                    'document_number': openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="Customer document number (e.g., 8-123-456)"
                    ),
                }
            ),
            responses={
                200: openapi.Response(
                    description="Customer already exists",
                    schema=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'status': openapi.Schema(type=openapi.TYPE_STRING, example='success'),
                            'message': openapi.Schema(type=openapi.TYPE_STRING, example='Customer already exists.'),
                            'newly_created_customer': openapi.Schema(type=openapi.TYPE_BOOLEAN, example=False),
                            'data': openapi.Schema(
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
                                    'created_at': openapi.Schema(type=openapi.TYPE_STRING, format='date-time'),
                                    'updated_at': openapi.Schema(type=openapi.TYPE_STRING, format='date-time'),
                                }
                            )
                        }
                    )
                ),
                201: openapi.Response(
                    description="Customer created successfully",
                    schema=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'status': openapi.Schema(type=openapi.TYPE_STRING, example='success'),
                            'message': openapi.Schema(type=openapi.TYPE_STRING, example='Customer created successfully.'),
                            'newly_created_customer': openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                            'data': openapi.Schema(
                                type=openapi.TYPE_OBJECT,
                                properties={
                                    'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                    'document_number': openapi.Schema(type=openapi.TYPE_STRING),
                                    'document_type': openapi.Schema(type=openapi.TYPE_STRING),
                                    'status': openapi.Schema(type=openapi.TYPE_STRING),
                                    'created_by': openapi.Schema(type=openapi.TYPE_INTEGER),
                                    'created_at': openapi.Schema(type=openapi.TYPE_STRING, format='date-time'),
                                    'updated_at': openapi.Schema(type=openapi.TYPE_STRING, format='date-time'),
                                }
                            )
                        }
                    )
                ),
                400: "Validation error"
            }
        )


        def post(self, request):
            document_type = request.data.get("document_type")
            document_number = request.data.get("document_number")

            if not document_type or not document_number:
                return Response({
                    "status": "error",
                    "message": "Both document_type and document_number are required.",
                    "data": None
                }, status=status.HTTP_400_BAD_REQUEST)

            # check if customer already exists
            existing_customer = Customer.objects.filter(
                document_type=document_type,
                document_number=document_number
            ).first()

            if existing_customer:
                existing_customer.otp_verified=False
                existing_customer.save(update_fields=["otp_verified"])
                newly_created = False
                customer = existing_customer

            else:
                serializer = CustomerSerializer(data={
                    "document_type": document_type,
                    "document_number": document_number
                }, context={'request': request})

                if not serializer.is_valid():
                    return Response({
                    "status": "error",
                    "message": "Validation failed.",
                    "data": serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

                customer = serializer.save()
                newly_created = True


            # ---------- CREDIT SCORE LOGIC ----------
            credit_view = CreditScoreCheckAPIView()
            credit_response = credit_view.get(request, customer.id)
            credit_data = credit_response.data

            credit_score = credit_data.get("data", {}).get("credit_score", {})
            source = credit_data.get("data", {}).get("source", "experian")

            return Response({
                "status": "success",
                "message": "Customer created successfully." if newly_created else "Customer already exists.",
                "newly_created_customer": newly_created,
                "data": CustomerSerializer(customer).data,
                "credit_score": {
                    "id": credit_score.get("id"),
                    "source": source,
                    "customer": (
                        credit_score.get("customer", {}).get("id")
                        if isinstance(credit_score.get("customer"), dict)
                        else credit_score.get("customer")
                    ),
                    "apc_score": credit_score.get("apc_score"),
                    "apc_score_date": credit_score.get("apc_score_date"),
                    "apc_consultation_id": credit_score.get("apc_consultation_id"),
                    "apc_status": credit_score.get("apc_status"),
                    "good_payment_history_points": credit_score.get("good_payment_history_points"),
                    "delinquency_penalty_points": credit_score.get("delinquency_penalty_points"),
                    "number_of_previous_loans": credit_score.get("number_of_previous_loans"),
                    "payment_capacity_status": credit_score.get("payment_capacity_status"),
                    "final_credit_status": credit_score.get("final_credit_status"),
                    "score_valid_until": credit_score.get("score_valid_until"),
                    "is_expired": credit_score.get("is_expired"),
                    "verbal_authorization_given": credit_score.get("verbal_authorization_given"),
                    "consulted_by": credit_score.get("consulted_by"),
                    "created_at": credit_score.get("created_at"),
                    "updated_at": credit_score.get("updated_at"),
                }
            }, status=status.HTTP_201_CREATED if newly_created else status.HTTP_200_OK)    

        # ---------- PATCH ----------
        @swagger_auto_schema(
            operation_summary="Update a customer (with OTP verification if provided)",
            operation_description="""
            Partially updates a customer by ID.

            - Provide the `id` query parameter to specify which customer to update.
            - Optionally include `phone_number` and `otp` to verify the customer's phone before saving updates.
            - If the OTP is valid, the customer's `otp_verified` field will be set to `true`.

            **Example Flow (Frontend):**
            1. User enters phone → clicks "Generate OTP" (calls `/customer/generate-otp/`)
            2. User enters OTP + fills details → clicks "Verify & Submit"
            3. This endpoint verifies OTP + updates customer data in one step.

            Example:
            PATCH /v1/customer/manage/?id=3
            """,
            tags=["customer"],
            manual_parameters=[
                openapi.Parameter(
                    'id', openapi.IN_QUERY,
                    description='Customer ID to update',
                    type=openapi.TYPE_INTEGER,
                    required=True
                )
            ],
            request_body=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'document_number': openapi.Schema(type=openapi.TYPE_STRING),
                    'document_type': openapi.Schema(type=openapi.TYPE_STRING),
                    'latitude': openapi.Schema(type=openapi.TYPE_NUMBER, format=openapi.FORMAT_FLOAT),
                    'longitude': openapi.Schema(type=openapi.TYPE_NUMBER, format=openapi.FORMAT_FLOAT),
                    'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                    'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                    'email': openapi.Schema(type=openapi.TYPE_STRING, format='email'),
                    'phone_number': openapi.Schema(type=openapi.TYPE_STRING),
                    'otp': openapi.Schema(
                        type=openapi.TYPE_STRING,
                        description="6-digit OTP for phone verification (optional)"
                    ),
                    'status': openapi.Schema(type=openapi.TYPE_STRING),
                },
                example={
                    "phone_number": "+50761234567",
                    "otp": "123456",
                    "first_name": "first_name",
                    "last_name": "last name",
                    "email": "customer@example.com"
                }
            ),
            responses={
                200: openapi.Response(
                    description="Customer updated successfully",
                    schema=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            'status': openapi.Schema(type=openapi.TYPE_STRING, example="success"),
                            'message': openapi.Schema(type=openapi.TYPE_STRING, example="Customer updated successfully."),
                            'data': openapi.Schema(
                                type=openapi.TYPE_OBJECT,
                                properties={
                                    'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                    'document_number': openapi.Schema(type=openapi.TYPE_STRING),
                                    'document_type': openapi.Schema(type=openapi.TYPE_STRING),
                                    'first_name': openapi.Schema(type=openapi.TYPE_STRING),
                                    'last_name': openapi.Schema(type=openapi.TYPE_STRING),
                                    'email': openapi.Schema(type=openapi.TYPE_STRING, format='email'),
                                    'phone_number': openapi.Schema(type=openapi.TYPE_STRING),
                                    'otp_verified': openapi.Schema(type=openapi.TYPE_BOOLEAN, example=True),
                                    'status': openapi.Schema(type=openapi.TYPE_STRING),
                                    'created_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                                    'updated_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                                }
                            )
                        }
                    )
                ),
                400: "Validation error or Invalid OTP",
                404: "Customer not found",
            }
        )
        def patch(self, request):
            """
            verify otp
            Partially update a customer by ID.
            Example:
            PATCH /v1/customer/manage/?id=3
            """
            customer_id = request.query_params.get('id') 
            if not customer_id:
                return Response({
                    "status": "error",
                    "message": "Customer ID is required.",
                    "data": None
                }, status=status.HTTP_400_BAD_REQUEST)


            try:
                customer = Customer.objects.get(id=customer_id)
            except Customer.DoesNotExist:
                return Response({
                    "status": "error",
                    "message": "Customer not found.",
                    "data": None
                }, status=status.HTTP_404_NOT_FOUND)
            
                # ---- Optional OTP Verification ----
            phone = request.data.get("phone_number")
            otp = request.data.get("otp")
            if not otp:
                return Response({
                    "status": "error",
                    "message": "OTP is requierd.",
                },status=status.HTTP_400_BAD_REQUEST) 

            if otp and phone:
                cached_otp = cache.get(f"otp_{phone}")
                if str(cached_otp) != str(otp):
                    return Response({
                        "status": "error",
                        "message": "Invalid or expired OTP.",
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # OTP verified
                cache.delete(f"otp_{phone}")
                customer.otp_verified = True
                customer.save(update_fields=["otp_verified"])


            serializer = CustomerSerializer(customer, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                updated_customer = serializer.save()
                return Response({
                    "status": "success",
                    "message": "Customer updated successfully.",
                    "data": CustomerSerializer(updated_customer).data
                }, status=status.HTTP_200_OK)

            return Response({
                "status": "error",
                "message": "Validation failed.",
                "data": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)


        # ---------- DELETE ----------
        @swagger_auto_schema(
            operation_summary="Delete a customer",
            operation_description="Deletes a customer by ID. Provide the `id` query parameter.",
            tags=["customer"],
            manual_parameters=[
                openapi.Parameter(
                    'id', openapi.IN_QUERY,
                    description='Customer ID to delete',
                    type=openapi.TYPE_INTEGER,
                    required=True
                )
            ],
            responses={
                204: "Customer deleted successfully",
                404: "Customer not found",
            }
        )
        def delete(self, request):
            """
            Delete a customer by ID.
            Example:
            DELETE /v1/customer/manage/?id=3
            """
            customer_id = request.query_params.get('id') 
            if not customer_id:
                return Response({
                    "status": "error",
                    "message": "Customer ID is required.",
                    "data": None
                }, status=status.HTTP_400_BAD_REQUEST)


            try:
                customer = Customer.objects.get(id=customer_id)
                customer.delete()
                return Response({
                    "status": "success",
                    "message": "Customer deleted successfully.",
                    "data": None
                }, status=status.HTTP_200_OK)

            except Customer.DoesNotExist:
                return Response({
                    "status": "error",
                    "message": "Customer not found.",
                    "data": None
                }, status=status.HTTP_404_NOT_FOUND)


# ========================================================
# VIEW FOR UPDATE CUSTOMER STATUS (BLOCK/UNBLOCK/INACTIVE)
# ========================================================

class CustomerStatusUpdateView(APIView):
    """
    Update the status of a customer (ACTIVE, INACTIVE, BLOCKED)
    """

    permission_classes = [IsAuthenticatedUser]  

    # --------- PATCH METHOD -----------------

    @swagger_auto_schema(
        operation_summary="Update customer status (ACTIVE, INACTIVE, BLOCKED)",
        operation_description="Updates a customer's status by providing the `id` query parameter and the new `status` in the request body.",
        tags=["customer"],
        manual_parameters=[
            openapi.Parameter(
                'id', openapi.IN_QUERY,
                description='Customer ID to update',
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['status'],
            properties={
                'status': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='New status for the customer (ACTIVE, INACTIVE, BLOCKED)'
                )
            }
        ),
        responses={
            200: openapi.Response(
                description="Customer status updated successfully",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'status': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                ),
                examples={
                    "application/json": {
                        "id": 3,
                        "status": "ACTIVE"
                    }
                }
            ),
            400: "Validation error",
            404: "Customer not found",
        }
    )
    def patch(self, request):
        customer_id = request.query_params.get('id')
        if not customer_id:
            return Response({
                "status": "error",
                "message": "Customer ID is required.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Customer not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)


        serializer = CustomerStatusSerializer(customer, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "status": "success",
                "message": "Customer status updated successfully.",
                "data": {
                    "id": customer.id,
                    "status": serializer.data['status']
                }
            }, status=status.HTTP_200_OK)

        return Response({
            "status": "error",
            "message": "Validation failed.",
            "data": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)



# =================================
# CREDIT SCORE CHECK VIEW
# =================================


class CreditScoreCheckAPIView(APIView):
    permission_classes=[IsAuthenticatedUser]
    """Check a customer's credit score (cached or Experian)."""

    # --------------- GET METHOD ---------------------

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
                examples={"application/json": {"detail": "Customer not found"}}
            ),
            500: openapi.Response(
                description="Failed to fetch credit score from Experian",
                examples={"application/json": {"detail": "Failed to fetch credit score from Experian"}}
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
        tags=['credit']
    )

    def get(self, request, customer_id):
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Customer not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        # 1️= Check if recent score exists (within 30 days)
        latest_score = customer.get_latest_credit_score()
        if latest_score:
            logger.info(f"[CreditScoreCheck] Returning cached score for customer {customer.id}")
            serializer = CreditScoreSerializer(latest_score)
            return Response({
                "status": "success",
                "message": "Cached credit score retrieved successfully.",
                "data": {
                    "source": "cache",
                    "credit_score": serializer.data
                }
            }, status=status.HTTP_200_OK)

        

        # 2️= Fetch new score from Experian
        logger.info(f"Fetched new score from Experian for customer {customer.id}") 
        experian_data = fetch_credit_score_from_experian(customer)
        
        if not experian_data:
            return Response({
                "status": "error",
                "message": "Failed to fetch credit score from Experian.",
                "data": None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
            # credit_score.apc_status='APPROVED'
            credit_score.score_valid_until = experian_data["score_valid_until"]

            credit_score.save()
            logger.info(f"[CreditScoreUpdated] Customer {customer.id} score updated: {credit_score.apc_score}")


        else:
            
            credit_score = CreditScore(
            customer=customer,
            apc_score=experian_data["apc_score"],
            apc_consultation_id=experian_data["apc_consultation_id"],
            apc_status=experian_data["apc_status"],
            score_valid_until=experian_data["score_valid_until"],
            )
            
            credit_score.save()
            

        if request.user.is_authenticated:
            credit_score.consulted_by = request.user
            credit_score.save()    

        if not credit_score.check_apc_approval():
            return Response({
                "status": "error",
                "message": "Credit score too low. Application rejected.",
                "data": {
                    "credit_score": CreditScoreSerializer(credit_score).data
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = CreditScoreSerializer(credit_score)
        return Response({
            "status": "success",
            "message": "Credit score fetched successfully from Experian.",
            "data": {
                "source": "experian",
                "credit_score": serializer.data
            }
        }, status=status.HTTP_200_OK)


# ==============================================
# CREDIT CONFIG GET VIEW (VIEW THRESHOLD VALUES)
# =============================================


class CreditConfigGetAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]
    """
     for view minimum value of Tier A,Tier B,Tier C 
    """

    # -----------GET METHOD --------------------

    @swagger_auto_schema(
        operation_summary="Get current APC tier thresholds",
        operation_description="Fetch the current tier configuration (A, B, C).",
        responses={
            200: openapi.Response(
                description="Current APC tier thresholds fetched successfully",
                examples={
                    "application/json": {
                        "id": 1,
                        "tier_a_min_score": 600,
                        "tier_b_min_score": 550,
                        "tier_c_min_score": 500,
                        "updated_at": "2025-10-20T14:30:00Z",
                        "created_at": "2025-10-15T10:00:00Z"
                    }
                },
            ),
            404: openapi.Response(
                description="Configuration not found",
                examples={"application/json": {"detail": "No configuration found"}},
            ),
        },
        tags=["credit"],
    )
    def get(self, request):
        config = CreditConfig.objects.first()
        if not config:
            return Response({
                "status": "error",
                "message": "No configuration found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = CreditConfigSerializer(config)
        return Response({
            "status": "success",
            "message": "Credit configuration fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)


# ==============================================
# CREDIT CONFIG CHANGE VIEW (SET THRESHOLD VALUE)
# =============================================


class CreditConfigChangeAPIView(APIView):
    permission_classes = [IsAdminOrGlobalManager]
    """
     for add and update credit configs (min value of Tier A,Tier B,Tier C)
    """

    # ---------- POST METHOD ---------------

    @swagger_auto_schema(
        operation_summary="Create APC tier configuration",
        operation_description="Create a new tier configuration (A, B, C). Only one allowed.",
        request_body=CreditConfigSerializer,
        responses={
            201: openapi.Response(
                description="Configuration created successfully",
                examples={
                    "application/json": {
                        "id": 1,
                        "tier_a_min_score": 600,
                        "tier_b_min_score": 550,
                        "tier_c_min_score": 500
                    }
                },
            ),
            400: openapi.Response(
                description="Already exists or validation error",
                examples={"application/json": {"detail": "CreditConfig already exists. Only one row allowed."}},
            ),
        },
        tags=["credit"],
    )

    def post(self, request):
            if CreditConfig.objects.exists():
                return Response({
                    "status": "error",
                    "message": "CreditConfig already exists. Only one row allowed.",
                    "data": None
                }, status=status.HTTP_400_BAD_REQUEST)


            serializer = CreditConfigSerializer(data=request.data)
            if serializer.is_valid():
                try:
                    serializer.save()
                    return Response({
                        "status": "success",
                        "message": "Credit configuration created successfully.",
                        "data": serializer.data
                    }, status=status.HTTP_201_CREATED)
                except ValidationError as e:
                    # Catch model clean() validation error here
                    message = (
                        e.message_dict.get("__all__")[0]
                        if hasattr(e, "message_dict") and "__all__" in e.message_dict
                        else str(e)
                    )
                    return Response({
                        "status": "error",
                        "message": message,
                        "data": None
                    }, status=status.HTTP_400_BAD_REQUEST)

            return Response({
                "status": "error",
                "message": "Validation failed.",
                "data": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

    # ---------- PATCH METHOD --------------
    @swagger_auto_schema(
        operation_summary="Update APC tier thresholds",
        operation_description="Update existing APC tier thresholds (A, B, C).",
        request_body=CreditConfigSerializer,
        responses={
            200: openapi.Response(
                description="Thresholds updated successfully",
                examples={
                    "application/json": {
                        "id": 1,
                        "tier_a_min_score": 620,
                        "tier_b_min_score": 560,
                        "tier_c_min_score": 510,
                    }
                },
            ),
        },
        tags=["credit"],
    )

    def patch(self, request):
        config = CreditConfig.objects.first()
        if not config:
            return Response({
                "status": "error",
                "message": "No configuration found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)


        serializer = CreditConfigSerializer(config, data=request.data, partial=True)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response({
                    "status": "success",
                    "message": "Credit configuration updated successfully.",
                    "data": serializer.data
                }, status=status.HTTP_200_OK)
            except ValidationError as e:
                message = (
                    e.message_dict.get("__all__")[0]
                    if hasattr(e, "message_dict") and "__all__" in e.message_dict
                    else str(e)
                )
                return Response({
                    "status": "error",
                    "message": message,
                    "data": None
                }, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "status": "error",
            "message": "Validation failed.",
            "data": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)



# =====================================================
#  PERSONAL REFERENCE LIST + CREATE
# =====================================================

class PersonalReferenceListCreateAPIView(APIView):
    """
    Handles listing and creating personal references for a specific customer.
    """
    permission_classes = [IsAuthenticatedUser]

    # --------- GET METHOD -----------------

    @swagger_auto_schema(
        operation_summary="List all personal references of a customer",
        operation_description="Fetch all personal references by providing a customer ID.",
        manual_parameters=[
            openapi.Parameter(
                'customer_id',
                openapi.IN_PATH,
                description="Customer ID to fetch personal references for",
                type=openapi.TYPE_INTEGER
            )
        ],
        responses={
            200: openapi.Response(
                description="List of personal references for a given customer",
                examples={
                    "application/json": [
                        {
                            "id": 1,
                            "customer": 12,
                            "name": "John Doe",
                            "relationship": "Friend",
                            "phone": "+91-9876543210",
                            "address": "Bangalore, India"
                        }
                    ]
                }
            ),
            404: openapi.Response(
                description="Customer not found",
                examples={"application/json": {"detail": "Customer not found"}}
            )
        },
        tags=['personal-reference']
    )
    def get(self, request, customer_id):
        """
        Returns all personal references for a given customer.
        """
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Customer not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        references = PersonalReference.objects.filter(customer=customer)
        serializer = PersonalReferenceSerializer(references, many=True)
        return Response({
            "status": "success",
            "message": "Data fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
#    ------------- POST METHOD ---------------

    @swagger_auto_schema(
        operation_summary="Create a new personal reference",
        operation_description="Create a new personal reference entry for a specific customer.",
        manual_parameters=[
            openapi.Parameter(
                'customer_id',
                openapi.IN_PATH,
                description="Customer ID for whom the reference is being created",
                type=openapi.TYPE_INTEGER
            )
        ],
        request_body=PersonalReferenceSerializer,
        responses={
            201: openapi.Response(
                description="Personal reference created successfully",
                examples={
                    "application/json": {
                        "id": 2,
                        "customer": 12,
                        "name": "Jane Smith",
                        "relationship": "Colleague",
                        "phone": "+91-8888888888",
                        "address": "Hyderabad, India"
                    }
                }
            ),
            400: openapi.Response(
                description="Validation error",
                examples={"application/json": {"name": ["This field is required."]}}
            ),
            404: openapi.Response(
                description="Customer not found",
                examples={"application/json": {"detail": "Customer not found"}}
            ),
        },
        tags=['personal-reference']
    )
    def post(self, request, customer_id):
        """
        Creates a personal reference linked to the specified customer.
        """
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Customer not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = PersonalReferenceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(customer=customer)
            return Response({
                "status": "success",
                "message": "Personal reference created successfully.",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            "status": "error",
            "message": "Validation failed.",
            "data": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)



# =====================================================
#  PERSONAL REFERENCE DETAIL (GET / PATCH / DELETE)
# =====================================================

class PersonalReferenceDetailAPIView(APIView):
    """
    Retrieve, update, or delete a personal reference by its ID.
    """
    permission_classes = [IsAuthenticatedUser]

    def get_object(self, pk):
        try:
            return PersonalReference.objects.get(id=pk)
        except PersonalReference.DoesNotExist:
            return None
        
    # --------------- GET METHOD -------------------    

    @swagger_auto_schema(
        operation_summary="Retrieve a personal reference by ID",
        operation_description="Get details of a single personal reference using its ID.",
        responses={
            200: openapi.Response(
                description="Personal reference details",
                examples={
                    "application/json": {
                        "id": 5,
                        "customer": 12,
                        "name": "Amit Verma",
                        "relationship": "Brother",
                        "phone": "+91-9999999999",
                        "address": "Delhi, India"
                    }
                }
            ),
            404: openapi.Response(
                description="Reference not found",
                examples={"application/json": {"detail": "Reference not found"}}
            )
        },
        tags=['personal-reference']
    )
    def get(self, request, pk):
        reference = self.get_object(pk)
        if not reference:
            return Response({
                "status": "error",
                "message": "Reference not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)
        serializer = PersonalReferenceSerializer(reference)
        return Response({
            "status": "success",
            "message": "Reference fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    # ------------- PATCH METHOD --------------------

    @swagger_auto_schema(
        operation_summary="Update an existing personal reference",
        operation_description="Partially update personal reference fields (PATCH).",
        request_body=PersonalReferenceSerializer,
        responses={
            200: openapi.Response(
                description="Reference updated successfully",
                examples={
                    "application/json": {
                        "id": 5,
                        "customer": 12,
                        "name": "Amit Verma",
                        "relationship": "Brother",
                        "phone": "+91-9000000000",
                        "address": "Updated address"
                    }
                }
            ),
            400: openapi.Response(
                description="Validation error",
                examples={"application/json": {"phone": ["Invalid format."]}}
            ),
            404: openapi.Response(
                description="Reference not found",
                examples={"application/json": {"detail": "Reference not found"}}
            )
        },
        tags=['personal-reference']
    )
    def patch(self, request, pk):
        reference = self.get_object(pk)
        if not reference:
            return Response({
                "status": "error",
                "message": "Reference not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = PersonalReferenceSerializer(reference, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "status": "success",
                "message": "Reference updated successfully.",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        return Response({
            "status": "error",
            "message": "Validation failed.",
            "data": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    # ---------- DELETE METHOD ----------
    @swagger_auto_schema(
        operation_summary="Delete a personal reference",
        operation_description="Delete a personal reference by its ID.",

        responses={
            204: openapi.Response(description="Reference deleted successfully"),
            404: openapi.Response(
                description="Reference not found",
                examples={"application/json": {"detail": "Reference not found"}}
            )
        },
        tags=['personal-reference']
    )
    def delete(self, request, pk):
        reference = self.get_object(pk)
        if not reference:
            return Response({
                "status": "error",
                "message": "Reference not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)
        reference.delete()
        return Response({
            "status": "success",
            "message": "Reference deleted successfully.",
            "data": None
        }, status=status.HTTP_200_OK)


# ========================================================
# VIEWS FOR ADD OR UPDATE INCOME FILE
# =========================================================


class CustomerIncomeFileView(APIView):
    permission_classes = [IsAdminOrGlobalManager]
    """
    for add and update income file for admin and global manager
    """

    # helper function to refresh SQLite cache
    def load_excel_to_sqlite(self, file_path):
        if os.path.exists(settings.EXCEL_CACHE_DB):
            os.remove(settings.EXCEL_CACHE_DB)

        df = pd.read_excel(file_path)
        df = df.rename(columns={
            'CEDULA': 'document_id',
            'PATRONO': 'employer',
            'SALARIO': 'monthly_income'
        })

        conn = sqlite3.connect(settings.EXCEL_CACHE_DB)
        df.to_sql('income_data', conn, index=False, if_exists='replace')
        conn.close()

    # ---------- POST METHOD ------------

    @swagger_auto_schema(
        operation_summary="Upload customer income Excel file",
        tags=["customer-income"],
    )
    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response({
                "status": "error",
                "message": "No file uploaded.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        existing_file = CustomerIncomeFile.objects.first()
        if existing_file:
            serializer = CustomerIncomeFileSerializer(existing_file)
            return Response({
                "status": "success",
                "message": "An income sheet already exists.",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        serializer = CustomerIncomeFileSerializer(data={"file": file})
        if serializer.is_valid():
            instance = serializer.save()
            #  refresh SQLite cache after save
            self.load_excel_to_sqlite(instance.file.path)
            return Response({
                "status": "success",
                "message": "Income sheet uploaded successfully.",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            "status": "error",
            "message": "Validation failed.",
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
   # ----------- PUT METHOD --------
    @swagger_auto_schema(
        operation_summary="Update existing income Excel file",
        tags=["customer-income"],
    )
    def put(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response({
                "status": "error",
                "message": "No file uploaded.",
                "data": None
            }, status=status.HTTP_400_BAD_REQUEST)

        existing_file = CustomerIncomeFile.objects.first()
        if not existing_file:
            return Response({
                "status": "error",
                "message": "No existing income sheet found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = CustomerIncomeFileSerializer(existing_file, data={"file": file}, partial=True)
        if serializer.is_valid():
            instance = serializer.save()
            #  refresh SQLite cache after update
            self.load_excel_to_sqlite(instance.file.path)
            return Response({
                "status": "success",
                "message": "Income sheet updated successfully.",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        return Response({
            "status": "error",
            "message": "Invalid data.",
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


# ===================================================
# FOR GENERATE OTP , for phone number verification
# ===================================================


class GenerateOTPView(APIView):
    permission_classes=[IsAuthenticatedUser]
    """
    Generate and send OTP to customer phone number.
    """

    @swagger_auto_schema(
        operation_summary="Generate and send OTP",
        operation_description="""
        Generates a 6-digit OTP and sends it to the provided phone number using LabsMobile API.  
        The OTP is valid for 5 minutes and stored temporarily in cache.
        
        **Frontend Flow:**
        1. User enters phone number.  
        2. Calls this endpoint to receive an OTP via SMS.  
        3. Then enters the OTP in the next step to verify.
        """,
        tags=["customer"],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["phone_number"],
            properties={
                "phone_number": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="Customer phone number in international format (e.g. +5076XXXXXXX)"
                ),
            },
        ),
        responses={
            200: openapi.Response(
                description="OTP sent successfully",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "status": openapi.Schema(type=openapi.TYPE_STRING, example="success"),
                        "message": openapi.Schema(type=openapi.TYPE_STRING, example="OTP sent successfully."),
                        "data": openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "phone_number": openapi.Schema(type=openapi.TYPE_STRING, example="+5076XXXXXXX"),
                            },
                        ),
                    },
                ),
            ),
            400: openapi.Response(
                description="Missing or invalid phone number",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "status": openapi.Schema(type=openapi.TYPE_STRING, example="error"),
                        "message": openapi.Schema(type=openapi.TYPE_STRING, example="Phone number is required."),
                    },
                ),
            ),
        },
    )
    def post(self, request):
        phone = request.data.get("phone_number")
        if not phone:
            return Response({"status": "error", "message": "Phone number is required."}, status=400)

        otp = random.randint(100000, 999999)
        cache.set(f"otp_{phone}", otp, timeout=300)  

        # Send OTP via LabsMobile
        message = f"Your Ola Credits verification code is {otp}"
        sms_response=send_sms(phone, message)
        # print('otp==',otp)
        if "error" in sms_response:
            return Response({
                "status": "error",
                "message": sms_response["error"]
            }, status=500)

        return Response({
            "status": "success",
            "message": "OTP sent successfully.",
            "data": {"phone_number": phone},
            "otp": otp
        }, status=200)

# ====================================================
#  CUSTOMER DASHBOARD VIEW (ALL CUSTOMERRELATED DATA)
# ====================================================

class CustomerDashboardAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    """
    for fetch all customer related data for customer dashboard
    """

    @swagger_auto_schema(
        operation_summary="Get complete customer dashboard",
        operation_description="""
        Returns a unified dashboard view for a specific customer.  
        This endpoint aggregates all related customer data — identity verification, 
        credit score, latest credit application, decision engine, device enrollment, 
        personal references, and income information.

        **Accessible by:** Admin, Manager, or Salesperson  
        **Example Usage:**  
        `GET /api/customers/12/dashboard/`
        """,
        manual_parameters=[
            openapi.Parameter(
                "customer_id",
                openapi.IN_PATH,
                description="Customer ID whose dashboard data should be fetched",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
        ],
        responses={
            200: openapi.Response(
                description="Customer dashboard fetched successfully",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "Customer dashboard fetched successfully.",
                        "data": {
                            "customer": {
                                "id": 12,
                                "first_name": "John",
                                "last_name": "Doe",
                                "document_number": "8-123-456",
                                "email": "john@example.com",
                                "phone_number": "+5076000000",
                                "status": "ACTIVE"
                            },
                            "identity_verification": {
                                "overall_status": "VERIFIED",
                                "biometric_status": "COMPLETED",
                                "face_match_score": 98.5,
                                "liveness_check_passed": True
                            },
                            "credit_score": {
                                "apc_score": 540,
                                "apc_status": "APPROVED",
                                "final_credit_status": "APPROVED"
                            },
                            "credit_application": {
                                "status": "APPROVED",
                                "device_brand": "Samsung",
                                "device_model": "Galaxy A55",
                                "amount_to_finance": 800.00
                            },
                            "decision_engine": {
                                "total_score": 90,
                                "final_decision": "APPROVED"
                            },
                            "device_enrollment": {
                                "imei": "123456789012345",
                                "enrollment_status": "COMPLETED",
                                "is_locked": False
                            },
                            "personal_references": [
                                {"id": 1, "full_name": "Jane Doe", "relationship": "Sister"},
                                {"id": 2, "full_name": "Carlos Diaz", "relationship": "Friend"}
                            ],
                            "income": {
                                "employer": "TechCorp",
                                "monthly_income": "1250.00"
                            }
                        }
                    }
                }
            ),
            404: openapi.Response(
                description="Customer not found",
                examples={"application/json": {
                    "status": "error",
                    "message": "Customer not found.",
                    "data": None
                }}
            )
        },
        tags=["customer-dashboard"]
    )


    def get(self, request, customer_id):
        # --- optimized query ---
        customer = (
            Customer.objects
            .select_related("identity_verification")
            .prefetch_related(
                "credit_scores",
                "personal_references",
                "credit_applications__decision_engine_result",
                "credit_applications__device_enrollment"
            )

            .filter(id=customer_id)
            .first()
        )

        if not customer:
            return Response({
                "status": "error",
                "message": "Customer not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        # --- related data ---
        identity = getattr(customer, "identity_verification", None)
        latest_credit_score = customer.credit_scores.order_by("-created_at").first()
        latest_application = customer.credit_applications.order_by("-created_at").first()
        decision_engine = getattr(latest_application, "decision_engine_result", None) if latest_application else None
        device_enrollment = getattr(latest_application, "device_enrollment", None) if latest_application else None
        personal_refs = customer.personal_references.all()
        income = CustomerIncome.objects.filter(document_id=customer.document_number).first()

        # --- response structure ---
        response_data = {
            "customer": CustomerSerializer(customer).data,
            "identity_verification": {
                "overall_status": identity.overall_status if identity else None,
                "biometric_status": identity.biometric_status if identity else None,
                "face_match_score": identity.face_match_score if identity else None,
                "liveness_check_passed": identity.liveness_check_passed if identity else None,
                "email_verified_at": identity.email_verified_at if identity else None,
                "phone_verified_at": identity.phone_verified_at if identity else None,
                "verification_completed_at": identity.verification_completed_at if identity else None,
                "rejection_reason": identity.rejection_reason if identity else None,
            },
            "credit_score": CreditScoreSerializer(latest_credit_score).data if latest_credit_score else None,
            "credit_application": {
                "status": latest_application.status if latest_application else None,
                "device_brand": latest_application.device_brand if latest_application else None,
                "device_model": latest_application.device_model if latest_application else None,
                "device_price": latest_application.device_price if latest_application else None,
                "initial_payment": latest_application.initial_payment if latest_application else None,
                "amount_to_finance": latest_application.amount_to_finance if latest_application else None,
                "number_of_installments": latest_application.number_of_installments if latest_application else None,
                "installment_amount": latest_application.installment_amount if latest_application else None,
                "total_amount": latest_application.total_amount if latest_application else None,
                "interest_rate": latest_application.interest_rate if latest_application else None,
                "created_at": latest_application.created_at if latest_application else None,
                "expires_at": latest_application.expires_at if latest_application else None,
            },
            "decision_engine": {
                "apc_score_value": decision_engine.apc_score_value if decision_engine else None,
                "internal_score_value": decision_engine.internal_score_value if decision_engine else None,
                "identity_validation_passed": decision_engine.identity_validation_passed if decision_engine else None,
                "payment_capacity_passed": decision_engine.payment_capacity_passed if decision_engine else None,
                "references_passed": decision_engine.references_passed if decision_engine else None,
                "anti_fraud_passed": decision_engine.anti_fraud_passed if decision_engine else None,
                "commercial_conditions_passed": decision_engine.commercial_conditions_passed if decision_engine else None,
                "total_score": decision_engine.total_score if decision_engine else None,
                "final_decision": decision_engine.final_decision if decision_engine else None,
                "rejection_reasons": decision_engine.rejection_reasons if decision_engine else None,
            },
            "device_enrollment": {
                "imei": device_enrollment.imei if device_enrollment else None,
                "device_brand": device_enrollment.device_brand if device_enrollment else None,
                "device_model": device_enrollment.device_model if device_enrollment else None,
                "enrollment_status": device_enrollment.enrollment_status if device_enrollment else None,
                "locking_system": device_enrollment.locking_system if device_enrollment else None,
                "is_locked": device_enrollment.is_locked if device_enrollment else None,
                "lock_applied_at": device_enrollment.lock_applied_at if device_enrollment else None,
            },
            "personal_references": PersonalReferenceSerializer(personal_refs, many=True).data,
            "income": {
                "employer": income.employer if income else None,
                "monthly_income": income.monthly_income if income else None,
            },
            "summary": {
                "total_credit_applications": customer.credit_applications.count(),
                "approved_applications": customer.credit_applications.filter(status="APPROVED").count(),
                "rejected_applications": customer.credit_applications.filter(status="REJECTED").count(),
                "active_status": customer.status,
                "total_references": personal_refs.count(),
            },
            "credit_summary": {
                "latest_apc_score": latest_credit_score.apc_score if latest_credit_score else None,
                "previous_apc_score": customer.credit_scores.order_by("-created_at")[1].apc_score if customer.credit_scores.count() > 1 else None,
                "credit_score_trend": (
                    "improved" if customer.credit_scores.count() > 1 and
                                latest_credit_score.apc_score > customer.credit_scores.order_by("-created_at")[1].apc_score
                    else "declined" if customer.credit_scores.count() > 1 and
                                latest_credit_score.apc_score < customer.credit_scores.order_by("-created_at")[1].apc_score
                    else "no_change"
                )
            },
            "device_enrollment_summary": {
                "total_devices": customer.credit_applications.filter(device_imei__isnull=False).count(),
                "enrolled_devices": customer.credit_applications.filter(
                    device_enrollment__enrollment_status="COMPLETED"
                ).count(),
                "locked_devices": customer.credit_applications.filter(
                    device_enrollment__is_locked=True
                ).count(),
            }
        }

        return Response({
            "status": "success",
            "message": "Customer dashboard fetched successfully.",
            "data": response_data
        }, status=status.HTTP_200_OK)

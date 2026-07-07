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
                     IdentityVerification, CreditApplication
                     )
from .serializers import (
     CustomerSerializer,
     CreditScoreSerializer,
     CustomerStatusSerializer,
     CreditConfigSerializer,
     PersonalReferenceSerializer,
     CustomerIncomeFileSerializer,
     CreditApplicationAsCustomerSerializer,
     )
from .utils import fetch_credit_score_from_experian
from .sms_utils import send_sms

# Standard Library Imports
import logging
import random
import requests
import hmac
import hashlib
import json

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


from .utils import CustomerFilter
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
                openapi.Parameter(
                    'status',
                    openapi.IN_QUERY,
                    description='Customer status',
                    type=openapi.TYPE_STRING,
                    enum=["ACTIVE", "INACTIVE", "BLOCKED"]
                ),
                openapi.Parameter(
                    'document_type',
                    openapi.IN_QUERY,
                    description='Filter by document type',
                    type=openapi.TYPE_STRING,
                    enum=['PANAMA_ID', 'PASSPORT', 'FOREIGNER_ID'],
                ),

                openapi.Parameter('created_by', openapi.IN_QUERY, description='Created by user ID', type=openapi.TYPE_INTEGER),

                openapi.Parameter('created_from', openapi.IN_QUERY, description='Created from (YYYY-MM-DD)', type=openapi.TYPE_STRING),
                openapi.Parameter('created_to', openapi.IN_QUERY, description='Created to (YYYY-MM-DD)', type=openapi.TYPE_STRING),

                openapi.Parameter('region_id', openapi.IN_QUERY, type=openapi.TYPE_STRING),
                openapi.Parameter('province_id', openapi.IN_QUERY, type=openapi.TYPE_STRING),
                openapi.Parameter('district_id', openapi.IN_QUERY, type=openapi.TYPE_STRING),
                openapi.Parameter('corregimiento_id', openapi.IN_QUERY, type=openapi.TYPE_STRING),

                openapi.Parameter(
                    'has_application',
                    openapi.IN_QUERY,
                    description='Filter customers having credit applications (1 or 0)',
                    type=openapi.TYPE_STRING
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
            - GET customers using all filters
            """

            customer_id = request.query_params.get('id')
            search_query = request.query_params.get('search', '').strip()

            # For salesperson, store manager, and sales advisor, return CreditApplications representing loan accounts / drafts
            if request.user.role in ['salesperson', 'store_manager', 'sales_advisor']:
                app_qs = CreditApplication.objects.select_related(
                    "customer",
                    "customer__created_by",
                    "customer__created_by__store",
                    "sales_person",
                    "sales_person__store",
                    "device",
                    "device__brand",
                    "finance_plan",
                    "finance_plan__store",
                ).order_by("-created_at")

                # Filter salesperson to their corresponding loans/applications only
                if request.user.role == 'salesperson':
                    app_qs = app_qs.filter(sales_person=request.user)
                
                # Filter store manager to store they belong to or chose
                elif request.user.role == 'store_manager':
                    store_id = request.query_params.get("store_id")
                    if store_id:
                        app_qs = app_qs.filter(
                            Q(finance_plan__store_id=store_id) | 
                            Q(sales_person__store_id=store_id)
                        )
                    elif request.user.store:
                        app_qs = app_qs.filter(
                            Q(finance_plan__store=request.user.store) | 
                            Q(sales_person__store=request.user.store)
                        )
                    else:
                        app_qs = app_qs.none()

                # Filter sales advisor to stores they are associated with
                elif request.user.role == 'sales_advisor':
                    app_qs = app_qs.filter(
                        Q(finance_plan__store__sales_advisor=request.user) |
                        Q(sales_person__store__sales_advisor=request.user)
                    ).distinct()

                # ------------ SINGLE CUSTOMER IN LATEST APP CONTEXT ------------
                if customer_id:
                    app = app_qs.filter(customer_id=customer_id).first()
                    if not app:
                        return Response({
                            "status": "error",
                            "message": "Application/Customer not found or restricted",
                        }, status=status.HTTP_404_NOT_FOUND)

                    serializer = CreditApplicationAsCustomerSerializer(app, context={'request': request})
                    return Response({
                        "status": "success",
                        "message": "Data fetched successfully.",
                        "data": serializer.data
                    })

                # Apply Filters
                status_filter = request.query_params.get("status")
                document_type = request.query_params.get("document_type")
                created_by = request.query_params.get("created_by")
                created_from = request.query_params.get("created_from")
                created_to = request.query_params.get("created_to")
                region_id = request.query_params.get("region_id")
                province_id = request.query_params.get("province_id")
                district_id = request.query_params.get("district_id")
                corregimiento_id = request.query_params.get("corregimiento_id")
                registration_status = request.query_params.get("registration_status")

                if status_filter:
                    if status_filter == 'DRAFT':
                        app_qs = app_qs.exclude(status='APPROVED')
                    else:
                        app_qs = app_qs.filter(customer__status=status_filter)
                
                if registration_status:
                    if registration_status == "Approved":
                        app_qs = app_qs.filter(status="APPROVED", device_imei__isnull=False).exclude(finance_plan__disbursements__status="COMPLETED")
                    elif registration_status == "Disbursed":
                        app_qs = app_qs.filter(status="APPROVED", device_imei__isnull=False, finance_plan__disbursements__status="COMPLETED")
                    elif registration_status == "Pending Approval":
                        app_qs = app_qs.filter(status="PENDING_APPROVAL")
                    elif registration_status == "Rejected":
                        app_qs = app_qs.filter(status="REJECTED")

                if document_type:
                    app_qs = app_qs.filter(customer__document_type=document_type)
                
                if created_by:
                    app_qs = app_qs.filter(customer__created_by_id=created_by)

                if created_from:
                    app_qs = app_qs.filter(created_at__date__gte=created_from)

                if created_to:
                    app_qs = app_qs.filter(created_at__date__lte=created_to)

                if region_id:
                    app_qs = app_qs.filter(finance_plan__store__region_id=region_id)

                if province_id:
                    app_qs = app_qs.filter(finance_plan__store__province_id=province_id)

                if district_id:
                    app_qs = app_qs.filter(finance_plan__store__district_id=district_id)

                if corregimiento_id:
                    app_qs = app_qs.filter(finance_plan__store__corregimiento_id=corregimiento_id)

                # Apply Search
                if search_query:
                    app_qs = app_qs.filter(
                        Q(customer__first_name__icontains=search_query) |
                        Q(customer__last_name__icontains=search_query) |
                        Q(customer__email__icontains=search_query) |
                        Q(customer__document_number__icontains=search_query) |
                        Q(customer__phone_number__icontains=search_query) |
                        Q(device_imei__icontains=search_query)
                    )

                if request.query_params.get('count_only') == 'true':
                    count = app_qs.distinct().count()
                    return Response({
                        "status": "success",
                        "count": count
                    }, status=status.HTTP_200_OK)

                # Pagination
                paginator = self.pagination_class()
                paginated_qs = paginator.paginate_queryset(app_qs.distinct(), request)
                serializer = CreditApplicationAsCustomerSerializer(paginated_qs, many=True, context={'request': request})
                paginated_response = paginator.get_paginated_response(serializer.data)
                paginated_data = paginated_response.data

                return Response({
                    "status": "success",
                    "message": "Loan accounts fetched successfully.",
                    "data": paginated_data
                }, status=status.HTTP_200_OK)

            # For other roles, use standard Customer queryset list
            queryset = (
                Customer.objects
                .select_related(
                    "created_by",
                    "created_by__store",
                    "created_by__store__region",
                    "created_by__store__province",
                    "created_by__store__district",
                    "created_by__store__corregimiento",
                    "created_by__store__sales_advisor",
                )                    
                .prefetch_related(                              
                    "credit_applications__finance_plan__store",
                    "credit_applications__finance_plan__device"
                )
                .order_by("-created_at")
            )

            # ------------ SINGLE CUSTOMER ------------

            if customer_id:
                customer = queryset.filter(id=customer_id).first()

                if not customer:
                    return Response({
                        "status": "error",
                        "message": "Customer not found",
                    }, status=status.HTTP_404_NOT_FOUND)

                serializer = CustomerSerializer(customer, context={'request': request})
                return Response({
                    "status": "success",
                    "message": "Data fetched successfully.",
                    "data": serializer.data
                })

            # ---- APPLY FILTERS ----
            queryset = CustomerFilter.apply_filters(queryset, request.query_params)

            # ------------ SEARCH ------------

            if search_query:
                queryset = queryset.filter(
                    Q(first_name__icontains=search_query) |
                    Q(last_name__icontains=search_query) |
                    Q(email__icontains=search_query) |
                    Q(document_number__icontains=search_query) |
                    Q(phone_number__icontains=search_query)
                )
            if request.query_params.get('count_only') == 'true':
                count = queryset.count()
                return Response({
                    "status": "success",
                    "count": count
                }, status=status.HTTP_200_OK)

            # ------------ PAGINATION ------------
            paginator = self.pagination_class()
            paginated_qs = paginator.paginate_queryset(queryset, request)
            serializer = CustomerSerializer(paginated_qs, many=True, context={'request': request})

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
                latest_app = existing_customer.credit_applications.order_by("-created_at").first()
                if not latest_app or latest_app.status in ["APPROVED", "REJECTED", "EXPIRED"]:
                    existing_customer.otp_verified = False
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
            latest_app = customer.credit_applications.order_by("-created_at").first()
            if latest_app and latest_app.status in ["APPROVED", "REJECTED", "EXPIRED"]:
                latest_app = None

            app_id = latest_app.id if latest_app else None
            current_step = latest_app.current_step if latest_app else 0

            # Fetch AutoFinancePlan id
            from finance.models import AutoFinancePlan, FinancePlan, EMISchedule
            latest_auto_plan = AutoFinancePlan.objects.filter(credit_application=latest_app).order_by("-id").first() if latest_app else None
            auto_plan_id = latest_auto_plan.id if latest_auto_plan else None

            # Check if customer has an active finance plan with unpaid EMIs
            active_plan = FinancePlan.objects.filter(
                credit_application__customer=customer,
                status="ACTIVE"
            ).first()

            has_active_plan = False
            if active_plan:
                has_active_plan = EMISchedule.objects.filter(
                    finance_plan=active_plan
                ).exclude(status="PAID").exists()

            # previous applications history
            previous_apps = []
            apps_qs = customer.credit_applications.order_by("-created_at")
            if latest_app:
                apps_qs = apps_qs.exclude(id=latest_app.id)
            for app in apps_qs:
                previous_apps.append({
                    "id": app.id,
                    "status": app.status,
                    "device_model": app.device_model or "N/A",
                    "device_price": str(app.device_price) if app.device_price else "0.00",
                    "created_at": app.created_at.strftime('%Y-%m-%d')
                })

            return Response({
                "status": "success",
                "message": "Customer created successfully." if newly_created else "Customer already exists.",
                "newly_created_customer": newly_created,
                "data": CustomerSerializer(customer).data,
                "application_id": app_id,
                "auto_plan_id": auto_plan_id,
                "current_step": current_step,
                "draft_data": latest_app.draft_data if latest_app else None,
                "has_active_plan": has_active_plan,
                "previous_applications": previous_apps,
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
                if request.user.role == 'salesperson':
                    customer = Customer.objects.filter(
                        Q(id=customer_id) &
                        (Q(created_by=request.user) | Q(credit_applications__sales_person=request.user))
                    ).distinct().get()
                else:
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
            otp_valid = None  # track OTP status

            if otp and phone:
                cached_otp = cache.get(f"otp_{phone}")
                if str(cached_otp) == str(otp):
                    cache.delete(f"otp_{phone}")
                    customer.otp_verified = True
                    customer.save(update_fields=["otp_verified"])
                    latest_app = customer.credit_applications.order_by("-created_at").first()
                    if latest_app:
                        latest_app.otp_verified = True
                        latest_app.save(update_fields=["otp_verified"])
                    otp_valid = True
                else:
                    otp_valid = False

            # ---- Continue updating other fields ----
            data = request.data.copy()
            data.pop("otp", None)
            

            serializer = CustomerSerializer(customer, data=data, partial=True, context={'request': request})
            if serializer.is_valid():
                updated_customer = serializer.save()
                
                # Activate customer if name details are entered
                if updated_customer.status == 'DRAFT' and updated_customer.first_name and updated_customer.last_name:
                    updated_customer.status = 'ACTIVE'
                    updated_customer.save(update_fields=['status'])
                
                # Sync manually entered salary and employer to CustomerIncome and SQLite cache
                salary = request.data.get("salary")
                employer = request.data.get("employer")
                if salary is not None or employer is not None:
                    from customer.models import CustomerIncome
                    from decimal import Decimal
                    defaults = {}
                    if salary is not None:
                        defaults["monthly_income"] = Decimal(str(salary))
                    if employer is not None:
                        defaults["employer"] = str(employer)
                    
                    CustomerIncome.objects.update_or_create(
                        document_id=updated_customer.document_number,
                        defaults=defaults
                    )
                    
                    # Also update SQLite cache database
                    from django.conf import settings
                    import sqlite3
                    db_path = getattr(settings, "EXCEL_CACHE_DB", None)
                    if db_path:
                        try:
                            conn = sqlite3.connect(db_path, timeout=5)
                            cur = conn.cursor()
                            cur.execute("SELECT 1 FROM income_data WHERE TRIM(document_id)=?", (str(updated_customer.document_number).strip(),))
                            exists = cur.fetchone()
                            if exists:
                                if salary is not None and employer is not None:
                                    cur.execute("UPDATE income_data SET monthly_income=?, employer=? WHERE TRIM(document_id)=?", 
                                                (float(salary), str(employer), str(updated_customer.document_number).strip()))
                                elif salary is not None:
                                    cur.execute("UPDATE income_data SET monthly_income=? WHERE TRIM(document_id)=?", 
                                                (float(salary), str(updated_customer.document_number).strip()))
                                elif employer is not None:
                                    cur.execute("UPDATE income_data SET employer=? WHERE TRIM(document_id)=?", 
                                                (str(employer), str(updated_customer.document_number).strip()))
                            else:
                                cur.execute("INSERT INTO income_data (document_id, employer, monthly_income) VALUES (?, ?, ?)", 
                                            (str(updated_customer.document_number).strip(), str(employer or ""), float(salary or 0)))
                            conn.commit()
                            conn.close()
                        except Exception as e:
                            logger.warning(f"Error updating SQLite income cache: {e}")
                    
                    # Recalculate AutoFinancePlan if salary changed
                    if salary is not None:
                        from finance.models import AutoFinancePlan
                        from finance.decision_engine import AutoDecisionEngine
                        auto_plan = AutoFinancePlan.objects.filter(
                            customer=updated_customer,
                            has_finance_plan=False
                        ).order_by("-id").first()
                        if auto_plan:
                            auto_plan.customer_monthly_income = Decimal(str(salary))
                            auto_plan.save(update_fields=["customer_monthly_income"])
                            try:
                                engine = AutoDecisionEngine(auto_plan)
                                engine.run()
                                logger.info(f"[AutoPlanRecalculated] Salary updated to {salary} for auto plan {auto_plan.id}")
                            except Exception as e:
                                logger.warning(f"Error recalculating auto plan: {e}")
                

                if otp_valid is False:
                    message = "OTP verification failed."
                    otp_status="failed"
                    
                elif otp_valid is True:
                    message = "Customer updated successfully (OTP verified)."
                    otp_status="sucess"
                else:
                    message = "Customer updated successfully."
                    otp_status="not_provided"

                return Response({
                    "status": "success",
                    "message": message,
                    "otp_verification":otp_status,
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

   # -----------GET METHOD-------------

    @swagger_auto_schema(
        operation_summary="Retrieve uploaded income Excel file",
        tags=["customer-income"],
    )
    def get(self, request):
        existing_file = CustomerIncomeFile.objects.first()

        if not existing_file:
            return Response({
                "status": "error",
                "message": "No income sheet found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = CustomerIncomeFileSerializer(existing_file)

        return Response({
            "status": "success",
            "message": "Income sheet retrieved successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)


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

        if request.user.role == 'salesperson':
            is_owner = (customer.created_by == request.user) or customer.credit_applications.filter(sales_person=request.user).exists()
            if not is_owner:
                return Response({
                    "status": "error",
                    "message": "Permission denied."
                }, status=status.HTTP_403_FORBIDDEN)

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







# class StartVerificationAPIView(APIView):
#     permission_classes=[IsAuthenticatedUser]
    
#     def post(self, request):

#         customer_id=request.data.get('customer_id')
#         if not customer_id:
#             logger.warning("StartVerification: customer_id missing in request.")
#             return Response({
#                 "status": "error",
#                 "message": "customer_id is required.",
#                 "data": None
#             }, status=status.HTTP_400_BAD_REQUEST)
#         logger.info("StartVerification: Creating session for customer_id=%s", customer_id)
        
#         veriff_url = "https://api.veriff.com/v1/sessions"

#         payload = {
#             "verification": {
#                 "vendorData": str(customer_id),
#                 "callback":{
#                     "redirectUrl":"https://ola-credits-ui.vercel.app/sellerPortal/creditScore"
#                 }
#             }
#         }

#         headers = {
#             "Content-Type": "application/json",
#             "X-AUTH-CLIENT":settings.VERIFF_API_KEY,
#         }

#         try:
#             veriff_res = requests.post(veriff_url, json=payload, headers=headers,timeout=10)

#             if veriff_res.status_code != 200:
#                 logger.error("StartVerification: Veriff error %s - %s",veriff_res.status_code, veriff_res.text)
#                 return Response({
#                     "status": "error",
#                     "message": "Failed to create Veriff session.",
#                     "data": veriff_res.json()
#                 }, status=veriff_res.status_code)
#             logger.info("StartVerification: Veriff session created successfully for customer_id=%s", customer_id)

#             veriff_data = veriff_res.json()

#             return Response({
#                 "status": "success",
#                 "message": "Verification session created successfully.",
#                 "data": veriff_data
#             }, status=status.HTTP_200_OK)
        
#         except requests.Timeout:
#             logger.error("StartVerification: Request to Veriff timed out.")
#             return Response({
#                 "status": "error",
#                 "message": "Veriff request timed out.",
#                 "data": None
#             }, status=status.HTTP_504_GATEWAY_TIMEOUT)
        
#         except requests.ConnectionError:
#             logger.error("StartVerification: Failed to connect to Veriff.")
#             return Response({
#                 "status": "error",
#                 "message": "Failed to connect to Veriff.",
#                 "data": None
#             }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

#         except Exception as e:
#             logger.exception("StartVerification: Unexpected error occurred.")
#             return Response({
#                 "status": "error",
#                 "message": str(e),
#                 "data": None
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ========================================================
#     VIEW FOR VERIFF FOR STORE FINAL RESPONSE
# ========================================================

class VeriffWebhookAPIView(APIView):
    """
    Veriff Webhook Receiver.
    - Veriff sends verification updates (submitted, approved, declined).
    - This endpoint MUST return only HTTP status codes .
    - Used internally (not accessed by frontend).
    - store final response status
    """
    authentication_classes = []   
    permission_classes = []       

    def get(self, request):
        logger.info("get method is working")
        try:
            logger.info("veriff webhook started")
            logger.info("Received Veriff webhook: %s", request.body.decode())

            # ======VALIDATE SIGNATURE========#
            raw_body = request.body
            hmac_signature = request.headers.get("x-hmac-signature")
            shared_secret = settings.VERIFF_SHARED_SECRET   

            calculated_sig = hmac.new(
                shared_secret.encode(),
                raw_body,
                hashlib.sha256
            ).hexdigest()

            if calculated_sig != hmac_signature:
                logger.warning("Invalid HMAC signature from Veriff.")
                return Response(status=401) 

            # ======= PARSE PAYLOAD =======#
            data = request.data
            # verif = data.get("verification") or data
            # decision webhook → has "verification"
            if "verification" in data:
                verif = data["verification"]
                status = verif.get("status")

            # event webhook → has "action"
            else:
                verif = data
                status = verif.get("action")


            # vendor_data = verif.get("vendorData")  
            # vendor_raw = (verif.get("vendorData") or "").strip()

            vendor_raw = (verif.get("vendorData") or "").strip()
            # status = verif.get("status") or verif.get("action")
            if not vendor_raw:
                logger.warning("Ignoring webhook with empty vendorData")
                return Response(status=200)

            # if vendor_data is None or status is None:
            #     logger.warning("Invalid payload structure: %s", data)
            #     return Response(status=400)   

            try:
                # vendor_data = int(vendor_data)
                vendor_id = int(vendor_raw)
            except:
                logger.warning("Invalid vendorData (not int): %s", vendor_raw)
                # return Response(status=400) 
                return Response(status=200)

            # ============ UPDATE DATABASE ===============#

            try:
                customer = Customer.objects.get(id=vendor_id)
            except Customer.DoesNotExist:
                logger.error("Customer not found: %s", vendor_id)
                # return Response(status=404) 
                return Response(status=200)

            latest_app = customer.credit_applications.order_by("-created_at").first()
            identity = None
            if latest_app:
                try:
                    identity = latest_app.identity_verification
                except IdentityVerification.DoesNotExist:
                    identity = None
            if identity is None:
                identity = IdentityVerification.objects.filter(credit_application=latest_app).first()
            if identity is None:
                identity = IdentityVerification.objects.create(customer=customer, credit_application=latest_app)

            if status == "approved":
                identity.overall_status = "VERIFIED"
                if latest_app:
                    latest_app.identity_verified = True
                    latest_app.save(update_fields=["identity_verified"])
            elif status == "declined":
                identity.overall_status = "REJECTED"
                if latest_app:
                    latest_app.identity_verified = False
                    latest_app.save(update_fields=["identity_verified"])
            elif status == "submitted" or status == "started":
                identity.overall_status = "IN_PROGRESS"
            elif status == "expired":
                identity.overall_status = "EXPIRED"
            else:
                identity.overall_status = "PENDING"
            identity.save()
            logger.info("Webhook completed")
            logger.info("Updated verification status for customer %s to %s", vendor_id, status)

            #==========SUCCESS RESPONSE===========
            return Response(status=200)
        
        
        except Exception as e:
            logger.exception("Unexpected error in Veriff webhook.")
            return Response(status=200)     

        # ==============================================

    def post(self, request):
        logger.info("post method is working")
        try:
            logger.info("veriff webhook started")
            logger.info("Received Veriff webhook: %s", request.body.decode())

            # ======VALIDATE SIGNATURE========#
            raw_body = request.body
            hmac_signature = request.headers.get("x-hmac-signature")
            shared_secret = settings.VERIFF_SHARED_SECRET   

            calculated_sig = hmac.new(
                shared_secret.encode(),
                raw_body,
                hashlib.sha256
            ).hexdigest()

            if calculated_sig != hmac_signature:
                logger.warning("Invalid HMAC signature from Veriff.")
                return Response(status=401) 

            # ======= PARSE PAYLOAD =======#
            data = request.data
            # verif = data.get("verification") or data
            # decision webhook → has "verification"
            if "verification" in data:
                verif = data["verification"]
                status = verif.get("status")

            # event webhook → has "action"
            else:
                verif = data
                status = verif.get("action")


            # vendor_data = verif.get("vendorData")  
            # vendor_raw = (verif.get("vendorData") or "").strip()

            vendor_raw = (verif.get("vendorData") or "").strip()
            # status = verif.get("status") or verif.get("action")
            if not vendor_raw:
                logger.warning("Ignoring webhook with empty vendorData")
                return Response(status=200)

            # if vendor_data is None or status is None:
            #     logger.warning("Invalid payload structure: %s", data)
            #     return Response(status=400)   

            try:
                # vendor_data = int(vendor_data)
                vendor_id = int(vendor_raw)
            except:
                logger.warning("Invalid vendorData (not int): %s", vendor_raw)
                # return Response(status=400) 
                return Response(status=200)

            # ============ UPDATE DATABASE ===============#

            try:
                customer = Customer.objects.get(id=vendor_id)
            except Customer.DoesNotExist:
                logger.error("Customer not found: %s", vendor_id)
                # return Response(status=404) 
                return Response(status=200)

            identity = getattr(customer, "identity_verification", None)

            if identity is None:
                identity = IdentityVerification.objects.create(customer=customer)  
            

            if status == "approved":
                identity.overall_status = "VERIFIED"
            elif status == "declined":
                identity.overall_status = "REJECTED"
            elif status == "submitted" or status == "started":
                identity.overall_status = "IN_PROGRESS"
            elif status == "expired":
                identity.overall_status = "EXPIRED"
            else:
                identity.overall_status = "PENDING"
            identity.save()
            logger.info("Webhook completed")
            logger.info("Updated verification status for customer %s to %s", vendor_id, status)

            #==========SUCCESS RESPONSE===========
            return Response(status=200)
        
        
        except Exception as e:
            logger.exception("Unexpected error in Veriff webhook.")
            return Response(status=200)        
# ===========================================================
#    VERIFF FINAL RESPONSE GET VIEW
# ===========================================================


class VerificationStatusAPIView(APIView):
    """
    Fetch the current Veriff verification status for a customer.
    Called by frontend (polling).
    """
    permission_classes=[IsAuthenticatedUser]


    @swagger_auto_schema(
        operation_summary="Get customer's verification status",
        operation_description="""
        Frontend polls this API to check updated ID verification status.

        Status values:
        - PENDING
        - IN_PROGRESS
        - VERIFIED
        - REJECTED
        - EXPIRED
        """,
        tags=["Identity-verification"],
        manual_parameters=[
            openapi.Parameter(
                "customer_id",
                openapi.IN_PATH,
                description="Customer ID",
                type=openapi.TYPE_INTEGER
            )
        ],
        responses={
            200: openapi.Response("Success"),
            404: "Customer / IdentityVerification not found",
            500: "Server error"
        }
    )

    def get(self, request, customer_id):
        try:
            logger.info("VerificationStatus: Fetching status for customer_id=%s", customer_id)

            # -------- Fetch customer --------
            try:
                customer = Customer.objects.get(id=customer_id)
            except Customer.DoesNotExist:
                logger.warning("VerificationStatus: Customer %s not found", customer_id)
                return Response({
                    "status": "error",
                    "message": "Customer not found.",
                    "data": None
                }, status=status.HTTP_404_NOT_FOUND)
            
            # -------- Check IdentityVerification --------
            latest_app = customer.credit_applications.order_by("-created_at").first()
            identity = None
            if latest_app:
                try:
                    identity = latest_app.identity_verification
                except IdentityVerification.DoesNotExist:
                    identity = None
            if identity is None:
                identity = IdentityVerification.objects.filter(credit_application=latest_app).first()
                
            if identity is None:
                logger.warning("VerificationStatus: IdentityVerification missing for customer %s", customer_id)
                return Response({
                    "status": "error",
                    "message": "IdentityVerification record not found for this customer.",
                    "data": None
                }, status=status.HTTP_404_NOT_FOUND)

            # -------- SUCCESS --------
            logger.info(
                "VerificationStatus: Status fetched for customer %s => %s",
                customer_id,
                identity.overall_status
            )

            return Response({
                "status": "success",
                "message": "Verification status fetched successfully.",
                "data": {
                    "overall_status": identity.overall_status
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("VerificationStatus: Unexpected error")
            return Response({
                "status": "error",
                "message": str(e),
                "data": None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, customer_id):
        # Allow mock verification from frontend
        try:
            customer = Customer.objects.get(id=customer_id)
            latest_app = customer.credit_applications.order_by("-created_at").first()
            identity, created = IdentityVerification.objects.get_or_create(
                customer=customer,
                credit_application=latest_app
            )
            identity.overall_status = "VERIFIED"
            identity.save()
            if latest_app:
                latest_app.identity_verified = True
                latest_app.save(update_fields=["identity_verified"])
            return Response({
                "status": "success",
                "message": "Customer identity mock-verified successfully.",
                "data": {
                    "overall_status": "VERIFIED"
                }
            }, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Customer not found."
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StartVerificationAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        customer_id = request.data.get("customer_id")
        if not customer_id:
            return Response({
                "status": "error",
                "message": "customer_id is required."
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Customer not found."
            }, status=status.HTTP_404_NOT_FOUND)

        latest_app = customer.credit_applications.order_by("-created_at").first()
        # Get or create IdentityVerification record
        identity, created = IdentityVerification.objects.get_or_create(
            customer=customer,
            credit_application=latest_app,
            defaults={
                "overall_status": "PENDING"
            }
        )

        veriff_session_url = f"https://demo.veriff.me/check/{customer.id}"
        identity.verification_link = veriff_session_url
        identity.overall_status = "IN_PROGRESS"
        identity.save()

        return Response({
            "status": "success",
            "message": "Verification session started successfully.",
            "data": {
                "verification": {
                    "id": str(identity.id),
                    "url": veriff_session_url
                }
            }
        }, status=status.HTTP_200_OK)


class CreditApplicationStepView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        application_id = request.data.get("application_id")
        current_step = request.data.get("current_step")
        draft_data = request.data.get("draft_data")

        if not application_id or current_step is None:
            return Response({
                "status": "error",
                "message": "Both application_id and current_step are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            app = CreditApplication.objects.get(id=application_id)
            app.current_step = int(current_step)
            update_fields = ["current_step"]
            if draft_data is not None:
                app.draft_data = draft_data
                update_fields.append("draft_data")
            app.save(update_fields=update_fields)
            return Response({
                "status": "success",
                "message": "Credit application step and draft updated successfully.",
                "data": {
                    "application_id": app.id,
                    "current_step": app.current_step,
                    "draft_data": app.draft_data
                }
            }, status=status.HTTP_200_OK)
        except CreditApplication.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Credit application not found."
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("Error updating credit application step")
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ========================================
#  NOTIFICATION AND STATUS UPDATE VIEWS
# ========================================

from .models import Notification
from .serializers import NotificationSerializer

class NotificationListAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user)
        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "status": "success",
            "data": serializer.data
        })

    def post(self, request):
        Notification.objects.filter(user=request.user).update(is_read=True)
        return Response({
            "status": "success",
            "message": "All notifications marked as read."
        })


class NotificationMarkReadAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, pk):
        try:
            notification = Notification.objects.get(id=pk, user=request.user)
            notification.is_read = True
            notification.save(update_fields=["is_read"])
            return Response({
                "status": "success",
                "message": "Notification marked as read."
            })
        except Notification.DoesNotExist:
            return Response({"status": "error", "message": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)


class CreditApplicationStatusUpdateView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def patch(self, request):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        app_id = request.data.get("application_id")
        new_status = request.data.get("status")

        if not app_id or not new_status:
            return Response({"status": "error", "message": "application_id and status are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            app = CreditApplication.objects.get(id=app_id)
            if new_status not in [c[0] for c in CreditApplication.STATUS_CHOICES]:
                return Response({"status": "error", "message": f"Invalid status value. Must be one of {[c[0] for c in CreditApplication.STATUS_CHOICES]}"}, status=status.HTTP_400_BAD_REQUEST)

            app.status = new_status
            app.save(update_fields=["status"])
            return Response({
                "status": "success",
                "message": "Application status updated successfully.",
                "data": {
                    "application_id": app.id,
                    "status": app.status
                }
            })
        except CreditApplication.DoesNotExist:
            return Response({"status": "error", "message": "Credit application not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Django Imports
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError


# Django REST Framework Imports
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status


# Local  Imports
from .models import ( Customer,CreditScore,
                     CreditConfig,PersonalReference,
                     )
from .serializers import (
     CustomerSerializer,
     CreditScoreSerializer,
     CustomerStatusSerializer,
     CreditConfigSerializer,
     PersonalReferenceSerializer,
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
from products.permissions import IsAdminOrGlobalManager


from rest_framework.pagination import PageNumberPagination
from django.db.models import Q





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
            - GET /api/customers/<id>/ → get individual customer
            """
            # Check if individual customer requested
            customer_id = request.query_params.get('id')
            if customer_id:
                try:
                    customer = Customer.objects.get(id=customer_id)
                    serializer = CustomerSerializer(customer)
                    return Response(serializer.data, status=status.HTTP_200_OK)
                except Customer.DoesNotExist:
                    return Response({'detail': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)

            # Otherwise, handle list or search
            search_query = request.query_params.get('search', '').strip()
            queryset = Customer.objects.all().order_by('-created_at')

            if search_query:
                queryset = queryset.filter(
                    Q(first_name__icontains=search_query) |
                    Q(last_name__icontains=search_query) |
                    Q(email__icontains=search_query) |
                    Q(document_number__icontains=search_query)|
                    Q(phone_number__icontains=search_query)
                )

            # Apply pagination
            paginator = self.pagination_class()
            paginated_qs = paginator.paginate_queryset(queryset, request)
            serializer = CustomerSerializer(paginated_qs, many=True)

            return paginator.get_paginated_response(serializer.data)

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
                    'latitude': openapi.Schema(type=openapi.TYPE_NUMBER, format=openapi.FORMAT_FLOAT),
                    'longitude': openapi.Schema(type=openapi.TYPE_NUMBER, format=openapi.FORMAT_FLOAT),
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






        # ---------- PATCH ----------
        @swagger_auto_schema(
            operation_summary="Update a customer",
            operation_description="Partially updates a customer. Provide `id` query parameter and only the fields you want to update.",
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
                    'status': openapi.Schema(type=openapi.TYPE_STRING),
                }
            ),
            responses={
                200: openapi.Response(
                    description="Customer updated successfully",
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
                            'created_by': openapi.Schema(type=openapi.TYPE_INTEGER, nullable=True),
                            'created_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                            'updated_at': openapi.Schema(type=openapi.FORMAT_DATETIME),
                        }
                    )
                ),
                400: "Validation error",
                404: "Customer not found",
            }
        )
        def patch(self, request):
            """
            Partially update a customer by ID.
            Example:
            PATCH /v1/customer/manage/?id=3
            """
            customer_id = request.query_params.get('id') 
            if not customer_id:
                return Response(
                    {"detail": "Customer ID is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                customer = Customer.objects.get(id=customer_id)
            except Customer.DoesNotExist:
                return Response(
                    {"detail": "Customer not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            serializer = CustomerSerializer(customer, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                updated_customer = serializer.save()
                return Response(CustomerSerializer(updated_customer).data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)





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
                return Response(
                    {"detail": "Customer ID is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                customer = Customer.objects.get(id=customer_id)
                customer.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)
            except Customer.DoesNotExist:
                return Response(
                    {"detail": "Customer not found"},
                    status=status.HTTP_404_NOT_FOUND
                )






class CustomerStatusUpdateView(APIView):
    """
    Update the status of a customer (ACTIVE, INACTIVE, BLOCKED)
    """

    permission_classes = [IsAuthenticatedUser]  

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
            return Response({"detail": "Customer ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({"detail": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = CustomerStatusSerializer(customer, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"id": customer.id, "status": serializer.data['status']}, status=status.HTTP_200_OK)
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
            return Response({"detail": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

        # 1️= Check if recent score exists (within 30 days)
        latest_score = customer.get_latest_credit_score()
        if latest_score:
            serializer = CreditScoreSerializer(latest_score)
            return Response({"source": "cache", "credit_score": serializer.data})

        # 2️= Fetch new score from Experian
        experian_data = fetch_credit_score_from_experian(customer)
        if not experian_data:
            return Response({"detail": "Failed to fetch credit score from Experian"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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



# ==============================================
# CREDIT CONFIG GET VIEW (VIEW THRESHOLD VALUE)
# =============================================




class CreditConfigGetAPIView(APIView):
    permission_classes=[IsAuthenticatedUser]
    """
    only get method, permission for all authanticated users
    """
    
    @swagger_auto_schema(
        operation_summary="Get current APC threshold",
        operation_description="Fetch the current dynamic APC/Experian approval threshold value.",
        responses={
            200: openapi.Response(
                description="Current APC threshold fetched successfully",
                examples={
                    "application/json": {
                        "id": 1,
                        "apc_approval_threshold": 500,
                        "updated_at": "2025-10-20T14:30:00Z",
                        "created_at": "2025-10-15T10:00:00Z"
                    }
                }
            ),
            404: openapi.Response(
                description="Configuration not found",
                examples={"application/json": {"detail": "No configuration found"}}
            ),
        },
        tags=['credit']
    )


    def get(self, request):
        config = CreditConfig.objects.first()
        serializer = CreditConfigSerializer(config)
        return Response(serializer.data)




# ==============================================
# CREDIT CONFIG CHANGE VIEW (SET THRESHOLD VALUE)
# =============================================



class CreditConfigChangeAPIView(APIView):
    permission_classes=[IsAdminOrGlobalManager]
    """
    only post and patch, post only one time, permission for admin and global manager
    """
    @swagger_auto_schema(
        operation_summary="Create APC threshold configuration",
        operation_description="Create a new CreditConfig row. Only one configuration is allowed; will return 400 if it already exists.",
        request_body=CreditConfigSerializer,
        responses={
            201: openapi.Response(
                description="CreditConfig created successfully",
                examples={
                    "application/json": {
                        "id": 1,
                        "apc_approval_threshold": 500,
                        "updated_at": "2025-10-21T12:00:00Z"
                    }
                }
            ),
            400: openapi.Response(
                description="Configuration already exists or validation error",
                examples={"application/json": {"detail": "CreditConfig already exists. Only one row allowed."}}
            ),
        },
        tags=['credit']
    )



    def post(self, request):
        # Check if a config already exists
        if CreditConfig.objects.exists():
            return Response(
                {"detail": "CreditConfig already exists. Only one row allowed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CreditConfigSerializer(data=request.data)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except ValidationError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




    @swagger_auto_schema(
        operation_summary="Update APC threshold",
        operation_description="Update the dynamic APC/Experian approval threshold value. Only one configuration row exists; updates are applied to it.",
        request_body=CreditConfigSerializer,
        responses={
            200: openapi.Response(
                description="APC threshold updated successfully",
                examples={
                    "application/json": {
                        "id": 1,
                        "apc_approval_threshold": 520,
                        "updated_at": "2025-10-20T15:00:00Z",
                        "created_at": "2025-10-15T10:00:00Z"
                    }
                }
            ),
            400: openapi.Response(
                description="Validation error",
                examples={"application/json": {"apc_approval_threshold": ["This field is required."]}}
            ),
        },
        tags=['credit']
        )


    def patch(self, request):
        config = CreditConfig.objects.first()
        serializer = CreditConfigSerializer(config, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    






# =====================================================
#  PERSONAL REFERENCE LIST + CREATE
# =====================================================

class PersonalReferenceListCreateAPIView(APIView):
    """
    Handles listing and creating personal references for a specific customer.
    """
    permission_classes = [IsAuthenticatedUser]

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
            return Response({"detail": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

        references = PersonalReference.objects.filter(customer=customer)
        serializer = PersonalReferenceSerializer(references, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
            return Response({"detail": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = PersonalReferenceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(customer=customer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
            return Response({"detail": "Reference not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PersonalReferenceSerializer(reference)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
            return Response({"detail": "Reference not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PersonalReferenceSerializer(reference, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
            return Response({"detail": "Reference not found"}, status=status.HTTP_404_NOT_FOUND)
        reference.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

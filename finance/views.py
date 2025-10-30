
# ============================================================
# Standard Library Imports
# ============================================================
import logging
from decimal import Decimal
from datetime import timedelta

# swagger settup
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from customer.permissions import IsAuthenticatedUser

# ============================================================
# Django Imports
# ============================================================
from django.shortcuts import get_object_or_404
from django.db.models import Count, Sum, Avg
from django.utils import timezone
from django.db import models 

# ============================================================
# Third-Party Imports
# ============================================================
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from drf_yasg.utils import swagger_auto_schema

# ============================================================
# Local Application Imports
# ============================================================
from .models import FinancePlan, PaymentRecord, EMISchedule, AutoFinancePlan
from home.permissions import CanViewReports
from customer.models import Customer, CreditApplication, CreditScore, CustomerIncome
from .serializers import (
    FinancePlanSerializer,
    RegionWiseReportSerializer,
    CommonReportSerializer,
    FinancePlanCreateSerializer,
    AutoFinancePlanCreateSerializer,
    FinanceOverviewSerializer,
    AutoFinancePlanSerializer,
    PaymentRecordSerializer,
    PaymentRecordSerializerPlan,
    FinanceRiskTierSerializer,
    FinanceCollectionSerializer,
    FinanceOverdueSerializer,
    EMIScheduleSerializerPlan,
)
from .permissions import IsAdminOrGlobalManager
from .decision_engine import DecisionEngine, AutoDecisionEngine
# ============================================================
# Logger Setup
# ============================================================
logger = logging.getLogger(__name__)

# ============================================================
# Pagination
# ============================================================
class FinancePlanPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================
# Tier-based finance plans with multiple terms
# ============================================================
class AutoFinancePlanView(APIView):
    """
    Automatically creates Finance Plan Terms for a customer.
    """
    permission_classes = [IsAuthenticatedUser]
    @swagger_auto_schema(
        operation_summary="Create Finance Plan Terms",
        request_body=AutoFinancePlanCreateSerializer(),
        responses={
            201: AutoFinancePlanSerializer(many=True),
            400: "Validation Error",
            500: "Internal Server Error",
        },
        tags=["Finance"]
    )
    def post(self, request):
        try:
            # Validate Input
            serializer = AutoFinancePlanCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            customer_id = serializer.validated_data["customer_id"]

            # Get Customer
            customer = get_object_or_404(Customer, id=customer_id)

            # Get latest credit score (non-expired)
            credit_score = (
                CreditScore.objects.filter(customer=customer, is_expired=False)
                .order_by("-created_at")
                .first()
            )
            if not credit_score:
                return Response(
                    {"detail": "No active credit score found for this customer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            apc_score = credit_score.apc_score

            # Get or create an active credit application
            credit_app = (
                CreditApplication.objects.filter(
                    customer=customer, status__in=["PENDING_APPROVAL", "PRE_QUALIFIED"]
                )
                .order_by("-created_at")
                .first()
            )
            if not credit_app or credit_app.is_expired():
                credit_app = CreditApplication.objects.create(
                    customer=customer, device_price=0
                )

            # To get monthly income of customer
            document_number = customer.document_number
            monthly_income = CustomerIncome.get_income_by_document(document_number)

            engine_input, created = AutoFinancePlan.objects.get_or_create(
                customer=customer,
                credit_application=credit_app,
                credit_score=credit_score,
                apc_score=apc_score,
                risk_tier="",
                customer_monthly_income=monthly_income,
                maximum_allowed_installment=Decimal("0.00"),
                minimum_down_payment_percentage=Decimal("0.00"),
            )

            # Run Decision Engine
            engine = AutoDecisionEngine(engine_input)
            decision_output = engine.run()  

            #Save all data to AutoFinancePlan      
            # auto_plan, created = AutoFinancePlan.objects.get_or_create(
            #     credit_application=credit_app,
            #     defaults={
            #         "customer": customer,
            #         "credit_score": credit_score,
            #         "apc_score": apc_score,
            #         "risk_tier": "",
            #         "customer_monthly_income": monthly_income,
            #         "maximum_allowed_installment": Decimal("0.00"),
            #         "minimum_down_payment_percentage": Decimal("0.00"),
            #     }
            # )    
            auto_plan=engine_input

            #Return success response           
            return Response(
                {
                    "message": "Auto Finance Plan generated successfully.",
                    "customer": customer.id,
                    "credit_application": credit_app.id,
                    "apc_score": apc_score,
                    "data": {
                        "risk_tier": auto_plan.risk_tier,
                        "monthly_income": str(auto_plan.customer_monthly_income),
                        "payment_capacity_factor": str(auto_plan.payment_capacity_factor),
                        "maximum_allowed_installment": str(auto_plan.maximum_allowed_installment),
                        "minimum_down_payment_percentage": str(auto_plan.minimum_down_payment_percentage),
                        "allowed_plans": auto_plan.allowed_plans,
                        "high_end_extra_percentage": str(auto_plan.high_end_extra_percentage),
                    },
                },
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            logger.error(f"Error in AutoFinancePlanView: {str(e)}")
            return Response(
                {"detail": "Internal server error while creating finance plan terms."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )        


# --------------------------------------------------------
# API: Create or Get Finance Plan
# --------------------------------------------------------
class FinancePlanAPIView(APIView):
    permission_classes=[IsAuthenticatedUser]
    """
    API to create a Finance Plan using Decision Engine from AutoFinancePlan data,
    and retrieve all or specific Finance Plans.
    """

    @swagger_auto_schema(
        operation_summary="Create Finance Plan",
        operation_description="""
        Creates a new Finance Plan using AutoFinancePlan data and Decision Engine results.
        Input example shows how 'choosed_allowed_plans' should be structured.
        Device is mandatory, device_price is optional (will be auto-calculated if not provided).
        """,
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["temp_plan_id", "device", "actual_down_payment", "choosed_allowed_plans"],
            properties={
                "temp_plan_id": openapi.Schema(type=openapi.TYPE_INTEGER, description="Temporary AutoFinancePlan ID"),
                "device": openapi.Schema(type=openapi.TYPE_INTEGER, description="Product Model ID (required)"),
                "device_price": openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    format=openapi.FORMAT_DECIMAL, 
                    description="Device price (optional - will be auto-calculated from device if not provided)"
                ),
                "actual_down_payment": openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_DECIMAL, description="Down payment made by customer"),
                "choosed_allowed_plans": openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    description="Allowed plan selection with term and frequency",
                    properties={
                        "selected_term": openapi.Schema(type=openapi.TYPE_INTEGER, description="Selected term in months (e.g. 6)"),
                        "installment_frequency_days": openapi.Schema(type=openapi.TYPE_INTEGER, description="Installment frequency in days (e.g. 30)"),
                    },
                    example={
                        "selected_term": 6,
                        "installment_frequency_days": 30
                    }
                ),
            },
            example={
                "temp_plan_id": 1,
                "device": 5,
                "device_price": "25000.00",
                "actual_down_payment": "5000.00",
                "choosed_allowed_plans": {
                    "selected_term": 6,
                    "installment_frequency_days": 30
                }
            }
        ),
        responses={
            201: FinancePlanSerializer(),
            400: "Validation Error",
            404: "AutoFinancePlan not found",
            500: "Internal Server Error",
        },
        tags=["Finance"]
    )

    def post(self, request):
        try:
            # Validate input
            serializer = FinancePlanCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            # Fetch AutoFinancePlan by ID
            auto_finance_plan = get_object_or_404(AutoFinancePlan, id=data.get('temp_plan_id'))

            # Get device_price - either from input or auto-calculate
            device = data["device"]
            device_price = data.get("device_price")
            
            if not device_price:
                # Auto-calculate device price with 7% ITBMS tax
                base_price = device.suggested_price
                device_price = base_price + (base_price * Decimal('0.07'))

            # Prepare DecisionEngine input
            engine_input = FinancePlan(
                credit_application=auto_finance_plan.credit_application,
                credit_score=auto_finance_plan.credit_score,
                apc_score=auto_finance_plan.apc_score,
                device=device,
                device_price=device_price,
                actual_down_payment=data["actual_down_payment"],
                customer_monthly_income=auto_finance_plan.customer_monthly_income,
                selected_term=data["choosed_allowed_plans"]["selected_term"],
                installment_frequency_days=data["choosed_allowed_plans"]["installment_frequency_days"],
                risk_tier="",
                minimum_down_payment_percentage=Decimal("0.00"),
                down_payment_percentage=Decimal("0.00"),
                amount_to_finance=Decimal("0.00"),
                monthly_installment=Decimal("0.00"),
                total_amount_payable=Decimal("0.00"),
                payment_capacity_factor=Decimal("0.00"),
                maximum_allowed_installment=Decimal("0.00"),
                installment_to_income_ratio=Decimal("0.00"),
            )

            logger.info(f"[FinancePlanAPI] DecisionEngine input: {engine_input}")

            # Run Decision Engine
            engine = DecisionEngine(engine_input)
            engine_output = engine.run()  

            final_plan = engine_output  
            final_plan.save()   

            # Save new FinancePlan and return 
            finance_plan_serializer = FinancePlanSerializer(final_plan)
            return Response(finance_plan_serializer.data, status=status.HTTP_201_CREATED)
        except AutoFinancePlan.DoesNotExist:
            logger.error("[FinancePlanAPI] AutoFinancePlan not found.")
            return Response({"error": "AutoFinancePlan not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("[FinancePlanAPI] Error creating Finance Plan.")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    # --------------------------------------------------------
    # GET: List All or Retrieve by ID
    # --------------------------------------------------------
    @swagger_auto_schema(
        operation_summary="Retrieve Finance Plan(s)",
        operation_description="""
        Retrieves either all Finance Plans or a specific one by ID.

        **Examples:**
        - `GET /api/finance/plan/` → list all
        - `GET /api/finance/plan/?id=5` → retrieve FinancePlan with ID=5
        """,
        responses={200: FinancePlanSerializer(many=True)},
        tags=["Finance"]
    )
    def get(self, request, id=None):
        try:
            if id:
                plan = get_object_or_404(FinancePlan, id=id)
                serializer = FinancePlanSerializer(plan)
                logger.info(f"[FinancePlanAPI] Retrieved FinancePlan ID={id}")
                return Response(serializer.data, status=status.HTTP_200_OK)

           # Paginated list of plans
            finance_plans = FinancePlan.objects.all().order_by("-created_at")
            paginator = FinancePlanPagination()
            paginated_qs = paginator.paginate_queryset(finance_plans, request)
            serializer = FinancePlanSerializer(paginated_qs, many=True)
            logger.info(f"[FinancePlanAPI] Retrieved {len(paginated_qs)} finance plans (paginated).")
            return paginator.get_paginated_response(serializer.data)
        except Exception as e:
            logger.exception("[FinancePlanAPI] Error retrieving Finance Plans.")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

    @swagger_auto_schema(
        operation_summary="Get Finance Plan by Customer ID",
        operation_description="""
        Retrieve the finance plan for a specific customer.
        Pass customer_id as query parameter.
        
        **Example:**
        - `GET /api/finance/plan/customer/?customer_id=5`
        """,
        manual_parameters=[
            openapi.Parameter(
                'customer_id',
                openapi.IN_QUERY,
                description="Customer ID",
                type=openapi.TYPE_INTEGER,
                required=True
            )
        ],
        responses={
            200: FinancePlanSerializer(),
            404: "Finance Plan not found for this customer",
            400: "customer_id parameter is required"
        },
        tags=["Finance"]
    )
    def get(self, request, id=None):
        try:
            # Check if customer_id is provided
            customer_id = request.query_params.get('customer_id')
            
            if customer_id:
                # Get customer
                customer = get_object_or_404(Customer, id=customer_id)
                
                # Get finance plan through credit application
                finance_plan = FinancePlan.objects.filter(
                    credit_application__customer=customer
                ).order_by('-created_at').first()
                
                if not finance_plan:
                    return Response(
                        {"error": f"No finance plan found for customer ID {customer_id}"}, 
                        status=status.HTTP_404_NOT_FOUND
                    )
                
                serializer = FinancePlanSerializer(finance_plan)
                logger.info(f"[FinancePlanAPI] Retrieved FinancePlan for Customer ID={customer_id}")
                return Response(serializer.data, status=status.HTTP_200_OK)
            
            # Existing logic for getting by ID
            if id:
                plan = get_object_or_404(FinancePlan, id=id)
                serializer = FinancePlanSerializer(plan)
                logger.info(f"[FinancePlanAPI] Retrieved FinancePlan ID={id}")
                return Response(serializer.data, status=status.HTTP_200_OK)

            # Paginated list of plans
            finance_plans = FinancePlan.objects.all().order_by("-created_at")
            paginator = FinancePlanPagination()
            paginated_qs = paginator.paginate_queryset(finance_plans, request)
            serializer = FinancePlanSerializer(paginated_qs, many=True)
            logger.info(f"[FinancePlanAPI] Retrieved {len(paginated_qs)} finance plans (paginated).")
            return paginator.get_paginated_response(serializer.data)
            
        except Exception as e:
            logger.exception("[FinancePlanAPI] Error retrieving Finance Plans.")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ============================================================
# Finance Analytics Overview for Plans
# ============================================================
class FinanceOverviewAPIView(APIView):
    """
    GET: Return dashboard-style analytics for finance plans
    """
    permission_classes = [IsAdminOrGlobalManager]

    @swagger_auto_schema(
    operation_summary="Get Finance Analytics Overview",
    operation_description=(
        "Returns summarized analytics for all Finance Plans, including:\n"
        "- Total finance plans\n"
        "- Total customers\n"
        "- Approved and rejected counts\n"
        "- Total financed amount\n"
        "- Average installment amount\n"
        "- Average APC score\n"
        "- Risk tier distribution"
    ),
    responses={
        200: FinanceOverviewSerializer,
        500: "Internal Server Error",
    },
    tags=["Finance"]
    )

    def get(self, request):
        try:
            plans = FinancePlan.objects.all()

            # Aggregates
            total_finance_plans = plans.count()
            total_customers = plans.values('credit_application__customer').distinct().count()
            total_approved = plans.filter(score_status='APPROVED').count()
            total_rejected = plans.filter(score_status='REJECTED').count()
            total_amount_financed = float(plans.aggregate(total=Sum('amount_to_finance'))['total'] or 0)
            average_installment = float(plans.aggregate(avg=Avg('monthly_installment'))['avg'] or 0)
            avg_apc_score = float(plans.aggregate(avg=Avg('apc_score'))['avg'] or 0)

            # Tier distribution
            tier_counts = plans.values('risk_tier').annotate(count=Count('id'))
            avg_risk_tier = {tier['risk_tier']: tier['count'] for tier in tier_counts}

            data = {
                "total_finance_plans": total_finance_plans,
                "total_customers": total_customers,
                "total_approved": total_approved,
                "total_rejected": total_rejected,
                "total_amount_financed": total_amount_financed,
                "average_installment": average_installment,
                "avg_apc_score": avg_apc_score,
                "avg_risk_tier": avg_risk_tier,
            }

            serializer = FinanceOverviewSerializer(data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error generating finance overview: {str(e)}", exc_info=True)
            return Response(
                {"detail": "Failed to generate finance overview."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

# ============================================================
# Finance Risk Tier Analytics 
# ============================================================
class FinanceRiskTierView(APIView):
    """
    GET: Return analytics grouped by risk tier
    """
    permission_classes = [IsAdminOrGlobalManager]

    @swagger_auto_schema(
        operation_summary="Get Risk Tier Analytics",
        operation_description=(
            "Returns aggregated metrics grouped by risk tier:\n"
            "- Total customers per tier\n"
            "- Total plans per tier\n"
            "- Total amount financed per tier\n"
            "- Average installment per tier"
        ),
        responses={200: FinanceRiskTierSerializer(many=True)},
        tags=["Finance"]
    )
    def get(self, request):
        try:
            data = []
            tiers = (
                FinancePlan.objects.values("risk_tier")
                .annotate(
                    total_customers=Count("credit_application__customer", distinct=True),
                    total_finance_plans=Count("id"),
                    total_amount_financed=Sum("amount_to_finance"),
                    average_installment=Avg("monthly_installment"),
                )
                .order_by("risk_tier")
            )
            for tier in tiers:
                data.append({
                    "risk_tier": tier["risk_tier"],
                    "total_customers": tier["total_customers"],
                    "total_finance_plans": tier["total_finance_plans"],
                    "total_amount_financed": float(tier["total_amount_financed"] or 0),
                    "average_installment": float(tier["average_installment"] or 0),
                })

            serializer = FinanceRiskTierSerializer(data, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error generating risk tier analytics: {str(e)}", exc_info=True)
            return Response({"detail": "Failed to generate risk tier analytics."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# Finance Collection Analytics 
# ============================================================
class FinanceCollectionsView(APIView):
    permission_classes = [IsAdminOrGlobalManager]

    @swagger_auto_schema(
        operation_summary="Get Collection Analytics",
        responses={200: FinanceCollectionSerializer},
        tags=["Finance"]
    )
    def get(self, request):
        try:
            payments = PaymentRecord.objects.all()
            total_installments = payments.count()
            total_collected = float(payments.filter(payment_status='COMPLETED')
                                    .aggregate(Sum('payment_amount'))['payment_amount__sum'] or 0)
            total_due = float(payments.aggregate(Sum('payment_amount'))['payment_amount__sum'] or 0)
            total_pending = total_due - total_collected
            collection_rate = (total_collected / total_due * 100) if total_due > 0 else 0.0

            data = {
                "total_installments": total_installments,
                "total_collected": total_collected,
                "total_pending": total_pending,
                "collection_rate": round(collection_rate, 2),
            }

            serializer = FinanceCollectionSerializer(data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error generating collection analytics: {str(e)}", exc_info=True)
            return Response({"detail": "Failed to generate collection analytics."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# Finance Overdue Installment Analytics 
# ============================================================       
class FinanceOverdueView(APIView):
    permission_classes = [IsAdminOrGlobalManager]

    @swagger_auto_schema(
        operation_summary="Get Overdue Installment Analytics",
        responses={200: FinanceOverdueSerializer},
        tags=["Finance"]
    )
    def get(self, request):
        try:
            today = timezone.now().date()
            overdue = EMISchedule.objects.filter(amount_paid__lt=models.F('installment_amount'), due_date__lt=today)

            total_overdue_installments = overdue.count()
            total_overdue_amount = float(overdue.aggregate(Sum('installment_amount'))['installment_amount__sum'] or 0)
            customers_with_overdue = overdue.values('finance_plan__credit_application__customer').distinct().count()

            data = {
                "total_overdue_installments": total_overdue_installments,
                "total_overdue_amount": total_overdue_amount,
                "customers_with_overdue": customers_with_overdue,
            }

            serializer = FinanceOverdueSerializer(data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error generating overdue analytics: {str(e)}", exc_info=True)
            return Response({"detail": "Failed to generate overdue analytics."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

# ============================================================
# Payment Record List & Create View
# ============================================================
class PaymentRecordListCreateView(APIView):
    """
    Handles both:
    - List payment records 
    - Create a new payment record
    """
    permission_classes = [IsAdminOrGlobalManager]
    serializer_class = PaymentRecordSerializer

    # --------------------------------------
    # List all payment records
    # --------------------------------------
    @swagger_auto_schema(
        operation_summary="List Payment Records",
        operation_description="Retrieve a paginated list of all payment records, ordered by latest payment date.",
        responses={
            200: PaymentRecordSerializer(many=True),
            500: "Internal Server Error",
        },
        tags=["Finance"]
    )
    def get(self, request):
        """
        Retrieve a paginated list of all payment records.
        """
        try:
            payments = PaymentRecord.objects.all().order_by('-payment_date')
            paginator = FinancePlanPagination()
            result_page = paginator.paginate_queryset(payments, request)
            serializer = self.serializer_class(result_page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        except Exception as e:
            logger.error(f"Error fetching payment records: {str(e)}", exc_info=True)
            return Response(
                {"detail": "Failed to fetch payment records."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # --------------------------------------
    # Create new payment record
    # --------------------------------------
    @swagger_auto_schema(
        operation_summary="Create Payment Record",
        operation_description="Creates a new payment record linked to a Finance Plan or EMI Schedule.",
        request_body=PaymentRecordSerializer,
        responses={
            201: PaymentRecordSerializer,
            400: "Bad Request",
            404: "Finance Plan or EMI Schedule Not Found",
            500: "Internal Server Error",
        },
        tags=["Finance"]
    )
    def post(self, request):
        """
        Create a new payment record for a given Finance Plan or EMI Schedule.
        """
        try:
            serializer = PaymentRecordSerializer(data=request.data)
            if serializer.is_valid():
                payment = serializer.save(processed_by=request.user)
                return Response(
                    PaymentRecordSerializer(payment).data,
                    status=status.HTTP_201_CREATED
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except FinancePlan.DoesNotExist:
            logger.error("FinancePlan not found", exc_info=True)
            return Response({"detail": "Finance plan not found."}, status=status.HTTP_404_NOT_FOUND)
        except EMISchedule.DoesNotExist:
            logger.error("EMI schedule not found", exc_info=True)
            return Response({"detail": "EMI schedule not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error creating payment record: {str(e)}", exc_info=True)
            return Response(
                {"detail": "Failed to create payment record."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        



# --------------------------------------------------------
# API: Get EMI Schedule by Customer ID
# --------------------------------------------------------
class EMIScheduleAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]
    
    @swagger_auto_schema(
        operation_summary="Get EMI Schedule by Customer ID",
        operation_description="""
        Retrieve all EMI schedules (upcoming, due, paid, overdue) for a specific customer.
        
        **Query Parameters:**
        - `customer_id` (required): Customer ID
        - `status` (optional): Filter by status (UPCOMING, DUE, PAID, OVERDUE, PARTIALLY_PAID)
        
        **Examples:**
        - `GET /api/finance/emi-schedule/?customer_id=5` → Get all EMI schedules
        - `GET /api/finance/emi-schedule/?customer_id=5&status=PAID` → Get only paid EMIs
        """,
        manual_parameters=[
            openapi.Parameter(
                'customer_id',
                openapi.IN_QUERY,
                description="Customer ID",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'status',
                openapi.IN_QUERY,
                description="Filter by EMI status",
                type=openapi.TYPE_STRING,
                enum=['UPCOMING', 'DUE', 'PAID', 'OVERDUE', 'PARTIALLY_PAID'],
                required=False
            )
        ],
        responses={
            200: openapi.Response(
                description="EMI Schedule list with summary",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'customer_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'customer_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'finance_plan_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'summary': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'total_installments': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'paid_installments': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'upcoming_installments': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'overdue_installments': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'total_amount': openapi.Schema(type=openapi.TYPE_STRING),
                                'amount_paid': openapi.Schema(type=openapi.TYPE_STRING),
                                'balance_remaining': openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        ),
                        'schedules': openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_OBJECT))
                    }
                )
            ),
            400: "customer_id parameter is required",
            404: "No EMI schedules found for this customer"
        },
        tags=["Finance"]
    )
    def get(self, request):
        try:
            customer_id = request.query_params.get('customer_id')
            status_filter = request.query_params.get('status')
            
            if not customer_id:
                return Response(
                    {"error": "customer_id parameter is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get customer
            customer = get_object_or_404(Customer, id=customer_id)
            
            # Get finance plan for customer
            finance_plan = FinancePlan.objects.filter(
                credit_application__customer=customer
            ).order_by('-created_at').first()
            
            if not finance_plan:
                return Response(
                    {"error": f"No finance plan found for customer ID {customer_id}"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get EMI schedules
            emi_schedules = EMISchedule.objects.filter(
                finance_plan=finance_plan
            ).order_by('installment_number')
            
            # Apply status filter if provided
            if status_filter:
                emi_schedules = emi_schedules.filter(status=status_filter.upper())
            
            if not emi_schedules.exists():
                return Response(
                    {"error": f"No EMI schedules found for customer ID {customer_id}"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Calculate summary
            total_installments = emi_schedules.count()
            paid_count = emi_schedules.filter(status='PAID').count()
            upcoming_count = emi_schedules.filter(status='UPCOMING').count()
            overdue_count = emi_schedules.filter(status='OVERDUE').count()
            
            total_amount = sum(emi.installment_amount for emi in emi_schedules)
            amount_paid = sum(emi.amount_paid for emi in emi_schedules)
            balance_remaining = sum(emi.balance_remaining for emi in emi_schedules)
            
            # Serialize data
            serializer = EMIScheduleSerializerPlan(emi_schedules, many=True)
            
            response_data = {
                'customer_id': customer.id,
                'customer_name': f"{customer.first_name} {customer.last_name}",
                'finance_plan_id': finance_plan.id,
                'summary': {
                    'total_installments': total_installments,
                    'paid_installments': paid_count,
                    'upcoming_installments': upcoming_count,
                    'overdue_installments': overdue_count,
                    'total_amount': str(total_amount),
                    'amount_paid': str(amount_paid),
                    'balance_remaining': str(balance_remaining),
                },
                'schedules': serializer.data
            }
            
            logger.info(f"[EMIScheduleAPI] Retrieved {total_installments} EMI schedules for Customer ID={customer_id}")
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.exception("[EMIScheduleAPI] Error retrieving EMI schedules.")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --------------------------------------
# EMI Payment View
# --------------------------------------
class FinanceInstallmentPaymentView(APIView):
    """
    Handles EMI payment updates and rescheduling logic for Finance Plans.
    """

    @swagger_auto_schema(
        operation_summary="Create EMI Payment and Reschedule Future EMIs",
        operation_description=(
            "Records a payment for a specific EMI installment. "
            "If the payment is late, it deletes all future pending EMIs and regenerates them "
            "starting 15 days after the actual payment date.\n\n"
            "**Business Rules:**\n"
            "- Normal case → next EMIs every 15 days\n"
            "- If EMI is missed (Overdue) → schedule pauses\n"
            "- Once overdue EMI is paid → next EMI = 15 days after payment\n"
            "- Schedule resumes every 15 days"
        ),
        request_body=PaymentRecordSerializer,
        responses={
            200: "Payment recorded successfully and EMI schedule updated.",
            400: "Bad Request — Invalid data or duplicate payment.",
            404: "EMI schedule not found.",
            500: "Internal Server Error",
        },
        tags=["Finance"]
    )
    def post(self, request, emi_id):
        """
        Record payment for a specific EMI and handle rescheduling logic.
        """
        try:
            emi = EMISchedule.objects.select_related('finance_plan').get(id=emi_id)
            plan = emi.finance_plan

            amount_paid = Decimal(request.data.get('amount_paid', '0.00'))
            payment_method = request.data.get('payment_method', 'OTHER')

            if emi.status == 'PAID':
                return Response({"message": "This EMI is already paid."}, status=status.HTTP_400_BAD_REQUEST)

            # ---- Create Payment Record ----
            payment = PaymentRecord.objects.create(
                finance_plan=plan,
                emi_schedule=emi,
                payment_type='EMI',
                payment_method=payment_method,
                payment_amount=amount_paid,
                payment_date=timezone.now(),
                payment_status='COMPLETED',
                processed_by=request.user if request.user.is_authenticated else None,
                notes=f"Payment for EMI #{emi.installment_number}"
            )

            # ---- Update EMI ----
            emi.amount_paid += amount_paid
            emi.update_status()
            emi.paid_date = timezone.now().date()
            emi.save()

            logger.info(f"EMI #{emi.installment_number} paid for plan {plan.id} on {emi.paid_date}")

            # ---- Check for Late Payment ----
            if emi.due_date < emi.paid_date:
                logger.warning(f"EMI #{emi.installment_number} was late. Rescheduling future EMIs...")

                # Delete all upcoming unpaid EMIs
                future_emis = plan.emi_schedule.filter(
                    installment_number__gt=emi.installment_number
                ).exclude(status='PAID')
                deleted_count, _ = future_emis.delete()

                logger.info(f"Deleted {deleted_count} future EMIs for plan {plan.id}")

                # Recreate from new base date
                next_emi_date = emi.paid_date + timedelta(days=15)
                self.generate_future_emis(plan, next_emi_date, emi.installment_number + 1)

            return Response(
                {"message": "Payment recorded successfully and EMI schedule updated."},
                status=status.HTTP_200_OK
            )
        
        except EMISchedule.DoesNotExist:
            logger.error("EMI schedule not found.")
            return Response({"error": "EMI schedule not found."}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.exception("Error processing EMI payment.")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def generate_future_emis(self, plan, start_date, start_number):
        """
        Dynamically generate future EMIs every 15 days after a late payment.
        """
        total_installments = plan.selected_term
        emi_amount = plan.monthly_installment

        for i in range(start_number, total_installments + 1):
            EMISchedule.objects.create(
                finance_plan=plan,
                installment_number=i,
                due_date=start_date,
                installment_amount=emi_amount,
                balance_remaining=emi_amount,
                status='UPCOMING'
            )
            start_date += timedelta(days=15)
        logger.info(f"Regenerated EMIs #{start_number}–{total_installments} for plan {plan.id}")


# --------------------------------------
# Finance Report View
# --------------------------------------
class ReportsAPIView(APIView):
    """
    Generates a summarized financial and customer report for Admin, 
    Global Manager, and Finance Manager.
    """
    permission_classes = [CanViewReports]    

    @swagger_auto_schema(
        operation_summary="Get Common Reports (Admin / Global / Finance Manager)",
        operation_description="""
        Returns summarized reports including:
        - Total customers and applications  
        - Approval / Rejection / Pending counts  
        - Total financed amount and average down payment  
        - Risk tier distribution  
        """,
        responses={
            200:  CommonReportSerializer(),
            400: "Bad Request",
            500: "Internal Server Error",
        },
        tags=["Reports"]
    )
    def get(self, request):
        try:
            # --- Data Aggregation ---
            total_customers = Customer.objects.count()
            total_applications = CreditApplication.objects.count()

            approved_apps = CreditApplication.objects.filter(status='APPROVED').count()
            rejected_apps = CreditApplication.objects.filter(status='REJECTED').count()
            pending_apps = CreditApplication.objects.filter(status='PENDING').count()

            total_financed = FinancePlan.objects.aggregate(total=Sum('amount_to_finance'))['total'] or 0
            avg_down_payment = FinancePlan.objects.aggregate(avg=Avg('down_payment_percentage'))['avg'] or 0

            tier_counts = (
                FinancePlan.objects
                .values('risk_tier')
                .annotate(count=Count('id'))
                .order_by('risk_tier')
            )
            report_data = {
                "customers": total_customers,
                "applications": {
                    "total": total_applications,
                    "approved": approved_apps,
                    "rejected": rejected_apps,
                    "pending": pending_apps,
                },
                "financing": {
                    "total_financed": round(total_financed, 2),
                    "average_down_payment": round(avg_down_payment, 2),
                },
                "risk_tiers": list(tier_counts),
            }
            serializer = CommonReportSerializer(report_data)
            logger.info(f"Report generated successfully by user {request.user.username}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error generating report: {str(e)}", exc_info=True)
            return Response(
                {"error": "Failed to generate report", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
# --------------------------------------
# Regional-Wise Finance Report View
# --------------------------------------
class RegionWiseReportAPIView(APIView):
    """
    Generate region-wise sales and financing performance report.
    Sales Advisors can only see their own region.
    Admin, Global Manager, and Finance Manager can see all.
    """
    permission_classes = [CanViewReports]

    @swagger_auto_schema(
        operation_summary="Region-wise Sales Report",
        operation_description="Generates region-based performance reports. "
                              "Sales Advisors see their own region only.",
        responses={
            200: RegionWiseReportSerializer(),
            403: "Forbidden - insufficient permissions",
            500: "Internal Server Error"
        },
        tags=["Reports"]
    )
    def get(self, request):
        try:
            user = request.user

            # --- Region-based Filtering ---
            if user.is_sales_advisor():  
                # Sales Advisor → only their region
                region_filter = {"region": user.region}
            else:
                # Admin, Global Manager, Finance Manager → all regions
                region_filter = {}

            # --- Sales Summary ---
            region_data = (
                Customer.objects
                .filter(**region_filter)
                .values("region")
                .annotate(
                    total_customers=Count("id"),
                    total_applications=Count("credit_applications"),
                    approved=Count("credit_applications", filter=models.Q(credit_applications__status="APPROVED")),
                    rejected=Count("credit_applications", filter=models.Q(credit_applications__status="REJECTED")),
                )
                .order_by("region")
            )

            # --- Finance Summary ---
            finance_data = (
                FinancePlan.objects
                .filter(**region_filter)
                .values("region")
                .annotate(
                    total_financed=Sum("amount_to_finance"),
                    avg_down_payment=Avg("down_payment_percentage")
                )
                .order_by("region")
            )
            report = {
                "sales_summary": list(region_data),
                "finance_summary": list(finance_data),
            }
            serializer = RegionWiseReportSerializer(report)
            logger.info(f"Region-wise report generated by {user.username}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error generating region-wise report: {str(e)}", exc_info=True)
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )





# --------------------------------------------------------
# API: Get Payment Records by Customer ID
# --------------------------------------------------------
class PaymentRecordAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]
    
    @swagger_auto_schema(
        operation_summary="Get Payment Records by Customer ID",
        operation_description="""
        Retrieve all payment records for a specific customer.
        
        **Query Parameters:**
        - `customer_id` (required): Customer ID
        - `payment_type` (optional): Filter by type (DOWN_PAYMENT, EMI, LATE_FEE, FULL_SETTLEMENT)
        - `payment_status` (optional): Filter by status (PENDING, COMPLETED, FAILED, REFUNDED, CANCELLED)
        - `payment_method` (optional): Filter by method (PUNTO_PAGO, YAPPY, WESTERN_UNION, CASH, etc.)
        
        **Examples:**
        - `GET /api/finance/payments/?customer_id=5` → Get all payments
        - `GET /api/finance/payments/?customer_id=5&payment_type=EMI` → Get only EMI payments
        - `GET /api/finance/payments/?customer_id=5&payment_status=COMPLETED` → Get completed payments
        """,
        manual_parameters=[
            openapi.Parameter(
                'customer_id',
                openapi.IN_QUERY,
                description="Customer ID",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'payment_type',
                openapi.IN_QUERY,
                description="Filter by payment type",
                type=openapi.TYPE_STRING,
                enum=['DOWN_PAYMENT', 'EMI', 'LATE_FEE', 'FULL_SETTLEMENT'],
                required=False
            ),
            openapi.Parameter(
                'payment_status',
                openapi.IN_QUERY,
                description="Filter by payment status",
                type=openapi.TYPE_STRING,
                enum=['PENDING', 'COMPLETED', 'FAILED', 'REFUNDED', 'CANCELLED'],
                required=False
            ),
            openapi.Parameter(
                'payment_method',
                openapi.IN_QUERY,
                description="Filter by payment method",
                type=openapi.TYPE_STRING,
                enum=['PUNTO_PAGO', 'YAPPY', 'WESTERN_UNION', 'CASH', 'BANK_TRANSFER', 'OTHER'],
                required=False
            )
        ],
        responses={
            200: openapi.Response(
                description="Payment records list with summary",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'customer_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'customer_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'finance_plan_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'summary': openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'total_payments': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'completed_payments': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'pending_payments': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'total_amount_paid': openapi.Schema(type=openapi.TYPE_STRING),
                                'payment_methods': openapi.Schema(type=openapi.TYPE_OBJECT),
                            }
                        ),
                        'payments': openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Schema(type=openapi.TYPE_OBJECT))
                    }
                )
            ),
            400: "customer_id parameter is required",
            404: "No payment records found for this customer"
        },
        tags=["Finance"]
    )
    def get(self, request):
        try:
            customer_id = request.query_params.get('customer_id')
            payment_type = request.query_params.get('payment_type')
            payment_status = request.query_params.get('payment_status')
            payment_method = request.query_params.get('payment_method')
            
            if not customer_id:
                return Response(
                    {"error": "customer_id parameter is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get customer
            customer = get_object_or_404(Customer, id=customer_id)
            
            # Get finance plan for customer
            finance_plan = FinancePlan.objects.filter(
                credit_application__customer=customer
            ).order_by('-created_at').first()
            
            if not finance_plan:
                return Response(
                    {"error": f"No finance plan found for customer ID {customer_id}"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get payment records
            payments = PaymentRecord.objects.filter(
                finance_plan=finance_plan
            ).order_by('-payment_date')
            
            # Apply filters
            if payment_type:
                payments = payments.filter(payment_type=payment_type.upper())
            if payment_status:
                payments = payments.filter(payment_status=payment_status.upper())
            if payment_method:
                payments = payments.filter(payment_method=payment_method.upper())
            
            if not payments.exists():
                return Response(
                    {"error": f"No payment records found for customer ID {customer_id}"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Calculate summary
            total_payments = payments.count()
            completed_count = payments.filter(payment_status='COMPLETED').count()
            pending_count = payments.filter(payment_status='PENDING').count()
            
            total_amount_paid = sum(
                payment.payment_amount 
                for payment in payments.filter(payment_status='COMPLETED')
            )
            
            # Payment methods breakdown
            payment_methods_summary = {}
            for payment in payments.filter(payment_status='COMPLETED'):
                method = payment.get_payment_method_display()
                if method not in payment_methods_summary:
                    payment_methods_summary[method] = {
                        'count': 0,
                        'total_amount': Decimal('0.00')
                    }
                payment_methods_summary[method]['count'] += 1
                payment_methods_summary[method]['total_amount'] += payment.payment_amount
            
            # Convert Decimal to string for JSON serialization
            for method in payment_methods_summary:
                payment_methods_summary[method]['total_amount'] = str(
                    payment_methods_summary[method]['total_amount']
                )
            
            # Serialize data
            serializer = PaymentRecordSerializerPlan(payments, many=True)
            
            response_data = {
                'customer_id': customer.id,
                'customer_name': f"{customer.first_name} {customer.last_name}",
                'finance_plan_id': finance_plan.id,
                'summary': {
                    'total_payments': total_payments,
                    'completed_payments': completed_count,
                    'pending_payments': pending_count,
                    'total_amount_paid': str(total_amount_paid),
                    'payment_methods': payment_methods_summary,
                },
                'payments': serializer.data
            }
            
            logger.info(f"[PaymentRecordAPI] Retrieved {total_payments} payment records for Customer ID={customer_id}")
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.exception("[PaymentRecordAPI] Error retrieving payment records.")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ============================================================
# Standard Library Imports
# ============================================================
import logging
from decimal import Decimal
from datetime import timedelta, datetime
from collections import defaultdict
from decimal import Decimal

# swagger settup
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from customer.permissions import IsAuthenticatedUser
from django.conf import settings

# ============================================================
# Django Imports
# ============================================================
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils.dateparse import parse_date
from django.db.models import Count, Sum, Avg, Q, Prefetch
from django.db.models.functions import TruncWeek, TruncMonth
from django.utils import timezone
from django.db import models 
from django.core.cache import cache

# ============================================================
# Third-Party Imports
# ============================================================
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError
from drf_yasg.utils import swagger_auto_schema

# ============================================================
# Local Application Imports
# ============================================================
from .models import FinancePlan, PaymentRecord, EMISchedule, AutoFinancePlan, AuditLog,FinanceMultiple
from store.models import Region
from .utils.utils import get_device_price_with_cache
from home.permissions import CanViewReports
from customer.models import Customer, CreditApplication, CreditScore
from .serializers import (
    FinancePlanSerializer, 
    FinancePlanNestedSerializer,  
    FinancePlanCreateSerializer,
    AutoFinancePlanCreateSerializer,
    FinanceOverviewSerializer,
    AutoFinancePlanSerializer,   
    PaymentCreateSerializer,
    PaymentRecord3DSerializer,
    PaymentRecordSerializerPlan,
    FinanceRiskTierSerializer,
    FinanceCollectionAnalyticsSerializer,
    FinanceOverdueSerializer,
    EMIScheduleSerializerPlan,
    EMIScheduleSerializer,
    FinanceMultipleSerializer,
    EMIPaymentRequestSerializer,
    VerifyCustomerSerializer,
    FinanceFullDetailsSerializer,
)
from .permissions import IsAdminOrGlobalManager
from home.permissions import CanViewFinanceDetails
from .decision_engine import DecisionEngine, AutoDecisionEngine
from .utils.masking import mask_sensitive_data
from customer .utils import get_customer_monthly_income

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
            # -----Validate Input------------
            serializer = AutoFinancePlanCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            customer_id = serializer.validated_data["customer_id"]

            # -------3D Data Fetch ----------
            customer = (
                Customer.objects
                .prefetch_related('credit_applications', 'credit_scores')
                .only("id", "document_number")
                .get(id=customer_id)
            )

            # --------Get latest credit score (non-expired)----------
            credit_score = (
                CreditScore.objects.filter(customer=customer, is_expired=False)
                .only("id", "apc_score", "created_at")
                .order_by("-created_at")
                .first()
            )
            if not credit_score:
                return Response(
                    {"status": "error", "message": "No active credit score found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            apc_score = credit_score.apc_score

            # -------Get or create an active credit application-------------
            credit_app = (
                CreditApplication.objects.filter(
                    customer=customer, status__in=["PENDING_APPROVAL", "PRE_QUALIFIED"]
                ).order_by("-created_at").first()
            ) or CreditApplication.objects.create(customer=customer, device_price=0)

            # ----To get monthly income of customer---------
            document_number = customer.document_number
            monthly_income = get_customer_monthly_income(document_number)
            auto_plan, created = AutoFinancePlan.objects.get_or_create(
                credit_application=credit_app,
                defaults={
                    "customer": customer,
                    "credit_score": credit_score,
                    "apc_score": apc_score,
                    "risk_tier": "",
                    "customer_monthly_income": monthly_income,
                    "payment_capacity_factor": Decimal("0.00"),
                    "maximum_allowed_installment": Decimal("0.00"),
                    "minimum_down_payment_percentage": Decimal("0.00"),
                    "has_finance_plan": False,
                }
            )

            # If finance plan already exists for this auto plan
            if auto_plan.has_finance_plan:
                #  Create a NEW AutoPlan for new FinancePlan requests
                auto_plan = AutoFinancePlan.objects.create(
                    credit_application=credit_app,
                    customer=customer,
                    credit_score=credit_score,
                    apc_score=apc_score,
                    risk_tier="",
                    customer_monthly_income=monthly_income,
                    payment_capacity_factor=Decimal("0.00"),
                    maximum_allowed_installment=Decimal("0.00"),
                    minimum_down_payment_percentage=Decimal("0.00"),
                    has_finance_plan=False,
                )
            else:
                # Update existing autoplan since no FinancePlan created yet
                AutoFinancePlan.objects.filter(id=auto_plan.id).update(
                    credit_score=credit_score,
                    apc_score=apc_score,
                    customer_monthly_income=monthly_income,
                    risk_tier="",
                )

            engine = AutoDecisionEngine(auto_plan)
            engine_out=engine.run()

            # ---- Audit Logging ----
            AuditLog.objects.create(
                user=request.user,
                action_type="CREATE_AUTO_FINANCE_PLAN",
                customer=customer,
            )

            # ---- Success Response ----
            return Response(
                {
                    "status": "success",
                    "message": "Auto Finance Plan generated successfully.",
                    "data": {
                        "plan_id": auto_plan.id,
                        "customer_id": customer.id,
                        "credit_application_id": credit_app.id,
                        "apc_score": apc_score,
                        "risk_tier": auto_plan.risk_tier,
                        "monthly_income": str(engine_out.customer_monthly_income),
                        "maximum_allowed_installment": str(engine_out.maximum_allowed_installment),
                        "minimum_down_payment_percentage": str(engine_out.minimum_down_payment_percentage),
                        "allowed_plans": engine_out.allowed_plans,
                        "high_end_extra_percentage": engine_out.high_end_extra_percentage
                    },
                },
                status=status.HTTP_201_CREATED,
            )
        except Customer.DoesNotExist:
            return Response(
                {"status": "error", "message": "Customer not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.exception(f"Error in AutoFinancePlanView: {str(e)}")
            return Response(
                {"status": "error", "message": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

# --------------------------------------------------------
# API: Create or Get Finance Plan List
# --------------------------------------------------------
class FinancePlanAPIView(APIView):   
    """
    API to create a Finance Plan using Decision Engine from AutoFinancePlan data,
    and retrieve all or specific Finance Plans.
    """
    permission_classes=[IsAuthenticatedUser]
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
            # --------------------------------------------------------
            # Validate input
            # --------------------------------------------------------
            serializer = FinancePlanCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            temp_plan_id = data.get("temp_plan_id")
            device = data.get("device")

            # --------------------------------------------------------
            # Fetch AutoFinancePlan or base FinancePlan data
            # --------------------------------------------------------
            finance_plan = (
            AutoFinancePlan.objects.select_related(
                "customer",
                "customer__created_by",
                "customer__created_by__store",
                "customer__created_by__store__region",
                "credit_application",
                "credit_score",                
            )
            .filter(id=temp_plan_id)
            .first()
            )
            if not finance_plan:
                return Response({
                    "status": "error",
                    "message": "AutoFinancePlan not found."
                }, status=status.HTTP_404_NOT_FOUND)

            # --------------------------------------------------------
            # Get device price (from cache or DB)
            # --------------------------------------------------------
            device_price = data.get("device_price") or get_device_price_with_cache(device)
            # --------------------------------------------------------
            # Prepare / Update FinancePlan from AutoFinancePlan
            # --------------------------------------------------------
            finance_plan_data = {                
                "credit_application": finance_plan.credit_application,
                "credit_score": finance_plan.credit_score,
                "apc_score": finance_plan.apc_score,
                "risk_tier": finance_plan.risk_tier or "",
                "customer_monthly_income": finance_plan.customer_monthly_income,
                "payment_capacity_factor": finance_plan.payment_capacity_factor or Decimal("0.00"),
                "maximum_allowed_installment": finance_plan.maximum_allowed_installment or Decimal("0.00"),
                "minimum_down_payment_percentage": finance_plan.minimum_down_payment_percentage or Decimal("0.00"),

                # Device & Payment info
                "device": device,
                "device_price": device_price,
                "actual_down_payment": data.get("actual_down_payment"),
                "selected_term": data["choosed_allowed_plans"]["selected_term"],
                "installment_frequency_days": data["choosed_allowed_plans"]["installment_frequency_days"],

                # Placeholder computed fields (Decision Engine will update)
                "down_payment_percentage": Decimal("0.00"),
                "amount_to_finance": Decimal("0.00"),
                "monthly_installment": Decimal("0.00"),
                "total_amount_payable": Decimal("0.00"),
                "installment_to_income_ratio": Decimal("0.00"),
            }            
            finance_plan_data["created_by"] = request.user
            finance_plan_data["store"] = getattr(request.user, "store", None)

            engine_input, created = FinancePlan.objects.get_or_create(
                credit_application=finance_plan.credit_application,
                created_by=request.user,
                store=getattr(request.user, "store", None),
                defaults=finance_plan_data
            )
             # Mark AutoPlan as finalized
            finance_plan.has_finance_plan = True
            finance_plan.save(update_fields=["has_finance_plan"])         

            logger.info(f"[FinancePlanAPI] DecisionEngine input: {engine_input}")

            # --------------------------------------------------------
            # Run Decision Engine
            # --------------------------------------------------------
            logger.info(f"[FinancePlanAPI] Running Decision Engine")
            engine = DecisionEngine(engine_input)
            final_plan = engine.run()
            final_plan.save()
            
            #Audit Log          
            AuditLog.objects.create(
            user=request.user,
            action_type="FINANCE_PLAN_CREATED",
            description=f"Finance plan created (AutoPlan ID: {temp_plan_id})",
            metadata={
                "auto_finance_plan_id": temp_plan_id,
                "device_id": device.id if device else None,
                "device_price": str(device_price),
                }
            )

            # --------------------------------------------------------
            # Serialize response
            # --------------------------------------------------------
            serialized_data = FinancePlanSerializer(final_plan).data

            # --- Add device details ---
            device = getattr(final_plan, "device", None)

            device_info = {
                "category": getattr(device.brand.category, "name", None)
                if getattr(device, "brand", None) and getattr(device.brand, "category", None)
                else None,
                "brand": getattr(device.brand, "name", None)
                if getattr(device, "brand", None)
                else None,
                "model": getattr(device, "model_name", None),
            }
            return Response({
            "status": "success",
            "message": "Finance Plan created successfully.",
            "data": {
                **serialized_data,
                "device_details": device_info
            }
            }, status=status.HTTP_201_CREATED)
        except ValidationError as ve:
            return Response({
                "status": "error",
                "message": "Invalid input data.",
                "details": ve.detail
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.exception("[FinancePlanAPI] Unexpected error creating Finance Plan.")
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # --------------------------------------------------------
    # GET: List All Plans or Retrieve by ID
    # --------------------------------------------------------
    @swagger_auto_schema(
    operation_summary="Retrieve Finance Plan(s)",
    operation_description="""
    Retrieve Finance Plan records with multiple filtering options.

    **Role-based Access:**
    - **Customers:** Only their own plans  
    - **FinanceManager / Admin / GlobalManager:** All plans  
    - **SalesAdvisor:** Plans within their region  
    - **StoreManager:** Plans under their store  
    - **SalesPerson:** Plans created by them  

    **Optional Filters:**  
    - `id`: Finance Plan ID  
    - `customer_id`: Filter by Customer ID  
    - `product_id`: Filter by Product ID  
    - `emi_id`: Filter by EMI ID  
    - `apc_score`: Filter by APC Score  
    - `start_date`: Filter by creation date (start range, format YYYY-MM-DD)  
    - `end_date`: Filter by creation date (end range, format YYYY-MM-DD)  
    - `updated_start_date`: Filter by last updated date (start range, format YYYY-MM-DD)  
    - `updated_end_date`: Filter by last updated date (end range, format YYYY-MM-DD)
    """,
    manual_parameters=[
        openapi.Parameter("customer_id", openapi.IN_QUERY, description="Filter by Customer ID", type=openapi.TYPE_INTEGER),
        openapi.Parameter("product_id", openapi.IN_QUERY, description="Filter by Product ID", type=openapi.TYPE_INTEGER),
        openapi.Parameter("emi_id", openapi.IN_QUERY, description="Filter by EMI ID", type=openapi.TYPE_INTEGER),
        openapi.Parameter("apc_score", openapi.IN_QUERY, description="Filter by APC Score", type=openapi.TYPE_INTEGER),
        openapi.Parameter("start_date", openapi.IN_QUERY, description="Filter by creation date (start range, format YYYY-MM-DD)", type=openapi.TYPE_STRING, format="date"),
        openapi.Parameter("end_date", openapi.IN_QUERY, description="Filter by creation date (end range, format YYYY-MM-DD)", type=openapi.TYPE_STRING, format="date"),
        openapi.Parameter("updated_start_date", openapi.IN_QUERY, description="Filter by last updated date (start range, format YYYY-MM-DD)", type=openapi.TYPE_STRING, format="date"),
        openapi.Parameter("updated_end_date", openapi.IN_QUERY, description="Filter by last updated date (end range, format YYYY-MM-DD)", type=openapi.TYPE_STRING, format="date"),
    ],
    responses={200: "Finance Plan List"},
    tags=["Finance"]
    )
    def get(self, request):
        try:
            user = request.user
            user_role = getattr(user, "role", "Customer")

            # --------------------- Base Query ---------------------
            finance_qs = (
                FinancePlan.objects
                .select_related(
                    "credit_application",
                    "credit_application__customer",
                    "credit_application__customer__created_by",
                    "credit_application__customer__created_by__store",
                    "credit_application__customer__created_by__store__region",
                    "credit_score",
                    "device"
                )
                .prefetch_related("emi_schedule")
                .order_by("-created_at")
            )

            # --------------------- Filters ---------------------
            emi_id = request.query_params.get("emi_id")
            customer_id = request.query_params.get("customer_id")
            product_id = request.query_params.get("product_id")
            apc_score = request.query_params.get("apc_score")
            start_date = request.query_params.get("start_date")
            end_date = request.query_params.get("end_date")
            updated_start_date = request.query_params.get("updated_start_date")
            updated_end_date = request.query_params.get("updated_end_date")

            if emi_id:
                finance_qs = finance_qs.filter(emi_schedule__id=emi_id)
            if customer_id:
                finance_qs = finance_qs.filter(credit_application__customer__id=customer_id)
            if product_id:
                finance_qs = finance_qs.filter(device__id=product_id)
            if apc_score:
                finance_qs = finance_qs.filter(apc_score=apc_score)

            # --------------------- Date Filters ---------------------
            # Filter by created_at range
            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
                    finance_qs = finance_qs.filter(created_at__gte=start_date_obj)
                except ValueError:
                    return Response({
                        "status": "error",
                        "message": "Invalid start_date format. Use YYYY-MM-DD"
                    }, status=status.HTTP_400_BAD_REQUEST)

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                    finance_qs = finance_qs.filter(created_at__lt=end_date_obj)
                except ValueError:
                    return Response({
                        "status": "error",
                        "message": "Invalid end_date format. Use YYYY-MM-DD"
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Filter by updated_at range
            if updated_start_date:
                try:
                    updated_start_obj = datetime.strptime(updated_start_date, "%Y-%m-%d")
                    finance_qs = finance_qs.filter(updated_at__gte=updated_start_obj)
                except ValueError:
                    return Response({
                        "status": "error",
                        "message": "Invalid updated_start_date format. Use YYYY-MM-DD"
                    }, status=status.HTTP_400_BAD_REQUEST)

            if updated_end_date:
                try:
                    updated_end_obj = datetime.strptime(updated_end_date, "%Y-%m-%d") + timedelta(days=1)
                    finance_qs = finance_qs.filter(updated_at__lt=updated_end_obj)
                except ValueError:
                    return Response({
                        "status": "error",
                        "message": "Invalid updated_end_date format. Use YYYY-MM-DD"
                    }, status=status.HTTP_400_BAD_REQUEST)

            # --------------------- Role-Based Access ---------------------
            if user_role in ['admin', 'global_manager', 'financial_manager']:
                pass
            elif user_role == "store_manager":
                finance_qs = finance_qs.filter(
                    credit_application__customer__created_by__store=user.store
                )
            elif user_role == "sales_advisor":
                finance_qs = finance_qs.filter(
                    credit_application__customer__created_by__store__region=user.store.region
                )
            elif user_role == "salesperson":
                finance_qs = finance_qs.filter(
                    credit_application__customer__created_by=user
                )
            else:
                customer = Customer.objects.filter(created_by=user).first()
                if not customer:
                    return Response({
                        "status": "error",
                        "message": "No Customer record linked to this user."
                    }, status=status.HTTP_400_BAD_REQUEST)
                finance_qs = finance_qs.filter(
                    credit_application__customer=customer
                )

            # --------------------Caching ---------------------
            cache_key = (
                f"financeplans_{user_role}_"
                f"{emi_id or 'any'}_"
                f"{customer_id or 'any'}_"
                f"{product_id or 'any'}_"
                f"{apc_score or 'any'}_"
                f"{start_date or 'any'}_"
                f"{end_date or 'any'}_"
                f"{updated_start_date or 'any'}_"
                f"{updated_end_date or 'any'}"
            )
            cached_data = cache.get(cache_key)
            if cached_data:
                return Response(cached_data, status=status.HTTP_200_OK)

            # --------------------- Pagination ---------------------
            paginator = FinancePlanPagination()
            paginated_qs = paginator.paginate_queryset(finance_qs, request)
            serializer = FinancePlanSerializer(paginated_qs, many=True)
            masked_data = mask_sensitive_data(serializer.data, user_role)
            response_data = {
                "status": "success",
                "message": "Finance plans retrieved successfully.",
                "count": finance_qs.count(),
                "data": masked_data,
            }

            # --------------------- Audit Log ---------------------
            AuditLog.objects.create(
                user=user,
                action_type="FINANCE_PLAN_LIST_VIEWED",
                description="Viewed Finance Plan List.",
                metadata={"filters": request.query_params.dict(), "role": user_role},
                ip_address=request.META.get("REMOTE_ADDR")
            )
            cache.set(cache_key, response_data, timeout=60)
            return paginator.get_paginated_response(response_data)

        except Exception as e:
            logger.exception("[FinancePlanAPIView] Error retrieving Finance Plans.")
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            

# --------------------------------------------------------
# API: Get Specific Plan Using ID
# --------------------------------------------------------
class FinancePlanDetailAPIView(APIView):
    """
    API: Retrieve a Single Finance Plan by ID (3D Fetch + Role-based Access)
    """
    permission_classes = [IsAuthenticatedUser]
    @swagger_auto_schema(
        operation_summary="Retrieve a single Finance Plan by ID",
        operation_description="""
        Fetches a detailed finance plan record by its unique plan ID.
        Includes 3-level relational data (Finance → Customer → Device → Transactions)
        and applies role-based access restrictions.
        
        Example:
        - `GET /api/finance/plan/12/`
        """,
        responses={200: "Finance Plan Details", 404: "Finance Plan not found"},
        tags=["Finance"]
    )
    def get(self, request, plan_id):
        try:
            user = request.user
            user_role = getattr(user, "role", "Customer")

            finance_qs = (
                FinancePlan.objects
                .select_related(
                    "credit_application",
                    "credit_application__customer",
                    "credit_application__customer__created_by",
                    "credit_application__customer__created_by__store",
                    "credit_application__customer__created_by__store__region",
                    "credit_score",
                    "device",
                    "device__brand"
                )
                .prefetch_related("emi_schedule", "payments")
            )

            plan = get_object_or_404(finance_qs, id=plan_id)

            # --------------------- Role-Based Access ---------------------
            if user_role in ['admin', 'global_manager', 'financial_manager']:
                pass
            elif user_role == "sales_manager":
                finance_qs = finance_qs.filter(credit_application__customer__created_by__store=user.store)
            elif user_role == "sales_advisor":
                finance_qs = finance_qs.filter(credit_application__customer__created_by__store__region=user.store.region)
            elif user_role == "salesperson":
                finance_qs = finance_qs.filter(credit_application__customer__created_by=user)
            else:
                # If the logged-in user is a customer
                finance_qs = finance_qs.filter(credit_application__customer__created_by=user)
            serializer = FinancePlanSerializer(plan)
            masked_data = mask_sensitive_data(serializer.data, user_role)

            # Audit log
            AuditLog.objects.create(
            user=user,
            action_type="FINANCE_PLAN_VIEWED", 
            description=f"Viewed Finance Plan ID={id} by {user.username if user else 'Anonymous'}",
            metadata={"role": user_role},
            ip_address=request.META.get("REMOTE_ADDR")
            )
            return Response({
                "status": "success",
                "message": f"Finance Plan ID={plan_id} retrieved successfully.",
                "data": masked_data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("[FinancePlanDetailAPIView] Error retrieving Finance Plan.")
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
    """   
    Provides analytics and detailed payment records for Finance Collections.
    Includes:
    - Total installments, collected, pending, overdue
    - Customers with overdue
    - Region-wise collection summary
    - Flexible filters (date, status, method, type, store, region, etc.)
    """

    permission_classes = [IsAuthenticatedUser]
    @swagger_auto_schema(
        operation_summary="Finance Collection Analytics",
        operation_description="""
        Provides analytics and detailed payment collection data for finance plans.

        **Role-based Access:**
        - **Superuser / Admin / FinanceManager / GlobalManager:** Full access to all records  
        - **RegionalManager:** Payments belonging to stores within their region  
        - **StoreManager:** Payments under their store  
        - **SalesPerson:** Payments created by them  
        - **Customer:** Payments for their own finance plans only  

        **Analytics Included:**
        - Total installments, collected, pending, overdue
        - Customers with overdue
        - Region-wise collection summary
        - Collection rate (percentage of collected vs total due)

        **Optional Filters:**  
        - `payment_status`: Filter by Payment Status (Pending, Completed, Failed, Refunded, Cancelled)  
        - `payment_method`: Filter by Payment Method (Punto Pago, Yappy, Western Union, Cash, Bank Transfer, Other)  
        - `payment_type`: Filter by Payment Type (Down Payment, EMI, Late Fee, Full Settlement)  
        - `region_id`: Filter by Region ID  
        - `store_id`: Filter by Store ID  
        - `customer_id`: Filter by Customer ID  
        - `finance_plan_id`: Filter by Finance Plan ID  
        - `start_date`: Filter by Payment Start Date (YYYY-MM-DD)  
        - `end_date`: Filter by Payment End Date (YYYY-MM-DD)
        """,
        manual_parameters=[
            openapi.Parameter("payment_status", openapi.IN_QUERY, description="Filter by Payment Status", type=openapi.TYPE_STRING),
            openapi.Parameter("payment_method", openapi.IN_QUERY, description="Filter by Payment Method", type=openapi.TYPE_STRING),
            openapi.Parameter("payment_type", openapi.IN_QUERY, description="Filter by Payment Type", type=openapi.TYPE_STRING),
            openapi.Parameter("region_id", openapi.IN_QUERY, description="Filter by Region ID", type=openapi.TYPE_INTEGER),
            openapi.Parameter("store_id", openapi.IN_QUERY, description="Filter by Store ID", type=openapi.TYPE_INTEGER),
            openapi.Parameter("customer_id", openapi.IN_QUERY, description="Filter by Customer ID", type=openapi.TYPE_INTEGER),
            openapi.Parameter("finance_plan_id", openapi.IN_QUERY, description="Filter by Finance Plan ID", type=openapi.TYPE_INTEGER),
            openapi.Parameter("start_date", openapi.IN_QUERY, description="Filter by Payment Start Date (YYYY-MM-DD)", type=openapi.TYPE_STRING, format="date"),
            openapi.Parameter("end_date", openapi.IN_QUERY, description="Filter by Payment End Date (YYYY-MM-DD)", type=openapi.TYPE_STRING, format="date"),
        ],
        responses={200: FinanceCollectionAnalyticsSerializer},
        tags=["Finance"]
    )
    def get(self, request):
        try:
            user = request.user
            user_role = getattr(user, "role", "Customer")

            # ==================================================
            # Base Query
            # ==================================================
            qs = (
                PaymentRecord.objects.select_related(
                    "finance_plan",
                    "finance_plan__store",                
                    "finance_plan__store__region",        
                    "finance_plan__credit_application",
                    "finance_plan__credit_application__customer",
                    "finance_plan__credit_score",
                    "finance_plan__device",
                    "emi_schedule",
                )
                .prefetch_related("emi_schedule__payments")
                .order_by("-created_at")
            )

            # ==================================================
            # Role-Based Access
            # ==================================================
            if user.is_superuser or user_role in ['admin', 'global_manager', 'financial_manager']:
                pass  # full access
            elif user_role == "sales_advisor":
                region = getattr(user, "region", None)
                qs = qs.filter(finance_plan__store__region=region) if region else qs.none()
            elif user_role == "store_manager":
                store = getattr(user, "store", None)
                qs = qs.filter(finance_plan__store=store) if store else qs.none()
            elif user_role == "salesperson":
                qs = qs.filter(finance_plan__created_by=user)
            elif user_role == "Customer":
                qs = qs.filter(finance_plan__credit_application__customer=user)
            else:
                qs = qs.none()

            # ==================================================
            # Query Filters (status, type, date, etc.)
            # ==================================================
            params = request.query_params
            filters = {
                "payment_status__iexact": params.get("payment_status"),
                "payment_method__iexact": params.get("payment_method"),
                "payment_type__iexact": params.get("payment_type"),
                "finance_plan__store__region__id": params.get("region_id"),
                "finance_plan__store__id": params.get("store_id"),
                "finance_plan__credit_application__customer__id": params.get("customer_id"),
                "finance_plan__id": params.get("finance_plan_id"),
            }

            for key, value in filters.items():
                if value:
                    qs = qs.filter(**{key: value})

            start_date = params.get("start_date")
            end_date = params.get("end_date")

            if start_date:
                try:
                    qs = qs.filter(payment_date__date__gte=datetime.strptime(start_date, "%Y-%m-%d"))
                except ValueError:
                    pass
            if end_date:
                try:
                    qs = qs.filter(payment_date__date__lte=datetime.strptime(end_date, "%Y-%m-%d"))
                except ValueError:
                    pass

            # ==================================================
            # Analytics Calculation
            # ==================================================
            total_installments = qs.count()
            total_collected = float(qs.filter(payment_status="COMPLETED").aggregate(total=Sum("payment_amount"))["total"] or 0)
            total_due = float(qs.aggregate(total=Sum("payment_amount"))["total"] or 0)
            total_pending = total_due - total_collected
            collection_rate = (total_collected / total_due * 100) if total_due > 0 else 0.0

            # --- Overdue Analytics ---
            overdue_qs = qs.filter(
                Q(payment_status__in=["PENDING", "FAILED"]) &
                Q(emi_schedule__due_date__lt=timezone.now().date())
            )
            total_overdue = float(overdue_qs.aggregate(total=Sum("payment_amount"))["total"] or 0)
            total_overdue_installments = overdue_qs.count()
            customers_with_overdue = overdue_qs.values_list(
                "finance_plan__credit_application__customer", flat=True
            ).distinct().count()

            # ==================================================
            # Region Summary
            # ==================================================
            region_summary = defaultdict(lambda: {
                "region_name": "",
                "total_installments": 0,
                "total_collected": 0.0,
                "total_pending": 0.0,
                "total_overdue": 0.0,
            })

            for payment in qs:
                store = payment.finance_plan.store
                region = getattr(store.region, "name", None) if store else None
                if not region:
                    continue

                region_data = region_summary[region]
                region_data["region_name"] = region
                region_data["total_installments"] += 1

                amt = float(payment.payment_amount or 0)
                if payment.payment_status == "COMPLETED":
                    region_data["total_collected"] += amt
                elif payment.payment_status in ["PENDING", "FAILED"]:
                    region_data["total_pending"] += amt

                if payment.emi_schedule and payment.emi_schedule.due_date < timezone.now().date() and payment.payment_status in ["PENDING", "FAILED"]:
                    region_data["total_overdue"] += amt

            # ==================================================
            # Serialize Analytics Data
            # ==================================================
            analytics_data = {
                "total_installments": total_installments,
                "total_collected": round(total_collected, 2),
                "total_pending": round(total_pending, 2),
                "total_overdue": round(total_overdue, 2),
                "total_overdue_installments": total_overdue_installments,
                "collection_rate": round(collection_rate, 2),
                "customers_with_overdue": customers_with_overdue,
                "regions_summary": list(region_summary.values()),
            }

            serializer = FinanceCollectionAnalyticsSerializer(analytics_data)
            meta = serializer.data

            # ==================================================
            # Pagination & Results
            # ==================================================
            paginator = FinancePlanPagination()
            page = paginator.paginate_queryset(qs, request)

            results = []
            for p in page:
                fp = p.finance_plan
                store = getattr(fp, "store", None)
                region = getattr(store, "region", None)
                dev = getattr(fp, "device", None)
                ca = getattr(fp, "credit_application", None)
                cust = getattr(ca, "customer", None)
                emi = getattr(p, "emi_schedule", None)

                item = {
                    "payment_id": p.id,
                    "payment_amount": float(p.payment_amount or 0),
                    "payment_type": p.payment_type,
                    "payment_method": p.payment_method,
                    "payment_status": p.payment_status,
                    "payment_date": p.payment_date.isoformat() if p.payment_date else None,
                    "finance_plan": {
                        "finance_plan_id": fp.id,
                        "amount": float(fp.amount_to_finance or 0),
                        "store": getattr(store, "name", None),
                        "region": getattr(region, "name", None),
                        "device": {"id": dev.id, "model_name": dev.model_name} if dev else None,
                       "customer": {
                        "id": cust.id,
                        "name": f"{cust.first_name} {cust.last_name}",
                        "phone": getattr(cust, "phone", None)} if cust else None,
                    },
                    "emi_schedule": {
                        "emi_id": emi.id if emi else None,
                        "due_date": emi.due_date.isoformat() if emi and emi.due_date else None,
                        "amount_due": float(emi.amount_due or 0) if emi else None,
                        "status": getattr(emi, "status", None) if emi else None,
                    },
                }
                results.append(mask_sensitive_data(item, user_role))

            # ==================================================
            # Audit Log
            # ==================================================
            try:
                AuditLog.objects.create(
                    user=user if user.is_authenticated else None,
                    action_type="FINANCE_COLLECTIONS_VIEWED",
                    description=f"{user_role} viewed finance collections analytics.",
                    metadata={
                        "role": user_role,
                        "filters": request.query_params.dict(),
                        "total_records": total_installments,
                    },
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
            except Exception as log_error:
                logger.warning(f"Audit logging failed: {log_error}")

            # ==================================================
            # Response
            # ==================================================
            payload = {
                "meta": meta,
                "results": results,
                "page": paginator.page.number if paginator.page else 1,
                "page_size": paginator.get_page_size(request),
            }

            return paginator.get_paginated_response(payload)

        except Exception as e:
            logger.error(f"Error generating finance collection analytics: {str(e)}", exc_info=True)
            return Response(
                {"detail": "Failed to generate finance collection analytics."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        
        
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
        

# --------------------------------------------------------
# API: Get EMI Schedule (Single or Multiple Customers)
# --------------------------------------------------------
class EMIScheduleAPIView(APIView):
    """
    Retrieve EMI schedules with flexible filters & role-based access.
    Roles:
        - Admin / FinanceManager / GlobalManager -> Full access
        - RegionalManager / SalesAdvisor -> Only for their region
        - StoreManager -> Only EMIs in their store
        - SalesPerson -> Only EMIs created by them
        - Customer -> Only their own EMIs
    """
    permission_classes = [IsAuthenticatedUser]
    pagination_class = FinancePlanPagination  

    @swagger_auto_schema(
        operation_summary="Retrieve EMI Schedules (Single or Multiple Customers)",
        operation_description="""
        Retrieve EMI schedules with role-based access and multiple filter options.
        Works for both single customer and multi-customer queries based on role access.
        """,
        manual_parameters=[
            openapi.Parameter("customer_id", openapi.IN_QUERY, description="Customer ID (optional)", type=openapi.TYPE_INTEGER),
            openapi.Parameter("finance_plan_id", openapi.IN_QUERY, description="Finance Plan ID (optional)", type=openapi.TYPE_INTEGER),
            openapi.Parameter("status", openapi.IN_QUERY, description="Filter by EMI status", type=openapi.TYPE_STRING, enum=["UPCOMING", "DUE", "PAID", "OVERDUE", "PARTIALLY_PAID"]),
            openapi.Parameter("installment_number", openapi.IN_QUERY, description="Installment number", type=openapi.TYPE_INTEGER),
            openapi.Parameter("due_from", openapi.IN_QUERY, description="Filter by due_date ≥ (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter("due_to", openapi.IN_QUERY, description="Filter by due_date ≤ (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter("paid_from", openapi.IN_QUERY, description="Filter by paid_date ≥ (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter("paid_to", openapi.IN_QUERY, description="Filter by paid_date ≤ (YYYY-MM-DD)", type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE),
            openapi.Parameter("order_by", openapi.IN_QUERY, description="Order results (default: installment_number)", type=openapi.TYPE_STRING),
        ],
        tags=["Finance"]
    )
    def get(self, request):
        try:
            user = request.user
            role = getattr(user, "role", "").lower()

            # ----------------------------
            # Query Params
            # ----------------------------
            customer_id = request.query_params.get("customer_id")
            finance_plan_id = request.query_params.get("finance_plan_id")
            status_filter = request.query_params.get("status")
            installment_number = request.query_params.get("installment_number")
            due_from = request.query_params.get("due_from")
            due_to = request.query_params.get("due_to")
            paid_from = request.query_params.get("paid_from")
            paid_to = request.query_params.get("paid_to")
            order_by = request.query_params.get("order_by", "installment_number")

            # Validate order_by (prevent '14'-like values)
            allowed_order_fields = [
                "installment_number", "due_date", "paid_date",
                "status", "created_at", "-installment_number", "-due_date", "-paid_date", "-created_at"
            ]
            if order_by not in allowed_order_fields:
                order_by = "installment_number"

            # ----------------------------
            # Base Query (3D Fetching)
            # ----------------------------
            emi_qs = EMISchedule.objects.select_related(
                "finance_plan",
                "finance_plan__credit_application__customer",
                "finance_plan__store__region",
                "finance_plan__device",
                "finance_plan__created_by",
            )

            # ----------------------------
            # Apply Role-Based Filtering
            # ----------------------------
            if role in ('admin', 'global_manager', 'financial_manager'):
                pass  # Full access

            elif role == "sales_advisor":
                region = getattr(user, "region", None)
                if region:
                    emi_qs = emi_qs.filter(finance_plan__store__region=region)
                else:
                    return Response({"error": "Region not assigned to user"}, status=403)

            elif role == "store_manager":
                store = getattr(user, "store", None)
                if store:
                    emi_qs = emi_qs.filter(finance_plan__store=store)
                else:
                    return Response({"error": "Store not assigned to user"}, status=403)

            elif role == "salesperson":
                emi_qs = emi_qs.filter(finance_plan__created_by=user)

            elif role == "Customer":
                emi_qs = emi_qs.filter(finance_plan__credit_application__customer__user=user)

            else:
                return Response({"error": "Unauthorized role"}, status=403)

            # ----------------------------
            # Apply Filters (Optional)
            # ----------------------------
            if finance_plan_id:
                emi_qs = emi_qs.filter(finance_plan_id=int(finance_plan_id))
            if customer_id:
                emi_qs = emi_qs.filter(finance_plan__credit_application__customer_id=int(customer_id))
            if status_filter:
                emi_qs = emi_qs.filter(status=status_filter.upper())
            if installment_number:
                emi_qs = emi_qs.filter(id=int(installment_number))

            if due_from and (parsed := parse_date(due_from)):
                emi_qs = emi_qs.filter(due_date__gte=parsed)
            if due_to and (parsed := parse_date(due_to)):
                emi_qs = emi_qs.filter(due_date__lte=parsed)
            if paid_from and (parsed := parse_date(paid_from)):
                emi_qs = emi_qs.filter(paid_date__gte=parsed)
            if paid_to and (parsed := parse_date(paid_to)):
                emi_qs = emi_qs.filter(paid_date__lte=parsed)

            emi_qs = emi_qs.order_by(order_by)

            if not emi_qs.exists():
                return Response({"error": "No EMI schedules found matching filters or permissions"}, status=404)

            # ----------------------------
            # Aggregations & Summary
            # ----------------------------
            total_installments = emi_qs.count()
            paid_count = emi_qs.filter(status="PAID").count()
            partially_paid_count = emi_qs.filter(status="PARTIALLY_PAID").count()
            upcoming_count = emi_qs.filter(status="UPCOMING").count()
            overdue_count = emi_qs.filter(status="OVERDUE").count()

            totals = emi_qs.aggregate(
                total_amount=Sum("installment_amount"),
                amount_paid=Sum("amount_paid"),
                balance_remaining=Sum("balance_remaining"),
            )

            # ----------------------------
            # Pagination
            # ----------------------------
            paginator = self.pagination_class()
            page = paginator.paginate_queryset(emi_qs, request, view=self)
            serializer = EMIScheduleSerializerPlan(page, many=True)

            response_data = {
                "access_role": role,
                "filters_applied": {
                    "customer_id": customer_id,
                    "finance_plan_id": finance_plan_id,
                    "status": status_filter,
                    "installment_number": installment_number,
                    "due_from": due_from,
                    "due_to": due_to,
                    "paid_from": paid_from,
                    "paid_to": paid_to,
                },
                "summary": {
                    "total_installments": total_installments,
                    "paid_installments": paid_count,
                    "partially_paid_installments": partially_paid_count,
                    "upcoming_installments": upcoming_count,
                    "overdue_installments": overdue_count,
                    "total_amount": str(totals["total_amount"] or Decimal("0.00")),
                    "amount_paid": str(totals["amount_paid"] or Decimal("0.00")),
                    "balance_remaining": str(totals["balance_remaining"] or Decimal("0.00")),
                },
                "schedules": serializer.data,
            }

            # ----------------------------
            # Audit Logging (Non-Blocking)
            # ----------------------------
            try:
                AuditLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    action_type="VIEW_EMI_SCHEDULE",
                    description=f"User viewed EMI schedules | Role={role.upper()} | Filters={dict(request.query_params)}",
                    metadata={
                        "filters": dict(request.query_params),
                        "results_count": total_installments,
                        "access_role": role,
                    },
                )
            except Exception as log_error:
                logger.warning(f"[AuditLog Warning] Failed to record view event: {log_error}")

            return paginator.get_paginated_response(response_data)

        except Exception as e:
            logger.exception("[EMIScheduleAPI] Error retrieving EMI schedules.")
            return Response({"error": str(e)}, status=500)


# --------------------------------------
# EMI Payment View
# --------------------------------------
class FinanceInstallmentPaymentView(APIView):
    """
    Handles EMI payment updates and rescheduling logic for Finance Plans.
    """
    permission_classes = [IsAuthenticatedUser]

    @swagger_auto_schema(
        operation_summary="Create EMI Payment and Reschedule Future EMIs",
        operation_description=(
            "Records a payment for a specific EMI installment. "
            "If the payment is late, it deletes all future pending EMIs and regenerates them "
            "starting after the chosen interval_days.\n\n"
            "**Business Rules:**\n"
            "- Normal case → next EMIs every interval_days\n"
            "- If EMI is missed (Overdue) → schedule pauses\n"
            "- Once overdue EMI is paid → next EMI = interval_days after payment\n"
            "- Schedule resumes at same interval"
        ),
        request_body=EMIPaymentRequestSerializer,
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
            # -----------------------------------------------------------------
            #  Fetch EMI with full related details (3D fetch)
            # -----------------------------------------------------------------
            emi = (
                EMISchedule.objects
                .select_related(
                    "finance_plan",
                    "finance_plan__credit_application",
                    "finance_plan__credit_application__customer",
                    "finance_plan__device",
                    "finance_plan__store",
                    "finance_plan__store__region"
                )
                .get(id=emi_id)
            )
            plan = emi.finance_plan
            store = plan.store

            amount_paid = Decimal(request.data.get('amount_paid', '0.00'))
            payment_method = request.data.get('payment_method', 'OTHER')

            if emi.status == 'PAID':
                return Response({"message": "This EMI is already paid."}, status=status.HTTP_400_BAD_REQUEST)

            # -----------------------------------------------------------------
            #  Create Payment Record
            # -----------------------------------------------------------------
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

            # -----------------------------------------------------------------
            # Apply Payment to EMI 
            # -----------------------------------------------------------------
            payment.apply_to_emi()

            # -----------------------------------------------------------------
            #  Audit Log Entry
            # -----------------------------------------------------------------
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action_type="CREATE_EMI_PAYMENT",
                description=(
                    f"EMI Payment recorded for FinancePlan ID={plan.id}, "
                    f"EMI #{emi.installment_number}, Amount={amount_paid}, "
                    f"Method={payment_method}, Store={store.name if store else 'N/A'}"
                ),
                metadata={
                    "finance_plan_id": plan.id,
                    "emi_id": emi.id,
                    "amount": str(amount_paid),
                    "payment_method": payment_method,
                    "store": store.name if store else None,
                    "region": store.region.name if store and store.region else None
                }
            )

            # -----------------------------------------------------------------
            #  Late Payment → Reschedule future EMIs
            # -----------------------------------------------------------------
            if emi.due_date < timezone.now().date():
                logger.warning(f"EMI #{emi.installment_number} was late. Rescheduling future EMIs...")

                future_emis = plan.emi_schedule.filter(
                    installment_number__gt=emi.installment_number
                ).exclude(status='PAID')

                deleted_count, _ = future_emis.delete()
                logger.info(f"Deleted {deleted_count} future EMIs for plan {plan.id}")

                interval_days = plan.installment_frequency_days or 15
                next_emi_date = timezone.now().date() + timedelta(days=interval_days)
                self.generate_future_emis(plan, next_emi_date, emi.installment_number + 1)

                # -----------------------------------------------------------------
                #  Prepare Response
                # -----------------------------------------------------------------
            if emi.status == 'PAID':
                user_message = f"EMI #{emi.installment_number} fully paid. Thank you!"
            elif emi.status == 'PARTIALLY_PAID':
                user_message = (
                    f"EMI #{emi.installment_number} partially paid. "
                    f"Balance remaining: ₹{emi.installment_amount - emi.amount_paid}"
                )
            elif emi.status == 'OVERDUE':
                user_message = f"EMI #{emi.installment_number} is overdue. Please clear the balance soon."
            else:
                user_message = "Payment recorded successfully."
            response_data = {
            "message": user_message,
            "payment": {
                "id": payment.id,
                "amount": str(payment.payment_amount),
                "method": payment.payment_method,
                "status": payment.payment_status,
                "date": str(payment.payment_date.date()),
            },
            "finance_plan": {
                "id": plan.id,
                "apc_score": plan.apc_score,
                "risk_tier": plan.risk_tier,
                "selected_term": plan.selected_term,
                "interval_days": plan.installment_frequency_days,
                "total_amount": str(plan.total_amount_payable),
            },
            "store": {
                "id": store.id,
                "name": store.name,
                "code": store.code,
                "region": store.region.name if store and store.region else None,
                "channel": store.get_channel_display(),
            } if store else None,
            "emi": {
                "installment_number": emi.installment_number,
                "status": emi.status,
                "amount_paid": str(emi.amount_paid),
                "paid_date": str(emi.paid_date),
                "due_date": str(emi.due_date),
            }
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except EMISchedule.DoesNotExist:
            logger.error("EMI schedule not found.")
            return Response({"error": "EMI schedule not found."}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.exception("Error processing EMI payment.")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def generate_future_emis(self, plan, start_date, start_number):
        """
        Dynamically generate future EMIs every `installment_frequency_days` after a late payment.
        """
        total_installments = plan.selected_term
        interval_days = plan.installment_frequency_days or 15

        # Adjust amount proportionally if interval ≠ 30 days
        days_ratio = Decimal(interval_days) / Decimal(30)
        emi_amount = plan.monthly_installment * days_ratio

        for i in range(start_number, total_installments + 1):
            EMISchedule.objects.create(
                finance_plan=plan,
                installment_number=i,
                due_date=start_date,
                installment_amount=emi_amount,
                balance_remaining=emi_amount,
                status='UPCOMING'
            )
            start_date += timedelta(days=interval_days)

        logger.info(f"Regenerated EMIs #{start_number} - {total_installments} for plan {plan.id}")


# ============================================================
# API: Region Wise and Global Finance Report
# ============================================================               
class FinanceReportAPIView(APIView):
    """
    Generates Region-wise or Global Finance Report (Summary or Detailed).
    Supports weekly or monthly aggregation views.
    """
    permission_classes = [IsAuthenticatedUser]

    @swagger_auto_schema(
    operation_summary="Region-wise or Global Finance Report (Summary or Detailed)",
    operation_description="""
    Generates a **region-wise or global finance performance report** — either in **summary** or **detailed** format,
    aggregated by week or month.

    ###  Roles & Access Control
    - **Admin / GlobalManager / FinanceManager** → Access **all regions** (global view) or a specific region (`region_id` filter)
    - **SalesAdvisor** → Access **only their assigned region**, even if `region_id` is not provided

    ###  Filters & Query Parameters
    | Parameter | Type | Description |
    |------------|------|-------------|
    | `region_id` | integer | _(Optional)_ Filter report for a single region. If omitted, returns **all regions** (global report). |
    | `month` | integer | _(Optional)_ Filter by month (1–12). |
    | `date_from` | date (YYYY-MM-DD) | _(Optional)_ Custom start date for report range. |
    | `date_to` | date (YYYY-MM-DD) | _(Optional)_ Custom end date for report range. |
    | `report_type` | string | _(Optional)_ Choose between `summary` or `detailed` view. Default: `summary`. |
    | `view` | string | _(Optional)_ Aggregation mode — `weekly` or `monthly`. Default: `monthly`. |

    ### Report Modes
    - **Summary:** Aggregated metrics by region and store.
    - **Detailed:** Paginated list of finance plans with full customer and device info.

    ###  Behavior Summary
    | Role | `region_id` Provided | `region_id` Not Provided |
    |------|----------------------|---------------------------|
    | Admin / GlobalManager / FinanceManager | Single region report | Global (all-region) report |
    | SalesAdvisor | Their assigned region only | Their assigned region only |
    | Others | Not authorized | Not authorized |
    """,
    manual_parameters=[
        openapi.Parameter(
            "region_id",
            openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            description="(Optional) Region ID to filter a specific region. Leave empty for global report (Admin roles only).",
        ),
        openapi.Parameter(
            "month",
            openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            description="(Optional) Filter by month (1–12).",
        ),
        openapi.Parameter(
            "date_from",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            format=openapi.FORMAT_DATE,
            description="(Optional) Start date (YYYY-MM-DD). Used with `date_to`.",
        ),
        openapi.Parameter(
            "date_to",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            format=openapi.FORMAT_DATE,
            description="(Optional) End date (YYYY-MM-DD). Used with `date_from`.",
        ),
        openapi.Parameter(
            "report_type",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            enum=["summary", "detailed"],
            description="(Optional) Type of report. Choose `summary` (default) or `detailed`.",
        ),
        openapi.Parameter(
            "view",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            enum=["weekly", "monthly"],
            description="(Optional) Aggregation view mode: `weekly` or `monthly` (default: monthly).",
        ),
    ],
    tags=["Reports"],
    )
    def get(self, request):
        try:
            user = request.user
            user_role = getattr(user, "role", "Unknown")

            # ---------------- Query Params ----------------
            region_id = request.query_params.get("region_id")
            month = request.query_params.get("month")
            date_from = request.query_params.get("date_from")
            date_to = request.query_params.get("date_to")
            report_type = request.query_params.get("report_type", "summary").lower()
            view_mode = request.query_params.get("view", "monthly").lower()

            # ---------------- Base Query ----------------
            queryset = (
                FinancePlan.objects.select_related(
                    "credit_application__customer__created_by__store__region",
                    "device",
                )
                .prefetch_related(Prefetch("payments"))
            )

            # ---------------- Role-Based Access ----------------
            if user.is_superuser or user_role in ['admin', 'global_manager', 'financial_manager']:
                pass  # Full access
            elif user_role == "sales_advisor":
                if not getattr(user, "store", None) or not getattr(user.store, "region", None):
                    return Response(
                        {"status": "error", "message": "No region linked to this Sales Advisor."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                queryset = queryset.filter(
                    credit_application__customer__created_by__store__region=user.store.region
                )
            else:
                return Response(
                    {"status": "error", "message": "You are not authorized to view this report."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # ---------------- Filters ----------------
            if region_id and (user.is_superuser or user_role in ['admin', 'global_manager', 'financial_manager']):
                queryset = queryset.filter(
                    credit_application__customer__created_by__store__region_id=region_id
                )
            if month:
                try:
                    month_int = int(month)
                    if not 1 <= month_int <= 12:
                        raise ValueError
                    queryset = queryset.filter(created_at__month=month_int)
                except ValueError:
                    return Response(
                        {"status": "error", "message": "Invalid month. Must be between 1 and 12."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            if date_from and date_to:
                queryset = queryset.filter(created_at__date__range=[date_from, date_to])

            # ---------------- Weekly / Monthly View ----------------
            if view_mode == "weekly":
                queryset = queryset.annotate(period=TruncWeek("created_at"))
            else:
                queryset = queryset.annotate(period=TruncMonth("created_at"))

            # ============================================================
            # REPORT TYPE HANDLING
            # ============================================================
            if report_type == "summary":
                # ---------------- Aggregated Summary ----------------
                region_data = (
                    queryset.values(
                        "credit_application__customer__created_by__store__region__id",
                        "credit_application__customer__created_by__store__region__name",
                        "credit_application__customer__created_by__store__id",
                        "credit_application__customer__created_by__store__name",
                        "period",
                    )
                    .annotate(
                        total_finance_plans=Count("id"),
                        total_amount_financed=Sum("amount_to_finance"),
                        total_down_payment=Sum("actual_down_payment"),
                        approved_count=Count("id", filter=Q(score_status="APPROVED")),
                        rejected_count=Count("id", filter=Q(score_status="REJECTED")),
                        pending_count=Count("id", filter=Q(score_status="PENDING")),
                    )
                    .order_by("credit_application__customer__created_by__store__region__name", "period")
                )
                response_data = [
                    {
                        "region_id": r["credit_application__customer__created_by__store__region__id"],
                        "region_name": r["credit_application__customer__created_by__store__region__name"],
                        "store_id": r["credit_application__customer__created_by__store__id"],
                        "store_name": r["credit_application__customer__created_by__store__name"],
                        "period": r["period"].strftime("%Y-%m-%d") if r["period"] else None,
                        "total_finance_plans": r["total_finance_plans"],
                        "total_amount_financed": str(r["total_amount_financed"] or 0),
                        "total_down_payment": str(r["total_down_payment"] or 0),
                        "approved_count": r["approved_count"],
                        "rejected_count": r["rejected_count"],
                        "pending_count": r["pending_count"],
                    }
                    for r in region_data
                ]
                result = {
                    "status": "success",
                    "message": "Summary report fetched successfully.",
                    "filters": {
                        "region_id": region_id,
                        "month": month,
                        "date_from": date_from,
                        "date_to": date_to,
                        "report_type": report_type,
                        "view": view_mode,
                    },
                    "data": response_data,
                }
            elif report_type == "detailed":
                # ---------------- Paginated Detailed List ----------------
                paginator = FinancePlanPagination()
                paginated_queryset = paginator.paginate_queryset(queryset, request)
                detailed_data = []
                for obj in paginated_queryset:
                    customer = getattr(obj.credit_application, "customer", None)
                    created_by = getattr(customer, "created_by", None)
                    store = getattr(created_by, "store", None)
                    region = getattr(store, "region", None)

                    detailed_data.append({
                    "finance_id": obj.id,
                    "customer_name": f"{customer.first_name} {customer.last_name}" if customer else None,
                    "device_name": str(obj.device) if obj.device else None,
                    "amount_to_finance": str(obj.amount_to_finance or 0),
                    "actual_down_payment": str(obj.actual_down_payment or 0),
                    "score_status": obj.score_status,
                    "created_at": obj.created_at.strftime("%Y-%m-%d"),
                    "store_id": getattr(store, "id", None),
                    "store_name": getattr(store, "name", None),
                    "region_id": getattr(region, "id", None),
                    "region_name": getattr(region, "name", None),
                })
                result = {
                    "status": "success",
                    "message": "Detailed finance report fetched successfully.",
                    "filters": {
                        "region_id": region_id,
                        "month": month,
                        "date_from": date_from,
                        "date_to": date_to,
                        "report_type": report_type,
                        "view": view_mode,
                    },
                    "data": detailed_data,
                }
                return paginator.get_paginated_response(result)
            else:
                return Response(
                    {"status": "error", "message": "Invalid report_type. Use 'summary' or 'detailed'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # ----------------------- Audit Log -----------------------
            AuditLog.objects.create(
                user=user,
                action_type="FINANCE_REPORT_VIEWED",
                description=f"Viewed {report_type.capitalize()} report ({view_mode or 'monthly'} view).",
                metadata={
                    "filters": request.query_params.dict(),
                    "role": user_role,
                    "region_id": region_id,
                    "month": month,
                    "date_from": date_from,
                    "date_to": date_to,
                    "view": view_mode,
                },
                ip_address=request.META.get("REMOTE_ADDR"),
            )         

            logger.info(f"[FinanceReport] User={user.username}, Role={user_role}, Params={request.query_params}")
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"FinanceReport Error: {str(e)}", exc_info=True)
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)      


# ============================================================
# Create a New Payment Record
# ============================================================
class PaymentRecordCreateAPIView(APIView):
    """
    Creates a new Payment Record linked to a Finance Plan.
    """  
    permission_classes = [AllowAny] 

    @swagger_auto_schema(
        operation_summary="Create a Payment Record",
        operation_description="""
        Create a new **Payment Record** associated with a Finance Plan.

        ### Purpose
        Used to record payments like **Down Payment**, **EMI**, or **Full Settlement**.

        ### Fields
        | Field | Type | Required | Description |
        |--------|------|-----------|--------------|
        | finance_plan | integer | ID of the Finance Plan |
        | payment_type | string | One of `EMI`, `DOWN_PAYMENT`, `FULL_SETTLEMENT`, `LATE_FEE` |
        | payment_amount | decimal | Amount paid by the customer |
        | transaction_reference | string | Optional | Gateway reference (e.g., `"YAPPY-TRX-784923"`) |

        ### Auto Fields
        - `payment_method`: Default `"CASH"`
        - `payment_status`: `"COMPLETED"`
        - `payment_date`: Current timestamp
        - `processed_by`: Logged-in user

        ### Example Request
        ```json
        {
          "finance_plan": 101,
          "payment_type": "EMI",
          "payment_amount": "250.00",
          "transaction_reference": "YAPPY-TRX-784923"
        }
        ```
        """,
        request_body=PaymentCreateSerializer,
        responses={
            201: openapi.Response("Payment Created", PaymentRecord3DSerializer),
            400: "Validation Error",
            404: "Finance Plan not found",
            500: "Server Error",
        },
        tags=["Finance"]
    )
    def post(self, request):
        serializer = PaymentCreateSerializer(data=request.data, context={"request": request})

        # --- Input Validation
        if not serializer.is_valid():
            return Response({
                "status": "error",
                "message": "Validation failed.",
                "errors": serializer.errors,
            }, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        finance_plan = validated.get("finance_plan")
        payment_type = validated.get("payment_type")
        payment_amount = validated.get("payment_amount")

        try:
            with transaction.atomic():
                # --- Create Payment Record
                payment = serializer.save(
                    payment_method="CASH",
                    payment_date=timezone.now(),
                    payment_status="COMPLETED",
                    processed_by=request.user if request.user.is_authenticated else None,
                )

                # --- Apply EMI logic if applicable
                if hasattr(payment, "apply_to_emi") and payment.payment_status == "COMPLETED":
                    payment.apply_to_emi()

                # ----------------------- Audit Log -----------------------
                AuditLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    action_type="CREATE_PAYMENT",
                    description=(
                        f"Payment created for FinancePlan ID={payment.finance_plan.id}, "
                        f"Type={payment.payment_type}, Amount={payment.payment_amount}, "
                        f"Ref={payment.transaction_reference or 'N/A'}"
                    ),
                    metadata={
                        "finance_plan_id": payment.finance_plan.id,
                        "payment_type": payment.payment_type,
                        "payment_amount": str(payment.payment_amount),
                        "transaction_reference": payment.transaction_reference,
                        "payment_method": payment.payment_method,
                        "payment_status": payment.payment_status,
                        "timestamp": str(timezone.now()),
                    },
                    ip_address=request.META.get("REMOTE_ADDR"),
                )

        except Exception as e:
            logger.error(f"Failed to create payment record: {str(e)}", exc_info=True)
            return Response({
                "status": "error",
                "message": f"Failed to create payment record: {str(e)}",
                "filters": {
                    "finance_plan": finance_plan.id if 'finance_plan' in locals() and finance_plan else None,
                    "payment_type": payment_type if 'payment_type' in locals() else None
                },
                "data": None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        # --- Fetch with Relations
        payment = (
            PaymentRecord.objects
            .select_related("finance_plan", "finance_plan__device", "finance_plan__credit_application")
            .prefetch_related("finance_plan__payments", "emi_schedule")
            .get(id=payment.id)
        )

        # --- Serialize + Mask
        serialized = PaymentRecord3DSerializer(payment, context={"request": request}).data
        masked = mask_sensitive_data(serialized, getattr(request.user, "role", "guest"))

        # --- Success Response
        return Response({
            "status": "success",
            "message": "Payment record created successfully.",
            "filters": {
                "finance_plan": finance_plan.id,
                "payment_type": payment_type,
                "payment_amount": str(payment_amount)
            },
            "data": masked
        }, status=status.HTTP_201_CREATED)


# --------------------------------------------------------
# API: Get Payment Records 
# --------------------------------------------------------
class PaymentRecordAPIView(APIView):
    """
    List all Payment Records or a Specific Record by ID
    """  
    permission_classes = [IsAuthenticatedUser]

    @swagger_auto_schema(
        operation_summary="Get Payment Records (Role-based & Filtered)",
        operation_description="""
        Retrieve payment records with role-based access and filters.

        **Filters:**
        - `customer_id` (optional)
        - `payment_type` (optional)
        - `payment_status` (optional)
        - `payment_method` (optional)
        - `payment_date` (optional)
        - `start_date` and `end_date` (optional)
        """,
        manual_parameters=[
            openapi.Parameter('customer_id', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter('payment_type', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter('payment_status', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter('payment_method', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter('payment_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
        ],
        tags=["Finance"]
    )
    def get(self, request):
        try:
            user = request.user
            role = getattr(user, 'role', None)

            # === Filters ===
            customer_id = request.query_params.get('customer_id')
            payment_type = request.query_params.get('payment_type')
            payment_status = request.query_params.get('payment_status')
            payment_method = request.query_params.get('payment_method')
            payment_date = request.query_params.get('payment_date')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            # === Base queryset ===
            payments = PaymentRecord.objects.select_related(
                "finance_plan__credit_application__customer",
                "finance_plan__device"
            ).all()

            # === Role-based access ===
            if role == "Customer":
                payments = payments.filter(finance_plan__credit_application__customer__user=user)            
            elif role == "salesperson":
                payments = payments.filter(processed_by=user)
            elif role == "sales_advisor":
                if hasattr(user, "region"):
                    payments = payments.filter(finance_plan__credit_application__customer__region=user.region)
                else:
                    return Response({"status": "error", "message": "User region not assigned."}, status=403)
            elif role == "store_manager":
                if hasattr(user, "store"):
                    payments = payments.filter(finance_plan__credit_application__customer__store=user.store)
                else:
                    return Response({"status": "error", "message": "User store not assigned."}, status=403)
            elif role not in ['admin', 'global_manager', 'financial_manager']:
                return Response({"status": "error", "message": "Unauthorized role."}, status=403)

            # === Filters ===
            if customer_id:
                payments = payments.filter(finance_plan__credit_application__customer_id=customer_id)
            if payment_type:
                payments = payments.filter(payment_type=payment_type.upper())
            if payment_status:
                payments = payments.filter(payment_status=payment_status.upper())
            if payment_method:
                payments = payments.filter(payment_method=payment_method.upper())

            # === Date filters ===
            if payment_date:
                payments = payments.filter(payment_date=payment_date)
            elif start_date and end_date:
                payments = payments.filter(payment_date__range=[start_date, end_date])
            elif start_date:
                payments = payments.filter(payment_date__gte=start_date)
            elif end_date:
                payments = payments.filter(payment_date__lte=end_date)

            # === Default ordering by payment_date descending ===
            payments = payments.order_by('-payment_date')

            # === Summary ===
            if not payments.exists():
                return Response({"status": "success", "message": "No payment records found.", "data": []}, status=200)

            total_payments = payments.count()
            completed = payments.filter(payment_status='COMPLETED').count()
            pending = payments.filter(payment_status='PENDING').count()
            total_amount = payments.filter(payment_status='COMPLETED').aggregate(Sum('payment_amount'))['payment_amount__sum'] or Decimal('0.00')

            serializer = PaymentRecordSerializerPlan(payments, many=True)

            response = {
                "status": "success",
                "message": f"Retrieved {total_payments} payment records.",
                "summary": {
                    "total_payments": total_payments,
                    "completed_payments": completed,
                    "pending_payments": pending,
                    "total_amount_paid": str(total_amount),
                },
                "data": serializer.data
            }
            logger.info(f"[PaymentRecordAPI] Retrieved {total_payments} payment records for role={role}")

            # === Audit Log ===
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action_type="PAYMENT_VIEWED",
                description=(
                    f"Viewed {total_payments} payment records "
                    f"(Role={role or 'N/A'}, CustomerID={customer_id or 'All'})"
                ),
                metadata={
                    "filters": {
                        "customer_id": customer_id,
                        "payment_type": payment_type,
                        "payment_status": payment_status,
                        "payment_method": payment_method,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    "total_records": total_payments,
                    "completed": completed,
                    "pending": pending,
                    "total_amount_paid": str(total_amount),
                    "timestamp": str(timezone.now()),
                },
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return Response(response, status=200)

        except Exception as e:
            logger.exception("[PaymentRecordAPI] Error retrieving payment records.")
            return Response({"status": "error", "message": str(e)}, status=500)
        

            


# ============================================================
# Create a dynamic multiple value (intrest) 
# ============================================================


class FinanceMultipleListCreateView(APIView):
    permission_classes=[IsAdminOrGlobalManager]
    """
    Admin API → List all multiples or add a new one.
    GET: list all
    POST: create new
    """
    # -----------GET METHOD------------

    @swagger_auto_schema(
        # method='get',
        operation_summary="List all Finance Multiples",
        operation_description="Fetch all FinanceMultiple records ordered by term and interval.",
        responses={
            200: openapi.Response(
                description="List of Finance Multiples",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "Finance multiple list fetched successfully.",
                        "data": [
                            {"id": 1, "term_months": 4, "interval_days": 15, "multiple": "1.7"},
                            {"id": 2, "term_months": 6, "interval_days": 30, "multiple": "1.8"},
                        ],
                    }
                },
            ),
        },
        tags=["Finance Multiples"]
    )

    def get(self, request):
        multiples = FinanceMultiple.objects.all().order_by('term_months', 'interval_days')
        serializer = FinanceMultipleSerializer(multiples, many=True)
        return Response({
            "status": "success",
            "message": "Finance multiple list fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    # ------POST METHOD----------
    
    @swagger_auto_schema(
        # method='post',
        operation_summary="Create a new Finance Multiple",
        operation_description="Add a new FinanceMultiple record (admin only).",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["term_months", "interval_days", "multiple"],
            properties={
                "term_months": openapi.Schema(type=openapi.TYPE_INTEGER, example=6),
                "interval_days": openapi.Schema(type=openapi.TYPE_INTEGER, example=30),
                "multiple": openapi.Schema(type=openapi.TYPE_STRING, example="1.8"),
            },
        ),
        responses={
            201: openapi.Response(
                description="Multiple created successfully",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "Multiple added successfully",
                        "data": {"id": 3, "term_months": 8, "interval_days": 15, "multiple": "2.2"},
                    }
                },
            ),
            400: "Validation failed",
        },
        tags=["Finance Multiples"]
    )

    def post(self, request):
        serializer = FinanceMultipleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "status": "success",
                "message": "Multiple added successfully",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)

        return Response({
            "status": "error",
            "message": "Validation failed.",
            "data": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

# ============================================================
# Create a dynamic multiple value (intrest)
# ============================================================

class FinanceMultipleDetailView(APIView):
    permission_classes=[IsAdminOrGlobalManager]
    """
    Admin API → Retrieve, update, or delete a specific multiple.
    """

    def get_object(self, pk):
        try:
            return FinanceMultiple.objects.get(pk=pk)
        except FinanceMultiple.DoesNotExist:
            return None
        
    #  ---------GET METHOD-------
       
    @swagger_auto_schema(
        # method='get',
        operation_summary="Retrieve a specific Finance Multiple",
        operation_description="Fetch details of a specific FinanceMultiple by ID.",
        responses={
            200: openapi.Response(
                description="Finance multiple detail",
                examples={
                    "application/json": {
                        "status": "success",
                        "message": "Finance multiple fetched successfully.",
                        "data": {"id": 1, "term_months": 4, "interval_days": 15, "multiple": "1.7"},
                    }
                },
            ),
            404: "Finance multiple not found",
        },
        tags=["Finance Multiples"]
    )
    def get(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({
                "status": "error",
                "message": "Finance multiple not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)
        serializer = FinanceMultipleSerializer(obj)
        return Response({
            "status": "success",
            "message": "Finance multiple fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    # -------PATCH METHOD---------
    
    @swagger_auto_schema(
        # method='patch',
        operation_summary="Update a specific Finance Multiple",
        operation_description="Partially update term, interval, or multiple value by ID.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "term_months": openapi.Schema(type=openapi.TYPE_INTEGER, example=8),
                "interval_days": openapi.Schema(type=openapi.TYPE_INTEGER, example=15),
                "multiple": openapi.Schema(type=openapi.TYPE_STRING, example="2.2"),
            },
        ),
        responses={
            200: "Updated successfully",
            404: "Finance multiple not found",
        },
        tags=["Finance Multiples"]
    )

    def patch(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({
                "status": "error",
                "message": "Finance multiple not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)
        serializer = FinanceMultipleSerializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "status": "success",
                "message": "Finance Multiple updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        return Response({
            "status": "error",
            "message": "Validation failed.",
            "data": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # ---------DELETE METHOD--------
    
    @swagger_auto_schema(
        # method='delete',
        operation_summary="Delete a Finance Multiple",
        operation_description="Remove a specific FinanceMultiple record by ID (admin only).",
        responses={
            200: "Deleted successfully",
            404: "Finance multiple not found",
        },
        tags=["Finance Multiples"]
    )

    def delete(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({
                "status": "error",
                "message": "Finance multiple not found.",
                "data": None
            }, status=status.HTTP_404_NOT_FOUND)
        obj.delete()

        return Response({
            "status": "success",
            "message": "Finance multiple deleted successfully.",
            "data": None
        }, status=status.HTTP_200_OK)

# ===================================
# WESTERN UNION (CASH PAYMENT) API
# ===================================

class VerifyCustomerAPIView(APIView):
    permission_classes=[AllowAny]
    """
    Step 1: Customer enters ID/account number to check EMI details.
    Endpoint: /verify-customer/
    only for western union dashboard
    """
    @swagger_auto_schema(
        tags=["Western Union Payments"],
        operation_summary="Verify Customer and Fetch EMI Details- FOR WESTERN UNION (NOT FOR FROTEND)",
        operation_description=(
            "This API is called by Western Union to verify a customer and retrieve pending EMI details. "
            "The request must include customer ID, operation type, and other transaction parameters."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=[
                "customer_id", "operation_type", "utility",
                "terminal_id", "date", "time", "operation_code",
                "user", "password"
            ],
            properties={
                "customer_id": openapi.Schema(type=openapi.TYPE_STRING, example="123456"),
                "operation_type": openapi.Schema(type=openapi.TYPE_STRING, example="CashIn"),
                "utility": openapi.Schema(type=openapi.TYPE_STRING, example="90061234"),
                "terminal_id": openapi.Schema(type=openapi.TYPE_STRING, example="D00561"),
                "date": openapi.Schema(type=openapi.TYPE_STRING, example="20251107"),
                "time": openapi.Schema(type=openapi.TYPE_STRING, example="101940"),
                "operation_code": openapi.Schema(type=openapi.TYPE_STRING, example="C"),
                "user": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
                "password": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
            },
        ),
        responses={
            200: openapi.Response(
                description="Customer and EMI details found successfully",
                examples={
                    "application/json": {
                        "operation_type": "CashIn",
                        "customer_id": "123456",
                        "customer_name": "Rahul Sharma",
                        "utility": "90061234",
                        "terminal": "D00561",
                        "date": "20251107",
                        "time": "101940",
                        "operation_code": "C",
                        "response_code": "0",
                        "response_message": "Query successful",
                        "items": [
                            {
                                "id_item": "LOAN123",
                                "amount": "10000",
                                "description": "Loan installment - Due 2025-11-15",
                                "due_date": "20251115"
                            }
                        ]
                    }
                },
            ),
            404: openapi.Response(
                description="Customer not found",
                examples={"application/json": {"response_code": "7", "response_message": "Customer not found"}}
            ),
            200: openapi.Response(
                description="No pending payments found",
                examples={"application/json": {"response_code": "6", "response_message": "No pending payments found"}}
            ),
        },
    )
    def post(self, request):

        serializer = VerifyCustomerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data


        #  Validate credentials
        if data.get("user") != settings.WESTERN_USER  or data.get("password") != settings.WESTERN_PASS:
            return Response(
                {"response_code": "9", "response_message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        customer_id = data.get("customer_id")

        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response(
                {"response_code": "7", "response_message": "Customer not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Fetch pending EMI
        pending_emi = EMISchedule.objects.filter(
            finance_plan__credit_application__customer=customer,
            status__in=["DUE", "OVERDUE","PARTIALLY_PAID"]
        ).first()

        if not pending_emi:
            return Response(
                {"response_code": "6", "response_message": "No pending payments found"},
                status=status.HTTP_200_OK
            )

        response = {
            "operation_type": "CashIn",
            "customer_id": str(customer.id),
            "customer_name": f"{customer.first_name} {customer.last_name}",
            "utility": data.get("utility"),
            "terminal": data.get("terminal_id"),
            "date": data.get("date"),
            "time": data.get("time"),
            "operation_code": data.get("operation_code"),
            "response_code": "0",
            "response_message": "Query successful",
            "items": [
                {
                    "id_item": str(pending_emi.id),
                    "amount": str(pending_emi.balance_remaining),
                    "description": f"Loan installment - Due {pending_emi.due_date}",
                    "due_date": pending_emi.due_date.strftime("%Y%m%d"),
                }
            ]
        }
        return Response(response, status=status.HTTP_200_OK)


# ==============================================
# WESTERN UNION (CASH PAYMENT) SUCESS/FAIL VIEW
# =============================================


class WesternUnionPaymentAPIView(APIView):
    permission_classes=[]
    """
    Step 2: Western Union calls this API after customer pays cash.
    Endpoint: /directa/
    only for western union dashboard
    """
    @swagger_auto_schema(
        operation_summary="Process Western Union Payment- FOR WESTERN UNION (NOT FOR FROTEND)",
        operation_description=(
            "This API is called by Western Union after a customer deposits cash at a kiosk. "
            "It validates the EMI, checks amount limits, updates the payment record, and marks the EMI as paid."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=[
                "operation_type", "customer_id", "id_item", "terminal",
                "date", "time", "sequence", "transaction_code",
                "operation_code", "barcode", "utility", "amount",
                "payment_method", "user", "password"
            ],
            properties={
                "operation_type": openapi.Schema(type=openapi.TYPE_STRING, example="CashIn"),
                "customer_id": openapi.Schema(type=openapi.TYPE_STRING, example="123456"),
                "id_item": openapi.Schema(type=openapi.TYPE_STRING, example="LOAN123"),
                "terminal": openapi.Schema(type=openapi.TYPE_STRING, example="D00561"),
                "date": openapi.Schema(type=openapi.TYPE_STRING, example="20251107"),
                "time": openapi.Schema(type=openapi.TYPE_STRING, example="102000"),
                "sequence": openapi.Schema(type=openapi.TYPE_STRING, example="1125"),
                "transaction_code": openapi.Schema(type=openapi.TYPE_STRING, example="D00561202511071020001125"),
                "operation_code": openapi.Schema(type=openapi.TYPE_STRING, example="D"),
                "barcode": openapi.Schema(type=openapi.TYPE_STRING, example="90061234000232500005656500"),
                "utility": openapi.Schema(type=openapi.TYPE_STRING, example="90061234"),
                "amount": openapi.Schema(type=openapi.TYPE_STRING, example="10000"),
                "payment_method": openapi.Schema(type=openapi.TYPE_STRING, example="E01 (Cash)"),
                "user": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
                "password": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
            }
        ),
        responses={
            200: openapi.Response(
                description="Payment Successful",
                examples={
                    "application/json": {
                        "operation_type": "CashIn",
                        "utility": "90061234",
                        "terminal": "D00561",
                        "date": "20251107",
                        "time": "102000",
                        "sequence": "1125",
                        "transaction_code": "D00561202511071020001125",
                        "operation_code": "D",
                        "response_code": "0",
                        "response_message": "Payment successful",
                        "ticket_text": "Thank you! Your payment of ₹10000 was received successfully."
                    }
                },
            ),
            400: openapi.Response(
                description="Overpayment or Invalid Input",
                examples={
                    "application/json": {
                        "response_code": "5",
                        "response_message": "Payment exceeds pending EMI amount",
                        "ticket_text": "Payment rejected. Pending amount is ₹9500.00. Please retry with the exact amount."
                    }
                },
            ),
            404: openapi.Response(
                description="EMI Record Not Found",
                examples={
                    "application/json": {
                        "response_code": "4",
                        "response_message": "EMI record not found",
                        "ticket_text": "Payment could not be processed."
                    }
                },
            ),
        },
        tags=["Western Union Payments"]
    )

    def post(self, request):
        data = request.data

        if data.get("user") != settings.WESTERN_USER  or data.get("password") != settings.WESTERN_PASS:
            return Response(
                {"response_code": "9", "response_message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            emi = EMISchedule.objects.get(id=data.get("id_item"))
        except EMISchedule.DoesNotExist:
            return Response({
                "operation_type": data.get("operation_type"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "date": data.get("date"),
                "time": data.get("time"),
                "sequence": data.get("sequence"),
                "transaction_code": data.get("transaction_code"),
                "operation_code": data.get("operation_code"),
                "response_code": "4",
                "response_message": "EMI record not found",
                "ticket_text": "Payment could not be processed."
            }, status=status.HTTP_404_NOT_FOUND)

        # Update EMI status and record payment
        pending_amount = Decimal(emi.installment_amount - emi.amount_paid)
        amount = Decimal(data.get("amount", 0))

        #  Reject overpayment
        if amount > pending_amount:
            return Response({
                "operation_type": data.get("operation_type"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "date": data.get("date"),
                "time": data.get("time"),
                "sequence": data.get("sequence"),
                "transaction_code": data.get("transaction_code"),
                "operation_code": data.get("operation_code"),
                "response_code": "5",
                "response_message": "Payment exceeds pending EMI amount",
                "ticket_text": f"Payment rejected. Pending amount is ₹{pending_amount:.2f}. Please retry with the exact amount."
            }, status=status.HTTP_400_BAD_REQUEST)

        emi.amount_paid += amount
        emi.update_status()
        emi.save()

        # Save payment record
        PaymentRecord.objects.create(
            finance_plan=emi.finance_plan,
            emi_schedule=emi,
            payment_type="EMI",
            payment_method="WESTERN_UNION",
            payment_amount=amount,
            payment_date=timezone.now(),
            payment_status="COMPLETED",
            transaction_reference=data.get("transaction_code"),
            notes="Payment received via Western Union"
        )

        return Response({
            "operation_type": data.get("operation_type"),
            "utility": data.get("utility"),
            "terminal": data.get("terminal"),
            "date": data.get("date"),
            "time": data.get("time"),
            "sequence": data.get("sequence"),
            "transaction_code": data.get("transaction_code"),
            "operation_code": data.get("operation_code"),
            "response_code": "0",
            "response_message": "Payment successful",
            "ticket_text": f"Thank you! Your payment of ₹{amount} was received successfully."
        }, status=status.HTTP_200_OK)


# ============================================================
# Get Complete Finance Details 
# ============================================================
class FinanceCompleteDetailsAPIView(APIView):
    """
    API to get COMPLETE Finance details including:
    Finance plan, Customer, EMI schedules, Device, Store, Region, Payment summary
    """
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Get complete Finance details",
        operation_description="""
        If `customer_id` is provided → returns full finance snapshot for that customer.
        If not → returns paginated list of all finance plans with filters.
        """,
        manual_parameters=[
            openapi.Parameter("customer_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                              description="Return full finance details for 1 customer"),
            openapi.Parameter("store_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                              description="Filter by Store"),
            openapi.Parameter("region_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                              description="Filter by Region"),
            openapi.Parameter("device_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                              description="Filter by Device"),
            openapi.Parameter("status", openapi.IN_QUERY, type=openapi.TYPE_STRING,
                              description="Filter EMI status (PAID, PENDING, OVERDUE)"),
            openapi.Parameter("date_from", openapi.IN_QUERY, type=openapi.TYPE_STRING,
                              description="Filter emi due_date >= this date (YYYY-MM-DD)"),
            openapi.Parameter("date_to", openapi.IN_QUERY, type=openapi.TYPE_STRING,
                              description="Filter emi due_date <= this date (YYYY-MM-DD)"),
        ],
        tags=["Finance"]
    )
    def get(self, request):
        try:
            customer_id = request.query_params.get("customer_id")
            store_id = request.query_params.get("store_id")
            region_id = request.query_params.get("region_id")
            device_id = request.query_params.get("device_id")
            status_filter = request.query_params.get("status")
            date_from = request.query_params.get("date_from")
            date_to = request.query_params.get("date_to")

            pagination = FinancePlanPagination()

            # Single customer complete details
            if customer_id:
                return self.get_customer_finance_details(
                    customer_id,
                    status_filter=status_filter,
                    date_from=date_from,
                    date_to=date_to
                )

            # List view
            queryset = FinancePlan.objects.select_related(
                "customer",
                "device",
                "store",
                "store__region"
            ).prefetch_related(
                Prefetch("emi_schedules", queryset=EMISchedule.objects.order_by("due_date"))
            )

            # Apply filters on FinancePlans
            if store_id:
                queryset = queryset.filter(store_id=store_id)
            if region_id:
                queryset = queryset.filter(store__region_id=region_id)
            if device_id:
                queryset = queryset.filter(device_id=device_id)
            if status_filter:
                queryset = queryset.filter(emi_schedules__status=status_filter.upper())
            if date_from:
                queryset = queryset.filter(emi_schedules__due_date__gte=date_from)
            if date_to:
                queryset = queryset.filter(emi_schedules__due_date__lte=date_to)
            queryset = queryset.distinct()

            # Pagination
            paginated_data = pagination.paginate_queryset(queryset, request)
            serializer = FinancePlanSerializer(paginated_data, many=True)
            return pagination.get_paginated_response(serializer.data)

        except Exception as e:
            return Response(
                {"detail": f"Error fetching finance data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ---------------------------------------------------------------
    # Full Finance details for one customer with EMI filters
    # ---------------------------------------------------------------
    def get_customer_finance_details(self, customer_id, status_filter=None, date_from=None, date_to=None):
        try:
            finance_plan = get_object_or_404(
                FinancePlan.objects.select_related(
                    "device",
                    "store",
                    "store__region",
                    "credit_application__customer",
                ).prefetch_related(
                    Prefetch("emi_schedule", queryset=EMISchedule.objects.order_by("due_date"))
                ),
                credit_application__customer_id=customer_id
            )

            # All EMIs
            emi_schedules = finance_plan.emi_schedule.all()

            # Apply EMI filters
            if status_filter:
                emi_schedules = emi_schedules.filter(status=status_filter.upper())
            if date_from:
                emi_schedules = emi_schedules.filter(due_date__gte=date_from)
            if date_to:
                emi_schedules = emi_schedules.filter(due_date__lte=date_to)

            overdue_emis = emi_schedules.filter(status="OVERDUE")
            upcoming_emis = emi_schedules.filter(status="PENDING")

            # Aggregates
            total_paid = emi_schedules.aggregate(total=Sum("amount_paid"))["total"] or 0
            outstanding_balance = sum(emi.balance_remaining for emi in emi_schedules)
            overdue_total = overdue_emis.aggregate(total=Sum("installment_amount"))["total"] or 0

            # Generate interest_details dynamically
            multiple = FinanceMultiple.objects.filter(
                term_months=finance_plan.selected_term,
                interval_days=finance_plan.installment_frequency_days,
                is_active=True
            ).first()

            if multiple:
                principal = float(finance_plan.device_price)
                interest_amount = principal * (float(multiple.multiple) - 1)
                total_payable = principal + interest_amount

                emi_count = getattr(finance_plan, "total_installments", None)
                if not emi_count:
                    # Calculate if not explicitly stored
                    emi_count = int(finance_plan.selected_term * 30 / finance_plan.installment_frequency_days)

                emi_amount = total_payable / emi_count if emi_count else None

                interest_details = {
                    "term_months": finance_plan.selected_term,
                    "interval_days": finance_plan.installment_frequency_days,
                    "multiple": float(multiple.multiple),
                    "principal_amount": principal,
                    "interest_amount": interest_amount,
                    "total_payable": total_payable,
                    "emi_count": emi_count,
                    "emi_amount": emi_amount
                }
            else:
                interest_details = None

            # Build response
            serializer_data = {
                "finance_plan": finance_plan,
                "emi_schedule": emi_schedules,
                "overdue_details": {
                    "total_overdue_installments": overdue_emis.count(),
                    "total_overdue_amount": overdue_total,
                    "customers_with_overdue": 1,
                },
                "payments": finance_plan.payments.all(),
                "interest_details": interest_details,
                "total_paid": total_paid,
                "total_outstanding": outstanding_balance,
                "pending_emis_count": upcoming_emis.count(),
                "paid_emis_count": emi_schedules.filter(status="PAID").count(),
                "overdue_emis_count": overdue_emis.count(),
            }

            serializer = FinanceFullDetailsSerializer(serializer_data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"detail": f"Error fetching customer finance details: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

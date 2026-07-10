
# ============================================================
# Standard Library Imports
# ============================================================
import logging
from decimal import Decimal
from datetime import timedelta, datetime
from collections import defaultdict
from decimal import Decimal
import base64, hmac, hashlib
import time
import requests


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
from django.db import models, DatabaseError
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
from store.models import Region, Store
from .utils.utils import get_device_price_with_cache
from .finance_filter import FinancePlanFilter
from home.permissions import CanViewAdminFinanceDetails, CanViewSalesAdvisorFinance, CanViewStoreManagerFinance
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
    WesternUnionPaymentSerializer,
    FinanceFullDetailsSerializer,
)
from .permissions import IsAdminOrGlobalManager
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

    def paginate_queryset(self, queryset, request, view=None):
        try:
            return super().paginate_queryset(queryset, request, view)
        except Exception:
            self.request = request
            page_size = self.get_page_size(request)
            if not page_size:
                return []
            from django.core.paginator import Paginator
            paginator = Paginator(queryset, page_size)
            last_page = max(1, paginator.num_pages)
            try:
                self.page = paginator.page(last_page)
            except Exception:
                return []
            self.page.object_list = []
            return []


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
            # serializer = AutoFinancePlanCreateSerializer(data=request.data)
            # serializer.is_valid(raise_exception=True)

    # 1️⃣ Validate input
            serializer = AutoFinancePlanCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"status": "error", "message": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            
            customer_id = serializer.validated_data["customer_id"]
            

            # -------3D Data Fetch ----------
            # customer = (
            #     Customer.objects
            #     .prefetch_related('credit_applications', 'credit_scores')
            #     .only("id", "document_number")
            #     .get(id=customer_id)
            # )

            # 2️⃣ Fetch customer
            try:
                customer = (
                    Customer.objects
                    .prefetch_related('credit_applications', 'credit_scores')
                    .only("id", "document_number")
                    .get(id=customer_id)
                )
            except Customer.DoesNotExist:
                return Response(
                    {"status": "error", "message": "Customer not found."},
                    status=status.HTTP_404_NOT_FOUND,
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
            )
            if not credit_app:
                credit_app = CreditApplication.objects.create(
                    customer=customer,
                    sales_person=request.user,
                    device_price=0
                )
            elif not credit_app.sales_person:
                credit_app.sales_person = request.user
                credit_app.save(update_fields=["sales_person"])

            # ----To get monthly income of customer---------
            document_number = customer.document_number
            if not document_number:
                return Response(
                    {
                        "status": "error",
                        "message": "Customer document number not found."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            # monthly_income = get_customer_monthly_income(document_number)
            # 6️⃣ Fetch monthly income
            try:
                monthly_income = get_customer_monthly_income(customer.document_number)
            except Exception as e:
                logger.exception(f"Error fetching monthly income: {str(e)}")
                return Response(
                    {"status": "error", "message": "Failed to fetch monthly income."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            if monthly_income is None:
                # Fallback to TIER_F by assigning a default monthly income (e.g., $350.00 USD)
                # so the credit check can proceed under TIER_F instead of raising a 400 Bad Request.
                monthly_income = Decimal('350.00')
            # auto_plan, created = AutoFinancePlan.objects.get_or_create(
            #     credit_application=credit_app,
            #     defaults={
            #         "customer": customer,
            #         "credit_score": credit_score,
            #         "apc_score": apc_score,
            #         "risk_tier": "",
            #         "customer_monthly_income": monthly_income,
            #         "payment_capacity_factor": Decimal("0.00"),
            #         "maximum_allowed_installment": Decimal("0.00"),
            #         "minimum_down_payment_percentage": Decimal("0.00"),
            #         "has_finance_plan": False,
            #     }
            # )
            auto_plan = AutoFinancePlan.objects.filter(
                credit_application=credit_app,
                has_finance_plan=False
            ).order_by('-id').first()

            if auto_plan is None:
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

            # engine = AutoDecisionEngine(auto_plan)
            # engine_out=engine.run()
            # 8️⃣ Run decision engine
            

            try:
                engine = AutoDecisionEngine(auto_plan)
                engine_out = engine.run()
            except Exception as e:
                logger.exception(f"Error running decision engine: {str(e)}")
                return Response(
                    {"status": "error", "message": "Failed to run decision engine."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ---- Audit Logging ----
            # AuditLog.objects.create(
            #     user=request.user,
            #     action_type="CREATE_AUTO_FINANCE_PLAN",
            #     customer=customer,
            # )
            # 9️⃣ Audit log
            try:
                AuditLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    action_type="CREATE_AUTO_FINANCE_PLAN",
                    customer=customer,
                )
            except Exception as e:
                logger.warning(f"Audit log failed: {str(e)}")

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

def get_transient_plan_from_application(app_id):
    from customer.models import CreditApplication
    credit_app = CreditApplication.objects.filter(id=app_id).first()
    if not credit_app:
        return None
        
    # Check if there is an active plan already
    from finance.models import FinancePlan
    active_plan = FinancePlan.objects.filter(credit_application=credit_app).first()
    if active_plan:
        return active_plan

    # Otherwise build transient FinancePlan
    from finance.models import AutoFinancePlan
    from finance.decision_engine import DecisionEngine
    from decimal import Decimal
    
    latest_auto_plan = AutoFinancePlan.objects.filter(credit_application=credit_app).order_by("-id").first()
    
    plan_data = {
        "id": credit_app.id,
        "credit_application": credit_app,
        "credit_score": latest_auto_plan.credit_score if latest_auto_plan else None,
        "apc_score": latest_auto_plan.apc_score if latest_auto_plan else 550,
        "risk_tier": latest_auto_plan.risk_tier if latest_auto_plan else "TIER_B",
        "customer_monthly_income": 3000,
        "payment_capacity_factor": latest_auto_plan.payment_capacity_factor if latest_auto_plan else Decimal("0.20"),
        "maximum_allowed_installment": latest_auto_plan.maximum_allowed_installment if latest_auto_plan else Decimal("0.00"),
        "minimum_down_payment_percentage": latest_auto_plan.minimum_down_payment_percentage if latest_auto_plan else Decimal("20.00"),
        
        "device": credit_app.device,
        "device_price": credit_app.device_price or Decimal("0.00"),
        "actual_down_payment": credit_app.initial_payment or Decimal("0.00"),
        "selected_term": credit_app.number_of_installments or 6,
        "installment_frequency_days": credit_app.installment_frequency_days or 30,
        "status": "DRAFT",
    }
    
    transient_plan = FinancePlan(**plan_data)
    engine = DecisionEngine(transient_plan)
    final_plan = engine.run(save=False)
    final_plan.id = credit_app.id
    return final_plan

# --------------------------------------------------------
# API: Create or Get Finance Plan List
# --------------------------------------------------------
class FinancePlanAPIView(APIView):   
    """
    API to create a Finance Plan using Decision Engine from AutoFinancePlan data,
    and retrieve all or specific Finance Plans.
    """
    permission_classes = [IsAuthenticatedUser]
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
            if request.user.role not in ["salesperson", "store_manager"]:
                return Response({
                    "status": "error",
                    "message": "only salesperson and store_manager create finance plans."
                }, status=status.HTTP_403_FORBIDDEN)        
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

            # Save IMEI number to CreditApplication (skip placeholder "000000000000000")
            imei = data.get("imei")
            if imei and imei != "000000000000000":
                if len(imei) == 15 and imei.isdigit():
                    if finance_plan.credit_application:
                        duplicate_imei_exists = CreditApplication.objects.filter(
                            device_imei=imei
                        ).exclude(id=finance_plan.credit_application.id).exists()
                        
                        if duplicate_imei_exists:
                            return Response({
                                "status": "error",
                                "message": "This device IMEI is already enrolled in another application."
                            }, status=status.HTTP_400_BAD_REQUEST)

                        credit_app = finance_plan.credit_application
                        credit_app.device_imei = imei
                        credit_app.save(update_fields=["device_imei"])

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
                "customer_monthly_income": finance_plan.customer_monthly_income or Decimal("350.00"),
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

            # Save selected term and details directly to CreditApplication
            credit_app = finance_plan.credit_application
            credit_app.device = device
            credit_app.device_price = device_price
            credit_app.initial_payment = data.get("actual_down_payment")
            credit_app.number_of_installments = data["choosed_allowed_plans"]["selected_term"]
            credit_app.installment_frequency_days = data["choosed_allowed_plans"]["installment_frequency_days"]
            credit_app.save()

            # Setup transient plan to compute calculations
            engine_input = FinancePlan(**finance_plan_data)
            
             # Mark AutoPlan as finalized
            finance_plan.has_finance_plan = True
            finance_plan.save(update_fields=["has_finance_plan"])         

            logger.info(f"[FinancePlanAPI] DecisionEngine transient input: {engine_input}")

            # --------------------------------------------------------
            # Run Decision Engine
            # --------------------------------------------------------
            logger.info(f"[FinancePlanAPI] Running Decision Engine")
            engine = DecisionEngine(engine_input)
            final_plan = engine.run(save=False)
            
            # Save computations back to CreditApplication
            credit_app.amount_to_finance = final_plan.amount_to_finance
            credit_app.installment_amount = final_plan.monthly_installment
            credit_app.total_amount = final_plan.total_amount_payable
            credit_app.save()
            
            final_plan.id = credit_app.id
            
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
            "New": False,
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
        openapi.Parameter("page", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
        openapi.Parameter("page_size", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),

        # ---------------- BASIC FILTERS ----------------
        openapi.Parameter("emi_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
        openapi.Parameter("customer_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
        openapi.Parameter("product_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
        openapi.Parameter("apc_score", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),

        openapi.Parameter("start_date", openapi.IN_QUERY, type=openapi.TYPE_STRING, format="date"),
        openapi.Parameter("end_date", openapi.IN_QUERY, type=openapi.TYPE_STRING, format="date"),
        openapi.Parameter("updated_start_date", openapi.IN_QUERY, type=openapi.TYPE_STRING, format="date"),
        openapi.Parameter("updated_end_date", openapi.IN_QUERY, type=openapi.TYPE_STRING, format="date"),

        # ---------------- FINANCEPLAN FILTERS ----------------
        openapi.Parameter(
            "status", openapi.IN_QUERY, type=openapi.TYPE_STRING,
            enum=["ACTIVE", "CLOSED"]
        ),
        openapi.Parameter(
            "risk_tier", openapi.IN_QUERY, type=openapi.TYPE_STRING,
            enum=["TIER_A", "TIER_B", "TIER_C", "TIER_D"]
        ),
        openapi.Parameter(
            "is_active", openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN,
            enum=["true", "false"]
        ),
        openapi.Parameter("selected_term", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
        openapi.Parameter("installment_frequency_days", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),

        openapi.Parameter(
            "is_high_end_device", openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN,
            enum=["true", "false"]
        ),
        openapi.Parameter(
            "payment_capacity_passed", openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN,
            enum=["true", "false"]
        ),
        openapi.Parameter(
            "score_status", openapi.IN_QUERY, type=openapi.TYPE_STRING,
            enum=["APPROVED", "CONDITIONAL", "REJECTED"]
        ),
        openapi.Parameter(
            "disbursement_status", openapi.IN_QUERY, type=openapi.TYPE_STRING,
            enum=["PENDING", "DISBURSED"]
        ),
        openapi.Parameter(
            "conditions_met", openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN,
            enum=["true", "false"]
        ),
        openapi.Parameter(
            "requires_adjustment", openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN,
            enum=["true", "false"]
        ),

        openapi.Parameter("min_amount_to_finance", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),
        openapi.Parameter("max_amount_to_finance", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),

        openapi.Parameter("min_monthly_installment", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),
        openapi.Parameter("max_monthly_installment", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),

        openapi.Parameter("min_device_price", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),
        openapi.Parameter("max_device_price", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),

        # ---------------- CUSTOMER FILTERS ----------------
        openapi.Parameter("customer_document_number", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("customer_phone", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("customer_email", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter(
            "customer_status", openapi.IN_QUERY, type=openapi.TYPE_STRING,
            enum=["ACTIVE", "INACTIVE", "BLOCKED"]
        ),
        openapi.Parameter("customer_created_by", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),

        # ---------------- STORE FILTERS ----------------
        openapi.Parameter("store_id", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("region_id", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("province_id", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("district_id", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("corregimiento_id", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter(
            "store_channel", openapi.IN_QUERY, type=openapi.TYPE_STRING,
            enum=["retail", "wholesale", "franchise", "corporate", "online"]
        ),

        # ---------------- PRODUCT FILTERS ----------------
        openapi.Parameter("brand_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
        openapi.Parameter("category_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),
        openapi.Parameter("model_name", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("ram", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("storage", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("processor", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter(
            "condition", openapi.IN_QUERY, type=openapi.TYPE_STRING,
            enum=["NEW", "REFURBISHED", "LIKE_NEW", "USED"]
        ),
        openapi.Parameter("color", openapi.IN_QUERY, type=openapi.TYPE_STRING),
        openapi.Parameter("release_year", openapi.IN_QUERY, type=openapi.TYPE_INTEGER),

        openapi.Parameter("device_min_price", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),
        openapi.Parameter("device_max_price", openapi.IN_QUERY, type=openapi.TYPE_NUMBER),
    # ]

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

            # --------- APPLY FILTERS ----------

            finance_qs = FinancePlanFilter.apply_filters(finance_qs, request.query_params)

            if emi_id:
                finance_qs = finance_qs.filter(emi_schedule__id=emi_id)
            if customer_id:
                finance_qs = finance_qs.filter(credit_application__customer__id=customer_id)
            if product_id:
                finance_qs = finance_qs.filter(device__id=product_id)
            if apc_score:
                finance_qs = finance_qs.filter(apc_score=apc_score)

            has_loan = request.query_params.get("has_loan")
            if has_loan and has_loan.lower() == "true":
                finance_qs = finance_qs.filter(
                    loan_account_number__isnull=False,
                    status__in=["ACTIVE", "CLOSED"]
                )

            search = request.query_params.get("search")
            if search:
                finance_qs = finance_qs.filter(
                    Q(loan_account_number__icontains=search) |
                    Q(credit_application__customer__first_name__icontains=search) |
                    Q(credit_application__customer__last_name__icontains=search) |
                    Q(credit_application__customer__document_number__icontains=search) |
                    Q(credit_application__customer__phone_number__icontains=search)
                ).distinct()

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
                if user.store:
                    finance_qs = finance_qs.filter(store=user.store)
                else:
                    finance_qs = finance_qs.none()
            elif user_role == "sales_advisor":
                finance_qs = finance_qs.filter(
                    Q(credit_application__customer__created_by__store__sales_advisor=request.user) |
                    Q(credit_application__customer__created_by__store__created_by=request.user) |
                    Q(credit_application__customer__created_by=request.user)
                ).distinct()
            elif user_role == "salesperson":
                if user.store:
                    finance_qs = finance_qs.filter(store=user.store)
                else:
                    finance_qs = finance_qs.none()
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
            all_params = "_".join(f"{k}:{v}" for k, v in sorted(request.query_params.items()))
            cache_key = f"financeplans_{user_role}_{all_params}"
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
            paginated_response = paginator.get_paginated_response(response_data)
            cache.set(cache_key, paginated_response.data, timeout=60)
            return paginated_response

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

            # --------------------- Role-Based Access ---------------------
            if user_role in ['admin', 'global_manager', 'financial_manager']:
                pass
            elif user_role == "store_manager":
                finance_qs = finance_qs.filter(credit_application__customer__created_by__store=user.store)
            elif user_role == "sales_advisor":
                finance_qs = finance_qs.filter(
                    Q(credit_application__customer__created_by__store__sales_advisor=request.user) |
                    Q(credit_application__customer__created_by__store__created_by=request.user) |
                    Q(credit_application__customer__created_by=request.user)
                ).distinct()

            elif user_role == "salesperson":
                finance_qs = finance_qs.filter(
                    Q(credit_application__customer__created_by=user) |
                    Q(credit_application__sales_person=user) |
                    Q(created_by=user)
                ).distinct()
            else:
                # If the logged-in user is a customer
                finance_qs = finance_qs.filter(credit_application__customer__created_by=user)
            plan = finance_qs.filter(id=plan_id).first()
            if not plan:
                plan = get_transient_plan_from_application(plan_id)
            if not plan:
                return Response({
                    "status": "error",
                    "message": f"Finance Plan with ID={plan_id} not found."
                }, status=status.HTTP_404_NOT_FOUND)
            serializer = FinancePlanSerializer(plan)
            masked_data = mask_sensitive_data(serializer.data, user_role)

            # Audit log
            AuditLog.objects.create(
            user=user,
            action_type="FINANCE_PLAN_VIEWED", 
            description=f"Viewed Finance Plan ID={plan_id} by {user.username if user else 'Anonymous'}",
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

    def patch(self, request, plan_id):
        try:
            plan = FinancePlan.objects.filter(id=plan_id).first()
            credit_app = None
            if plan:
                credit_app = plan.credit_application
            else:
                from customer.models import CreditApplication
                credit_app = CreditApplication.objects.filter(id=plan_id).first()

            if not plan and not credit_app:
                return Response({
                    "status": "error",
                    "message": "Finance plan not found."
                }, status=status.HTTP_404_NOT_FOUND)

            disbursement_status = request.data.get("disbursement_status")
            if disbursement_status:
                if disbursement_status not in ['PENDING', 'DISBURSED']:
                    return Response({
                        "status": "error",
                        "message": "Invalid disbursement_status. Must be PENDING or DISBURSED."
                    }, status=status.HTTP_400_BAD_REQUEST)
                if plan:
                    plan.disbursement_status = disbursement_status
                    if disbursement_status == 'DISBURSED' and not plan.disbursed_at:
                        from django.utils import timezone
                        plan.disbursed_at = timezone.now()
                    elif disbursement_status == 'PENDING':
                        plan.disbursed_at = None
                    plan.save(update_fields=["disbursement_status", "disbursed_at"])

                    # Synchronize EMI statuses based on disbursement
                    if disbursement_status == 'DISBURSED':
                        plan.emi_schedule.filter(status='DRAFT').update(status='UPCOMING')
                    elif disbursement_status == 'PENDING':
                        plan.emi_schedule.filter(status='UPCOMING').update(status='DRAFT')

                    logger.info(f"[DISBURSEMENT UPDATED] Updated status to {disbursement_status} for plan ID={plan.id}")

            disbursed_at_val = request.data.get("disbursed_at")
            if disbursed_at_val is not None:
                if plan:
                    from django.utils.dateparse import parse_datetime
                    if disbursed_at_val:
                        plan.disbursed_at = parse_datetime(disbursed_at_val)
                    else:
                        plan.disbursed_at = None
                    plan.save(update_fields=["disbursed_at"])

            imei = request.data.get("imei")
            if imei:
                if len(imei) != 15 or not imei.isdigit():
                    return Response({
                        "status": "error",
                        "message": "IMEI must be exactly 15 digits."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if credit_app:
                    duplicate_imei_exists = CreditApplication.objects.filter(
                        device_imei=imei
                    ).exclude(id=credit_app.id).exists()
                    
                    if duplicate_imei_exists:
                        return Response({
                            "status": "error",
                            "message": "This device IMEI is already enrolled in another application."
                        }, status=status.HTTP_400_BAD_REQUEST)

                    credit_app.device_imei = imei
                    credit_app.save(update_fields=["device_imei"])
                    logger.info(f"[IMEI UPDATED] Updated IMEI to {imei} for CreditApplication ID={credit_app.id}")

                # DeviceEnrollmentCustomer logic
                plan_obj = plan if plan else get_transient_plan_from_application(plan_id)
                if plan_obj:
                    # Save the plan to database if it does not exist yet (as transient plan is not saved during POST)
                    if not FinancePlan.objects.filter(id=plan_obj.id).exists():
                        plan_obj.status = "DRAFT"
                        plan_obj.created_by = request.user
                        plan_obj.store = getattr(request.user, "store", None)
                        plan_obj.save(force_insert=True)
                        plan = plan_obj
                    
                    from customer_device.models import DeviceEnrollmentCustomer
                    
                    # Check for duplicate IMEI in DeviceEnrollmentCustomer
                    duplicate_enrollment_exists = DeviceEnrollmentCustomer.objects.filter(
                        imei=imei
                    ).exclude(finance_plan=plan_obj).exists()
                    
                    if duplicate_enrollment_exists:
                        return Response({
                            "status": "error",
                            "message": "This device IMEI is already enrolled in another application."
                        }, status=status.HTTP_400_BAD_REQUEST)

                    customer = plan_obj.credit_application.customer
                    device_model = plan_obj.device
                    if not device_model:
                        return Response({
                            "status": "error",
                            "message": "Finance plan must have a device associated with it to enroll IMEI."
                        }, status=status.HTTP_400_BAD_REQUEST)

                    device_brand_name = device_model.brand.name if device_model.brand else "Unknown"

                    enrollment = DeviceEnrollmentCustomer.objects.filter(finance_plan=plan_obj).first()
                    
                    should_enroll = False
                    if not enrollment:
                        enrollment = DeviceEnrollmentCustomer(
                            finance_plan=plan_obj,
                            customer=customer,
                            imei=imei,
                            device_brand_name=device_brand_name,
                            device_model=device_model,
                            enrollment_status='NOT_STARTED'
                        )
                        enrollment.determine_locking_system()
                        enrollment.save()
                        should_enroll = True
                    elif enrollment.imei != imei:
                        enrollment.imei = imei
                        enrollment.device_brand_name = device_brand_name
                        enrollment.device_model = device_model
                        enrollment.enrollment_status = 'NOT_STARTED'
                        enrollment.determine_locking_system()
                        enrollment.save()
                        should_enroll = True
                    
                    if should_enroll:
                        from customer_device.views import DeviceEnrollmentAPIView
                        view = DeviceEnrollmentAPIView()
                        enrollment_result = view._initiate_enrollment(enrollment, customer)
                        
                        if enrollment_result.get('success'):
                            enrollment.enrollment_status = 'QR_GENERATED'
                            enrollment.enrollment_qr_code = enrollment_result.get('qr_code', '')
                            enrollment.enrollment_link = enrollment_result.get('enrollment_link', '')
                            enrollment.locking_system_id = enrollment_result.get('enrollment_id', '')
                            enrollment.save()
                            logger.info(f"[DeviceEnrollment] Enrolled IMEI {imei} on patch (success)")
                        else:
                            enrollment.enrollment_status = 'FAILED'
                            enrollment.enrollment_failed_reason = enrollment_result.get('error', 'Unknown error')
                            enrollment.save()
                            logger.error(f"[DeviceEnrollment] Enrollment failed for IMEI {imei} on patch: {enrollment_result.get('error')}")

            serialized_plan = plan if plan else get_transient_plan_from_application(plan_id)
            return Response({
                "status": "success",
                "message": "Finance plan updated successfully.",
                "data": FinancePlanSerializer(serialized_plan).data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error in patching Finance Plan")
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FinancePlanActivateAPIView(APIView):
    """
    POST: Activates a DRAFT FinancePlan, generating invoices and double-entry ledger entries.
    """
    permission_classes = [IsAuthenticatedUser]

    @swagger_auto_schema(
        operation_summary="Activate a Finance Plan",
        operation_description="Updates the plan status to ACTIVE and generates invoices/ledgers for its draft installments.",
        responses={200: "Plan activated successfully", 404: "Finance Plan not found", 400: "Invalid plan state"},
        tags=["Finance"]
    )
    def post(self, request, plan_id):
        try:
            if request.user.role not in ["salesperson", "store_manager", "admin", "global_manager", "financial_manager"]:
                return Response({
                    "status": "error",
                    "message": "Permission denied."
                }, status=status.HTTP_403_FORBIDDEN)

            plan = FinancePlan.objects.filter(credit_application_id=plan_id).first()
            if not plan:
                plan = FinancePlan.objects.filter(id=plan_id).first()

            if plan and plan.status == "ACTIVE":
                return Response({
                    "status": "success",
                    "message": "Finance Plan is already active.",
                    "data": FinancePlanSerializer(plan).data
                }, status=status.HTTP_200_OK)

            if not plan:
                from customer.models import CreditApplication
                credit_app = CreditApplication.objects.filter(id=plan_id).first()
                if not credit_app:
                    return Response({
                        "status": "error",
                        "message": f"Credit Application / Finance Plan with ID={plan_id} not found."
                    }, status=status.HTTP_404_NOT_FOUND)

                # Check if a FinancePlan already exists for this credit_app
                plan = FinancePlan.objects.filter(credit_application=credit_app).first()
                if plan:
                    # Update existing plan
                    plan.device = credit_app.device
                    plan.device_price = credit_app.device_price or Decimal("0.00")
                    plan.actual_down_payment = credit_app.initial_payment or Decimal("0.00")
                    plan.selected_term = credit_app.number_of_installments or 6
                    plan.installment_frequency_days = credit_app.installment_frequency_days or 30
                    plan.status = "ACTIVE"
                    plan.save()
                    
                    from finance.decision_engine import DecisionEngine
                    engine = DecisionEngine(plan)
                    plan = engine.run()
                    plan.status = "ACTIVE"
                    plan.save()
                else:
                    # Fetch AutoFinancePlan
                    from finance.models import AutoFinancePlan
                    latest_auto_plan = AutoFinancePlan.objects.filter(credit_application=credit_app).order_by("-id").first()
                    if not latest_auto_plan:
                        return Response({
                            "status": "error",
                            "message": "Pre-qualified Auto Finance Plan not found."
                        }, status=status.HTTP_400_BAD_REQUEST)

                    # Create the FinancePlan directly in ACTIVE status
                    from finance.decision_engine import DecisionEngine
                    plan = FinancePlan.objects.create(
                        credit_application=credit_app,
                        credit_score=latest_auto_plan.credit_score,
                        apc_score=latest_auto_plan.apc_score,
                        risk_tier=latest_auto_plan.risk_tier or "TIER_A",
                        customer_monthly_income=3000,
                        payment_capacity_factor=latest_auto_plan.payment_capacity_factor or Decimal("0.20"),
                        maximum_allowed_installment=latest_auto_plan.maximum_allowed_installment or Decimal("0.00"),
                        minimum_down_payment_percentage=latest_auto_plan.minimum_down_payment_percentage or Decimal("0.00"),
                        
                        device=credit_app.device,
                        device_price=credit_app.device_price or Decimal("0.00"),
                        actual_down_payment=credit_app.initial_payment or Decimal("0.00"),
                        selected_term=credit_app.number_of_installments or 6,
                        installment_frequency_days=credit_app.installment_frequency_days or 30,
                        status="ACTIVE",
                        
                        down_payment_percentage=Decimal("0.00"),
                        amount_to_finance=credit_app.amount_to_finance or Decimal("0.00"),
                        monthly_installment=credit_app.installment_amount or Decimal("0.00"),
                        total_amount_payable=credit_app.total_amount or Decimal("0.00"),
                        installment_to_income_ratio=Decimal("0.00"),
                        created_by=request.user,
                        store=getattr(request.user, "store", None),
                    )
                    
                    engine = DecisionEngine(plan)
                    plan = engine.run()
                    plan.status = "ACTIVE"
                    plan.save()

                # Generate the EMISchedule if missing
                if not plan.emi_schedule.exists():
                    import datetime
                    from .models import EMISchedule
                    first_due = timezone.now().date() + datetime.timedelta(days=plan.installment_frequency_days)
                    EMISchedule.generate_schedule(plan, first_due)

            else:
                plan.status = "ACTIVE"
                plan.save(update_fields=["status"])
                # Generate the EMISchedule if missing
                if not plan.emi_schedule.exists():
                    import datetime
                    from .models import EMISchedule
                    first_due = timezone.now().date() + datetime.timedelta(days=plan.installment_frequency_days)
                    EMISchedule.generate_schedule(plan, first_due)

            # Update credit application status to APPROVED
            credit_app = plan.credit_application
            credit_app.status = "APPROVED"
            credit_app.save(update_fields=["status"])

            # Update customer status to ACTIVE
            customer = credit_app.customer
            customer.status = "ACTIVE"
            customer.save(update_fields=["status"])

            # Ensure DeviceEnrollmentCustomer is created at loan activation/disbursal if it has an IMEI and not already present
            if credit_app.device_imei:
                from customer_device.models import DeviceEnrollmentCustomer
                enrollment = DeviceEnrollmentCustomer.objects.filter(finance_plan=plan).first()
                if not enrollment:
                    device_model = plan.device
                    device_brand_name = device_model.brand.name if device_model and device_model.brand else "Unknown"
                    
                    enrollment = DeviceEnrollmentCustomer.objects.create(
                        finance_plan=plan,
                        customer=customer,
                        imei=credit_app.device_imei,
                        device_brand_name=device_brand_name,
                        device_model=device_model,
                        enrollment_status='NOT_STARTED'
                    )
                    # determine_locking_system is automatically run on save()
                    
                    # Initiate enrollment
                    from customer_device.views import DeviceEnrollmentAPIView
                    view = DeviceEnrollmentAPIView()
                    enrollment_result = view._initiate_enrollment(enrollment, customer)
                    if enrollment_result.get('success'):
                        enrollment.enrollment_status = 'QR_GENERATED'
                        enrollment.enrollment_qr_code = enrollment_result.get('qr_code', '')
                        enrollment.enrollment_link = enrollment_result.get('enrollment_link', '')
                        enrollment.locking_system_id = enrollment_result.get('enrollment_id', '')
                        enrollment.save()
                    else:
                        enrollment.enrollment_status = 'FAILED'
                        enrollment.enrollment_failed_reason = enrollment_result.get('error', 'Unknown error')
                        enrollment.save()

            # Generate and save the PDF agreement to the CreditApplication model
            from django.core.files.base import ContentFile
            from .services import ContractService
            from customer.sms_utils import send_sms
            from django.core.mail import EmailMessage
            
            pdf_data = None
            filename = f"loan_agreement_{credit_app.id}.pdf"
            try:
                agreement_text = ContractService.generate_loan_agreement(plan)
                pdf_data = ContractService.generate_pdf_from_text(agreement_text)
                
                credit_app.loan_agreement_pdf.save(filename, ContentFile(pdf_data), save=True)
                logger.info(f"[FinancePlanActivateAPIView] Saved PDF for CreditApplication ID={credit_app.id}")
            except Exception as e:
                logger.exception("[FinancePlanActivateAPIView] Failed to generate/save loan agreement PDF")

            # Send SMS to customer phone
            if customer.phone_number:
                try:
                    sms_message = f"Hola {customer.first_name}, su financiamiento con Ola Credit ha sido activado con exito. Su equipo {plan.device.model_name if plan.device else 'dispositivo'} ha sido entregado."
                    send_sms(customer.phone_number, sms_message)
                    logger.info(f"[FinancePlanActivateAPIView] Sent SMS to {customer.phone_number}")
                except Exception as sms_ex:
                    logger.exception("[FinancePlanActivateAPIView] Failed to send activation SMS")

            # Send Email with PDF attachment
            if customer.email and pdf_data:
                try:
                    email_subject = "Ola Credit - Financiamiento Activado / Contrato de Credito"
                    email_body = f"""Estimado(a) {customer.first_name} {customer.last_name},

Nos complace informarle que su financiamiento con Ola Credit ha sido activado exitosamente y su dispositivo ha sido entregado.

Adjunto a este correo encontrara el Contrato de Credito firmado correspondiente a su solicitud.

Detalles del Financiamiento:
- Dispositivo: {plan.device.brand.name if plan.device and plan.device.brand else ''} {plan.device.model_name if plan.device else 'N/A'}
- Plazo: {plan.selected_term} Meses
- Frecuencia: Cada {plan.installment_frequency_days} Dias
- Cuota de pago: ${plan.monthly_installment} USD

Gracias por confiar en Ola Credit.

Atentamente,
El equipo de Ola Credit Panama, S.A.
"""
                    email_message = EmailMessage(
                        email_subject,
                        email_body,
                        to=[customer.email]
                    )
                    email_message.attach(filename, pdf_data, "application/pdf")
                    email_message.send()
                    logger.info(f"[FinancePlanActivateAPIView] Sent activation email to {customer.email}")
                except Exception as email_ex:
                    logger.exception("[FinancePlanActivateAPIView] Failed to send activation email")

            AuditLog.objects.create(
                user=request.user,
                action_type="FINANCE_PLAN_ACTIVATED",
                description=f"Finance plan ID={plan_id} activated.",
                metadata={"plan_id": plan_id}
            )

            return Response({
                "status": "success",
                "message": "Finance Plan activated successfully.",
                "data": FinancePlanSerializer(plan).data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("[FinancePlanActivateAPIView] Error activating Finance Plan.")
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
            from .models import Invoice
            from django.db.models import Q, Sum
            
            user = request.user
            user_role = getattr(user, "role", "Customer")

            # ==================================================
            # Base Query based on Invoice
            # ==================================================
            qs = (
                Invoice.objects.select_related(
                    "customer",
                    "finance_plan",
                    "finance_plan__store",                
                    "finance_plan__store__region",        
                    "finance_plan__credit_application",
                    "finance_plan__device",
                    "emi_schedule",
                )
                .prefetch_related(
                    "emi_schedule__payments",
                )
                .order_by("-due_date")
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
                qs = qs.filter(customer=user)
            else:
                qs = qs.none()

            # ==================================================
            # Query Filters (status, type, date, etc.)
            # ==================================================
            params = request.query_params
            
            # Map payment_status to invoice status
            status_param = params.get("payment_status")
            mapped_status = None
            if status_param:
                status_map = {
                    "COMPLETED": "PAID",
                    "PENDING": "PENDING",
                    "FAILED": "OVERDUE",
                }
                mapped_status = status_map.get(status_param.upper(), status_param.upper())

            # Map payment_type to invoice_type
            type_param = params.get("payment_type")
            mapped_type = None
            if type_param:
                if type_param.upper() == "EMI":
                    mapped_type = "PLAN"
                elif type_param.upper() == "DOWN_PAYMENT":
                    # Down payments are down payments, could map to a specific type if defined
                    pass

            filters = {
                "payment_method__iexact": params.get("payment_method"),
                "finance_plan__store__region__id": params.get("region_id"),
                "finance_plan__store__id": params.get("store_id"),
                "customer__id": params.get("customer_id"),
                "finance_plan__id": params.get("finance_plan_id"),
                "finance_plan__created_by__id": params.get("salesperson_id") or params.get("sales_advisor_id"),
            }

            for key, value in filters.items():
                if value:
                    qs = qs.filter(**{key: value})

            if mapped_status:
                qs = qs.filter(status=mapped_status)
            if mapped_type:
                qs = qs.filter(invoice_type=mapped_type)

            # Search Filter
            search = params.get("search")
            if search:
                search_q = Q(invoice_number__icontains=search) | \
                           Q(customer__first_name__icontains=search) | \
                           Q(customer__last_name__icontains=search) | \
                           Q(customer__phone__icontains=search) | \
                           Q(customer__document_number__icontains=search) | \
                           Q(finance_plan__device__brand__name__icontains=search) | \
                           Q(finance_plan__device__model_name__icontains=search) | \
                           Q(status__icontains=search) | \
                           Q(notes__icontains=search) | \
                           Q(invoice_type__icontains=search)

                # Optional numeric search
                try:
                    from decimal import Decimal, InvalidOperation
                    decimal_val = Decimal(search)
                    search_q |= Q(total_amount=decimal_val) | Q(amount_paid=decimal_val) | Q(balance=decimal_val)
                except (InvalidOperation, ValueError, TypeError):
                    pass

                # Optional date search
                try:
                    date_val = datetime.strptime(search, "%Y-%m-%d").date()
                    search_q |= Q(due_date=date_val) | Q(created_at__date=date_val)
                except (ValueError, TypeError):
                    pass

                qs = qs.filter(search_q).distinct()

            # Custom Ordering/Sorting
            ordering = params.get("ordering")
            if ordering:
                ordering_fields = {
                    "payment_date": "updated_at",
                    "-payment_date": "-updated_at",
                    "due_date": "due_date",
                    "-due_date": "-due_date",
                    "amount": "total_amount",
                    "-amount": "-total_amount",
                    "customer_name": "customer__first_name",
                    "-customer_name": "-customer__first_name",
                    "created_at": "created_at",
                    "-created_at": "-created_at",
                }
                mapped_ordering = ordering_fields.get(ordering)
                if mapped_ordering:
                    qs = qs.order_by(mapped_ordering)

            start_date = params.get("start_date")
            end_date = params.get("end_date")

            if start_date:
                try:
                    qs = qs.filter(created_at__date__gte=datetime.strptime(start_date, "%Y-%m-%d").date())
                except ValueError:
                    pass
            if end_date:
                try:
                    qs = qs.filter(created_at__date__lte=datetime.strptime(end_date, "%Y-%m-%d").date())
                except ValueError:
                    pass

            # ==================================================
            # Analytics Calculation
            # ==================================================
            total_installments = qs.count()
            total_collected = float(qs.aggregate(total=Sum("amount_paid"))["total"] or 0)
            total_due = float(qs.aggregate(total=Sum("total_amount"))["total"] or 0)
            total_pending = float(qs.aggregate(total=Sum("balance"))["total"] or 0)
            collection_rate = (total_collected / total_due * 100) if total_due > 0 else 0.0

            # --- Overdue Analytics ---
            overdue_qs = qs.filter(
                Q(status="OVERDUE") |
                Q(status__in=["PENDING", "PARTIAL"], due_date__lt=timezone.now().date())
            )
            total_overdue = float(overdue_qs.aggregate(total=Sum("balance"))["total"] or 0)
            total_overdue_installments = overdue_qs.count()
            customers_with_overdue = overdue_qs.values_list(
                "customer", flat=True
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

            for inv in qs:
                fp = inv.finance_plan
                store = getattr(fp, "store", None) if fp else None
                region = getattr(store.region, "name", None) if store else None
                if not region:
                    continue

                region_data = region_summary[region]
                region_data["region_name"] = region
                region_data["total_installments"] += 1

                region_data["total_collected"] += float(inv.amount_paid or 0)
                region_data["total_pending"] += float(inv.balance or 0)

                is_overdue = inv.status == "OVERDUE" or (inv.status in ["PENDING", "PARTIAL"] and inv.due_date < timezone.now().date())
                if is_overdue:
                    region_data["total_overdue"] += float(inv.balance or 0)

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
            if mapped_status:
                list_qs = qs
            else:
                list_qs = qs.exclude(status="PAID")

            paginator = FinancePlanPagination()
            page = paginator.paginate_queryset(list_qs, request)

            results = []
            for inv in page:
                fp = inv.finance_plan
                store = getattr(fp, "store", None) if fp else None
                region = getattr(store.region, "name", None) if store else None
                dev = getattr(fp, "device", None) if fp else None
                cust = inv.customer
                emi = inv.emi_schedule

                # Map status to payment status equivalent
                payment_status = "PENDING"
                if inv.status == "PAID":
                    payment_status = "COMPLETED"
                elif inv.status == "OVERDUE" or (inv.status in ["PENDING", "PARTIAL"] and inv.due_date < timezone.now().date()):
                    payment_status = "FAILED"

                # Check if there is completed payments
                payment_method = "N/A"
                payment_date = None
                if emi:
                    last_payment = emi.payments.filter(payment_status="COMPLETED").order_by("-payment_date").first()
                    if last_payment:
                        payment_method = last_payment.payment_method
                        payment_date = last_payment.payment_date.isoformat() if last_payment.payment_date else None

                # Fallback to check PaymentReceived records for invoice payment association
                if not payment_date and cust:
                    from .models import PaymentReceived
                    recent_payments = PaymentReceived.objects.filter(customer=cust).order_by("-payment_date")[:10]
                    for pay in recent_payments:
                        if isinstance(pay.invoices, list):
                            for item in pay.invoices:
                                if int(item.get("invoice_id", 0)) == inv.id:
                                    payment_method = pay.payment_method
                                    payment_date = pay.payment_date.isoformat()
                                    break
                        if payment_date:
                            break

                if not payment_date and inv.status == "PAID":
                    payment_date = inv.updated_at.isoformat()

                item = {
                    "payment_id": inv.id,
                    "payment_amount": float(inv.total_amount),
                    "payment_type": "EMI" if inv.invoice_type == "PLAN" else "MANUAL",
                    "payment_method": payment_method,
                    "payment_status": payment_status,
                    "payment_date": payment_date,
                    "finance_plan": {
                        "finance_plan_id": fp.id if fp else None,
                        "amount": float(fp.amount_to_finance or 0) if fp else None,
                        "store": getattr(store, "name", None),
                        "region": region,
                        "device": {"id": dev.id, "model_name": dev.model_name} if dev else None,
                        "customer": {
                            "id": cust.id,
                            "name": f"{cust.first_name} {cust.last_name}",
                            "phone": getattr(cust, "phone_number", None)
                        } if cust else None,
                    },
                    "emi_schedule": {
                        "emi_id": emi.id if emi else None,
                        "due_date": emi.due_date.isoformat() if emi and emi.due_date else inv.due_date.isoformat(),
                        "amount_due": float(emi.installment_amount or 0) if emi else float(inv.total_amount),
                        "status": getattr(emi, "status", None) if emi else inv.status,
                    },
                    "invoice": {
                        "invoice_id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "total_amount": float(inv.total_amount),
                        "amount_paid": float(inv.amount_paid),
                        "balance": float(inv.balance),
                        "status": inv.status,
                    }
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
                "count": list_qs.count(),
            }

            return Response(payload, status=status.HTTP_200_OK)

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
        - SalesAdvisor -> Only for their region
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
                emi_qs = emi_qs.filter(
                    Q(finance_plan__store__sales_advisor=user) |
                    Q(finance_plan__store__created_by=user) |
                    Q(finance_plan__created_by=user)
                ).distinct()

            elif role == "store_manager":
                store = getattr(user, "store", None)
                if store:
                    emi_qs = emi_qs.filter(finance_plan__store=store)
                else:
                    return Response({"error": "Store not assigned to user"}, status=403)

            elif role == "salesperson":
                store = getattr(user, "store", None)
                if store:
                    emi_qs = emi_qs.filter(finance_plan__store=store)
                else:
                    emi_qs = emi_qs.none()

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
            if user_role in ['admin', 'global_manager', 'financial_manager']:
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

def parse_importe(importe_val):
    s = str(importe_val).strip()
    if not s.isdigit():
        return Decimal("0.00")
    if len(s) < 3:
        return Decimal(s)
    integer_part = s[:-2]
    decimal_part = s[-2:]
    return Decimal(f"{integer_part}.{decimal_part}")


class VerifyCustomerAPIView(APIView):
    permission_classes = [AllowAny]
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
                "tipo_operacion", "campos_busqueda", "utility",
                "terminal", "fecha", "hora", "cod_operacion"
            ],
            properties={
                "tipo_operacion": openapi.Schema(type=openapi.TYPE_STRING, example="CashIn"),
                "campos_busqueda": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "campo1": openapi.Schema(type=openapi.TYPE_STRING, example="12345678"),
                            "campo2": openapi.Schema(type=openapi.TYPE_STRING, example="996884"),
                        }
                    )
                ),
                "utility": openapi.Schema(type=openapi.TYPE_STRING, example="90061234"),
                "terminal": openapi.Schema(type=openapi.TYPE_STRING, example="D00561"),
                "fecha": openapi.Schema(type=openapi.TYPE_STRING, example="20190106"),
                "hora": openapi.Schema(type=openapi.TYPE_STRING, example="101940"),
                "cod_operacion": openapi.Schema(type=openapi.TYPE_STRING, example="C"),
                "user": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
                "password": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
            },
        ),
        responses={
            200: openapi.Response(
                description="Customer and EMI details found successfully",
                examples={
                    "application/json": {
                        "tipo_operacion": "CashIn",
                        "cod_cliente": "77893",
                        "nom_cliente": "Manuel Belgrano",
                        "cod_severidad": "0",
                        "utility": "90061234",
                        "terminal": "D00561",
                        "fecha": "20190106",
                        "hora": "101940",
                        "cod_operacion": "C",
                        "cod_respuesta": "0",
                        "msg_respuesta": "Consulta exitosa",
                        "items": [
                            {
                                "id_item": "123456",
                                "cod_barra": "90061234000232500005656500",
                                "importe": "75000",
                                "monto_abierto": False,
                                "texto_mostrar": "Factura 1",
                                "prioriza_deuda": "",
                                "orden": 0,
                                "fecha_vencimiento": "20190201"
                            }
                        ]
                    }
                },
            ),
        },
    )
    def post(self, request):
        serializer = VerifyCustomerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Validate credentials (supporting user, username, and userName keys)
        req_user = (
            request.data.get("user") or 
            request.data.get("username") or 
            request.data.get("userName") or 
            "pagofacil"
        )
        req_pass = request.data.get("password") or "pagofacil"
        if req_user != settings.WESTERN_USER or req_pass != settings.WESTERN_PASS:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "cod_cliente": "",
                "nom_cliente": "",
                "cod_severidad": "0",
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_respuesta": "9",
                "msg_respuesta": "Invalid credentials",
                "items": []
            }, status=status.HTTP_200_OK)

        campos = data.get("campos_busqueda", [])
        if not campos or not isinstance(campos, list):
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "cod_cliente": "",
                "nom_cliente": "",
                "cod_severidad": "0",
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_respuesta": "8",
                "msg_respuesta": "Error de validación del campo de búsqueda",
                "items": []
            }, status=status.HTTP_200_OK)

        campo1 = campos[0].get("campo1", "").strip()
        if not campo1:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "cod_cliente": "",
                "nom_cliente": "",
                "cod_severidad": "0",
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_respuesta": "8",
                "msg_respuesta": "Error de validación del campo de búsqueda",
                "items": []
            }, status=status.HTTP_200_OK)

        # Search customer by document_number or ID
        customer = Customer.objects.filter(document_number=campo1).first()
        if not customer and campo1.isdigit():
            customer = Customer.objects.filter(id=int(campo1)).first()

        if not customer:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "cod_cliente": "",
                "nom_cliente": "",
                "cod_severidad": "0",
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_respuesta": "7",
                "msg_respuesta": "Cliente no existe",
                "items": []
            }, status=status.HTTP_200_OK)

        # Fetch pending Invoices
        from .models import Invoice
        pending_invoices = Invoice.objects.filter(
            customer=customer,
            status__in=["PENDING", "PARTIAL", "OVERDUE"]
        ).order_by("due_date", "id")

        if not pending_invoices.exists():
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "cod_cliente": str(customer.id),
                "nom_cliente": f"{customer.first_name} {customer.last_name}",
                "cod_severidad": "0",
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_respuesta": "6",
                "msg_respuesta": "No existe registro",
                "items": []
            }, status=status.HTTP_200_OK)

        items = []
        for inv in pending_invoices:
            # Format: Utility (8) + Id_item (21) + Monto abierto (1) + Importe (11) + Vencimiento (5) + Filler (13)
            utility_str = data.get("utility", "").zfill(8)[:8]
            id_item_str = str(inv.id).zfill(21)[:21]
            monto_abierto_str = "0"
            cents = int(round(inv.balance * 100))
            importe_str = str(cents).zfill(11)[:11]
            
            # Julian date AAJJJ
            due_date = inv.due_date
            aa = due_date.strftime("%y")
            jjj = f"{due_date.timetuple().tm_yday:03d}"
            julian_str = f"{aa}{jjj}"
            filler_str = "0" * 13

            cod_barra = f"{utility_str}{id_item_str}{monto_abierto_str}{importe_str}{julian_str}{filler_str}"

            items.append({
                "id_item": str(inv.id),
                "cod_barra": cod_barra,
                "importe": str(cents),
                "monto_abierto": False,
                "texto_mostrar": f"Factura {inv.invoice_number} - Vence {due_date.strftime('%Y-%m-%d')}",
                "prioriza_deuda": "",
                "orden": 0,
                "fecha_vencimiento": due_date.strftime("%Y%m%d")
            })

        response = {
            "tipo_operacion": data.get("tipo_operacion"),
            "cod_cliente": str(customer.id),
            "nom_cliente": f"{customer.first_name} {customer.last_name}",
            "cod_severidad": "0",
            "utility": data.get("utility"),
            "terminal": data.get("terminal"),
            "fecha": data.get("fecha"),
            "hora": data.get("hora"),
            "cod_operacion": data.get("cod_operacion"),
            "cod_respuesta": "0",
            "msg_respuesta": "Consulta exitosa",
            "items": items
        }
        return Response(response, status=status.HTTP_200_OK)


class WesternUnionPaymentAPIView(APIView):
    permission_classes = [AllowAny]
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
                "tipo_operacion", "cod_cliente", "cod_operacion", "id_item", "terminal",
                "fecha", "hora", "secuencia", "cod_trx", "cod_barra", "utility", "importe",
                "medio_pago", "user", "password"
            ],
            properties={
                "tipo_operacion": openapi.Schema(type=openapi.TYPE_STRING, example="CashIn"),
                "cod_cliente": openapi.Schema(type=openapi.TYPE_STRING, example="77893"),
                "cod_operacion": openapi.Schema(type=openapi.TYPE_STRING, example="D"),
                "id_item": openapi.Schema(type=openapi.TYPE_STRING, example="123456"),
                "terminal": openapi.Schema(type=openapi.TYPE_STRING, example="D00561"),
                "fecha": openapi.Schema(type=openapi.TYPE_STRING, example="20190106"),
                "hora": openapi.Schema(type=openapi.TYPE_STRING, example="102000"),
                "secuencia": openapi.Schema(type=openapi.TYPE_STRING, example="1125"),
                "cod_trx": openapi.Schema(type=openapi.TYPE_STRING, example="D00561201901061020001125"),
                "cod_barra": openapi.Schema(type=openapi.TYPE_STRING, example="90061234000232500005656500"),
                "utility": openapi.Schema(type=openapi.TYPE_STRING, example="90061234"),
                "importe": openapi.Schema(type=openapi.TYPE_STRING, example="75000"),
                "medio_pago": openapi.Schema(type=openapi.TYPE_STRING, example="E01"),
                "user": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
                "password": openapi.Schema(type=openapi.TYPE_STRING, example="pagofacil"),
            }
        ),
        responses={
            200: openapi.Response(
                description="Payment Successful",
                examples={
                    "application/json": {
                        "tipo_operacion": "CashIn",
                        "utility": "90061234",
                        "terminal": "D00561",
                        "fecha": "20190106",
                        "hora": "102000",
                        "secuencia": "1125",
                        "cod_trx": "D00561201901061020001125",
                        "cod_operacion": "D",
                        "cod_severidad": "0",
                        "cod_respuesta": "0",
                        "msg_respuesta": "Cobranza exitosa",
                        "texto_ticket": "Mensaje propio de la entidad"
                    }
                },
            ),
        },
        tags=["Western Union Payments"]
    )
    def post(self, request):
        serializer = WesternUnionPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1. Validate credentials (supporting user, username, and userName keys)
        req_user = (
            request.data.get("user") or 
            request.data.get("username") or 
            request.data.get("userName") or 
            "pagofacil"
        )
        req_pass = request.data.get("password") or "pagofacil"
        if req_user != settings.WESTERN_USER or req_pass != settings.WESTERN_PASS:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "secuencia": data.get("secuencia"),
                "cod_trx": data.get("cod_trx"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_severidad": "0",
                "cod_respuesta": "9",
                "msg_respuesta": "Invalid credentials"
            }, status=status.HTTP_200_OK)

        # 2. Utility validation
        if data.get("utility") != settings.WESTERN_UTILITY:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "secuencia": data.get("secuencia"),
                "cod_trx": data.get("cod_trx"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_severidad": "0",
                "cod_respuesta": "9",
                "msg_respuesta": "Invalid utility"
            }, status=status.HTTP_200_OK)

        # 3. Duplicate payment protection
        cod_trx = data.get("cod_trx")
        existing_payment = PaymentRecord.objects.filter(
            transaction_reference=cod_trx,
            payment_method="WESTERN_UNION"
        ).first()

        if existing_payment:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "secuencia": data.get("secuencia"),
                "cod_trx": data.get("cod_trx"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_severidad": "0",
                "cod_respuesta": "0",
                "msg_respuesta": "Transaction already processed",
                "texto_ticket": f"Payment already registered with transaction ref: {cod_trx}"
            }, status=status.HTTP_200_OK)

        id_item = data.get("id_item")
        try:
            id_item_int = int(id_item)
        except (ValueError, TypeError):
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "secuencia": data.get("secuencia"),
                "cod_trx": data.get("cod_trx"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_severidad": "0",
                "cod_respuesta": "9",
                "msg_respuesta": "Invoice record not found",
                "texto_ticket": "Payment could not be processed."
            }, status=status.HTTP_200_OK)

        # 4. Idempotency Lock using select_for_update inside transaction.atomic
        from .models import Invoice, EMIConfiguration, BankAccount, PaymentReceived
        try:
            with transaction.atomic():
                invoice = Invoice.objects.select_for_update().get(id=id_item_int)

                # 5. Customer validation
                expected_customer_id = invoice.customer.id
                incoming_customer_id = data.get("cod_cliente")
                if str(expected_customer_id) != str(incoming_customer_id):
                    return Response({
                        "tipo_operacion": data.get("tipo_operacion"),
                        "utility": data.get("utility"),
                        "terminal": data.get("terminal"),
                        "fecha": data.get("fecha"),
                        "hora": data.get("hora"),
                        "secuencia": data.get("secuencia"),
                        "cod_trx": data.get("cod_trx"),
                        "cod_operacion": data.get("cod_operacion"),
                        "cod_severidad": "0",
                        "cod_respuesta": "9",
                        "msg_respuesta": "Customer validation failed",
                        "texto_ticket": "Payment could not be processed."
                    }, status=status.HTTP_200_OK)

                # 6. Barcode validation
                utility_str = data.get("utility", "").zfill(8)[:8]
                id_item_str = str(invoice.id).zfill(21)[:21]
                monto_abierto_str = "0"
                cents = int(round(invoice.balance * 100))
                importe_str = str(cents).zfill(11)[:11]
                
                due_date = invoice.due_date
                aa = due_date.strftime("%y")
                jjj = f"{due_date.timetuple().tm_yday:03d}"
                julian_str = f"{aa}{jjj}"
                filler_str = "0" * 13

                expected_cod_barra = f"{utility_str}{id_item_str}{monto_abierto_str}{importe_str}{julian_str}{filler_str}"
                
                if data.get("cod_barra") != expected_cod_barra:
                    return Response({
                        "tipo_operacion": data.get("tipo_operacion"),
                        "utility": data.get("utility"),
                        "terminal": data.get("terminal"),
                        "fecha": data.get("fecha"),
                        "hora": data.get("hora"),
                        "secuencia": data.get("secuencia"),
                        "cod_trx": data.get("cod_trx"),
                        "cod_operacion": data.get("cod_operacion"),
                        "cod_severidad": "0",
                        "cod_respuesta": "9",
                        "msg_respuesta": "Barcode validation failed",
                        "texto_ticket": "Payment could not be processed."
                    }, status=status.HTTP_200_OK)

                # 7. Parse payment amount and check exact amount for closed amount (monto_abierto = False)
                amount = parse_importe(data.get("importe", "0"))
                pending_amount = invoice.balance

                if amount != pending_amount:
                    return Response({
                        "tipo_operacion": data.get("tipo_operacion"),
                        "utility": data.get("utility"),
                        "terminal": data.get("terminal"),
                        "fecha": data.get("fecha"),
                        "hora": data.get("hora"),
                        "secuencia": data.get("secuencia"),
                        "cod_trx": data.get("cod_trx"),
                        "cod_operacion": data.get("cod_operacion"),
                        "cod_severidad": "0",
                        "cod_respuesta": "5",
                        "msg_respuesta": f"Payment amount ({amount}) must exactly match pending Invoice amount ({pending_amount})",
                        "texto_ticket": f"Payment rejected. Exact pending amount is ₹{pending_amount:.2f}."
                    }, status=status.HTTP_200_OK)

                # 8. Resolve Western Union bank account
                bank_account = None
                config = EMIConfiguration.objects.filter(is_active=True).first()
                if config and config.western_union_bank_account:
                    bank_account = config.western_union_bank_account

                if not bank_account:
                    wu_bank_acc_num = getattr(settings, 'WESTERN_UNION_BANK_ACCOUNT_NUMBER', '9876543211')
                    bank_account = BankAccount.objects.filter(account_number=wu_bank_acc_num).first()
                    if not bank_account:
                        bank_account = BankAccount.objects.create(
                            bank_name="Western Union Settlement Bank",
                            account_number=wu_bank_acc_num,
                            account_holder_name="Ola Credit",
                            initial_balance=Decimal('0.00'),
                            status="ACTIVE",
                            account_name="Western Union Account"
                        )

                deposited_to = bank_account.accounting_code
                if not deposited_to:
                    from .models import AccountingCode
                    deposited_to = AccountingCode.objects.filter(code="1100").first()

                # Generate payment number PR-YYYYMMDD-XXXX
                import random
                date_str = timezone.now().strftime("%Y%m%d")
                rand_str = str(random.randint(1000, 9999))
                payment_number = f"PR-{date_str}-{rand_str}"
                while PaymentReceived.objects.filter(payment_number=payment_number).exists():
                    rand_str = str(random.randint(1000, 9999))
                    payment_number = f"PR-{date_str}-{rand_str}"

                payment_notes = (
                    f"Payment received via Western Union (Ref: {cod_trx}). "
                    f"Deposited to bank account {bank_account.bank_name} - A/C: {bank_account.account_number} ({deposited_to.name if deposited_to else 'None'})"
                )

                # Create PaymentReceived record
                payment_received = PaymentReceived.objects.create(
                    payment_number=payment_number,
                    customer=invoice.customer,
                    amount_received=amount,
                    payment_date=timezone.now(),
                    payment_method='WESTERN_UNION',
                    transaction_reference=cod_trx,
                    deposited_to=deposited_to,
                    invoices=[{
                        'invoice_id': invoice.id,
                        'amount_applied': float(amount)
                    }],
                    notes=payment_notes
                )
                payment_received.process_payment(user=None)

                # Fetch or create target PaymentRecord just to maintain compatibility
                payment_rec = PaymentRecord.objects.filter(payment_received=payment_received).first()
                if not payment_rec:
                    PaymentRecord.objects.create(
                        finance_plan=invoice.finance_plan,
                        emi_schedule=invoice.emi_schedule,
                        payment_received=payment_received,
                        payment_type="EMI",
                        payment_method="WESTERN_UNION",
                        payment_amount=amount,
                        payment_date=timezone.now(),
                        payment_status="COMPLETED",
                        transaction_reference=cod_trx,
                        notes="Payment received via Western Union"
                    )

        except Invoice.DoesNotExist:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "secuencia": data.get("secuencia"),
                "cod_trx": data.get("cod_trx"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_severidad": "0",
                "cod_respuesta": "9",
                "msg_respuesta": "Invoice record not found",
                "texto_ticket": "Payment could not be processed."
            }, status=status.HTTP_200_OK)

        return Response({
            "tipo_operacion": data.get("tipo_operacion"),
            "utility": data.get("utility"),
            "terminal": data.get("terminal"),
            "fecha": data.get("fecha"),
            "hora": data.get("hora"),
            "secuencia": data.get("secuencia"),
            "cod_trx": data.get("cod_trx"),
            "cod_operacion": data.get("cod_operacion"),
            "cod_severidad": "0",
            "cod_respuesta": "0",
            "msg_respuesta": "Cobranza exitosa",
            "texto_ticket": f"Thank you! Your payment of ₹{amount} was received successfully."
        }, status=status.HTTP_200_OK)


class WesternUnionReverseAPIView(APIView):
    permission_classes = [AllowAny]
    """
    Step 3: Western Union calls this API to reverse a transaction.
    Endpoint: /reversa/
    only for western union dashboard
    """
    @swagger_auto_schema(
        operation_summary="Process Western Union Reversal- FOR WESTERN UNION (NOT FOR FROTEND)",
        operation_description=(
            "This API is called by Western Union to reverse a payment transaction."
        ),
        request_body=WesternUnionPaymentSerializer,
        responses={
            200: openapi.Response(
                description="Reversal Successful",
                examples={
                    "application/json": {
                        "tipo_operacion": "CashIn",
                        "utility": "90061234",
                        "terminal": "D00561",
                        "fecha": "20190106",
                        "hora": "102000",
                        "secuencia": "1125",
                        "cod_trx": "D00561201901061020001125",
                        "cod_operacion": "R",
                        "cod_severidad": "0",
                        "cod_respuesta": "0",
                        "msg_respuesta": "Reversa exitosa"
                    }
                },
            ),
        },
        tags=["Western Union Payments"]
    )
    def post(self, request):
        serializer = WesternUnionPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1. Validate credentials (supporting user, username, and userName keys)
        req_user = (
            request.data.get("user") or 
            request.data.get("username") or 
            request.data.get("userName") or 
            "pagofacil"
        )
        req_pass = request.data.get("password") or "pagofacil"
        if req_user != settings.WESTERN_USER or req_pass != settings.WESTERN_PASS:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "secuencia": data.get("secuencia"),
                "cod_trx": data.get("cod_trx"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_severidad": "0",
                "cod_respuesta": "9",
                "msg_respuesta": "Invalid credentials"
            }, status=status.HTTP_200_OK)

        # 2. Utility validation
        if data.get("utility") != settings.WESTERN_UTILITY:
            return Response({
                "tipo_operacion": data.get("tipo_operacion"),
                "utility": data.get("utility"),
                "terminal": data.get("terminal"),
                "fecha": data.get("fecha"),
                "hora": data.get("hora"),
                "secuencia": data.get("secuencia"),
                "cod_trx": data.get("cod_trx"),
                "cod_operacion": data.get("cod_operacion"),
                "cod_severidad": "0",
                "cod_respuesta": "9",
                "msg_respuesta": "Invalid utility"
            }, status=status.HTTP_200_OK)

        cod_trx = data.get("cod_trx")
        
        with transaction.atomic():
            payment = PaymentRecord.objects.select_for_update().filter(
                transaction_reference=cod_trx,
                payment_method="WESTERN_UNION"
            ).first()

            if not payment:
                return Response({
                    "tipo_operacion": data.get("tipo_operacion"),
                    "utility": data.get("utility"),
                    "terminal": data.get("terminal"),
                    "fecha": data.get("fecha"),
                    "hora": data.get("hora"),
                    "secuencia": data.get("secuencia"),
                    "cod_trx": data.get("cod_trx"),
                    "cod_operacion": data.get("cod_operacion"),
                    "cod_severidad": "0",
                    "cod_respuesta": "9",
                    "msg_respuesta": "Payment record not found"
                }, status=status.HTTP_200_OK)

            if payment.payment_status == "REVERSED":
                return Response({
                    "tipo_operacion": data.get("tipo_operacion"),
                    "utility": data.get("utility"),
                    "terminal": data.get("terminal"),
                    "fecha": data.get("fecha"),
                    "hora": data.get("hora"),
                    "secuencia": data.get("secuencia"),
                    "cod_trx": data.get("cod_trx"),
                    "cod_operacion": data.get("cod_operacion"),
                    "cod_severidad": "0",
                    "cod_respuesta": "0",
                    "msg_respuesta": "Transaction already reversed"
                }, status=status.HTTP_200_OK)

            if payment.payment_status != "COMPLETED":
                return Response({
                    "tipo_operacion": data.get("tipo_operacion"),
                    "utility": data.get("utility"),
                    "terminal": data.get("terminal"),
                    "fecha": data.get("fecha"),
                    "hora": data.get("hora"),
                    "secuencia": data.get("secuencia"),
                    "cod_trx": data.get("cod_trx"),
                    "cod_operacion": data.get("cod_operacion"),
                    "cod_severidad": "0",
                    "cod_respuesta": "9",
                    "msg_respuesta": f"Invalid payment status: {payment.payment_status}"
                }, status=status.HTTP_200_OK)

            emi = EMISchedule.objects.select_for_update().get(id=payment.emi_schedule.id)
            
            # Revert the amount on EMI
            emi.amount_paid -= payment.payment_amount
            emi.update_status()
            emi.save()

            # Revert the amount on Invoice
            from .models import Invoice
            invoice = Invoice.objects.filter(emi_schedule=emi).first()
            if invoice:
                invoice.amount_paid -= payment.payment_amount
                invoice.balance = invoice.total_amount - invoice.amount_paid
                invoice.status = 'PENDING' if invoice.amount_paid == 0 else 'PARTIAL'
                invoice.save()

                # Revert Ledger Entries
                from .models import AccountingCode, LedgerEntry
                ar_code = AccountingCode.objects.filter(code="1200").first()
                if ar_code and payment.payment_received:
                    # Restored to AR
                    LedgerEntry.objects.create(
                        payment_received=payment.payment_received,
                        invoice=invoice,
                        accounting_code=ar_code,
                        type='DEBIT',
                        amount=payment.payment_amount,
                        description=f"AR restored due to Western Union reversal of payment {payment.payment_received.payment_number}",
                        entry_date=timezone.now()
                    )
                    # Reversal entry in Bank Account
                    LedgerEntry.objects.create(
                        payment_received=payment.payment_received,
                        invoice=invoice,
                        accounting_code=payment.payment_received.deposited_to,
                        type='CREDIT',
                        amount=payment.payment_amount,
                        description=f"Reversal of payment {payment.payment_received.payment_number} via Western Union.",
                        entry_date=timezone.now()
                    )

            # Update payment status
            payment.payment_status = "REVERSED"
            payment.save()

        return Response({
            "tipo_operacion": data.get("tipo_operacion"),
            "utility": data.get("utility"),
            "terminal": data.get("terminal"),
            "fecha": data.get("fecha"),
            "hora": data.get("hora"),
            "secuencia": data.get("secuencia"),
            "cod_trx": data.get("cod_trx"),
            "cod_operacion": data.get("cod_operacion"),
            "cod_severidad": "0",
            "cod_respuesta": "0",
            "msg_respuesta": "Reversa exitosa",
            "texto_ticket": "Reversal processed successfully"
        }, status=status.HTTP_200_OK)


# ====================================================================
# Get Complete Finance Details : Admin/Finance Manager/Global Manager
# =====================================================================
class FinanceCompleteDetailsAdminAPIView(APIView):
    """
    API to get COMPLETE Finance details including:
    Finance plan, Customer, EMI schedules, Device, Store, Region, Payment summary
    """
    permission_classes = [CanViewAdminFinanceDetails]

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

            # Base queryset
            queryset = FinancePlan.objects.select_related(
                "credit_application__customer",
                "device",
                "store",
                "store__region"
            ).prefetch_related(
                Prefetch("emi_schedule", queryset=EMISchedule.objects.order_by("due_date"))
            )

            # Apply filters
            if customer_id:
                queryset = queryset.filter(credit_application__customer_id=customer_id)
            if store_id:
                queryset = queryset.filter(store_id=store_id)
            if region_id:
                queryset = queryset.filter(store__region_id=region_id)
            if device_id:
                queryset = queryset.filter(device_id=device_id)
            if status_filter:
                queryset = queryset.filter(emi_schedule__status=status_filter.upper())
            if date_from:
                queryset = queryset.filter(emi_schedule__due_date__gte=date_from)
            if date_to:
                queryset = queryset.filter(emi_schedule__due_date__lte=date_to)

            queryset = queryset.distinct()

            # If ANY filter is applied — or even if not — always return detailed view
            paginated_qs = pagination.paginate_queryset(queryset, request)
            detailed_data = []

            for finance_plan in paginated_qs:
                cust_id = finance_plan.credit_application.customer.id
                customer_data = self.get_customer_finance_details(
                    cust_id,
                    status_filter=status_filter,
                    date_from=date_from,
                    date_to=date_to,
                    return_response=False 
                )
                detailed_data.append(customer_data)

            return pagination.get_paginated_response(detailed_data)

        except Exception as e:
            return Response(
                {"detail": f"Error fetching finance data: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ---------------------------------------------------------------
    # Full Finance details for one customer with EMI filters
    # ---------------------------------------------------------------
    def get_customer_finance_details(
    self,
    customer_id,
    status_filter=None,
    date_from=None,
    date_to=None,
    return_response=True,
    ):
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
            customer = finance_plan.credit_application.customer

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

            # Interest details
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

            # Customer details
            customer_details = {
                "id": customer.id,
                "name": f"{customer.first_name} {customer.last_name}",
                "phone": customer.phone_number,
                "email": customer.email,
                }

            # Build response
            serializer_data = {
                "customer": customer_details,
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
            if return_response:
                return Response(serializer.data, status=status.HTTP_200_OK)
            else:
                return serializer.data
        except Exception as e:
            error_msg = {"detail": f"Error fetching customer finance details: {str(e)}"}
            if return_response:
                return Response(error_msg, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                return error_msg 


# ====================================================================
# Get Complete Finance Details : Sales Advisor
# =====================================================================
class FinanceCompleteDetailsSalesAdvisorAPIView(FinanceCompleteDetailsAdminAPIView):
    """
    Finance details restricted to the Sales Advisor's region.
    Automatically injects region_id from authenticated user.
    """
    permission_classes = [CanViewSalesAdvisorFinance] 

    @swagger_auto_schema(
        operation_summary="Get Finance Details (Sales Advisor)",
        operation_description="""
        Returns full finance details automatically filtered based on the logged-in Sales Advisor's region.

        **Filters (optional):**
        - customer_id
        - store_id
        - device_id
        - status (PAID, PENDING, OVERDUE)
        - date_from (YYYY-MM-DD)
        - date_to (YYYY-MM-DD)
        """,
        manual_parameters=[
            openapi.Parameter('customer_id', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter('store_id', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter('device_id', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, required=False),
            openapi.Parameter('status', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter('date_from', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
            openapi.Parameter('date_to', openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False),
        ],
        tags=["Finance"]
    )
 
    def get(self, request):
        try:
            user = request.user
            user_store = user.store
            if not user_store:
                return Response(
                    {"detail": "Store not assigned to this user."},
                    status=403
                )
            request_region_id = user_store.region_id
            print(request_region_id)
            if not request_region_id:
                logger.warning(f"User {user.id} attempted access without region assigned.")
                return Response(
                    {"detail": "Region not assigned to this Sales Advisor."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Clone query params and add region_id
            mutable_params = request.query_params.copy()
            mutable_params["region_id"] = request_region_id
            print(mutable_params["region_id"])
            request._request.GET = mutable_params
            logger.info(
                f"Finance data requested by SalesAdvisor ID={user.id}, Region={request_region_id}"
            )

            # Call parent view
            response = super().get(request)

            # ---- Extract summary counts from final response ----
            data = response.data
            total_plans = len(data.get("finance_plans", [])) if isinstance(data, dict) else 0

            # Extract filters from request
            filters = {
                "customer_id": request.query_params.get("customer_id"),
                "store_id": request.query_params.get("store_id"),
                "device_id": request.query_params.get("device_id"),
                "status": request.query_params.get("status"),
                "date_from": request.query_params.get("date_from"),
                "date_to": request.query_params.get("date_to"),
                "region_id": str(request_region_id),
            }

            # --- Create Audit Log ---
            AuditLog.objects.create(
                user=user if user.is_authenticated else None,
                action_type="COMPLETE_FINANCE_VIEWED",
                description=(
                    f"Viewed {total_plans} finance records "
                    f"(Role=sales_advisor, Region={request_region_id})"
                ),
                metadata={
                    "filters": filters,
                    "total_records": total_plans,
                    "timestamp": str(timezone.now()),
                },
                ip_address=request.META.get("REMOTE_ADDR"),
            )

            return response

        except Exception as e:
            logger.error(
                f"Error in SalesAdvisorFinanceDetailsAPIView for user {request.user.id}: {str(e)}",
                exc_info=True
            )

            # Audit the error also
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action_type="FINANCE_VIEW_ERROR",
                description=f"Error occurred: {str(e)}",
                metadata={
                    "filters": dict(request.query_params),
                    "timestamp": str(timezone.now()),
                },
                ip_address=request.META.get("REMOTE_ADDR"),
            )

            return Response(
                {"detail": f"Failed to process request: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ====================================================================
# Get Complete Finance Details : Store Manager
# =====================================================================
class FinanceCompleteDetailsStoreManagerAPIView(FinanceCompleteDetailsAdminAPIView):
    """
    API for Store Manager to get COMPLETE Finance details for their own store(s).   
    """
    permission_classes = [CanViewStoreManagerFinance] 
    @swagger_auto_schema(
        operation_summary="Get complete Finance details (Store Manager)",
        operation_description="""
        Returns all finance details accessible to the Store Manager.
        - Can view only finance plans belonging to their store(s).
        - Supports same filters as admin: status, date range, etc.
        """,
        manual_parameters=[
            openapi.Parameter("store_id", openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                              description="Optional filter (must belong to this manager)"),
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
    # def get_base_queryset(self, request):
    #     user = request.user
    #     manager_stores = Store.objects.filter(store_manager=user)
    #     if not manager_stores.exists():
    #         return Response({"detail": "No stores assigned to this manager."}, status=403)

    #     return super().get_base_queryset(request).filter(store__in=manager_stores)
    
    def get_base_queryset(self, request):
        user = request.user
        try:
            manager_stores = Store.objects.filter(store_manager=user)
            if not manager_stores.exists():
                logger.warning(f"User {user.id} attempted access without assigned stores.")
                
                # --- Audit Log Entry ---
                AuditLog.objects.create(
                    user=user if user.is_authenticated else None,
                    action_type="STORE_ACCESS_DENIED",
                    description="Attempted to access finance data without assigned stores.",
                    metadata={
                        "filters": dict(request.query_params),
                        "timestamp": str(timezone.now()),
                    },
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
                
                return Response(
                    {"detail": "No stores assigned to this manager."},
                    status=status.HTTP_403_FORBIDDEN
                )

            base_qs = super().get_base_queryset(request)
            filtered_qs = base_qs.filter(store__in=manager_stores)

            logger.info(
                f"StoreManager ID={user.id} accessing {filtered_qs.count()} finance records "
                f"from {manager_stores.count()} assigned store(s)."
            )

            # --- Audit Log Entry ---
            AuditLog.objects.create(
                user=user if user.is_authenticated else None,
                action_type="STORE_FINANCE_VIEWED",
                description=f"Viewed finance records from {manager_stores.count()} store(s).",
                metadata={
                    "store_ids": list(manager_stores.values_list('id', flat=True)),
                    "filters": dict(request.query_params),
                    "total_records": filtered_qs.count(),
                    "timestamp": str(timezone.now()),
                },
                ip_address=request.META.get("REMOTE_ADDR"),
            )

            return filtered_qs

        except DatabaseError as e:
            logger.exception(f"Database error while fetching store finance data for user {user.id}: {e}")
            AuditLog.objects.create(
                user=user if user.is_authenticated else None,
                action_type="STORE_FINANCE_DB_ERROR",
                description=str(e),
                metadata={"timestamp": str(timezone.now())},
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return Response(
                {"detail": "Database error occurred while fetching finance data."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        except Exception as e:
            logger.exception(f"Unexpected error for StoreManager {user.id}: {e}")
            AuditLog.objects.create(
                user=user if user.is_authenticated else None,
                action_type="STORE_FINANCE_ERROR",
                description=str(e),
                metadata={"timestamp": str(timezone.now())},
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            return Response(
                {"detail": f"Unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )




# ================================================================================
#  YAPPY ONLINE PAYMENT VIEW
# ================================================================================


class YappyCreateOrderView(APIView):
    permission_classes=[]

    @swagger_auto_schema(
        tags=["yappy"],

        operation_summary="Create Yappy Payment Order",
        operation_description="""
                        Starts a Yappy payment by:

                        1. Validating merchant with Yappy  
                        2. Creating a payment order  
                        3. Returning token + transactionId + documentName to frontend  

                        Frontend must send the EMI ID of the installment the user wants to pay.
                        """,
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["emi_id"],
            properties={
                "emi_id": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="ID of the EMI installment to pay"
                )
            },
        ),
        responses={
            200: openapi.Response(
                description="Yappy order created successfully",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "status": openapi.Schema(type=openapi.TYPE_STRING),
                        "message": openapi.Schema(type=openapi.TYPE_STRING),
                        "data": openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "transactionId": openapi.Schema(type=openapi.TYPE_STRING),
                                "token": openapi.Schema(type=openapi.TYPE_STRING),
                                "documentName": openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        )
                    }
                )
            ),
            400: "Invalid input",
            500: "Yappy API error",
        }
    )
    def post(self, request):
        """ 
        1. call validate API
        2. call payment-wc API
        3. return transactionId, token, documentName 
        """

        # -----------------------------------------
        #  CALL YAPPY VALIDATE API
        # -----------------------------------------
        urlDomain=settings.urlDomain

        # url = "https://apipagosbg.bgeneral.cloud/payments/validate/merchant"
        url="http://127.0.0.1:8000/v2/finance/mock-yappy/payments/validate/merchant/"
        payload = {
            "merchantId": settings.YAPPY_MERCHANT_ID,
            "urlDomain": urlDomain
        }
        headers = {
            "Content-Type": "application/json"
        }
        try:
            yappy_response = requests.post(url, json=payload, headers=headers, timeout=10)
            yappy_response.raise_for_status()
            data = yappy_response.json()

        except requests.exceptions.Timeout:
            return Response({
                "status": "error",
                "message": "Yappy validate API timeout"
            }, status=504)  
        
        except requests.exceptions.HTTPError:
            return Response({
                "status": "error",
                "message": "Yappy validate API returned error",
                "yappy_response": yappy_response.text
            }, status=502)  
        
        except Exception as e:
            return Response({
                "status": "error",
                "message": "Unexpected error calling Yappy validate API",
                "error": str(e)
            }, status=500)
        
        # extract auth token
        auth_token = data["body"]["token"]

        # ----------------------------------------------------------
        #  CREATE ORDER (transactionId, token, documentName)
        # ----------------------------------------------------------

        # payment_url = "https://apipagosbg.bgeneral.cloud/payments/payment-wc"
        payment_url="http://127.0.0.1:8000//v2/finance/mock-yappy/payments/payment-wc/"

        try:
            emi_Schedule=EMISchedule.objects.get(id=request.data.get("emi_id"))
        except EMISchedule.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Invalid emi_id. EMI schedule not found."
            }, status=404)    
        
        oreder_id=emi_Schedule.id
        emi_amount = str(emi_Schedule.balance_remaining)

        try:
            customer_fullphone_number=emi_Schedule.finance_plan.credit_application.customer.phone_number
            customer_phone_number = customer_fullphone_number.replace("+507", "").replace(" ", "")
        except Exception:
            return Response({
                "status": "error",
                "message": "Customer phone number not found."
            }, status=400)
        
        # ipnUrl="http://127.0.0.1:8000//v2/finance/yappy/ipn/" 

        order_payload = {
            "merchantId": settings.YAPPY_MERCHANT_ID,
            "orderId": oreder_id,
            "domain": urlDomain,
            "paymentDate": int(time.time()),
            "aliasYappy": customer_phone_number,   
            "ipnUrl":settings.YAPPY_IPN_URL,
            "discount": "0.00",
            "taxes": "0.00",
            "subtotal": emi_amount,
            "total": emi_amount
        }
        order_headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json"
        }

        try:
            payment_response  = requests.post(
                payment_url, 
                json=order_payload, 
                headers=order_headers,
                timeout=10
                )
            payment_response.raise_for_status()
            order_res = payment_response.json()
        except requests.exceptions.Timeout:
            return Response({
                "status": "error",
                "message": "Yappy payment API timeout"
            }, status=504) 
        except requests.exceptions.HTTPError:
            return Response({
                "status": "error",
                "message": "Yappy payment API returned error",
                "yappy_response": payment_response.text
            }, status=502)   
        except Exception as e:
            return Response({
                "status": "error",
                "message": "Unexpected error calling Yappy payment API",
                "error": str(e)
            }, status=500)

        # extract values to send to frontend
        transactionId  = order_res["body"]["transactionId"]
        token          = order_res["body"]["token"]
        documentName   = order_res["body"]["documentName"]

        # return these 3 to frontend
        return Response({
            "status": "success",
            "message": "Yappy order created successfully.",
            "data": {
                "transactionId": transactionId,
                "token": token,
                "documentName": documentName
            }
        }, status=status.HTTP_200_OK)


# ================================================================================
#  YAPPY ONLINE PAYMENT IPN VIEW
# ================================================================================

class YappyIPNView(APIView):
    permission_classes=[]

    @swagger_auto_schema(
            tags=["yappy"],
        operation_summary="Yappy IPN Webhook",
        operation_description="""
            Yappy sends payment status to this endpoint.

            Yappy will send:
            - orderId: EMI installment ID  
            - status: E (Executed), R (Rejected), C (Cancelled), X (Expired)  
            - hash: Security hash to validate authenticity  
            - domain: Registered domain  

            Flow:
            1. Validate hash using Secret Key  
            2. Update EMI status in DB  
            3. Return success response
        """,
        manual_parameters=[
            openapi.Parameter(
                "orderId", openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Order/EMI ID sent by Yappy"
            ),
            openapi.Parameter(
                "status", openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Yappy payment status: E, R, C, X"
            ),
            openapi.Parameter(
                "hash", openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Hash from Yappy"
            ),
            openapi.Parameter(
                "domain", openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Domain registered for Yappy"
            ),
        ],
        responses={
            200: openapi.Response(
                description="IPN processed successfully",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        "message": openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            ),
            400: "Invalid hash",
            404: "EMI not found",
        }
    )
    def get(self, request):

        # ------------------------------------------
        # 1. Get data from Yappy
        # ------------------------------------------
        orderId = request.GET.get("orderId")
        status_value = request.GET.get("status")
        hash_received = request.GET.get("hash") 
        domain = request.GET.get("domain")
        # ------------------------------------------
        # 2. Decode secret key
        # ------------------------------------------
        decoded = base64.b64decode(settings.YAPPY_SECRET_KEY).decode("utf-8")
        secret_key = decoded.split(".")[0]
        # secret_key = settings.YAPPY_SECRET_KEY

        # ------------------------------------------
        # 3. Create expected hash
        # ------------------------------------------
        data = f"{orderId}{status_value}{domain}"
        expected_hash = hmac.new(
            secret_key.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()

        # ------------------------------------------
        # 4. Compare both hashes
        # ------------------------------------------
        if expected_hash != hash_received:
            return Response({"success": False, "message": "Invalid hash"}, status=400)
        # ------------------------------------------
        # 5. Hash valid → update EMI status
        # ------------------------------------------

        try:
            emi = EMISchedule.objects.get(id=orderId)
        except EMISchedule.DoesNotExist:
            return Response({"success": False, "message": "EMI not found"}, status=404)
        
        # Yappy status codes:
        # E = Executed (Paid)
        # R = Rejected
        # C = Cancelled
        # X = Expired

        today = timezone.now().date()
                
        if status_value == "E":
            emi.status = "PAID"
            emi.amount_paid = emi.installment_amount
            emi.balance_remaining = 0
            emi.paid_date = timezone.now().date()

            if today > emi.due_date:
                emi.days_overdue = (today - emi.due_date).days

        elif status_value in ["R", "C", "X"]:
            # Do NOTHING: EMI remains unpaid
            pass

        emi.save()

        PaymentRecord.objects.create(
            finance_plan = emi.finance_plan,
            emi_schedule = emi,
            payment_type = "EMI",
            payment_method = "YAPPY",
            payment_amount = emi.installment_amount,
            payment_date = timezone.now(),
            payment_status = "COMPLETED",
            transaction_reference = request.GET.get("transactionId", None),
            notes = f"Yappy payment for EMI #{emi.installment_number}",
            metadata = request.GET.dict()
        )

        return Response({"success": True})


# ========================================
# ACCOUNTING VIEWS (OLA CARS STYLE)
# ========================================

from .models import AccountingCode, Invoice, PaymentReceived, LedgerEntry, Tax, BankAccount, Vendor, Expense, Bill, PaymentMade, CreditNote, JournalEntry, LoanDisbursement, CustomerLoanLedgerEntry, MerchantSettlement, MerchantLedgerEntry
from .serializers import (
    AccountingCodeSerializer,
    InvoiceSerializer,
    PaymentReceivedSerializer,
    LedgerEntrySerializer,
    TaxSerializer,
    BankAccountSerializer,
    VendorSerializer,
    ExpenseSerializer,
    BillSerializer,
    PaymentMadeSerializer,
    CreditNoteSerializer,
    JournalEntrySerializer,
    LoanDisbursementSerializer,
    CustomerLoanLedgerEntrySerializer,
    MerchantSettlementSerializer,
    MerchantLedgerEntrySerializer
)
from .signals import seed_default_accounting_codes

class AccountingCodeListAPIView(APIView):
    """
    List all accounting codes. Seeds default codes if none exist.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        seed_default_accounting_codes()
        codes = AccountingCode.objects.all().order_by('code')
        serializer = AccountingCodeSerializer(codes, many=True)
        return Response(serializer.data)


class AccountingCodeCreateAPIView(APIView):
    """
    Create a new accounting code.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AccountingCodeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TaxListCreateAPIView(APIView):
    """
    List all taxes or create a new tax rate.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        taxes = Tax.objects.all().order_by('name')
        serializer = TaxSerializer(taxes, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = TaxSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BankAccountListCreateAPIView(APIView):
    """
    List all bank accounts or create a new bank account.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        accounts = BankAccount.objects.all().select_related('accounting_code').order_by('account_name')
        serializer = BankAccountSerializer(accounts, many=True)
        return Response(serializer.data)

    def post(self, request):
        data = request.data.copy()
        if 'initial_balance' in data and 'current_balance' not in data:
            data['current_balance'] = data['initial_balance']
        
        serializer = BankAccountSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BankAccountDetailAPIView(APIView):
    """
    Retrieve a single bank account.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            account = BankAccount.objects.select_related('accounting_code').get(pk=pk)
            serializer = BankAccountSerializer(account)
            return Response(serializer.data)
        except BankAccount.DoesNotExist:
            return Response({"error": "Bank account not found"}, status=status.HTTP_404_NOT_FOUND)


class InvoiceListAPIView(APIView):
    """
    List and filter all invoices, or create a new manual invoice.
    """
    permission_classes = [CanViewAdminFinanceDetails]

    def get(self, request):
        invoices = Invoice.objects.all().select_related('customer', 'finance_plan', 'emi_schedule')
        
        customer_id = request.query_params.get('customer_id')
        status_param = request.query_params.get('status')
        
        if customer_id:
            invoices = invoices.filter(customer_id=customer_id)

        finance_plan_id = request.query_params.get('finance_plan_id')
        if finance_plan_id:
            invoices = invoices.filter(finance_plan_id=finance_plan_id)
        if status_param:
            status_param = status_param.upper()
            today = timezone.now().date()
            if ',' in status_param:
                statuses = [s.strip() for s in status_param.split(',')]
                status_q = Q()
                for status_single in statuses:
                    if status_single == 'OVERDUE':
                        status_q |= Q(status='OVERDUE') | Q(status__in=['PENDING', 'PARTIAL'], due_date__lt=today)
                    elif status_single == 'PENDING':
                        status_q |= Q(status='PENDING', due_date__gte=today)
                    elif status_single == 'PARTIAL':
                        status_q |= Q(status='PARTIAL', due_date__gte=today)
                    else:
                        status_q |= Q(status=status_single)
                invoices = invoices.filter(status_q)
            else:
                if status_param == 'OVERDUE':
                    invoices = invoices.filter(
                        Q(status='OVERDUE') | 
                        Q(status__in=['PENDING', 'PARTIAL'], due_date__lt=today)
                    )
                elif status_param == 'PENDING':
                    invoices = invoices.filter(status='PENDING', due_date__gte=today)
                elif status_param == 'PARTIAL':
                    invoices = invoices.filter(status='PARTIAL', due_date__gte=today)
                else:
                    invoices = invoices.filter(status=status_param)

        # --------------------- Search Filter ---------------------
        search = request.query_params.get('search')
        if search:
            search_q = Q(invoice_number__icontains=search) | \
                       Q(customer__first_name__icontains=search) | \
                       Q(customer__last_name__icontains=search) | \
                       Q(customer__document_number__icontains=search) | \
                       Q(finance_plan__device__brand__name__icontains=search) | \
                       Q(finance_plan__device__model_name__icontains=search) | \
                       Q(status__icontains=search) | \
                       Q(notes__icontains=search) | \
                       Q(invoice_type__icontains=search)

            # Optional numeric search for total_amount, amount_paid, balance
            try:
                from decimal import Decimal, InvalidOperation
                decimal_val = Decimal(search)
                search_q |= Q(total_amount=decimal_val) | Q(amount_paid=decimal_val) | Q(balance=decimal_val)
            except (InvalidOperation, ValueError, TypeError):
                pass

            # Optional date search for due_date or created_at date part
            try:
                # support YYYY-MM-DD
                date_val = datetime.strptime(search, "%Y-%m-%d").date()
                search_q |= Q(due_date=date_val) | Q(created_at__date=date_val)
            except (ValueError, TypeError):
                pass

            invoices = invoices.filter(search_q).distinct()

        # --------------------- Sorting / Ordering ---------------------
        ordering = request.query_params.get('ordering', '-created_at')
        allowed_ordering = {
            'invoice_number': 'invoice_number',
            '-invoice_number': '-invoice_number',
            'customer_name': 'customer__first_name',
            '-customer_name': '-customer__first_name',
            'due_date': 'due_date',
            '-due_date': '-due_date',
            'created_at': 'created_at',
            '-created_at': '-created_at',
            'total_amount': 'total_amount',
            '-total_amount': '-total_amount',
            'amount_paid': 'amount_paid',
            '-amount_paid': '-amount_paid',
            'balance': 'balance',
            '-balance': '-balance',
            'status': 'status',
            '-status': '-status',
        }
        db_ordering = allowed_ordering.get(ordering, '-created_at')
        invoices = invoices.order_by(db_ordering)

        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(invoices, request, view=self)
        serializer = InvoiceSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        customer_id = data.get('customer_id')
        due_date_str = data.get('due_date')
        line_items_data = data.get('line_items', [])
        notes = data.get('notes', '')

        if not customer_id or not due_date_str or not line_items_data:
            return Response({"error": "Missing required fields: customer_id, due_date, and line_items"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        from datetime import datetime
        try:
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response({"error": "Invalid date format. Expected YYYY-MM-DD"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                customer = Customer.objects.get(id=customer_id)

                # Compute totals
                subtotal = Decimal('0.00')
                tax_amount = Decimal('0.00')
                processed_line_items = []

                for item in line_items_data:
                    name = item.get('name', 'Line Item')
                    qty = Decimal(str(item.get('qty', 1)))
                    unit_price = Decimal(str(item.get('unit_price', 0)))
                    sales_account_id = item.get('sales_account_id')
                    tax_rate_id = item.get('tax_rate_id')

                    line_subtotal = qty * unit_price
                    subtotal += line_subtotal

                    line_tax = Decimal('0.00')
                    tax_rate_val = Decimal('0.00')
                    if tax_rate_id:
                        tax_obj = Tax.objects.get(id=tax_rate_id)
                        tax_rate_val = tax_obj.rate
                        line_tax = line_subtotal * (tax_rate_val / Decimal('100.00'))
                        line_tax = line_tax.quantize(Decimal('0.01'))
                    tax_amount += line_tax

                    processed_line_items.append({
                        "name": name,
                        "qty": float(qty),
                        "unit_price": float(unit_price),
                        "sales_account_id": sales_account_id,
                        "tax_rate_id": tax_rate_id,
                        "tax_rate": float(tax_rate_val),
                        "tax_amount": float(line_tax),
                        "total": float(line_subtotal + line_tax)
                    })

                total_amount = subtotal + tax_amount

                # Generate unique sequential manual invoice number
                invoice_number = None
                while not invoice_number:
                    last_inv = Invoice.objects.filter(invoice_number__startswith='OLA-MAN-').order_by('-id').first()
                    if last_inv:
                        try:
                            last_num = int(last_inv.invoice_number.split('-')[-1])
                            next_num = last_num + 1
                        except (ValueError, IndexError):
                            next_num = 1
                    else:
                        next_num = 1
                    candidate = f"OLA-MAN-{next_num:06d}"
                    if not Invoice.objects.filter(invoice_number=candidate).exists():
                        invoice_number = candidate

                invoice = Invoice.objects.create(
                    invoice_number=invoice_number,
                    customer=customer,
                    due_date=due_date,
                    base_amount=subtotal,
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    total_amount=total_amount,
                    balance=total_amount,
                    amount_paid=Decimal('0.00'),
                    status='PENDING',
                    invoice_type='MANUAL',
                    line_items=processed_line_items,
                    notes=notes
                )

                # Generate ledger entries
                invoice.generate_ledger_entries()

                # Audit log
                AuditLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    customer=customer,
                    action_type='CREATE_PAYMENT',
                    description=f"Manually created invoice {invoice_number} of total {total_amount} for customer {customer.first_name} {customer.last_name}"
                )

                return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)
        except Tax.DoesNotExist:
            return Response({"error": "Tax rate not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class InvoiceDetailAPIView(APIView):
    """
    Retrieve a single invoice's details.
    """
    permission_classes = [CanViewAdminFinanceDetails]

    def get(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk)
        serializer = InvoiceSerializer(invoice)
        return Response(serializer.data)


class PaymentReceivedListCreateAPIView(APIView):
    """
    List all payments received or record a new payment against invoices.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        payments = PaymentReceived.objects.all().select_related('customer', 'deposited_to').order_by('-payment_date')
        customer_id = request.query_params.get('customer_id')
        if customer_id:
            payments = payments.filter(customer_id=customer_id)
        
        finance_plan_id = request.query_params.get('finance_plan_id')
        if finance_plan_id:
            try:
                fp_id = int(finance_plan_id)
                from .models import Invoice
                inv_ids = set(Invoice.objects.filter(finance_plan_id=fp_id).values_list('id', flat=True))
                payment_ids = []
                for p in payments:
                    p_invs = p.invoices or []
                    if any(isinstance(item, dict) and item.get('invoice_id') in inv_ids for item in p_invs):
                        payment_ids.append(p.id)
                payments = payments.filter(id__in=payment_ids)
            except ValueError:
                pass
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(payments, request, view=self)
        serializer = PaymentReceivedSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        customer_id = data.get('customer_id')
        amount_received = Decimal(str(data.get('amount_received', 0)))
        payment_method = data.get('payment_method', 'CASH')
        transaction_reference = data.get('transaction_reference')
        deposited_to_id = data.get('deposited_to')
        invoices_data = data.get('invoices', [])
        notes = data.get('notes')

        if not customer_id or amount_received <= 0 or not deposited_to_id:
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                customer = Customer.objects.get(id=customer_id)
                deposited_to = AccountingCode.objects.get(id=deposited_to_id)

                # Generate payment number PR-YYYYMMDD-XXXX
                import random
                date_str = timezone.now().strftime("%Y%m%d")
                rand_str = str(random.randint(1000, 9999))
                payment_number = f"PR-{date_str}-{rand_str}"

                payment = PaymentReceived.objects.create(
                    payment_number=payment_number,
                    customer=customer,
                    amount_received=amount_received,
                    payment_date=timezone.now(),
                    payment_method=payment_method,
                    transaction_reference=transaction_reference,
                    deposited_to=deposited_to,
                    invoices=invoices_data,
                    notes=notes
                )

                # Process invoice balance updates, EMI schedule integration, and ledger postings
                payment.process_payment(user=request.user if request.user.is_authenticated else None)

                # Create Audit Log
                AuditLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    customer=customer,
                    action_type='PAYMENT_RECEIVED',
                    description=f"Recorded PaymentReceived {payment_number} of {amount_received} from customer {customer.first_name} {customer.last_name}",
                    metadata={
                        "payment_number": payment_number,
                        "amount_received": str(amount_received),
                        "payment_method": payment_method,
                        "transaction_reference": transaction_reference
                    }
                )

                return Response({
                    "status": "success",
                    "message": "Payment received and processed successfully",
                    "payment_number": payment_number
                }, status=status.HTTP_201_CREATED)

        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)
        except AccountingCode.DoesNotExist:
            return Response({"error": "Accounting code not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class LedgerEntryListAPIView(APIView):
    """
    List all general ledger entries.
    """
    permission_classes = [CanViewAdminFinanceDetails]

    def get(self, request):
        entries = LedgerEntry.objects.all().select_related('invoice', 'payment_received', 'accounting_code', 'bill', 'expense', 'payment_made', 'credit_note').order_by('-entry_date', '-id')
        bill_id = request.query_params.get('bill_id')
        invoice_id = request.query_params.get('invoice_id')
        expense_id = request.query_params.get('expense_id')
        payment_received_id = request.query_params.get('payment_received_id')
        payment_made_id = request.query_params.get('payment_made_id')
        credit_note_id = request.query_params.get('credit_note_id')
        vendor_id = request.query_params.get('vendor_id')
        customer_id = request.query_params.get('customer_id')
        accounting_code_id = request.query_params.get('accounting_code_id')

        if bill_id:
            entries = entries.filter(bill_id=bill_id)
        if invoice_id:
            entries = entries.filter(invoice_id=invoice_id)
        if expense_id:
            entries = entries.filter(expense_id=expense_id)
        if payment_received_id:
            entries = entries.filter(payment_received_id=payment_received_id)
        if payment_made_id:
            entries = entries.filter(payment_made_id=payment_made_id)
        if credit_note_id:
            entries = entries.filter(credit_note_id=credit_note_id)
        if vendor_id:
            from django.db.models import Q
            entries = entries.filter(Q(bill__vendor_id=vendor_id) | Q(payment_made__vendor_id=vendor_id))
        if customer_id:
            from django.db.models import Q
            entries = entries.filter(Q(invoice__customer_id=customer_id) | Q(payment_received__customer_id=customer_id))
        if accounting_code_id:
            entries = entries.filter(accounting_code_id=accounting_code_id)
            
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(entries, request, view=self)
        serializer = LedgerEntrySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class PaymentReceivedDetailAPIView(APIView):
    """
    Retrieve a single payment received.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            payment = PaymentReceived.objects.select_related('customer', 'deposited_to').get(pk=pk)
            serializer = PaymentReceivedSerializer(payment)
            return Response(serializer.data)
        except PaymentReceived.DoesNotExist:
            return Response({"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)


class ExpenseDetailAPIView(APIView):
    """
    Retrieve a single manual expense.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            expense = Expense.objects.select_related('paid_from', 'expense_category').get(pk=pk)
            serializer = ExpenseSerializer(expense)
            return Response(serializer.data)
        except Expense.DoesNotExist:
            return Response({"error": "Expense not found"}, status=status.HTTP_404_NOT_FOUND)


class VendorDetailAPIView(APIView):
    """
    Retrieve a single vendor.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            vendor = Vendor.objects.get(pk=pk)
            serializer = VendorSerializer(vendor)
            return Response(serializer.data)
        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)



class VendorListCreateAPIView(APIView):
    """
    List all vendors or create a new vendor.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        vendors = Vendor.objects.all().order_by('name')
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(vendors, request, view=self)
        serializer = VendorSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = VendorSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ExpenseListCreateAPIView(APIView):
    """
    List all expenses or create a new expense.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        expenses = Expense.objects.all().select_related('paid_from', 'expense_category').order_by('-payment_date', '-id')
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(expenses, request, view=self)
        serializer = ExpenseSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        payment_date = data.get('payment_date')
        amount = Decimal(str(data.get('amount', 0)))
        payment_method = data.get('payment_method', 'CASH')
        paid_from_id = data.get('paid_from')
        expense_category_id = data.get('expense_category')
        notes = data.get('notes', '')

        if not payment_date or amount <= 0 or not paid_from_id or not expense_category_id:
            return Response({"error": "Missing required fields: payment_date, amount, paid_from, and expense_category"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                paid_from = AccountingCode.objects.get(id=paid_from_id)
                expense_category = AccountingCode.objects.get(id=expense_category_id)

                # Generate unique expense number EXP-YYYYMMDD-XXXX
                import random
                expense_number = None
                while not expense_number:
                    date_str = timezone.now().strftime("%Y%m%d")
                    rand_str = str(random.randint(1000, 9999))
                    candidate = f"EXP-{date_str}-{rand_str}"
                    if not Expense.objects.filter(expense_number=candidate).exists():
                        expense_number = candidate

                expense = Expense.objects.create(
                    expense_number=expense_number,
                    payment_date=payment_date,
                    amount=amount,
                    payment_method=payment_method,
                    paid_from=paid_from,
                    expense_category=expense_category,
                    notes=notes
                )

                # Generate ledger entries
                expense.generate_ledger_entries()

                return Response(ExpenseSerializer(expense).data, status=status.HTTP_201_CREATED)

        except AccountingCode.DoesNotExist:
            return Response({"error": "GL Account not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class BillListCreateAPIView(APIView):
    """
    List all vendor bills or create a new purchase bill.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        bills = Bill.objects.all().select_related('vendor').order_by('-due_date')
        
        vendor_id = request.query_params.get('vendor_id')
        status_param = request.query_params.get('status')
        
        if vendor_id:
            bills = bills.filter(vendor_id=vendor_id)
            
        if status_param:
            status_param = status_param.upper()
            if ',' in status_param:
                statuses = [s.strip() for s in status_param.split(',')]
                bills = bills.filter(status__in=statuses)
            else:
                bills = bills.filter(status=status_param)

        search = request.query_params.get('search')
        if search:
            from django.db.models import Q
            bills = bills.filter(
                Q(bill_number__icontains=search) |
                Q(vendor__name__icontains=search) |
                Q(notes__icontains=search)
            ).distinct()

        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(bills, request, view=self)
        serializer = BillSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        vendor_id = data.get('vendor_id')
        bill_date = data.get('bill_date')
        due_date = data.get('due_date')
        line_items_data = data.get('line_items', [])
        notes = data.get('notes', '')

        if not vendor_id or not bill_date or not due_date or not line_items_data:
            return Response({"error": "Missing required fields: vendor_id, bill_date, due_date, and line_items"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                vendor = Vendor.objects.get(id=vendor_id)

                # Compute subtotal, tax and total
                subtotal = Decimal('0.00')
                tax_amount = Decimal('0.00')
                processed_line_items = []

                for item in line_items_data:
                    name = item.get('name', 'Line Item')
                    qty = Decimal(str(item.get('qty', 1)))
                    unit_price = Decimal(str(item.get('unit_price', 0)))
                    expense_account_id = item.get('expense_account_id')
                    tax_rate_id = item.get('tax_rate_id')

                    line_subtotal = qty * unit_price
                    subtotal += line_subtotal

                    line_tax = Decimal('0.00')
                    tax_rate_val = Decimal('0.00')
                    if tax_rate_id:
                        tax_obj = Tax.objects.get(id=tax_rate_id)
                        tax_rate_val = tax_obj.rate
                        line_tax = line_subtotal * (tax_rate_val / Decimal('100.00'))
                        line_tax = line_tax.quantize(Decimal('0.01'))
                    tax_amount += line_tax

                    processed_line_items.append({
                        "name": name,
                        "qty": float(qty),
                        "unit_price": float(unit_price),
                        "expense_account_id": expense_account_id,
                        "tax_rate_id": tax_rate_id,
                        "tax_rate": float(tax_rate_val),
                        "tax_amount": float(line_tax),
                        "total": float(line_subtotal + line_tax)
                    })

                total_amount = subtotal + tax_amount

                # Generate unique bill number
                import random
                bill_number = None
                while not bill_number:
                    date_str = timezone.now().strftime("%Y%m%d")
                    rand_str = str(random.randint(1000, 9999))
                    candidate = f"BILL-{date_str}-{rand_str}"
                    if not Bill.objects.filter(bill_number=candidate).exists():
                        bill_number = candidate

                bill = Bill.objects.create(
                    bill_number=bill_number,
                    vendor=vendor,
                    bill_date=bill_date,
                    due_date=due_date,
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    total_amount=total_amount,
                    balance=total_amount,
                    amount_paid=Decimal('0.00'),
                    status='PENDING',
                    line_items=processed_line_items,
                    notes=notes
                )

                # Generate ledger entries
                bill.generate_ledger_entries()

                return Response(BillSerializer(bill).data, status=status.HTTP_201_CREATED)

        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)
        except Tax.DoesNotExist:
            return Response({"error": "Tax rate not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class BillDetailAPIView(APIView):
    """
    Retrieve a single bill's details.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        bill = get_object_or_404(Bill, pk=pk)
        serializer = BillSerializer(bill)
        return Response(serializer.data)


class PaymentMadeListCreateAPIView(APIView):
    """
    List all payments made to vendors or record a new bill payment.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        payments = PaymentMade.objects.all().select_related('vendor', 'paid_from').order_by('-payment_date', '-id')
        vendor_id = request.query_params.get('vendor_id')
        if vendor_id:
            payments = payments.filter(vendor_id=vendor_id)
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(payments, request, view=self)
        serializer = PaymentMadeSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        vendor_id = data.get('vendor_id')
        amount_paid = Decimal(str(data.get('amount_paid', 0)))
        payment_date = data.get('payment_date')
        payment_method = data.get('payment_method', 'CASH')
        paid_from_id = data.get('paid_from')
        bills_data = data.get('bills', [])
        notes = data.get('notes', '')

        if not vendor_id or amount_paid <= 0 or not payment_date or not paid_from_id:
            return Response({"error": "Missing required fields: vendor_id, amount_paid, payment_date, and paid_from"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                vendor = Vendor.objects.get(id=vendor_id)
                paid_from = AccountingCode.objects.get(id=paid_from_id)

                # Generate payment number VPM-YYYYMMDD-XXXX
                import random
                date_str = timezone.now().strftime("%Y%m%d")
                rand_str = str(random.randint(1000, 9999))
                payment_number = f"VPM-{date_str}-{rand_str}"

                payment = PaymentMade.objects.create(
                    payment_number=payment_number,
                    vendor=vendor,
                    amount_paid=amount_paid,
                    payment_date=payment_date,
                    payment_method=payment_method,
                    paid_from=paid_from,
                    bills=bills_data,
                    notes=notes
                )

                # Process applied bills and generate ledger entries
                payment.process_payment()

                return Response(PaymentMadeSerializer(payment).data, status=status.HTTP_201_CREATED)

        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=status.HTTP_404_NOT_FOUND)
        except AccountingCode.DoesNotExist:
            return Response({"error": "GL Account not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PaymentMadeDetailAPIView(APIView):
    """
    Retrieve a single payment made to a vendor.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            payment = PaymentMade.objects.select_related('vendor', 'paid_from').get(pk=pk)
            serializer = PaymentMadeSerializer(payment)
            return Response(serializer.data)
        except PaymentMade.DoesNotExist:
            return Response({"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)


class CreditNoteListCreateAPIView(APIView):
    """
    List all credit notes or create a new credit note.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        credit_notes = CreditNote.objects.all().select_related('customer').order_by('-date', '-id')
        customer_id = request.query_params.get('customer_id')
        if customer_id:
            credit_notes = credit_notes.filter(customer_id=customer_id)
        invoice_id = request.query_params.get('invoice_id')
        if invoice_id:
            credit_notes = credit_notes.filter(invoice_id=invoice_id)
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(credit_notes, request, view=self)
        serializer = CreditNoteSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        customer_id = data.get('customer_id')
        date = data.get('date')
        amount = Decimal(str(data.get('amount', 0)))
        notes = data.get('notes', '')
        accounts_receivable_account_id = data.get('accounts_receivable_account_id') or data.get('accounts_receivable_account')
        debit_account_id = data.get('debit_account_id') or data.get('debit_account')

        if not customer_id or not date or amount <= 0:
            return Response({"error": "Missing required fields: customer_id, date, and amount"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                customer = Customer.objects.get(id=customer_id)

                # Generate unique credit note number CN-YYYYMMDD-XXXX
                import random
                credit_note_number = None
                while not credit_note_number:
                    date_str = timezone.now().strftime("%Y%m%d")
                    rand_str = str(random.randint(1000, 9999))
                    candidate = f"CN-{date_str}-{rand_str}"
                    if not CreditNote.objects.filter(credit_note_number=candidate).exists():
                        credit_note_number = candidate

                credit_note = CreditNote.objects.create(
                    credit_note_number=credit_note_number,
                    customer=customer,
                    date=date,
                    amount=amount,
                    status='UNAPPLIED',
                    notes=notes,
                    accounts_receivable_account_id=accounts_receivable_account_id,
                    debit_account_id=debit_account_id
                )

                # Generate ledger entries
                credit_note.generate_ledger_entries()

                return Response(CreditNoteSerializer(credit_note).data, status=status.HTTP_201_CREATED)

        except Customer.DoesNotExist:
            return Response({"error": "Customer not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CreditNoteDetailAPIView(APIView):
    """
    Retrieve details of a single credit note.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            credit_note = CreditNote.objects.select_related('customer', 'invoice').get(pk=pk)
            serializer = CreditNoteSerializer(credit_note)
            return Response(serializer.data)
        except CreditNote.DoesNotExist:
            return Response({"error": "Credit note not found"}, status=status.HTTP_404_NOT_FOUND)


class CreditNoteApplyAPIView(APIView):
    """
    Apply a credit note to an invoice.
    """
    permission_classes = [AllowAny]

    def post(self, request, pk):
        invoice_id = request.data.get('invoice_id')
        if not invoice_id:
            return Response({"error": "invoice_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                credit_note = CreditNote.objects.select_related('customer').get(pk=pk)
                if credit_note.status != 'UNAPPLIED':
                    return Response({"error": f"Credit note status is {credit_note.status}, only UNAPPLIED credit notes can be applied"}, 
                                    status=status.HTTP_400_BAD_REQUEST)

                invoice = Invoice.objects.get(pk=invoice_id)
                if invoice.customer_id != credit_note.customer_id:
                    return Response({"error": "Invoice customer does not match credit note customer"}, 
                                    status=status.HTTP_400_BAD_REQUEST)

                if invoice.balance <= 0:
                    return Response({"error": "Invoice is already fully paid"}, 
                                    status=status.HTTP_400_BAD_REQUEST)

                # Determine the amount to apply: minimum of credit note amount and invoice balance
                apply_amount = min(credit_note.amount, invoice.balance)

                # Deduct from invoice balance, add to amount_paid
                invoice.amount_paid += apply_amount
                invoice.balance = invoice.total_amount - invoice.amount_paid

                if invoice.balance <= 0:
                    invoice.status = 'PAID'
                    invoice.balance = 0
                else:
                    invoice.status = 'PARTIAL'

                invoice.save()

                # Mark credit note as applied and associate with invoice
                credit_note.status = 'APPLIED'
                credit_note.invoice = invoice
                credit_note.save()

                # Update descriptions and associate credit note ledger entries with the invoice
                for entry in LedgerEntry.objects.filter(credit_note=credit_note):
                    entry.invoice = invoice
                    if entry.accounting_code.code == "1200":
                        entry.description = f"EMI Receivable reduction for plan invoice {invoice.invoice_number} via credit note {credit_note.credit_note_number}"
                    entry.save()

                return Response({
                    "message": "Credit note successfully applied to invoice",
                    "credit_note": CreditNoteSerializer(credit_note).data,
                    "applied_amount": str(apply_amount)
                })

        except CreditNote.DoesNotExist:
            return Response({"error": "Credit note not found"}, status=status.HTTP_404_NOT_FOUND)
        except Invoice.DoesNotExist:
            return Response({"error": "Invoice not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class JournalEntryListCreateAPIView(APIView):
    """
    List all manual journal entries or post a new double-entry journal.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        journal_entries = JournalEntry.objects.all().order_by('-entry_date', '-id')
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(journal_entries, request, view=self)
        serializer = JournalEntrySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        data = request.data
        entry_date = data.get('entry_date')
        description = data.get('description', '')
        lines = data.get('lines', [])

        if not entry_date or not lines:
            return Response({"error": "Missing required fields: entry_date and lines"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        # Validate debits match credits
        total_debit = Decimal('0.00')
        total_credit = Decimal('0.00')
        for line in lines:
            amt = Decimal(str(line.get('amount', 0)))
            if line.get('type') == 'DEBIT':
                total_debit += amt
            elif line.get('type') == 'CREDIT':
                total_credit += amt

        if total_debit != total_credit:
            return Response({"error": f"Unbalanced Journal Entry: Debits (${total_debit}) must equal Credits (${total_credit})"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        if total_debit <= 0:
            return Response({"error": "Journal Entry amount must be greater than zero"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                # Generate unique reference number JR-YYYYMMDD-XXXX
                import random
                reference_number = None
                while not reference_number:
                    date_str = timezone.now().strftime("%Y%m%d")
                    rand_str = str(random.randint(1000, 9999))
                    candidate = f"JR-{date_str}-{rand_str}"
                    if not JournalEntry.objects.filter(reference_number=candidate).exists():
                        reference_number = candidate

                journal = JournalEntry.objects.create(
                    reference_number=reference_number,
                    entry_date=entry_date,
                    description=description
                )

                import datetime
                dt = timezone.make_aware(datetime.datetime.combine(timezone.datetime.strptime(entry_date, '%Y-%m-%d').date(), datetime.time.min))

                # Create Ledger Entries
                for line in lines:
                    code_id = line.get('accounting_code_id')
                    code = AccountingCode.objects.get(id=code_id)
                    amt = Decimal(str(line.get('amount', 0)))
                    l_type = line.get('type')

                    LedgerEntry.objects.create(
                        journal_entry=journal,
                        accounting_code=code,
                        type=l_type,
                        amount=amt,
                        description=description or f"Manual journal adjustment {reference_number}",
                        entry_date=dt
                    )

                return Response(JournalEntrySerializer(journal).data, status=status.HTTP_201_CREATED)

        except AccountingCode.DoesNotExist:
            return Response({"error": "GL Account not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FinanceConfigAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        from .models import RiskTier, LoanTerm, EMIConfiguration, EmployerRule, DecisionRule, InterestPlan
        
        risk_tiers = list(RiskTier.objects.filter(is_active=True).values())
        loan_terms = list(LoanTerm.objects.filter(is_active=True).values())
        emi_config = list(EMIConfiguration.objects.filter(is_active=True).values())
        employer_rules = list(EmployerRule.objects.filter(is_active=True).values())
        decision_rules = list(DecisionRule.objects.filter(is_active=True).values())
        
        # Add interest plans details for each loan term
        for term in loan_terms:
            plans = list(InterestPlan.objects.filter(loan_term_id=term['id'], is_active=True).values())
            term['interest_plans'] = plans
            
        return Response({
            "status": "success",
            "data": {
                "risk_tiers": risk_tiers,
                "loan_terms": loan_terms,
                "emi_config": emi_config,
                "employer_rules": employer_rules,
                "decision_rules": decision_rules
            }
        })

    def put(self, request):
        from .models import EMIConfiguration, BankAccount
        from decimal import Decimal
        
        config = EMIConfiguration.objects.filter(is_active=True).first()
        if not config:
            config = EMIConfiguration.objects.create(is_active=True)
            
        if "punto_pago_bank_account_id" in request.data:
            punto_pago_bank_account_id = request.data.get("punto_pago_bank_account_id")
            if punto_pago_bank_account_id:
                try:
                    bank_acc = BankAccount.objects.get(id=int(punto_pago_bank_account_id))
                    config.punto_pago_bank_account = bank_acc
                except (BankAccount.DoesNotExist, ValueError, TypeError):
                    return Response({
                        "status": "error",
                        "message": f"Bank account with ID {punto_pago_bank_account_id} not found for Punto Pago."
                    }, status=status.HTTP_404_NOT_FOUND)
            else:
                config.punto_pago_bank_account = None

        if "western_union_bank_account_id" in request.data:
            western_union_bank_account_id = request.data.get("western_union_bank_account_id")
            if western_union_bank_account_id:
                try:
                    bank_acc = BankAccount.objects.get(id=int(western_union_bank_account_id))
                    config.western_union_bank_account = bank_acc
                except (BankAccount.DoesNotExist, ValueError, TypeError):
                    return Response({
                        "status": "error",
                        "message": f"Bank account with ID {western_union_bank_account_id} not found for Western Union."
                    }, status=status.HTTP_404_NOT_FOUND)
            else:
                config.western_union_bank_account = None
            
        if "processing_fee_default" in request.data:
            config.processing_fee_default = Decimal(str(request.data["processing_fee_default"]))
        if "insurance_fee_default" in request.data:
            config.insurance_fee_default = Decimal(str(request.data["insurance_fee_default"]))
        if "tax_rate_pct" in request.data:
            config.tax_rate_pct = Decimal(str(request.data["tax_rate_pct"]))
            
        config.save()
        return Response({
            "status": "success",
            "message": "Configuration updated successfully."
        })


class FinanceGeneratePlansAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        principal = request.data.get("principal")
        risk_tier = request.data.get("risk_tier", "TIER_A")
        
        if principal is None:
            return Response({
                "status": "error",
                "message": "principal is required."
            }, status=status.HTTP_400_BAD_REQUEST)
            
        from .services import FinancingEngineService
        plans = FinancingEngineService.generate_emi_plans(Decimal(str(principal)), risk_tier)
        return Response({
            "status": "success",
            "data": plans
        })


class FinanceContractsAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        plan_id = request.query_params.get("plan_id")
        if not plan_id:
            return Response({"status": "error", "message": "plan_id query param is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        from .models import FinancePlan
        plan = FinancePlan.objects.filter(id=plan_id).first()
        if not plan:
            plan = get_transient_plan_from_application(plan_id)
            
        if not plan:
            return Response({"status": "error", "message": "Finance Plan not found"}, status=status.HTTP_404_NOT_FOUND)
            
        from .services import ContractService
        loan_agreement = ContractService.generate_loan_agreement(plan)
        payment_schedule = ContractService.generate_payment_schedule_text(plan)
        downpayment_receipt = ContractService.generate_downpayment_receipt(plan)
        delivery_form = ContractService.generate_delivery_form(plan)
        
        from .serializers import EMIScheduleSerializer
        schedules = plan.emi_schedule.all().order_by('installment_number')
        if not schedules.exists():
            import datetime
            from django.utils import timezone
            from .models import EMISchedule
            frequency_days = plan.installment_frequency_days or 30
            first_due_date = timezone.now().date() + datetime.timedelta(days=frequency_days)
            schedules_list = EMISchedule.generate_schedule(plan, first_due_date, save=False)
            schedule_data = EMIScheduleSerializer(schedules_list, many=True).data
        else:
            schedule_data = EMIScheduleSerializer(schedules, many=True).data
            
        return Response({
            "status": "success",
            "data": {
                "loan_agreement": loan_agreement,
                "payment_schedule": payment_schedule,
                "downpayment_receipt": downpayment_receipt,
                "delivery_form": delivery_form,
                "emi_schedule": schedule_data
            }
        })


class FinanceContractsPDFView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        plan_id = request.query_params.get("plan_id")
        if not plan_id:
            return Response({"status": "error", "message": "plan_id query param is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        from .models import FinancePlan
        plan = FinancePlan.objects.filter(id=plan_id).first()
        if not plan:
            return Response({"status": "error", "message": "Finance Plan not found"}, status=status.HTTP_404_NOT_FOUND)
            
        from .services import ContractService
        try:
            agreement_text = ContractService.generate_loan_agreement(plan)
            pdf_data = ContractService.generate_pdf_from_text(agreement_text)
            
            from django.http import HttpResponse
            response = HttpResponse(pdf_data, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="loan_agreement_{plan.id}.pdf"'
            return response
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LoanDisbursementAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        
        finance_plan_id = request.query_params.get("finance_plan_id")
        qs = LoanDisbursement.objects.all().select_related('finance_plan__credit_application__customer', 'finance_plan__store')
        if finance_plan_id:
            qs = qs.filter(finance_plan_id=finance_plan_id)
        
        serializer = LoanDisbursementSerializer(qs, many=True)
        return Response({"status": "success", "data": serializer.data})

    def post(self, request):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        
        plan_id = request.data.get("finance_plan_id")
        amount = request.data.get("amount")
        description = request.data.get("description")

        if not plan_id or not amount:
            return Response({"status": "error", "message": "finance_plan_id and amount are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from finance.accounting_services import AccountingEngineService
            disb = AccountingEngineService.disburse_loan(plan_id, amount, description)
            return Response({
                "status": "success", 
                "message": "Loan disbursed successfully.",
                "data": LoanDisbursementSerializer(disb).data
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class LoanDisbursementReverseAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, pk):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        try:
            from finance.accounting_services import AccountingEngineService
            disb = AccountingEngineService.reverse_disbursement(pk)
            return Response({
                "status": "success",
                "message": "Disbursement reversed successfully.",
                "data": LoanDisbursementSerializer(disb).data
            })
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MerchantSettlementAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        if request.user.role not in ["admin", "global_manager", "financial_manager", "store_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        store_id = request.query_params.get("store_id")
        status_filter = request.query_params.get("status")
        
        qs = MerchantSettlement.objects.all().select_related('store', 'finance_plan__credit_application__customer', 'bank_account')
        
        if request.user.role == 'store_manager':
            if request.user.store:
                qs = qs.filter(store=request.user.store)
            else:
                qs = qs.none()
        else:
            if store_id:
                qs = qs.filter(store_id=store_id)
                
        if status_filter:
            qs = qs.filter(status=status_filter)

        serializer = MerchantSettlementSerializer(qs, many=True)
        return Response({"status": "success", "data": serializer.data})


class MerchantSettlementPayAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, pk):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        bank_account_id = request.data.get("bank_account_id")
        payment_reference = request.data.get("payment_reference")
        date_str = request.data.get("date")

        if not bank_account_id or not payment_reference:
            return Response({"status": "error", "message": "bank_account_id and payment_reference are required."}, status=status.HTTP_400_BAD_REQUEST)

        date_val = None
        if date_str:
            try:
                import datetime
                date_val = timezone.make_aware(datetime.datetime.strptime(date_str, "%Y-%m-%d"))
            except ValueError:
                pass

        try:
            from finance.accounting_services import AccountingEngineService
            settlement = AccountingEngineService.settle_merchant(pk, bank_account_id, payment_reference, date_val)
            return Response({
                "status": "success",
                "message": "Merchant settlement payment processed.",
                "data": MerchantSettlementSerializer(settlement).data
            })
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MerchantSettlementCancelAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, pk):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        try:
            from finance.accounting_services import AccountingEngineService
            settlement = AccountingEngineService.cancel_settlement(pk)
            return Response({
                "status": "success",
                "message": "Settlement cancelled successfully.",
                "data": MerchantSettlementSerializer(settlement).data
            })
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MerchantLedgerAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, store_id):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        from store.models import Store
        store = Store.objects.filter(id=store_id).first()
        if not store:
            return Response({"status": "error", "message": "Store not found."}, status=status.HTTP_404_NOT_FOUND)

        ledger_entries = MerchantLedgerEntry.objects.filter(store=store).select_related('finance_plan__credit_application__customer').order_by('-entry_date', '-id')
        last_entry = ledger_entries.first()
        outstanding_balance = last_entry.outstanding_balance if last_entry else Decimal('0.00')

        return Response({
            "status": "success",
            "data": {
                "store": {
                    "id": store.id,
                    "name": store.name,
                    "code": store.code,
                    "outstanding_balance": str(outstanding_balance)
                },
                "entries": MerchantLedgerEntrySerializer(ledger_entries, many=True).data
            }
        })


class CustomerLoanLedgerAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request, plan_id):
        if request.user.role not in ["admin", "global_manager", "financial_manager", "salesperson", "store_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        from .models import FinancePlan
        plan = FinancePlan.objects.filter(id=plan_id).first()
        if not plan:
            return Response({"status": "error", "message": "Finance Plan not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role in ["salesperson", "store_manager"]:
            if plan.store != request.user.store:
                return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        ledger_entries = CustomerLoanLedgerEntry.objects.filter(finance_plan=plan).order_by('-entry_date', '-id')
        last_entry = ledger_entries.first()
        
        balances = {
            "outstanding_principal": str(last_entry.outstanding_principal) if last_entry else "0.00",
            "outstanding_interest": str(last_entry.outstanding_interest) if last_entry else "0.00",
            "outstanding_penalties": str(last_entry.outstanding_penalties) if last_entry else "0.00",
            "outstanding_balance": str(last_entry.outstanding_balance) if last_entry else "0.00",
        }

        disbursed_total = sum(d.amount for d in LoanDisbursement.objects.filter(finance_plan=plan, status='COMPLETED'))

        return Response({
            "status": "success",
            "data": {
                "finance_plan_id": plan.id,
                "amount_to_finance": str(plan.amount_to_finance),
                "total_disbursed": str(disbursed_total),
                "balances": balances,
                "entries": CustomerLoanLedgerEntrySerializer(ledger_entries, many=True).data
            }
        })


class LoanManualActionAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, plan_id):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        action_type = request.data.get("action_type") # CHARGE_INTEREST, CHARGE_PENALTY, WRITE_OFF
        amount = request.data.get("amount")
        description = request.data.get("description")

        if not action_type:
            return Response({"status": "error", "message": "action_type is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from finance.accounting_services import AccountingEngineService
            if action_type == 'CHARGE_INTEREST':
                if not amount:
                    return Response({"status": "error", "message": "amount is required."}, status=status.HTTP_400_BAD_REQUEST)
                entry = AccountingEngineService.charge_interest_or_penalty(plan_id, amount, 'INTEREST', description)
                msg = "Interest charged successfully."
            elif action_type == 'CHARGE_PENALTY':
                if not amount:
                    return Response({"status": "error", "message": "amount is required."}, status=status.HTTP_400_BAD_REQUEST)
                entry = AccountingEngineService.charge_interest_or_penalty(plan_id, amount, 'PENALTY', description)
                msg = "Penalty charged successfully."
            elif action_type == 'WRITE_OFF':
                entry = AccountingEngineService.write_off_loan(plan_id, description)
                msg = "Loan written off successfully."
            else:
                return Response({"status": "error", "message": "Invalid action_type."}, status=status.HTTP_400_BAD_REQUEST)

            return Response({
                "status": "success",
                "message": msg,
                "data": CustomerLoanLedgerEntrySerializer(entry).data
            })
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class EMIInvoiceCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request, emi_id):
        if request.user.role not in ["admin", "global_manager", "financial_manager"]:
            return Response({"status": "error", "message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        from .models import EMISchedule, Invoice
        from django.db import transaction
        from django.utils import timezone
        import random
        from decimal import Decimal

        try:
            with transaction.atomic():
                emi = EMISchedule.objects.select_for_update().filter(id=emi_id).first()
                if not emi:
                    return Response({"status": "error", "message": "EMI Schedule not found."}, status=status.HTTP_404_NOT_FOUND)

                plan = emi.finance_plan
                if plan.disbursement_status != 'DISBURSED':
                    return Response({"status": "error", "message": "Cannot generate invoice for an undisbursed loan."}, status=status.HTTP_400_BAD_REQUEST)

                if Invoice.objects.filter(emi_schedule=emi).exists():
                    return Response({"status": "error", "message": "Invoice already generated for this EMI installment."}, status=status.HTTP_400_BAD_REQUEST)

                n = emi.installment_number
                if n > 1:
                    prev_emi = EMISchedule.objects.filter(finance_plan=plan, installment_number=n-1).first()
                    if not prev_emi or not Invoice.objects.filter(emi_schedule=prev_emi).exists():
                        return Response({
                            "status": "error",
                            "message": f"Cannot generate invoice for installment #{n}. Installment #{n-1} must have an invoice generated first."
                        }, status=status.HTTP_400_BAD_REQUEST)

                # Generate unique sequential EMI invoice number
                invoice_number = None
                while not invoice_number:
                    last_inv = Invoice.objects.filter(invoice_number__startswith='OLA-EMI-').order_by('-id').first()
                    if last_inv:
                        try:
                            last_num = int(last_inv.invoice_number.split('-')[-1])
                            next_num = last_num + 1
                        except (ValueError, IndexError):
                            next_num = 1
                    else:
                        next_num = 1
                    candidate = f"OLA-EMI-{next_num:06d}"
                    if not Invoice.objects.filter(invoice_number=candidate).exists():
                        invoice_number = candidate

                # Calculate balances
                penalty_amount = Decimal(str(request.data.get('penalty_amount', '0.00')))
                amount_paid = emi.amount_paid
                total_to_bill = emi.installment_amount + penalty_amount
                balance = total_to_bill - amount_paid
                inv_status = 'PAID' if emi.status == 'PAID' else 'PENDING'
 
                # Retrieve customer
                customer = plan.credit_application.customer
 
                # Line item description
                line_items = [{
                    "name": f"EMI Installment #{n} - Plan {plan.loan_account_number or plan.id}",
                    "qty": 1.0,
                    "unit_price": float(emi.installment_amount),
                    "sales_account_id": None,
                    "tax_rate_id": None,
                    "tax_rate": 0.0,
                    "tax_amount": 0.0,
                    "total": float(emi.installment_amount)
                }]
                if penalty_amount > 0:
                    line_items.append({
                        "name": f"Late Penalty Fee - Plan {plan.loan_account_number or plan.id}",
                        "qty": 1.0,
                        "unit_price": float(penalty_amount),
                        "sales_account_id": None,
                        "tax_rate_id": None,
                        "tax_rate": 0.0,
                        "tax_amount": 0.0,
                        "total": float(penalty_amount)
                    })
 
                invoice = Invoice.objects.create(
                    invoice_number=invoice_number,
                    customer=customer,
                    finance_plan=plan,
                    emi_schedule=emi,
                    due_date=emi.due_date,
                    base_amount=emi.installment_amount,
                    subtotal=total_to_bill,
                    tax_amount=Decimal('0.00'),
                    total_amount=total_to_bill,
                    balance=balance,
                    amount_paid=amount_paid,
                    principal_amount=emi.principal,
                    interest_amount=emi.interest,
                    penalty_amount=penalty_amount,
                    status=inv_status,
                    invoice_type='PLAN',
                    line_items=line_items,
                    notes=f"Generated invoice for EMI #{n} on plan {plan.loan_account_number or plan.id}"
                )
                
                # Generate double-entry ledger entries!
                invoice.generate_ledger_entries()

                # Also ensure the EMI status is updated to DUE if it was DRAFT/UPCOMING and is now due
                if emi.status == 'DRAFT':
                    emi.status = 'UPCOMING'
                    emi.save()

                return Response({
                    "status": "success",
                    "message": f"Invoice {invoice.invoice_number} generated successfully.",
                    "data": {
                        "id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "total_amount": str(invoice.total_amount),
                        "status": invoice.status
                    }
                })

        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


from .models import UncategorizedBankEntry
from .serializers import UncategorizedBankEntrySerializer
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from datetime import datetime, date
import csv
import io
import openpyxl

def parse_statement_file(file_obj, filename):
    parsed_entries = []
    is_excel = filename.endswith('.xlsx') or filename.endswith('.xls')
    
    if is_excel:
        try:
            wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
            sheet = wb.active
            rows_iter = list(sheet.iter_rows(values_only=True))
        except Exception as e:
            file_obj.seek(0)
            is_excel = False

    if not is_excel:
        try:
            content_str = file_obj.read().decode('utf-8-sig', errors='ignore')
            reader = csv.reader(io.StringIO(content_str))
            rows_iter = list(reader)
        except Exception as e:
            raise ValueError(f"Failed to read file as CSV or Excel: {str(e)}")

    headers = []
    
    # English & Spanish headers mappings
    DATE_HEADERS = ['date', 'fecha', 'fecha de proceso', 'value date', 'fecha valor']
    DESC_HEADERS = ['description', 'descripcion', 'descripción', 'concepto', 'detalle', 'narration', 'glosa', 'motivo']
    REF_HEADERS = ['reference', 'referencia', 'documento', 'doc', 'ref', 'nro doc', 'no. doc', 'nro. documento']
    AMOUNT_HEADERS = ['amount', 'monto', 'valor', 'amount usd', 'importe', 'saldo']
    DEBIT_HEADERS = ['debit', 'debito', 'débito', 'egreso', 'cargo', 'retiros']
    CREDIT_HEADERS = ['credit', 'credito', 'crédito', 'ingreso', 'abono', 'depósitos', 'depositos']

    for r_idx, row in enumerate(rows_iter, 1):
        if not row or not any(x is not None and str(x).strip() for x in row):
            continue
            
        row_str = [str(x).lower().strip() if x is not None else "" for x in row]
        
        if not headers:
            if any(h in row_str for h in ['date', 'fecha', 'concepto', 'description', 'amount', 'monto', 'valor', 'debito', 'credito']):
                headers = row_str
                continue
            if r_idx < 10:
                continue
            else:
                headers = [str(i) for i in range(len(row))]
                
        row_dict = {}
        for c_idx, val in enumerate(row):
            if c_idx < len(headers):
                row_dict[headers[c_idx]] = val
                
        date_val = None
        for key in DATE_HEADERS:
            if key in row_dict and row_dict[key] is not None:
                date_val = row_dict[key]
                break
                
        desc_val = None
        for key in DESC_HEADERS:
            if key in row_dict and row_dict[key] is not None:
                desc_val = str(row_dict[key]).strip()
                break
        if not desc_val:
            desc_val = "Bank Transaction"

        ref_val = None
        for key in REF_HEADERS:
            if key in row_dict and row_dict[key] is not None:
                ref_val = str(row_dict[key]).strip()
                break

        amount_val = Decimal('0.00')
        type_val = 'CREDIT'
        
        debit_col = None
        for key in DEBIT_HEADERS:
            if key in row_dict and row_dict[key] is not None:
                try:
                    debit_col = Decimal(str(row_dict[key]).replace(',', '').strip())
                except:
                    pass
                break
                
        credit_col = None
        for key in CREDIT_HEADERS:
            if key in row_dict and row_dict[key] is not None:
                try:
                    credit_col = Decimal(str(row_dict[key]).replace(',', '').strip())
                except:
                    pass
                break
                
        if debit_col is not None and debit_col > 0:
            amount_val = debit_col
            type_val = 'DEBIT'
        elif credit_col is not None and credit_col > 0:
            amount_val = credit_col
            type_val = 'CREDIT'
        else:
            for key in AMOUNT_HEADERS:
                if key in row_dict and row_dict[key] is not None:
                    try:
                        val = Decimal(str(row_dict[key]).replace(',', '').strip())
                        if val < 0:
                            amount_val = abs(val)
                            type_val = 'DEBIT'
                        else:
                            amount_val = val
                            type_val = 'CREDIT'
                    except:
                        pass
                    break
        
        if isinstance(date_val, str):
            date_val = date_val.strip()
            parsed_date = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
                try:
                    parsed_date = datetime.strptime(date_val, fmt).date()
                    break
                except ValueError:
                    continue
            if parsed_date:
                date_val = parsed_date
            else:
                date_val = timezone.now().date()
        elif isinstance(date_val, datetime):
            date_val = date_val.date()
        elif not isinstance(date_val, date):
            date_val = timezone.now().date()

        if amount_val > 0:
            parsed_entries.append({
                'entry_date': date_val,
                'description': desc_val,
                'amount': amount_val,
                'type': type_val,
                'reference_number': ref_val
            })
            
    return parsed_entries


class BankAccountUploadStatementAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, bank_account_id):
        try:
            bank_account = BankAccount.objects.get(pk=bank_account_id)
        except BankAccount.DoesNotExist:
            return Response({"error": "Bank account not found"}, status=status.HTTP_404_NOT_FOUND)

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            entries_data = parse_statement_file(file_obj, file_obj.name)
        except Exception as e:
            return Response({"error": f"Error parsing statement file: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            for item in entries_data:
                exists = UncategorizedBankEntry.objects.filter(
                    bank_account=bank_account,
                    entry_date=item['entry_date'],
                    amount=item['amount'],
                    type=item['type'],
                    description=item['description'],
                    reference_number=item['reference_number']
                ).exists()

                if not exists:
                    UncategorizedBankEntry.objects.create(
                        bank_account=bank_account,
                        entry_date=item['entry_date'],
                        description=item['description'],
                        amount=item['amount'],
                        type=item['type'],
                        reference_number=item['reference_number']
                    )
                    created_count += 1
                else:
                    skipped_count += 1

        return Response({
            "status": "success",
            "message": f"Successfully parsed statement. Imported {created_count} entries, skipped {skipped_count} duplicates.",
            "imported_count": created_count,
            "skipped_count": skipped_count
        }, status=status.HTTP_201_CREATED)


class BankAccountUncategorizedEntriesAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, bank_account_id):
        entries = UncategorizedBankEntry.objects.filter(
            bank_account_id=bank_account_id,
            is_mapped=False
        )
        
        entry_type = request.query_params.get('type')
        if entry_type:
            entries = entries.filter(type=entry_type.upper())
            
        entries = entries.order_by('-entry_date', '-id')
        
        paginator = FinancePlanPagination()
        page = paginator.paginate_queryset(entries, request, view=self)
        serializer = UncategorizedBankEntrySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class UncategorizedBankEntryMapAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, pk):
        try:
            entry = UncategorizedBankEntry.objects.select_related('bank_account').get(pk=pk)
        except UncategorizedBankEntry.DoesNotExist:
            return Response({"error": "Uncategorized entry not found"}, status=status.HTTP_404_NOT_FOUND)

        if entry.is_mapped:
            return Response({"error": "Entry is already mapped"}, status=status.HTTP_400_BAD_REQUEST)

        invoices_data = request.data.get('invoices')
        single_invoice_id = request.data.get('invoice_id')

        if not invoices_data and not single_invoice_id:
            return Response({"error": "Missing invoices or invoice_id parameter"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                target_customer = None
                sum_amount = Decimal('0.00')
                first_invoice = None

                if not invoices_data:
                    # Single invoice backward compatible mapping
                    try:
                        invoice = Invoice.objects.select_related('customer').get(pk=single_invoice_id)
                    except Invoice.DoesNotExist:
                        return Response({"error": "Invoice not found"}, status=status.HTTP_404_NOT_FOUND)

                    if invoice.balance <= 0:
                        return Response({"error": f"Invoice {invoice.invoice_number} is already fully paid"}, status=status.HTTP_400_BAD_REQUEST)

                    applied_amount = min(entry.amount, invoice.balance)
                    invoices_list = [{
                        'invoice_id': invoice.id,
                        'amount_applied': float(applied_amount)
                    }]
                    sum_amount = applied_amount
                    target_customer = invoice.customer
                    first_invoice = invoice
                else:
                    # Multi-invoice Zoho-like mapping
                    if not isinstance(invoices_data, list) or len(invoices_data) == 0:
                        return Response({"error": "invoices must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)

                    invoices_list = []
                    for item in invoices_data:
                        inv_id = item.get('invoice_id')
                        amt = Decimal(str(item.get('amount_applied', 0)))
                        if not inv_id or amt <= 0:
                            return Response({"error": "Invalid invoice_id or amount_applied in invoices list"}, status=status.HTTP_400_BAD_REQUEST)

                        try:
                            invoice = Invoice.objects.select_related('customer').get(pk=inv_id)
                        except Invoice.DoesNotExist:
                            return Response({"error": f"Invoice with ID {inv_id} not found"}, status=status.HTTP_404_NOT_FOUND)

                        if invoice.balance <= 0:
                            return Response({"error": f"Invoice {invoice.invoice_number} is already fully paid"}, status=status.HTTP_400_BAD_REQUEST)

                        if amt > invoice.balance:
                            return Response({"error": f"Applied amount ({amt}) exceeds balance ({invoice.balance}) for invoice {invoice.invoice_number}"}, status=status.HTTP_400_BAD_REQUEST)

                        if target_customer is None:
                            target_customer = invoice.customer
                            first_invoice = invoice
                        elif target_customer.id != invoice.customer.id:
                            return Response({"error": f"All invoices must belong to the same customer ({target_customer.first_name} {target_customer.last_name})"}, status=status.HTTP_400_BAD_REQUEST)

                        sum_amount += amt
                        invoices_list.append({
                            'invoice_id': invoice.id,
                            'amount_applied': float(amt)
                        })

                    if sum_amount > entry.amount:
                        return Response({"error": f"Total applied amount ({sum_amount}) exceeds statement entry amount ({entry.amount})"}, status=status.HTTP_400_BAD_REQUEST)

                deposited_to = entry.bank_account.accounting_code
                if not deposited_to:
                    return Response({"error": "Bank account is not linked to any accounting code"}, status=status.HTTP_400_BAD_REQUEST)

                import random
                date_str = timezone.now().strftime("%Y%m%d")
                rand_str = str(random.randint(1000, 9999))
                payment_number = f"PR-{date_str}-{rand_str}"

                payment = PaymentReceived.objects.create(
                    payment_number=payment_number,
                    customer=target_customer,
                    amount_received=sum_amount,
                    payment_date=timezone.now(),
                    payment_method='BANK_TRANSFER',
                    transaction_reference=entry.reference_number or f"STATEMENT-MAP-{entry.id}",
                    deposited_to=deposited_to,
                    invoices=invoices_list,
                    notes=f"Mapped from bank statement: {entry.description}"
                )

                payment.process_payment(user=request.user if request.user.is_authenticated else None)

                entry.is_mapped = True
                entry.invoice = first_invoice
                entry.save()

                AuditLog.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    customer=target_customer,
                    action_type='PAYMENT_RECEIVED',
                    description=f"Recorded PaymentReceived {payment_number} of {sum_amount} via bank statement mapping to multiple invoices",
                    metadata={
                        "payment_number": payment_number,
                        "amount_received": str(sum_amount),
                        "payment_method": "BANK_TRANSFER",
                        "transaction_reference": entry.reference_number
                    }
                )

            return Response({
                "status": "success",
                "message": f"Successfully mapped entry to {len(invoices_list)} invoice(s). Created payment {payment_number}.",
                "payment_number": payment_number,
                "applied_amount": str(sum_amount)
            })

        except Exception as e:
            return Response({"error": f"Failed to map entry: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from .models import PaymentMade

class UncategorizedBankEntriesBulkMapAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        entry_ids = request.data.get('entry_ids')
        if not entry_ids or not isinstance(entry_ids, list):
            return Response({"error": "Missing or invalid entry_ids parameter"}, status=status.HTTP_400_BAD_REQUEST)

        entries = UncategorizedBankEntry.objects.filter(id__in=entry_ids).select_related('bank_account')
        if len(entries) != len(entry_ids):
            return Response({"error": "One or more bank entries were not found"}, status=status.HTTP_404_NOT_FOUND)

        if any(e.is_mapped for e in entries):
            return Response({"error": "One or more bank entries are already mapped"}, status=status.HTTP_400_BAD_REQUEST)

        types = set(e.type for e in entries)
        if len(types) > 1:
            return Response({"error": "Cannot map mixed CREDIT and DEBIT entries together"}, status=status.HTTP_400_BAD_REQUEST)
        entry_type = list(types)[0]

        bank_accounts = set(e.bank_account.id for e in entries)
        if len(bank_accounts) > 1:
            return Response({"error": "All bank entries must belong to the same bank account"}, status=status.HTTP_400_BAD_REQUEST)
        bank_account = entries[0].bank_account

        total_entry_amount = sum(e.amount for e in entries)

        if entry_type == 'CREDIT':
            invoices_data = request.data.get('invoices')
            if not invoices_data or not isinstance(invoices_data, list):
                return Response({"error": "Missing or invalid invoices parameter for CREDIT entries"}, status=status.HTTP_400_BAD_REQUEST)

            try:
                with transaction.atomic():
                    target_customer = None
                    sum_amount = Decimal('0.00')
                    first_invoice = None
                    invoices_list = []

                    for item in invoices_data:
                        inv_id = item.get('invoice_id')
                        amt = Decimal(str(item.get('amount_applied', 0)))
                        if not inv_id or amt <= 0:
                            return Response({"error": "Invalid invoice_id or amount_applied in invoices list"}, status=status.HTTP_400_BAD_REQUEST)

                        try:
                            invoice = Invoice.objects.select_related('customer').get(pk=inv_id)
                        except Invoice.DoesNotExist:
                            return Response({"error": f"Invoice with ID {inv_id} not found"}, status=status.HTTP_404_NOT_FOUND)

                        if invoice.balance <= 0:
                            return Response({"error": f"Invoice {invoice.invoice_number} is already fully paid"}, status=status.HTTP_400_BAD_REQUEST)

                        if amt > invoice.balance:
                            return Response({"error": f"Applied amount ({amt}) exceeds balance ({invoice.balance}) for invoice {invoice.invoice_number}"}, status=status.HTTP_400_BAD_REQUEST)

                        if target_customer is None:
                            target_customer = invoice.customer
                            first_invoice = invoice
                        elif target_customer.id != invoice.customer.id:
                            return Response({"error": f"All invoices must belong to the same customer ({target_customer.first_name} {target_customer.last_name})"}, status=status.HTTP_400_BAD_REQUEST)

                        sum_amount += amt
                        invoices_list.append({
                            'invoice_id': invoice.id,
                            'amount_applied': float(amt)
                        })

                    if sum_amount > total_entry_amount:
                        return Response({"error": f"Total applied amount ({sum_amount}) exceeds total statement entries amount ({total_entry_amount})"}, status=status.HTTP_400_BAD_REQUEST)

                    deposited_to = bank_account.accounting_code
                    if not deposited_to:
                        return Response({"error": "Bank account is not linked to any accounting code"}, status=status.HTTP_400_BAD_REQUEST)

                    import random
                    date_str = timezone.now().strftime("%Y%m%d")
                    rand_str = str(random.randint(1000, 9999))
                    payment_number = f"PR-{date_str}-{rand_str}"

                    refs = [e.reference_number for e in entries if e.reference_number]
                    tx_ref = ", ".join(refs) if refs else f"BULK-MAP-{payment_number}"

                    payment = PaymentReceived.objects.create(
                        payment_number=payment_number,
                        customer=target_customer,
                        amount_received=sum_amount,
                        payment_date=timezone.now(),
                        payment_method='BANK_TRANSFER',
                        transaction_reference=tx_ref[:100],
                        deposited_to=deposited_to,
                        invoices=invoices_list,
                        notes=f"Mapped from bank statement bulk entries: " + ", ".join([e.description[:30] for e in entries])
                    )

                    payment.process_payment(user=request.user if request.user.is_authenticated else None)

                    for e in entries:
                        e.is_mapped = True
                        e.invoice = first_invoice
                        e.save()

                    AuditLog.objects.create(
                        user=request.user if request.user.is_authenticated else None,
                        customer=target_customer,
                        action_type='PAYMENT_RECEIVED',
                        description=f"Recorded PaymentReceived {payment_number} of {sum_amount} via bank statement bulk mapping to multiple invoices",
                        metadata={
                            "payment_number": payment_number,
                            "amount_received": str(sum_amount),
                            "payment_method": "BANK_TRANSFER",
                            "mapped_entries": entry_ids
                        }
                    )

                return Response({
                    "status": "success",
                    "message": f"Successfully mapped {len(entries)} entries to {len(invoices_list)} invoice(s). Created payment {payment_number}.",
                    "payment_number": payment_number,
                    "applied_amount": str(sum_amount)
                })

            except Exception as e:
                return Response({"error": f"Failed to map entries: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        else:
            # --- DEBIT Mapping (Vendor Bills) ---
            bills_data = request.data.get('bills')
            if not bills_data or not isinstance(bills_data, list):
                return Response({"error": "Missing or invalid bills parameter for DEBIT entries"}, status=status.HTTP_400_BAD_REQUEST)

            try:
                with transaction.atomic():
                    target_vendor = None
                    sum_amount = Decimal('0.00')
                    bills_list = []

                    for item in bills_data:
                        b_id = item.get('bill_id')
                        amt = Decimal(str(item.get('amount_applied', 0)))
                        if not b_id or amt <= 0:
                            return Response({"error": "Invalid bill_id or amount_applied in bills list"}, status=status.HTTP_400_BAD_REQUEST)

                        try:
                            bill = Bill.objects.select_related('vendor').get(pk=b_id)
                        except Bill.DoesNotExist:
                            return Response({"error": f"Bill with ID {b_id} not found"}, status=status.HTTP_404_NOT_FOUND)

                        if bill.balance <= 0:
                            return Response({"error": f"Bill {bill.bill_number} is already fully paid"}, status=status.HTTP_400_BAD_REQUEST)

                        if amt > bill.balance:
                            return Response({"error": f"Applied amount ({amt}) exceeds balance ({bill.balance}) for bill {bill.bill_number}"}, status=status.HTTP_400_BAD_REQUEST)

                        if target_vendor is None:
                            target_vendor = bill.vendor
                        elif target_vendor.id != bill.vendor.id:
                            return Response({"error": f"All bills must belong to the same vendor ({target_vendor.name})"}, status=status.HTTP_400_BAD_REQUEST)

                        sum_amount += amt
                        bills_list.append({
                            'bill_id': bill.id,
                            'amount_applied': float(amt)
                        })

                    if sum_amount > total_entry_amount:
                        return Response({"error": f"Total applied amount ({sum_amount}) exceeds total statement entries amount ({total_entry_amount})"}, status=status.HTTP_400_BAD_REQUEST)

                    paid_from = bank_account.accounting_code
                    if not paid_from:
                        return Response({"error": "Bank account is not linked to any accounting code"}, status=status.HTTP_400_BAD_REQUEST)

                    import random
                    date_str = timezone.now().strftime("%Y%m%d")
                    rand_str = str(random.randint(1000, 9999))
                    payment_number = f"PM-{date_str}-{rand_str}"

                    refs = [e.reference_number for e in entries if e.reference_number]
                    tx_ref = ", ".join(refs) if refs else f"BULK-MAP-{payment_number}"

                    payment = PaymentMade.objects.create(
                        payment_number=payment_number,
                        vendor=target_vendor,
                        amount_paid=sum_amount,
                        payment_date=timezone.now().date(),
                        payment_method='BANK_TRANSFER',
                        paid_from=paid_from,
                        bills=bills_list,
                        notes=f"Mapped from bank statement bulk entries: " + ", ".join([e.description[:30] for e in entries])
                    )

                    payment.process_payment()

                    for e in entries:
                        e.is_mapped = True
                        e.save()

                    AuditLog.objects.create(
                        user=request.user if request.user.is_authenticated else None,
                        action_type='PAYMENT_MADE',
                        description=f"Recorded PaymentMade {payment_number} of {sum_amount} to vendor {target_vendor.name} via bank statement mapping",
                        metadata={
                            "payment_number": payment_number,
                            "amount_paid": str(sum_amount),
                            "payment_method": "BANK_TRANSFER",
                            "mapped_entries": entry_ids
                        }
                    )

                return Response({
                    "status": "success",
                    "message": f"Successfully mapped {len(entries)} entries to {len(bills_list)} bill(s). Created vendor payment {payment_number}.",
                    "payment_number": payment_number,
                    "applied_amount": str(sum_amount)
                })

            except Exception as e:
                return Response({"error": f"Failed to map entries: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==============================================================================
# FINANCIAL REPORTS & FIXED ASSET VIEWS (P&L, BALANCE SHEET, FIXED ASSETS)
# ==============================================================================
import math
import time
import datetime as dt_module
from django.db.models import Q
from .models import FixedAssetType, FixedAsset, DepreciationScheduleEntry

class ProfitLossReportAPIView(APIView):
    def get(self, request):
        user = request.user
        user_role = getattr(user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "You are not authorized to view this report."}, status=status.HTTP_403_FORBIDDEN)

        start_date = request.query_params.get("startDate") or request.query_params.get("date_from")
        end_date = request.query_params.get("endDate") or request.query_params.get("date_to")
        
        if not start_date or not end_date:
            return Response({
                "status": "success",
                "data": {
                    "income": [],
                    "expenses": [],
                    "netProfit": 0
                },
                "message": "Please select a date range to generate the Profit & Loss report."
            })

        # We query LedgerEntry objects within the date range
        entries = LedgerEntry.objects.filter(entry_date__date__range=[start_date, end_date])
        
        # Prepopulate income and expenses
        income_map = {}
        expense_map = {}
        
        active_codes = AccountingCode.objects.filter(is_active=True)
        for code in active_codes:
            if code.category in ['REVENUE', 'INCOME']:
                income_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id}
            elif code.category in ['EXPENSE']:
                expense_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id}
                
        for entry in entries:
            code = entry.accounting_code
            category = code.category
            amount = float(entry.amount)
            if category in ['REVENUE', 'INCOME']:
                val = amount if entry.type == 'CREDIT' else -amount
                if code.name not in income_map:
                    income_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id}
                income_map[code.name]["amount"] += val
            elif category == 'EXPENSE':
                val = amount if entry.type == 'DEBIT' else -amount
                if code.name not in expense_map:
                    expense_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id}
                expense_map[code.name]["amount"] += val

        income_list = [{"name": k, **v} for k, v in income_map.items()]
        expense_list = [{"name": k, **v} for k, v in expense_map.items()]
        
        total_income = sum(item["amount"] for item in income_list)
        total_expense = sum(item["amount"] for item in expense_list)
        net_profit = total_income - total_expense
        
        return Response({
            "status": "success",
            "data": {
                "income": income_list,
                "expenses": expense_list,
                "netProfit": net_profit
            }
        })


class BalanceSheetReportAPIView(APIView):
    def get(self, request):
        user = request.user
        user_role = getattr(user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "You are not authorized to view this report."}, status=status.HTTP_403_FORBIDDEN)

        end_date = request.query_params.get("endDate") or request.query_params.get("date_to") or request.query_params.get("startDate") or request.query_params.get("date_from")
        
        if not end_date:
            return Response({
                "status": "success",
                "data": {
                    "assets": [],
                    "liabilities": [],
                    "equity": [],
                    "assetsTotal": 0,
                    "liabilitiesTotal": 0,
                    "equityTotal": 0
                },
                "message": "Please select an end date to generate the Balance Sheet."
            })

        # We query LedgerEntry up to end_date
        entries = LedgerEntry.objects.filter(entry_date__date__lte=end_date)
        
        assets_map = {}
        liabilities_map = {}
        equity_map = {}
        
        active_codes = AccountingCode.objects.filter(is_active=True)
        for code in active_codes:
            if code.category == 'ASSET':
                assets_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id, "accountType": "Asset"}
            elif code.category == 'LIABILITY':
                liabilities_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id, "accountType": "Liability"}
            elif code.category == 'EQUITY':
                equity_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id, "accountType": "Equity"}
                
        cumulative_net_income = 0.0
        
        for entry in entries:
            code = entry.accounting_code
            category = code.category
            amount = float(entry.amount)
            
            if category == 'ASSET':
                val = amount if entry.type == 'DEBIT' else -amount
                if code.name not in assets_map:
                    assets_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id, "accountType": "Asset"}
                assets_map[code.name]["amount"] += val
            elif category == 'LIABILITY':
                val = amount if entry.type == 'CREDIT' else -amount
                if code.name not in liabilities_map:
                    liabilities_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id, "accountType": "Liability"}
                liabilities_map[code.name]["amount"] += val
            elif category == 'EQUITY':
                val = amount if entry.type == 'CREDIT' else -amount
                if code.name not in equity_map:
                    equity_map[code.name] = {"amount": 0.0, "code": code.code, "category": code.category, "id": code.id, "accountType": "Equity"}
                equity_map[code.name]["amount"] += val
            elif category in ['REVENUE', 'INCOME']:
                cumulative_net_income += (amount if entry.type == 'CREDIT' else -amount)
            elif category == 'EXPENSE':
                cumulative_net_income -= (amount if entry.type == 'DEBIT' else -amount)

        # Overwrite Retained Earnings (Current Period)
        if cumulative_net_income != 0:
            re_name = "Retained Earnings (Current Period)"
            if re_name not in equity_map:
                equity_map[re_name] = {"amount": 0.0, "code": "RE-CURRENT", "category": "EQUITY", "id": 0, "accountType": "Equity"}
            equity_map[re_name]["amount"] += cumulative_net_income

        assets_list = [{"name": k, **v} for k, v in assets_map.items()]
        liabilities_list = [{"name": k, **v} for k, v in liabilities_map.items()]
        equity_list = [{"name": k, **v} for k, v in equity_map.items()]
        
        assets_total = sum(item["amount"] for item in assets_list)
        liabilities_total = sum(item["amount"] for item in liabilities_list)
        equity_total = sum(item["amount"] for item in equity_list)
        
        return Response({
            "status": "success",
            "data": {
                "assets": assets_list,
                "liabilities": liabilities_list,
                "equity": equity_list,
                "assetsTotal": assets_total,
                "liabilitiesTotal": liabilities_total,
                "equityTotal": equity_total
            }
        })


class FixedAssetTypeListCreateAPIView(APIView):
    def get(self, request):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
        types = FixedAssetType.objects.all()
        data = [{"_id": t.id, "name": t.name, "description": t.description, "isActive": t.is_active} for t in types]
        return Response({"status": "success", "data": data})

    def post(self, request):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
        name = request.data.get('name')
        description = request.data.get('description')
        is_active = request.data.get('isActive', True)
        if not name:
            return Response({"status": "error", "message": "Name is required"}, status=status.HTTP_400_BAD_REQUEST)
        t = FixedAssetType.objects.create(name=name, description=description, is_active=is_active)
        return Response({"status": "success", "data": {"_id": t.id, "name": t.name, "description": t.description, "isActive": t.is_active}})


class FixedAssetTypeDetailAPIView(APIView):
    def put(self, request, pk):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            t = FixedAssetType.objects.get(pk=pk)
        except FixedAssetType.DoesNotExist:
            return Response({"status": "error", "message": "Fixed Asset Type not found"}, status=status.HTTP_404_NOT_FOUND)
            
        name = request.data.get('name')
        description = request.data.get('description')
        is_active = request.data.get('isActive')
        
        if name is not None:
            t.name = name
        if description is not None:
            t.description = description
        if is_active is not None:
            t.is_active = is_active
            
        t.save()
        return Response({"status": "success", "data": {"_id": t.id, "name": t.name, "description": t.description, "isActive": t.is_active}})

    def delete(self, request, pk):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            t = FixedAssetType.objects.get(pk=pk)
        except FixedAssetType.DoesNotExist:
            return Response({"status": "error", "message": "Fixed Asset Type not found"}, status=status.HTTP_404_NOT_FOUND)
            
        t.delete()
        return Response({"status": "success", "message": "Fixed Asset Type deleted successfully"})


def generate_depreciation_schedule(asset):
    cost = float(asset.purchase_price)
    salvage = float(asset.residual_value)
    years = float(asset.useful_life_years)
    
    if asset.asset_life and asset.asset_life_unit:
        if asset.asset_life_unit == "Months":
            years = float(asset.asset_life) / 12.0
        else:
            years = float(asset.asset_life)
            
    depreciable_amount = cost - salvage
    interval = asset.depreciation_interval or "Monthly"
    
    if depreciable_amount <= 0 or years <= 0:
        return
        
    start_date = asset.depreciation_start_date or asset.purchase_date
    if isinstance(start_date, str):
        start_date = dt_module.date.fromisoformat(start_date)
        
    # Clear existing schedule
    asset.depreciation_schedule.all().delete()
    accumulated_depreciation = 0.0
    
    if interval == "Yearly":
        annual_depr = round(depreciable_amount / years, 2)
        total_periods = math.ceil(years)
        for i in range(1, total_periods + 1):
            dep_amount = annual_depr
            if i == total_periods:
                dep_amount = round(depreciable_amount - accumulated_depreciation, 2)
            accumulated_depreciation = round(accumulated_depreciation + dep_amount, 2)
            book_value = round(cost - accumulated_depreciation, 2)
            
            period_date = dt_module.date(start_date.year + i - 1, 12, 31)
            
            DepreciationScheduleEntry.objects.create(
                fixed_asset=asset,
                period_index=i,
                period_date=period_date,
                depreciation_amount=Decimal(str(dep_amount)),
                accumulated_depreciation=Decimal(str(accumulated_depreciation)),
                book_value=Decimal(str(book_value)),
                status="Pending"
            )
    else: # Monthly
        total_months = math.ceil(years * 12)
        monthly_depr = round(depreciable_amount / total_months, 2)
        for i in range(1, total_months + 1):
            dep_amount = monthly_depr
            if i == total_months:
                dep_amount = round(depreciable_amount - accumulated_depreciation, 2)
            accumulated_depreciation = round(accumulated_depreciation + dep_amount, 2)
            book_value = round(cost - accumulated_depreciation, 2)
            
            m = start_date.month + i
            y = start_date.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            if m == 12:
                last_day = dt_module.date(y + 1, 1, 1) - dt_module.timedelta(days=1)
            else:
                last_day = dt_module.date(y, m + 1, 1) - dt_module.timedelta(days=1)
                
            DepreciationScheduleEntry.objects.create(
                fixed_asset=asset,
                period_index=i,
                period_date=last_day,
                depreciation_amount=Decimal(str(dep_amount)),
                accumulated_depreciation=Decimal(str(accumulated_depreciation)),
                book_value=Decimal(str(book_value)),
                status="Pending"
            )


class FixedAssetListCreateAPIView(APIView):
    def get(self, request):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
        
        status_filter = request.query_params.get("status")
        search = request.query_params.get("search")
        
        queryset = FixedAsset.objects.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
            
        page_num = request.query_params.get("page")
        limit_num = request.query_params.get("limit") or 25
        
        data_list = []
        for asset in queryset:
            data_list.append({
                "_id": asset.id,
                "name": asset.name,
                "code": asset.code,
                "purchaseDate": asset.purchase_date.isoformat() if asset.purchase_date else None,
                "purchasePrice": float(asset.purchase_price),
                "residualValue": float(asset.residual_value),
                "usefulLifeYears": asset.useful_life_years,
                "location": asset.location,
                "status": asset.status,
                "fixedAssetAccount": {"_id": asset.fixed_asset_account.id, "code": asset.fixed_asset_account.code, "name": asset.fixed_asset_account.name} if asset.fixed_asset_account else None,
                "accumulatedDepreciationAccount": {"_id": asset.accumulated_depreciation_account.id, "code": asset.accumulated_depreciation_account.code, "name": asset.accumulated_depreciation_account.name} if asset.accumulated_depreciation_account else None,
                "depreciationExpenseAccount": {"_id": asset.depreciation_expense_account.id, "code": asset.depreciation_expense_account.code, "name": asset.depreciation_expense_account.name} if asset.depreciation_expense_account else None,
                "currentValue": float(asset.current_value) if asset.current_value is not None else float(asset.purchase_price),
            })
            
        if page_num:
            page_int = int(page_num)
            limit_int = int(limit_num)
            total = len(data_list)
            start = (page_int - 1) * limit_int
            end = start + limit_int
            paginated = data_list[start:end]
            return Response({
                "status": "success",
                "data": {
                    "data": paginated,
                    "total": total,
                    "page": page_int,
                    "limit": limit_int,
                    "pages": math.ceil(total / limit_int)
                }
            })
            
        return Response({"status": "success", "data": data_list})

    def post(self, request):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        d = request.data
        code = d.get("code") or f"FA-{int(time.time())}"
        
        try:
            fixed_asset_account = AccountingCode.objects.get(pk=d.get("fixedAssetAccount"))
            accumulated_depreciation_account = AccountingCode.objects.get(pk=d.get("accumulatedDepreciationAccount"))
            depreciation_expense_account = AccountingCode.objects.get(pk=d.get("depreciationExpenseAccount"))
        except AccountingCode.DoesNotExist:
            return Response({"status": "error", "message": "Invalid Accounting Code(s)"}, status=status.HTTP_400_BAD_REQUEST)
            
        fixed_asset_type_id = d.get("fixedAssetType")
        fixed_asset_type = None
        if fixed_asset_type_id:
            try:
                fixed_asset_type = FixedAssetType.objects.get(pk=fixed_asset_type_id)
            except FixedAssetType.DoesNotExist:
                pass
                
        asset = FixedAsset.objects.create(
            name=d.get("name"),
            code=code,
            purchase_date=d.get("purchaseDate"),
            purchase_price=Decimal(str(d.get("purchasePrice"))),
            residual_value=Decimal(str(d.get("residualValue", 0))),
            useful_life_years=int(d.get("usefulLifeYears", 5)),
            location=d.get("location"),
            purchase_quantity=int(d.get("purchaseQuantity", 1)),
            serial_number=d.get("serialNumber"),
            current_quantity=int(d.get("currentQuantity", 1)),
            current_value=Decimal(str(d.get("currentValue") or d.get("purchasePrice"))),
            disposal_value=Decimal(str(d.get("disposalValue"))) if d.get("disposalValue") else None,
            warranty_expiration_date=d.get("warrantyExpirationDate") or None,
            fixed_asset_type=fixed_asset_type,
            computation_type=d.get("computationType"),
            depreciation_start_date=d.get("depreciationStartDate") or d.get("purchaseDate"),
            asset_life=int(d.get("assetLife")) if d.get("assetLife") else None,
            asset_life_unit=d.get("assetLifeUnit", "Years"),
            notes=d.get("notes"),
            description=d.get("description"),
            depreciation_method=d.get("depreciationMethod", "Straight-Line"),
            depreciation_interval=d.get("depreciationInterval", "Monthly"),
            status=d.get("status", "Draft"),
            fixed_asset_account=fixed_asset_account,
            accumulated_depreciation_account=accumulated_depreciation_account,
            depreciation_expense_account=depreciation_expense_account,
            created_by=request.user
        )
        
        if asset.status == "Active":
            generate_depreciation_schedule(asset)
            
        return Response({
            "status": "success",
            "data": {
                "_id": asset.id,
                "name": asset.name,
                "code": asset.code,
                "status": asset.status
            }
        })


class FixedAssetDetailAPIView(APIView):
    def get(self, request, pk):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            asset = FixedAsset.objects.get(pk=pk)
        except FixedAsset.DoesNotExist:
            return Response({"status": "error", "message": "Asset not found"}, status=status.HTTP_404_NOT_FOUND)
            
        schedule = list(asset.depreciation_schedule.all())
        schedule_data = [{
            "_id": entry.id,
            "periodIndex": entry.period_index,
            "periodDate": entry.period_date.isoformat(),
            "depreciationAmount": float(entry.depreciation_amount),
            "accumulatedDepreciation": float(entry.accumulated_depreciation),
            "bookValue": float(entry.book_value),
            "status": entry.status,
            "postedDate": entry.posted_date.isoformat() if entry.posted_date else None
        } for entry in schedule]
        
        return Response({
            "status": "success",
            "data": {
                "_id": asset.id,
                "name": asset.name,
                "code": asset.code,
                "purchaseDate": asset.purchase_date.isoformat() if asset.purchase_date else None,
                "purchasePrice": float(asset.purchase_price),
                "residualValue": float(asset.residual_value),
                "usefulLifeYears": asset.useful_life_years,
                "location": asset.location,
                "purchaseQuantity": asset.purchase_quantity,
                "serialNumber": asset.serial_number,
                "currentQuantity": asset.current_quantity,
                "currentValue": float(asset.current_value) if asset.current_value is not None else float(asset.purchase_price),
                "disposalValue": float(asset.disposal_value) if asset.disposal_value is not None else None,
                "warrantyExpirationDate": asset.warranty_expiration_date.isoformat() if asset.warranty_expiration_date else None,
                "fixedAssetType": {"_id": asset.fixed_asset_type.id, "name": asset.fixed_asset_type.name} if asset.fixed_asset_type else None,
                "computationType": asset.computation_type,
                "depreciationStartDate": asset.depreciation_start_date.isoformat() if asset.depreciation_start_date else None,
                "assetLife": asset.asset_life,
                "assetLifeUnit": asset.asset_life_unit,
                "notes": asset.notes,
                "description": asset.description,
                "depreciationMethod": asset.depreciation_method,
                "depreciationInterval": asset.depreciation_interval,
                "status": asset.status,
                "fixedAssetAccount": {"_id": asset.fixed_asset_account.id, "code": asset.fixed_asset_account.code, "name": asset.fixed_asset_account.name} if asset.fixed_asset_account else None,
                "accumulatedDepreciationAccount": {"_id": asset.accumulated_depreciation_account.id, "code": asset.accumulated_depreciation_account.code, "name": asset.accumulated_depreciation_account.name} if asset.accumulated_depreciation_account else None,
                "depreciationExpenseAccount": {"_id": asset.depreciation_expense_account.id, "code": asset.depreciation_expense_account.code, "name": asset.depreciation_expense_account.name} if asset.depreciation_expense_account else None,
                "depreciationSchedule": schedule_data
            }
        })

    def put(self, request, pk):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            asset = FixedAsset.objects.get(pk=pk)
        except FixedAsset.DoesNotExist:
            return Response({"status": "error", "message": "Asset not found"}, status=status.HTTP_404_NOT_FOUND)
            
        d = request.data
        if "name" in d: asset.name = d["name"]
        if "purchaseDate" in d: asset.purchase_date = d["purchaseDate"]
        if "purchasePrice" in d: asset.purchase_price = Decimal(str(d["purchasePrice"]))
        if "residualValue" in d: asset.residual_value = Decimal(str(d["residualValue"]))
        if "usefulLifeYears" in d: asset.useful_life_years = int(d["usefulLifeYears"])
        if "location" in d: asset.location = d["location"]
        if "purchaseQuantity" in d: asset.purchase_quantity = int(d["purchaseQuantity"])
        if "serialNumber" in d: asset.serial_number = d["serialNumber"]
        if "currentQuantity" in d: asset.current_quantity = int(d["currentQuantity"])
        if "currentValue" in d: asset.current_value = Decimal(str(d["currentValue"]))
        if "disposalValue" in d: asset.disposal_value = Decimal(str(d["disposalValue"])) if d["disposalValue"] else None
        if "warrantyExpirationDate" in d: asset.warranty_expiration_date = d["warrantyExpirationDate"] or None
        if "computationType" in d: asset.computation_type = d["computationType"]
        if "depreciationStartDate" in d: asset.depreciation_start_date = d["depreciationStartDate"] or None
        if "assetLife" in d: asset.asset_life = int(d["assetLife"]) if d["assetLife"] else None
        if "assetLifeUnit" in d: asset.asset_life_unit = d["assetLifeUnit"]
        if "notes" in d: asset.notes = d["notes"]
        if "description" in d: asset.description = d["description"]
        if "depreciationMethod" in d: asset.depreciation_method = d["depreciationMethod"]
        if "depreciationInterval" in d: asset.depreciation_interval = d["depreciationInterval"]
        
        if "fixedAssetAccount" in d:
            try:
                asset.fixed_asset_account = AccountingCode.objects.get(pk=d["fixedAssetAccount"])
            except AccountingCode.DoesNotExist:
                pass
        if "accumulatedDepreciationAccount" in d:
            try:
                asset.accumulated_depreciation_account = AccountingCode.objects.get(pk=d["accumulatedDepreciationAccount"])
            except AccountingCode.DoesNotExist:
                pass
        if "depreciationExpenseAccount" in d:
            try:
                asset.depreciation_expense_account = AccountingCode.objects.get(pk=d["depreciationExpenseAccount"])
            except AccountingCode.DoesNotExist:
                pass
                
        if "fixedAssetType" in d:
            if d["fixedAssetType"]:
                try:
                    asset.fixed_asset_type = FixedAssetType.objects.get(pk=d["fixedAssetType"])
                except FixedAssetType.DoesNotExist:
                    pass
            else:
                asset.fixed_asset_type = None
                
        old_status = asset.status
        if "status" in d:
            asset.status = d["status"]
            
        asset.save()
        
        if asset.status == "Active" and (old_status != "Active" or asset.depreciation_schedule.count() == 0):
            generate_depreciation_schedule(asset)
            
        return Response({"status": "success", "data": {"_id": asset.id, "name": asset.name, "status": asset.status}})

    def delete(self, request, pk):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            asset = FixedAsset.objects.get(pk=pk)
        except FixedAsset.DoesNotExist:
            return Response({"status": "error", "message": "Asset not found"}, status=status.HTTP_404_NOT_FOUND)
            
        asset.delete()
        return Response({"status": "success", "message": "Asset deleted"})


class FixedAssetCalculateDepreciationPreviewAPIView(APIView):
    def post(self, request):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        d = request.data
        cost = float(d.get("purchasePrice") or d.get("purchaseValue") or 0)
        salvage = float(d.get("residualValue") or d.get("disposalValue") or 0)
        years = float(d.get("usefulLifeYears") or 5)
        
        if d.get("assetLife") and d.get("assetLifeUnit"):
            if d.get("assetLifeUnit") == "Months":
                years = float(d.get("assetLife")) / 12.0
            else:
                years = float(d.get("assetLife"))
                
        depreciable_amount = cost - salvage
        interval = d.get("depreciationInterval") or "Monthly"
        
        if depreciable_amount <= 0 or years <= 0:
            return Response({"status": "success", "data": []})
            
        start_date_str = d.get("depreciationStartDate") or d.get("purchaseDate") or dt_module.date.today().isoformat()
        try:
            start_date = dt_module.date.fromisoformat(start_date_str)
        except ValueError:
            start_date = dt_module.date.today()
            
        schedule = []
        accumulated_depreciation = 0.0
        
        if interval == "Yearly":
            annual_depr = round(depreciable_amount / years, 2)
            total_periods = math.ceil(years)
            for i in range(1, total_periods + 1):
                dep_amount = annual_depr
                if i == total_periods:
                    dep_amount = round(depreciable_amount - accumulated_depreciation, 2)
                accumulated_depreciation = round(accumulated_depreciation + dep_amount, 2)
                book_value = round(cost - accumulated_depreciation, 2)
                
                period_date = dt_module.date(start_date.year + i - 1, 12, 31)
                
                schedule.append({
                    "periodIndex": i,
                    "periodDate": period_date.isoformat(),
                    "depreciationAmount": dep_amount,
                    "accumulatedDepreciation": accumulated_depreciation,
                    "bookValue": book_value,
                    "status": "Pending"
                })
        else: # Monthly
            total_months = math.ceil(years * 12)
            monthly_depr = round(depreciable_amount / total_months, 2)
            for i in range(1, total_months + 1):
                dep_amount = monthly_depr
                if i == total_months:
                    dep_amount = round(depreciable_amount - accumulated_depreciation, 2)
                accumulated_depreciation = round(accumulated_depreciation + dep_amount, 2)
                book_value = round(cost - accumulated_depreciation, 2)
                
                m = start_date.month + i
                y = start_date.year + (m - 1) // 12
                m = (m - 1) % 12 + 1
                if m == 12:
                    last_day = dt_module.date(y + 1, 1, 1) - dt_module.timedelta(days=1)
                else:
                    last_day = dt_module.date(y, m + 1, 1) - dt_module.timedelta(days=1)
                    
                schedule.append({
                    "periodIndex": i,
                    "periodDate": last_day.isoformat(),
                    "depreciationAmount": dep_amount,
                    "accumulatedDepreciation": accumulated_depreciation,
                    "bookValue": book_value,
                    "status": "Pending"
                })
                
        return Response({"status": "success", "data": schedule})


class FixedAssetPostDepreciationAPIView(APIView):
    def post(self, request, pk):
        user_role = getattr(request.user, "role", None)
        if user_role not in ['admin', 'global_manager', 'financial_manager']:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            asset = FixedAsset.objects.get(pk=pk)
        except FixedAsset.DoesNotExist:
            return Response({"status": "error", "message": "Asset not found"}, status=status.HTTP_404_NOT_FOUND)
            
        if asset.status != "Active":
            return Response({"status": "error", "message": "Asset is not Active"}, status=status.HTTP_400_BAD_REQUEST)
            
        period_index = request.data.get("periodIndex")
        if period_index is None:
            return Response({"status": "error", "message": "periodIndex is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            entry = asset.depreciation_schedule.get(period_index=int(period_index))
        except DepreciationScheduleEntry.DoesNotExist:
            return Response({"status": "error", "message": "Period not found in schedule"}, status=status.HTTP_404_NOT_FOUND)
            
        if entry.status == "Posted":
            return Response({"status": "error", "message": "Period already posted"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            with transaction.atomic():
                import random
                rand_num = random.randint(10000, 99999)
                ref_num = f"DEP-{asset.code}-{entry.period_index}-{rand_num}"
                
                while JournalEntry.objects.filter(reference_number=ref_num).exists():
                    rand_num = random.randint(10000, 99999)
                    ref_num = f"DEP-{asset.code}-{entry.period_index}-{rand_num}"
                
                dt_naive = dt_module.datetime.combine(entry.period_date, dt_module.time.min)
                dt_aware = timezone.make_aware(dt_naive)
                
                je = JournalEntry.objects.create(
                    reference_number=ref_num,
                    entry_date=entry.period_date,
                    description=f"Depreciation for asset {asset.name} ({asset.code}) period {entry.period_index}"
                )
                
                debit_le = LedgerEntry.objects.create(
                    journal_entry=je,
                    accounting_code=asset.depreciation_expense_account,
                    type="DEBIT",
                    amount=entry.depreciation_amount,
                    description=f"Depreciation expense - {asset.name}",
                    entry_date=dt_aware
                )
                
                credit_le = LedgerEntry.objects.create(
                    journal_entry=je,
                    accounting_code=asset.accumulated_depreciation_account,
                    type="CREDIT",
                    amount=entry.depreciation_amount,
                    description=f"Accumulated depreciation - {asset.name}",
                    entry_date=dt_aware
                )
                
                entry.status = "Posted"
                entry.ledger_entry = debit_le
                entry.posted_date = timezone.now()
                entry.save()
                
                asset.current_value = entry.book_value
                asset.save()
                
                AuditLog.objects.create(
                    user=request.user,
                    action_type='COMPLETE_FINANCE_VIEWED',
                    description=f"Posted depreciation period {entry.period_index} for asset {asset.code}",
                    metadata={"asset_code": asset.code, "period_index": entry.period_index, "amount": str(entry.depreciation_amount)}
                )
                
            return Response({
                "status": "success",
                "message": f"Successfully posted depreciation for period {entry.period_index}.",
                "data": {
                    "_id": entry.id,
                    "status": entry.status,
                    "postedDate": entry.posted_date.isoformat(),
                    "currentValue": float(asset.current_value)
                }
            })
        except Exception as e:
            return Response({"status": "error", "message": f"Failed to post depreciation: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)







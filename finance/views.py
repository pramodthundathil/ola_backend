
# ============================================================
# Standard Library Imports
# ============================================================
import logging

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
from .models import FinancePlan, PaymentRecord, EMISchedule
from .serializers import FinancePlanSerializer, FinanceOverviewSerializer, PaymentRecordSerializer, FinanceRiskTierSerializer, FinanceCollectionSerializer, FinanceOverdueSerializer
from .permissions import IsAdminOrGlobalManager

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
# Finance Plan List & Create View
# ============================================================
class FinancePlanView(APIView):
    """
    API View for listing and creating Finance Plans.
    - GET: List all finance plans (with pagination)
    - POST: Create a new finance plan
    """
    permission_classes = [IsAdminOrGlobalManager]
    serializer_class = FinancePlanSerializer 
 
    @swagger_auto_schema(
        operation_summary="List all Finance Plans",
        responses={200: FinancePlanSerializer(many=True)},
        tags=["Finance"]
    )

    #-------List All Finance Plans----------
    def get(self, request):        
        try:
            financeplan = FinancePlan.objects.all().order_by('-created_at')
            paginator = FinancePlanPagination()            
            result_page = paginator.paginate_queryset(financeplan, request)
            serializer = self.serializer_class(result_page, many=True, context={'request': request})    
            return paginator.get_paginated_response(serializer.data)           
        except Exception as e:
            logger.error(f"Error fetching finance plans: {str(e)}")
            return Response(
                {"detail": "Internal server error while fetching finance plans."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
    #---------Create Finance Plan ----------------
    @swagger_auto_schema(
        operation_summary="Create a new Finance Plan",
        request_body=FinancePlanSerializer,
        responses={
            201: FinancePlanSerializer,
            400: "Validation Error",
            500: "Internal Server Error"
        },
        tags=["Finance"]
    )    
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(
                    {"message": "Finance Plan created successfully.", "data": serializer.data},
                    status=status.HTTP_201_CREATED
                )
            logger.warning(f"Finance Plan creation failed: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error creating finance plan: {str(e)}")
            return Response(
                {"detail": "Internal server error while creating finance plan."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


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
        
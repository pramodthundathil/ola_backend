
# ============================================================
# Standard Library Imports
# ============================================================
import logging
from decimal import Decimal
from datetime import timedelta

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
from .models import FinancePlan, PaymentRecord, EMISchedule, FinancePlanTerm
from customer.models import Customer, CreditApplication, CreditScore
from .serializers import FinancePlanSerializer, FinancePlanFetchSerializer, FinancePlanTermSerializer, FinanceOverviewSerializer, FinancePlanCreateSerializer, PaymentRecordSerializer, FinanceRiskTierSerializer, FinanceCollectionSerializer, FinanceOverdueSerializer
from .permissions import IsAdminOrGlobalManager
from .decision_engine import DecisionEngine
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
    Automatically creates Finance Plan Terms for a customer using Decision Engine.
    """
    permission_classes = [IsAdminOrGlobalManager]

    @swagger_auto_schema(
        operation_summary="Create Finance Plan Terms",
        request_body=FinancePlanCreateSerializer,
        responses={
            201: FinancePlanTermSerializer(many=True),
            400: "Validation Error",
            500: "Internal Server Error",
        },
        tags=["Finance"]
    )
    def post(self, request):
        try:
            serializer = FinancePlanCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            customer_id = serializer.validated_data["customer_id"]

            customer = get_object_or_404(Customer, id=customer_id)

            # Get latest credit score
            credit_score_obj = (
                CreditScore.objects.filter(customer=customer, is_expired=False)
                .order_by("-created_at")
                .first()
            )

            credit_score = credit_score_obj if credit_score_obj else None
            apc_score = credit_score_obj.apc_score if credit_score_obj else None

            # Get or create active credit application
            credit_app = (
                CreditApplication.objects.filter(customer=customer, status__in=["PENDING_APPROVAL", "PRE_QUALIFIED"])
                .order_by("-created_at")
                .first()
            )
            if not credit_app or credit_app.is_expired():
                credit_app = CreditApplication.objects.create(customer=customer, device_price=0)

            # Run Decision Engine
            engine = DecisionEngine(customer, credit_application=credit_app, credit_score=credit_score)
            decision_results = engine.run()  # returns list of dicts for each term/frequency

            # Save to FinancePlanTerm
            term_serializer = FinancePlanTermSerializer(data=decision_results, many=True)
            term_serializer.is_valid(raise_exception=True)
            term_serializer.save()

            return Response({"message": "Finance Plan Terms created successfully", "data": term_serializer.data},
                            status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error in AutoFinancePlanView: {str(e)}")
            return Response(
                {"detail": "Internal server error while creating finance plan terms."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ============================================================
# Finance Plan List & Create View
# ============================================================
class FinancePlanView(APIView):
    """
    API View for listing and creating Finance Plans.
    - GET: List all finance plans (with pagination)
    - POST: Create a new finance plan
    """
    permission_classes = [AllowAny]
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
        request_body=FinancePlanFetchSerializer,  # <--- Updated here
        responses={
            200: FinancePlanSerializer(many=True),
            400: "Validation Error",
            404: "No Finance Plan Terms found",
            500: "Internal Server Error"
        },
        tags=["Finance"]
    )
    def post(self, request):
        try:
            # Use the new serializer
            serializer = FinancePlanFetchSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            customer_id = serializer.validated_data["customer_id"]
            term = serializer.validated_data["term"]
            frequency = serializer.validated_data["installment_frequency_days"]

            # Verify customer exists
            customer = Customer.objects.filter(id=customer_id).first()
            if not customer:
                return Response({"error": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)

            # Retrieve all FinancePlanTerm records based on user input
            plan_terms = FinancePlanTerm.objects.filter(
                credit_application__customer=customer,
                selected_term=term,
                installment_frequency_days=frequency
            ).order_by('-created_at')

            if not plan_terms.exists():
                return Response(
                    {"error": "No Finance Plan Terms found for the given criteria."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Save or update FinancePlan for each term
            saved_plans = []
            for plan_term in plan_terms:
                finance_plan, created = FinancePlan.objects.update_or_create(
                    credit_application=plan_term.credit_application,
                    defaults={
                        'credit_score': plan_term.credit_score,
                        'apc_score': plan_term.apc_score,
                        'device_price': plan_term.device_price,
                        'is_high_end_device': plan_term.is_high_end_device,
                        'minimum_down_payment_percentage': plan_term.minimum_down_payment_percentage,
                        'actual_down_payment': plan_term.actual_down_payment,
                        'down_payment_percentage': plan_term.down_payment_percentage,
                        'amount_to_finance': plan_term.amount_to_finance,
                        'allowed_terms': plan_term.allowed_terms,
                        'selected_term': plan_term.selected_term,
                        'installment_frequency_days': plan_term.installment_frequency_days,
                        'monthly_installment': plan_term.monthly_installment,
                        'total_amount_payable': plan_term.total_amount_payable,
                        'customer_monthly_income': plan_term.customer_monthly_income,
                        'payment_capacity_factor': plan_term.payment_capacity_factor,
                        'maximum_allowed_installment': plan_term.maximum_allowed_installment,
                        'installment_to_income_ratio': plan_term.installment_to_income_ratio,
                        'payment_capacity_passed': plan_term.payment_capacity_passed,
                        'conditions_met': plan_term.conditions_met,
                        'requires_adjustment': plan_term.requires_adjustment,
                        'adjustment_notes': plan_term.adjustment_notes,
                        'final_score': plan_term.final_score,
                        'score_status': plan_term.score_status,
                    }
                )
                saved_plans.append(finance_plan)

            # Serialize and return all saved plans
            serializer = FinancePlanSerializer(saved_plans, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error retrieving and saving Finance Plans: {str(e)}")
            return Response(
                {"detail": "Internal server error while fetching and saving finance plans."},
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

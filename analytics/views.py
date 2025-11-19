"""
Analytics API Views with Role-Based Access Control
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Avg, Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from .models import (
    SalesAnalytics, ApplicationFunnelAnalytics, DeviceEnrollmentAnalytics,
    BrandModelAnalytics, GeographicAnalytics, FPDAnalytics,
    FinancialMetrics, StoreRetentionAnalytics, ClerkPerformanceAnalytics,
    HourlyAnalytics
)
from .serializers import (
    SalesAnalyticsSerializer, ApplicationFunnelSerializer,
    DeviceEnrollmentSerializerAnalytics, BrandModelAnalyticsSerializer,
    GeographicAnalyticsSerializer, FPDAnalyticsSerializer,
    FinancialMetricsSerializer, StoreRetentionSerializer,
    ClerkPerformanceSerializer, HourlyAnalyticsSerializer,
    DashboardOverviewSerializer, TopPerformerSerializer
)
from .permissions import AnalyticsPermission


class BaseAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """Base viewset with common filtering logic"""
    permission_classes = [IsAuthenticated, AnalyticsPermission]
    
    def get_date_range(self, request):
        """Extract date range from query params"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        period = request.query_params.get('period', 'month')  # day, week, month, quarter, year
        
        if not end_date:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        if not start_date:
            if period == 'day':
                start_date = end_date - timedelta(days=30)
            elif period == 'week':
                start_date = end_date - timedelta(weeks=12)
            elif period == 'month':
                start_date = end_date - timedelta(days=365)
            elif period == 'quarter':
                start_date = end_date - timedelta(days=365)
            elif period == 'year':
                start_date = end_date - timedelta(days=730)
            else:
                start_date = end_date - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        
        return start_date, end_date
    
    def filter_by_role(self, queryset, user):
        """Filter queryset based on user role"""
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            # Full access to all data
            return queryset
        
        elif user.role == 'sales_advisor':
            # Access to region data
            if user.store and user.store.region:
                store_ids = user.store.region.stores.values_list('id', flat=True)
                return queryset.filter(store_id__in=store_ids)
            return queryset.none()
        
        elif user.role == 'store_manager':
            # Access to own store data
            if user.store:
                return queryset.filter(store=user.store)
            return queryset.none()
        
        elif user.role == 'salesperson':
            # Access to own data only
            return queryset.filter(salesperson=user)
        
        return queryset.none()


class SalesAnalyticsViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for sales analytics
    
    Supports filtering by:
    - Date range (start_date, end_date)
    - Store
    - Salesperson
    - Period granularity (day, week, month, quarter, year)
    """
    queryset = SalesAnalytics.objects.all()
    serializer_class = SalesAnalyticsSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Apply role-based filtering
        queryset = self.filter_by_role(queryset, user)
        
        # Apply date filtering
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        # Additional filters
        store_id = self.request.query_params.get('store')
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        
        salesperson_id = self.request.query_params.get('salesperson')
        if salesperson_id:
            queryset = queryset.filter(salesperson_id=salesperson_id)
        
        return queryset.order_by('-date')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Get summary statistics for the period
        
        Returns:
        - total_sales
        - total_amount
        - avg_metrics
        - trend (vs previous period)
        """
        queryset = self.get_queryset()
        
        summary = queryset.aggregate(
            total_sales=Sum('total_sales'),
            total_amount=Sum('total_sales_amount'),
            avg_retail_price=Avg('avg_retail_price'),
            avg_finance_amount=Avg('avg_finance_amount'),
            avg_down_payment=Avg('avg_down_payment_pct'),
            active_stores=Sum('active_stores_count')
        )
        
        return Response(summary)
    
    @action(detail=False, methods=['get'])
    def trend(self, request):
        """
        Get sales trend over time with period grouping
        """
        queryset = self.get_queryset()
        period = request.query_params.get('period', 'month')
        
        # Group by period
        if period == 'day':
            trend_data = queryset.values('date').annotate(
                sales=Sum('total_sales'),
                amount=Sum('total_sales_amount')
            ).order_by('date')
        else:
            # For week/month/quarter/year, aggregate accordingly
            trend_data = queryset.values('date').annotate(
                sales=Sum('total_sales'),
                amount=Sum('total_sales_amount')
            ).order_by('date')
        
        return Response(trend_data)


class ApplicationFunnelViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for application funnel analytics
    
    Tracks:
    - Applications → KYC → Approved → Sales
    - Conversion rates at each stage
    """
    queryset = ApplicationFunnelAnalytics.objects.all()
    serializer_class = ApplicationFunnelSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        queryset = self.filter_by_role(queryset, user)
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        store_id = self.request.query_params.get('store')
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        
        return queryset.order_by('-date')
    
    @action(detail=False, methods=['get'])
    def funnel_summary(self, request):
        """
        Get overall funnel conversion rates
        """
        queryset = self.get_queryset()
        
        summary = queryset.aggregate(
            total_applications=Sum('applications'),
            total_kyc=Sum('kyc_completed'),
            total_approved=Sum('approved'),
            total_sales=Sum('sales'),
            avg_approval_rate=Avg('approval_rate'),
            avg_take_rate=Avg('take_rate'),
            avg_conversion_rate=Avg('conversion_rate')
        )
        
        # Calculate overall conversion rates
        if summary['total_applications'] and summary['total_applications'] > 0:
            summary['overall_kyc_rate'] = round(
                (summary['total_kyc'] / summary['total_applications']) * 100, 2
            )
            summary['overall_approval_rate'] = round(
                (summary['total_approved'] / summary['total_applications']) * 100, 2
            )
            summary['overall_conversion_rate'] = round(
                (summary['total_sales'] / summary['total_applications']) * 100, 2
            )
        
        return Response(summary)


class DeviceEnrollmentViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for device enrollment analytics
    
    Tracks device locks by type
    """
    queryset = DeviceEnrollmentAnalytics.objects.all()
    serializer_class = DeviceEnrollmentSerializerAnalytics
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        queryset = self.filter_by_role(queryset, user)
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        return queryset.order_by('-date')
    
    @action(detail=False, methods=['get'])
    def lock_distribution(self, request):
        """
        Get overall lock type distribution
        """
        queryset = self.get_queryset()
        
        totals = queryset.aggregate(
            base_android=Sum('lock_base_android'),
            android_dlc=Sum('lock_android_dlc'),
            kpe=Sum('lock_kpe'),
            kg=Sum('lock_kg'),
            base_android_frp=Sum('lock_base_android_frp'),
            access=Sum('lock_access'),
            total=Sum('total_devices_enrolled')
        )
        
        if totals['total'] and totals['total'] > 0:
            distribution = {
                'BASEANDROID': {
                    'count': totals['base_android'] or 0,
                    'percentage': round((totals['base_android'] or 0) / totals['total'] * 100, 2)
                },
                'ANDROID_DLC': {
                    'count': totals['android_dlc'] or 0,
                    'percentage': round((totals['android_dlc'] or 0) / totals['total'] * 100, 2)
                },
                'KPE': {
                    'count': totals['kpe'] or 0,
                    'percentage': round((totals['kpe'] or 0) / totals['total'] * 100, 2)
                },
                'KG': {
                    'count': totals['kg'] or 0,
                    'percentage': round((totals['kg'] or 0) / totals['total'] * 100, 2)
                },
                'BASEANDROID_FRP': {
                    'count': totals['base_android_frp'] or 0,
                    'percentage': round((totals['base_android_frp'] or 0) / totals['total'] * 100, 2)
                },
                'ACCESS': {
                    'count': totals['access'] or 0,
                    'percentage': round((totals['access'] or 0) / totals['total'] * 100, 2)
                }
            }
            return Response({'total': totals['total'], 'distribution': distribution})
        
        return Response({'total': 0, 'distribution': {}})


class BrandModelAnalyticsViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for brand and model sales analytics
    """
    queryset = BrandModelAnalytics.objects.all()
    serializer_class = BrandModelAnalyticsSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        queryset = self.filter_by_role(queryset, user)
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        brand = self.request.query_params.get('brand')
        if brand:
            queryset = queryset.filter(brand_name__icontains=brand)
        
        return queryset.order_by('-sales_count')
    
    @action(detail=False, methods=['get'])
    def top_brands(self, request):
        """
        Get top performing brands
        """
        limit = int(request.query_params.get('limit', 10))
        queryset = self.get_queryset()
        
        top_brands = queryset.values('brand_name').annotate(
            total_sales=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-total_sales')[:limit]
        
        return Response(top_brands)
    
    @action(detail=False, methods=['get'])
    def top_models(self, request):
        """
        Get top performing models
        """
        limit = int(request.query_params.get('limit', 10))
        queryset = self.get_queryset()
        
        top_models = queryset.values('brand_name', 'model_name').annotate(
            total_sales=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-total_sales')[:limit]
        
        return Response(top_models)


class GeographicAnalyticsViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for geographic sales analytics
    """
    queryset = GeographicAnalytics.objects.all()
    serializer_class = GeographicAnalyticsSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Apply role-based filtering
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            pass  # Full access
        elif user.role == 'sales_advisor' and user.store:
            queryset = queryset.filter(region=user.store.region)
        else:
            queryset = queryset.none()
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        return queryset.order_by('-sales_count')
    
    @action(detail=False, methods=['get'])
    def by_region(self, request):
        """Sales by region"""
        queryset = self.get_queryset()
        
        by_region = queryset.values('region__name').annotate(
            total_sales=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-total_sales')
        
        return Response(by_region)
    
    @action(detail=False, methods=['get'])
    def by_province(self, request):
        """Sales by province"""
        queryset = self.get_queryset()
        
        by_province = queryset.values('province_name').annotate(
            total_sales=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-total_sales')
        
        return Response(by_province)


class FPDAnalyticsViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for First Payment Default analytics
    """
    queryset = FPDAnalytics.objects.all()
    serializer_class = FPDAnalyticsSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        queryset = self.filter_by_role(queryset, user)
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        return queryset.order_by('-date')
    
    @action(detail=False, methods=['get'])
    def fpd_summary(self, request):
        """
        Get average FPD rates
        """
        queryset = self.get_queryset()
        
        summary = queryset.aggregate(
            avg_fpd_3=Avg('fpd_3_rate'),
            avg_fpd_7=Avg('fpd_7_rate'),
            avg_fpd_15=Avg('fpd_15_rate'),
            avg_early_inactive=Avg('early_inactive_rate'),
            avg_pay_40_60=Avg('pay_40_at_60_rate'),
            total_contracts=Sum('total_contracts')
        )
        
        return Response(summary)


class FinancialMetricsViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for financial metrics
    """
    queryset = FinancialMetrics.objects.all()
    serializer_class = FinancialMetricsSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        queryset = self.filter_by_role(queryset, user)
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        return queryset.order_by('-date')
    
    @action(detail=False, methods=['get'])
    def financial_summary(self, request):
        """
        Get financial performance summary
        """
        queryset = self.get_queryset()
        
        summary = queryset.aggregate(
            total_revenue=Sum('total_revenue'),
            total_financed=Sum('total_financed_amount'),
            total_down_payment=Sum('total_down_payment'),
            collections=Sum('collections_received'),
            outstanding=Sum('outstanding_amount'),
            avg_multiple=Avg('avg_multiple'),
            avg_term=Avg('avg_term_months')
        )
        
        # Calculate collection rate
        if summary['total_financed'] and summary['total_financed'] > 0:
            summary['collection_rate'] = round(
                (summary['collections'] / summary['total_financed']) * 100, 2
            )
        
        return Response(summary)


class ClerkPerformanceViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for salesperson performance analytics
    """
    queryset = ClerkPerformanceAnalytics.objects.all()
    serializer_class = ClerkPerformanceSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.role == 'salesperson':
            # Salesperson can only see their own performance
            queryset = queryset.filter(salesperson=user)
        else:
            queryset = self.filter_by_role(queryset, user)
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        return queryset.order_by('-total_sales')
    
    @action(detail=False, methods=['get'])
    def leaderboard(self, request):
        """
        Get salesperson leaderboard
        """
        limit = int(request.query_params.get('limit', 20))
        queryset = self.get_queryset()
        
        leaderboard = queryset.values(
            'salesperson__first_name',
            'salesperson__last_name',
            'store__name'
        ).annotate(
            total_sales=Sum('total_sales'),
            total_amount=Sum('total_sales_amount'),
            avg_approval_rate=Avg('approval_rate')
        ).order_by('-total_sales')[:limit]
        
        # Add rank
        for idx, item in enumerate(leaderboard, 1):
            item['rank'] = idx
        
        return Response(leaderboard)


class HourlyAnalyticsViewSet(BaseAnalyticsViewSet):
    """
    API endpoints for hourly sales pattern analytics
    """
    queryset = HourlyAnalytics.objects.all()
    serializer_class = HourlyAnalyticsSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        queryset = self.filter_by_role(queryset, user)
        
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        return queryset.order_by('hour')
    
    @action(detail=False, methods=['get'])
    def by_hour(self, request):
        """
        Sales distribution by hour of day
        """
        queryset = self.get_queryset()
        
        by_hour = queryset.values('hour').annotate(
            total_sales=Sum('sales_count')
        ).order_by('hour')
        
        return Response(by_hour)
    
    @action(detail=False, methods=['get'])
    def by_day_of_week(self, request):
        """
        Sales distribution by day of week
        """
        queryset = self.get_queryset()
        
        by_day = queryset.values('day_of_week').annotate(
            total_sales=Sum('sales_count')
        ).order_by('day_of_week')
        
        return Response(by_day)


class DashboardOverviewViewSet(viewsets.ViewSet):
    """
    Consolidated dashboard overview
    """
    permission_classes = [IsAuthenticated, AnalyticsPermission]
    
    def list(self, request):
        """
        Get complete dashboard overview
        """
        user = request.user
        start_date, end_date = self._get_date_range(request)
        
        # Build base querysets with role filtering
        sales_qs = self._filter_by_role(SalesAnalytics.objects.all(), user)
        funnel_qs = self._filter_by_role(ApplicationFunnelAnalytics.objects.all(), user)
        fpd_qs = self._filter_by_role(FPDAnalytics.objects.all(), user)
        financial_qs = self._filter_by_role(FinancialMetrics.objects.all(), user)
        
        # Apply date filters
        sales_qs = sales_qs.filter(date__range=[start_date, end_date])
        funnel_qs = funnel_qs.filter(date__range=[start_date, end_date])
        fpd_qs = fpd_qs.filter(date__range=[start_date, end_date])
        financial_qs = financial_qs.filter(date__range=[start_date, end_date])
        
        # Aggregate metrics
        overview = {
            'period_start': start_date,
            'period_end': end_date,
            
            # Sales metrics
            'total_sales': sales_qs.aggregate(Sum('total_sales'))['total_sales__sum'] or 0,
            'total_sales_amount': sales_qs.aggregate(Sum('total_sales_amount'))['total_sales_amount__sum'] or Decimal('0.00'),
            'active_stores': sales_qs.values('store').distinct().count(),
            
            # Funnel metrics
            'total_applications': funnel_qs.aggregate(Sum('applications'))['applications__sum'] or 0,
            'avg_approval_rate': funnel_qs.aggregate(Avg('approval_rate'))['approval_rate__avg'] or Decimal('0.00'),
            'avg_conversion_rate': funnel_qs.aggregate(Avg('conversion_rate'))['conversion_rate__avg'] or Decimal('0.00'),
            
            # FPD metrics
            'avg_fpd_3': fpd_qs.aggregate(Avg('fpd_3_rate'))['fpd_3_rate__avg'] or Decimal('0.00'),
            'avg_fpd_7': fpd_qs.aggregate(Avg('fpd_7_rate'))['fpd_7_rate__avg'] or Decimal('0.00'),
            'avg_fpd_15': fpd_qs.aggregate(Avg('fpd_15_rate'))['fpd_15_rate__avg'] or Decimal('0.00'),
            
            # Financial metrics
            'total_financed_amount': financial_qs.aggregate(Sum('total_financed_amount'))['total_financed_amount__sum'] or Decimal('0.00'),
            'collections_received': financial_qs.aggregate(Sum('collections_received'))['collections_received__sum'] or Decimal('0.00'),
        }
        
        serializer = DashboardOverviewSerializer(overview)
        return Response(serializer.data)
    
    def _get_date_range(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if not end_date:
            end_date = timezone.now().date()
        else:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        if not start_date:
            start_date = end_date - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        
        return start_date, end_date
    
    def _filter_by_role(self, queryset, user):
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            return queryset
        elif user.role == 'sales_advisor' and user.store:
            store_ids = user.store.region.stores.values_list('id', flat=True)
            return queryset.filter(store_id__in=store_ids)
        elif user.role == 'store_manager' and user.store:
            return queryset.filter(store=user.store)
        elif user.role == 'salesperson':
            return queryset.filter(salesperson=user)
        return queryset.none()
    

# chart analytics 


"""
Django REST Framework Views for Analytics Dashboard
File: analytics/views.py

Role-Based Access Control:
- Admin/Global Manager/Financial Manager: All data across country
- Sales Advisor: Data for their assigned region
- Store Manager: Data for their store only
- Salesperson: Only their own sales data
"""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Avg, Count, Q, F
from django.utils import timezone
from datetime import timedelta, datetime
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import (
    DailyFinanceMetrics,
    BrandPerformanceMetrics,
    ProductPerformanceMetrics,
    SalespersonPerformance,
    PaymentCollectionMetrics,
    RiskAnalysisMetrics,
    GeographicPerformanceMetrics,
    DeviceLockPerformanceMetrics,
    MetricsAggregator
)
from .serializers import (
    DailyFinanceMetricsSerializer,
    BrandPerformanceMetricsSerializer,
    ProductPerformanceMetricsSerializer,
    SalespersonPerformanceSerializer,
    PaymentCollectionMetricsSerializer,
    RiskAnalysisMetricsSerializer,
    GeographicPerformanceMetricsSerializer,
    DeviceLockPerformanceMetricsSerializer,
    DashboardSummarySerializer,
    AnalyticsFilterSerializer
)
from finance.models import FinancePlan, PaymentRecord, EMISchedule
from customer.models import Customer, CreditApplication
from store.models import Store


# ========================================
# BASE ANALYTICS VIEWSET WITH RBAC
# ========================================

class BaseAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Base viewset with role-based access control
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    
    def get_queryset(self):
        """
        Filter queryset based on user role
        """
        user = self.request.user
        queryset = super().get_queryset()
        
        # Admin, Global Manager, Financial Manager: See all data
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            return queryset
        
        # Sales Advisor: See region data
        elif user.role == 'sales_advisor':
            # Get stores assigned to this sales advisor
            advised_stores = Store.objects.filter(sales_advisor=user)
            return queryset.filter(
                Q(store__in=advised_stores) | Q(region__stores__in=advised_stores)
            ).distinct()
        
        # Store Manager: See their store data only
        elif user.role == 'store_manager':
            return queryset.filter(store=user.store)
        
        # Salesperson: See only their own data
        elif user.role == 'salesperson':
            return queryset.filter(created_by=user)
        
        # Default: No access
        return queryset.none()
    
    def apply_date_filters(self, queryset):
        """
        Apply date range filters from query params
        """
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        return queryset


# ========================================
# DAILY FINANCE METRICS VIEWSET
# ========================================

class DailyFinanceMetricsViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for daily finance metrics
    
    Provides aggregated daily financial data with filtering and time-series analysis
    """
    queryset = DailyFinanceMetrics.objects.all()
    serializer_class = DailyFinanceMetricsSerializer
    ordering_fields = ['date', 'total_sales_value', 'approval_rate']
    
    @swagger_auto_schema(
        operation_description="Get daily finance metrics with date range filtering",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date'),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='date'),
            openapi.Parameter('store_id', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='uuid'),
            openapi.Parameter('region_id', openapi.IN_QUERY, type=openapi.TYPE_STRING, format='uuid'),
        ]
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        # Additional filters
        store_id = request.query_params.get('store_id')
        region_id = request.query_params.get('region_id')
        
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        if region_id:
            queryset = queryset.filter(region_id=region_id)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_description="Get time-series trend data for charts",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, required=True, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, required=True, type=openapi.TYPE_STRING),
            openapi.Parameter('granularity', openapi.IN_QUERY, type=openapi.TYPE_STRING, 
                            enum=['day', 'week', 'month'], default='day'),
        ]
    )
    @action(detail=False, methods=['get'])
    def trend(self, request):
        """
        Get trend data for time-series charts
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        granularity = request.query_params.get('granularity', 'day')
        
        # Aggregate based on granularity
        if granularity == 'week':
            # Group by week
            trend_data = queryset.extra(
                select={'week': 'EXTRACT(WEEK FROM date)'}
            ).values('week').annotate(
                total_sales=Sum('total_sales_value'),
                total_applications=Sum('total_applications'),
                avg_approval_rate=Avg('approval_rate')
            ).order_by('week')
        elif granularity == 'month':
            # Group by month
            trend_data = queryset.extra(
                select={'month': 'EXTRACT(MONTH FROM date)'}
            ).values('month').annotate(
                total_sales=Sum('total_sales_value'),
                total_applications=Sum('total_applications'),
                avg_approval_rate=Avg('approval_rate')
            ).order_by('month')
        else:
            # Daily
            trend_data = queryset.values('date').annotate(
                total_sales=Sum('total_sales_value'),
                total_applications=Sum('total_applications'),
                avg_approval_rate=Avg('approval_rate')
            ).order_by('date')
        
        return Response(list(trend_data))
    
    @swagger_auto_schema(
        operation_description="Get summary KPIs for dashboard",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, required=True, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, required=True, type=openapi.TYPE_STRING),
        ]
    )
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Get aggregated summary KPIs
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        summary = queryset.aggregate(
            total_applications=Sum('total_applications'),
            total_approved=Sum('approved_applications'),
            total_sales=Sum('total_sales_value'),
            total_financed=Sum('total_financed_amount'),
            avg_ticket_size=Avg('average_ticket_size'),
            avg_approval_rate=Avg('approval_rate'),
            unique_customers=Sum('unique_customers'),
            tier_a=Sum('tier_a_count'),
            tier_b=Sum('tier_b_count'),
            tier_c=Sum('tier_c_count'),
            tier_d=Sum('tier_d_count'),
        )
        
        return Response(summary)


# ========================================
# BRAND PERFORMANCE VIEWSET
# ========================================

class BrandPerformanceMetricsViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for brand performance metrics
    """
    queryset = BrandPerformanceMetrics.objects.select_related('brand', 'store', 'region')
    serializer_class = BrandPerformanceMetricsSerializer
    ordering_fields = ['date', 'total_revenue', 'total_units_sold']
    
    @swagger_auto_schema(
        operation_description="Get top performing brands",
        manual_parameters=[
            openapi.Parameter('limit', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, default=10),
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
        ]
    )
    @action(detail=False, methods=['get'])
    def top_brands(self, request):
        """
        Get top performing brands by revenue
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        limit = int(request.query_params.get('limit', 10))
        
        top_brands = queryset.values('brand__name').annotate(
            total_revenue=Sum('total_revenue'),
            total_units=Sum('total_units_sold')
        ).order_by('-total_revenue')[:limit]
        
        return Response(list(top_brands))


# ========================================
# PRODUCT PERFORMANCE VIEWSET
# ========================================

class ProductPerformanceMetricsViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for product performance metrics
    """
    queryset = ProductPerformanceMetrics.objects.select_related('product', 'store', 'region')
    serializer_class = ProductPerformanceMetricsSerializer
    ordering_fields = ['date', 'revenue', 'units_sold']
    
    @swagger_auto_schema(
        operation_description="Get top selling products",
        manual_parameters=[
            openapi.Parameter('limit', openapi.IN_QUERY, type=openapi.TYPE_INTEGER, default=10),
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
        ]
    )
    @action(detail=False, methods=['get'])
    def top_products(self, request):
        """
        Get top selling products by units sold
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        limit = int(request.query_params.get('limit', 10))
        
        top_products = queryset.values(
            'product__ola_code',
            'product__model_name',
            'product__brand__name'
        ).annotate(
            total_units=Sum('units_sold'),
            total_revenue=Sum('revenue')
        ).order_by('-total_units')[:limit]
        
        return Response(list(top_products))


# ========================================
# SALESPERSON PERFORMANCE VIEWSET
# ========================================

class SalespersonPerformanceViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for salesperson performance metrics
    """
    queryset = SalespersonPerformance.objects.select_related('salesperson', 'store')
    serializer_class = SalespersonPerformanceSerializer
    ordering_fields = ['date', 'total_sales', 'approval_rate']
    
    @swagger_auto_schema(
        operation_description="Get salesperson leaderboard",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter('metric', openapi.IN_QUERY, type=openapi.TYPE_STRING,
                            enum=['sales', 'applications', 'approval_rate'], default='sales'),
        ]
    )
    @action(detail=False, methods=['get'])
    def leaderboard(self, request):
        """
        Get salesperson leaderboard
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        metric = request.query_params.get('metric', 'sales')
        
        if metric == 'applications':
            order_by = '-applications_created'
            aggregate_field = 'applications_created'
        elif metric == 'approval_rate':
            order_by = '-approval_rate'
            aggregate_field = 'approval_rate'
        else:
            order_by = '-total_sales'
            aggregate_field = 'total_sales'
        
        leaderboard = queryset.values(
            'salesperson__first_name',
            'salesperson__last_name',
            'salesperson__email',
            'store__name'
        ).annotate(
            total_metric=Sum(aggregate_field) if metric != 'approval_rate' else Avg(aggregate_field)
        ).order_by(order_by)[:20]
        
        return Response(list(leaderboard))


# ========================================
# PAYMENT COLLECTION VIEWSET
# ========================================

class PaymentCollectionMetricsViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for payment collection metrics
    """
    queryset = PaymentCollectionMetrics.objects.all()
    serializer_class = PaymentCollectionMetricsSerializer
    ordering_fields = ['date', 'collection_rate', 'total_collected']
    
    @swagger_auto_schema(
        operation_description="Get payment method distribution",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
        ]
    )
    @action(detail=False, methods=['get'])
    def payment_methods(self, request):
        """
        Get distribution of payment methods
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        payment_methods = queryset.aggregate(
            cash=Sum('cash_collected'),
            yappy=Sum('yappy_collected'),
            punto_pago=Sum('punto_pago_collected'),
            western_union=Sum('western_union_collected'),
            bank_transfer=Sum('bank_transfer_collected'),
        )
        
        return Response(payment_methods)
    
    @swagger_auto_schema(
        operation_description="Get delinquency analysis",
    )
    @action(detail=False, methods=['get'])
    def delinquency(self, request):
        """
        Get delinquency aging analysis
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        delinquency = queryset.aggregate(
            current_overdue=Sum('accounts_overdue'),
            days_30=Sum('accounts_30_days_overdue'),
            days_60=Sum('accounts_60_days_overdue'),
            days_90_plus=Sum('accounts_90_days_plus_overdue'),
            total_overdue_amount=Sum('total_overdue'),
        )
        
        return Response(delinquency)


# ========================================
# RISK ANALYSIS VIEWSET
# ========================================

class RiskAnalysisMetricsViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for risk analysis metrics
    """
    queryset = RiskAnalysisMetrics.objects.all()
    serializer_class = RiskAnalysisMetricsSerializer
    ordering_fields = ['date', 'default_rate', 'total_portfolio_value']
    
    @swagger_auto_schema(
        operation_description="Get risk tier distribution",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
        ]
    )
    @action(detail=False, methods=['get'])
    def tier_distribution(self, request):
        """
        Get distribution across risk tiers
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        distribution = queryset.values('risk_tier').annotate(
            total_accounts=Sum('total_accounts'),
            total_value=Sum('total_portfolio_value'),
            avg_default_rate=Avg('default_rate')
        ).order_by('risk_tier')
        
        return Response(list(distribution))


# ========================================
# GEOGRAPHIC PERFORMANCE VIEWSET
# ========================================

class GeographicPerformanceMetricsViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for geographic performance metrics
    """
    queryset = GeographicPerformanceMetrics.objects.select_related('region', 'province', 'district')
    serializer_class = GeographicPerformanceMetricsSerializer
    ordering_fields = ['date', 'total_sales', 'approval_rate']
    
    @swagger_auto_schema(
        operation_description="Get regional performance comparison",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, type=openapi.TYPE_STRING),
        ]
    )
    @action(detail=False, methods=['get'])
    def regional_comparison(self, request):
        """
        Compare performance across regions
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        comparison = queryset.values('region__name').annotate(
            total_sales=Sum('total_sales'),
            total_applications=Sum('total_applications'),
            avg_approval_rate=Avg('approval_rate'),
            active_stores=Sum('active_stores')
        ).order_by('-total_sales')
        
        return Response(list(comparison))


# ========================================
# DEVICE LOCK PERFORMANCE VIEWSET
# ========================================

class DeviceLockPerformanceMetricsViewSet(BaseAnalyticsViewSet):
    """
    ViewSet for device lock performance metrics
    """
    queryset = DeviceLockPerformanceMetrics.objects.all()
    serializer_class = DeviceLockPerformanceMetricsSerializer
    ordering_fields = ['date', 'devices_enrolled', 'enrollment_success_rate']
    
    @swagger_auto_schema(
        operation_description="Get lock system comparison",
    )
    @action(detail=False, methods=['get'])
    def system_comparison(self, request):
        """
        Compare performance across lock systems
        """
        queryset = self.get_queryset()
        queryset = self.apply_date_filters(queryset)
        
        comparison = queryset.values('lock_system').annotate(
            total_enrolled=Sum('devices_enrolled'),
            total_locked=Sum('devices_locked'),
            avg_success_rate=Avg('enrollment_success_rate')
        ).order_by('lock_system')
        
        return Response(list(comparison))


# ========================================
# COMPREHENSIVE DASHBOARD VIEWSET
# ========================================

class DashboardViewSet(viewsets.ViewSet):
    """
    Comprehensive dashboard with all metrics combined
    """
    permission_classes = [IsAuthenticated]
    
    @swagger_auto_schema(
        operation_description="Get complete dashboard with all metrics",
        manual_parameters=[
            openapi.Parameter('start_date', openapi.IN_QUERY, required=True, type=openapi.TYPE_STRING),
            openapi.Parameter('end_date', openapi.IN_QUERY, required=True, type=openapi.TYPE_STRING),
        ]
    )
    @action(detail=False, methods=['get'])
    def overview(self, request):
        """
        Get complete dashboard overview
        """
        user = request.user
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if not start_date or not end_date:
            return Response({
                'error': 'start_date and end_date are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Build base filters based on user role
        base_filters = {'created_at__date__gte': start_date, 'created_at__date__lte': end_date}
        
        if user.role == 'salesperson':
            base_filters['created_by'] = user
        elif user.role == 'store_manager':
            base_filters['store'] = user.store
        elif user.role == 'sales_advisor':
            advised_stores = Store.objects.filter(sales_advisor=user)
            base_filters['store__in'] = advised_stores
        
        # Aggregate metrics
        finance_plans = FinancePlan.objects.filter(**base_filters)
        
        dashboard_data = {
            'date_range': {'start': start_date, 'end': end_date},
            'summary': {
                'total_applications': finance_plans.count(),
                'total_sales': finance_plans.aggregate(Sum('device_price'))['device_price__sum'] or 0,
                'total_financed': finance_plans.aggregate(Sum('amount_to_finance'))['amount_to_finance__sum'] or 0,
                'avg_ticket_size': finance_plans.aggregate(Avg('device_price'))['device_price__avg'] or 0,
                'approval_rate': self._calculate_approval_rate(finance_plans),
            },
            'risk_distribution': self._get_risk_distribution(finance_plans),
            'sales_trend': self._get_sales_trend(finance_plans, start_date, end_date),
            'top_brands': self._get_top_brands(finance_plans),
            'top_products': self._get_top_products(finance_plans),
        }
        
        return Response(dashboard_data)
    
    def _calculate_approval_rate(self, queryset):
        total = queryset.count()
        approved = queryset.filter(conditions_met=True).count()
        return (approved / total * 100) if total > 0 else 0
    
    def _get_risk_distribution(self, queryset):
        return {
            'tier_a': queryset.filter(risk_tier='TIER_A').count(),
            'tier_b': queryset.filter(risk_tier='TIER_B').count(),
            'tier_c': queryset.filter(risk_tier='TIER_C').count(),
            'tier_d': queryset.filter(risk_tier='TIER_D').count(),
        }
    
    def _get_sales_trend(self, queryset, start_date, end_date):
        return list(queryset.extra(
            select={'date': 'DATE(created_at)'}
        ).values('date').annotate(
            sales=Sum('device_price'),
            count=Count('id')
        ).order_by('date'))
    
    def _get_top_brands(self, queryset):
        return list(queryset.values(
            'device__brand__name'
        ).annotate(
            units=Count('id'),
            revenue=Sum('device_price')
        ).order_by('-revenue')[:10])
    
    def _get_top_products(self, queryset):
        return list(queryset.values(
            'device__ola_code',
            'device__model_name'
        ).annotate(
            units=Count('id'),
            revenue=Sum('device_price')
        ).order_by('-units')[:10])
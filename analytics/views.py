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
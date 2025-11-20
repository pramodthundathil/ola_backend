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
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from home.models import CustomUser

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
        
        # Filter by brand text search
        brand = self.request.query_params.get('brand')
        if brand:
            queryset = queryset.filter(brand_name__icontains=brand)
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """
        Override list to return all brands with their models in the desired format
        """
        queryset = self.get_queryset()
        
        # Get all unique brands
        brands = queryset.values('brand_id', 'brand_name').distinct()
        
        response_data = []
        
        for brand in brands:
            brand_id = brand['brand_id']
            brand_name = brand['brand_name']
            
            # Filter data for this brand
            brand_queryset = queryset.filter(brand_id=brand_id)
            
            # Get totals
            totals = brand_queryset.aggregate(
                total_sales_count=Sum('sales_count'),
                total_revenue=Sum('total_amount')
            )
            
            # Get models for this brand
            models = brand_queryset.values(
                'device_id', 
                'device__model_name',
                'model_name'
            ).annotate(
                sales_count=Sum('sales_count'),
                total_amount=Sum('total_amount')
            ).order_by('-sales_count')
            
            models_list = [
                {
                    "device_id": model['device_id'],
                    "device_name": model['device__model_name'],
                    "model_name": model['model_name'],
                    "units_sold": model['sales_count'],
                    "sales_amount": float(model['total_amount'])
                }
                for model in models
            ]
            
            response_data.append({
                'brand_id': brand_id,
                'brand': brand_name,
                'summary': {
                    'total_units_sold': totals['total_sales_count'] or 0,
                    'total_sales_amount': float(totals['total_revenue'] or 0),
                    'total_models_sold': len(models_list)
                },
                'models': models_list
            })
        
        return Response(response_data)
    
    @swagger_auto_schema(
        operation_summary="Get sales data for a specific brand",
        operation_description="""
        Returns comprehensive sales analytics for a brand including:
        - Total sales metrics (count, revenue, averages)
        - Device-wise breakdown
        - Store-wise breakdown
        - Time series data for charts
        """,
        manual_parameters=[
            openapi.Parameter(
                'brand_id',
                openapi.IN_QUERY,
                description="Brand ID (required)",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'start_date',
                openapi.IN_QUERY,
                description="Start date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
            openapi.Parameter(
                'end_date',
                openapi.IN_QUERY,
                description="End date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
        ],
        responses={
            200: openapi.Response(
                description="Successful response",
                examples={
                    "application/json": {
                        "brand_id": "5",
                        "totals": {
                            "total_sales_count": 150,
                            "total_revenue": "450000.00",
                            "avg_sale_amount": "3000.00",
                            "total_stores": 5,
                            "total_devices": 8
                        },
                        "device_breakdown": [
                            {
                                "device_id": 10,
                                "model_name": "iPhone 15 Pro",
                                "sales_count": 50,
                                "total_amount": "150000.00",
                                "avg_amount": "3000.00"
                            }
                        ],
                        "store_breakdown": [
                            {
                                "store_id": 1,
                                "store__name": "Downtown Store",
                                "sales_count": 30,
                                "total_amount": "90000.00"
                            }
                        ],
                        "chart_data": {
                            "time_series": [
                                {
                                    "date": "2024-01-01",
                                    "sales_count": 10,
                                    "total_amount": "30000.00"
                                }
                            ],
                            "device_time_series": [
                                {
                                    "date": "2024-01-01",
                                    "device_id": 10,
                                    "model_name": "iPhone 15 Pro",
                                    "sales_count": 5,
                                    "total_amount": "15000.00"
                                }
                            ]
                        }
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request - brand_id missing",
                examples={
                    "application/json": {
                        "error": "brand_id is required"
                    }
                }
            )
        }
    )
    @action(detail=False, methods=['get'])
    def brand_sales(self, request):
        """
        Get sales data for a specific brand with device breakdown
        Query params: brand_id (required), start_date, end_date
        """
        brand_id = request.query_params.get('brand_id')
        if not brand_id:
            return Response({'error': 'brand_id is required'}, status=400)
        
        queryset = self.get_queryset().filter(brand_id=brand_id)
        
        # Total aggregations
        totals = queryset.aggregate(
            total_sales_count=Sum('sales_count'),
            total_revenue=Sum('total_amount'),
            total_stores=Count('store', distinct=True),
            total_devices=Count('device', distinct=True)
        )
        
        # Calculate average manually
        if totals['total_sales_count'] and totals['total_sales_count'] > 0:
            totals['avg_sale_amount'] = totals['total_revenue'] / totals['total_sales_count']
        else:
            totals['avg_sale_amount'] = Decimal('0.00')
        
        # Device-wise breakdown
        device_breakdown = queryset.values(
            'device_id', 'model_name'
        ).annotate(
            sales_count=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-sales_count')
        
        # Add average calculation to each device
        device_breakdown_list = list(device_breakdown)
        for device in device_breakdown_list:
            if device['sales_count'] > 0:
                device['avg_amount'] = device['total_amount'] / device['sales_count']
            else:
                device['avg_amount'] = Decimal('0.00')
        
        # Store-wise breakdown
        store_breakdown = queryset.values(
            'store_id', 'store__name'
        ).annotate(
            sales_count=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-sales_count')
        
        # Time series data for charts (daily)
        time_series = queryset.values('date').annotate(
            sales_count=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('date')
        
        # Device sales trend (for stacked chart)
        device_time_series = queryset.values(
            'date', 'device_id', 'model_name'
        ).annotate(
            sales_count=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('date', '-sales_count')
        
        # Get brand name
        brand_name = queryset.first().brand_name if queryset.exists() else "Unknown"
        
        # Format models list
        models_list = [
            {
                "model_name": device['model_name'],
                "model_id": device['id'],
                "units_sold": device['sales_count'],
                "sales_amount": float(device['total_amount'])
            }
            for device in device_breakdown_list
        ]
        
        return Response({
            'brand': brand_name,
            'summary': {
                'total_units_sold': totals['total_sales_count'] or 0,
                'total_sales_amount': float(totals['total_revenue'] or 0),
                'total_models_sold': len(device_breakdown_list)
            },
            'models': models_list
        })
    
    @swagger_auto_schema(
        operation_summary="Get sales data for a specific device/model",
        operation_description="""
        Returns comprehensive sales analytics for a specific device model including:
        - Total sales metrics (count, revenue, averages)
        - Store-wise breakdown
        - Time series data for charts
        - Store performance trends over time
        """,
        manual_parameters=[
            openapi.Parameter(
                'device_id',
                openapi.IN_QUERY,
                description="Device ID (required)",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
            openapi.Parameter(
                'start_date',
                openapi.IN_QUERY,
                description="Start date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
            openapi.Parameter(
                'end_date',
                openapi.IN_QUERY,
                description="End date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
        ],
        responses={
            200: openapi.Response(
                description="Successful response",
                examples={
                    "application/json": {
                        "device_id": "10",
                        "totals": {
                            "total_sales_count": 75,
                            "total_revenue": "225000.00",
                            "avg_sale_amount": "3000.00",
                            "total_stores": 3
                        },
                        "store_breakdown": [
                            {
                                "store_id": 1,
                                "store__name": "Downtown Store",
                                "sales_count": 30,
                                "total_amount": "90000.00",
                                "avg_amount": "3000.00"
                            },
                            {
                                "store_id": 2,
                                "store__name": "Mall Store",
                                "sales_count": 25,
                                "total_amount": "75000.00",
                                "avg_amount": "3000.00"
                            }
                        ],
                        "chart_data": {
                            "time_series": [
                                {
                                    "date": "2024-01-01",
                                    "sales_count": 5,
                                    "total_amount": "15000.00"
                                },
                                {
                                    "date": "2024-01-02",
                                    "sales_count": 8,
                                    "total_amount": "24000.00"
                                }
                            ],
                            "store_time_series": [
                                {
                                    "date": "2024-01-01",
                                    "store_id": 1,
                                    "store__name": "Downtown Store",
                                    "sales_count": 3,
                                    "total_amount": "9000.00"
                                },
                                {
                                    "date": "2024-01-01",
                                    "store_id": 2,
                                    "store__name": "Mall Store",
                                    "sales_count": 2,
                                    "total_amount": "6000.00"
                                }
                            ]
                        }
                    }
                }
            ),
            400: openapi.Response(
                description="Bad request - device_id missing",
                examples={
                    "application/json": {
                        "error": "device_id is required"
                    }
                }
            )
        }
    )
    @action(detail=False, methods=['get'])
    def device_sales(self, request):
        """
        Get sales data for a specific device/model
        Query params: device_id (required), start_date, end_date
        """
        device_id = request.query_params.get('device_id')
        if not device_id:
            return Response({'error': 'device_id is required'}, status=400)
        
        queryset = self.get_queryset().filter(device_id=device_id)
        
        # Total aggregations
        totals = queryset.aggregate(
            total_sales_count=Sum('sales_count'),
            total_revenue=Sum('total_amount'),
            total_stores=Count('store', distinct=True)
        )
        
        # Calculate average manually
        if totals['total_sales_count'] and totals['total_sales_count'] > 0:
            totals['avg_sale_amount'] = totals['total_revenue'] / totals['total_sales_count']
        else:
            totals['avg_sale_amount'] = Decimal('0.00')
        
        # Store-wise breakdown
        store_breakdown = queryset.values(
            'store_id', 'store__name'
        ).annotate(
            sales_count=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-sales_count')
        
        # Add average calculation to each store
        store_breakdown_list = list(store_breakdown)
        for store in store_breakdown_list:
            if store['sales_count'] > 0:
                store['avg_amount'] = store['total_amount'] / store['sales_count']
            else:
                store['avg_amount'] = Decimal('0.00')
        
        # Time series data for charts (daily)
        time_series = queryset.values('date').annotate(
            sales_count=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('date')
        
        # Store performance over time (for multi-line chart)
        store_time_series = queryset.values(
            'date', 'store_id', 'store__name'
        ).annotate(
            sales_count=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('date', '-sales_count')
        
        return Response({
            'device_id': device_id,
            'totals': totals,
            'store_breakdown': store_breakdown_list,
            'chart_data': {
                'time_series': list(time_series),
                'store_time_series': list(store_time_series)
            }
        })
    
    @swagger_auto_schema(
        operation_summary="Get top performing brands",
        operation_description="""
        Returns a list of top performing brands ranked by total sales count.
        Includes sales count, total revenue, and average sale amount.
        """,
        manual_parameters=[
            openapi.Parameter(
                'limit',
                openapi.IN_QUERY,
                description="Number of top brands to return (default: 10)",
                type=openapi.TYPE_INTEGER,
                required=False,
                default=10
            ),
            openapi.Parameter(
                'start_date',
                openapi.IN_QUERY,
                description="Start date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
            openapi.Parameter(
                'end_date',
                openapi.IN_QUERY,
                description="End date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
        ],
        responses={
            200: openapi.Response(
                description="List of top performing brands",
                examples={
                    "application/json": [
                        {
                            "brand_id": 5,
                            "brand_name": "Apple",
                            "total_sales": 150,
                            "total_amount": "450000.00",
                            "avg_amount": "3000.00"
                        },
                        {
                            "brand_id": 3,
                            "brand_name": "Samsung",
                            "total_sales": 120,
                            "total_amount": "360000.00",
                            "avg_amount": "3000.00"
                        }
                    ]
                }
            )
        }
    )
    @action(detail=False, methods=['get'])
    def top_brands(self, request):
        """
        Get top performing brands
        """
        limit = int(request.query_params.get('limit', 10))
        queryset = self.get_queryset()
        
        top_brands = queryset.values('brand_id', 'brand_name').annotate(
            total_sales=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-total_sales')[:limit]
        
        # Add average calculation
        top_brands_list = list(top_brands)
        for brand in top_brands_list:
            if brand['total_sales'] > 0:
                brand['avg_amount'] = brand['total_amount'] / brand['total_sales']
            else:
                brand['avg_amount'] = Decimal('0.00')
        
        return Response(top_brands_list)
    
    @swagger_auto_schema(
        operation_summary="Get top performing device models",
        operation_description="""
        Returns a list of top performing device models ranked by total sales count.
        Includes brand information, sales count, total revenue, and average sale amount.
        """,
        manual_parameters=[
            openapi.Parameter(
                'limit',
                openapi.IN_QUERY,
                description="Number of top models to return (default: 10)",
                type=openapi.TYPE_INTEGER,
                required=False,
                default=10
            ),
            openapi.Parameter(
                'start_date',
                openapi.IN_QUERY,
                description="Start date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
            openapi.Parameter(
                'end_date',
                openapi.IN_QUERY,
                description="End date (YYYY-MM-DD)",
                type=openapi.TYPE_STRING,
                format=openapi.FORMAT_DATE,
                required=False
            ),
        ],
        responses={
            200: openapi.Response(
                description="List of top performing device models",
                examples={
                    "application/json": [
                        {
                            "device_id": 10,
                            "brand_id": 5,
                            "brand_name": "Apple",
                            "model_name": "iPhone 15 Pro",
                            "total_sales": 75,
                            "total_amount": "225000.00",
                            "avg_amount": "3000.00"
                        },
                        {
                            "device_id": 8,
                            "brand_id": 3,
                            "brand_name": "Samsung",
                            "model_name": "Galaxy S24 Ultra",
                            "total_sales": 60,
                            "total_amount": "180000.00",
                            "avg_amount": "3000.00"
                        }
                    ]
                }
            )
        }
    )
    @action(detail=False, methods=['get'])
    def top_models(self, request):
        """
        Get top performing models
        """
        limit = int(request.query_params.get('limit', 10))
        queryset = self.get_queryset()
        
        top_models = queryset.values(
            'device_id', 'brand_id', 'brand_name', 'model_name'
        ).annotate(
            total_sales=Sum('sales_count'),
            total_amount=Sum('total_amount')
        ).order_by('-total_sales')[:limit]
        
        # Add average calculation
        top_models_list = list(top_models)
        for model in top_models_list:
            if model['total_sales'] > 0:
                model['avg_amount'] = model['total_amount'] / model['total_sales']
            else:
                model['avg_amount'] = Decimal('0.00')
        
        return Response(top_models_list)



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



class ClerkPerformanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoints for salesperson performance analytics
    """
    queryset = ClerkPerformanceAnalytics.objects.all()
    serializer_class = ClerkPerformanceSerializer
    
    def get_date_range(self, request):
        """Helper to get date range from request"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if not end_date:
            end_date = timezone.now().date()
        else:
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
        
        if not start_date:
            start_date = end_date - timedelta(days=30)
        else:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
        
        return start_date, end_date
    
    def get_queryset(self):
        """
        Filter queryset based on user role
        """
        queryset = ClerkPerformanceAnalytics.objects.select_related(
            'salesperson', 'store'
        )
        user = self.request.user
        
        # Role-based filtering
        if user.role == 'salesperson':
            queryset = queryset.filter(salesperson=user)
        elif user.role == 'store_manager':
            if user.store:
                queryset = queryset.filter(store=user.store)
        elif user.role == 'sales_advisor':
            if user.advised_stores.exists():
                queryset = queryset.filter(store__in=user.advised_stores.all())
        # Global managers, financial managers, and admins see all
        
        # Date range filtering
        start_date, end_date = self.get_date_range(self.request)
        queryset = queryset.filter(date__range=[start_date, end_date])
        
        # Additional filters from query params
        salesperson_id = self.request.query_params.get('salesperson_id')
        store_id = self.request.query_params.get('store_id')
        
        if salesperson_id:
            queryset = queryset.filter(salesperson_id=salesperson_id)
        
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        
        return queryset.order_by('-date', '-total_sales')
    
    def list(self, request, *args, **kwargs):
        """
        Override list to return aggregated data with salesperson details
        """
        queryset = self.get_queryset()
        
        # Group by salesperson
        salesperson_data = {}
        
        for record in queryset:
            sp_id = str(record.salesperson.id)
            
            if sp_id not in salesperson_data:
                salesperson_data[sp_id] = {
                    'salesperson_id': sp_id,
                    'salesperson_name': record.salesperson.get_full_name(),
                    'salesperson_email': record.salesperson.email,
                    'salesperson_phone': record.salesperson.phone or record.salesperson.phone_number,
                    'store_id': str(record.store.id) if record.store else None,
                    'store_name': record.store.name if record.store else None,
                    'store_code': record.store.code if record.store else None,
                    'total_sales': 0,
                    'total_sales_amount': Decimal('0.00'),
                    'total_applications_created': 0,
                    'total_applications_approved': 0,
                    'average_approval_rate': Decimal('0.00'),
                    'records_count': 0,
                    'daily_records': []
                }
            
            # Aggregate totals
            salesperson_data[sp_id]['total_sales'] += record.total_sales
            salesperson_data[sp_id]['total_sales_amount'] += record.total_sales_amount
            salesperson_data[sp_id]['total_applications_created'] += record.applications_created
            salesperson_data[sp_id]['total_applications_approved'] += record.applications_approved
            salesperson_data[sp_id]['records_count'] += 1
            
            # Add daily record
            salesperson_data[sp_id]['daily_records'].append({
                'date': record.date,
                'sales': record.total_sales,
                'sales_amount': record.total_sales_amount,
                'applications_created': record.applications_created,
                'applications_approved': record.applications_approved,
                'approval_rate': record.approval_rate,
                'rank_in_store': record.rank_in_store,
                'rank_overall': record.rank_overall
            })
        
        # Calculate average approval rates
        for sp_id, data in salesperson_data.items():
            if data['records_count'] > 0:
                # Get average approval rate from daily records
                total_approval_rate = sum(
                    record['approval_rate'] 
                    for record in data['daily_records']
                )
                data['average_approval_rate'] = round(
                    total_approval_rate / data['records_count'], 2
                )
        
        # Convert to list and sort by total sales
        result = list(salesperson_data.values())
        result.sort(key=lambda x: x['total_sales'], reverse=True)
        
        # Add overall ranking
        for idx, item in enumerate(result, 1):
            item['overall_rank'] = idx
        
        return Response({
            'count': len(result),
            'results': result
        })
    
    @action(detail=False, methods=['get'], url_path='by-salesperson/(?P<salesperson_id>[^/.]+)')
    def by_salesperson(self, request, salesperson_id=None):
        """
        Get detailed performance for a specific salesperson
        URL: /api/analytics/performance/by-salesperson/{salesperson_id}/
        """
        try:
            salesperson = CustomUser.objects.get(id=salesperson_id, role='salesperson')
        except CustomUser.DoesNotExist:
            return Response(
                {'error': 'Salesperson not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions
        user = request.user
        if user.role == 'salesperson' and user.id != salesperson.id:
            return Response(
                {'error': 'You do not have permission to view this data'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if user.role == 'store_manager' and salesperson.store != user.store:
            return Response(
                {'error': 'You do not have permission to view this data'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get date range
        start_date, end_date = self.get_date_range(request)
        
        # Get analytics records
        records = ClerkPerformanceAnalytics.objects.filter(
            salesperson=salesperson,
            date__range=[start_date, end_date]
        ).order_by('-date')
        
        # Aggregate data
        total_records = records.count()
        aggregated_data = records.aggregate(
            total_sales=Sum('total_sales'),
            total_sales_amount=Sum('total_sales_amount'),
            total_applications_created=Sum('applications_created'),
            total_applications_approved=Sum('applications_approved'),
            avg_approval_rate=Avg('approval_rate')
        )
        
        # Daily breakdown
        daily_records = [
            {
                'date': record.date,
                'sales': record.total_sales,
                'sales_amount': record.total_sales_amount,
                'applications_created': record.applications_created,
                'applications_approved': record.applications_approved,
                'approval_rate': record.approval_rate,
                'rank_in_store': record.rank_in_store,
                'rank_overall': record.rank_overall
            }
            for record in records
        ]
        
        return Response({
            'salesperson': {
                'id': str(salesperson.id),
                'name': salesperson.get_full_name(),
                'email': salesperson.email,
                'phone': salesperson.phone or salesperson.phone_number,
                'employee_id': salesperson.employee_id,
                'commission_rate': salesperson.commission_rate,
            },
            'store': {
                'id': str(salesperson.store.id) if salesperson.store else None,
                'name': salesperson.store.name if salesperson.store else None,
                'code': salesperson.store.code if salesperson.store else None,
            } if salesperson.store else None,
            'period': {
                'start_date': start_date,
                'end_date': end_date,
                'days': total_records
            },
            'summary': {
                'total_sales': aggregated_data['total_sales'] or 0,
                'total_sales_amount': aggregated_data['total_sales_amount'] or Decimal('0.00'),
                'total_applications_created': aggregated_data['total_applications_created'] or 0,
                'total_applications_approved': aggregated_data['total_applications_approved'] or 0,
                'average_approval_rate': aggregated_data['avg_approval_rate'] or Decimal('0.00'),
                'average_daily_sales': round(
                    (aggregated_data['total_sales'] or 0) / total_records, 2
                ) if total_records > 0 else 0,
                'average_daily_amount': round(
                    (aggregated_data['total_sales_amount'] or Decimal('0.00')) / total_records, 2
                ) if total_records > 0 else Decimal('0.00')
            },
            'daily_records': daily_records
        })
    
    @action(detail=False, methods=['get'])
    def leaderboard(self, request):
        """
        Get salesperson leaderboard
        URL: /api/analytics/performance/leaderboard/
        """
        limit = int(request.query_params.get('limit', 20))
        start_date, end_date = self.get_date_range(request)
        
        # Apply role-based filtering
        queryset = ClerkPerformanceAnalytics.objects.filter(
            date__range=[start_date, end_date]
        )
        
        user = request.user
        if user.role == 'store_manager':
            if user.store:
                queryset = queryset.filter(store=user.store)
        elif user.role == 'sales_advisor':
            if user.advised_stores.exists():
                queryset = queryset.filter(store__in=user.advised_stores.all())
        
        # Group by salesperson
        leaderboard = queryset.values(
            'salesperson__id',
            'salesperson__first_name',
            'salesperson__last_name',
            'salesperson__email',
            'salesperson__phone',
            'store__id',
            'store__name',
            'store__code'
        ).annotate(
            total_sales=Sum('total_sales'),
            total_amount=Sum('total_sales_amount'),
            total_applications=Sum('applications_created'),
            total_approved=Sum('applications_approved'),
            avg_approval_rate=Avg('approval_rate')
        ).order_by('-total_sales')[:limit]
        
        # Format response with IDs for navigation
        result = []
        for idx, item in enumerate(leaderboard, 1):
            result.append({
                'rank': idx,
                'salesperson_id': str(item['salesperson__id']),
                'salesperson_name': f"{item['salesperson__first_name']} {item['salesperson__last_name']}".strip(),
                'salesperson_email': item['salesperson__email'],
                'salesperson_phone': item['salesperson__phone'],
                'store_id': str(item['store__id']) if item['store__id'] else None,
                'store_name': item['store__name'],
                'store_code': item['store__code'],
                'total_sales': item['total_sales'],
                'total_amount': item['total_amount'],
                'total_applications': item['total_applications'],
                'total_approved': item['total_approved'],
                'average_approval_rate': round(item['avg_approval_rate'] or 0, 2)
            })
        
        return Response({
            'period': {
                'start_date': start_date,
                'end_date': end_date
            },
            'count': len(result),
            'leaderboard': result
        })
    
    @action(detail=False, methods=['get'])
    def by_store(self, request):
        """
        Get performance grouped by store
        URL: /api/analytics/performance/by-store/
        """
        store_id = request.query_params.get('store_id')
        start_date, end_date = self.get_date_range(request)
        
        queryset = ClerkPerformanceAnalytics.objects.filter(
            date__range=[start_date, end_date]
        )
        
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        
        # Apply role-based filtering
        user = request.user
        if user.role == 'store_manager':
            if user.store:
                queryset = queryset.filter(store=user.store)
        elif user.role == 'sales_advisor':
            if user.advised_stores.exists():
                queryset = queryset.filter(store__in=user.advised_stores.all())
        
        # Group by store
        store_data = queryset.values(
            'store__id',
            'store__name',
            'store__code'
        ).annotate(
            total_salespersons=Count('salesperson', distinct=True),
            total_sales=Sum('total_sales'),
            total_amount=Sum('total_sales_amount'),
            avg_approval_rate=Avg('approval_rate')
        ).order_by('-total_sales')
        
        # Format response
        result = []
        for item in store_data:
            result.append({
                'store_id': str(item['store__id']),
                'store_name': item['store__name'],
                'store_code': item['store__code'],
                'total_salespersons': item['total_salespersons'],
                'total_sales': item['total_sales'],
                'total_amount': item['total_amount'],
                'average_approval_rate': round(item['avg_approval_rate'] or 0, 2)
            })
        
        return Response({
            'period': {
                'start_date': start_date,
                'end_date': end_date
            },
            'count': len(result),
            'stores': result
        })

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
import json
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import (
    DailyAnalytics, MerchantAnalytics, BranchAnalytics, DeviceAnalytics,
    CustomerAnalytics, RiskAnalytics, ExecutiveAnalytics, CollectionAnalytics,
    DashboardSummary
)
from .serializers import (
    DailyAnalyticsSerializer, MerchantAnalyticsSerializer, BranchAnalyticsSerializer,
    DeviceAnalyticsSerializer, CustomerAnalyticsSerializer, RiskAnalyticsSerializer,
    ExecutiveAnalyticsSerializer, CollectionAnalyticsSerializer, DashboardSummarySerializer,
    AnalyticsFilterSerializer, MetricsExportSerializer
)
from .permissions import AnalyticsPermission
from .services import AnalyticsService

logger = logging.getLogger(__name__)


class BaseAnalyticsAPIView(APIView):
    """
    Base API View with common filtering and Redis caching utilities
    """
    permission_classes = [IsAuthenticated, AnalyticsPermission]
    
    def perform_content_negotiation(self, request, force=False):
        # Prevent DRF content negotiation errors when clients pass common parameters like 'format'
        renderers = self.get_renderers()
        return (renderers[0], renderers[0].media_type)
        
    def get_filter_params(self, request):
        serializer = AnalyticsFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        # Set default date range to last 30 days if not provided
        if 'start_date' not in params:
            params['start_date'] = timezone.now().date() - timedelta(days=30)
        if 'end_date' not in params:
            params['end_date'] = timezone.now().date()
            
        return params

    def get_cache_key(self, endpoint_name, params):
        # Convert date objects to strings for the cache key
        param_dict = {}
        for k, v in params.items():
            if isinstance(v, (datetime, timezone.datetime)):
                param_dict[k] = v.strftime('%Y-%m-%d')
            elif hasattr(v, 'isoformat'): # date object
                param_dict[k] = v.isoformat()
            else:
                param_dict[k] = str(v)
        
        sorted_params = sorted(param_dict.items())
        param_str = "-".join([f"{k}:{v}" for k, v in sorted_params])
        return f"analytics:{endpoint_name}:{param_str}"


class KPIsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/kpis
    Returns top-level Executive Summary KPIs.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('kpis', params)
        
        def fetch_data():
            # Query dashboard summary or daily analytics range
            summary = DashboardSummary.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).order_by('-date').first()
            
            if not summary:
                # Return empty default KPIs if no data
                return DashboardSummarySerializer(DashboardSummary(date=params['end_date'])).data
                
            return DashboardSummarySerializer(summary).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class LoanTrendView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/loan-trend
    Returns daily trends of applications, approvals, and disbursement amounts.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('loan-trend', params)
        
        def fetch_data():
            queryset = DailyAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).order_by('date')
            
            return DailyAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class CustomerAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/customer
    Returns customer demographics, lifetime value, and onboarding metrics.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('customer', params)
        
        def fetch_data():
            queryset = CustomerAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).order_by('-date')
            
            # Take the latest demographic distributions in date range
            latest = queryset.first()
            if not latest:
                return {}
                
            return CustomerAnalyticsSerializer(latest).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class CollectionAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/collection
    Returns collection performance, principal/interest breakdown, and overdue amounts.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('collection', params)
        
        def fetch_data():
            queryset = CollectionAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).order_by('date')
            
            return CollectionAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class MerchantAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/merchant
    Returns sales, approvals, and collections by merchants.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('merchant', params)
        
        def fetch_data():
            queryset = MerchantAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).select_related('store').order_by('-date')
            
            if 'merchant' in params:
                queryset = queryset.filter(store_id=params['merchant'])
                
            return MerchantAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class BranchAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/branch
    Returns performance rankings and aggregated disbursements/recovery rates for branches.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('branch', params)
        
        def fetch_data():
            queryset = BranchAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).select_related('store').order_by('-date')
            
            if 'branch' in params:
                queryset = queryset.filter(store_id=params['branch'])
                
            return BranchAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class DeviceAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/device
    Returns device metrics, brand performance, and enrollment locking data.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('device', params)
        
        def fetch_data():
            queryset = DeviceAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).select_related('brand', 'device').order_by('-date')
            
            if 'brand' in params:
                queryset = queryset.filter(brand_id=params['brand'])
            if 'device_model' in params:
                queryset = queryset.filter(device_id=params['device_model'])
                
            return DeviceAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class GeographyAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/geography
    Returns sales and collection performance geographically (region, state, city).
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('geography', params)
        
        def fetch_data():
            queryset = BranchAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).select_related('store')
            
            if 'state' in params:
                queryset = queryset.filter(province_name=params['state'])
            if 'city' in params:
                queryset = queryset.filter(city_name=params['city'])
                
            return BranchAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class FunnelAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/funnel
    Returns step-by-step onboarding stage conversions.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('funnel', params)
        
        def fetch_data():
            daily = DailyAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).order_by('-date').first()
            
            if not daily:
                return {}
                
            return {
                "date": daily.date,
                "kyc_success_rate": daily.kyc_success_rate,
                "approval_rate": daily.approval_rate,
                "take_rate": daily.take_rate,
                "conversion_rate": daily.conversion_rate,
                "stages": daily.funnel_stages_count
            }
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class RiskAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/risk
    Returns PAR metrics, credit scores, default probability, and FPD rates.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('risk', params)
        
        def fetch_data():
            queryset = RiskAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).order_by('date')
            
            return RiskAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class ExecutiveAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/executive
    Returns leaderboards and conversion rates for sales executives.
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('executive', params)
        
        def fetch_data():
            queryset = ExecutiveAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).select_related('executive', 'store').order_by('-sales_amount')
            
            if 'sales_executive' in params:
                queryset = queryset.filter(executive_id=params['sales_executive'])
                
            return ExecutiveAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class OperationsAnalyticsView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/operations
    Returns operational delay statistics (avg approval, disbursement, and recovery delays).
    """
    def get(self, request):
        params = self.get_filter_params(request)
        cache_key = self.get_cache_key('operations', params)
        
        def fetch_data():
            queryset = DailyAnalytics.objects.filter(
                date__range=(params['start_date'], params['end_date'])
            ).order_by('date')
            
            return DailyAnalyticsSerializer(queryset, many=True).data
            
        data = AnalyticsService.get_cached_analytics(cache_key, fetch_data)
        return Response(data, status=status.HTTP_200_OK)


class ReportsExportView(BaseAnalyticsAPIView):
    """
    GET /api/analytics/reports/export
    Generates downloadable reports (CSV, Excel, PDF) dynamically.
    """
    def get(self, request):
        serializer = MetricsExportSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        export_params = serializer.validated_data
        
        start_date = export_params.get('start_date') or (timezone.now().date() - timedelta(days=30))
        end_date = export_params.get('end_date') or timezone.now().date()
        report_type = export_params.get('report_type')
        fmt = export_params.get('format')
        
        headers = []
        rows = []
        
        if report_type == 'kpis':
            headers = ['Date', 'Total Applications', 'Total Customers', 'Active Loans', 'Outstanding Balance', 'Total Collection', 'Profit']
            summaries = DashboardSummary.objects.filter(date__range=(start_date, end_date)).order_by('date')
            for s in summaries:
                rows.append([s.date, s.total_applications, s.total_customers, s.active_loans, s.outstanding_balance, s.total_collection, s.profit])
        elif report_type == 'loans':
            headers = ['Date', 'Applications', 'Approvals', 'Rejections', 'Disbursed Amount', 'Avg Retail Price']
            dailies = DailyAnalytics.objects.filter(date__range=(start_date, end_date)).order_by('date')
            for d in dailies:
                rows.append([d.date, d.total_applications, d.approved_applications, d.rejected_applications, d.total_disbursed, d.avg_retail_price])
        elif report_type == 'collections':
            headers = ['Date', 'EMI Collected', 'Principal Collected', 'Interest Collected', 'Yappy Collected', 'Cash Collected']
            cols = CollectionAnalytics.objects.filter(date__range=(start_date, end_date)).order_by('date')
            for c in cols:
                rows.append([c.date, c.emi_collected, c.principal_collected, c.interest_collected, c.yappy_collected, c.cash_collected])
        else:
            # Fallback placeholder for other report types
            headers = ['Date', 'Placeholder Columns']
            rows = [[start_date, "Report details available in dashboard endpoints."]]
            
        filename = f"{report_type}_report_{start_date}_to_{end_date}"
        
        if fmt == 'csv':
            csv_bytes = AnalyticsService.generate_csv_report(rows, headers)
            response = HttpResponse(csv_bytes, content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
            return response
            
        elif fmt == 'excel':
            excel_bytes = AnalyticsService.generate_excel_report(rows, headers, title=report_type.capitalize())
            response = HttpResponse(excel_bytes, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
            return response
            
        elif fmt == 'pdf':
            pdf_bytes = AnalyticsService.generate_pdf_report(
                [[str(cell) for cell in row] for row in rows], 
                headers, 
                title=f"{report_type.upper()} REPORT ({start_date} to {end_date})"
            )
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
            return response
            
        return Response({"error": "Unsupported export format"}, status=status.HTTP_400_BAD_REQUEST)
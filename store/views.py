
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import Region, Province, District, Corregimiento, Store, StorePerformance
from home.models import CustomUser
from .serializers import (
    RegionSerializer, ProvinceSerializer, DistrictSerializer,
    CorregimientoSerializer, StoreListSerializer, StoreDetailSerializer,
    StoreCreateUpdateSerializer, AddSalespersonSerializer,
    SalespersonSerializer, StorePerformanceSerializer
)
from .permissions import (
    CanManageStores, CanViewStore, IsStoreManagerOfStore,
    CanAddSalesperson, CanManageSalesperson, CanViewStorePerformance
)
from home.permissions import IsAdminUser

import logging
logger = logging.getLogger(__name__)


# ==================== GEOGRAPHICAL DATA ====================

class RegionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing regions.
    Admin only can create/update/delete.
    """
    queryset = Region.objects.filter(is_active=True)
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'created_at']
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]


class ProvinceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing provinces.
    """
    queryset = Province.objects.filter(is_active=True)
    serializer_class = ProvinceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'created_at']
    filterset_fields = ['region']
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]
    
    @swagger_auto_schema(
        operation_summary="Get Provinces by Region",
        operation_description="Filter provinces by region ID",
        manual_parameters=[
            openapi.Parameter('region_id', openapi.IN_QUERY, 
                            description="Region UUID", type=openapi.TYPE_STRING)
        ]
    )
    @action(detail=False, methods=['get'])
    def by_region(self, request):
        region_id = request.query_params.get('region_id')
        if not region_id:
            return Response(
                {'error': 'region_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        provinces = self.queryset.filter(region_id=region_id)
        serializer = self.get_serializer(provinces, many=True)
        return Response(serializer.data)


class DistrictViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing districts.
    """
    queryset = District.objects.filter(is_active=True)
    serializer_class = DistrictSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'created_at']
    filterset_fields = ['province']
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]
    
    @action(detail=False, methods=['get'])
    def by_province(self, request):
        province_id = request.query_params.get('province_id')
        if not province_id:
            return Response(
                {'error': 'province_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        districts = self.queryset.filter(province_id=province_id)
        serializer = self.get_serializer(districts, many=True)
        return Response(serializer.data)


class CorregimientoViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing corregimientos.
    """
    queryset = Corregimiento.objects.filter(is_active=True)
    serializer_class = CorregimientoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'created_at']
    filterset_fields = ['district']
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [IsAuthenticated()]
    
    @action(detail=False, methods=['get'])
    def by_district(self, request):
        district_id = request.query_params.get('district_id')
        if not district_id:
            return Response(
                {'error': 'district_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        corregimientos = self.queryset.filter(district_id=district_id)
        serializer = self.get_serializer(corregimientos, many=True)
        return Response(serializer.data)


# ==================== STORE MANAGEMENT ====================

class StoreViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing stores.
    - Admin, Global Manager: Full CRUD on all stores
    - Store Manager: View own store, limited updates
    - Sales Advisor: View assigned stores
    - Salesperson: View own store
    """
    queryset = Store.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code', 'ruc', 'email', 'phone']
    ordering_fields = ['name', 'code', 'created_at']
    filterset_fields = ['region', 'province', 'district', 'channel', 'is_active']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return StoreListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return StoreCreateUpdateSerializer
        return StoreDetailSerializer
    
    def get_permissions(self):
        if self.action in ['create', 'destroy']:
            return [CanManageStores()]
        elif self.action in ['update', 'partial_update']:
            return [IsStoreManagerOfStore()]
        elif self.action == 'add_salesperson':
            return [CanAddSalesperson()]
        return [CanViewStore()]
    
    def get_queryset(self):
        """Filter stores based on user role."""
        user = self.request.user
        
        # Admin, Global Manager, Financial Manager see all stores
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            queryset = Store.objects.all()
        
        # Sales Advisor sees assigned stores
        elif user.role == 'sales_advisor':
            queryset = Store.objects.filter(sales_advisor=user)
        
        # Store Manager sees only their store
        elif user.role == 'store_manager':
            queryset = Store.objects.filter(store_manager=user)
        
        # Salesperson sees only their store
        elif user.role == 'salesperson' and user.store_id:
            queryset = Store.objects.filter(id=user.store_id)
        
        else:
            queryset = Store.objects.none()
        
        # Apply filters
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        return queryset.select_related(
            'region', 'province', 'district', 'corregimiento',
            'store_manager', 'sales_advisor', 'created_by'
        )
    
    @swagger_auto_schema(
        operation_summary="List All Stores",
        operation_description="Get list of stores based on user role and permissions."
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Create New Store",
        operation_description="Create a new store. Admin and Global Manager only."
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Get Store Details",
        operation_description="Retrieve detailed information about a specific store."
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Update Store",
        operation_description="Update store information. Full update."
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Partial Update Store",
        operation_description="Partially update store information."
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Delete Store",
        operation_description="Delete a store. Admin only."
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
    # ==================== CUSTOM ACTIONS ====================
    
    @swagger_auto_schema(
        method='post',
        operation_summary="Add Salesperson to Store",
        operation_description="Store Manager or Admin adds a new salesperson to the store.",
        request_body=AddSalespersonSerializer,
        responses={
            201: SalespersonSerializer,
            400: "Validation error",
            403: "Permission denied"
        }
    )
    @action(detail=True, methods=['post'], permission_classes=[CanAddSalesperson])
    def add_salesperson(self, request, pk=None):
        """
        Add a new salesperson to the store.
        Store manager can only add to their own store.
        """
        store = self.get_object()
        serializer = AddSalespersonSerializer(data=request.data)
        
        if serializer.is_valid():
            # Create the salesperson user
            user_data = serializer.validated_data
            password = user_data.pop('password')
            
            salesperson = CustomUser.objects.create_user(
                email=user_data['email'],
                password=password,
                first_name=user_data['first_name'],
                last_name=user_data['last_name'],
                phone=user_data.get('phone', ''),
                role='salesperson',
                store_id=str(store.id),
                employee_id=user_data.get('employee_id'),
                commission_rate=user_data.get('commission_rate', 0.00),
                is_verified=True
            )
            
            logger.info(f"Salesperson {salesperson.email} added to store {store.name} by {request.user.email}")
            
            return Response(
                {
                    'message': 'Salesperson added successfully.',
                    'salesperson': SalespersonSerializer(salesperson).data
                },
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @swagger_auto_schema(
        operation_summary="Get Store Salespersons",
        operation_description="Retrieve all salespersons assigned to this store."
    )
    @action(detail=True, methods=['get'])
    def salespersons(self, request, pk=None):
        """Get all salespersons for a store."""
        store = self.get_object()
        salespersons = store.get_salespersons()
        serializer = SalespersonSerializer(salespersons, many=True)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_summary="Get Store Statistics",
        operation_description="Get summary statistics for the store."
    )
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """Get store statistics."""
        store = self.get_object()
        
        stats = {
            'store_id': str(store.id),
            'store_name': store.name,
            'total_salespersons': store.get_salespersons_count(),
            'active_salespersons': store.get_salespersons().filter(is_active=True).count(),
            'monthly_target': float(store.monthly_target),
            'is_active': store.is_active,
        }
        
        return Response(stats)
    
    @swagger_auto_schema(
        operation_summary="My Store",
        operation_description="Get the store managed by the authenticated store manager."
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_store(self, request):
        """
        Get the store for the authenticated store manager.
        """
        user = request.user
        
        if user.role == 'store_manager':
            try:
                store = Store.objects.get(store_manager=user)
                serializer = StoreDetailSerializer(store)
                return Response(serializer.data)
            except Store.DoesNotExist:
                return Response(
                    {'error': 'No store assigned to you.'},
                    status=status.HTTP_404_NOT_FOUND
                )
        elif user.role == 'salesperson' and user.store_id:
            try:
                store = Store.objects.get(id=user.store_id)
                serializer = StoreDetailSerializer(store)
                return Response(serializer.data)
            except Store.DoesNotExist:
                return Response(
                    {'error': 'Store not found.'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {'error': 'You are not assigned to any store.'},
                status=status.HTTP_400_BAD_REQUEST
            )


# ==================== SALESPERSON MANAGEMENT ====================

@swagger_auto_schema(
    method='get',
    operation_summary="Get Salesperson Details",
    operation_description="Get details of a specific salesperson. Store manager can only view their store's salespersons."
)
@swagger_auto_schema(
    method='patch',
    operation_summary="Update Salesperson",
    operation_description="Update salesperson information. Store manager can only update their store's salespersons.",
    request_body=SalespersonSerializer
)
@swagger_auto_schema(
    method='delete',
    operation_summary="Delete Salesperson",
    operation_description="Delete a salesperson. Store manager can only delete their store's salespersons."
)
@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([CanManageSalesperson])
def manage_salesperson(request, salesperson_id):
    """
    Manage individual salesperson: view, update, or delete.
    """
    salesperson = get_object_or_404(
        CustomUser,
        id=salesperson_id,
        role='salesperson'
    )
    
    # Check object-level permission
    permission = CanManageSalesperson()
    if not permission.has_object_permission(request, None, salesperson):
        return Response(
            {'error': 'You do not have permission to manage this salesperson.'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    if request.method == 'GET':
        serializer = SalespersonSerializer(salesperson)
        return Response(serializer.data)
    
    elif request.method == 'PATCH':
        # Only allow updating specific fields
        allowed_fields = ['first_name', 'last_name', 'phone', 'commission_rate', 'is_active']
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
        
        serializer = SalespersonSerializer(
            salesperson,
            data=update_data,
            partial=True
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        # Soft delete - just deactivate
        salesperson.is_active = False
        salesperson.save()
        return Response(
            {'message': 'Salesperson deactivated successfully.'},
            status=status.HTTP_200_OK
        )


@swagger_auto_schema(
    method='get',
    operation_summary="List Salespersons by Store",
    operation_description="Get all salespersons for a specific store."
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_salespersons_by_store(request, store_id):
    """
    List all salespersons for a specific store.
    """
    store = get_object_or_404(Store, id=store_id)
    
    # Check if user has permission to view this store
    permission = CanViewStore()
    if not permission.has_object_permission(request, None, store):
        return Response(
            {'error': 'You do not have permission to view this store.'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    salespersons = store.get_salespersons()
    serializer = SalespersonSerializer(salespersons, many=True)
    
    return Response({
        'store_id': str(store.id),
        'store_name': store.name,
        'total_count': len(salespersons),
        'salespersons': serializer.data
    })


# ==================== STORE PERFORMANCE ====================

class StorePerformanceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for store performance metrics.
    """
    queryset = StorePerformance.objects.all()
    serializer_class = StorePerformanceSerializer
    permission_classes = [CanViewStorePerformance]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['month', 'total_sales', 'approval_rate']
    filterset_fields = ['store', 'month']
    
    def get_queryset(self):
        """Filter performance data based on user role."""
        user = self.request.user
        queryset = StorePerformance.objects.all()
        
        # Admin, Global Manager, Financial Manager see all
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            pass
        
        # Sales Advisor sees assigned stores
        elif user.role == 'sales_advisor':
            store_ids = Store.objects.filter(sales_advisor=user).values_list('id', flat=True)
            queryset = queryset.filter(store_id__in=store_ids)
        
        # Store Manager sees only their store
        elif user.role == 'store_manager':
            try:
                store = Store.objects.get(store_manager=user)
                queryset = queryset.filter(store=store)
            except Store.DoesNotExist:
                queryset = StorePerformance.objects.none()
        
        else:
            queryset = StorePerformance.objects.none()
        
        return queryset.select_related('store')


# ==================== DASHBOARD STATS ====================

@swagger_auto_schema(
    method='get',
    operation_summary="Get Store Dashboard Statistics",
    operation_description="Get comprehensive dashboard statistics based on user role."
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def store_dashboard_stats(request):
    """
    Get dashboard statistics for stores based on user role.
    """
    user = request.user
    
    if user.role in ['admin', 'global_manager', 'financial_manager']:
        # Global statistics
        total_stores = Store.objects.filter(is_active=True).count()
        total_salespersons = CustomUser.objects.filter(
            role='salesperson',
            is_active=True
        ).count()
        
        stores_by_region = Store.objects.filter(is_active=True).values(
            'region__name'
        ).annotate(count=Count('id'))
        
        return Response({
            'total_stores': total_stores,
            'total_salespersons': total_salespersons,
            'stores_by_region': list(stores_by_region),
            'role': user.role
        })
    
    elif user.role == 'store_manager':
        try:
            store = Store.objects.get(store_manager=user)
            salespersons_count = store.get_salespersons_count()
            
            return Response({
                'store_id': str(store.id),
                'store_name': store.name,
                'total_salespersons': salespersons_count,
                'monthly_target': float(store.monthly_target),
                'role': user.role
            })
        except Store.DoesNotExist:
            return Response({
                'error': 'No store assigned.',
                'role': user.role
            })
    
    else:
        return Response({
            'message': 'Limited access for your role.',
            'role': user.role
        })
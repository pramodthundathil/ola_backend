# stores/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegionViewSet, ProvinceViewSet, DistrictViewSet, CorregimientoViewSet,
    StoreViewSet, StorePerformanceViewSet,
    manage_salesperson, list_salespersons_by_store, store_dashboard_stats
)

# Create router for ViewSets
router = DefaultRouter()
router.register(r'regions', RegionViewSet, basename='region')
router.register(r'provinces', ProvinceViewSet, basename='province')
router.register(r'districts', DistrictViewSet, basename='district')
router.register(r'corregimientos', CorregimientoViewSet, basename='corregimiento')
router.register(r'stores', StoreViewSet, basename='store')
router.register(r'performance', StorePerformanceViewSet, basename='store-performance')

# URL patterns
urlpatterns = [
    # Router URLs
    path('', include(router.urls)),
    
    # Salesperson Management
    path('salespersons/<uuid:salesperson_id>/', manage_salesperson, name='manage-salesperson'),
    path('stores/<uuid:store_id>/salespersons/', list_salespersons_by_store, name='store-salespersons'),
    
    # Dashboard
    path('dashboard/stats/', store_dashboard_stats, name='store-dashboard-stats'),
]

"""
API Endpoints Structure:

GEOGRAPHICAL DATA:
- GET    /api/stores/regions/                      - List all regions
- POST   /api/stores/regions/                      - Create region (Admin)
- GET    /api/stores/regions/{id}/                 - Get region details
- PUT    /api/stores/regions/{id}/                 - Update region (Admin)
- DELETE /api/stores/regions/{id}/                 - Delete region (Admin)

- GET    /api/stores/provinces/                    - List all provinces
- GET    /api/stores/provinces/by_region/?region_id={uuid} - Filter by region
- POST   /api/stores/provinces/                    - Create province (Admin)
- GET    /api/stores/provinces/{id}/               - Get province details
- PUT    /api/stores/provinces/{id}/               - Update province (Admin)
- DELETE /api/stores/provinces/{id}/               - Delete province (Admin)

- GET    /api/stores/districts/                    - List all districts
- GET    /api/stores/districts/by_province/?province_id={uuid} - Filter by province
- POST   /api/stores/districts/                    - Create district (Admin)
- GET    /api/stores/districts/{id}/               - Get district details
- PUT    /api/stores/districts/{id}/               - Update district (Admin)
- DELETE /api/stores/districts/{id}/               - Delete district (Admin)

- GET    /api/stores/corregimientos/               - List all corregimientos
- GET    /api/stores/corregimientos/by_district/?district_id={uuid} - Filter by district
- POST   /api/stores/corregimientos/               - Create corregimiento (Admin)
- GET    /api/stores/corregimientos/{id}/          - Get corregimiento details
- PUT    /api/stores/corregimientos/{id}/          - Update corregimiento (Admin)
- DELETE /api/stores/corregimientos/{id}/          - Delete corregimiento (Admin)

STORE MANAGEMENT:
- GET    /api/stores/stores/                       - List stores (filtered by role)
- POST   /api/stores/stores/                       - Create store (Admin/Global Manager)
- GET    /api/stores/stores/{id}/                  - Get store details
- PUT    /api/stores/stores/{id}/                  - Update store
- PATCH  /api/stores/stores/{id}/                  - Partial update store
- DELETE /api/stores/stores/{id}/                  - Delete store (Admin)

CUSTOM STORE ACTIONS:
- GET    /api/stores/stores/my_store/              - Get my assigned store (Store Manager/Salesperson)
- POST   /api/stores/stores/{id}/add_salesperson/  - Add salesperson to store
- GET    /api/stores/stores/{id}/salespersons/     - Get store salespersons
- GET    /api/stores/stores/{id}/statistics/       - Get store statistics

SALESPERSON MANAGEMENT:
- GET    /api/stores/salespersons/{id}/            - Get salesperson details
- PATCH  /api/stores/salespersons/{id}/            - Update salesperson
- DELETE /api/stores/salespersons/{id}/            - Delete/deactivate salesperson
- GET    /api/stores/stores/{store_id}/salespersons/ - List salespersons by store

PERFORMANCE:
- GET    /api/stores/performance/                  - List performance records
- POST   /api/stores/performance/                  - Create performance record
- GET    /api/stores/performance/{id}/             - Get performance details
- PUT    /api/stores/performance/{id}/             - Update performance
- DELETE /api/stores/performance/{id}/             - Delete performance

DASHBOARD:
- GET    /api/stores/dashboard/stats/              - Get dashboard statistics

PERMISSIONS MATRIX:

ROLE                  | Stores CRUD | Add Salesperson | Manage Salesperson | View Performance
----------------------|-------------|-----------------|-------------------|------------------
Admin                 | Full        | All stores      | All               | All stores
Global Manager        | Full        | All stores      | All               | All stores
Financial Manager     | View All    | No              | No                | All stores
Sales Advisor         | View Assigned| No             | No                | Assigned stores
Store Manager         | View Own    | Own store       | Own store         | Own store
                      | Update Own  |                 |                   |
Salesperson           | View Own    | No              | No                | No
"""
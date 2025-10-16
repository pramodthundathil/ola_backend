from django.urls import path, include
from .import views
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

urlpatterns = [
    # Authentication
    path('api/token/', views.MyTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/generate-otp/', views.generate_otp, name='generate-otp'),
    path('auth/verify-otp/', views.verify_otp_and_login, name='verify-otp-login'),
    path('auth/resend-otp/', views.resend_otp, name='resend-otp'),
    path('auth/logout/', views.logout, name='logout'),
    
    # User Registration (Admin Only)
    path('admin/create-user/', views.admin_create_user, name='admin-create-user'),
    path('auth/verify-registration/', views.verify_registration_otp, name='verify-registration'),
    
    # User Profile
    path('profile/', views.UserProfileView.as_view(), name='profile'),
    path('profile/change-password/', views.change_password, name='change-password'),
    path('profile/delete/', views.DeleteOwnAccount.as_view(), name='delete-own-account'),
    
    # Admin User Management
    path('admin/users/', views.ListAllUsers.as_view(), name='list-users'),
    path('admin/users/<int:pk>/', views.get_user_by_id, name='get-user'),
    path('admin/users/<int:user_id>/toggle-active/', 
         views.ToggleUserActiveStatus.as_view(), name='toggle-user-active'),
    path('admin/users/<int:user_id>/delete/', 
         views.DeleteUserByAdmin.as_view(), name='admin-delete-user'),



    # Router URLs
    path('stores/', include(router.urls)),
    
    # Salesperson Management
    path('salespersons/<int:salesperson_id>/', manage_salesperson, name='manage-salesperson'),
    path('stores/<int:store_id>/salespersons/', list_salespersons_by_store, name='store-salespersons'),
    
    # Dashboard
    path('dashboard/stats/', store_dashboard_stats, name='store-dashboard-stats'),

]

from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


# Swagger Configuration
schema_view = get_schema_view(
    openapi.Info(
        title="Phone Financing Platform API",
        default_version='v1',
        description="""
        # Phone Financing & Credit Sales Platform API
        
        Complete API documentation for the phone financing platform.
        
        ## Features
        - OTP-based authentication
        - Role-based access control (6 user roles)
        - Credit application management
        - Payment processing
        - Device enrollment and locking
        - Comprehensive reporting
        
        ## Authentication
        This API uses JWT (JSON Web Tokens) for authentication.
        
        ### Login Flow:
        1. Call /api/v1/auth/generate-otp/ with email/phone
        2. Receive OTP via email/SMS
        3. Call /api/v1/auth/verify-otp/ with OTP
        4. Receive access and refresh tokens
        5. Use access token in Authorization header: Bearer <token>
        
        ## User Roles
        - *Salesperson*: Create applications, enroll devices
        - *Store Manager*: Manage store, approve collections
        - *Global Manager*: View all stores, analytics
        - *Financial Manager*: Configure credit tiers, system settings
        - *Sales Advisor*: Support collections, monitoring
        - *Admin*: Full system access
        """,
        terms_of_service="https://www.byteboot.in/",
        contact=openapi.Contact(email="support@byteboot.in"),
        license=openapi.License(name="Ola Credit"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # API Documentation
    path('', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('swagger.json', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('swagger.yaml', schema_view.without_ui(cache_timeout=0), name='schema-yaml'),
    
    # API v1
    path('api/v1/users/', include('home.urls')),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # path('api/v1/applications/', include('applications.urls')),
    # path('api/v1/products/', include('products.urls')),
    # path('api/v1/payments/', include('payments.urls')),
    # path('api/v1/devices/', include('devices.urls')),
    # path('api/v1/reports/', include('reports.urls')),
]



if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
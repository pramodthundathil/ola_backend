from django.urls import path 
from .import views 

urlpatterns = [
     # Device Enrollment CRUD
    path('device-enrollment/', views.DeviceEnrollmentAPIView.as_view(), name='device-enrollment-list-create'),
    path('device-enrollment/<int:id>/', views.DeviceEnrollmentAPIView.as_view(), name='device-enrollment-detail-update'),
    
    # Device Lock/Unlock (Admin only)
    path('device-lock/', views.DeviceLockAPIView.as_view(), name='device-lock'),
    path('device-unlock/', views.DeviceLockAPIView.as_view(), name='device-unlock'),
]
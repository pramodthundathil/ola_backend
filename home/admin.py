from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import CustomUser as User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom admin interface for User model.
    """
    list_display = [
        'email',
        'first_name',
        'last_name',
        'role',
        'store_id',
        'is_active',
        'is_verified',
        'date_joined'
    ]
    list_filter = [
        'role',
        'is_active',
        'is_verified',
        'is_staff',
        'is_superuser',
        'date_joined'
    ]
    search_fields = ['email', 'first_name', 'last_name', 'employee_id']
    ordering = ['-date_joined']
    
    fieldsets = (
        (None, {
            'fields': ('email', 'password')
        }),
        (_('Personal Info'), {
            'fields': (
                'first_name',
                'last_name',
                'username',
                'phone',
                'profile_picture',
                'employee_id'
            )
        }),
        (_('Role & Store'), {
            'fields': ('role', 'store_id', 'commission_rate')
        }),
        (_('Permissions'), {
            'fields': (
                'is_active',
                'is_verified',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions'
            )
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'date_joined', 'updated_at')
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'password1',
                'password2',
                'first_name',
                'last_name',
                'role',
                'store_id',
                'is_active',
                'is_staff'
            ),
        }),
    )
    
    readonly_fields = ['date_joined', 'last_login', 'updated_at']



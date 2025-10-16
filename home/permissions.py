"""
Checks if the authenticated user has the salesperson role.

Args:
    request: The HTTP request object.
    view: The view being accessed.

Returns:
    bool: True if the user is authenticated and is a salesperson, False otherwise.
"""

from rest_framework import permissions


class IsSalesperson(permissions.BasePermission):
    """
    Permission check for salesperson role.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_salesperson()
        )


class IsStoreManager(permissions.BasePermission):
    """
    Permission check for store manager role.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_store_manager()
        )


class IsGlobalManager(permissions.BasePermission):
    """
    Permission check for global manager role.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_global_manager()
        )


class IsFinancialManager(permissions.BasePermission):
    """
    Permission check for financial manager role.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_financial_manager()
        )


class IsAdminUser(permissions.BasePermission):
    """
    Permission check for admin role.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_admin_user()
        )


class IsAdmin(permissions.BasePermission):
    """
    Custom permission to only allow admin users to access this view.
    """
    def has_permission(self, request, view):
        # Check if the user is authenticated and has the 'admin' role
        return request.user and request.user.role == 'admin'


class CanApproveApplications(permissions.BasePermission):
    """
    Permission check for users who can approve applications.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.can_approve_applications()
        )


class CanManageStore(permissions.BasePermission):
    """
    Permission check for users who can manage store operations.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.can_manage_store()
        )


class CanConfigureSystem(permissions.BasePermission):
    """
    Permission check for users who can configure system settings.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.can_configure_system()
        )
    

# stores/permissions.py
from rest_framework import permissions


class CanManageStores(permissions.BasePermission):
    """
    Permission for users who can create/edit stores.
    Admin and Global Manager can manage all stores.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Admins and Global Managers can manage stores
        return request.user.role in [
            'admin', 'global_manager', 'financial_manager',
            'sales_advisor', 'store_manager'
        ]
    
    def has_object_permission(self, request, view, obj):
        """obj is the Store instance"""
        user = request.user
        
        # Admin, Global Manager, Financial Manager can view all
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            return True
        
        # Sales Advisor can view assigned stores
        if user.role == 'sales_advisor' and obj.sales_advisor == user:
            return True
        
        # Store Manager can view their own store
        if user.role == 'store_manager' and obj.store_manager == user:
            return True
        
        return False


class CanViewStore(permissions.BasePermission):
    """
    Permission to view store details.
    - Admin, Global Manager, Financial Manager: All stores
    - Sales Advisor: Assigned stores
    - Store Manager: Own store
    - Salesperson: Own store
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Admin, Global Manager, Financial Manager can view all
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            return True
        
        # Sales Advisor can view assigned stores
        if user.role == 'sales_advisor' and obj.sales_advisor == user:
            return True
        
        # Store Manager can view their own store
        if user.role == 'store_manager' and obj.store_manager == user:
            return True
        
        # Salesperson can view their store
        if user.role == 'salesperson' and str(user.store_id) == str(obj.id):
            return True
        
        return False


class IsStoreManagerOfStore(permissions.BasePermission):
    """
    Permission for store manager to manage their own store.
    Store manager can:
    - Add salespersons to their store
    - Update their store info (limited fields)
    - View store performance
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Admin and Global Manager always have permission
        if request.user.role in ['admin', 'global_manager']:
            return True
        
        # Store manager must be assigned to a store
        return request.user.role == 'store_manager' and request.user.store_id
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Admin and Global Manager can access all
        if user.role in ['admin', 'global_manager']:
            return True
        
        # Store manager can only access their own store
        if user.role == 'store_manager':
            return obj.store_manager == user
        
        return False


class CanAddSalesperson(permissions.BasePermission):
    """
    Permission to add salespersons to a store.
    - Admin, Global Manager: Any store
    - Store Manager: Only their own store
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.role in ['admin', 'global_manager', 'store_manager']
    
    def has_object_permission(self, request, view, obj):
        """obj is the Store instance"""
        user = request.user
        
        # Admin and Global Manager can add to any store
        if user.role in ['admin', 'global_manager']:
            return True
        
        # Store manager can only add to their own store
        if user.role == 'store_manager':
            return obj.store_manager == user
        
        return False


class CanManageSalesperson(permissions.BasePermission):
    """
    Permission to update/delete salespersons.
    - Admin, Global Manager: Any salesperson
    - Store Manager: Only salespersons in their store
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.role in ['admin', 'global_manager', 'store_manager']
    
    def has_object_permission(self, request, view, obj):
        """obj is the CustomUser (salesperson) instance"""
        user = request.user
        
        # Admin and Global Manager can manage any salesperson
        if user.role in ['admin', 'global_manager']:
            return True
        
        # Store manager can only manage salespersons in their store
        if user.role == 'store_manager':
            return (
                obj.role == 'salesperson' and 
                str(obj.store_id) == str(user.store_id)
            )
        
        return False


class CanViewStorePerformance(permissions.BasePermission):
    """
    Permission to view store performance metrics.
    - Admin, Global Manager, Financial Manager: All stores
    - Sales Advisor: Assigned stores
    - Store Manager: Own store
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.role in ['admin', 'global_manager']
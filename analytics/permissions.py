"""
Role-based permissions for analytics endpoints
"""

from rest_framework import permissions


class AnalyticsPermission(permissions.BasePermission):
    """
    Custom permission for analytics access based on user role
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        
        # All authenticated users can access analytics
        # Filtering is done at the queryset level based on role
        return True
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Admin, Global Manager, Financial Manager have full access
        if user.role in ['admin', 'global_manager', 'financial_manager']:
            return True
        
        # Sales Advisor can access region data
        if user.role == 'sales_advisor':
            if hasattr(obj, 'store'):
                return obj.store.region == user.store.region if user.store else False
            return True
        
        # Store Manager can access own store data
        if user.role == 'store_manager':
            if hasattr(obj, 'store'):
                return obj.store == user.store if user.store else False
            return True
        
        # Salesperson can only access own data
        if user.role == 'salesperson':
            if hasattr(obj, 'salesperson'):
                return obj.salesperson == user
            return False
        
        return False


class FinancialAnalyticsPermission(permissions.BasePermission):
    """
    Stricter permission for financial analytics
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Only specific roles can access financial data
        allowed_roles = ['admin', 'global_manager', 'financial_manager']
        
        # Store managers can see their store's financial data
        if request.user.role == 'store_manager':
            return True
        
        return request.user.role in allowed_roles
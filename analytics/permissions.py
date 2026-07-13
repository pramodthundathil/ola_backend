from rest_framework import permissions

class AnalyticsPermission(permissions.BasePermission):
    """
    Strict role-based permissions for analytics access.
    Only allows 'admin', 'global_manager', and 'financial_manager' roles.
    """
    
    def has_permission(self, request, view):
        # User must be authenticated
        if not request.user or not request.user.is_authenticated:
            return False
            
        # Allowed roles for enterprise analytics and business intelligence
        allowed_roles = ['admin', 'global_manager', 'financial_manager']
        
        return getattr(request.user, 'role', None) in allowed_roles
        
    def has_object_permission(self, request, view, obj):
        # Re-use the same class-level permission check for object permissions
        return self.has_permission(request, view)
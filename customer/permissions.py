from rest_framework import permissions



class IsAuthenticatedUser(permissions.BasePermission):
    """
    Permission for any authenticated user.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsAdminOrGlobalOrFinancialManager(permissions.BasePermission):
    """
    Permission check for Admin, Global Manager, or Financial Manager role.
    """
    def has_permission(self, request, view):
        user = request.user
        return (
            user
            and user.is_authenticated
            and (
                user.is_staff
                or getattr(user, 'role', '') in ['admin', 'global_manager', 'financial_manager']
            )
        )


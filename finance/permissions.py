"""
Checks if the authenticated user has the salesperson role.

Args:
    request: The HTTP request object.
    view: The view being accessed.

Returns:
    bool: True if the user is authenticated and is a salesperson, False otherwise.
"""

from rest_framework import permissions


class IsAdminOrGlobalManager(permissions.BasePermission):
    """
    Permission check for admin or global manager role.
    """
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or getattr(request.user, 'is_global_manager', lambda: False))
        )
    

class IsAdminOrGlobalManagerOrReadOnly(permissions.BasePermission):
    """
    Read-only access for all.
    Write access only for Admin or Global Manager.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS: #Everyone (even unauthenticated users) can read data(GET,HEAD,OPTIONS allowed)
            return True

        user = request.user
        if not user or not user.is_authenticated: #The user is not logged in, deny access.
            return False

        return (
            user.is_staff
            or getattr(user, 'is_global_manager', False)
            or getattr(user, 'role', '').lower() in ['admin', 'global_manager'] #Allows only 'admin' or 'global_manager'
        )

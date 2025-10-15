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
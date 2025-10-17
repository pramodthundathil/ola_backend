from rest_framework import permissions



class IsAuthenticatedUser(permissions.BasePermission):
    """
    Permission for any authenticated user.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

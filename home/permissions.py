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


class CanViewReports(permissions.BasePermission):
    """
    Permission for Admin, Global Manager, and Financial Manager
    to access common reports.
    """
    def has_permission(self, request, view):
        user = request.user
        return (
            user
            and user.is_authenticated
            and (
                user.is_admin_user()
                or user.is_global_manager()
                or user.is_financial_manager()
            )
        )



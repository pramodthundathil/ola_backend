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


class CanViewAdminFinanceDetails(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ["admin", "financial_manager", "global_manager"]
    

class CanViewSalesAdvisorFinance(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role == "sales_advisor"
    

class CanViewStoreManagerFinance(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role == "store_manager"


class CanListUsers(permissions.BasePermission):
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and request.user.role in ['admin', 'global_manager', 'financial_manager', 'sales_advisor', 'store_manager']
        )


class CanManageUsers(permissions.BasePermission):
    """
    Permission check to allow user management edits (Admin and Global Manager).
    """
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and request.user.role in ['admin', 'global_manager']
        )


class CanCreateUsersPermission(permissions.BasePermission):
    """
    Permission check for users who can create/register other users.
    Allows Admin, Global Manager, Financial Manager, and Sales Advisor.
    """
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and request.user.role in ['admin', 'global_manager', 'financial_manager', 'sales_advisor']
        )




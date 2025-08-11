"""
Role-based permission system for Timelog application.

This module implements strict role checking as specified in US-B01:
- Employees: Only access their own time entries
- Backoffice: Full access to all employees and time entries
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import TimeEntry, User


def role_required(required_role):
    """
    Decorator that requires a specific user role.

    Args:
        required_role (str): The required role ('employee' or 'backoffice')

    Raises:
        PermissionDenied: If user doesn't have the required role
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication required")

            if request.user.role != required_role:
                raise PermissionDenied(f"Role '{required_role}' required")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def backoffice_required(view_func):
    """Decorator that requires backoffice role."""
    return role_required("backoffice")(view_func)


def employee_required(view_func):
    """Decorator that requires employee role."""
    return role_required("employee")(view_func)


def can_access_time_entry(user, time_entry):
    """
    Check if user can access a specific time entry.

    Args:
        user: The user requesting access
        time_entry: The TimeEntry object

    Returns:
        bool: True if user can access the entry
    """
    if not user.is_authenticated:
        return False

    # Superusers and backoffice can access all time entries
    if user.is_superuser or user.is_backoffice:
        return True

    # Employees can only access their own time entries
    if user.is_employee and time_entry.user == user:
        return True

    return False


def can_modify_time_entry(user, time_entry):
    """
    Check if user can modify a specific time entry.

    Args:
        user: The user requesting modification access
        time_entry: The TimeEntry object

    Returns:
        bool: True if user can modify the entry
    """
    # Same logic as access for this application
    return can_access_time_entry(user, time_entry)


def can_create_time_entry_for_user(user, target_user):
    """
    Check if user can create time entries for target_user.

    Args:
        user: The user requesting to create entries
        target_user: The user for whom entries would be created

    Returns:
        bool: True if user can create entries for target_user
    """
    if not user.is_authenticated:
        return False

    # Superusers and backoffice can create entries for anyone
    if user.is_superuser or user.is_backoffice:
        return True

    # Employees can only create their own entries
    if user.is_employee and target_user == user:
        return True

    return False


def can_view_user_list(user):
    """
    Check if user can view the full user list.

    Args:
        user: The user requesting access

    Returns:
        bool: True if user can view user list
    """
    return user.is_authenticated and (user.is_superuser or user.is_backoffice)


def can_create_users(user):
    """
    Check if user can create new users.

    Args:
        user: The user requesting access

    Returns:
        bool: True if user can create users
    """
    return user.is_authenticated and (user.is_superuser or user.is_backoffice)


def can_export_time_entries(user):
    """
    Check if user can export time entry data.

    Args:
        user: The user requesting access

    Returns:
        bool: True if user can export data
    """
    return user.is_authenticated and (user.is_superuser or user.is_backoffice)


def get_accessible_time_entries(user):
    """
    Get time entries that the user is allowed to access.

    Args:
        user: The user requesting access

    Returns:
        QuerySet: TimeEntry objects the user can access
    """
    if not user.is_authenticated:
        return TimeEntry.objects.none()

    if user.is_superuser or user.is_backoffice:
        # Superusers and backoffice can access all time entries
        return TimeEntry.objects.all()

    if user.is_employee:
        # Employees can only access their own entries
        return TimeEntry.objects.filter(user=user)

    return TimeEntry.objects.none()


def get_accessible_users(user):
    """
    Get users that the current user is allowed to see.

    Args:
        user: The user requesting access

    Returns:
        QuerySet: User objects the user can access
    """
    if not user.is_authenticated:
        return User.objects.none()

    if user.is_superuser or user.is_backoffice:
        # Superusers and backoffice can see all users
        return User.objects.all()

    if user.is_employee:
        # Employees can only see themselves
        return User.objects.filter(pk=user.pk)

    return User.objects.none()


def require_time_entry_access(view_func):
    """
    Decorator that requires access to a time entry.
    Expects 'entry_id' in URL kwargs.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        entry_id = kwargs.get("entry_id") or kwargs.get("pk")
        if not entry_id:
            raise PermissionDenied("No time entry ID provided")

        time_entry = get_object_or_404(TimeEntry, pk=entry_id)

        if not can_access_time_entry(request.user, time_entry):
            raise PermissionDenied("Access to this time entry denied")

        # Add time_entry to kwargs for the view
        kwargs["time_entry"] = time_entry
        return view_func(request, *args, **kwargs)

    return wrapper


def require_time_entry_modify(view_func):
    """
    Decorator that requires modify access to a time entry.
    Expects 'entry_id' in URL kwargs.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        entry_id = kwargs.get("entry_id") or kwargs.get("pk")
        if not entry_id:
            raise PermissionDenied("No time entry ID provided")

        time_entry = get_object_or_404(TimeEntry, pk=entry_id)

        if not can_modify_time_entry(request.user, time_entry):
            raise PermissionDenied("Modification of this time entry denied")

        # Add time_entry to kwargs for the view
        kwargs["time_entry"] = time_entry
        return view_func(request, *args, **kwargs)

    return wrapper


class PermissionMixin:
    """
    Mixin class for views that need role-based permission checking.
    """

    def dispatch(self, request, *args, **kwargs):
        """Check permissions before dispatching to view method."""
        if not self.has_permission(request, *args, **kwargs):
            raise PermissionDenied("Insufficient permissions")
        return super().dispatch(request, *args, **kwargs)

    def has_permission(self, request, *args, **kwargs):
        """Override this method in subclasses to define permission logic."""
        return request.user.is_authenticated


class BackofficeRequiredMixin(PermissionMixin):
    """Mixin that requires backoffice role."""

    def has_permission(self, request, *args, **kwargs):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.is_backoffice
        )


class EmployeeRequiredMixin(PermissionMixin):
    """Mixin that requires employee role."""

    def has_permission(self, request, *args, **kwargs):
        return request.user.is_authenticated and request.user.is_employee


class TimeEntryAccessMixin(PermissionMixin):
    """Mixin that requires access to a specific time entry."""

    def has_permission(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return False

        entry_id = kwargs.get("entry_id") or kwargs.get("pk")
        if not entry_id:
            return False

        try:
            time_entry = TimeEntry.objects.get(pk=entry_id)
            return can_access_time_entry(request.user, time_entry)
        except TimeEntry.DoesNotExist:
            return False

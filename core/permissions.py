from rest_framework import permissions

class IsSuperAdmin(permissions.BasePermission):
    """Allows access only to super administrators."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_super_admin)


class IsAdminUserOrSuperAdmin(permissions.BasePermission):
    """Allows access to authenticated admin users and super administrators."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and (
                request.user.role in ['admin', 'super_admin'] or request.user.is_staff
            )
        )


class IsSuperAdminOrReadOnly(permissions.BasePermission):
    """Read-only for normal admins, write operations restricted to super administrators."""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_authenticated and request.user.is_super_admin)

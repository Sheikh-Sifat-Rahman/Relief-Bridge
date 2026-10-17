from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def has_role(user, role):
    return (
        user.is_authenticated
        and user.is_active
        and user.user_roles.filter(role__name=role, status="ACTIVE").exists()
    )


def active_role_required(role):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not has_role(request.user, role):
                raise PermissionDenied("An active role is required.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


def require_staff(user):
    if not user.is_active or not user.is_staff:
        raise PermissionDenied("Staff authorization required.")

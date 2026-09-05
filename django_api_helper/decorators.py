"""Permission and safe-error helpers shared by the public views."""

import logging
import time
from functools import wraps

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

logger = logging.getLogger("django_api_helper")


def request_log_context(request, view, status_code=None, duration_ms=None):
    """Return safe, structured fields suitable for application log formatters."""
    model = getattr(view, "model", None)
    request_id = request.headers.get("X-Request-ID", "")[:128]
    context = {
        "request_method": getattr(request, "method", None),
        "request_path": getattr(request, "path", None),
        "request_id": request_id or None,
        "view_name": view.__class__.__name__,
        "model_name": getattr(model, "__name__", None),
        "status_code": status_code,
    }
    if duration_ms is not None:
        context["duration_ms"] = round(duration_ms, 3)
    return context


def error_response(code, detail, http_status, errors=None):
    """Build the stable, non-sensitive error envelope used by this package."""
    payload = {"code": code, "detail": detail}
    if errors is not None:
        payload["errors"] = errors
    return Response(payload, status=http_status)


def exception_response(exc, request, view):
    """Convert expected exceptions to safe API responses and log unknown ones."""
    if isinstance(exc, (ValidationError, DjangoValidationError)):
        errors = getattr(exc, "detail", None) or getattr(exc, "message_dict", None) or getattr(exc, "messages", None)
        return error_response("validation_error", "Request validation failed.", status.HTTP_400_BAD_REQUEST, errors)
    if isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        return error_response("permission_denied", "You do not have permission to perform this action.", status.HTTP_403_FORBIDDEN)
    if isinstance(exc, (NotFound, Http404)):
        return error_response("not_found", "The requested resource was not found.", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, APIException):
        return error_response(str(exc.default_code), "Request could not be completed.", exc.status_code)

    logger.exception(
        "Unhandled API helper error",
        extra=request_log_context(request, view, status.HTTP_500_INTERNAL_SERVER_ERROR),
    )
    return error_response("internal_error", "An internal error occurred.", status.HTTP_500_INTERNAL_SERVER_ERROR)


def check_table_permissions(view_func):
    """Require Django's standard model permission that matches the HTTP method."""
    permission_prefixes = {"GET": "view", "POST": "add", "PUT": "change", "PATCH": "change", "DELETE": "delete"}

    @wraps(view_func)
    def wrapped(view, request, *args, **kwargs):
        prefix = permission_prefixes.get(request.method.upper(), "view")
        permission = f"{view.app_label}.{prefix}_{view.model_name}"
        if not request.user.has_perm(permission):
            return error_response("permission_denied", "You do not have permission to perform this action.", status.HTTP_403_FORBIDDEN)
        return view_func(view, request, *args, **kwargs)

    return wrapped


def get_object_for_user(queryset, user, permission):
    """Retain the legacy permission helper while returning no queryset on denial."""
    return queryset if not permission or user.has_perm(permission) else None


def check_object_permissions(permission_prefix="view_"):
    """Apply a legacy object-level permission check without leaking object details."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(view, request, *args, **kwargs):
            pk = kwargs.get("pk") or request.query_params.get("pk")
            permission = f"{view.app_label}.{permission_prefix}{view.model_name}"
            queryset = view.get_queryset()
            if pk and not get_object_for_user(queryset, request.user, permission):
                return error_response("permission_denied", "You do not have permission to perform this action.", status.HTTP_403_FORBIDDEN)
            view.queryset = queryset
            return view_func(view, request, *args, **kwargs)

        return wrapped

    return decorator


def error_handling(view_func):
    """Wrap public view methods so internal details are logged, not exposed."""
    @wraps(view_func)
    def wrapped(view, request, *args, **kwargs):
        started = time.perf_counter()
        try:
            response = view_func(view, request, *args, **kwargs)
        except Exception as exc:
            response = exception_response(exc, request, view)
        logger.debug(
            "API helper request completed",
            extra=request_log_context(
                request,
                view,
                getattr(response, "status_code", None),
                (time.perf_counter() - started) * 1000,
            ),
        )
        return response

    return wrapped

"""Reusable, safe CRUD views for Django REST Framework applications."""

import os
import warnings

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.db.models import Avg, Count, Max, Min, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import URLPattern, URLResolver, get_resolver
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from django_api_helper.decorators import check_table_permissions, error_handling, error_response
from django_api_helper.filters import DynamicFilterSetCreator
from django_api_helper.pagination import CustomPageNumberPagination
from django_api_helper.serializers import (
    DEFAULT_SENSITIVE_FIELD_NAMES,
    FileUploadSerializer,
    normalize_field_list,
    redact_sensitive_data,
    serialize_related_object,
)


class GenericCRUDView(generics.GenericAPIView):
    """CRUD endpoint using ``?pk=`` for details and optional nested output."""

    permission_classes = []
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_class = None
    model = None
    pagination_class = CustomPageNumberPagination
    model_name = None
    app_label = None

    allow_aggregate = False
    allowed_aggregate_methods = []
    allowed_aggregate_fields = []
    select_related_fields = ()
    prefetch_related_fields = ()
    include_sensitive_fields = False
    sensitive_field_names = DEFAULT_SENSITIVE_FIELD_NAMES

    AGGREGATE_FUNC_MAP = {"sum": Sum, "avg": Avg, "min": Min, "max": Max, "count": Count}

    def __init__(self, **kwargs):
        if self.model is None:
            raise TypeError("GenericCRUDView subclasses must define model.")
        self.app_label = self.model._meta.app_label
        self.model_name = self.model._meta.model_name
        if self.filterset_class is None:
            self.filterset_class = DynamicFilterSetCreator(self.model).get_filterset()
        super().__init__(**kwargs)

    def squash(self, obj, include=None, exclude=None):
        """Project only root response fields. Exclude has precedence over include."""
        include_fields = set(normalize_field_list(include))
        exclude_fields = set(normalize_field_list(exclude))
        if not isinstance(obj, dict):
            return obj
        return {
            key: value for key, value in obj.items()
            if (not include_fields or key in include_fields) and key not in exclude_fields
        }

    def project_response(self, data, request):
        include = request.META.get("HTTP_X_INCLUDE")
        exclude = request.META.get("HTTP_X_EXCLUDE")
        if not include and not exclude:
            return data
        if isinstance(data, list):
            return [self.squash(item, include, exclude) for item in data]
        return self.squash(data, include, exclude)

    def get_queryset(self):
        queryset = self.model.objects.all()
        if self.select_related_fields:
            queryset = queryset.select_related(*self.select_related_fields)
        if self.prefetch_related_fields:
            queryset = queryset.prefetch_related(*self.prefetch_related_fields)

        order_by = self.request.query_params.get("order_by")
        if order_by:
            ordering_fields = [field.strip() for field in order_by.split(",") if field.strip()]
            if not ordering_fields:
                raise ValidationError({"order_by": ["Provide at least one field."]})
            for field in ordering_fields:
                try:
                    self.model._meta.get_field(field.lstrip("-"))
                except FieldDoesNotExist:
                    raise ValidationError({"order_by": [f"Unknown ordering field: {field.lstrip('-')}."]})
            queryset = queryset.order_by(*ordering_fields)

        filterset = self.filterset_class(self.request.query_params, queryset=queryset)
        if not filterset.is_valid():
            raise ValidationError(filterset.errors)
        return filterset.qs

    def get_serializer_class(self, requested_depth=1):
        return self.serializer_class

    def serialize_instance(self, instance, requested_depth=1, nested=False):
        if nested:
            data = serialize_related_object(
                instance, requested_depth,
                include_sensitive_fields=self.include_sensitive_fields,
                sensitive_field_names=self.sensitive_field_names,
            )
        else:
            data = self.get_serializer_class(requested_depth)(instance, context=self.get_serializer_context()).data
        return redact_sensitive_data(data, self.include_sensitive_fields, self.sensitive_field_names)

    def get_serialized_data(self, queryset, requested_depth=1, nested=False):
        if nested:
            return [self.serialize_instance(item, requested_depth, True) for item in queryset]
        data = self.get_serializer_class(requested_depth)(queryset, many=True, context=self.get_serializer_context()).data
        return redact_sensitive_data(data, self.include_sensitive_fields, self.sensitive_field_names)

    def get_requested_depth(self, request):
        minimum = getattr(settings, "SERIALIZER_MIN_DEPTH", 1)
        maximum = getattr(settings, "SERIALIZER_MAX_DEPTH", 3)
        try:
            requested = int(request.query_params.get("depth", minimum))
        except (TypeError, ValueError):
            raise ValidationError({"depth": ["Depth must be an integer."]})
        return min(maximum, max(minimum, requested))

    def get_aggregate_results(self, queryset):
        if not self.allow_aggregate:
            return None
        raw = self.request.query_params.get("aggregate")
        if not raw:
            return None
        expressions = {}
        for token in (part.strip() for part in raw.split(",") if part.strip()):
            if token.count(":") != 1:
                raise ValidationError({"aggregate": ["Use method:field[,method:field]."]})
            method, field = token.split(":", 1)
            method = method.strip().lower()
            field = field.strip()
            if method not in self.AGGREGATE_FUNC_MAP:
                raise ValidationError({"aggregate": [f"Unsupported aggregation: {method}."]})
            if self.allowed_aggregate_methods and method not in self.allowed_aggregate_methods:
                raise ValidationError({"aggregate": [f"Aggregation method is not allowed: {method}."]})
            if self.allowed_aggregate_fields and field not in self.allowed_aggregate_fields:
                raise ValidationError({"aggregate": [f"Aggregation field is not allowed: {field}."]})
            try:
                self.model._meta.get_field(field)
            except FieldDoesNotExist:
                raise ValidationError({"aggregate": [f"Unknown aggregation field: {field}."]})
            expressions[f"{method}_{field}"] = self.AGGREGATE_FUNC_MAP[method](field)
        return queryset.aggregate(**expressions) if expressions else None

    def require_pk(self, request):
        pk = request.query_params.get("pk")
        if not pk:
            raise ValidationError({"pk": ["This query parameter is required."]})
        return pk

    def get_single(self, pk, requested_depth=1, nested=False):
        instance = get_object_or_404(self.queryset, pk=pk)
        return self.serialize_instance(instance, requested_depth, nested)

    @error_handling
    def get(self, request, *args, **kwargs):
        self.queryset = self.get_queryset()
        requested_depth = self.get_requested_depth(request)
        nested = bool(request.query_params.get("nested"))
        pk = request.query_params.get("pk")
        if pk:
            return Response(self.project_response(self.get_single(pk, requested_depth, nested), request))

        aggregates = self.get_aggregate_results(self.queryset)
        if aggregates is not None:
            return Response({"aggregates": aggregates})
        page = self.paginate_queryset(self.queryset)
        records = page if page is not None else self.queryset
        data = self.project_response(self.get_serialized_data(records, requested_depth, nested), request)
        return self.get_paginated_response(data) if page is not None else Response(data)

    @check_table_permissions
    @error_handling
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return error_response("validation_error", "Request validation failed.", status.HTTP_400_BAD_REQUEST, serializer.errors)
        with transaction.atomic():
            instance = serializer.save()
        return Response(self.serialize_instance(instance), status=status.HTTP_201_CREATED)

    @check_table_permissions
    @error_handling
    def patch(self, request, *args, **kwargs):
        instance = get_object_or_404(self.get_queryset(), pk=self.require_pk(request))
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response("validation_error", "Request validation failed.", status.HTTP_400_BAD_REQUEST, serializer.errors)
        with transaction.atomic():
            instance = serializer.save()
        return Response(self.serialize_instance(instance))

    @check_table_permissions
    @error_handling
    def delete(self, request, *args, **kwargs):
        instance = get_object_or_404(self.get_queryset(), pk=self.require_pk(request))
        with transaction.atomic():
            instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GenericBulkCreateView(GenericCRUDView):
    """Generic CRUD view that also accepts a JSON list for serializer-based bulk creation."""

    parser_classes = (JSONParser,)
    upload_cap = 1000

    @check_table_permissions
    @error_handling
    def post(self, request, *args, **kwargs):
        is_bulk = isinstance(request.data, list)
        if is_bulk and len(request.data) > self.upload_cap:
            return error_response("upload_limit_exceeded", "The upload exceeds this view's record limit.", status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(data=request.data, many=is_bulk)
        if not serializer.is_valid():
            return error_response("validation_error", "Request validation failed.", status.HTTP_400_BAD_REQUEST, serializer.errors)
        with transaction.atomic():
            instances = serializer.save()
        if not is_bulk:
            return Response(self.serialize_instance(instances), status=status.HTTP_201_CREATED)
        return Response([self.serialize_instance(instance) for instance in instances], status=status.HTTP_201_CREATED)


class GenericObjectPermissionView(generics.GenericAPIView):
    """Legacy owner-only object permission view."""

    model = None
    serializer_class = None
    owner_field_name = "created_by"

    def check_owner(self, obj, user):
        return getattr(obj, self.owner_field_name) == user

    def get_object(self, pk):
        obj = get_object_or_404(self.model, pk=pk)
        if not self.check_owner(obj, self.request.user) and not self.request.user.is_superuser:
            raise PermissionDenied()
        return obj

    @error_handling
    def get(self, request, pk, *args, **kwargs):
        return Response(self.get_serializer(self.get_object(pk)).data)

    @error_handling
    def post(self, request, pk, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(pk), data=request.data)
        if not serializer.is_valid():
            return error_response("validation_error", "Request validation failed.", status.HTTP_400_BAD_REQUEST, serializer.errors)
        with transaction.atomic():
            instance = serializer.save()
        return Response(self.get_serializer(instance).data)

    @error_handling
    def delete(self, request, pk, *args, **kwargs):
        return error_response("method_not_allowed", "This legacy view does not implement permission deletion.", status.HTTP_405_METHOD_NOT_ALLOWED)


class GenericBulkUploadView(generics.GenericAPIView):
    """Deprecated optional django-import-export upload endpoint."""

    parser_classes = (MultiPartParser, FormParser)
    model = None
    upload_cap = 1000
    serializer_class = None
    resource_class = None

    def get_serializer_class(self):
        return FileUploadSerializer if self.request.method == "GET" else self.serializer_class

    @error_handling
    def get(self, request, *args, **kwargs):
        return Response(self.get_serializer().data)

    @error_handling
    def post(self, request, *args, **kwargs):
        warnings.warn("GenericBulkUploadView is deprecated; use a dedicated upload endpoint.", DeprecationWarning, stacklevel=2)
        try:
            import tablib
        except ImportError:
            return error_response("optional_dependency_missing", "Bulk uploads require the 'uploads' optional dependency.", status.HTTP_501_NOT_IMPLEMENTED)
        if not self.resource_class:
            return error_response("upload_not_configured", "This upload view has no resource class.", status.HTTP_400_BAD_REQUEST)
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return error_response("validation_error", "Request validation failed.", status.HTTP_400_BAD_REQUEST, {"file": ["This field is required."]})
        suffix = os.path.splitext(uploaded_file.name)[1].lower()
        formats = {".csv": "csv", ".xls": "xlsx", ".xlsx": "xlsx"}
        if suffix not in formats:
            return error_response("unsupported_file_type", "Only CSV and Excel files are supported.", status.HTTP_400_BAD_REQUEST)
        payload = uploaded_file.read()
        dataset = tablib.Dataset().load(payload.decode("utf-8") if suffix == ".csv" else payload, format=formats[suffix])
        if dataset.height > self.upload_cap:
            return error_response("upload_limit_exceeded", "The upload exceeds this view's record limit.", status.HTTP_400_BAD_REQUEST)
        result = self.resource_class().import_data(dataset, dry_run=False)
        if result.has_errors():
            return error_response("upload_validation_error", "The upload contains invalid rows.", status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Data uploaded successfully"}, status=status.HTTP_201_CREATED)


class ReadOnlyView(GenericCRUDView):
    """CRUD read endpoint with an optional secure file download response."""

    download_field = None

    def post(self, request, *args, **kwargs):
        return error_response("method_not_allowed", "This view is read-only.", status.HTTP_405_METHOD_NOT_ALLOWED)

    patch = post
    delete = post

    @error_handling
    def dispatch(self, request, *args, **kwargs):
        if request.method.lower() != "get" or str(request.GET.get("download", "")).lower() not in {"1", "true", "yes"}:
            return super().dispatch(request, *args, **kwargs)
        pk = request.GET.get("pk") or kwargs.get("pk")
        if not pk:
            return error_response("validation_error", "Request validation failed.", status.HTTP_400_BAD_REQUEST, {"pk": ["This query parameter is required."]})
        obj = get_object_or_404(self.model, pk=pk)
        field_name = self.download_field
        if field_name is None:
            field_name = next((field.name for field in self.model._meta.fields if field.get_internal_type() == "FileField"), None)
        file_field = getattr(obj, field_name, None) if field_name else None
        if not file_field:
            return error_response("not_found", "The requested file was not found.", status.HTTP_404_NOT_FOUND)
        return FileResponse(file_field.open("rb"), as_attachment=True, filename=os.path.basename(file_field.name))


class APIIndexView(APIView):
    """Return named endpoints belonging to ``app_name``."""

    permission_classes = []
    app_name = ""

    @error_handling
    def get(self, request):
        if not self.app_name:
            return error_response("api_not_configured", "app_name must be configured for APIIndexView.", status.HTTP_400_BAD_REQUEST)
        endpoints = {}

        def extract_urls(patterns, parent=""):
            for pattern in patterns:
                if isinstance(pattern, URLPattern) and pattern.lookup_str.startswith(f"{self.app_name}."):
                    endpoints[pattern.name or pattern.lookup_str] = request.build_absolute_uri("/" + (parent + str(pattern.pattern)).lstrip("/"))
                elif isinstance(pattern, URLResolver):
                    extract_urls(pattern.url_patterns, parent + str(pattern.pattern))

        extract_urls(get_resolver().url_patterns)
        return Response(endpoints)

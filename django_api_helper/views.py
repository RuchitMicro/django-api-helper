import tablib  # Ensure tablib is installed
import os

from typing                 import Any, Dict, List, Optional

# Django 
from django.db              import transaction
from django.db.models       import Avg, Count, Max, Min, Sum, QuerySet
from django.conf            import settings
from django.shortcuts       import get_object_or_404
from django.core.exceptions import FieldDoesNotExist
from django.http                    import HttpResponse, FileResponse, JsonResponse, HttpResponseRedirect, Http404, HttpResponseForbidden, HttpResponseBadRequest, HttpResponseServerError
from django.urls            import get_resolver, URLPattern, URLResolver

# DRF
from rest_framework             import generics, status
from rest_framework.response    import Response
from rest_framework.filters     import SearchFilter
from rest_framework.exceptions  import PermissionDenied
from rest_framework.parsers     import MultiPartParser, FormParser
from rest_framework.views       import APIView
from rest_framework.parsers     import JSONParser
from rest_framework.exceptions import ValidationError


# Filters
from django_filters.rest_framework  import DjangoFilterBackend
from django_filters                 import rest_framework as filters

# Helpers
from django_api_helper.pagination   import CustomPageNumberPagination
from django_api_helper.decorators   import check_object_permissions, check_table_permissions, error_handling
from django_api_helper.filters      import DynamicFilterSetCreator
from django_api_helper.serializers  import serialize_related_object, create_file_upload_serializer, FileUploadSerializer
from django.db.models.signals       import post_save






class GenericCRUDView(generics.GenericAPIView):
    '''
        Generic CRUD View
        -----------------
        This view is used to create a generic CRUD view for any model.
        It creates a view with the following endpoints:
            - GET /api/model_name/ (List)
            - GET /api/model_name/?pk=1 (Single)
            - POST /api/model_name/ (Create)
            - PATCH /api/model_name/?pk=1 (Update)
            - DELETE /api/model_name/?pk=1 (Delete)
        It also supports:
            - Pagination
            - Filtering
            - Aggregation
                
                - GET /api/model_name/?aggregate=sum:amount,avg:rate # only if allow_aggregate=True
                - GET /api/model_name/?status=active&aggregate=count:id

        
        The following attributes must be defined in the child class:
            - permission_classes
            - filter_backends
            - filterset_class
            - model
            - pagination_class
            - serializer_class

            - allow_aggregate: bool                   = False
            - allowed_aggregate_methods: List[str]    = []   # empty ⇒ all allowed
            - allowed_aggregate_fields:  List[str]    = []


    '''
    permission_classes  =   []  # Default permission
    filter_backends     =   [DjangoFilterBackend, SearchFilter]
    filterset_class     =   None
    model               =   None
    pagination_class    =   CustomPageNumberPagination
    model_name          =   None
    app_label           =   None

    allow_aggregate: bool                   = False
    allowed_aggregate_methods: List[str]    = []   # empty ⇒ all allowed
    allowed_aggregate_fields:  List[str]    = []

    AGGREGATE_FUNC_MAP: dict[str, Any] = {
        "sum":   Sum,
        "avg":   Avg,
        "min":   Min,
        "max":   Max,
        "count": Count,
    }



    def __init__(self, **kwargs):
        self.app_label  = self.model._meta.app_label
        self.model_name = self.model._meta.model_name
        if self.filterset_class is None:
            # add all fields in filter fields
            # filter_fields = [field.name for field in self.model._meta.get_fields()]
            # self.filterset_class = self.create_dynamic_filterset(self.model, filter_fields)
            self.filterset_class = DynamicFilterSetCreator(self.model).get_filterset()

        super().__init__(**kwargs)


    # Helper method to squash a dictionary
    def squash(self, obj, include=None, exclude=None):
        if include is None:
            include = []
        if exclude is None:
            exclude = []
            
        def _squash(obj, include, exclude):
            if isinstance(obj, dict):
                return {k: _squash(v, include, exclude) for k, v in obj.items() if k in include and k not in exclude}
            elif isinstance(obj, list):
                return [_squash(item, include, exclude) for item in obj]
            else:
                return obj
        
        return _squash(obj, include, exclude)

    # Get Query
    def get_queryset(self):
        queryset = self.model.objects.all()

        order_by = self.request.query_params.get('order_by', None)

        if order_by:
            ordering_fields = order_by.split(',')
            # Validate the fields are part of the model
            for field in ordering_fields:
                field_name = field.lstrip('-')
                try:
                    self.model._meta.get_field(field_name)
                except FieldDoesNotExist:
                    raise ValueError(f"Invalid field name for ordering: {field_name}")

            queryset = queryset.order_by(*ordering_fields)

        # Apply additional filters if any
        filtered_queryset = self.filterset_class(self.request.GET, queryset=queryset)
        return filtered_queryset.qs

    # Get Serializer
    def get_serializer_class(self, requested_depth=1):
        return self.serializer_class

    # Get Serialized Data
    def get_serialized_data(self, queryset, requested_depth=1, nested=False):
        if nested:
            serialized_data = [serialize_related_object(obj, requested_depth) for obj in queryset]
        else:
            serialized_data = self.get_serializer_class()(queryset, many=True)
            serialized_data = serialized_data.data
        return serialized_data

    # Helper method to determine the requested depth for nested serialization.
    # You can also pass a depth parameter from the front end with ?depth=3
    def get_requested_depth(self, request):
        # Fetch depth limits from settings with fallback to default values.
        SERIALIZER_MIN_DEPTH = getattr(settings, 'SERIALIZER_MIN_DEPTH', 1)
        SERIALIZER_MAX_DEPTH = getattr(settings, 'SERIALIZER_MAX_DEPTH', 3)
        try:
            requested_depth = int(request.query_params.get('depth', SERIALIZER_MIN_DEPTH))
            return requested_depth
        except ValueError:
            requested_depth = SERIALIZER_MIN_DEPTH
        return min(SERIALIZER_MAX_DEPTH, max(SERIALIZER_MIN_DEPTH, requested_depth))
    
    def get_aggregate_results(self, queryset: QuerySet) -> Optional[Dict[str, Any]]:
        """
        Parse ?aggregate=sum:amount,avg:rate
        and return {"sum_amount": ..., "avg_rate": ...} or None
        """
        if not self.allow_aggregate:
            return None

        raw = self.request.query_params.get("aggregate")
        if not raw:
            return None

        expressions: Dict[str, Any] = {}
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
        for token in tokens:
            try:
                method, field = token.split(":", 1)
            except ValueError:
                raise ValidationError("Aggregate format is method:field[,method:field]")

            method = method.lower().strip()
            field  = field.strip()

            # allow‑lists
            if self.allowed_aggregate_methods and method not in self.allowed_aggregate_methods:
                raise ValidationError(f"Aggregation method '{method}' not allowed.")

            if self.allowed_aggregate_fields and field not in self.allowed_aggregate_fields:
                raise ValidationError(f"Aggregation field '{field}' not allowed.")

            try:
                self.model._meta.get_field(field)
            except FieldDoesNotExist:
                raise ValidationError(f"Model has no field '{field}'.")

            try:
                func = self.AGGREGATE_FUNC_MAP[method]
            except KeyError:
                raise ValidationError(f"Unsupported aggregation '{method}'.")

            expressions[f"{method}_{field}"] = func(field)

        return queryset.aggregate(**expressions) if expressions else None

    def get_single(self, pk):
        """
        Helper method to get a single object by primary key.
        """
        try:
            saved_object = get_object_or_404(self.queryset, pk=pk)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer_class()(saved_object)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    # Get List or Single
    # @check_table_permissions
    # @check_object_permissions(permission_prefix='view_')
    @error_handling
    def get(self, request, *args, **kwargs):
        '''
        Handles GET requests:
        - Permission decorators run first (table & object level).
        - Object-level permissions may override self.queryset.
        - Supports single-object fetch by pk, aggregates, or paginated list.
        '''
        # Get the base queryset, already filtered and permission-aware.
        # Important: keep self.queryset in sync, as some decorators or methods rely on it.
        base_qs = self.get_queryset()
        self.queryset = base_qs

        # Check if client requested a single object by pk
        pk = request.GET.get('pk')
        if pk:
            return self.get_single(pk)

        # Compute aggregates after filtering but before pagination
        aggregates = self.get_aggregate_results(base_qs)

        # If aggregates exist, return them immediately (skip list data)
        if aggregates:
            return Response({"aggregates": aggregates}, status=status.HTTP_200_OK)

        # Otherwise, proceed to fetch and return list data
        requested_depth =   self.get_requested_depth(request)   # Controls nesting depth in serialized data
        nested          =   bool(request.GET.get('nested'))              # Force nested structure if requested

        # Paginate the queryset if pagination is enabled
        page = self.paginate_queryset(base_qs)
        if page is not None:
            # Serialize paginated page data
            serialized_data = self.get_serialized_data(page, requested_depth, nested=nested)

            # Optionally squash fields if include/exclude headers are present
            include = request.META.get('HTTP_X_INCLUDE')
            exclude = request.META.get('HTTP_X_EXCLUDE')
            if include or exclude:
                serialized_data = [self.squash(obj, include=include, exclude=exclude) for obj in serialized_data]

            # Return paginated response
            return self.get_paginated_response(serialized_data)

        # Fallback: no pagination; serialize the entire filtered queryset
        serialized_data = self.get_serialized_data(base_qs, requested_depth, nested=nested)
        return Response(serialized_data, status=status.HTTP_200_OK)



    # Create 
    @check_table_permissions
    @error_handling
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer_class()(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



    # Update
    @check_table_permissions
    # @check_object_permissions(permission_prefix='change_')
    @error_handling
    def patch(self, request, *args, **kwargs):
        pk              =   request.GET.get('pk')
        saved_object    =   self.get_queryset().get(pk=pk)
        # Notice the `partial=True` parameter below, indicating a partial update
        serializer = self.get_serializer_class()(saved_object, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



    # Delete
    @check_table_permissions
    # @check_object_permissions(permission_prefix='delete_')
    @error_handling
    def delete(self, request, *args, **kwargs):
        pk                  =   request.GET.get('pk')
        object_to_delete    =   get_object_or_404(self.get_queryset(), pk=pk)
        object_to_delete.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
class GenericBulkCreateView(GenericCRUDView):
    """
    A Generic View for bulk creation of model instances.

    Inherits listing and detail endpoints from GenericCRUDView,
    but overrides POST to support bulk JSON uploads via an array of objects.
    Enforces an upload cap and performs chunked bulk inserts for large datasets.

    Attributes:
        model           : The model class to create instances of.
        permission_classes: List of permission classes to apply.
        serializer_class: Serializer class for the model.
        upload_cap      : Maximum number of records allowed per bulk request.
        parser_classes  : List of parsers to handle incoming data formats.

    """
    parser_classes  = (JSONParser,)
    upload_cap      = 1000  # default maximum records per bulk request

    @check_table_permissions
    @error_handling
    def post(self, request, *args, **kwargs):
        data = request.data
        is_bulk = isinstance(data, list)

        # For bulk, enforce upload cap
        if is_bulk and len(data) > self.upload_cap:
            return Response(
                {"error": f"Upload limit exceeded: max {self.upload_cap} records allowed per request."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer_class()(data=data, many=is_bulk)
        serializer.is_valid(raise_exception=True)

        if is_bulk:
            model_cls = self.model
            instances = [model_cls(**item) for item in serializer.validated_data]
            created_instances = []
            # Chunked bulk_create for performance and DB safety
            with transaction.atomic():
                for i in range(0, len(instances), self.upload_cap):
                    batch = instances[i:i + self.upload_cap]
                    created_batch = model_cls.objects.bulk_create(batch)
                    for instance in created_batch:
                        post_save.send(sender=model_cls, instance=instance, created=True)
                    created_instances.extend(created_batch)

            resp_ser = self.get_serializer_class()(created_instances, many=True)
            return Response(resp_ser.data, status=status.HTTP_201_CREATED)
        else:
            instance = serializer.save()
            resp_ser = self.get_serializer_class()(instance)
            return Response(resp_ser.data, status=status.HTTP_201_CREATED)


class GenericObjectPermissionView(generics.GenericAPIView):
    '''
        Object Permission View
        ----------------------
        This view is used to manage object-level permissions for any given model.
        It allows the owner of an object to manage permissions.
        
        Attributes to define in the child class:
            - model
            - serializer_class
            - owner_field_name (field in the model that refers to the owner)
    '''
    model               =   None
    serializer_class    =   None
    owner_field_name    =   'created_by'


    def check_owner(self, object, user):
        return getattr(object, self.owner_field_name) == user

    def get_object(self, pk):
        obj = get_object_or_404(self.model, pk=pk)
        if not self.check_owner(obj, self.request.user) and not self.request.user.is_superuser:
            raise PermissionDenied("You do not have permission to modify this object.")
        return obj

    # GET permissions for an object
    def get(self, request, pk, *args, **kwargs):
        obj         = self.get_object(pk)
        serializer  = self.serializer_class(obj, context={'request': request})
        return Response(serializer.data)

    # POST/PUT to update permissions
    def post(self, request, pk, *args, **kwargs):
        obj         = self.get_object(pk)
        serializer  = self.serializer_class(obj, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # DELETE to remove specific permissions
    def delete(self, request, pk, *args, **kwargs):
        # Implement logic to handle deletion of specific permissions
        pass


class GenericBulkUploadView(generics.GenericAPIView):
    parser_classes      = (MultiPartParser, FormParser)
    model               = None  # Model should be set in subclass
    upload_cap          = 1000  # Default cap, can be overridden in subclass
    serializer_class    = None  # Serializer class should be set in subclass
    resource_class      = None  # Resource class for django-import-export
    
    def get_serializer_class(self):
        if self.request.method == 'GET':
            self.serializer_class = FileUploadSerializer
        return self.serializer_class

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer()
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

        if not self.resource_class:
            raise ValueError('Resource class not defined for the view.')

        resource = self.resource_class()
        data = file.read()

        try:
            if file.name.endswith('.csv'):
                dataset = tablib.Dataset().load(data.decode('utf-8'), format='csv')
            elif file.name.endswith(('.xls', '.xlsx')):
                dataset = tablib.Dataset().load(data, format='xlsx')
            else:
                return Response({'error': 'Unsupported file format'}, status=status.HTTP_400_BAD_REQUEST)

            # Check upload cap after creating the dataset
            if dataset.height > self.upload_cap:
                return Response({'error': f'The number of records in your dataset exceeds the limit of {self.upload_cap}. Please upload your file in smaller chunks.'}, status=status.HTTP_400_BAD_REQUEST)

            # Perform the import
            result = resource.import_data(dataset, dry_run=False)

            # Check for errors in result
            if result.has_errors():
                # Collect errors from the result
                error_messages = self.format_errors(result)
                return Response({'error': 'Errors occurred during import', 'details': error_messages}, status=status.HTTP_400_BAD_REQUEST)

            return Response({'message': 'Data uploaded successfully'}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': f'Something went wrong: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

    def format_errors(self, result):
        error_messages = []
        pretty_error_messages = []

        for line, errors in result.row_errors():
            # Line is the line number from the dataset starting at 1
            # Errors is a list of errors encountered processing the row
            for error in errors:
                # Constructing the technical error message
                error_message = f"Line {line}: {str(error.error)}"
                if hasattr(error, 'traceback'):
                    error_message += f" | Details: {error.traceback}"
                error_messages.append(error_message)

                # Constructing a user-friendly error message
                column_name = "the relevant column"  # Placeholder, should be determined based on the error context
                # Assuming error.error holds the exception or a custom error object that can be parsed
                if "This field cannot be null." in str(error.error):
                    user_friendly_message = f"There's missing information on line {line}, in {column_name} of your uploaded file. Please make sure all required fields are filled in."
                elif "Invalid value" in str(error.error):
                    user_friendly_message = f"There's an incorrect value on line {line}, in {column_name} of your uploaded file. Please double-check the information."
                else:
                    # Generic catch-all message
                    user_friendly_message = f"There's an issue with the information on line {line}, in {column_name} of your uploaded file. Please review it for accuracy."
                pretty_error_messages.append(user_friendly_message)

        return {"technical": error_messages, "user_friendly": pretty_error_messages}


##### Generic API Views #####
class ReadOnlyView(GenericCRUDView):
    def post(self, request, *args, **kwargs):
        return HttpResponseForbidden()
    
    def patch(self, request, *args, **kwargs):
        return HttpResponseForbidden()
    
    def delete(self, request, *args, **kwargs):
        return HttpResponseForbidden()
    
    download_field = None        # e.g. "video"
    
    def dispatch(self, request, *args, **kwargs):
        """
        If the caller added ?download=true (or 1 / yes) to a GET request,
        stream the file attached to <download_field>; otherwise fall back
        to the normal DRF dispatch flow (list/detail/create/…).
        """
        if (
            request.method.lower() == "get"
            and str(request.GET.get("download", "")).lower() in ("1", "true", "yes")
        ):
            pk = request.GET.get("pk") or kwargs.get("pk")
            if not pk:
                return Response(
                    {"detail": "pk query-param is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                obj = self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                raise Http404("Object not found")

            # Find the correct FileField --------------------------------
            field_name = self.download_field
            if field_name is None:                       # fallback: first FileField on the model
                for f in self.model._meta.fields:
                    if f.get_internal_type() == "FileField":
                        field_name = f.name
                        break

            file_field = getattr(obj, field_name, None)
            if not file_field:
                return Response(
                    {"detail": "No file attached to this object."},
                    status=status.HTTP_404_NOT_FOUND
                )

            return FileResponse(
                file_field.open("rb"),
                as_attachment=True,
                filename=os.path.basename(file_field.name)
            )

        # No ?download=true → normal GenericAPIView life-cycle
        return super().dispatch(request, *args, **kwargs)


# API Index
class APIIndexView(APIView):
    permission_classes  =   []
    app_name            =   ''  

    def get(self, request):
        if not self.app_name:
            return Response({"error": "app_name is not set for APIIndexView"}, status=status.HTTP_400_BAD_REQUEST)
        
        resolver = get_resolver()
        api_endpoints = {}

        def extract_urls(urlpatterns, parent_pattern=''):
            for pattern in urlpatterns:
                if isinstance(pattern, URLPattern):
                    if pattern.lookup_str.startswith(f'{self.app_name}.'):
                        name = pattern.name or pattern.lookup_str
                        full_path = parent_pattern + str(pattern.pattern)
                        url = request.build_absolute_uri("/" + full_path.lstrip("/"))
                        url = url.replace('<', '&lt;').replace('>', '&gt;')  # HTML safe if needed
                        api_endpoints[name] = url
                elif isinstance(pattern, URLResolver):
                    nested_pattern = parent_pattern + str(pattern.pattern)
                    extract_urls(pattern.url_patterns, nested_pattern)

        extract_urls(resolver.url_patterns)

        return Response(api_endpoints)
    
# Django API Helper

Reusable Django REST Framework views for conventional model CRUD endpoints. The package is a library for Django projects, not a standalone Django application.

## Compatibility and installation

| Package | Supported versions |
| --- | --- |
| Python | 3.9 to 3.13 |
| Django | 4.2 LTS and 5.2 LTS |
| Django REST Framework | 3.14 or newer |
| django-filter | 23.5 or newer |

```bash
python -m pip install django-api-helper
```

The legacy `GenericBulkUploadView` additionally requires the optional upload extra:

```bash
python -m pip install "django-api-helper[uploads]"
```

## Basic CRUD view

```python
from django_api_helper.views import GenericCRUDView
from .models import Book
from .serializers import BookSerializer


class BookView(GenericCRUDView):
    model = Book
    serializer_class = BookSerializer
```

```python
from django.urls import path
from .views import BookView

urlpatterns = [path("api/books/", BookView.as_view())]
```

The endpoint supports:

| Request | Behavior |
| --- | --- |
| `GET /api/books/` | List records, with the configured pagination class. |
| `GET /api/books/?pk=1` | Retrieve one record. |
| `POST /api/books/` | Create a record. |
| `PATCH /api/books/?pk=1` | Partially update a record. |
| `DELETE /api/books/?pk=1` | Delete a record. |
| `GET /api/books/?order_by=-created_at` | Order by concrete model fields. |
| `GET /api/books/?nested=1&depth=2` | Serialize forward relations to a bounded depth. |

## Filtering and aggregation

If `filterset_class` is omitted, a filter set is generated from the model's concrete fields. Numeric fields accept `_min`, `_max`, and `_exact`; date fields accept exact, `_from`, and `_to` values. Invalid values return a safe validation response.

Enable aggregation explicitly:

```python
class InvoiceView(GenericCRUDView):
    model = Invoice
    serializer_class = InvoiceSerializer
    allow_aggregate = True
    allowed_aggregate_methods = ["sum", "avg"]
    allowed_aggregate_fields = ["amount"]
```

`GET /api/invoices/?status=paid&aggregate=sum:amount,avg:amount` returns `{"aggregates": ...}`. Aggregates run after filtering and before pagination.

For predictable nested-query performance, configure relations explicitly instead of relying on automatic joins:

```python
class InvoiceView(GenericCRUDView):
    select_related_fields = ("customer",)
    prefetch_related_fields = ("items",)
```

## Field projection and sensitive data

`X-Include` and `X-Exclude` preserve the historic header interface. Values may be comma- or semicolon-separated top-level response fields. When both are present, exclusion wins. Projection applies to detail, list, paginated, and nested responses, but never changes aggregation keys.

```http
X-Include: id,title,owner
X-Exclude: owner
```

Password and common credential fields are removed recursively by default, including in related user objects and custom serializer output. The `user` relation itself is not hidden. Consumers must deliberately opt in to expose fields:

```python
class InternalAccountView(GenericCRUDView):
    include_sensitive_fields = True
```

Use `sensitive_field_names` to replace the default protected-name set. Do not make this option request-controlled.

## Errors, logging, and permissions

Expected failures use a stable payload:

```json
{
  "code": "validation_error",
  "detail": "Request validation failed.",
  "errors": {"field": ["A validation message."]}
}
```

Internal exceptions return only `internal_error` and are logged to the `django_api_helper` logger with traceback, request method/path, view, model, status, and a bounded `X-Request-ID` when supplied. Debug logging also emits safe completion timing. Request data and exception text are not sent to clients.

`@check_table_permissions` uses Django's matching model permission: `view_*` for GET, `add_*` for POST, `change_*` for PATCH/PUT, and `delete_*` for DELETE.

## Legacy helpers and migration notes

`GenericBulkCreateView`, `GenericObjectPermissionView`, and existing import paths remain available. `GenericBulkUploadView` is deprecated and requires the optional upload dependency; new applications should use a dedicated validated upload endpoint.

Version 0.1.0 keeps successful response formats and the existing query-string/header interfaces. Error payloads are intentionally standardized so raw internal exceptions and technical import errors are no longer exposed.

## Development

```bash
python -m unittest django_api_helper.tests
python -m compileall -q django_api_helper
```

The GitHub Actions matrix runs these checks across the supported Python and Django versions.

# AGENTS.md

`django-api-helper` is a dependency-light Django REST Framework library for consumer projects. It provides reusable CRUD views, filtering, pagination, serializers, permissions, and safe error handling. It is not a standalone Django application.

## Supported stack

- Python 3.9 to 3.13
- Django 4.2 LTS and 5.2 LTS
- Django REST Framework 3.14+
- django-filter 23.5+

## Project map

- `README.md`: canonical installation, compatibility, API, and migration documentation.
- `setup.py` and `pyproject.toml`: package metadata, build configuration, dependencies, and optional extras.
- `django_api_helper/views.py`: `GenericCRUDView` and legacy public views.
- `django_api_helper/decorators.py`: permission checks, safe error responses, and structured logging helpers.
- `django_api_helper/filters.py`: cached dynamic model filter-set generation.
- `django_api_helper/serializers.py`: dynamic serializers, recursive relation serialization, and sensitive-data redaction.
- `django_api_helper/pagination.py`: bounded-link page-number pagination.
- `django_api_helper/tests.py`: self-contained regression suite.
- `.github/workflows/tests.yml`: supported Python and Django CI matrix.

## Compatibility and security rules

- Preserve successful CRUD behavior and query-string interfaces: `?pk=`, `?aggregate=`, `?depth=`, `?nested`, and `order_by`.
- Preserve `X-Include` and `X-Exclude`; they select top-level response fields and exclusion wins.
- Do not expose passwords or credential-like fields by default, including through nested relations or custom serializer output. Only a view-level `include_sensitive_fields = True` may opt out.
- Keep error responses in the `code`, `detail`, and optional `errors` envelope. Never return exception messages, tracebacks, uploaded-file contents, or request bodies to clients.
- Log unexpected errors with `logger.exception` through the `django_api_helper` logger. Logging fields must be safe metadata only: request method/path, bounded request ID, view, model, status, and duration.
- Keep the standard Django permission mapping: GET `view_*`, POST `add_*`, PATCH/PUT `change_*`, DELETE `delete_*`.

## Performance rules

- Reuse cached dynamic filter-set classes. Do not add per-request class generation or cache entries keyed by request data.
- Use `select_related_fields` and `prefetch_related_fields` on consumer views for known relation paths. Do not add speculative automatic joins.
- Keep pagination links bounded by `page_link_window`; retain first, last, previous, and next links. Preserve the `links.pages` response key.
- Keep `max_page_size` finite to prevent oversized responses.
- Prefer queryset operations and serializer behavior that avoid N+1 queries. Preserve the nested-depth cycle guard.

## Legacy surface

- Retain public view imports such as `GenericBulkCreateView`, `GenericObjectPermissionView`, `GenericBulkUploadView`, `ReadOnlyView`, and `APIIndexView` unless a major-version migration explicitly authorizes removal.
- `GenericBulkUploadView` is deprecated and requires the optional `uploads` extra. Keep optional dependencies lazily imported so core package imports remain lightweight.
- Do not recreate removed starter-app boilerplate (`admin.py`, `models.py`, `urls.py`, migrations, duplicate package README, or empty requirements file) unless the package gains a concrete runtime need for it.

## Validation

Run these after changes:

```bash
python -m unittest django_api_helper.tests
python -m compileall -q django_api_helper
python setup.py check
python -m pip wheel --no-deps . --wheel-dir /tmp/django-api-helper-wheel
```

Add or update focused regression tests for each behavior change, especially error confidentiality, permissions, field projection, sensitive-field redaction, nested serialization, pagination bounds, and filter validation.

## Edit style

- Keep changes surgical and backward compatible.
- Keep comments concise and useful for security, compatibility, debugging, or non-obvious performance behavior.
- Avoid em dashes in comments and documentation.
- Update `README.md` when a public behavior, configuration option, dependency, or compatibility guarantee changes.

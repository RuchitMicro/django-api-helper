
# Generic CRUD View User Manual

## Overview
The Generic CRUD View in Django is a powerful tool for creating RESTful APIs with Create, Read, Update, and Delete functionalities. This user manual covers how to set up and use the Generic CRUD View, including configuring URLs, permissions, pagination, and views.

## Setting Up
Before using the Generic CRUD View, ensure you have Django and Django REST Framework installed in your environment. Additionally, install `django-filter` and `django-guardian` for advanced filtering and object-level permissions.

### Dependencies:
- Django
- Django REST Framework
- django-filter
- django-guardian

## Creating a CRUD View
To create a CRUD view for your model, inherit from `GenericCRUDView` and specify the required attributes.

### Example:
```python
from myapp.views import GenericCRUDView
from myapp.models import MyModel
from myapp.serializers import MyModelSerializer
from myapp.filters import MyModelFilterSet

class MyModelCRUDView(GenericCRUDView):
    model = MyModel
    serializer_class = MyModelSerializer
    filterset_class = MyModelFilterSet
    # Define other attributes like permission_classes, pagination_class
```

## URL Configuration
Set up URL patterns to route requests to your CRUD view.

### Example:
```python
from django.urls import path
from myapp.views import MyModelCRUDView

urlpatterns = [
    path('api/mymodel/', MyModelCRUDView.as_view(), name='mymodel-list'),
    # Include other CRUD URLs
]
```

## Permissions
Permissions can be managed at both table and object levels using decorators.

### Table-level Permissions:
Use `@check_table_permissions('app_name.permission_name')` to check if the user has the necessary table-level permission.

### Object-level Permissions:
Use `@check_object_permissions('app_name.permission_name')` for object-level permissions check.

## Pagination
Customize pagination by setting the `pagination_class` attribute in your view.

### Example:
```python
from rest_framework.pagination import PageNumberPagination

class CustomPagination(PageNumberPagination):
    page_size = 10
    # Define other pagination settings

# In your CRUD view
class MyModelCRUDView(GenericCRUDView):
    pagination_class = CustomPagination
    # Other attributes...
```

## Using the CRUD View
The CRUD view automatically provides endpoints for listing, retrieving, creating, updating, and deleting objects.

### List Objects:
`GET /api/model_name/`

### Retrieve a Single Object:
`GET /api/model_name/?pk=1`

### Create a New Object:
`POST /api/model_name/`

### Update an Object:
`PUT /api/model_name/?pk=1`

### Delete an Object:
`DELETE /api/model_name/?pk=1`

## Advanced Filtering
Leverage `django-filter` to provide advanced filtering capabilities. Define your filters in `filterset_class`.

## Conclusion
The Generic CRUD View simplifies building RESTful APIs in Django, providing a robust and flexible framework for handling CRUD operations with ease.
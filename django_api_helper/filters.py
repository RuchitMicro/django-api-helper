from functools                          import lru_cache
from django.contrib.contenttypes.fields import GenericForeignKey
from django_filters                     import rest_framework as filters
from django_filters                     import ModelMultipleChoiceFilter
from django.db.models                   import DateField, DateTimeField, ForeignKey, BooleanField, IntegerField, FloatField, PositiveIntegerField, Q


    
# Class to create a dynamic FilterSet class based on the given model and filter fields.
class DynamicFilterSetCreator:
    def __init__(self, model, search_fields=None):
        self.model          = model
        self.search_fields  = search_fields

    @lru_cache(maxsize=32)
    def get_filterset(self):
        filter_fields = [field.name for field in self.model._meta.get_fields() if field.name != 'search']
        return self.create_filterset(self.model, filter_fields)

    def create_filterset(self, model, filter_fields):
        dynamic_filters = {}
        dynamic_filters['depth'] = self.create_non_querying_number_filter('depth')

        if self.search_fields:
            dynamic_filters['search']=filters.CharFilter(label='Search                     ' ,method=self.filter_search)

        for field_name in filter_fields:
            field = model._meta.get_field(field_name)

            if isinstance(field, GenericForeignKey): # Ignore GenericForeignKey fields
                continue

            if isinstance(field, (DateField, DateTimeField)):
                dynamic_filters.update(self.create_date_range_filters(field_name))
            elif isinstance(field, (IntegerField, FloatField, PositiveIntegerField)):
                dynamic_filters.update(self.create_number_range_filters(field.name))
            else:
                dynamic_filters[field_name] = self.create_field_filter(field)

        Meta = type('Meta', (), {'model': model, 'fields': list(dynamic_filters.keys())})
        return type(f'DynamicFilterSet_{model._meta.model_name}', (filters.FilterSet,), dynamic_filters | {'Meta': Meta})
    
    def create_field_filter(self, field):
        if isinstance(field, ForeignKey):
            return ModelMultipleChoiceFilter(queryset=field.related_model.objects.all(), to_field_name='id', conjoined=False)
        elif isinstance(field, BooleanField):
            return filters.BooleanFilter()
        else:
            return filters.CharFilter(lookup_expr='icontains')
    
    # Create a filter for a date field that allows filtering by a range of values
    def create_date_range_filters(self, field_name):
        # Create a method to handle the exact date match
        def filter_by_exact_date(queryset, name, value):
            if value:
                lookup = f'{field_name}__date' if isinstance(queryset.model._meta.get_field(field_name), DateTimeField) else field_name
                return queryset.filter(**{lookup: value})
            return queryset
        return {
            field_name              : filters.DateFilter    (method = filter_by_exact_date),  # Exact date match
            f'{field_name}_from'    : filters.DateFilter    (field_name=field_name, lookup_expr='gte'),  # Start of range
            f'{field_name}_to'      : filters.DateFilter    (field_name=field_name, lookup_expr='lte')  # End of range
        }
    
    # Create a filter for a numeric field that allows filtering by a range of values
    def create_number_range_filters(self, field_name):
        return {
            f'{field_name}_min': filters.NumberFilter(label= f'{field_name}_min', field_name=field_name, lookup_expr='gte'),
            f'{field_name}_max': filters.NumberFilter(label= f'{field_name}_max', field_name=field_name, lookup_expr='lte'),
            f'{field_name}_exact': filters.NumberFilter(label= f'{field_name}_exact', field_name=field_name, lookup_expr='exact'),
        }

    # Create a filter for a numeric field that does not query the database
    def create_non_querying_number_filter(self, field_name):
        class NonQueryingNumberFilter(filters.NumberFilter):
            def filter(self, qs, value):
                # Override the filter method to do nothing
                return qs

        return NonQueryingNumberFilter(field_name=field_name, label=f'{field_name}')


    def filter_search(self, queryset, name, value):
        if not value:
            return queryset

        query = Q()
        for field in self.search_fields:
            field_parts = field.split('__')
            if len(field_parts) > 1:
                # Construct a query for a foreign key relationship
                fk_field = "__".join(field_parts[:-1])
                related_field = field_parts[-1]
                query |= Q(**{f"{fk_field}__{related_field}__icontains": value})
            else:
                # Query for a regular field
                query |= Q(**{f"{field}__icontains": value})

        return queryset.filter(query)



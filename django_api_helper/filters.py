"""Dynamic, model-field-only filter set generation."""

from functools                  import lru_cache

from django.db.models           import BooleanField, DateField, DateTimeField, FloatField, ForeignKey, IntegerField, PositiveIntegerField, Q
from django_filters             import ModelMultipleChoiceFilter
from django_filters             import rest_framework as filters


class DynamicFilterSetCreator:
    def __init__(self, model, search_fields=None):
        self.model              = model
        self.search_fields      = search_fields

    def get_filterset(self):
        return build_dynamic_filterset(self.model, tuple(self.search_fields or ()))


@lru_cache(maxsize=128)
def build_dynamic_filterset(model, search_fields):
    """Create each model/filter combination once, not once per view instance."""
    filter_fields               = [field.name for field in model._meta.fields if field.name != "search"]
    dynamic_filters             = {"depth": NonQueryingNumberFilter(field_name="depth")}
    if search_fields:
        dynamic_filters["search"] = filters.CharFilter(method=build_search_filter(search_fields))
    for field_name in filter_fields:
        field                   = model._meta.get_field(field_name)
        if isinstance(field, (DateField, DateTimeField)):
            dynamic_filters.update(create_date_range_filters(field_name))
        elif isinstance(field, (IntegerField, FloatField, PositiveIntegerField)):
            dynamic_filters.update(create_number_range_filters(field_name))
        else:
            dynamic_filters[field_name] = create_field_filter(field)
    meta                        = type("Meta", (), {"model": model, "fields": list(dynamic_filters)})
    return type(f"DynamicFilterSet_{model._meta.model_name}", (filters.FilterSet,), {**dynamic_filters, "Meta": meta})


class NonQueryingNumberFilter(filters.NumberFilter):
    def filter(self, qs, value):
        return qs


def create_field_filter(field):
    if isinstance(field, ForeignKey):
        return ModelMultipleChoiceFilter(queryset=field.related_model.objects.all(), to_field_name="id", conjoined=False)
    if isinstance(field, BooleanField):
        return filters.BooleanFilter()
    return filters.CharFilter(lookup_expr="icontains")


def create_date_range_filters(field_name):
    def filter_by_exact_date(queryset, name, value):
        if not value:
            return queryset
        field                   = queryset.model._meta.get_field(field_name)
        lookup                  = f"{field_name}__date" if isinstance(field, DateTimeField) else field_name
        return queryset.filter(**{lookup: value})
    return {
        field_name: filters.DateFilter(method=filter_by_exact_date),
        f"{field_name}_from": filters.DateFilter(field_name=field_name, lookup_expr="gte"),
        f"{field_name}_to": filters.DateFilter(field_name=field_name, lookup_expr="lte"),
    }


def create_number_range_filters(field_name):
    return {
        f"{field_name}_min": filters.NumberFilter(field_name=field_name, lookup_expr="gte"),
        f"{field_name}_max": filters.NumberFilter(field_name=field_name, lookup_expr="lte"),
        f"{field_name}_exact": filters.NumberFilter(field_name=field_name, lookup_expr="exact"),
    }


def build_search_filter(search_fields):
    def filter_search(queryset, name, value):
        if not value:
            return queryset
        query                   = Q()
        for field in search_fields:
            query |= Q(**{f"{field}__icontains": value})
        return queryset.filter(query)
    return filter_search

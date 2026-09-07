"""Dynamic serializers and output redaction helpers."""

import json

from django.db                  import models
from rest_framework             import serializers

DEFAULT_SENSITIVE_FIELD_NAMES = frozenset({
    "password", "password_hash", "passwd", "pass_hash", "token", "access_token",
    "refresh_token", "secret", "api_key", "authorization", "private_key",
})


def normalize_field_list(value):
    """Accept the legacy list input plus comma and semicolon separated headers."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value                   = value.strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        if isinstance(value, str):
            value               = [item.strip() for item in value.replace(";", ",").split(",")]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def is_sensitive_name(name, sensitive_field_names=None):
    name                        = str(name).lower()
    names                       = {str(item).lower() for item in (sensitive_field_names or DEFAULT_SENSITIVE_FIELD_NAMES)}
    return name in names or name.endswith("password")


def is_sensitive_field(field, include_sensitive_fields=False, sensitive_field_names=None):
    if include_sensitive_fields:
        return False
    if is_sensitive_name(field.name, sensitive_field_names):
        return True
    storage                     = getattr(field, "storage", None)
    return isinstance(field, (models.FileField, models.ImageField)) and getattr(storage, "default_acl", None) == "private"


def redact_sensitive_data(value, include_sensitive_fields=False, sensitive_field_names=None):
    """Recursively remove credentials even when a consumer uses a custom serializer."""
    if include_sensitive_fields:
        return value
    if isinstance(value, dict):
        return {
            key: redact_sensitive_data(child, False, sensitive_field_names)
            for key, child in value.items()
            if not is_sensitive_name(key, sensitive_field_names)
        }
    if isinstance(value, list):
        return [redact_sensitive_data(child, False, sensitive_field_names) for child in value]
    return value


def create_model_serializer(model_name, include=None, exclude=None, read_only=None,
                            include_sensitive_fields=False, sensitive_field_names=None):
    include_fields              = normalize_field_list(include)
    excluded_fields             = set(normalize_field_list(exclude))
    api_functions               = list(getattr(model_name, "api_meta", {}).get("api_function", []))
    if include_fields:
        fields                  = include_fields
    else:
        fields = [
            field.name for field in (*model_name._meta.fields, *model_name._meta.many_to_many)
            if not is_sensitive_field(field, include_sensitive_fields, sensitive_field_names)
        ] + api_functions
    fields = [
        field for field in fields
        if field not in excluded_fields and (
            include_sensitive_fields or not is_sensitive_name(field, sensitive_field_names)
        )
    ]

    serializer_fields           = fields

    class DynamicSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_name
            fields = serializer_fields
            read_only_fields = read_only or []

        def to_representation(self, instance):
            return redact_sensitive_data(
                super().to_representation(instance), include_sensitive_fields, sensitive_field_names
            )

    for method_name in api_functions:
        def method_handler(self, instance, name=method_name):
            return getattr(instance, name)()
        setattr(DynamicSerializer, method_name, serializers.SerializerMethodField())
        setattr(DynamicSerializer, f"get_{method_name}", method_handler)

    return DynamicSerializer


def serialize_related_object(obj, depth=5, include=None, exclude=None, read_only=None,
                             include_sensitive_fields=False, sensitive_field_names=None, visited=None):
    """Serialize forward relations safely, stopping cycles and excluded fields."""
    if obj is None:
        return None
    if depth <= 0:
        return {"pk": obj.pk}
    visited                     = set() if visited is None else visited
    identity                    = (obj._meta.label_lower, obj.pk)
    if identity in visited:
        return {"pk": obj.pk}
    visited = visited | {identity}

    serializer_class            = create_model_serializer(
        type(obj), include, exclude, read_only, include_sensitive_fields, sensitive_field_names
    )
    representation              = serializer_class(obj).data
    for field in obj._meta.fields:
        if field.name not in representation or is_sensitive_field(field, include_sensitive_fields, sensitive_field_names):
            continue
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            related             = getattr(obj, field.name)
            representation[field.name] = serialize_related_object(
                related, depth - 1, include_sensitive_fields=include_sensitive_fields,
                sensitive_field_names=sensitive_field_names, visited=visited,
            )
    for field in obj._meta.many_to_many:
        if field.name in representation:
            representation[field.name] = [
                serialize_related_object(related, depth - 1, include_sensitive_fields=include_sensitive_fields,
                                         sensitive_field_names=sensitive_field_names, visited=visited)
                for related in getattr(obj, field.name).all()
            ]
    return redact_sensitive_data(representation, include_sensitive_fields, sensitive_field_names)


def create_file_upload_serializer(model_name, include=None, exclude=None, read_only=None,
                                  include_sensitive_fields=False, sensitive_field_names=None):
    return create_model_serializer(
        model_name, include, exclude, read_only, include_sensitive_fields, sensitive_field_names
    )


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

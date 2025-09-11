
from django.db              import models
from django.db.models       import ForeignKey
from django.core.exceptions import FieldDoesNotExist
from rest_framework         import serializers

SENSITIVE_FIELD_NAMES = {"password", "user", "token", "secret", "api_key"}

def is_sensitive_field(field):
    if field.name.lower() in SENSITIVE_FIELD_NAMES:
        return True
    if isinstance(field, (models.FileField, models.ImageField)):
        storage = getattr(field, "storage", None)
        if storage and getattr(storage, "default_acl", None) == "private":
            return True
    return False

def create_model_serializer(model_name, include=None, exclude=None, read_only=None):
    if not include:
        api_meta        = getattr(model_name, 'api_meta', {})
        field_list      = [f.name for f in model_name._meta.fields if not is_sensitive_field(f)]
        api_functions   = api_meta.get('api_function', [])
        all_fields      = field_list + api_functions
    else:
        all_fields = include

    if exclude:
        all_fields = [field for field in all_fields if field not in exclude]

    class DynamicSerializer(serializers.ModelSerializer):
        for method_name in getattr(model_name, 'api_meta', {}).get('api_function', []):
            locals()[method_name] = serializers.SerializerMethodField()
        
        class Meta:
            model               = model_name
            fields              = all_fields
            read_only_fields    = read_only if read_only else []

        def to_representation(self, instance):
            ret = super().to_representation(instance)
            for method_name in getattr(model_name, 'api_meta', {}).get('api_function', []):
                method = getattr(self, f'get_{method_name}')
                ret[method_name] = method(instance)
            return ret

        def validate_created_by(self, value):
            request = self.context.get('request')
            if request and hasattr(request, 'user'):
                if request.user != value:
                    raise serializers.ValidationError("Invalid data for created_by.")
            return value

    for method_name in getattr(model_name, 'api_meta', {}).get('api_function', []):
        def method_handler(self, instance, method_name=method_name):
            method = getattr(instance, method_name)
            return method()
        setattr(DynamicSerializer, f'get_{method_name}', method_handler)

    return DynamicSerializer

def serialize_related_object(obj, depth=5, include=None, exclude=None, read_only=None):
    if obj is None:
        return None
    if depth <= 0:
        return {'pk': obj.pk}

    api_functions   = getattr(type(obj), 'api_meta', {}).get('api_function', [])
    model_fields    = [f for f in type(obj)._meta.fields if not is_sensitive_field(f)]
    all_fields      = [f.name for f in model_fields] + api_functions
    _include        = include if include else all_fields
    _exclude        = exclude if exclude else []

    class DynamicSerializer(serializers.ModelSerializer):
        class Meta:
            model               = type(obj)
            fields              = _include
            exclude             = _exclude
            read_only_fields    = read_only if read_only else []

        def to_representation(self, instance):
            ret = super().to_representation(instance)
            self._serialize_related_fields(instance, ret, depth)
            return ret

        def _serialize_related_fields(self, instance, ret, depth):
            for field_name in [f.name for f in model_fields]:
                try:
                    field = instance._meta.get_field(field_name)
                    self._serialize_field(instance, field, field_name, ret, depth)
                except FieldDoesNotExist:
                    pass

        def _serialize_field(self, instance, field, field_name, ret, depth):
            if isinstance(field, (models.ForeignKey, models.OneToOneField)) and ret[field_name] is not None:
                related_obj = getattr(instance, field_name)
                ret[field_name] = serialize_related_object(related_obj, depth-1)
            elif isinstance(field, models.ManyToManyField):
                related_objs = getattr(instance, field_name).all()
                ret[field_name] = [serialize_related_object(related_obj, depth-1) for related_obj in related_objs]

    return DynamicSerializer(obj).data

def create_file_upload_serializer(model_name, include=None, exclude=None, read_only=None):
    if not include:
        field_list = [f.name for f in model_name._meta.fields if not is_sensitive_field(f)] + \
                     [f.name for f in model_name._meta.related_objects]
    else:
        field_list = include

    if exclude:
        field_list = [field for field in field_list if field not in exclude]

    class DynamicFileUploadSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_name
            fields = field_list
            read_only_fields = read_only if read_only else []

        def validate(self, data):
            for field_name, value in list(data.items()):
                parts = field_name.split('__', 1)
                if len(parts) == 2 and hasattr(model_name, parts[0]):
                    related_field_name, related_lookup = parts
                    model_field = model_name._meta.get_field(related_field_name)
                    if isinstance(model_field, ForeignKey):
                        lookup_model = model_field.related_model
                        try:
                            lookup_instance = lookup_model.objects.get(**{related_lookup: value})
                            data[related_field_name] = lookup_instance.pk
                        except lookup_model.DoesNotExist:
                            raise serializers.ValidationError(f"{lookup_model.__name__} with {related_lookup}={value} does not exist.")
                        del data[field_name]
            return data

    return DynamicFileUploadSerializer

class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

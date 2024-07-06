from django.db              import models
from django.db.models       import ForeignKey
from django.contrib.auth    import get_user_model
from django.core.exceptions import FieldDoesNotExist
from rest_framework         import serializers


def create_model_serializer(model_name, include=None, exclude = None, read_only = None):
    if not include:
        # Improved method to get fields and api_function methods from api_meta
        api_meta        = getattr(model_name, 'api_meta', {})
        field_list      = [f.name for f in model_name._meta.fields]
        api_functions   = api_meta.get('api_function', [])
        
        # Combine model fields and api_function methods for serialization
        all_fields = field_list + api_functions
    else:
        all_fields = include

    # Handle Exclude
    if exclude:
        all_fields = [field for field in all_fields if field not in exclude]

    

    # Define a dynamic serializer class within the function.
    # This class is created dynamically for each object to be serialized.
    class DynamicSerializer(serializers.ModelSerializer):
        # Dynamically create SerializerMethodFields for each method in api_functions.
        for method_name in api_functions:
            locals()[method_name] = serializers.SerializerMethodField()
        
        class Meta:
            model               = model_name
            fields              = all_fields
            read_only_fields    = read_only if read_only else []

        # Override the to_representation method for including the api_functions.
        def to_representation(self, instance):
            ret = super().to_representation(instance)
            
            # Serialize the results of the api_function methods.
            for method_name in api_functions:
                method = getattr(self, f'get_{method_name}')
                ret[method_name] = method(instance)
            return ret
            

        # Define a custom validator for 'created_by'
        def validate_created_by(self, value):
            request = self.context.get('request')
            if request and hasattr(request, 'user'):
                if request.user != value:
                    raise serializers.ValidationError("Invalid data for created_by.")
            return value

    # Dynamically create methods for SerializerMethodField.
    for method_name in api_functions:
        def method_handler(self, instance, method_name=method_name):
            method = getattr(instance, method_name)
            return method()
        setattr(DynamicSerializer, f'get_{method_name}', method_handler)

    return DynamicSerializer


def serialize_related_object(obj, depth=5, include=None, exclude=None, read_only=None):
    # Terminate recursion if obj is None.
    if obj is None:
        return None
    
    # Check the object for object permissions


    # Terminate recursion if maximum depth is reached.
    if depth <= 0:
        return {'pk': obj.pk}

    # Extract custom methods and model fields.
    api_functions   = getattr(type(obj), 'api_meta', {}).get('api_function', [])
    model_fields    = [f.name for f in type(obj)._meta.fields]
    all_fields      = model_fields + api_functions
    _include         = include if include else all_fields
    _exclude         = exclude if exclude else []

    class DynamicSerializer(serializers.ModelSerializer):
        class Meta:
            model               = type(obj)
            fields              = _include
            exclude             = _exclude
            read_only_fields    = read_only if read_only else []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            
        def to_representation(self, instance):
            ret = super().to_representation(instance)
            
            self._serialize_related_fields(instance, ret, depth)
            return ret

        def _serialize_related_fields(self, instance, ret, depth):
            for field_name in model_fields:
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
    # Dynamically determine field list based on include or model fields
    if not include:
        field_list = [f.name for f in model_name._meta.fields] + \
                     [f.name for f in model_name._meta.related_objects]
    else:
        field_list = include

    # Apply exclude
    if exclude:
        field_list = [field for field in field_list if field not in exclude]

    class DynamicFileUploadSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_name
            fields = field_list  # Adjust this as per your requirements
            read_only_fields = read_only if read_only else []

        def validate(self, data):
            # Iterate over data items for foreign key resolution
            for field_name, value in list(data.items()):
                # Split to identify if field is a lookup field
                parts = field_name.split('__', 1)
                if len(parts) == 2 and hasattr(model_name, parts[0]):
                    related_field_name, related_lookup = parts
                    model_field = model_name._meta.get_field(related_field_name)
 
                    if isinstance(model_field, ForeignKey):
                        lookup_model = model_field.related_model
                        try:
                            # Perform lookup and replace data with the foreign key
                            lookup_instance = lookup_model.objects.get(**{related_lookup: value})
                            data[related_field_name] = lookup_instance.pk
                        except lookup_model.DoesNotExist:
                            raise serializers.ValidationError(f"{lookup_model.__name__} with {related_lookup}={value} does not exist.")
                        
                        # Remove the lookup field from data as it's replaced by actual FK
                        del data[field_name]
            return data

    return DynamicFileUploadSerializer




# Define a minimal serializer for the file upload
class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    

from functools                  import wraps
from django.shortcuts           import get_object_or_404
from rest_framework.response    import Response
from rest_framework             import status



'''
    Decorator: check_table_permissions
    ----------------------------------
    This decorator is used to check table level permissions for a given model.
    It is used in the GenericCRUDView class.
'''
def check_table_permissions(view_func):
    @wraps(view_func)
    def _wrapped_view(view, request, *args, **kwargs):
        app_label   = view.app_label
        model_name  = view.model_name
        permission  = f'{app_label}.view_{model_name}'
        
        if not request.user.has_perm(permission):
            return Response({'error': 'You do not have permission to access this table.', 'detail': 'Does not have table level permissions.'}, status=status.HTTP_403_FORBIDDEN)
        
        return view_func(view, request, *args, **kwargs)
    return _wrapped_view



'''
    Decorator: check_object_permissions
    -----------------------------------
    This decorator is used to check object level permissions for a given model.
    It is used in the GenericCRUDView class.
'''
def check_object_permissions(permission_prefix='view_'):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(view, request, *args, **kwargs):
            pk = kwargs.get('pk') or request.GET.get('pk')
            app_label       = view.app_label
            model_name      = view.model_name
            # view.permission = f'{app_label}.{permission_prefix}{model_name}'
            view.permission = f'{permission_prefix}{model_name}'
            view.queryset   =   view.get_queryset()
            obj             = get_object_for_user(view.queryset, request.user, view.permission)

            if pk:
                if not obj:
                    return Response({'error': 'You do not have permission to access this object.', 'detail': 'Does not have object level permissions.'}, status=status.HTTP_403_FORBIDDEN)
            
            view.queryset = obj # ovverride the queryset of the view calling this decorator
            return view_func(view, request, *args, **kwargs)
        return _wrapped_view
    return decorator




'''
    Decorator: error_handling
    -------------------------
    This decorator is used to handle errors in the views.
    It is used in the GenericCRUDView class.
'''
def error_handling(view_func):
    @wraps(view_func)
    def _wrapped_view(view, request, *args, **kwargs):
        try:
            return view_func(view, request, *args, **kwargs)
        except Exception as e:
            return Response({'error': 'An error occurred.', 'detail': str(e), }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _wrapped_view
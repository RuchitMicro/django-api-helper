from rest_framework.pagination  import PageNumberPagination
from rest_framework.response    import Response
from rest_framework.utils.urls  import replace_query_param


# Custom Pagination Class
# -----------------------
# This class extends the PageNumberPagination class provided by Django REST framework.
# It provides a custom response format for paginated data, including various page links.
class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = 'page_size'

    def get_paginated_response(self, data):
        # Building the base URL for the current request.
        base_url        = self.request.build_absolute_uri()
        current_page    = self.page.number
        last_page       = self.page.paginator.num_pages

        # Helper function to generate URL for a specific page number.
        def get_page_number_link(page_number):
            return replace_query_param(base_url, self.page_query_param, page_number)

        # Generating links for all pages.
        page_links = [get_page_number_link(page_number) for page_number in range(1, last_page + 1)]

        # Construct and return the custom paginated response.
        return Response({
            'links': {
                'first': get_page_number_link(1),
                'last': get_page_number_link(last_page),
                'previous': self.get_previous_link(),
                'next': self.get_next_link(),
                'pages': page_links
            },
            'current_page': current_page,
            'last_page': last_page,
            'total_items': self.page.paginator.count,
            'page_size': self.page_size,
            'results': data,
        })


"""Pagination with bounded link generation for large result sets."""

from rest_framework.pagination  import PageNumberPagination
from rest_framework.response    import Response
from rest_framework.utils.urls  import replace_query_param


class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param       = "page_size"
    max_page_size               = 1000
    page_link_window            = 21

    def get_page_links(self, base_url, current_page, last_page):
        """Return a stable, bounded window while retaining first and last links."""
        if last_page <= self.page_link_window:
            page_numbers        = range(1, last_page + 1)
        else:
            half_window         = self.page_link_window // 2
            start               = max(1, current_page - half_window)
            end                 = min(last_page, start + self.page_link_window - 1)
            start               = max(1, end - self.page_link_window + 1)
            page_numbers        = sorted({1, *range(start, end + 1), last_page})
        return [replace_query_param(base_url, self.page_query_param, page) for page in page_numbers]

    def get_paginated_response(self, data):
        base_url                = self.request.build_absolute_uri()
        current_page            = self.page.number
        last_page               = self.page.paginator.num_pages

        def page_link(page_number):
            return replace_query_param(base_url, self.page_query_param, page_number)

        return Response({
            "links": {
                "first": page_link(1),
                "last": page_link(last_page),
                "previous": self.get_previous_link(),
                "next": self.get_next_link(),
                "pages": self.get_page_links(base_url, current_page, last_page),
            },
            "current_page": current_page,
            "last_page": last_page,
            "total_items": self.page.paginator.count,
            "page_size": self.get_page_size(self.request),
            "results": data,
        })

from rest_framework.pagination import PageNumberPagination

class CustomPageNumberPagination(PageNumberPagination):
    page_size = 100                          # Default items per page
    page_size_query_param = 'page_size'    # Allow override with ?page_size=
    max_page_size = 100                    # Maximum allowed page size
    page_query_param = 'page'              # Default is 'page', you can override
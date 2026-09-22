from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """
    Paginación estándar del proyecto.
    Uso: ?page=2&page_size=50
    """
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200

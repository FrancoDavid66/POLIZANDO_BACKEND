# seguros_project/pagination.py
from rest_framework.pagination import PageNumberPagination, CursorPagination


class LargeResultsSetPagination(PageNumberPagination):
    """
    Paginación clásica con COUNT().
    Útil cuando necesitás "count" y "totalPages" en el front.
    """
    page_size = 100
    page_size_query_param = "page_size"

    # ⚠️ 20000 es peligrosísimo: una sola request puede traer demasiados registros.
    # Ajustalo a algo razonable para backoffice.
    max_page_size = 500


class CursorLargeResultsSetPagination(CursorPagination):
    """
    Paginación ultra rápida para listados grandes:
    - NO hace COUNT()
    - Usa cursor (next/previous)
    Ideal para /polizas/ cuando hay miles de registros.
    """
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500

    ordering = "-id"          # estable y rápido si hay índice por id
    cursor_query_param = "cursor"

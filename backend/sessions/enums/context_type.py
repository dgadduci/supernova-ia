from enum import StrEnum


class ContextType(StrEnum):
    PRODUCT_SELECTION = "product_selection"
    ORDER_LINE_SELECTION = "order_line_selection"
    PRODUCT_MODIFICATION = "product_modification"


__all__ = ["ContextType"]
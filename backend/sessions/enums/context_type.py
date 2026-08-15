from enum import StrEnum


class ContextType(StrEnum):
    PRODUCT_SELECTION = "product_selection"
    ORDER_LINE_SELECTION = "order_line_selection"
    PRODUCT_MODIFICATION = "product_modification"
    ORDER_CLEAR_CONFIRMATION = "order_clear_confirmation"
    ORDER_CONFIRMATION_OBSERVATION = "order_confirmation_observation"


__all__ = ["ContextType"]
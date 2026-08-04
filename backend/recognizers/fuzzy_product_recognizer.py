from typing import cast

from backend.recognizers import product_recognizer
from backend.recognizers.product_recognizer_contract import ProductRecognizerResult


class FuzzyProductRecognizer:
    def recognize(
        self,
        text: str,
        catalog: list[dict],
    ) -> ProductRecognizerResult:
        return cast(
            ProductRecognizerResult,
            product_recognizer.detectar_productos(text, catalog),
        )


__all__ = ["FuzzyProductRecognizer"]

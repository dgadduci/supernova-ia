from typing import cast

from backend.recognizers import product_recognizer
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerResult,
    RecognizeContext,
)


class FuzzyProductRecognizer:
    def recognize(
        self,
        text: str,
        catalog: list[dict],
        *,
        intent_metadata: RecognizeContext | None = None,
    ) -> ProductRecognizerResult:
        return cast(
            ProductRecognizerResult,
            product_recognizer.detectar_productos(text, catalog),
        )


__all__ = ["FuzzyProductRecognizer"]

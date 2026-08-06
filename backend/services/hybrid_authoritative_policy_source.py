"""Subphase 4.12B hybrid authoritative policy loader.

The loader is the single source of truth for the JSON calibration
report the 4.11 calibration runner emits. It is invoked exactly once
at factory call time when the effective ``product_recognizer_mode``
is ``"hybrid_authoritative"``. The loader:

- Reads ``settings.hybrid_authoritative_policy_path`` as a path,
  opens it in UTF-8 mode, and parses it as JSON.
- Requires the top-level ``selected_policy`` key to be a JSON object
  whose keys are exactly the six documented numeric fields.
- Requires the top-level ``eligibility.status`` key to equal the
  literal ``"eligible"``.
- Constructs the frozen ``HybridDecisionPolicy`` so the existing
  validators run on every load.
- Wraps every load-time failure (missing file, unparsable JSON,
  ineligible eligibility, malformed ``selected_policy``, or
  constructor failure) in :class:`HybridAuthoritativePolicyError`
  so the factory raises a single exception type for the
  orchestrator-import-time ``get_product_recognizer(load_settings())``
  call to fail closed.

The loader does NOT mutate the file system, does NOT write to any
JSON file, does NOT hold module-level mutable state, does NOT cache
the loaded policy across calls, and does NOT import FastAPI, the
embedding client transport, the vector search service, the shadow
service, the shadowed recognizer, the shadow recorder, the
recognizer factory, or any router.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from backend.services.exceptions import HybridAuthoritativePolicyError
from backend.services.product_recognition_calibration_policy import (
    HybridDecisionPolicy,
)

if TYPE_CHECKING:
    from backend.config.settings import Settings


_SELECTED_POLICY_KEYS: frozenset[str] = frozenset(
    {
        "fuzzy_weight",
        "vector_weight",
        "unique_threshold",
        "ambiguous_threshold",
        "minimum_score_gap",
        "vector_top_k",
    }
)


class HybridAuthoritativePolicySource:
    """Stateless loader for the hybrid authoritative ``HybridDecisionPolicy``."""

    @classmethod
    def load(cls, settings: Settings) -> HybridDecisionPolicy:
        path_value = settings.hybrid_authoritative_policy_path
        if path_value is None:
            raise HybridAuthoritativePolicyError(
                "hybrid_authoritative_policy_path must be set when the "
                "effective product_recognizer_mode is 'hybrid_authoritative'"
            )
        path = Path(path_value)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise HybridAuthoritativePolicyError(
                f"hybrid authoritative policy file not found: {path_value}"
            ) from exc
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HybridAuthoritativePolicyError(
                f"hybrid authoritative policy file is not valid JSON: {path_value}"
            ) from exc
        if not isinstance(document, dict):
            raise HybridAuthoritativePolicyError(
                "hybrid authoritative policy document must be a JSON object"
            )

        selected_policy = document.get("selected_policy")
        if not isinstance(selected_policy, dict):
            raise HybridAuthoritativePolicyError(
                "hybrid authoritative policy document must carry a "
                "'selected_policy' JSON object"
            )
        actual_keys = set(selected_policy.keys())
        if actual_keys != _SELECTED_POLICY_KEYS:
            missing = sorted(_SELECTED_POLICY_KEYS - actual_keys)
            extra = sorted(actual_keys - _SELECTED_POLICY_KEYS)
            raise HybridAuthoritativePolicyError(
                "hybrid authoritative policy 'selected_policy' must carry "
                f"exactly {sorted(_SELECTED_POLICY_KEYS)} "
                f"(missing={missing}, extra={extra})"
            )

        eligibility = document.get("eligibility")
        if not isinstance(eligibility, dict):
            raise HybridAuthoritativePolicyError(
                "hybrid authoritative policy document must carry an "
                "'eligibility' JSON object"
            )
        status = eligibility.get("status")
        if status != "eligible":
            raise HybridAuthoritativePolicyError(
                "hybrid authoritative policy document is not eligible "
                f"(eligibility.status={status!r})"
            )

        try:
            policy = HybridDecisionPolicy(
                fuzzy_weight=selected_policy["fuzzy_weight"],
                vector_weight=selected_policy["vector_weight"],
                unique_threshold=selected_policy["unique_threshold"],
                ambiguous_threshold=selected_policy["ambiguous_threshold"],
                minimum_score_gap=selected_policy["minimum_score_gap"],
                vector_top_k=selected_policy["vector_top_k"],
            )
        except (ValueError, TypeError) as exc:
            raise HybridAuthoritativePolicyError(
                "hybrid authoritative policy 'selected_policy' failed to "
                f"construct HybridDecisionPolicy: {exc}"
            ) from exc
        return policy


__all__ = [
    "HybridAuthoritativePolicyError",
    "HybridAuthoritativePolicySource",
]

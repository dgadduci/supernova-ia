"""Dedicated typed menu category resolver.

This module owns the bounded second LLM call that resolves which
``ver_menu`` category, if any, the customer's menu browse request
refers to. It is a **language interpreter only**: it never authorizes
catalog access, never supplies a database ID and never mutates any
state. The backend orchestration that calls this resolver validates
the returned opaque ``(token, nombre)`` pair against the same
in-memory candidate list and only then translates to a backend-held
category identity to filter the already-loaded catalog.

Design contract (see ``openspec/specs/category-menu-resolution/spec.md``
and ``design.md``):

* Only the classified ``ver_menu`` source text and the bounded opaque
  ``(token, nombre)`` candidate projection reach the prompt. No
  database IDs, product names, prices, presentation codes, customer
  data, pedido data, aliases, settings, credentials or provider data.
* The response schema is closed: either both ``token`` and ``nombre``
  refer to the same candidate in this invocation, or both are
  ``null``. Extra fields are forbidden.
* Documented transport failures
  (:class:`backend.llm.query_llm.QueryLlmTimeoutError`,
  :class:`backend.llm.query_llm.QueryLlmConnectionError`,
  :class:`backend.llm.query_llm.QueryLlmHttpError`) and response /
  schema failures
  (:class:`backend.llm.query_llm.QueryLlmResponseError`,
  :class:`pydantic.ValidationError`) are caught at the resolver
  boundary and translated to a typed ``no_selection`` with a closed
  ``failure_class``. They never leak raw text, IDs or exception
  messages to the caller and never reach the caller-owned order
  transaction.
* The resolver owns no transaction methods and never touches the
  database. The caller-owned transaction remains unchanged on every
  outcome.
* Diagnostics record only bounded metadata
  (``attempted``, ``candidate_count``, ``selected/null``,
  ``failure_class``, ``latency_ms``, ``template_identity``,
  ``model``); they MUST NOT include raw message text, candidate
  labels/tokens, IDs, prompt content or exception text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from backend.diagnostics.menu_category_prompt_template import (
    MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
    build_menu_category_prompt,
    menu_category_template_fingerprint,
)
from backend.llm.query_llm import (
    QueryLlm,
    QueryLlmConnectionError,
    QueryLlmError,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
)


class _QueryLlmLike(Protocol):
    def request(self, prompt: str) -> dict[str, Any]: ...


MAX_CANDIDATE_NAME_LENGTH = 80
MAX_CANDIDATE_COUNT = 20
MAX_CANDIDATE_CONTEXT_CHARS = 2000


class _ResolverSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str | None
    nombre: str | None


@dataclass(frozen=True)
class MenuCategoryCandidate:
    """Internal projection of one category candidate for the resolver.

    ``categoria_id`` is the real database identity; it NEVER leaves
    the backend. ``token`` is opaque per invocation and MUST NOT be
    a database ID. ``nombre`` is the exact display name.
    """

    categoria_id: int
    token: str
    nombre: str


@dataclass(frozen=True)
class MenuCategoryResolution:
    """Outcome of one resolver invocation.

    ``token`` and ``nombre`` are both populated only when both match
    the same candidate built for the current invocation; otherwise
    both are ``None``. ``failure_class`` is a closed label populated
    only when the resolver could not produce a typed result; it is
    always ``None`` for the happy paths.
    """

    selected: MenuCategoryCandidate | None
    failure_class: str | None
    attempted: bool
    candidate_count: int
    latency_ms: int
    template_version: str
    template_fingerprint: str
    model: str | None

    @property
    def is_selected(self) -> bool:
        return self.selected is not None


class MenuCategoryResolver:
    """Bounded second LLM interpreter for ``ver_menu`` category browse.

    The resolver is instantiated by the informational orchestration
    only after the existing primary classifier emits ``ver_menu`` and
    the session has no pending context. It accepts the classified
    source text and the bounded opaque candidate projection built
    from the already-loaded sellable catalog.
    """

    def __init__(
        self,
        query_llm: _QueryLlmLike | None = None,
        *,
        clock: Any | None = None,
    ) -> None:
        self._query_llm: _QueryLlmLike = query_llm if query_llm is not None else QueryLlm()
        self._clock = clock or __import__("time").monotonic

    def resolve(
        self,
        source_text: str,
        candidates: list[MenuCategoryCandidate],
        *,
        model: str | None = None,
    ) -> MenuCategoryResolution:
        """Resolve the (opaque) menu category for ``source_text``.

        Returns a typed :class:`MenuCategoryResolution`. The caller is
        responsible for validating ``selected`` against the candidate
        list again before filtering the catalog. Documented transport
        and schema failures are contained as
        ``failure_class="transport"`` or ``"schema"`` and never raise.
        """
        template_fingerprint = menu_category_template_fingerprint()

        bounded_candidates = _enforce_candidate_bounds(candidates)
        prompt = build_menu_category_prompt(source_text, _project_candidates(bounded_candidates))

        started = self._clock()
        try:
            payload = self._query_llm.request(prompt)
        except (
            QueryLlmTimeoutError,
            QueryLlmConnectionError,
            QueryLlmHttpError,
        ):
            elapsed = int((self._clock() - started) * 1000)
            return MenuCategoryResolution(
                selected=None,
                failure_class="transport",
                attempted=True,
                candidate_count=len(bounded_candidates),
                latency_ms=elapsed,
                template_version=MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
                template_fingerprint=template_fingerprint,
                model=model,
            )
        except QueryLlmResponseError:
            elapsed = int((self._clock() - started) * 1000)
            return MenuCategoryResolution(
                selected=None,
                failure_class="response",
                attempted=True,
                candidate_count=len(bounded_candidates),
                latency_ms=elapsed,
                template_version=MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
                template_fingerprint=template_fingerprint,
                model=model,
            )
        except QueryLlmError:
            elapsed = int((self._clock() - started) * 1000)
            return MenuCategoryResolution(
                selected=None,
                failure_class="transport",
                attempted=True,
                candidate_count=len(bounded_candidates),
                latency_ms=elapsed,
                template_version=MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
                template_fingerprint=template_fingerprint,
                model=model,
            )

        try:
            parsed = _ResolverSchema.model_validate(payload)
        except ValidationError:
            elapsed = int((self._clock() - started) * 1000)
            return MenuCategoryResolution(
                selected=None,
                failure_class="schema",
                attempted=True,
                candidate_count=len(bounded_candidates),
                latency_ms=elapsed,
                template_version=MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
                template_fingerprint=template_fingerprint,
                model=model,
            )

        elapsed = int((self._clock() - started) * 1000)
        selected = _match_selection(parsed.token, parsed.nombre, bounded_candidates)
        return MenuCategoryResolution(
            selected=selected,
            failure_class=None,
            attempted=True,
            candidate_count=len(bounded_candidates),
            latency_ms=elapsed,
            template_version=MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
            template_fingerprint=template_fingerprint,
            model=model,
        )


def _project_candidates(candidates: list[MenuCategoryCandidate]) -> list[dict[str, str]]:
    """Project internal candidates to the LLM-safe opaque view."""
    return [{"token": c.token, "nombre": c.nombre} for c in candidates]


def _enforce_candidate_bounds(
    candidates: list[MenuCategoryCandidate],
) -> list[MenuCategoryCandidate]:
    """Drop candidates that violate the documented bounds.

    The bounds are applied defensively; the orchestration already
    filters by document length and count. This guard returns only
    candidates that satisfy:

    * at most :data:`MAX_CANDIDATE_COUNT` entries (the first ones win);
    * each ``nombre`` at most :data:`MAX_CANDIDATE_NAME_LENGTH`
      characters.
    """
    bounded: list[MenuCategoryCandidate] = []
    for candidate in candidates:
        if len(bounded) >= MAX_CANDIDATE_COUNT:
            break
        if len(candidate.nombre) > MAX_CANDIDATE_NAME_LENGTH:
            continue
        bounded.append(candidate)
    return bounded


def _match_selection(
    token: str | None,
    nombre: str | None,
    candidates: list[MenuCategoryCandidate],
) -> MenuCategoryCandidate | None:
    """Return the matched candidate only when both fields agree.

    Either both ``token`` and ``nombre`` are populated and point to
    the same candidate, or both are ``None`` and the function returns
    ``None``. Any other combination (one populated, the other ``None``,
    mismatched pair, unknown token, unknown name) is treated as
    no-selection to honour the resolver's closed contract.
    """
    if token is None and nombre is None:
        return None
    if not isinstance(token, str) or not isinstance(nombre, str):
        return None
    matched: list[MenuCategoryCandidate] = [
        c for c in candidates if c.token == token and c.nombre == nombre
    ]
    if len(matched) != 1:
        return None
    return matched[0]


__all__ = [
    "MAX_CANDIDATE_CONTEXT_CHARS",
    "MAX_CANDIDATE_COUNT",
    "MAX_CANDIDATE_NAME_LENGTH",
    "MenuCategoryCandidate",
    "MenuCategoryResolution",
    "MenuCategoryResolver",
]
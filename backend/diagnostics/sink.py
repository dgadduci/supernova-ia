from __future__ import annotations

from typing import Protocol, final, runtime_checkable

from .events import (
    ClassifierCallCompleted,
    ClassifierCallStarted,
    DiagnosticEvent,
    PendingStateSnapshot,
    ResolverCallCompleted,
    ResolverCallStarted,
)


@runtime_checkable
class DiagnosticSink(Protocol):
    def on_classifier_started(self, event: ClassifierCallStarted) -> None: ...

    def on_classifier_completed(self, event: ClassifierCallCompleted) -> None: ...

    def on_resolver_started(self, event: ResolverCallStarted) -> None: ...

    def on_resolver_completed(self, event: ResolverCallCompleted) -> None: ...

    def on_pending_state_snapshot(self, event: PendingStateSnapshot) -> None: ...


@final
class NoopDiagnosticSink:
    __slots__ = ()

    def on_classifier_started(self, event: ClassifierCallStarted) -> None:
        pass

    def on_classifier_completed(self, event: ClassifierCallCompleted) -> None:
        pass

    def on_resolver_started(self, event: ResolverCallStarted) -> None:
        pass

    def on_resolver_completed(self, event: ResolverCallCompleted) -> None:
        pass

    def on_pending_state_snapshot(self, event: PendingStateSnapshot) -> None:
        pass


@final
class CollectingDiagnosticSink:
    __slots__ = (
        "_classifier_call_ids",
        "_classifier_count",
        "_events",
        "_resolver_call_ids",
        "_resolver_count",
        "_sequence",
        "_turn_id",
    )

    def __init__(self, *, turn_id: int = 1) -> None:
        self._events: list[DiagnosticEvent] = []
        self._classifier_count = 0
        self._resolver_count = 0
        self._sequence = 0
        self._turn_id = turn_id
        self._classifier_call_ids: list[str] = []
        self._resolver_call_ids: list[str] = []

    def on_classifier_started(self, event: ClassifierCallStarted) -> None:
        if not event.call_id:
            self._classifier_count += 1
            event.call_id = f"CLS-{self._classifier_count:03d}"
        self._classifier_call_ids.append(event.call_id)
        self._record(event)

    def on_classifier_completed(self, event: ClassifierCallCompleted) -> None:
        if not event.call_id:
            event.call_id = self._take_call_id(
                self._classifier_call_ids,
                "classifier",
            )
        else:
            self._discard_call_id(self._classifier_call_ids, event.call_id)
        self._record(event)

    def on_resolver_started(self, event: ResolverCallStarted) -> None:
        if not event.call_id:
            self._resolver_count += 1
            event.call_id = f"RES-{self._resolver_count:03d}"
        self._resolver_call_ids.append(event.call_id)
        self._record(event)

    def on_resolver_completed(self, event: ResolverCallCompleted) -> None:
        if not event.call_id:
            event.call_id = self._take_call_id(
                self._resolver_call_ids,
                "resolver",
            )
        else:
            self._discard_call_id(self._resolver_call_ids, event.call_id)
        self._record(event)

    def on_pending_state_snapshot(self, event: PendingStateSnapshot) -> None:
        if not event.call_id:
            if self._resolver_call_ids:
                event.call_id = self._resolver_call_ids[-1]
            elif self._classifier_call_ids:
                event.call_id = self._classifier_call_ids[-1]
        self._record(event)

    def events(self) -> list[DiagnosticEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._classifier_call_ids.clear()
        self._resolver_call_ids.clear()
        self._classifier_count = 0
        self._resolver_count = 0
        self._sequence = 0

    def _record(self, event: DiagnosticEvent) -> None:
        self._sequence += 1
        event.sequence = self._sequence
        if not event.turn_id:
            event.turn_id = self._turn_id
        self._events.append(event)

    def _take_call_id(self, call_ids: list[str], component: str) -> str:
        if call_ids:
            return call_ids.pop()
        if component == "classifier":
            self._classifier_count += 1
            return f"CLS-{self._classifier_count:03d}"
        self._resolver_count += 1
        return f"RES-{self._resolver_count:03d}"

    @staticmethod
    def _discard_call_id(call_ids: list[str], call_id: str) -> None:
        if call_id in call_ids:
            call_ids.remove(call_id)


__all__ = [
    "CollectingDiagnosticSink",
    "DiagnosticSink",
    "NoopDiagnosticSink",
]

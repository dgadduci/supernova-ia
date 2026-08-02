from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session as DatabaseSession

from backend.dependencies import get_session
from backend.diagnostics import (
    CollectingDiagnosticSink,
    DiagnosticSink,
    NoopDiagnosticSink,
    redact,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_responses,
)
from backend.schemas.incoming_message import (
    IncomingMessageRequest,
    IncomingMessageResponse,
)
from backend.services.exceptions import SessionNotFound
from backend.services.session_service import SessionService

router = APIRouter(tags=["incoming-messages"])


def _service(
    session: DatabaseSession = Depends(get_session),
) -> SessionService:
    return SessionService(session)


def get_diagnostic_sink(
    x_debug_flow: str | None = Header(default=None, alias="X-Debug-Flow"),
) -> DiagnosticSink:
    if x_debug_flow:
        return CollectingDiagnosticSink()
    return NoopDiagnosticSink()


@router.post(
    "/comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages",
    response_model=IncomingMessageResponse,
    status_code=status.HTTP_200_OK,
)
def post_incoming_message(
    comercio_id: int,
    cliente_id: int,
    payload: IncomingMessageRequest,
    service: SessionService = Depends(_service),
    db: DatabaseSession = Depends(get_session),
    sink: DiagnosticSink = Depends(get_diagnostic_sink),
) -> IncomingMessageResponse:
    try:
        session = service.get_active(comercio_id, cliente_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Share the sink across the orchestrator call and the response builder
    # so events emitted during dispatch surface in the response.
    shared_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    try:
        if isinstance(shared_sink, NoopDiagnosticSink):
            responses = process_incoming_message_with_responses(
                db, session, payload.message
            )
        else:
            responses = process_incoming_message_with_responses(
                db, session, payload.message, sink=shared_sink
            )
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response_payload: dict = {"responses": [r.model_dump() for r in responses]}
    if isinstance(shared_sink, CollectingDiagnosticSink):
        events = sorted(
            (event.to_dict() for event in shared_sink.events()),
            key=lambda item: (item.get("sequence", 0), item.get("phase", "")),
        )
        response_payload["diagnostics"] = events
    redacted_payload = redact(response_payload)
    if not isinstance(redacted_payload, dict):
        redacted_payload = {"responses": []}
    response = IncomingMessageResponse.model_validate(redacted_payload)
    if isinstance(shared_sink, CollectingDiagnosticSink):
        diagnostics_value: list[dict[str, Any]] | None = None
        raw_diagnostics: Any = redacted_payload.get("diagnostics")
        if isinstance(raw_diagnostics, list):
            diagnostics_value = [
                item for item in raw_diagnostics if isinstance(item, dict)
            ]
        response.diagnostics = diagnostics_value
    return response


__all__ = ["router"]

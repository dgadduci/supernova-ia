"""Standalone CLI HTTP client for the running API.

This script is a pure HTTP client: it talks to the FastAPI server exclusively
through ``urllib.request`` over the standard JSON endpoints. It deliberately
does NOT import ``fastapi``, ``sqlalchemy``, ``uvicorn``, or any ``backend.*``
module, and it does NOT start, stop, restart, or otherwise mutate the
FastAPI/Uvicorn process. Its only responsibilities are: bootstrap one session
plus its draft ``Pedido`` through the existing HTTP endpoints, send each typed
line to ``POST /incoming-messages`` on that session, print the pipeline
responses, and close the session on exit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


__all__ = [
    "main",
    "_post_json",
    "_read_int",
    "_print_responses",
    "_resolve_base_url",
    "_close_session",
    "_create_session",
    "_get_active_session",
    "_fetch_pedido_detalle",
    "response_modified_order",
    "format_order_table",
    "ORDER_MUTATING_INTENTS",
    "_format_kv_table",
    "_format_intent_table",
    "_format_pending_state_snapshot",
    "_format_pending_queue_table",
    "_extract_diagnostics",
    "_render_diagnostics",
    "_redact_payload",
    "_parse_debug_components",
]


# Subphase 3.30.2: extend this set in one place when a new order-mutating
# intent is added to the modern pipeline.
ORDER_MUTATING_INTENTS = {
    "agregar_producto",
    "quitar_producto",
    "modificar_producto",
}


_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_ENV_BASE_URL = "INCOMING_MESSAGES_BASE_URL"
_REQUEST_TIMEOUT = 1200

_DEBUG_COMPONENT_ALIASES = {"classifier", "resolver", "pending"}
_REDACTED_KEYS = {
    "password",
    "token",
    "api_key",
    "authorization",
    "secret",
    "database_url",
    "DATABASE_URL",
    "Authorization",
    "X-API-Key",
    "X-API-KEY",
}
_REDACTED_KEYS_NORMALIZED = {key.casefold() for key in _REDACTED_KEYS}


def _post_json(
    url: str,
    body: dict,
    timeout: int = _REQUEST_TIMEOUT,
    method: str = "POST",
    *,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    encoded = json.dumps(body).encode("utf-8") if body is not None else b""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if extra_headers:
        for key, value in extra_headers.items():
            headers[key] = value
    request = urllib.request.Request(
        url,
        data=encoded,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.getcode(), json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in response from {url}: {exc}") from exc
    except urllib.error.HTTPError as exc:
        decoded_body = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        try:
            return exc.code, json.loads(decoded_body) if decoded_body else {}
        except json.JSONDecodeError:
            return exc.code, decoded_body
    except urllib.error.URLError as exc:
        raise RuntimeError(f"connection error posting to {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in response from {url}: {exc}") from exc


def _resolve_base_url(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--base-url", default=None)
    args, _ = parser.parse_known_args(argv)
    if args.base_url:
        return args.base_url.rstrip("/")
    env_value = os.environ.get(_ENV_BASE_URL)
    if env_value:
        return env_value.rstrip("/")
    return _DEFAULT_BASE_URL


def _error_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
        return json.dumps(payload, ensure_ascii=False)
    if isinstance(payload, str) and payload:
        return payload
    return "request failed"


def _get_active_session(base_url: str, comercio_id: int, cliente_id: int) -> int | None:
    url = f"{base_url}/sessions/comercios/{comercio_id}/clientes/{cliente_id}/activa"
    try:
        status, payload = _post_json(url, {}, method="GET")
    except Exception as exc:
        print(f"warning: failed to check active session: {exc}", file=sys.stderr)
        return None
    if status == 200 and isinstance(payload, dict) and "id" in payload:
        return int(payload["id"])
    if status == 404:
        return None
    print(f"warning: unexpected status {status} checking active session", file=sys.stderr)
    return None


def _create_session(base_url: str, comercio_id: int, cliente_id: int) -> tuple[int, int]:
    active_id = _get_active_session(base_url, comercio_id, cliente_id)
    if active_id is not None:
        print(f"<closing existing session {active_id}>", file=sys.stderr)
        _close_session(base_url, active_id)
    status, payload = _post_json(
        f"{base_url}/sessions",
        {"id_comercio": comercio_id, "id_cliente": cliente_id},
    )
    if status == 201:
        session_id = int(payload["id"])
        pedido_id = _create_pedido(base_url, session_id)
        _associate_pedido(base_url, session_id, pedido_id)
        return session_id, pedido_id
    if status == 409:
        detail = _error_detail(payload)
        print(f"error: {detail}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(f"unexpected status {status} from POST /sessions")


def _create_pedido(base_url: str, session_id: int) -> int:
    status, payload = _post_json(
        f"{base_url}/pedidos",
        {"id_session": session_id},
    )
    if status in (200, 201):
        return int(payload["id"])
    detail = _error_detail(payload)
    _close_session(base_url, session_id)
    print(f"error: {detail}", file=sys.stderr)
    raise SystemExit(1)


def _associate_pedido(base_url: str, session_id: int, pedido_id: int) -> None:
    status, payload = _post_json(
        f"{base_url}/sessions/{session_id}/pedido",
        {"id_pedido": pedido_id},
        method="PUT",
    )
    if status in (200, 201):
        return
    detail = _error_detail(payload)
    _close_session(base_url, session_id)
    print(f"error: {detail}", file=sys.stderr)
    raise SystemExit(1)


def _close_session(base_url: str, session_id: int) -> None:
    try:
        _post_json(f"{base_url}/sessions/{session_id}/cerrar", {})
    except Exception as exc:
        print(f"warning: failed to close session {session_id}: {exc}")


def _fetch_pedido_detalle(base_url: str, pedido_id: int) -> tuple[int, object] | tuple[str, str]:
    url = f"{base_url}/pedidos/{pedido_id}/detalle"
    try:
        status, payload = _post_json(url, {}, method="GET")
    except Exception as exc:
        return ("warning", str(exc))
    if status == 200 and isinstance(payload, dict):
        return (200, payload)
    detail = _error_detail(payload)
    return ("warning", f"HTTP {status}: {detail}")


def _read_int(prompt: str) -> int:
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("please enter a valid integer", file=sys.stderr)


def _print_responses(payload: dict) -> None:
    responses = payload.get("responses", []) if isinstance(payload, dict) else []
    for response in responses:
        if isinstance(response, dict) and "message" in response:
            print(f"<- message={response['message']}")
        else:
            print(f"<- raw={json.dumps(response, ensure_ascii=False)}")


def response_modified_order(responses: Any) -> bool:
    for response in responses:
        if not isinstance(response, dict):
            continue
        if response.get("status") != "executed":
            continue
        if response.get("intent") in ORDER_MUTATING_INTENTS:
            return True
    return False


def format_order_table(lineas: Any) -> str:
    if not lineas:
        return "Pedido actual: vacío\n"

    headers = ("Producto", "Presentación", "Cantidad")
    rows: list[tuple[str, str, str]] = []
    for line in lineas:
        if not isinstance(line, dict):
            continue
        nombre = str(line.get("producto_nombre", "") or "")
        presentacion = line.get("presentacion_descripcion")
        if presentacion is None or str(presentacion).strip() == "":
            presentacion = "—"
        cantidad = line.get("cantidad", 0)
        try:
            cantidad_str = str(int(cantidad))
        except (TypeError, ValueError):
            cantidad_str = str(cantidad)
        rows.append((nombre, str(presentacion), cantidad_str))

    if not rows:
        return "Pedido actual: vacío\n"

    widths = [
        max(len(headers[0]), max(len(r[0]) for r in rows)),
        max(len(headers[1]), max(len(r[1]) for r in rows)),
        max(len(headers[2]), max(len(r[2]) for r in rows)),
    ]
    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    header_line = "| " + " | ".join(
        f"{headers[i]:<{widths[i]}}" for i in range(3)
    ) + " |"
    body_lines = []
    for row in rows:
        body_lines.append(
            "| "
            + " | ".join([
                f"{row[0]:<{widths[0]}}",
                f"{row[1]:<{widths[1]}}",
                f"{row[2]:>{widths[2]}}",
            ])
            + " |"
        )

    return (
        "Pedido actual:\n"
        + border + "\n"
        + header_line + "\n"
        + border + "\n"
        + "\n".join(body_lines) + "\n"
        + border + "\n"
    )


def _format_kv_table(title: str, rows: list[tuple[str, str]]) -> str:
    if not rows:
        return f"{title}:\n(none)\n"
    key_width = max(len("Field"), max(len(str(k)) for k, _ in rows))
    value_width = max(len("Value"), max(len(str(v)) for _, v in rows))
    border = "+" + "+".join("-" * (w + 2) for w in (key_width, value_width)) + "+"
    header = "| " + " | ".join(
        [f"{'Field':<{key_width}}", f"{'Value':<{value_width}}"]
    ) + " |"
    body = "\n".join(
        "| "
        + " | ".join(
            [f"{str(k):<{key_width}}", f"{str(v):<{value_width}}"]
        )
        + " |"
        for k, v in rows
    )
    return f"{title}:\n{border}\n{header}\n{border}\n{body}\n{border}\n"


def _format_intent_table(
    title: str,
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
) -> str:
    if not rows:
        return f"{title}:\n(none)\n"
    widths = [
        max(len(headers[i]), max(len(str(row[i])) for row in rows))
        for i in range(len(headers))
    ]
    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    header_line = "| " + " | ".join(
        f"{headers[i]:<{widths[i]}}" for i in range(len(headers))
    ) + " |"
    body_lines: list[str] = []
    for row in rows:
        body_lines.append(
            "| "
            + " | ".join(
                f"{str(row[i]):<{widths[i]}}" for i in range(len(headers))
            )
            + " |"
        )
    return (
        f"{title}:\n"
        + border
        + "\n"
        + header_line
        + "\n"
        + border
        + "\n"
        + "\n".join(body_lines)
        + "\n"
        + border
        + "\n"
    )


def _format_pending_state_snapshot(title: str, snapshot: dict) -> str:
    return _format_kv_table(
        title,
        [
            ("active_intent", str(snapshot.get("active_intent", "<not available>"))),
            ("active_status", str(snapshot.get("active_status", "<not available>"))),
            (
                "active_source_text",
                str(snapshot.get("active_source_text", "<not available>")),
            ),
            (
                "active_quantity",
                str(snapshot.get("active_quantity", "<not available>")),
            ),
            (
                "active_candidate_ids",
                str(snapshot.get("active_candidate_ids", "<not available>")),
            ),
            (
                "queue_length",
                str(snapshot.get("queue_length", "<not available>")),
            ),
            (
                "queue_intents",
                str(snapshot.get("queue_intents", "<not available>")),
            ),
            (
                "queue_sources",
                str(snapshot.get("queue_sources", "<not available>")),
            ),
            (
                "context_type",
                str(snapshot.get("context_type", "<not available>")),
            ),
        ],
    )


def _format_pending_queue_table(title: str, queue: list[dict]) -> str:
    if not queue:
        return f"{title}:\n(none)\n"
    headers = (
        "Position",
        "Intent",
        "Status",
        "Source text",
        "Quantity",
        "Candidate IDs",
        "Requirements",
        "Resolved data",
    )
    rows: list[tuple[str, ...]] = []
    for index, item in enumerate(queue, start=1):
        rows.append(
            (
                str(index),
                str(item.get("intent", "<not available>")),
                str(item.get("status", "<not available>")),
                str(item.get("source_text", "<not available>")),
                str(item.get("quantity", "<not available>")),
                str(item.get("candidate_ids", "<not available>")),
                str(item.get("requirements", "<not available>")),
                str(item.get("resolved_data", "<not available>")),
            )
        )
    return _format_intent_table(title, headers, rows)


def _extract_diagnostics(payload: dict) -> list[dict]:
    diagnostics = payload.get("diagnostics", [])
    if not isinstance(diagnostics, list):
        return []
    return [item for item in diagnostics if isinstance(item, dict)]


def _redact_payload(payload: dict | list) -> dict | list:
    if isinstance(payload, dict):
        redacted: dict[object, object] = {}
        for key, value in payload.items():
            if str(key).casefold() in _REDACTED_KEYS_NORMALIZED:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]
    return payload


def _parse_debug_components(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset(_DEBUG_COMPONENT_ALIASES)
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [p for p in parts if p not in _DEBUG_COMPONENT_ALIASES]
    if unknown:
        print(
            f"error: unknown --debug-components value(s): {', '.join(unknown)}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return frozenset(parts)


def _classify_diagnostic_event(event: dict) -> str:
    phase = str(event.get("phase", ""))
    if phase == "classifier":
        method = str(event.get("method", ""))
        if method == "query":
            return "classifier_input"
        return "classifier_output"
    if phase == "resolver":
        method = str(event.get("method", ""))
        if method == "resolve":
            return "resolver_input"
        return "resolver_output"
    if phase == "pending":
        return "pending_state"
    return "unknown"


def _render_classifier_input(event: dict) -> str:
    title = (
        f"CLASSIFIER INPUT [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}]"
    )
    redacted_event = _redact_payload(event)
    redacted_dict: dict = redacted_event if isinstance(redacted_event, dict) else {}
    return _format_kv_table(
        title,
        [
            ("call_id", str(redacted_dict.get("call_id", "<not available>"))),
            ("turn_id", str(redacted_dict.get("turn_id", "<not available>"))),
            ("raw_message", str(redacted_dict.get("raw_message", "<not available>"))),
            (
                "active_context_type",
                str(redacted_dict.get("active_context_type", "<not available>")),
            ),
            (
                "has_active_pending_intent",
                str(redacted_dict.get("has_active_pending_intent", "<not available>")),
            ),
            (
                "active_pending_intent",
                str(redacted_dict.get("active_pending_intent", "<not available>")),
            ),
            (
                "queued_intent_count",
                str(redacted_dict.get("queued_intent_count", "<not available>")),
            ),
            (
                "classifier_class",
                str(redacted_dict.get("classifier_class", "<not available>")),
            ),
            (
                "classifier_method",
                str(redacted_dict.get("classifier_method", "<not available>")),
            ),
            ("prompt_name", str(redacted_dict.get("prompt_name", "<not available>"))),
            ("model", str(redacted_dict.get("model", "<not available>"))),
            (
                "redacted_payload",
                json.dumps(redacted_dict, ensure_ascii=False),
            ),
        ],
    )


def _render_classifier_output(event: dict) -> str:
    title = (
        f"CLASSIFIER OUTPUT [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}]"
    )
    redacted_event = _redact_payload(event)
    redacted_dict: dict = redacted_event if isinstance(redacted_event, dict) else {}
    result_type = str(redacted_dict.get("result_type", ""))
    if result_type and result_type != "IntentClassificationResult":
        return _format_kv_table(
            title,
            [
                ("result_type", result_type),
                (
                    "parse_errors",
                    str(redacted_dict.get("parse_errors", "<not available>")),
                ),
                ("result", str(redacted_dict.get("result", "<not available>"))),
            ],
        )
    intents = redacted_dict.get("result", {})
    if isinstance(intents, dict):
        intent_list = intents.get("intents", [])
    else:
        intent_list = []
    if not isinstance(intent_list, list) or not intent_list:
        return f"{title}:\n(none)\n"
    headers = (
        "Index",
        "Intent",
        "Source text",
        "Quantity",
        "Confidence",
        "Status",
        "Resolved data",
        "Requirements",
        "Candidate IDs",
        "Raw payload",
    )
    rows: list[tuple[str, ...]] = []
    for index, intent in enumerate(intent_list, start=1):
        if not isinstance(intent, dict):
            continue
        rows.append(
            (
                str(index),
                str(intent.get("intent", "<not available>")),
                str(intent.get("mensaje", "<not available>")),
                str(intent.get("quantity", "<not available>")),
                str(intent.get("confidence", "<not available>")),
                str(intent.get("status", "<not available>")),
                str(intent.get("resolved_data", "<not available>")),
                str(intent.get("requirements", "<not available>")),
                str(intent.get("candidate_ids", "<not available>")),
                json.dumps(intent, ensure_ascii=False),
            )
        )
    return _format_intent_table(title, headers, rows)


def _render_resolver_input(event: dict) -> str:
    title = (
        f"RESOLVER INPUT [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}]"
    )
    return _format_kv_table(
        title,
        [
            ("call_id", str(event.get("call_id", "<not available>"))),
            ("turn_id", str(event.get("turn_id", "<not available>"))),
            (
                "resolver_class",
                str(event.get("resolver_class", "<not available>")),
            ),
            (
                "resolver_method",
                str(event.get("resolver_method", "<not available>")),
            ),
            (
                "resolver_purpose",
                str(event.get("resolver_purpose", "<not available>")),
            ),
            ("session_id", str(event.get("session_id", "<not available>"))),
            ("context_type", str(event.get("context_type", "<not available>"))),
            ("incoming_text", str(event.get("incoming_text", "<not available>"))),
            (
                "normalized_text",
                str(event.get("normalized_text", "<not available>")),
            ),
            ("intent", str(event.get("intent", "<not available>"))),
            ("source_text", str(event.get("source_text", "<not available>"))),
            ("quantity", str(event.get("quantity", "<not available>"))),
            (
                "status_before",
                str(event.get("status_before", "<not available>")),
            ),
            (
                "requirements_before",
                str(event.get("requirements_before", "<not available>")),
            ),
            (
                "resolved_data_before",
                str(event.get("resolved_data_before", "<not available>")),
            ),
            (
                "candidate_ids_before",
                str(event.get("candidate_ids_before", "<not available>")),
            ),
            (
                "candidate_count",
                str(event.get("candidate_count", "<not available>")),
            ),
            (
                "queued_intent_count",
                str(event.get("queued_intent_count", "<not available>")),
            ),
        ],
    )


def _render_resolver_candidates(event: dict) -> str | None:
    catalog = event.get("candidate_catalog")
    if not isinstance(catalog, list) or not catalog:
        return None
    title = (
        f"RESOLVER CANDIDATES [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}]"
    )
    headers = (
        "Index",
        "producto_presentacion_id",
        "producto_id",
        "producto_nombre",
        "presentacion_id",
        "presentacion_codigo",
        "presentacion_descripcion",
        "categoria_id",
        "categoria_nombre",
        "activo",
        "disponible",
    )
    rows: list[tuple[str, ...]] = []
    for index, row in enumerate(catalog, start=1):
        if not isinstance(row, dict):
            continue
        rows.append(
            (
                str(index),
                str(row.get("producto_presentacion_id", "<not available>")),
                str(row.get("producto_id", "<not available>")),
                str(row.get("producto_nombre", "<not available>")),
                str(row.get("presentacion_id", "<not available>")),
                str(row.get("presentacion_codigo", "<not available>")),
                str(row.get("presentacion_descripcion", "<not available>")),
                str(row.get("categoria_id", "<not available>")),
                str(row.get("categoria_nombre", "<not available>")),
                str(row.get("activo", "<not available>")),
                str(row.get("disponible", "<not available>")),
            )
        )
    return _format_intent_table(title, headers, rows)


def _render_resolver_output(event: dict) -> str:
    title = (
        f"RESOLVER OUTPUT [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}]"
    )
    return _format_kv_table(
        title,
        [
            ("call_id", str(event.get("call_id", "<not available>"))),
            ("turn_id", str(event.get("turn_id", "<not available>"))),
            ("result_type", str(event.get("result_type", "<not available>"))),
            ("status_after", str(event.get("status_after", "<not available>"))),
            (
                "selected_candidate_id",
                str(event.get("selected_candidate_id", "<not available>")),
            ),
            (
                "selected_product",
                str(event.get("selected_product", "<not available>")),
            ),
            (
                "quantity_after",
                str(event.get("quantity_after", "<not available>")),
            ),
            (
                "requirements_after",
                str(event.get("requirements_after", "<not available>")),
            ),
            (
                "resolved_data_after",
                str(event.get("resolved_data_after", "<not available>")),
            ),
            (
                "candidate_ids_after",
                str(event.get("candidate_ids_after", "<not available>")),
            ),
            (
                "candidate_count_after",
                str(event.get("candidate_count_after", "<not available>")),
            ),
            (
                "rejection_reason",
                str(event.get("rejection_reason", "<not available>")),
            ),
            (
                "clarification_message",
                str(event.get("clarification_message", "<not available>")),
            ),
        ],
    )


def _render_resolver_matches(event: dict) -> str | None:
    matches = event.get("matches")
    if not isinstance(matches, list) or not matches:
        return None
    title = (
        f"RESOLVER MATCHES [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}]"
    )
    headers = (
        "Index",
        "Candidate ID",
        "Candidate",
        "Score",
        "Match type",
        "Matched text",
        "Accepted",
    )
    rows: list[tuple[str, ...]] = []
    for index, match in enumerate(matches, start=1):
        if not isinstance(match, dict):
            continue
        rows.append(
            (
                str(index),
                str(match.get("candidate_id", "<not available>")),
                str(match.get("candidate", "<not available>")),
                str(match.get("score", "<not available>")),
                str(match.get("match_type", "<not available>")),
                str(match.get("matched_text", "<not available>")),
                str(match.get("accepted", "<not available>")),
            )
        )
    return _format_intent_table(title, headers, rows)


def _render_pending_state(event: dict) -> str:
    title = (
        f"PENDING STATE [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}] "
        f"[{event.get('snapshot_phase', 'snapshot')}]"
    )
    snapshot_text = _format_pending_state_snapshot(title, event)
    queue = event.get("queue_intents")
    if not isinstance(queue, list) or not queue:
        return snapshot_text
    queue_rows: list[dict] = []
    if isinstance(queue, list):
        for index, intent_name in enumerate(queue, start=1):
            sources = event.get("queue_sources", [])
            source = sources[index - 1] if index - 1 < len(sources) else "<not available>"
            queue_rows.append(
                {
                    "position": index,
                    "intent": intent_name,
                    "status": "<not available>",
                    "source_text": source,
                    "quantity": "<not available>",
                    "candidate_ids": "<not available>",
                    "requirements": "<not available>",
                    "resolved_data": "<not available>",
                }
            )
    if not queue_rows:
        return snapshot_text
    queue_text = _format_pending_queue_table(
        f"PENDING QUEUE [TURN {event.get('turn_id', 1)}] "
        f"[{event.get('call_id', '<no-id>')}]",
        queue_rows,
    )
    return snapshot_text + queue_text


def _render_diagnostics(
    components: frozenset[str],
    events: list[dict],
) -> None:
    if not events:
        return
    for event in events:
        category = _classify_diagnostic_event(event)
        if category in {"classifier_input", "classifier_output"}:
            if "classifier" not in components:
                continue
            if category == "classifier_input":
                print(_render_classifier_input(event), end="")
            else:
                print(_render_classifier_output(event), end="")
        elif category in {"resolver_input", "resolver_output"}:
            if "resolver" not in components:
                continue
            if category == "resolver_input":
                print(_render_resolver_input(event), end="")
                candidates = _render_resolver_candidates(event)
                if candidates:
                    print(candidates, end="")
            else:
                print(_render_resolver_output(event), end="")
                matches = _render_resolver_matches(event)
                if matches:
                    print(matches, end="")
        elif category == "pending_state":
            if "pending" not in components:
                continue
            print(_render_pending_state(event), end="")
        # unknown categories are skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cli_chat_client",
        description=(
            "Standalone CLI HTTP client for the FastAPI incoming-messages "
            "endpoint. Pass --debug-flow to receive classifier and resolver "
            "diagnostic tables in the response."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override the base URL of the API (default: 127.0.0.1:8000).",
    )
    parser.add_argument(
        "--debug-flow",
        action="store_true",
        help=(
            "Send X-Debug-Flow on every request and render the diagnostic "
            "tables included in the response."
        ),
    )
    parser.add_argument(
        "--debug-components",
        default="",
        help=(
            "Comma-separated subset of {classifier, resolver, pending} to "
            "render under --debug-flow. Empty enables all three."
        ),
    )
    args, _unknown = parser.parse_known_args()
    argv = sys.argv[1:]
    base_url = _resolve_base_url(argv)
    debug_components = _parse_debug_components(args.debug_components)

    comercio_id = _read_int("comercio_id: ")
    cliente_id = _read_int("cliente_id: ")

    session_id, pedido_id = _create_session(base_url, comercio_id, cliente_id)
    print(f"<session {session_id}>")
    print(f"<pedido {pedido_id}>")

    extra_headers: dict[str, str] | None = (
        {"X-Debug-Flow": "1"} if args.debug_flow else None
    )

    try:
        while True:
            line = input(
                f"[comercio={comercio_id} cliente={cliente_id} session={session_id}]> "
            )
            if line.strip().lower() == "exit":
                break
            if not line.strip():
                continue
            status, payload = _post_json(
                f"{base_url}/comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages",
                {"message": line},
                extra_headers=extra_headers,
            )
            if status == 200 and isinstance(payload, dict):
                _print_responses(payload)
                if args.debug_flow:
                    redacted = _redact_payload(payload)
                    if isinstance(redacted, dict):
                        diagnostics = _extract_diagnostics(redacted)
                        if diagnostics:
                            _render_diagnostics(debug_components, diagnostics)
                if response_modified_order(payload.get("responses", [])):
                    detail = _fetch_pedido_detalle(base_url, pedido_id)
                    if isinstance(detail, tuple) and len(detail) == 2:
                        if detail[0] == 200 and isinstance(detail[1], dict):
                            lineas_raw = detail[1].get("lineas", [])
                            lineas = lineas_raw if isinstance(lineas_raw, list) else []
                            print(format_order_table(lineas), end="")
                        elif detail[0] == "warning":
                            print(
                                f"Warning: the order was modified, but its "
                                f"updated detail could not be retrieved. "
                                f"({detail[1]})"
                            )
            elif isinstance(payload, dict):
                _print_responses(payload)
            else:
                print(f"<- raw={payload}")
    finally:
        _close_session(base_url, session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()

"""Cliente de chat sobre el app-server de Codex (T03).

Envuelve `CodexAppServer.request` con el mismo contrato semántico que
`deepseek_client.py`, pero **asíncrono** (el manager vive en el event loop):
`call_codex_chat` es una corrutina que se espera directo, nunca dentro de
`asyncio.to_thread`.

Contrato (global-constraints.md §Codex client and errors; receta
`integration-codex-appserver.md` §Turn lifecycle verification FR-01 y
§Request param shapes FR-01b, source `08e482e2` / `rust-v0.147.0-alpha.9`):

- **Ciclo de turno STREAMING:** la response de `turn/start` solo acepta el
  turno (`{turn:{id,status:"inProgress",items:[]}}`) — nunca texto ni usage.
  El texto final se toma SOLO de la notificación `item/completed` con
  `item.type=="agentMessage"` y `item.text`; el usage SOLO de
  `thread/tokenUsage/updated`; la terminación se detecta SOLO por
  `turn/completed` (no existe `turn/end` ni `turn/poll`). Los deltas
  (`item/agentMessage/delta`) son solo para UI y en v1 se ignoran. Un error de
  cuota en ejecución llega como notificación `error` + `turn/completed` con
  `status:"failed"` y `turn.error`; un error de aceptación SÍ puede ser
  JSON-RPC error en la response — son caminos distintos.
- **Correlación por `(user_id, turnId)`:** los handlers de notificación se
  registran UNA vez a nivel de módulo (guard idempotente) y despachan a un
  registro propio de contextos de espera (futures por turno); llamadas
  simultáneas del mismo usuario no pueden cruzar texto, usage ni errores.
- **Request params v2:** `thread/start` → `{model, developerInstructions?}`
  (el system prompt va al thread, que el cliente crea por llamada);
  `turn/start` → `{threadId, input:[{type:"text",text}], model}`. NO existen
  `message`, `system`, `temperature`, `threadID` ni `response_format` en el
  wire: `temperature` y `response_format` de la firma pública congelada solo
  configuran el comportamiento local (temperatura no se envía; `json_object`
  parsea el texto final con `json.loads`).
- Jerarquía congelada `CodexError` (base con `.message`): `CodexRateLimitError`,
  `CodexAuthError`, `CodexBusyError`, `CodexTimeoutError`; re-usa
  `CodexSpawnError`/`CodexRequestError` de T02. El spawn sin hueco se re-lanza
  como `CodexBusyError`; los errores de aceptación del server se mapean por
  `code` (`UsageLimitExceeded`/rate-limit → cuota; códigos de auth/refresh →
  vínculo), sin inventar códigos. Los fallos de turno se mapean desde
  `turn.error` (o la notificación `error`): `codexErrorInfo`
  `usageLimitExceeded` → cuota, `unauthorized` → vínculo, cualquier otro →
  `CodexError(CODEX_TURN_FAILED_MESSAGE)`.
- `CodexUsage` con los conteos SOLO desde la notificación
  `thread/tokenUsage/updated` correlacionada (parse defensivo; ceros si no
  existen; nunca valores inventados), `cost_usd=0.0`,
  `cost_source="chatgpt_quota"`, `quota_requests=1`.
- Con `response_format="json_object"` el texto final se parsea con `json.loads`
  y, si falla, se reintenta conversacionalmente (máx.
  `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES`) con un nuevo `turn/start` en el
  MISMO thread — turno correctivo corto sin reenviar la fuente ni el system
  prompt (patrón `_DeepSeekExplainerConversation`).

Seguridad: solo se loguean `user_id[:8]`, `model`, longitudes y previews
truncados; nunca `auth.json` ni el contenido completo de los mensajes fuente.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Literal

from backend.agents.explainer_openrouter import (
    OPENROUTER_EXPLAINER_TEMPERATURE,
    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
)
from backend.codex_app_server import (
    CODEX_REQUEST_TIMEOUT_SECONDS,
    CodexRequestError,
    CodexSpawnError,
    CodexTimeoutError as CodexAppServerTimeoutError,
    codex_manager,
    codex_manager as _app_server_codex_manager,
)
from backend.codex_model_routing import CODEX_MODEL

logger = logging.getLogger("backend.codex_client")

# Mensajes UX congelados (global-constraints.md §Codex client and errors).
CODEX_RATE_LIMIT_MESSAGE = (
    "Has agotado la cuota de Codex de tu plan ChatGPT por ahora. "
    "Inténtalo más tarde o cambia de proveedor."
)
CODEX_AUTH_MESSAGE = (
    "Tu cuenta ChatGPT ya no está vinculada. Vuelve a vincularla en Ajustes."
)
CODEX_BUSY_MESSAGE = (
    "Codex está saturado en este momento. Espera un poco e inténtalo de nuevo."
)
CODEX_TIMEOUT_MESSAGE = (
    "Codex tardó demasiado en responder. Espera un poco e inténtalo de nuevo."
)
# Constante ADITIVA del amendo FR-01: fallo de turno sin mapeo conocido. Los
# mensajes UX existentes no cambian.
CODEX_TURN_FAILED_MESSAGE = (
    "Codex no pudo completar el turno. Espera un poco e inténtalo de nuevo."
)

# Códigos de error del app-server que indican cuota agotada (per-docs; solo se
# mapean los que el server emite, no se inventan códigos nuevos).
_RATE_LIMIT_ERROR_CODES = frozenset({"UsageLimitExceeded", "RateLimitExceeded"})
# Subcadenas de códigos con semántica de auth/refresh/desvinculación.
_AUTH_ERROR_CODE_TOKENS = (
    "auth",
    "refresh",
    "login",
    "loggedin",
    "credential",
    "unauthorized",
    "session",
    "expired",
)


class CodexError(Exception):
    """Error base del cliente Codex, con `.message` para la UX."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CodexRateLimitError(CodexError):
    """Cuota de ChatGPT agotada (UsageLimitExceeded y similares)."""


class CodexAuthError(CodexError):
    """Refresh fallido / cuenta desvinculada."""


class CodexBusyError(CodexError):
    """Capacidad del app-server agotada (spawn sin hueco)."""


class CodexTimeoutError(CodexError):
    """El app-server no respondió dentro del timeout."""


class CodexUsage:
    """Uso de un turno Codex, con atributos compatibles con Gemini.

    Los conteos se rellenan SOLO desde la notificación
    `thread/tokenUsage/updated` correlacionada con el turno (parse defensivo;
    ceros si faltan; nunca valores inventados). Mapeo congelado (se prefiere
    `tokenUsage.last`; si no existe, `tokenUsage.total`):
    `inputTokens → prompt_token_count`, `cacheWriteInputTokens →
    tool_use_prompt_token_count`, `outputTokens → candidates_token_count`,
    `reasoningOutputTokens → thoughts_token_count`, `totalTokens →
    total_token_count`. La cuota de ChatGPT no produce coste USD:
    `cost_usd=0.0`, `cost_source="chatgpt_quota"` y `quota_requests=1` por
    llamada.
    """

    def __init__(
        self,
        *,
        prompt_token_count: int = 0,
        tool_use_prompt_token_count: int = 0,
        candidates_token_count: int = 0,
        thoughts_token_count: int = 0,
        total_token_count: int = 0,
    ):
        self.prompt_token_count = prompt_token_count
        self.tool_use_prompt_token_count = tool_use_prompt_token_count
        self.candidates_token_count = candidates_token_count
        self.thoughts_token_count = thoughts_token_count
        self.total_token_count = total_token_count
        self.cost_usd = 0.0
        self.cost_source = "chatgpt_quota"
        self.quota_requests = 1


# --- Parseo defensivo ---------------------------------------------------- #

def _as_count(value: Any) -> int:
    """Conteo entero no negativo; bool/negativo/no numérico cuenta como 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return 0


def _parse_token_usage(token_usage: dict[str, Any]) -> CodexUsage:
    """Conteos desde la notificación `thread/tokenUsage/updated`.

    Se prefiere el breakdown `last`; si no existe, `total`. Los campos del
    breakdown usan los nombres reales del source (camelCase); la ausencia de
    un campo nunca es un error (0).
    """
    breakdown = token_usage.get("last")
    if not isinstance(breakdown, dict):
        breakdown = token_usage.get("total")
    if not isinstance(breakdown, dict):
        breakdown = {}
    return CodexUsage(
        prompt_token_count=_as_count(breakdown.get("inputTokens")),
        tool_use_prompt_token_count=_as_count(breakdown.get("cacheWriteInputTokens")),
        candidates_token_count=_as_count(breakdown.get("outputTokens")),
        thoughts_token_count=_as_count(breakdown.get("reasoningOutputTokens")),
        total_token_count=_as_count(breakdown.get("totalTokens")),
    )


def _extract_thread_id(result: Any) -> str | None:
    """`thread.id` de la response de `thread/start` (defensivo).

    Shape verificado: `{"thread": {"id": ...}}`. Acepta también `id` al top
    level y los nombres legacy `threadId`/`threadID` por robustez.
    """
    if not isinstance(result, dict):
        return None
    thread = result.get("thread")
    if isinstance(thread, dict):
        value = thread.get("id")
        if isinstance(value, str) and value:
            return value
    for key in ("id", "threadId", "threadID"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_turn_id(result: Any) -> str | None:
    """`turn.id` de la response de `turn/start` (defensivo).

    Shape verificado: `{"turn": {"id": ...}}`; acepta también `id` al top
    level. La response NO lleva texto ni usage: el id es lo único que se toma
    de ella.
    """
    if not isinstance(result, dict):
        return None
    turn = result.get("turn")
    if isinstance(turn, dict):
        value = turn.get("id")
        if isinstance(value, str) and value:
            return value
    value = result.get("id")
    if isinstance(value, str) and value:
        return value
    return None


def _flatten_message_text(message: Any) -> str:
    """Texto plano de un mensaje (str o dict con `content`)."""
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _flatten_messages(messages: list[dict[str, Any]]) -> str:
    """Los mensajes del llamante como un único user message inicial.

    El app-server recibe UN input por turno (`input: [{type:"text",text}]`);
    los agentes pasan un único user message (patrón
    `_build_inline_source_message`). Si hay varios, se concatenan; nunca se
    pierde contenido.
    """
    return "\n\n".join(
        text for text in (_flatten_message_text(m) for m in messages) if text
    )


def _preview(text: str, limit: int = 200) -> str:
    """Preview seguro y truncado para logs (nunca contenido íntegro)."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "..."


def _payload_correction_message(exc: Exception) -> str:
    """Turno correctivo corto: solo el problema, sin reenviar la fuente."""
    return (
        "Tu respuesta anterior no es un objeto JSON válido.\n"
        f"Problema detectado: {exc}\n"
        "Responde de nuevo ÚNICAMENTE con un objeto JSON válido que cumpla "
        "exactamente el contrato solicitado, sin texto adicional."
    )


def _parse_turn_json(text: str) -> Any:
    """`json.loads` del texto final del turno (seam de tests)."""
    return json.loads(text)


# --- Request params v2 (reconciliación FR-01b) ---------------------------- #

def _thread_start_params(model: str, system_prompt: str | None) -> dict[str, Any]:
    """Params de `thread/start` v2: el system prompt viaja en
    `developerInstructions` (el cliente crea un thread por llamada; no existe
    un campo `system` ni un `settings` top-level)."""
    params: dict[str, Any] = {"model": model}
    if system_prompt:
        params["developerInstructions"] = system_prompt
    return params


def _turn_params(*, thread_id: str | None, text: str, model: str) -> dict[str, Any]:
    """Params de `turn/start` v2: `{threadId, input:[{type:"text",text}],
    model}`. NO existen `message`, `system`, `temperature`, `threadID` ni
    `response_format` (verificación de source FR-01b)."""
    params: dict[str, Any] = {
        "input": [{"type": "text", "text": text}],
        "model": model,
    }
    if thread_id is not None:
        params["threadId"] = thread_id
    return params


# --- Correlación de notificaciones (FR-01) -------------------------------- #

class _TurnWaitContext:
    """Estado de espera de UN turno, correlacionado por `(user_id, turnId)`.

    Lo rellenan los handlers de notificación y lo consume `call_codex_chat`
    tras `turn/completed` (o el timeout). El texto final y el usage solo son
    autoritativos aquí (`item/completed` agentMessage y
    `thread/tokenUsage/updated`); los deltas no se acumulan.
    """

    def __init__(self) -> None:
        self.completed = asyncio.Event()
        self.status: str | None = None
        self.final_text: str | None = None
        self.usage = CodexUsage()
        self.turn_error: dict | None = None
        self.error_notification: dict | None = None


# Registro de esperas por `(user_id, turnId)`: cada `turn/start` produce un
# `turnId` distinto y cada llamada tiene su propio contexto; varias llamadas
# simultáneas del mismo usuario no pueden cruzar texto, usage ni errores.
_TURN_WAITS: dict[tuple[str, str], _TurnWaitContext] = {}
# Buzón de notificaciones por `(user_id, turnId)`: el reader del app-server
# puede despachar los handlers ANTES de que la corrutina del cliente reanude
# tras la response de `turn/start` (la resolución de la response da dos saltos
# de cola y los tasks de los handlers se cuelan delante). El cliente registra
# su contexto al reanudar y reproduce el buzón de su turno antes de esperar
# `turn/completed`; las notificaciones posteriores van por la vía directa.
_INBOX: dict[tuple[str, str], list[tuple[str, Any]]] = {}
_notification_handlers_registered = False


def _on_turn_completed(user_id: str, params: Any) -> None:
    context = _turn_wait_context(user_id, params)
    if context is None:
        return  # turno desconocido: se ignora sin error
    context.status = params["turn"].get("status")
    error = params["turn"].get("error")
    context.turn_error = error if isinstance(error, dict) else None
    context.completed.set()


def _on_item_completed(user_id: str, params: Any) -> None:
    context = _turn_wait_context(user_id, params)
    if context is None:
        return
    item = params.get("item")
    if isinstance(item, dict) and item.get("type") == "agentMessage":
        text = item.get("text")
        if isinstance(text, str):
            # El texto final es autoritativo SOLO aquí; si llegan varios
            # agentMessage, gana el último.
            context.final_text = text


def _on_token_usage_updated(user_id: str, params: Any) -> None:
    context = _turn_wait_context(user_id, params)
    if context is None:
        return
    token_usage = params.get("tokenUsage")
    if isinstance(token_usage, dict):
        # Si llegan varios, gana el último correlacionado.
        context.usage = _parse_token_usage(token_usage)


def _on_error_notification(user_id: str, params: Any) -> None:
    context = _turn_wait_context(user_id, params)
    if context is None:
        return
    error = params.get("error")
    if isinstance(error, dict):
        context.error_notification = error


def _dispatch_to_context(method: str, user_id: str, params: Any) -> None:
    """Aplica una notificación ya correlacionada al contexto del turno."""
    if method == "turn/completed":
        _on_turn_completed(user_id, params)
    elif method == "item/completed":
        _on_item_completed(user_id, params)
    elif method == "thread/tokenUsage/updated":
        _on_token_usage_updated(user_id, params)
    elif method == "error":
        _on_error_notification(user_id, params)


def _notification_turn_id(params: Any) -> str | None:
    """`turnId` de una notificación (las correlacionadas lo llevan; solo
    `turn/completed` lo trae anidado en `turn.id` — shape verificado)."""
    if not isinstance(params, dict):
        return None
    turn = params.get("turn")
    if isinstance(turn, dict):
        turn_id = turn.get("id")
    else:
        turn_id = params.get("turnId")
    if isinstance(turn_id, str) and turn_id:
        return turn_id
    return None


def _turn_wait_context(user_id: str, params: Any) -> _TurnWaitContext | None:
    """Contexto del turno de una notificación, o None si el turno no se espera."""
    turn_id = _notification_turn_id(params)
    if turn_id is None:
        return None
    return _TURN_WAITS.get((user_id, turn_id))


def _notification_handler(method: str) -> Callable[[str, Any], None]:
    """Handler de una notificación: vía directa si el contexto ya está
    registrado; si no, encola en el buzón del turno (el cliente lo reproduce
    al registrar su contexto, antes de esperar `turn/completed`)."""

    def handler(user_id: str, params: Any) -> None:
        if _turn_wait_context(user_id, params) is not None:
            _dispatch_to_context(method, user_id, params)
            return
        turn_id = _notification_turn_id(params)
        if turn_id is None:
            return
        _INBOX.setdefault((user_id, turn_id), []).append((method, params))

    return handler


def _replay_inbox(user_id: str, turn_id: str) -> None:
    """Reproduce las notificaciones que llegaron antes del registro del
    contexto del turno (perdidas de otro modo: los tasks de los handlers
    pueden ejecutarse antes de que la corrutina reanude tras la response)."""
    pending = _INBOX.pop((user_id, turn_id), None)
    if not pending:
        return
    for method, params in pending:
        _dispatch_to_context(method, user_id, params)


def _ensure_notification_handlers() -> None:
    """Registra los handlers de notificación UNA vez (guard idempotente).

    Solo se registran `turn/completed`, `item/completed`,
    `thread/tokenUsage/updated` y `error`; `turn/started`, `item/started` y
    `item/agentMessage/delta` se ignoran en v1 (solo UI/progreso).

    Se registran en el singleton real del app-server (no en el alias del
    módulo): los tests envuelven `codex_client.codex_manager` para observar
    requests, pero las notificaciones las despacha el gestor real.
    """
    global _notification_handlers_registered
    if _notification_handlers_registered:
        return
    _notification_handlers_registered = True
    manager = _app_server_codex_manager
    for method in (
        "turn/completed",
        "item/completed",
        "thread/tokenUsage/updated",
        "error",
    ):
        manager.add_notification_handler(method, _notification_handler(method))


def _map_turn_error(turn_error: Any, error_notification: Any) -> CodexError:
    """Mapea un turno fallido: `turn.error` (preferido) o la notificación
    `error` registrada. `codexErrorInfo` comparado case-insensitive:
    `usageLimitExceeded` → `CodexRateLimitError`; `unauthorized` →
    `CodexAuthError`; cualquier otro (o error ausente) → fallo genérico.
    """
    error = turn_error if isinstance(turn_error, dict) else error_notification
    if isinstance(error, dict):
        info = error.get("codexErrorInfo")
        if isinstance(info, str):
            normalized = info.strip().lower()
            if normalized == "usagelimitexceeded":
                return CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE)
            if normalized == "unauthorized":
                return CodexAuthError(CODEX_AUTH_MESSAGE)
    return CodexError(CODEX_TURN_FAILED_MESSAGE)


def _map_turn_outcome(
    status: str | None, turn_error: Any, error_notification: Any
) -> CodexError | None:
    """Desenlace de `turn/completed`: `None` = éxito; si no, el error mapeado.

    `completed` → éxito; `failed` → error mapeado desde `turn.error` o la
    notificación `error`; cualquier otro status (o ausente) → fallo genérico
    (defensivo).
    """
    if status == "completed":
        return None
    if status == "failed":
        return _map_turn_error(turn_error, error_notification)
    return CodexError(CODEX_TURN_FAILED_MESSAGE)


def _map_request_error(exc: CodexRequestError) -> CodexError:
    """Mapea un error object del server por su `code`, sin inventar códigos.

    `UsageLimitExceeded`/`RateLimitExceeded` → `CodexRateLimitError`; códigos
    con semántica de auth/refresh → `CodexAuthError`. El resto se re-lanza sin
    cambios como `CodexRequestError` (T02, con `.code/.message/.data`).
    """
    code = exc.code
    if isinstance(code, str):
        normalized = code.strip().lower()
        if normalized in {c.lower() for c in _RATE_LIMIT_ERROR_CODES}:
            return CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE)
        if any(token in normalized for token in _AUTH_ERROR_CODE_TOKENS):
            return CodexAuthError(CODEX_AUTH_MESSAGE)
    return exc


async def call_codex_chat(
    *,
    user_id: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    model: str = CODEX_MODEL,
    response_format: Literal["text", "json_object"] = "json_object",
    temperature: float | None = OPENROUTER_EXPLAINER_TEMPERATURE,
    timeout: float = CODEX_REQUEST_TIMEOUT_SECONDS,
) -> tuple[Any, CodexUsage]:
    """Chat con Codex (app-server) y devuelve `(data, CodexUsage)`.

    Ciclo de turno STREAMING (FR-01): `await codex_manager.acquire(user_id)`,
    `thread/start` (con `developerInstructions` = system prompt), y por
    intento `turn/start` en el MISMO thread con `input:[{type:"text",text}]`
    y override `model`. La response de `turn/start` solo aporta el `turnId`;
    el texto final, el usage y los errores llegan por notificaciones
    correlacionadas por `(user_id, turnId)`; el turno termina SOLO en
    `turn/completed` (no existe `turn/end`). El `timeout` aplica tanto a cada
    request RPC como a la espera de `turn/completed` de cada intento.

    Con `response_format="json_object"` el texto final se parsea con
    `json.loads` y, si falla, se reintenta conversacionalmente (máx.
    `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES`) con un turno correctivo corto
    (nuevo `turn/start` en el mismo thread) que no reenvía la fuente ni el
    system prompt. `temperature` se acepta por firma congelada pero NO se
    envía: `TurnStartParams` v2 no lo acepta (FR-01b).

    Corrutina async: se espera directo, nunca dentro de `asyncio.to_thread`.

    Raises:
        CodexBusyError: spawn sin hueco (`CodexSpawnError` re-lanzado).
        CodexRateLimitError / CodexAuthError: cuota en ejecución (notificación
            `error`/`turn.error`) o error object del server mapeado por `code`.
        CodexTimeoutError: sin `turn/completed` (o sin response RPC) dentro de
            `timeout`.
        CodexRequestError (T02): error object no mapeado (aceptación).
        CodexError: JSON inválido tras agotar los reintentos, o fallo de turno
            sin mapeo conocido (`CODEX_TURN_FAILED_MESSAGE`).
    """
    _ensure_notification_handlers()
    try:
        server = await codex_manager.acquire(user_id)
    except CodexSpawnError as exc:
        raise CodexBusyError(CODEX_BUSY_MESSAGE) from exc

    uses_json_mode = response_format == "json_object"
    total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
    first_text = _flatten_messages(messages)
    corrective_text = ""

    try:
        thread_result = await server.request(
            "thread/start",
            _thread_start_params(model, system_prompt),
            timeout=timeout,
        )
        thread_id = _extract_thread_id(thread_result)
        if thread_id is None:
            logger.warning(
                "[codex] thread/start sin id en la response (user %s)",
                user_id[:8],
            )

        for attempt in range(1, total_attempts + 1):
            text = first_text if attempt == 1 else corrective_text
            logger.info(
                "[codex] turn/start %s/%s (user %s, model %s, chars=%s)",
                attempt,
                total_attempts,
                user_id[:8],
                model,
                len(text),
            )
            turn_result = await server.request(
                "turn/start",
                _turn_params(thread_id=thread_id, text=text, model=model),
                timeout=timeout,
            )
            turn_id = _extract_turn_id(turn_result)
            if turn_id is None:
                raise CodexError(CODEX_TURN_FAILED_MESSAGE)
            # Registro del contexto de espera (sin await intermedio tras la
            # response) y reproducción del buzón: los handlers despachados por
            # el reader se correlacionan por (user_id, turnId); las
            # notificaciones que llegaron antes del registro se reproducen
            # aquí y las posteriores van por la vía directa.
            context = _TurnWaitContext()
            _TURN_WAITS[(user_id, turn_id)] = context
            # Reproducir notificaciones que el reader pudo despachar antes de
            # que esta corrutina reanudara tras la response (ver `_INBOX`).
            _replay_inbox(user_id, turn_id)
            try:
                try:
                    await asyncio.wait_for(context.completed.wait(), timeout=timeout)
                except asyncio.TimeoutError as exc:
                    raise CodexTimeoutError(CODEX_TIMEOUT_MESSAGE) from exc
                outcome = _map_turn_outcome(
                    context.status, context.turn_error, context.error_notification
                )
                if outcome is not None:
                    raise outcome
                final_text = context.final_text or ""
                usage = context.usage
                if not uses_json_mode:
                    return final_text, usage
                try:
                    return _parse_turn_json(final_text), usage
                except (ValueError, TypeError) as exc:
                    if attempt >= total_attempts:
                        raise CodexError(
                            "Codex no devolvió un objeto JSON válido tras "
                            f"{total_attempts} intentos."
                        ) from exc
                    logger.warning(
                        "[codex] JSON inválido del turno (user %s, intento %s/%s): %s",
                        user_id[:8],
                        attempt,
                        OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
                        _preview(str(exc)),
                    )
                    corrective_text = _payload_correction_message(exc)
            finally:
                # Sin fugas: cada intento retira su propia entrada (espera y
                # buzón de notificaciones pendientes del turno).
                _TURN_WAITS.pop((user_id, turn_id), None)
                _INBOX.pop((user_id, turn_id), None)
    except CodexAppServerTimeoutError as exc:
        raise CodexTimeoutError(CODEX_TIMEOUT_MESSAGE) from exc
    except CodexRequestError as exc:
        mapped = _map_request_error(exc)
        if mapped is exc:
            raise
        raise mapped from exc

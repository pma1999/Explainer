"""HTTP client for the direct DeepSeek Chat Completions API."""
from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

import requests

from backend.deepseek_model_routing import (
    DEEPSEEK_FALLBACK_REASONING_EFFORT,
    DEEPSEEK_MAX_REASONING_EFFORT,
)
from backend.logging_config import get_logger

logger = get_logger("backend.deepseek_client")
# Logger dedicado para payloads completos (prompts + respuestas). Sus mensajes solo
# muestran un resumen en consola; el contenido íntegro va al archivo (CompleteJSONFormatter).
payload_logger = get_logger("backend.deepseek_client.payload")


def _payload_logging_enabled() -> bool:
    raw = os.environ.get("EXPLAINER_LOG_PAYLOADS")
    if raw is None:
        # Activo por defecto fuera de producción.
        return os.environ.get("ENVIRONMENT") != "production"
    return raw.strip().lower() in {"1", "true", "yes", "on"}

DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_JSON_RESPONSE_SYSTEM_SUFFIX = """

<json_response_contract>
Responde exclusivamente con un objeto JSON válido que cumpla el response_format solicitado.
No incluyas Markdown, comentarios ni texto fuera del JSON.
</json_response_contract>"""


class DeepSeekUsage:
    """Wrapper de usage con atributos compatibles con Gemini para _update_usage."""

    def __init__(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        thoughts_tokens: int = 0,
        total_tokens: int | None = None,
        server_tool_use: dict[str, Any] | None = None,
        cache_hit_tokens: int = 0,
        cache_miss_tokens: int = 0,
    ):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = completion_tokens
        self.thoughts_token_count = thoughts_tokens
        self.tool_use_prompt_token_count = 0
        self.total_token_count = (
            total_tokens
            if total_tokens is not None
            else prompt_tokens + completion_tokens + thoughts_tokens
        )
        self.cost_usd = None
        self.server_tool_use = dict(server_tool_use or {})
        # Context-cache accounting (DeepSeek disk cache): hits = prefijo reutilizado.
        self.prompt_cache_hit_tokens = cache_hit_tokens
        self.prompt_cache_miss_tokens = cache_miss_tokens


class DeepSeekError(Exception):
    pass


class DeepSeekRateLimitError(DeepSeekError):
    pass


class DeepSeekServiceError(DeepSeekError):
    pass


@dataclass(frozen=True, slots=True)
class DeepSeekAssistantMessage:
    content: str
    tool_calls: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class DeepSeekChatResult:
    content: str | dict[str, Any]
    usage: DeepSeekUsage
    assistant_message: DeepSeekAssistantMessage


def _with_json_response_instruction(system_prompt: str) -> str:
    if re.search(r"\bjson\b(?!-)", system_prompt, flags=re.IGNORECASE):
        return system_prompt
    return f"{system_prompt.rstrip()}{_JSON_RESPONSE_SYSTEM_SUFFIX}"


def _json_retry_user_message(
    exc: DeepSeekError,
    json_retry_instruction: str | None,
) -> str:
    details = [
        "Tu respuesta anterior no ha pasado la validación local.",
        f"Error detectado: {exc}",
        "",
        "Tienes que responder otra vez usando el mismo contexto anterior, pero corrigiendo SOLO el formato.",
        "Devuelve exclusivamente un objeto JSON raíz válido. No devuelvas arrays como raíz, Markdown, comentarios ni texto fuera del JSON.",
    ]
    if json_retry_instruction and json_retry_instruction.strip():
        details.extend(
            [
                "",
                "Contrato del objeto JSON esperado:",
                json_retry_instruction.strip(),
            ]
        )
    return "\n".join(details)


def _is_retryable_requests_exception(exc: requests.exceptions.RequestException) -> bool:
    non_retryable = (
        requests.exceptions.InvalidURL,
        requests.exceptions.InvalidSchema,
        requests.exceptions.MissingSchema,
        requests.exceptions.InvalidHeader,
        requests.exceptions.URLRequired,
        requests.exceptions.TooManyRedirects,
        requests.exceptions.SSLError,
    )
    return not isinstance(exc, non_retryable)


def _retry_after_seconds(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed) or parsed < 0:
        return fallback
    return int(min(max(parsed, 1), 120))


def _extract_message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "".join(chunks)
    return ""


def _extract_api_error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        normalized_message = message.strip() if isinstance(message, str) else ""
        if normalized_message and code is not None:
            return f"{normalized_message} (code={code})"
        if normalized_message:
            return normalized_message
        if code is not None:
            return f"code={code}"
    return None


def _response_preview(raw_text: str, *, limit: int = 300) -> str:
    preview = raw_text.strip()
    return preview[:limit] if preview else "<empty>"


def _build_invalid_response_error(
    *,
    reason: str,
    payload: Any,
    response_text: str,
) -> DeepSeekServiceError:
    details = [reason]
    error_message = _extract_api_error_message(payload)
    if error_message:
        details.append(f"error={error_message}")
    if isinstance(payload, dict):
        details.append(f"keys={list(payload.keys())}")
    else:
        details.append(f"payload_type={type(payload).__name__}")
    details.append(f"body={_response_preview(response_text)}")
    return DeepSeekServiceError("Respuesta DeepSeek inválida: " + " | ".join(details))


def _parse_number(raw: Any) -> int:
    if isinstance(raw, bool):
        return 0
    candidate: float | None
    if isinstance(raw, int):
        candidate = float(raw)
    elif isinstance(raw, float):
        candidate = raw
    elif isinstance(raw, str):
        normalized = raw.strip()
        if not normalized or not _NUMBER_RE.fullmatch(normalized):
            return 0
        try:
            candidate = float(normalized)
        except ValueError:
            return 0
    else:
        return 0
    if not math.isfinite(candidate):
        return 0
    return max(int(max(candidate, 0.0)), 0)


def _parse_usage(usage_raw: Any) -> DeepSeekUsage:
    if not isinstance(usage_raw, dict):
        usage_raw = {}
    completion_details = usage_raw.get("completion_tokens_details")
    reasoning_tokens = 0
    if isinstance(completion_details, dict):
        reasoning_tokens = _parse_number(completion_details.get("reasoning_tokens", 0))
    return DeepSeekUsage(
        prompt_tokens=_parse_number(usage_raw.get("prompt_tokens", 0)),
        completion_tokens=_parse_number(usage_raw.get("completion_tokens", 0)),
        thoughts_tokens=reasoning_tokens,
        total_tokens=_parse_number(usage_raw.get("total_tokens", 0)) or None,
        cache_hit_tokens=_parse_number(usage_raw.get("prompt_cache_hit_tokens", 0)),
        cache_miss_tokens=_parse_number(usage_raw.get("prompt_cache_miss_tokens", 0)),
    )


def _merge_server_tool_use(
    current: dict[str, Any],
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(current)
    for key, value in (update or {}).items():
        if isinstance(value, (int, float)) and isinstance(merged.get(key), (int, float)):
            merged[key] = merged[key] + value
        elif key not in merged:
            merged[key] = value
    return merged


def _add_usage(left: DeepSeekUsage, right: DeepSeekUsage) -> DeepSeekUsage:
    return DeepSeekUsage(
        prompt_tokens=left.prompt_token_count + right.prompt_token_count,
        completion_tokens=left.candidates_token_count + right.candidates_token_count,
        thoughts_tokens=left.thoughts_token_count + right.thoughts_token_count,
        total_tokens=left.total_token_count + right.total_token_count,
        server_tool_use=_merge_server_tool_use(left.server_tool_use, right.server_tool_use),
        cache_hit_tokens=left.prompt_cache_hit_tokens + right.prompt_cache_hit_tokens,
        cache_miss_tokens=left.prompt_cache_miss_tokens + right.prompt_cache_miss_tokens,
    )


def _parse_json_object_content(content: str) -> dict[str, Any]:
    if not content or not content.strip():
        raise DeepSeekError("DeepSeek devolvió contenido JSON vacío.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekError(
            "DeepSeek devolvió JSON inválido: "
            f"{exc.msg} (línea {exc.lineno}, columna {exc.colno})."
        ) from exc
    if not isinstance(parsed, dict):
        raise DeepSeekError("DeepSeek devolvió JSON válido, pero no un objeto JSON.")
    return parsed


def _extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        call_id = raw_call.get("id")
        normalized.append(
            {
                "id": str(call_id) if call_id else f"call_{index + 1}",
                "type": "function",
                "function": {
                    "name": name.strip(),
                    "arguments": function.get("arguments", "{}"),
                },
            }
        )
    return normalized


def _parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        normalized = raw_arguments.strip()
        if not normalized:
            return {}
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise DeepSeekError(
                "DeepSeek solicitó una tool call con argumentos JSON inválidos: "
                f"{exc.msg} (línea {exc.lineno}, columna {exc.colno})."
            ) from exc
        if not isinstance(parsed, dict):
            raise DeepSeekError("DeepSeek solicitó una tool call con argumentos no objeto.")
        return parsed
    return {}


def _reasoning_effort_rejected(status_code: int, response_text: str) -> bool:
    if status_code not in (400, 422):
        return False
    normalized = response_text.lower()
    return "reasoning_effort" in normalized and DEEPSEEK_MAX_REASONING_EFFORT in normalized


def _post_chat_completion(
    *,
    messages: list[dict[str, Any]],
    model: str,
    api_key: str,
    response_format: Literal["text", "json_object"],
    tools: list[dict[str, Any]] | None,
    reasoning_effort: str,
    temperature: float | None,
    max_retries: int,
) -> tuple[dict[str, Any], DeepSeekUsage, str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    effective_reasoning_effort = reasoning_effort
    last_exc: Exception = DeepSeekError("No se realizó ningún intento DeepSeek.")
    max_attempts = max(1, max_retries)
    reasoning_fallback_used = False

    for attempt in range(1, max_attempts + 2):
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "thinking": {"type": "enabled"},
            "reasoning_effort": effective_reasoning_effort,
        }
        if response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature

        try:
            response = requests.post(
                DEEPSEEK_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
                timeout=180,
            )

            if _reasoning_effort_rejected(response.status_code, response.text):
                if (
                    effective_reasoning_effort == DEEPSEEK_MAX_REASONING_EFFORT
                    and not reasoning_fallback_used
                ):
                    effective_reasoning_effort = DEEPSEEK_FALLBACK_REASONING_EFFORT
                    reasoning_fallback_used = True
                    logger.warning(
                        "[DeepSeek] reasoning_effort=max rechazado; reintentando con high",
                        extra={"model": model, "attempt": attempt},
                    )
                    continue

            if response.status_code == 429:
                wait = _retry_after_seconds(
                    response.headers.get("retry-after"),
                    min(2 ** attempt, 60),
                )
                logger.warning(
                    "[DeepSeek] Rate limit 429, reintento %s/%s en %ss",
                    attempt,
                    max_attempts,
                    wait,
                    extra={"model": model},
                )
                last_exc = DeepSeekRateLimitError(f"Rate limit DeepSeek en intento {attempt}")
                if attempt < max_attempts:
                    time.sleep(wait)
                    continue
                raise last_exc

            if response.status_code in (500, 502, 503, 504):
                wait = min(2 ** attempt, 60)
                logger.warning(
                    "[DeepSeek] Error servidor %s, reintento %s/%s en %ss",
                    response.status_code,
                    attempt,
                    max_attempts,
                    wait,
                    extra={"model": model},
                )
                last_exc = DeepSeekServiceError(
                    f"Error DeepSeek {response.status_code} en intento {attempt}"
                )
                if attempt < max_attempts:
                    time.sleep(wait)
                    continue
                raise last_exc

            if response.status_code != 200:
                raise DeepSeekError(
                    f"DeepSeek devolvió HTTP {response.status_code}: {response.text[:500]}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                invalid = DeepSeekServiceError(
                    f"DeepSeek devolvió JSON HTTP inválido: {response.text[:300]}"
                )
                last_exc = invalid
                if attempt < max_attempts:
                    time.sleep(min(2 ** attempt, 60))
                    continue
                raise invalid from exc

            choices = data.get("choices") if isinstance(data, dict) else None
            if not isinstance(choices, list) or not choices:
                invalid = _build_invalid_response_error(
                    reason="choices vacío o ausente",
                    payload=data,
                    response_text=response.text,
                )
                last_exc = invalid
                if attempt < max_attempts:
                    time.sleep(min(2 ** attempt, 60))
                    continue
                raise invalid
            choice = choices[0]
            if not isinstance(choice, dict):
                invalid = _build_invalid_response_error(
                    reason="choices[0] no es un objeto",
                    payload=data,
                    response_text=response.text,
                )
                last_exc = invalid
                if attempt < max_attempts:
                    time.sleep(min(2 ** attempt, 60))
                    continue
                raise invalid
            message = choice.get("message")
            if not isinstance(message, dict):
                invalid = _build_invalid_response_error(
                    reason="choices[0].message no es un objeto",
                    payload=data,
                    response_text=response.text,
                )
                last_exc = invalid
                if attempt < max_attempts:
                    time.sleep(min(2 ** attempt, 60))
                    continue
                raise invalid

            return (
                message,
                _parse_usage(data.get("usage") if isinstance(data, dict) else {}),
                str(choice.get("finish_reason") or "unknown"),
                effective_reasoning_effort,
            )

        except (DeepSeekRateLimitError, DeepSeekServiceError):
            raise
        except requests.exceptions.Timeout:
            wait = min(2 ** attempt, 60)
            last_exc = DeepSeekError(f"Timeout DeepSeek en intento {attempt}")
            logger.warning(
                "[DeepSeek] Timeout en intento %s/%s",
                attempt,
                max_attempts,
                extra={"model": model},
            )
            if attempt < max_attempts:
                time.sleep(wait)
                continue
        except requests.exceptions.RequestException as exc:
            if _is_retryable_requests_exception(exc):
                wait = min(2 ** attempt, 60)
                last_exc = DeepSeekError(f"Error de red DeepSeek en intento {attempt}: {exc}")
                logger.warning(
                    "[DeepSeek] Error de transporte reintentable en intento %s/%s: %s",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    extra={"model": model},
                )
                if attempt < max_attempts:
                    time.sleep(wait)
                    continue
                raise last_exc from exc
            raise DeepSeekError(f"Error de red DeepSeek: {exc}") from exc

    raise last_exc


def call_deepseek_chat_full(
    *,
    messages: list[dict[str, Any]],
    model: str,
    system_prompt: str,
    api_key: str,
    response_format: Literal["text", "json_object"] = "text",
    tools: list[dict[str, Any]] | None = None,
    tool_handlers: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
    reasoning_effort: str = DEEPSEEK_MAX_REASONING_EFFORT,
    max_retries: int = 5,
    max_tool_rounds: int = 3,
    temperature: float | None = None,
    json_retry_instruction: str | None = None,
) -> DeepSeekChatResult:
    """Call DeepSeek /chat/completions with retries, JSON validation and tool execution."""
    key = (api_key or "").strip()
    if not key:
        raise DeepSeekError("API key de DeepSeek no proporcionada.")

    uses_json_mode = response_format == "json_object"
    conversation_messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                _with_json_response_instruction(system_prompt)
                if uses_json_mode
                else system_prompt
            ),
        },
        *messages,
    ]
    aggregate_usage = DeepSeekUsage(0, 0)
    json_retry_count = 0
    tool_round_count = 0
    round_index = 0
    log_payloads = _payload_logging_enabled()
    effective_reasoning_effort = reasoning_effort
    force_final_without_tools = False

    while True:
        round_index += 1
        if log_payloads:
            # Request íntegro de esta ronda (system + toda la conversación) → solo al archivo.
            payload_logger.debug(
                "[DeepSeek] REQUEST modelo=%s ronda=%s mensajes=%s",
                model,
                round_index,
                len(conversation_messages),
                extra={
                    "deepseek_model": model,
                    "round": round_index,
                    "response_format": response_format,
                    "reasoning_effort": effective_reasoning_effort,
                    "tools_enabled": bool(tools) and not force_final_without_tools,
                    "request_messages": conversation_messages,
                },
            )
        message, usage, finish_reason, effective_reasoning_effort = _post_chat_completion(
            messages=conversation_messages,
            model=model,
            api_key=key,
            response_format=response_format,
            tools=None if force_final_without_tools else tools,
            reasoning_effort=effective_reasoning_effort,
            temperature=temperature,
            max_retries=max_retries,
        )
        aggregate_usage = _add_usage(aggregate_usage, usage)
        content_text = _extract_message_content(message)
        tool_calls = _extract_tool_calls(message)
        if log_payloads:
            # Respuesta cruda de esta ronda + contabilidad de caché → solo al archivo.
            payload_logger.debug(
                "[DeepSeek] RESPONSE modelo=%s ronda=%s finish=%s cache_hit=%s cache_miss=%s",
                model,
                round_index,
                finish_reason,
                usage.prompt_cache_hit_tokens,
                usage.prompt_cache_miss_tokens,
                extra={
                    "deepseek_model": model,
                    "round": round_index,
                    "finish_reason": finish_reason,
                    "prompt_tokens": usage.prompt_token_count,
                    "completion_tokens": usage.candidates_token_count,
                    "thoughts_tokens": usage.thoughts_token_count,
                    "prompt_cache_hit_tokens": usage.prompt_cache_hit_tokens,
                    "prompt_cache_miss_tokens": usage.prompt_cache_miss_tokens,
                    "response_content": content_text,
                    "response_tool_calls": tool_calls,
                },
            )

        if tool_calls:
            if force_final_without_tools:
                raise DeepSeekError(
                    "DeepSeek solicitó tool calls después de deshabilitar herramientas."
                )
            if not tool_handlers:
                raise DeepSeekError(
                    "DeepSeek solicitó tool calls, pero no hay handlers configurados."
                )
            if tool_round_count >= max_tool_rounds:
                logger.warning(
                    "[DeepSeek] Máximo de tool rounds alcanzado; forzando respuesta final sin herramientas",
                    extra={
                        "model": model,
                        "max_tool_rounds": max_tool_rounds,
                        "requested_tool_calls": len(tool_calls),
                    },
                )
                force_final_without_tools = True
                conversation_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Has alcanzado el límite de búsquedas externas para esta llamada. "
                            "No solicites más herramientas. Responde ahora con el objeto JSON final "
                            "usando únicamente el contexto original y los resultados de búsqueda ya recibidos. "
                            "Si algún dato no está suficientemente verificado, omítelo o indícalo en "
                            "`nota_de_integridad`."
                        ),
                    }
                )
                time.sleep(1)
                continue
            tool_round_count += 1
            conversation_messages.append(
                {
                    "role": "assistant",
                    "content": content_text or "",
                    "tool_calls": tool_calls,
                }
            )
            server_tool_use = dict(aggregate_usage.server_tool_use)
            for tool_call in tool_calls:
                function = tool_call["function"]
                tool_name = function["name"]
                handler = tool_handlers.get(tool_name)
                if handler is None:
                    tool_result: Any = {"error": f"Tool no soportada: {tool_name}"}
                else:
                    try:
                        tool_result = handler(_parse_tool_arguments(function.get("arguments")))
                    except Exception as exc:  # noqa: BLE001 - surfaced to model as tool output
                        logger.warning(
                            "[DeepSeek] Tool call falló: %s",
                            tool_name,
                            extra={"error_type": type(exc).__name__, "error": str(exc)[:300]},
                        )
                        tool_result = {
                            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                        }
                server_tool_use[f"{tool_name}_requests"] = (
                    int(server_tool_use.get(f"{tool_name}_requests", 0) or 0) + 1
                )
                try:
                    tool_content = json.dumps(tool_result, ensure_ascii=False)
                except (TypeError, ValueError):
                    tool_content = str(tool_result)
                conversation_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_content,
                    }
                )
            aggregate_usage.server_tool_use = server_tool_use
            continue

        parsed_or_text: str | dict[str, Any] = content_text
        if uses_json_mode:
            try:
                parsed_or_text = _parse_json_object_content(content_text)
            except DeepSeekError as exc:
                json_retry_count += 1
                logger.warning(
                    "[DeepSeek] JSON estructurado inválido, reintento conversacional %s/%s",
                    json_retry_count,
                    max_retries,
                    extra={
                        "model": model,
                        "finish_reason": finish_reason,
                        "response_preview": content_text[:300],
                    },
                )
                if json_retry_count >= max_retries:
                    raise
                conversation_messages.extend(
                    [
                        {"role": "assistant", "content": content_text},
                        {
                            "role": "user",
                            "content": _json_retry_user_message(
                                exc,
                                json_retry_instruction,
                            ),
                        },
                    ]
                )
                time.sleep(2)
                continue

        logger.debug(
            "[DeepSeek] Respuesta OK",
            extra={
                "model": model,
                "finish_reason": finish_reason,
                "prompt_tokens": aggregate_usage.prompt_token_count,
                "completion_tokens": aggregate_usage.candidates_token_count,
                "thoughts_tokens": aggregate_usage.thoughts_token_count,
                "prompt_cache_hit_tokens": aggregate_usage.prompt_cache_hit_tokens,
                "prompt_cache_miss_tokens": aggregate_usage.prompt_cache_miss_tokens,
                "tool_rounds": tool_round_count,
            },
        )
        return DeepSeekChatResult(
            content=parsed_or_text,
            usage=aggregate_usage,
            assistant_message=DeepSeekAssistantMessage(
                content=content_text,
                tool_calls=tool_calls or None,
            ),
        )


def call_deepseek_chat(
    messages: list[dict[str, Any]],
    model: str,
    system_prompt: str,
    api_key: str,
    response_format: Literal["text", "json_object"] = "text",
    tools: list[dict[str, Any]] | None = None,
    tool_handlers: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
    reasoning_effort: str = DEEPSEEK_MAX_REASONING_EFFORT,
    max_retries: int = 5,
    max_tool_rounds: int = 3,
    temperature: float | None = None,
    json_retry_instruction: str | None = None,
) -> tuple[str | dict[str, Any], DeepSeekUsage]:
    """Return `(content, usage)` for callers that do not need the full response."""
    result = call_deepseek_chat_full(
        messages=messages,
        model=model,
        system_prompt=system_prompt,
        api_key=api_key,
        response_format=response_format,
        tools=tools,
        tool_handlers=tool_handlers,
        reasoning_effort=reasoning_effort,
        max_retries=max_retries,
        max_tool_rounds=max_tool_rounds,
        temperature=temperature,
        json_retry_instruction=json_retry_instruction,
    )
    return result.content, result.usage

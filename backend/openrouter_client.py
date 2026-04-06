"""Cliente HTTP para OpenRouter API."""
from __future__ import annotations

import time
import json
from typing import Any, Literal

import requests

from backend.logging_config import get_logger

logger = get_logger("backend.openrouter_client")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_RESPONSE_HEALING_PLUGIN = {"id": "response-healing"}


class OpenRouterUsage:
    """Wrapper de usage con atributos compatibles con Gemini para _update_usage."""

    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = completion_tokens
        self.thoughts_token_count = 0
        self.tool_use_prompt_token_count = 0
        self.total_token_count = prompt_tokens + completion_tokens


class OpenRouterError(Exception):
    pass


class OpenRouterRateLimitError(OpenRouterError):
    pass


class OpenRouterServiceError(OpenRouterError):
    pass


def _merge_plugins(
    plugins: list[dict[str, Any]] | None,
    *,
    enable_response_healing: bool,
) -> list[dict[str, Any]] | None:
    """Merge request plugins and optionally append response-healing once."""
    merged = [dict(plugin) for plugin in (plugins or [])]
    if enable_response_healing and not any(
        plugin.get("id") == OPENROUTER_RESPONSE_HEALING_PLUGIN["id"]
        for plugin in merged
    ):
        merged.append(dict(OPENROUTER_RESPONSE_HEALING_PLUGIN))
    return merged or None


def _extract_message_content(message: dict[str, Any]) -> str:
    """Extract assistant message text from the OpenRouter response payload."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
        return "".join(chunks)
    return ""


def _parse_json_object_content(content: str) -> dict[str, Any]:
    """Parse JSON mode output and require a top-level object."""
    if not content or not content.strip():
        raise OpenRouterError("OpenRouter devolvió contenido JSON vacío.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(
            "OpenRouter devolvió JSON inválido en modo json_object: "
            f"{exc.msg} (línea {exc.lineno}, columna {exc.colno})."
        ) from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError(
            "OpenRouter devolvió JSON válido, pero no un objeto JSON en modo json_object."
        )
    return parsed


def call_openrouter_chat(
    messages: list[dict],
    model: str,
    system_prompt: str,
    api_key: str,
    response_format: Literal["text", "json_object"] = "text",
    plugins: list[dict] | None = None,
    enable_response_healing: bool = False,
    reasoning: dict | None = None,
    max_retries: int = 5,
) -> tuple[str | dict[str, Any], OpenRouterUsage]:
    """
    Llama a OpenRouter /chat/completions.
    Puede pedir texto libre o `json_object`, según el contrato esperado.
    Retorna (content, OpenRouterUsage), donde `content` es `str` o `dict`.
    """
    if not api_key:
        raise OpenRouterError("OpenRouter API key no proporcionada.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
        ],
    }

    if response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}

    merged_plugins = _merge_plugins(
        plugins,
        enable_response_healing=enable_response_healing and response_format == "json_object",
    )
    if merged_plugins:
        payload["plugins"] = merged_plugins

    if reasoning:
        payload["reasoning"] = reasoning

    last_exc: Exception = OpenRouterError("No se realizó ningún intento.")
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                OPENROUTER_BASE_URL,
                headers=headers,
                json=payload,
                timeout=300,
            )

            if resp.status_code == 429:
                wait = min(2 ** attempt, 60)
                logger.warning(
                    f"[OpenRouter] Rate limit (429), reintento {attempt}/{max_retries} en {wait}s"
                )
                time.sleep(wait)
                last_exc = OpenRouterRateLimitError(f"Rate limit en intento {attempt}")
                continue

            if resp.status_code in (500, 502, 503, 504):
                wait = min(2 ** attempt, 60)
                logger.warning(
                    f"[OpenRouter] Error servidor {resp.status_code}, reintento {attempt}/{max_retries} en {wait}s"
                )
                time.sleep(wait)
                last_exc = OpenRouterServiceError(f"Error {resp.status_code} en intento {attempt}")
                continue

            if resp.status_code != 200:
                raise OpenRouterError(
                    f"OpenRouter devolvió HTTP {resp.status_code}: {resp.text[:300]}"
                )

            data = resp.json()

            # Extraer content
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = _extract_message_content(message)
            finish_reason = choice.get("finish_reason", "unknown")

            # Extraer usage
            usage_raw = data.get("usage", {})
            usage = OpenRouterUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
            )

            if not content:
                logger.warning(
                    "[OpenRouter] Contenido vacío recibido",
                    extra={
                        "model": model,
                        "finish_reason": finish_reason,
                        "message_keys": list(message.keys()),
                        "full_choice": str(choice)[:500],
                        "full_data_keys": list(data.keys()),
                    },
                )
            else:
                logger.debug(
                    "[OpenRouter] Respuesta OK",
                    extra={
                        "model": model,
                        "finish_reason": finish_reason,
                        "prompt_tokens": usage.prompt_token_count,
                        "completion_tokens": usage.candidates_token_count,
                    },
                )
            if response_format == "json_object":
                try:
                    parsed_content = _parse_json_object_content(content)
                except OpenRouterError as exc:
                    wait = min(2 ** attempt, 60)
                    logger.warning(
                        "[OpenRouter] JSON mode inválido, reintento %s/%s en %ss",
                        attempt,
                        max_retries,
                        wait,
                        extra={
                            "model": model,
                            "finish_reason": finish_reason,
                            "response_preview": content[:300],
                        },
                    )
                    last_exc = exc
                    if attempt < max_retries:
                        time.sleep(wait)
                        continue
                    raise
                return parsed_content, usage

            return content, usage

        except (OpenRouterRateLimitError, OpenRouterServiceError):
            # ya manejado con sleep arriba
            pass
        except requests.exceptions.Timeout:
            wait = min(2 ** attempt, 60)
            logger.warning(
                f"[OpenRouter] Timeout en intento {attempt}/{max_retries}, reintentando en {wait}s"
            )
            time.sleep(wait)
            last_exc = OpenRouterError(f"Timeout en intento {attempt}")
        except requests.exceptions.RequestException as e:
            raise OpenRouterError(f"Error de red: {e}") from e

    raise last_exc

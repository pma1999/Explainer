"""Cliente HTTP para OpenRouter API."""
from __future__ import annotations

import time
import json
from typing import Any

import requests

from backend.logging_config import get_logger

logger = get_logger("backend.openrouter_client")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


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


def call_openrouter_chat(
    messages: list[dict],
    model: str,
    response_schema: dict,
    system_prompt: str,
    api_key: str,
    plugins: list[dict] | None = None,
    max_retries: int = 5,
) -> tuple[str, OpenRouterUsage]:
    """
    Llama a OpenRouter /chat/completions con structured output (json_schema).
    Retorna (content_string, OpenRouterUsage).
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
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_output",
                "strict": True,
                "schema": response_schema,
            },
        },
    }

    if plugins:
        payload["plugins"] = plugins

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
            content = data["choices"][0]["message"]["content"]

            # Extraer usage
            usage_raw = data.get("usage", {})
            usage = OpenRouterUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
            )

            logger.debug(
                "[OpenRouter] Respuesta OK",
                extra={
                    "model": model,
                    "prompt_tokens": usage.prompt_token_count,
                    "completion_tokens": usage.candidates_token_count,
                },
            )
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

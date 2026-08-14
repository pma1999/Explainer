"""Agente Explainer — implementación Codex (app-server) con JSON mode (T05).

Espejo posicional de `explainer_deepseek.py` sobre `call_codex_chat` (T03):
mismas firmas con `user_id` ocupando la posición de `api_key`, corrutinas
`async` que se esperan directo (nunca vía `asyncio.to_thread`). Reutiliza los
builders de prompts y validadores de payload existentes; el validador de
completitud también se ejecuta vía Codex, sin clave de DeepSeek.

El reintento conversacional replica `_DeepSeekExplainerConversation`: el system
prompt y el PRIMER user message (con la fuente) se mantienen byte-idénticos en
todas las rondas; cada regeneración solo AÑADE el turno `assistant` anterior
(re-serializado del payload parseado: `call_codex_chat` devuelve el JSON ya
parseado, no el texto crudo) y un turno `user` corto con el feedback.

Seguridad: solo se loguean `user_id[:8]`, modelo, longitudes y previews
truncados; nunca prompts fuente completos ni credenciales.
"""
from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

from backend.agents.completeness_validator import (
    MAX_EXPLAINER_VALIDATION_RETRIES,
    ExplainerValidationContext,
    ExplainerValidationError,
    ExplainerValidationReport,
    _OPENROUTER_VALIDATOR_JSON_RETRY_INSTRUCTION,
    _VALIDATOR_SYSTEM_PROMPT,
    _accepted_report,
    _build_validator_user_message,
    _parse_validation_report,
    format_explainer_retry_context,
)
from backend.agents.explainer_deepseek import (
    _build_inline_source_message,
    _is_retryable_payload_validation_error,
    _payload_correction_message,
)
from backend.agents.explainer_openrouter import (
    OPENROUTER_EXPLAINER_TEMPERATURE,
    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
    _count_desarrollo_subsections,
    _count_payload_chars,
    _validate_full_explainer_payload,
    _validate_subpart_explainer_payload,
    build_openrouter_explainer_system_prompt,
    build_openrouter_subpart_explainer_system_prompt,
)
from backend.codex_client import CodexError, CodexUsage, call_codex_chat
from backend.codex_model_routing import CODEX_MODEL, CODEX_MODEL_AUXILIARY
from backend.logging_config import get_logger
from backend.pdf_ocr_cache import PdfOcrCacheEntry

logger = get_logger("backend.agents.explainer_codex")

# Prompt del validador de completitud para Codex: el contrato base del revisor
# más el bloque de JSON mode (mismo patrón que `_DEEPSEEK_VALIDATOR_SYSTEM_PROMPT`,
# sin copiar constantes DEEPSEEK_*).
_CODEX_VALIDATOR_SYSTEM_PROMPT = f"""{_VALIDATOR_SYSTEM_PROMPT}

<codex_json_mode_contract>
Para Codex JSON mode, cumple explícitamente este contrato adicional:
{_OPENROUTER_VALIDATOR_JSON_RETRY_INSTRUCTION}
</codex_json_mode_contract>"""


async def _call_codex_with_validation_retries(
    *,
    call_operation: Callable[[], Awaitable[tuple[dict[str, Any], CodexUsage]]],
    validate_payload: Callable[[Any], dict[str, Any]],
    operation_label: str,
) -> tuple[dict[str, Any], CodexUsage]:
    """Ejecuta una llamada Codex validando el payload con reintentos.

    Espejo async de `_call_deepseek_with_validation_retries`
    (explainer_deepseek.py): misma política de reintentos y de errores.
    """
    total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        raw, usage = await call_operation()
        try:
            return validate_payload(raw), usage
        except Exception as exc:
            if attempt >= total_attempts or not _is_retryable_payload_validation_error(exc):
                raise CodexError(str(exc)) from exc
            logger.warning(
                "%s devolvió JSON estructurado inválido (%s). Reintentando %s/%s",
                operation_label,
                str(exc),
                attempt,
                OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
                extra={
                    "operation_label": operation_label,
                    "validation_attempt": attempt,
                    "validation_max_retries": OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
                    "error_message": str(exc),
                },
            )
    raise CodexError(
        f"{operation_label} agotó reintentos por payload inválido sin devolver JSON válido."
    )


async def _call_codex_json_with_pdf_fallback(
    *,
    source_path: str,
    identificacion: str,
    mime_type: str,
    model: str,
    system_prompt: str,
    user_id: str,
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage]:
    """Una llamada explainer Codex: mensaje inline con la fuente + JSON mode."""
    user_message = _build_inline_source_message(
        source_path=source_path,
        identificacion=identificacion,
        mime_type=mime_type,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
    )
    content, usage = await call_codex_chat(
        user_id=user_id,
        messages=[{"role": "user", "content": user_message}],
        system_prompt=system_prompt,
        model=model,
        response_format="json_object",
        temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
        effort=effort,
    )
    if not isinstance(content, dict):
        raise CodexError("Explainer Codex no devolvió un objeto JSON.")
    return content, usage


async def run_explainer_codex(
    source_path: str,
    identificacion: str,
    model: str = CODEX_MODEL,
    mime_type: str = "application/pdf",
    user_id: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    target_language: str = "es-ES",
    *,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage]:
    """Explainer completo vía Codex. Retorna (structured_result, usage)."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer (codex)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
            "user_id": user_id[:8],
        },
    )

    result, usage = await _call_codex_with_validation_retries(
        call_operation=lambda: _call_codex_json_with_pdf_fallback(
            source_path=source_path,
            identificacion=identificacion,
            mime_type=mime_type,
            model=model,
            system_prompt=build_openrouter_explainer_system_prompt(target_language),
            user_id=user_id,
            pdf_cache_entry=pdf_cache_entry,
            page_numbers=page_numbers,
            effort=effort,
        ),
        validate_payload=_validate_full_explainer_payload,
        operation_label="Explainer Codex",
    )
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)
    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Explainer (codex) completado: %s secciones, %s subsecciones, %s chars en %sms",
        len(desarrollo),
        total_subsections,
        total_chars,
        total_ms,
        extra={
            "num_sections": len(desarrollo),
            "num_subsections": total_subsections,
            "content_length": total_chars,
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
            "user_id": user_id[:8],
        },
    )
    return result, usage


async def run_subpart_explainer_codex(
    source_path: str,
    identificacion: str,
    model: str = CODEX_MODEL,
    mime_type: str = "application/pdf",
    user_id: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    target_language: str = "es-ES",
    *,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage]:
    """Explainer de subparte vía Codex — retorna solo `desarrollo` estructurado."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer subparte (codex)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
            "user_id": user_id[:8],
        },
    )

    result, usage = await _call_codex_with_validation_retries(
        call_operation=lambda: _call_codex_json_with_pdf_fallback(
            source_path=source_path,
            identificacion=identificacion,
            mime_type=mime_type,
            model=model,
            system_prompt=build_openrouter_subpart_explainer_system_prompt(target_language),
            user_id=user_id,
            pdf_cache_entry=pdf_cache_entry,
            page_numbers=page_numbers,
            effort=effort,
        ),
        validate_payload=_validate_subpart_explainer_payload,
        operation_label="Explainer subparte Codex",
    )
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)
    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Subpart explainer (codex) completado: %s secciones, %s subsecciones, %s chars en %sms",
        len(desarrollo),
        total_subsections,
        total_chars,
        total_ms,
        extra={
            "num_sections": len(desarrollo),
            "num_subsections": total_subsections,
            "content_length": total_chars,
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
            "user_id": user_id[:8],
        },
    )
    return result, usage


class _CodexExplainerConversation:
    """Conversación Codex con estado para reintentos cache-friendly.

    Espejo async de `_DeepSeekExplainerConversation` sobre `call_codex_chat`:
    el system prompt y el PRIMER user message (que lleva la fuente, caro) se
    mantienen byte-idénticos en todas las rondas; cada regeneración solo AÑADE
    el turno `assistant` anterior y un turno `user` corto con el feedback.

    A diferencia de DeepSeek (que reenvía el texto crudo del modelo), aquí el
    turno `assistant` se re-serializa del payload parseado con `json.dumps`,
    porque `call_codex_chat` devuelve `(data, usage)` sin exponer el texto
    crudo del turno.
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        user_message: str,
        model: str,
        user_id: str,
        validate_payload: Callable[[Any], dict[str, Any]],
        validation_context: ExplainerValidationContext | None,
        operation_label: str,
        effort: str | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._model = model
        self._user_id = user_id
        self._effort = effort
        self._validate_payload = validate_payload
        self._validation_context = validation_context
        self._operation_label = operation_label
        # Solo turnos user/assistant; el system se pasa aparte y NO se muta nunca.
        self._messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    async def _generate_validated(self) -> tuple[dict[str, Any], CodexUsage]:
        total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
        for attempt in range(1, total_attempts + 1):
            data, usage = await call_codex_chat(
                user_id=self._user_id,
                messages=self._messages,
                system_prompt=self._system_prompt,
                model=self._model,
                response_format="json_object",
                temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
                effort=self._effort,
            )
            # Reproducir el output del modelo en la siguiente ronda para
            # mantener la continuidad del prefijo (system + user0).
            self._messages.append(
                {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)}
            )
            if not isinstance(data, dict):
                raise CodexError("Explainer Codex no devolvió un objeto JSON.")
            try:
                return self._validate_payload(data), usage
            except Exception as exc:
                if attempt >= total_attempts or not _is_retryable_payload_validation_error(exc):
                    raise CodexError(str(exc)) from exc
                logger.warning(
                    "%s devolvió JSON estructurado inválido (%s). Reintento conversacional %s/%s",
                    self._operation_label,
                    str(exc),
                    attempt,
                    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
                    extra={
                        "operation_label": self._operation_label,
                        "validation_attempt": attempt,
                        "validation_max_retries": OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
                        "error_message": str(exc),
                        "user_id": self._user_id[:8],
                    },
                )
                # Turno correctivo appendido: no se reenvía la fuente, solo el problema.
                self._messages.append(
                    {"role": "user", "content": _payload_correction_message(exc)}
                )
        raise CodexError(
            f"{self._operation_label} agotó reintentos por payload inválido sin devolver JSON válido."
        )

    async def run_initial(self) -> tuple[dict[str, Any], CodexUsage]:
        return await self._generate_validated()

    async def run_retry(
        self, validation_report: ExplainerValidationReport
    ) -> tuple[dict[str, Any], CodexUsage]:
        logger.info(
            "Reintentando explainer (codex) por validación — append conversacional",
            extra={
                "operation_label": self._operation_label,
                "model": self._model,
                "is_complete": validation_report.is_complete,
                "scope_status": validation_report.scope_status,
                "user_id": self._user_id[:8],
            },
        )
        feedback = format_explainer_retry_context(
            {},  # el resultado previo ya está en el turno `assistant`; no se re-serializa
            validation_report,
            validation_context=self._validation_context,
            include_previous_result=False,
        )
        self._messages.append({"role": "user", "content": feedback})
        return await self._generate_validated()


async def check_explainer_validation_codex(
    explanation: dict,
    user_id: str,
    validation_context: ExplainerValidationContext | None = None,
    model: str = CODEX_MODEL_AUXILIARY,
    *,
    effort: str | None = None,
) -> tuple[ExplainerValidationReport, CodexUsage | None]:
    """Valida una explicación con Codex.

    Returns:
        (report, usage). Si el revisor falla, devuelve un report fail-open
        aceptado con usage None, igual que el resto de validadores.
    """
    start = time.time()
    try:
        user_message = _build_validator_user_message(explanation, validation_context)
        if user_message is None:
            return _accepted_report("Explicacion vacia; se acepta por defecto."), None

        content, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": user_message}],
            system_prompt=_CODEX_VALIDATOR_SYSTEM_PROMPT,
            model=model,
            response_format="json_object",
            effort=effort,
        )
        if not isinstance(content, dict):
            raise TypeError("El validador Codex no devolvió un objeto JSON.")

        report = _parse_validation_report(content)
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(
            "Explainer validado con Codex: complete=%s scope=%s — %s (%dms)",
            report.is_complete,
            report.scope_status,
            report.reason[:150],
            elapsed_ms,
            extra={
                "is_complete": report.is_complete,
                "scope_status": report.scope_status,
                "reason": report.reason[:200],
                "elapsed_ms": elapsed_ms,
                "prompt_tokens": usage.prompt_token_count,
                "candidates_tokens": usage.candidates_token_count,
                "model": model,
                "user_id": user_id[:8],
            },
        )
        return report, usage

    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning(
            "Error en validador Codex de explainer (%dms) — se acepta fail-open. Error: %s",
            elapsed_ms,
            str(exc)[:200],
            extra={
                "error_type": type(exc).__name__,
                "elapsed_ms": elapsed_ms,
                "user_id": user_id[:8],
            },
        )
        return (
            _accepted_report(f"Error en validador Codex ({type(exc).__name__}); resultado aceptado."),
            None,
        )


async def run_with_codex_explainer_validation(
    *,
    initial_call: Callable[[], Awaitable[tuple[dict[str, Any], CodexUsage]]],
    retry_call: Callable[..., Awaitable[tuple[dict[str, Any], CodexUsage]]],
    user_id: str,
    label: str,
    validation_context: ExplainerValidationContext | None = None,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage, list[Any]]:
    """Ejecuta una llamada explainer, la valida con Codex y regenera si falla.

    Espejo async de `run_with_deepseek_explainer_validation`: `user_id` ocupa
    la posición de `deepseek_api_key`; `initial_call`/`retry_call` son
    corrutinas. El validador es fail-open (un fallo del revisor acepta el
    resultado). Cada turno de validación consume `quota_requests=1` de la
    cuota de ChatGPT (comportamiento esperado y honesto).
    """
    result, usage = await initial_call()
    validator_usages: list[Any] = []
    last_report: ExplainerValidationReport | None = None

    for attempt in range(MAX_EXPLAINER_VALIDATION_RETRIES + 1):
        report, val_usage = await check_explainer_validation_codex(
            result, user_id=user_id, validation_context=validation_context, effort=effort
        )
        last_report = report
        if val_usage is not None:
            validator_usages.append(val_usage)

        if report.is_valid:
            if attempt > 0:
                logger.info(
                    "%s: validación confirmada tras %d reintento(s).",
                    label,
                    attempt,
                    extra={"label": label, "successful_attempt": attempt},
                )
            return result, usage, validator_usages

        logger.warning(
            "%s: explainer no valido (evaluacion %d/%d) — complete=%s scope=%s — %s",
            label,
            attempt + 1,
            MAX_EXPLAINER_VALIDATION_RETRIES + 1,
            report.is_complete,
            report.scope_status,
            report.reason[:150],
            extra={
                "label": label,
                "validation_attempt": attempt + 1,
                "max_validations": MAX_EXPLAINER_VALIDATION_RETRIES + 1,
                "is_complete": report.is_complete,
                "scope_status": report.scope_status,
                "reason": report.reason[:200],
            },
        )

        if attempt >= MAX_EXPLAINER_VALIDATION_RETRIES:
            break

        result, usage = await retry_call(result, report)

    assert last_report is not None
    logger.error(
        "%s: validacion de explainer agotada — abortando salida conocida como invalida.",
        label,
        extra={
            "label": label,
            "is_complete": last_report.is_complete,
            "scope_status": last_report.scope_status,
            "reason": last_report.reason[:300],
        },
    )
    raise ExplainerValidationError(label=label, report=last_report)


async def run_explainer_codex_validated(
    source_path: str,
    identificacion: str,
    model: str = CODEX_MODEL,
    mime_type: str = "application/pdf",
    user_id: str = "",
    validator_user_id: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    validation_context: ExplainerValidationContext | None = None,
    target_language: str = "es-ES",
    *,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage, list[Any]]:
    """run_explainer_codex con validación de completitud y reintento automático.

    Los reintentos son una conversación: el system prompt y el user message
    inicial (con la fuente OCR) no cambian; cada regeneración solo añade el
    turno previo + el feedback. La validación se ejecuta vía Codex
    (`validator_user_id` en la posición de `validator_api_key`).
    """
    user_message = _build_inline_source_message(
        source_path=source_path,
        identificacion=identificacion,
        mime_type=mime_type,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
    )
    conversation = _CodexExplainerConversation(
        system_prompt=build_openrouter_explainer_system_prompt(target_language),
        user_message=user_message,
        model=model,
        user_id=user_id,
        validate_payload=_validate_full_explainer_payload,
        validation_context=validation_context,
        operation_label="Explainer Codex",
        effort=effort,
    )
    return await run_with_codex_explainer_validation(
        initial_call=conversation.run_initial,
        retry_call=lambda prev, report: conversation.run_retry(report),
        user_id=validator_user_id or user_id,
        label=f"Explainer Codex [{model}]",
        validation_context=validation_context,
        effort=effort,
    )


async def run_subpart_explainer_codex_validated(
    source_path: str,
    identificacion: str,
    model: str = CODEX_MODEL,
    mime_type: str = "application/pdf",
    user_id: str = "",
    validator_user_id: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    validation_context: ExplainerValidationContext | None = None,
    target_language: str = "es-ES",
    *,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage, list[Any]]:
    """run_subpart_explainer_codex con validación de completitud y reintento.

    Reintentos conversacionales: el system prompt y el user message inicial
    (con la fuente OCR de la subparte) se mantienen idénticos; cada
    regeneración solo añade un turno.
    """
    user_message = _build_inline_source_message(
        source_path=source_path,
        identificacion=identificacion,
        mime_type=mime_type,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
    )
    conversation = _CodexExplainerConversation(
        system_prompt=build_openrouter_subpart_explainer_system_prompt(target_language),
        user_message=user_message,
        model=model,
        user_id=user_id,
        validate_payload=_validate_subpart_explainer_payload,
        validation_context=validation_context,
        operation_label="Subpart Explainer Codex",
        effort=effort,
    )
    return await run_with_codex_explainer_validation(
        initial_call=conversation.run_initial,
        retry_call=lambda prev, report: conversation.run_retry(report),
        user_id=validator_user_id or user_id,
        label=f"Subpart Explainer Codex [{model}]",
        validation_context=validation_context,
        effort=effort,
    )

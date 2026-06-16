"""Agente Explainer — implementación DeepSeek directa con JSON mode."""
from __future__ import annotations

import time
from typing import Any, Callable

from pypdf import PdfReader

from backend.agents.completeness_validator import (
    ExplainerValidationContext,
    ExplainerValidationReport,
    format_explainer_retry_context,
    run_with_deepseek_explainer_validation,
)
from backend.agents.explainer_openrouter import (
    OPENROUTER_EXPLAINER_TEMPERATURE,
    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
    build_openrouter_explainer_system_prompt,
    build_openrouter_subpart_explainer_system_prompt,
    _count_desarrollo_subsections,
    _count_payload_chars,
    _validate_full_explainer_payload,
    _validate_subpart_explainer_payload,
)
from backend.deepseek_client import (
    DeepSeekError,
    DeepSeekUsage,
    call_deepseek_chat,
    call_deepseek_chat_full,
)
from backend.deepseek_model_routing import DEEPSEEK_MODEL_V4_PRO, max_reasoning_effort
from backend.logging_config import get_logger
from backend.pdf_ocr_cache import PdfOcrCacheEntry, PdfOcrError, render_pdf_pages_with_xml_tags

logger = get_logger("backend.agents.explainer_deepseek")


def _extract_pdf_text(source_path: str) -> str:
    reader = PdfReader(source_path)
    chunks: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            chunks.append(f"<pagina_{index}>\n{text}\n</pagina_{index}>")
    if not chunks:
        raise DeepSeekError("DeepSeek fallback failed: no se pudo extraer texto útil del PDF local.")
    return "\n\n".join(chunks)


def _build_inline_source_message(
    *,
    source_path: str,
    identificacion: str,
    mime_type: str,
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
) -> str:
    source_text = ""
    if mime_type == "application/pdf" and pdf_cache_entry is not None:
        try:
            requested_pages = page_numbers or pdf_cache_entry.cached_page_numbers
            source_text = render_pdf_pages_with_xml_tags(
                cache_entry=pdf_cache_entry,
                page_numbers=requested_pages,
            )
        except PdfOcrError:
            logger.warning("La caché OCR de Mistral no pudo renderizar el subconjunto solicitado.")

    if not source_text and mime_type == "application/pdf":
        source_text = _extract_pdf_text(source_path)
    elif not source_text:
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            source_text = f.read()

    return (
        "<fuente_permitida>\n"
        f"{source_text}\n"
        "</fuente_permitida>\n\n"
        "<identificacion>\n"
        f"{identificacion}\n"
        "</identificacion>"
    )


def _is_retryable_payload_validation_error(exc: Exception) -> bool:
    return str(exc).startswith("Campo inválido en ")


def _call_deepseek_with_validation_retries(
    *,
    call_operation: Callable[[], tuple[dict[str, Any], DeepSeekUsage]],
    validate_payload: Callable[[Any], dict[str, Any]],
    operation_label: str,
) -> tuple[dict[str, Any], DeepSeekUsage]:
    total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        raw, usage = call_operation()
        try:
            return validate_payload(raw), usage
        except Exception as exc:
            if attempt >= total_attempts or not _is_retryable_payload_validation_error(exc):
                raise DeepSeekError(str(exc)) from exc
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
    raise DeepSeekError(
        f"{operation_label} agotó reintentos por payload inválido sin devolver JSON válido."
    )


def _call_deepseek_json_with_pdf_fallback(
    *,
    source_path: str,
    identificacion: str,
    mime_type: str,
    model: str,
    system_prompt: str,
    api_key: str,
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
) -> tuple[dict[str, Any], DeepSeekUsage]:
    user_message = _build_inline_source_message(
        source_path=source_path,
        identificacion=identificacion,
        mime_type=mime_type,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
    )
    content, usage = call_deepseek_chat(
        messages=[{"role": "user", "content": user_message}],
        model=model,
        system_prompt=system_prompt,
        api_key=api_key,
        response_format="json_object",
        reasoning_effort=max_reasoning_effort(),
        temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
    )
    if not isinstance(content, dict):
        raise DeepSeekError("Explainer DeepSeek no devolvió un objeto JSON.")
    return content, usage


def run_explainer_ds(
    source_path: str,
    identificacion: str,
    model: str = DEEPSEEK_MODEL_V4_PRO,
    mime_type: str = "application/pdf",
    api_key: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], DeepSeekUsage]:
    """Explainer completo vía DeepSeek directo. Retorna (structured_result, usage)."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer (deepseek)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
        },
    )

    result, usage = _call_deepseek_with_validation_retries(
        call_operation=lambda: _call_deepseek_json_with_pdf_fallback(
            source_path=source_path,
            identificacion=identificacion,
            mime_type=mime_type,
            model=model,
            system_prompt=build_openrouter_explainer_system_prompt(target_language),
            api_key=api_key,
            pdf_cache_entry=pdf_cache_entry,
            page_numbers=page_numbers,
        ),
        validate_payload=_validate_full_explainer_payload,
        operation_label="Explainer DeepSeek",
    )
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)
    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Explainer (deepseek) completado: %s secciones, %s subsecciones, %s chars en %sms",
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
        },
    )
    return result, usage


def run_subpart_explainer_ds(
    source_path: str,
    identificacion: str,
    model: str = DEEPSEEK_MODEL_V4_PRO,
    mime_type: str = "application/pdf",
    api_key: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], DeepSeekUsage]:
    """Explainer de subparte vía DeepSeek directo — retorna solo `desarrollo` estructurado."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer subparte (deepseek)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
        },
    )

    result, usage = _call_deepseek_with_validation_retries(
        call_operation=lambda: _call_deepseek_json_with_pdf_fallback(
            source_path=source_path,
            identificacion=identificacion,
            mime_type=mime_type,
            model=model,
            system_prompt=build_openrouter_subpart_explainer_system_prompt(target_language),
            api_key=api_key,
            pdf_cache_entry=pdf_cache_entry,
            page_numbers=page_numbers,
        ),
        validate_payload=_validate_subpart_explainer_payload,
        operation_label="Explainer subparte DeepSeek",
    )
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)
    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Subpart explainer (deepseek) completado: %s secciones, %s subsecciones, %s chars en %sms",
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
        },
    )
    return result, usage


def _payload_correction_message(exc: Exception) -> str:
    return (
        "Tu respuesta anterior no cumple el contrato JSON estructurado del explainer.\n"
        f"Problema detectado: {exc}\n"
        "Regenera la explicación COMPLETA respetando exactamente el mismo esquema JSON requerido "
        "(mismas claves y tipos), corrigiendo únicamente ese problema."
    )


class _DeepSeekExplainerConversation:
    """Conversación DeepSeek con estado para reintentos cache-friendly.

    El system prompt y el PRIMER user message (que lleva el OCR fuente, caro) se
    mantienen byte-idénticos en todas las rondas; cada reintento solo AÑADE el turno
    `assistant` crudo anterior y un nuevo turno `user` corto con el feedback. Así el
    prefijo (system + user0 [+ assistant0]) es una unidad de caché que DeepSeek reusa en
    cada regeneración, evitando reenviar la fuente.
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        user_message: str,
        model: str,
        api_key: str,
        validate_payload: Callable[[Any], dict[str, Any]],
        validation_context: ExplainerValidationContext | None,
        operation_label: str,
    ) -> None:
        self._system_prompt = system_prompt
        self._model = model
        self._api_key = api_key
        self._validate_payload = validate_payload
        self._validation_context = validation_context
        self._operation_label = operation_label
        # Solo turnos user/assistant; el system se pasa aparte y NO se muta nunca.
        self._messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    def _generate_validated(self) -> tuple[dict[str, Any], DeepSeekUsage]:
        total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
        for attempt in range(1, total_attempts + 1):
            result = call_deepseek_chat_full(
                messages=self._messages,
                model=self._model,
                system_prompt=self._system_prompt,
                api_key=self._api_key,
                response_format="json_object",
                reasoning_effort=max_reasoning_effort(),
                temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
            )
            # Reproducir el output crudo del modelo VERBATIM en la siguiente ronda para
            # mantener la continuidad del prefijo de caché.
            self._messages.append(
                {"role": "assistant", "content": result.assistant_message.content}
            )
            content = result.content
            if not isinstance(content, dict):
                raise DeepSeekError("Explainer DeepSeek no devolvió un objeto JSON.")
            try:
                return self._validate_payload(content), result.usage
            except Exception as exc:
                if attempt >= total_attempts or not _is_retryable_payload_validation_error(exc):
                    raise DeepSeekError(str(exc)) from exc
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
                    },
                )
                # Turno correctivo appendido: no se reenvía la fuente, solo el problema.
                self._messages.append(
                    {"role": "user", "content": _payload_correction_message(exc)}
                )
        raise DeepSeekError(
            f"{self._operation_label} agotó reintentos por payload inválido sin devolver JSON válido."
        )

    def run_initial(self) -> tuple[dict[str, Any], DeepSeekUsage]:
        return self._generate_validated()

    def run_retry(
        self, validation_report: ExplainerValidationReport
    ) -> tuple[dict[str, Any], DeepSeekUsage]:
        logger.info(
            "Reintentando explainer (deepseek) por validación — append conversacional",
            extra={
                "operation_label": self._operation_label,
                "model": self._model,
                "is_complete": validation_report.is_complete,
                "scope_status": validation_report.scope_status,
            },
        )
        feedback = format_explainer_retry_context(
            {},  # el resultado previo ya está en el turno `assistant`; no se re-serializa
            validation_report,
            validation_context=self._validation_context,
            include_previous_result=False,
        )
        self._messages.append({"role": "user", "content": feedback})
        return self._generate_validated()


def run_explainer_ds_validated(
    source_path: str,
    identificacion: str,
    model: str = DEEPSEEK_MODEL_V4_PRO,
    mime_type: str = "application/pdf",
    api_key: str = "",
    validator_api_key: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    validation_context: ExplainerValidationContext | None = None,
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], DeepSeekUsage, list[Any]]:
    """run_explainer_ds con validación de completitud y reintento automático.

    Los reintentos son una conversación: el system prompt y el user message inicial (con
    la fuente OCR) no cambian; cada regeneración solo añade el turno previo + el feedback.
    """
    user_message = _build_inline_source_message(
        source_path=source_path,
        identificacion=identificacion,
        mime_type=mime_type,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
    )
    conversation = _DeepSeekExplainerConversation(
        system_prompt=build_openrouter_explainer_system_prompt(target_language),
        user_message=user_message,
        model=model,
        api_key=api_key,
        validate_payload=_validate_full_explainer_payload,
        validation_context=validation_context,
        operation_label="Explainer DeepSeek",
    )
    return run_with_deepseek_explainer_validation(
        initial_call=conversation.run_initial,
        retry_call=lambda prev, report: conversation.run_retry(report),
        deepseek_api_key=validator_api_key or api_key,
        label=f"Explainer DeepSeek [{model}]",
        validation_context=validation_context,
    )


def run_subpart_explainer_ds_validated(
    source_path: str,
    identificacion: str,
    model: str = DEEPSEEK_MODEL_V4_PRO,
    mime_type: str = "application/pdf",
    api_key: str = "",
    validator_api_key: str = "",
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
    validation_context: ExplainerValidationContext | None = None,
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], DeepSeekUsage, list[Any]]:
    """run_subpart_explainer_ds con validación de completitud y reintento automático.

    Reintentos conversacionales: el system prompt y el user message inicial (con la fuente
    OCR de la subparte) se mantienen idénticos; cada regeneración solo añade un turno.
    """
    user_message = _build_inline_source_message(
        source_path=source_path,
        identificacion=identificacion,
        mime_type=mime_type,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
    )
    conversation = _DeepSeekExplainerConversation(
        system_prompt=build_openrouter_subpart_explainer_system_prompt(target_language),
        user_message=user_message,
        model=model,
        api_key=api_key,
        validate_payload=_validate_subpart_explainer_payload,
        validation_context=validation_context,
        operation_label="Subpart Explainer DeepSeek",
    )
    return run_with_deepseek_explainer_validation(
        initial_call=conversation.run_initial,
        retry_call=lambda prev, report: conversation.run_retry(report),
        deepseek_api_key=validator_api_key or api_key,
        label=f"Subpart Explainer DeepSeek [{model}]",
        validation_context=validation_context,
    )

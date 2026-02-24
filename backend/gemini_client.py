"""Cliente Gemini con sistema de retry robusto y manejo de errores.

Este módulo proporciona:
- Retry automático con backoff exponencial y jitter
- Manejo específico de errores de Gemini API (429, 500, 503, 504)
- Excepciones personalizadas para diferentes tipos de fallos
- Logging detallado de intentos y errores con métricas
- Decorator reutilizable para funciones de agentes
"""
from __future__ import annotations

import functools
import json
import logging
import random
import time
from typing import Any, Callable, TypeVar, cast

from google import genai
from google.genai import types

from backend.logging_config import get_logger

# Logger configurado
logger = get_logger("backend.gemini_client")

# Constantes configurables
MAX_RETRIES = 5
BASE_DELAY = 1.0  # segundos
MAX_DELAY = 60.0  # segundos
JITTER_FACTOR = 0.1  # 10% de variación
DEFAULT_TIMEOUT = 300  # 5 minutos

# Códigos de error retryable según documentación oficial Gemini
RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 403, 404}

# Tipo para el decorator
F = TypeVar("F", bound=Callable[..., Any])


class GeminiError(Exception):
    """Excepción base para errores de Gemini."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class GeminiRateLimitError(GeminiError):
    """Error cuando se excede el rate limit (429)."""

    def __init__(self, message: str, retry_after: int | None = None, details: dict | None = None):
        super().__init__(message, status_code=429, details=details)
        self.retry_after = retry_after


class GeminiServiceError(GeminiError):
    """Error de servicio de Gemini (500, 503)."""

    def __init__(self, message: str, status_code: int, details: dict | None = None):
        super().__init__(message, status_code=status_code, details=details)


class GeminiTimeoutError(GeminiError):
    """Error de timeout (504)."""

    def __init__(self, message: str, timeout: int, details: dict | None = None):
        super().__init__(message, status_code=504, details=details)
        self.timeout = timeout


class GeminiAuthError(GeminiError):
    """Error de autenticación o permisos (403)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, status_code=403, details=details)


class GeminiInvalidArgumentError(GeminiError):
    """Error de argumento inválido (400)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, status_code=400, details=details)


def _extract_error_info(error: Exception) -> tuple[int | None, str, dict]:
    """Extrae código de estado, mensaje y detalles de una excepción de la SDK.

    La SDK de google-genai lanza excepciones que pueden contener:
    - code: código HTTP de error
    - message: mensaje descriptivo
    - details: información adicional
    """
    status_code = None
    message = str(error)
    details = {}

    # Intentar extraer código de error
    if hasattr(error, "code"):
        try:
            status_code = int(error.code)
        except (ValueError, TypeError):
            pass

    # Intentar extraer código de args si es tupla (común en excepciones gRPC/HTTP)
    if status_code is None and hasattr(error, "args") and error.args:
        for arg in error.args:
            if isinstance(arg, int) and 100 <= arg <= 599:
                status_code = arg
                break

    # Extraer detalles si están disponibles
    if hasattr(error, "details") and error.details:
        details["raw_details"] = str(error.details)

    # Para errores HTTP específicos, intentar extraer más información
    if "429" in message or "Resource exhausted" in message or "rate limit" in message.lower():
        status_code = 429
    elif "503" in message or "Unavailable" in message:
        status_code = 503
    elif "500" in message or "Internal error" in message:
        status_code = 500
    elif "504" in message or "Deadline exceeded" in message or "timeout" in message.lower():
        status_code = 504
    elif "403" in message or "Permission denied" in message:
        status_code = 403
    elif "400" in message or "Invalid argument" in message:
        status_code = 400
    elif "404" in message or "Not found" in message:
        status_code = 404

    return status_code, message, details


def _calculate_delay(attempt: int, base_delay: float = BASE_DELAY, max_delay: float = MAX_DELAY) -> float:
    """Calcula el delay con backoff exponencial y jitter.

    Fórmula: min(base * 2^attempt, max_delay) + jitter
    Jitter: ±10% para evitar thundering herd
    """
    exponential_delay = min(base_delay * (2 ** attempt), max_delay)
    jitter = exponential_delay * JITTER_FACTOR * (random.random() * 2 - 1)
    delay = exponential_delay + jitter
    return max(0.1, delay)  # Mínimo 100ms


def _is_retryable_error(status_code: int | None, message: str) -> bool:
    """Determina si un error es retryable basado en código y mensaje."""
    if status_code is None:
        # Si no hay código, revisar mensaje para errores transitorios conocidos
        transient_patterns = [
            "rate limit",
            "resource exhausted",
            "service unavailable",
            "internal error",
            "timeout",
            "deadline exceeded",
            "connection",
            "network",
            "temporarily",
        ]
        message_lower = message.lower()
        return any(pattern in message_lower for pattern in transient_patterns)

    return status_code in RETRYABLE_STATUS_CODES


def _is_context_too_large_error(message: str) -> bool:
    """Detecta si el error es por contexto demasiado grande."""
    patterns = [
        "input context is too long",
        "context too long",
        "exceeds maximum token",
        "prompt is too large",
        "content too large",
    ]
    message_lower = message.lower()
    return any(pattern in message_lower for pattern in patterns)


def _is_safety_blocked_error(message: str) -> bool:
    """Detecta si el error es por bloqueo de safety/content."""
    patterns = [
        "blocked",
        "safety",
        "content policy",
        "recitation",
        "copyright",
    ]
    message_lower = message.lower()
    return any(pattern in message_lower for pattern in patterns)


class GeminiRetryHandler:
    """Handler centralizado para operaciones de Gemini con retry.

    Ejemplo de uso:
        handler = GeminiRetryHandler(max_retries=5)
        result = handler.execute_with_retry(
            lambda: client.models.generate_content(...)
        )
    """

    def __init__(
        self,
        max_retries: int = MAX_RETRIES,
        base_delay: float = BASE_DELAY,
        max_delay: float = MAX_DELAY,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self._consecutive_failures = 0
        self._circuit_breaker_threshold = 10
        self._circuit_breaker_reset_time = 300  # 5 minutos
        self._last_failure_time: float | None = None

    def _check_circuit_breaker(self) -> bool:
        """Verifica si el circuit breaker está abierto."""
        if self._consecutive_failures < self._circuit_breaker_threshold:
            return False

        # Si han pasado 5 minutos desde el último fallo, resetear
        if self._last_failure_time:
            time_since_last_failure = time.time() - self._last_failure_time
            if time_since_last_failure > self._circuit_breaker_reset_time:
                logger.info("Circuit breaker: reseteando después de cooldown")
                self._consecutive_failures = 0
                return False

        return True

    def _record_failure(self):
        """Registra un fallo para el circuit breaker."""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()

    def _record_success(self):
        """Registra un éxito, reseteando contador de fallos."""
        if self._consecutive_failures > 0:
            logger.debug("Reseteando contador de fallos consecutivos")
            self._consecutive_failures = 0

    def execute_with_retry(
        self,
        operation: Callable[[], Any],
        operation_name: str = "gemini_operation",
    ) -> Any:
        """Ejecuta una operación con retry automático.

        Args:
            operation: Función a ejecutar (lambda o callable)
            operation_name: Nombre descriptivo para logs

        Returns:
            Resultado de la operación

        Raises:
            GeminiError: Si se agotan los reintentos o el error no es retryable
        """
        start_time = time.time()
        logger.info(
            f"[{operation_name}] Iniciando operación",
            extra={"operation": operation_name, "max_retries": self.max_retries}
        )

        # Verificar circuit breaker
        if self._check_circuit_breaker():
            error_msg = (
                f"Circuit breaker abierto después de {self._consecutive_failures} fallos consecutivos. "
                f"Esperando {self._circuit_breaker_reset_time // 60} minutos antes de reintentar."
            )
            logger.critical(f"[{operation_name}] {error_msg}")
            raise GeminiServiceError(error_msg, status_code=503)

        last_exception: Exception | None = None
        current_timeout = self.timeout
        total_tokens = 0

        for attempt in range(self.max_retries + 1):
            attempt_start = time.time()
            try:
                logger.info(
                    f"[{operation_name}] Intento {attempt + 1}/{self.max_retries + 1}",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "max_attempts": self.max_retries + 1,
                    }
                )

                result = operation()
                attempt_duration = (time.time() - attempt_start) * 1000

                # Extraer información de uso de tokens si está disponible
                tokens_info = {}
                if hasattr(result, "usage_metadata") and result.usage_metadata:
                    total_tokens = getattr(result.usage_metadata, "total_token_count", 0)
                    tokens_info = {
                        "prompt_tokens": getattr(result.usage_metadata, "prompt_token_count", 0),
                        "candidates_tokens": getattr(result.usage_metadata, "candidates_token_count", 0),
                        "thoughts_tokens": getattr(result.usage_metadata, "thoughts_token_count", 0),
                        "total_tokens": total_tokens,
                    }

                self._record_success()
                total_duration = (time.time() - start_time) * 1000

                if attempt > 0:
                    logger.info(
                        f"[{operation_name}] Éxito después de {attempt} reintentos",
                        extra={
                            "operation": operation_name,
                            "retries_needed": attempt,
                            "duration_ms": int(total_duration),
                            **tokens_info,
                        }
                    )
                else:
                    logger.info(
                        f"[{operation_name}] Operación completada exitosamente",
                        extra={
                            "operation": operation_name,
                            "duration_ms": int(total_duration),
                            "attempt_duration_ms": int(attempt_duration),
                            **tokens_info,
                        }
                    )

                return result

            except Exception as e:
                attempt_duration = (time.time() - attempt_start) * 1000
                last_exception = e
                status_code, message, details = _extract_error_info(e)

                # Log detallado del error
                logger.warning(
                    f"[{operation_name}] Error en intento {attempt + 1}: "
                    f"code={status_code}, message={message[:150]}",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "status_code": status_code,
                        "error_type": type(e).__name__,
                        "error_message": message[:500],
                        "duration_ms": int(attempt_duration),
                    }
                )

                # Verificar casos especiales que no deben reintentarse
                if _is_context_too_large_error(message):
                    logger.error(
                        f"[{operation_name}] Contexto demasiado grande, no se reintentará",
                        extra={
                            "operation": operation_name,
                            "error_type": "context_too_large",
                            "status_code": status_code,
                        }
                    )
                    raise GeminiInvalidArgumentError(
                        "El contexto es demasiado largo para ser procesado. "
                        "Reduzca el tamaño del texto o divida en partes más pequeñas.",
                        details={"original_error": message, "status_code": status_code},
                    )

                if _is_safety_blocked_error(message):
                    logger.error(
                        f"[{operation_name}] Contenido bloqueado por safety, no se reintentará",
                        extra={
                            "operation": operation_name,
                            "error_type": "safety_blocked",
                            "status_code": status_code,
                        }
                    )
                    raise GeminiError(
                        "El contenido fue bloqueado por políticas de seguridad. "
                        "Revise el contenido del documento.",
                        status_code=status_code or 400,
                        details={"original_error": message, "reason": "safety_blocked"},
                    )

                # Si es el último intento, propagar el error
                if attempt >= self.max_retries:
                    self._record_failure()
                    total_duration = (time.time() - start_time) * 1000
                    logger.error(
                        f"[{operation_name}] Agotados {self.max_retries + 1} intentos. "
                        f"Último error: code={status_code}, message={message[:200]}",
                        extra={
                            "operation": operation_name,
                            "total_attempts": self.max_retries + 1,
                            "status_code": status_code,
                            "error_type": type(e).__name__,
                            "error_message": message[:1000],
                            "total_duration_ms": int(total_duration),
                            "circuit_failures": self._consecutive_failures,
                        }
                    )
                    raise self._create_gemini_error(status_code, message, details)

                # Verificar si el error es retryable
                if not _is_retryable_error(status_code, message):
                    logger.error(
                        f"[{operation_name}] Error no retryable (code={status_code}), propagando",
                        extra={
                            "operation": operation_name,
                            "status_code": status_code,
                            "error_type": type(e).__name__,
                            "retryable": False,
                        }
                    )
                    raise self._create_gemini_error(status_code, message, details)

                # Calcular delay antes del siguiente intento
                delay = _calculate_delay(attempt, self.base_delay, self.max_delay)

                # Para rate limits, intentar extraer Retry-After si está disponible
                if status_code == 429:
                    # Si la excepción tiene metadata de retry, usarla
                    if hasattr(e, "metadata") and e.metadata:
                        retry_after = getattr(e.metadata, "retry_after", None)
                        if retry_after:
                            delay = max(delay, retry_after)
                            logger.info(
                                f"[{operation_name}] Usando Retry-After: {delay:.1f}s",
                                extra={
                                    "operation": operation_name,
                                    "retry_after": retry_after,
                                    "calculated_delay": delay,
                                }
                            )

                # Para timeouts, aumentar el timeout para el siguiente intento
                if status_code == 504:
                    current_timeout = int(current_timeout * 1.5)
                    logger.info(
                        f"[{operation_name}] Aumentando timeout a {current_timeout}s",
                        extra={
                            "operation": operation_name,
                            "new_timeout": current_timeout,
                            "previous_timeout": int(current_timeout / 1.5),
                        }
                    )

                logger.info(
                    f"[{operation_name}] Esperando {delay:.2f}s antes del siguiente intento",
                    extra={
                        "operation": operation_name,
                        "delay_seconds": round(delay, 2),
                        "next_attempt": attempt + 2,
                    }
                )
                time.sleep(delay)

        # No debería llegar aquí, pero por seguridad
        total_duration = (time.time() - start_time) * 1000
        logger.critical(
            f"[{operation_name}] Error inesperado después de {self.max_retries + 1} intentos",
            extra={
                "operation": operation_name,
                "total_duration_ms": int(total_duration),
                "unexpected": True,
            }
        )
        raise GeminiServiceError(
            f"Error inesperado después de {self.max_retries + 1} intentos",
            status_code=500,
            details={"last_error": str(last_exception) if last_exception else None},
        )

    def _create_gemini_error(
        self, status_code: int | None, message: str, details: dict
    ) -> GeminiError:
        """Crea la excepción Gemini apropiada según el código de estado."""
        if status_code == 429:
            return GeminiRateLimitError(message, details=details)
        elif status_code == 504:
            return GeminiTimeoutError(message, timeout=self.timeout, details=details)
        elif status_code == 403:
            return GeminiAuthError(message, details=details)
        elif status_code == 400:
            return GeminiInvalidArgumentError(message, details=details)
        elif status_code in [500, 503]:
            return GeminiServiceError(message, status_code=status_code or 500, details=details)
        else:
            return GeminiError(
                message,
                status_code=status_code,
                details=details,
            )


def gemini_retry(
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    max_delay: float = MAX_DELAY,
    timeout: int = DEFAULT_TIMEOUT,
) -> Callable[[F], F]:
    """Decorator para añadir retry automático a funciones que usan Gemini.

    Args:
        max_retries: Número máximo de reintentos
        base_delay: Delay base para backoff exponencial
        max_delay: Delay máximo entre reintentos
        timeout: Timeout para operaciones

    Ejemplo:
        @gemini_retry(max_retries=5)
        def run_segmentador(api_key: str, file_uri: str, description: str):
            client = genai.Client(api_key=api_key)
            return client.models.generate_content(...)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            handler = GeminiRetryHandler(
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                timeout=timeout,
            )
            return handler.execute_with_retry(
                lambda: func(*args, **kwargs),
                operation_name=func.__name__,
            )
        return cast(F, wrapper)
    return decorator


def generate_content_with_retry(
    client: genai.Client,
    model: str,
    contents: list,
    config: types.GenerateContentConfig,
    max_retries: int = MAX_RETRIES,
    operation_context: dict[str, Any] | None = None,
) -> Any:
    """Wrapper conveniente para client.models.generate_content con retry.

    Args:
        client: Cliente de Gemini inicializado
        model: Nombre del modelo
        contents: Contenidos para la generación
        config: Configuración de generación
        max_retries: Número máximo de reintentos
        operation_context: Contexto adicional para logging (ej: agent_name, part_id)

    Returns:
        Respuesta de la API
    """
    operation_name = "generate_content"
    if operation_context:
        ctx_parts = [f"{k}={v}" for k, v in operation_context.items()]
        operation_name = f"generate_content[{','.join(ctx_parts)}]"

    logger.info(
        f"[{operation_name}] Preparando generación de contenido",
        extra={
            "operation": "generate_content",
            "model": model,
            "max_retries": max_retries,
            **(operation_context or {}),
        }
    )

    handler = GeminiRetryHandler(max_retries=max_retries)

    def operation():
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    return handler.execute_with_retry(operation, operation_name=operation_name)


def upload_file_with_retry(
    client: genai.Client,
    file_path: str,
    max_retries: int = MAX_RETRIES,
) -> Any:
    """Wrapper para client.files.upload con retry.

    Args:
        client: Cliente de Gemini inicializado
        file_path: Ruta del archivo a subir
        max_retries: Número máximo de reintentos

    Returns:
        Objeto File subido
    """
    import os

    file_size = 0
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        pass

    logger.info(
        f"[files.upload] Iniciando subida de archivo: {file_path}",
        extra={
            "operation": "files.upload",
            "file_path": file_path,
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else None,
            "max_retries": max_retries,
        }
    )

    handler = GeminiRetryHandler(max_retries=max_retries)

    def operation():
        return client.files.upload(file=file_path)

    result = handler.execute_with_retry(operation, operation_name="files.upload")

    logger.info(
        f"[files.upload] Archivo subido exitosamente: {result.uri if hasattr(result, 'uri') else 'unknown'}",
        extra={
            "operation": "files.upload",
            "file_uri": result.uri if hasattr(result, "uri") else None,
            "file_name": result.name if hasattr(result, "name") else None,
        }
    )

    return result


# Excepciones específicas que pueden usar los agentes
__all__ = [
    "GeminiRetryHandler",
    "gemini_retry",
    "generate_content_with_retry",
    "upload_file_with_retry",
    "GeminiError",
    "GeminiRateLimitError",
    "GeminiServiceError",
    "GeminiTimeoutError",
    "GeminiAuthError",
    "GeminiInvalidArgumentError",
]

"""
Middleware de seguridad (headers) y logging.
"""

import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from backend.logging_config import get_logger, set_context, clear_context

logger = get_logger("backend.middleware")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Añade headers de seguridad a todas las respuestas.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevenir que el browser "adivine" el tipo de contenido
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevenir clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Política de seguridad de contenido (básica)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self' https://generativelanguage.googleapis.com;"
        )

        # Forzar HTTPS
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Política de referrer
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware para logging de requests HTTP con correlation ID.
    """

    async def dispatch(self, request: Request, call_next):
        # Generar correlation ID
        correlation_id = str(uuid.uuid4())[:8]
        request.state.correlation_id = correlation_id

        # Limpiar contexto al inicio
        clear_context()

        start_time = time.time()
        method = request.method
        path = request.url.path

        # Log de request
        logger.debug(
            f"[{correlation_id}] Request iniciado: {method} {path}",
            extra={
                "correlation_id": correlation_id,
                "method": method,
                "path": path,
                "query_params": str(request.query_params),
                "client_host": request.client.host if request.client else None,
            }
        )

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            # Log de response exitosa
            logger.debug(
                f"[{correlation_id}] Request completado: {method} {path} - {response.status_code} ({int(duration_ms)}ms)",
                extra={
                    "correlation_id": correlation_id,
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": int(duration_ms),
                }
            )

            # Añadir correlation ID a la respuesta
            response.headers["X-Correlation-ID"] = correlation_id

            return response

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.exception(
                f"[{correlation_id}] Request fallido: {method} {path} - {str(e)[:100]}",
                extra={
                    "correlation_id": correlation_id,
                    "method": method,
                    "path": path,
                    "duration_ms": int(duration_ms),
                    "error_type": type(e).__name__,
                }
            )
            raise

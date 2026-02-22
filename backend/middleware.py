"""
Middleware de seguridad (headers).
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


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

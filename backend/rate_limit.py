"""
Rate limiting para protección contra abuso.

Usa slowapi para rate limiting basado en IP y usuario.
"""

from functools import wraps
from typing import Optional, Callable
import time
from collections import defaultdict

from fastapi import Request, HTTPException, status


# Almacenamiento simple en memoria para rate limiting
# En producción con múltiples instancias, usar Redis
class MemoryRateLimiter:
    """Rate limiter simple en memoria (para desarrollo y single-instance)."""

    def __init__(self):
        # key -> [(timestamp, count), ...]
        self._requests: defaultdict[str, list] = defaultdict(list)
        self._cleanup_interval = 3600  # Limpiar cada hora
        self._last_cleanup = time.time()

    def _cleanup(self):
        """Limpia entradas antiguas."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        for key in list(self._requests.keys()):
            self._requests[key] = [
                (ts, cnt) for ts, cnt in self._requests[key]
                if now - ts < 3600  # Mantener solo última hora
            ]
            if not self._requests[key]:
                del self._requests[key]

        self._last_cleanup = now

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """
        Verifica si una request está dentro del rate limit.

        Args:
            key: Identificador único (IP + endpoint, o user_id)
            max_requests: Máximo número de requests permitidos
            window_seconds: Ventana de tiempo en segundos

        Returns:
            True si está permitido, False si excede el límite
        """
        self._cleanup()

        now = time.time()
        window_start = now - window_seconds

        # Filtrar requests dentro de la ventana
        recent_requests = [
            (ts, cnt) for ts, cnt in self._requests[key]
            if ts > window_start
        ]

        total = sum(cnt for _, cnt in recent_requests)

        if total >= max_requests:
            return False

        # Registrar esta request
        recent_requests.append((now, 1))
        self._requests[key] = recent_requests

        return True

    def get_retry_after(self, key: str, window_seconds: int) -> int:
        """Calcula segundos hasta que se resetee el rate limit."""
        if key not in self._requests or not self._requests[key]:
            return 0

        now = time.time()
        oldest = min(ts for ts, _ in self._requests[key])
        retry_after = int(oldest + window_seconds - now)
        return max(0, retry_after)


# Instancia global
_limiter = MemoryRateLimiter()


def rate_limit(max_requests: int = 5, window_seconds: int = 60):
    """
    Decorador para rate limiting en endpoints.

    Args:
        max_requests: Máximo número de requests permitidos
        window_seconds: Ventana de tiempo en segundos

    Ejemplo:
        @app.post("/api/projects")
        @rate_limit(max_requests=10, window_seconds=60)
        async def create_project(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extraer request de los argumentos
            request: Optional[Request] = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if request is None:
                # Buscar en kwargs
                request = kwargs.get('request')

            if request:
                # Crear key basada en IP y path
                client_ip = request.client.host if request.client else "unknown"
                path = request.url.path
                key = f"{client_ip}:{path}"

                if not _limiter.is_allowed(key, max_requests, window_seconds):
                    retry_after = _limiter.get_retry_after(key, window_seconds)
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                        headers={"Retry-After": str(retry_after)}
                    )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


# Rate limits predefinidos para endpoints comunes

def api_rate_limit(func: Callable):
    """Rate limit general para API: 100 requests por minuto."""
    return rate_limit(max_requests=100, window_seconds=60)(func)


def project_create_rate_limit(func: Callable):
    """Rate limit para crear proyectos: 10 por minuto."""
    return rate_limit(max_requests=10, window_seconds=60)(func)


def api_key_rate_limit(func: Callable):
    """Rate limit para endpoints de API key (POST/DELETE): 10 por minuto."""
    return rate_limit(max_requests=10, window_seconds=60)(func)

"""
Gestor de Server-Sent Events (SSE) con soporte para Redis (producción)
y memoria local (desarrollo).

En Fly.io con una sola instancia, la memoria local funciona bien.
Si se escala a múltiples instancias, Redis es necesario.
"""

import os
import json
import asyncio
from typing import Dict, Optional, AsyncGenerator
from pathlib import Path

# Intentar importar redis, pero no es obligatorio (fallback a memoria)
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


# URL de Redis - Fly.io provee REDIS_URL en producción
REDIS_URL = os.environ.get("REDIS_URL")


class SSEManager:
    """
    Gestor de eventos SSE que soporta Redis (producción) o memoria local (dev).
    """

    def __init__(self):
        self._local_queues: Dict[str, asyncio.Queue] = {}
        self._redis_client = None
        self._use_redis = False

        if REDIS_AVAILABLE and REDIS_URL:
            try:
                self._redis_client = redis.from_url(REDIS_URL)
                self._use_redis = True
            except Exception as e:
                print(f"[SSE] No se pudo conectar a Redis: {e}. Usando memoria local.")
                self._use_redis = False

    def _get_queue(self, project_id: str) -> asyncio.Queue:
        """Obtiene o crea una cola local para un proyecto."""
        if project_id not in self._local_queues:
            self._local_queues[project_id] = asyncio.Queue()
        return self._local_queues[project_id]

    async def publish_event(self, project_id: str, event: dict) -> None:
        """
        Publica un evento SSE.

        Args:
            project_id: ID del proyecto
            event: Diccionario con el evento
        """
        if self._use_redis:
            try:
                await self._redis_client.publish(
                    f"sse:{project_id}",
                    json.dumps(event)
                )
            except Exception as e:
                print(f"[SSE] Error publicando en Redis: {e}")
                # Fallback a memoria
                queue = self._get_queue(project_id)
                await queue.put(event)
        else:
            queue = self._get_queue(project_id)
            await queue.put(event)

    async def subscribe_events(self, project_id: str) -> AsyncGenerator[dict, None]:
        """
        Suscribe a eventos SSE de un proyecto.

        Yields:
            Eventos como diccionarios
        """
        if self._use_redis:
            async for event in self._subscribe_redis(project_id):
                yield event
        else:
            async for event in self._subscribe_local(project_id):
                yield event

    async def _subscribe_local(self, project_id: str) -> AsyncGenerator[dict, None]:
        """Suscripción local en memoria."""
        queue = self._get_queue(project_id)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if event is None:  # Señal de fin
                    yield {"type": "stream_end"}
                    break
                yield event
            except asyncio.TimeoutError:
                yield {"type": "ping"}

    async def _subscribe_redis(self, project_id: str) -> AsyncGenerator[dict, None]:
        """Suscripción via Redis pub/sub."""
        channel = f"sse:{project_id}"

        try:
            pubsub = self._redis_client.pubsub()
            await pubsub.subscribe(channel)

            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)

                if message is None:
                    # Timeout - enviar ping
                    yield {"type": "ping"}
                    continue

                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        if event.get("type") == "stream_end":
                            yield event
                            break
                        yield event
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            print(f"[SSE] Error en suscripción Redis: {e}")
            # Fallback a ping para mantener conexión
            yield {"type": "ping"}
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except:
                pass

    async def end_stream(self, project_id: str) -> None:
        """
        Señaliza el fin del stream SSE para un proyecto.
        """
        await self.publish_event(project_id, {"type": "stream_end"})

        # Limpiar cola local si existe
        if project_id in self._local_queues:
            del self._local_queues[project_id]


# Instancia global del gestor
sse_manager = SSEManager()


# Funciones de conveniencia para compatibilidad con el código existente
async def send_event(project_id: str, payload: dict) -> None:
    """Envía un evento SSE (compatible con el código anterior)."""
    await sse_manager.publish_event(project_id, payload)


async def subscribe_events(project_id: str) -> AsyncGenerator[dict, None]:
    """Suscribe a eventos SSE (compatible con el código anterior)."""
    async for event in sse_manager.subscribe_events(project_id):
        yield event

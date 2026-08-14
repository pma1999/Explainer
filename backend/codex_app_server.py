"""Gestor de procesos `codex app-server --stdio` por tenant (T02).

Un proceso por `user_id`, spawn perezoso vía `CodexAppServerManager.acquire`,
aislamiento por `CODEX_HOME` (modo 0700), transporte JSONL newline-delimited
por stdin/stdout, límites por env, restauración/snapshot cifrado de `auth.json`
y ciclo de vida (evicción LRU + inactividad + shutdown del lifespan).

Contrato (global-constraints.md §Tenant isolation and process lifecycle):
- `CodexAppServerManager.acquire/evict/shutdown/add_notification_handler` +
  `active_count`; singleton de módulo `codex_manager`.
- `CodexAppServer.home_dir` + `CodexAppServer.request(method, params, timeout)`.
- Errores tipados `CodexAppServerError` / `CodexSpawnError` /
  `CodexRequestError(code, message, data)`; `CodexTimeoutError` (aditivo para
  la jerarquía de T07).
- Límites por env: `CODEX_BIN_PATH`, `CODEX_HOME_ROOT`, `CODEX_MAX_PROCESSES=3`,
  `CODEX_SPAWN_WAIT_SECONDS=60`, `CODEX_PER_PROCESS_MAX_CONCURRENCY=5`,
  `CODEX_IDLE_TTL_SECONDS=600`, `CODEX_REQUEST_TIMEOUT_SECONDS=900` (más
  `CODEX_TERMINATE_GRACE_SECONDS` para SIGTERM → SIGKILL).

Seguridad: `user_id` pasa validación UUID estricta antes de usarse en paths;
nunca se loguea `auth.json`, `encrypted_credentials` ni stderr crudo (solo
previews truncados y `user_id[:8]`); stderr del subproceso va a
`<CODEX_HOME>/app-server.stderr.log` truncado en cada spawn.

Ciclo de vida: cada tenant tiene un lock de evicción (hoja) que la
evacuación (LRU, `evict`, shutdown) mantiene durante TODO el
terminate/snapshot/cleanup y que `acquire` espera antes de tocar
`CODEX_HOME`; nunca hay dos ciclos de vida (restauración/spawn vs
terminate/snapshot/borrado) sobre el mismo home a la vez.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("backend.codex_app_server")

# --- Límites por env (contrato) ---
# Nombres públicos congelados = defaults del contrato. Los VALORES efectivos
# se leen del env EN EL MOMENTO DE USO vía los helpers `_env_*()`: este módulo
# puede importarse de forma eager (main.py → agents → codex_client) ANTES de
# que el entorno fije `CODEX_BIN_PATH` (p.ej. los tests de T02 lo fijan a
# nivel de módulo), y congelar el env en el import dejaba el singleton con el
# binario por defecto (spawns rotos en la suite completa; ver
# tests/backend/test_codex_env_lazy.py).
CODEX_BIN_PATH = "/usr/local/bin/codex"
CODEX_HOME_ROOT = "/tmp/codex"
CODEX_MAX_PROCESSES = 3
CODEX_SPAWN_WAIT_SECONDS = 60.0
CODEX_PER_PROCESS_MAX_CONCURRENCY = 5
CODEX_IDLE_TTL_SECONDS = 600.0
CODEX_REQUEST_TIMEOUT_SECONDS = 900.0
CODEX_TERMINATE_GRACE_SECONDS = 5.0


def _env_bin_path() -> str:
    return os.environ.get("CODEX_BIN_PATH") or CODEX_BIN_PATH


def _env_home_root() -> str:
    return os.environ.get("CODEX_HOME_ROOT") or CODEX_HOME_ROOT


def _env_max_processes() -> int:
    return int(os.environ.get("CODEX_MAX_PROCESSES", str(CODEX_MAX_PROCESSES)))


def _env_spawn_wait_seconds() -> float:
    return float(
        os.environ.get("CODEX_SPAWN_WAIT_SECONDS", str(CODEX_SPAWN_WAIT_SECONDS))
    )


def _env_per_process_max_concurrency() -> int:
    return int(
        os.environ.get(
            "CODEX_PER_PROCESS_MAX_CONCURRENCY",
            str(CODEX_PER_PROCESS_MAX_CONCURRENCY),
        )
    )


def _env_idle_ttl_seconds() -> float:
    return float(
        os.environ.get("CODEX_IDLE_TTL_SECONDS", str(CODEX_IDLE_TTL_SECONDS))
    )


def _env_request_timeout_seconds() -> float:
    return float(
        os.environ.get("CODEX_REQUEST_TIMEOUT_SECONDS", str(CODEX_REQUEST_TIMEOUT_SECONDS))
    )


def _env_terminate_grace_seconds() -> float:
    return float(
        os.environ.get(
            "CODEX_TERMINATE_GRACE_SECONDS", str(CODEX_TERMINATE_GRACE_SECONDS)
        )
    )

# Validación estricta del user_id antes de usarlo en paths (anti path traversal).
_VALID_USER_ID_RE = re.compile(r"[0-9a-fA-F-]{36}")

# Timeout explícito y corto del handshake `initialize` en el spawn (ronda 4,
# gate live): si el binario no completa el handshake, el spawn falla limpio
# vía el cleanup BaseException de `_spawn`. Los requests posteriores usan
# CODEX_REQUEST_TIMEOUT_SECONDS.
_HANDSHAKE_TIMEOUT_SECONDS = 30.0
_READER_DRAIN_TIMEOUT_SECONDS = 5.0


class CodexAppServerError(Exception):
    """Error base del gestor del app-server de Codex."""


class CodexSpawnError(CodexAppServerError):
    """No se pudo crear un proceso del app-server (capacidad o lanzamiento)."""


class CodexTimeoutError(CodexAppServerError):
    """Una petición JSON-RPC no recibió respuesta dentro del timeout."""


class CodexRequestError(CodexAppServerError):
    """El app-server respondió con un error object JSON-RPC.

    Expone `.code`, `.message` y `.data` (opacos al logging del backend).
    """

    def __init__(self, code: Any, message: str, data: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _preview(text: str, limit: int = 200) -> str:
    """Preview seguro y truncado para logs (nunca contenido íntegro)."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "..."


def _atomic_write(path: Path, content: str) -> None:
    """Escritura atómica (temp + rename) con modo 0600, para `auth.json`."""
    data = content.encode("utf-8")
    tmp_path = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass  # Windows: best-effort
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class CodexAppServer:
    """Un proceso `codex app-server --stdio` propiedad de un tenant."""

    def __init__(
        self,
        *,
        user_id: str,
        home_dir: Path,
        process: asyncio.subprocess.Process,
        manager: "CodexAppServerManager",
        stderr_file,
        per_process_max_concurrency: Optional[int] = None,
    ):
        # `None` = límite del env leído en el momento de uso (el default no se
        # congela en el import).
        if per_process_max_concurrency is None:
            per_process_max_concurrency = _env_per_process_max_concurrency()
        self.user_id = user_id
        self.home_dir = home_dir
        self._manager = manager
        self._process = process
        self._stderr_file = stderr_file
        self._pending: dict[int, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._concurrency_sem = asyncio.Semaphore(per_process_max_concurrency)
        self._active_requests = 0
        self._last_used = time.monotonic()
        self._closed = False
        self._reader_task: Optional[asyncio.Task] = None
        self._holds_global_slot = False

    @property
    def is_alive(self) -> bool:
        return not self._closed and self._process.returncode is None

    def touch(self) -> None:
        """Marca uso reciente (LRU)."""
        self._last_used = time.monotonic()

    async def request(
        self,
        method: str,
        params: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Envía una petición JSON-RPC y espera su respuesta por `id`.

        Raises:
            CodexTimeoutError: sin respuesta dentro de `timeout`.
            CodexRequestError: error object del server o canal cerrado.
        """
        # `None` = CODEX_REQUEST_TIMEOUT_SECONDS leído en el momento de uso
        # (el default no se congela en el import).
        if timeout is None:
            timeout = _env_request_timeout_seconds()
        self._active_requests += 1
        self._last_used = time.monotonic()
        try:
            async with self._concurrency_sem:
                if not self.is_alive:
                    raise CodexRequestError(
                        code="server_closed",
                        message="El proceso del app-server de Codex no está activo",
                        data=None,
                    )
                payload: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": next(self._ids),
                    "method": method,
                    "params": params if params is not None else {},
                }
                # Serializar antes de registrar el future: un payload no
                # serializable no debe dejar un future huérfano en `_pending`.
                line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
                loop = asyncio.get_running_loop()
                future: asyncio.Future = loop.create_future()
                self._pending[payload["id"]] = future
                try:
                    self._process.stdin.write(line)
                    await self._process.stdin.drain()
                    return await asyncio.wait_for(future, timeout)
                except asyncio.TimeoutError:
                    self._pending.pop(payload["id"], None)
                    raise CodexTimeoutError(
                        f"Timeout esperando respuesta del app-server de Codex "
                        f"(método '{method}' tras {timeout:g}s)"
                    ) from None
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as exc:
                    self._pending.pop(payload["id"], None)
                    raise CodexRequestError(
                        code="transport_closed",
                        message="El canal de comunicación con el app-server de Codex se cerró",
                        data=None,
                    ) from exc
                finally:
                    self._pending.pop(payload["id"], None)
        finally:
            self._active_requests -= 1

    async def _send_notification(self, method: str, params: Any = None) -> None:
        """Envía una notificación JSON-RPC (mensaje sin `id`) y drena la
        línea, SIN crear future ni esperar respuesta (el server no responde a
        notificaciones). Reutiliza el canal de `request` (stdin del proceso);
        usado por el handshake `initialized` del spawn."""
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else {},
        }
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self._process.stdin.write(line)
        await self._process.stdin.drain()

    async def _reader_loop(self) -> None:
        """Única reader-task del proceso: resuelve respuestas por `id` y
        despacha notificaciones (sin `id`) a los handlers del manager.

        Nada de este bucle bloquea el event loop (lecturas nativas de pipe).
        """
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except (ValueError, TypeError):
                    logger.warning(
                        "[codex] Línea JSON inválida del app-server (user %s): %s",
                        self.user_id[:8],
                        _preview(text),
                    )
                    continue
                if not isinstance(msg, dict):
                    continue
                msg_id = msg.get("id")
                if msg_id is not None:
                    future = self._pending.pop(msg_id, None)
                    if future is None or future.done():
                        continue
                    if isinstance(msg.get("error"), dict):
                        err = msg["error"]
                        future.set_exception(
                            CodexRequestError(
                                code=err.get("code"),
                                message=err.get("message")
                                or "Error del app-server de Codex",
                                data=err.get("data"),
                            )
                        )
                    else:
                        future.set_result(msg.get("result"))
                else:
                    method = msg.get("method")
                    if isinstance(method, str) and method:
                        self._manager._dispatch_notification(
                            self.user_id, method, msg.get("params")
                        )
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            logger.exception(
                "[codex] Reader del app-server terminó por error (user %s)",
                self.user_id[:8],
            )
        finally:
            self._closed = True
            for msg_id, future in list(self._pending.items()):
                if not future.done():
                    future.set_exception(
                        CodexRequestError(
                            code="server_closed",
                            message="El proceso del app-server de Codex se cerró "
                            "antes de responder",
                            data=None,
                        )
                    )
            self._pending.clear()
            self._manager._handle_process_exit(self)


class CodexAppServerManager:
    """Gestor de procesos del app-server: uno por tenant, con límites y ciclo
    de vida. Singleton de módulo: `codex_manager`.

    Los parámetros del constructor permiten configuración de tests sin tocar
    env; `None` = límite del env leído en el momento de uso (los valores por
    defecto del contrato nunca se congelan en el import).
    """

    def __init__(
        self,
        *,
        bin_path: Optional[str] = None,
        home_root: Optional[str] = None,
        max_processes: Optional[int] = None,
        spawn_wait_seconds: Optional[float] = None,
        per_process_max_concurrency: Optional[int] = None,
        idle_ttl_seconds: Optional[float] = None,
        terminate_grace_seconds: Optional[float] = None,
    ):
        # `None` = env leído en el momento de uso vía los resolvers
        # `_<x>_value()`: el singleton `codex_manager` se crea en el import,
        # posiblemente ANTES de que el entorno fije CODEX_* (imports eager de
        # agents/codex_client); resolver aquí congelaría el env de nuevo.
        self._bin_path = bin_path
        self._home_root = home_root
        self._max_processes = max_processes
        self._spawn_wait_seconds = spawn_wait_seconds
        self._per_process_max_concurrency = per_process_max_concurrency
        self._idle_ttl_seconds = idle_ttl_seconds
        self._terminate_grace_seconds = terminate_grace_seconds

        self._servers: dict[str, CodexAppServer] = {}
        self._spawn_locks: dict[str, asyncio.Lock] = {}
        # Locks de evicción por tenant: serializan cualquier evacuación
        # (LRU, evict, shutdown) con el acquire del mismo user_id durante
        # TODO el terminate/snapshot/cleanup, para que nunca haya dos ciclos
        # de vida sobre el mismo CODEX_HOME. Son locks hoja: quien los tiene
        # no adquiere ningún otro lock (ni siquiera otro de evicción), lo que
        # impide ciclos de locks entre acquires concurrentes.
        self._eviction_locks: dict[str, asyncio.Lock] = {}
        self._notification_handlers: dict[
            str, list[Callable[[str, Any], Awaitable[None]]]
        ] = {}
        self._eviction_task: Optional[asyncio.Task] = None
        # Semáforo global creado de forma perezosa en el primer acquire para
        # quedar ligado al event loop en curso.
        self._sem: Optional[asyncio.Semaphore] = None

    # --- Resolvers de configuración: valor explícito del constructor si lo
    # hay; si no, env leído en el momento de uso (nunca congelado en import).

    def _bin_path_value(self) -> str:
        return self._bin_path if self._bin_path is not None else _env_bin_path()

    def _home_root_value(self) -> Path:
        # Conversión a Path como hacía el constructor original: los llamadores
        # pueden pasar str o Path (los tests también parchean `_home_root` con
        # objetos path-like de pytest).
        if self._home_root is not None:
            return Path(self._home_root)
        return Path(_env_home_root())

    def _max_processes_value(self) -> int:
        return (
            self._max_processes if self._max_processes is not None else _env_max_processes()
        )

    def _spawn_wait_seconds_value(self) -> float:
        return (
            self._spawn_wait_seconds
            if self._spawn_wait_seconds is not None
            else _env_spawn_wait_seconds()
        )

    def _per_process_max_concurrency_value(self) -> int:
        return (
            self._per_process_max_concurrency
            if self._per_process_max_concurrency is not None
            else _env_per_process_max_concurrency()
        )

    def _idle_ttl_seconds_value(self) -> float:
        return (
            self._idle_ttl_seconds
            if self._idle_ttl_seconds is not None
            else _env_idle_ttl_seconds()
        )

    def _terminate_grace_seconds_value(self) -> float:
        return (
            self._terminate_grace_seconds
            if self._terminate_grace_seconds is not None
            else _env_terminate_grace_seconds()
        )

    @property
    def active_count(self) -> int:
        """Procesos vivos actualmente gestionados."""
        return sum(1 for server in self._servers.values() if server.is_alive)

    def add_notification_handler(
        self, method: str, handler: Callable[[str, Any], Awaitable[None]]
    ) -> None:
        """Registra un handler `handler(user_id, params)` para notificaciones
        JSON-RPC (mensajes sin `id`) del método indicado."""
        self._notification_handlers.setdefault(method, []).append(handler)

    async def acquire(self, user_id: str) -> CodexAppServer:
        """Devuelve el proceso vivo del tenant, creándolo si hace falta.

        Un proceso vivo se devuelve sin re-spawn. La creación espera el
        semáforo global `CODEX_MAX_PROCESSES` durante `CODEX_SPAWN_WAIT_SECONDS`;
        si se agota, evicta LRU un proceso inactivo antes de lanzar
        `CodexSpawnError`.

        La creación queda serializada con cualquier evacuación del mismo
        tenant (LRU o `evict`) mediante su lock de evicción, mantenido por
        el evacuador durante todo el terminate/snapshot/cleanup: nunca hay
        dos ciclos de vida sobre el mismo `CODEX_HOME`.
        """
        if not _VALID_USER_ID_RE.fullmatch(user_id):
            raise CodexAppServerError(
                f"user_id inválido para Codex (debe ser un UUID): {user_id[:8]}..."
            )
        self._ensure_eviction_loop()
        async with self._user_lock(user_id):
            server = self._servers.get(user_id)
            if server is not None and server.is_alive:
                server.touch()
                return server
            # Slot global primero: agotar la espera puede requerir evicción
            # LRU de OTRO tenant (que toma el lock de evicción de ese
            # tenant). Aquí no se sostiene el lock de evicción propio: los
            # locks de evicción nunca se anidan entre sí (evita ciclos de
            # locks entre acquires concurrentes).
            if not await self._wait_global_slot():
                raise CodexSpawnError(
                    f"No se pudo crear el proceso Codex: capacidad máxima "
                    f"alcanzada ({self._max_processes_value()} procesos)"
                )
            try:
                # Serializa con cualquier evacuación en vuelo de ESTE tenant:
                # el lock se mantiene durante todo el spawn (restauración +
                # creación del proceso). El try cubre también la espera del
                # lock para que una cancelación ahí no fugue el slot global.
                async with self._eviction_lock(user_id):
                    server = await self._spawn(user_id)
            except BaseException as exc:
                # El spawn falló o fue cancelado antes de registrar el
                # server: liberar el slot global adquirido en
                # _wait_global_slot.
                if self._sem is not None:
                    self._sem.release()
                if isinstance(exc, CodexAppServerError):
                    raise
                if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                    raise
                raise CodexSpawnError(
                    f"No se pudo lanzar el proceso Codex: {type(exc).__name__}"
                ) from exc
            self._servers[user_id] = server
            server._holds_global_slot = True
            return server

    async def evict(self, user_id: str) -> None:
        """Termina el proceso del tenant, re-sincroniza `auth.json` cifrado
        (si `status="linked"`), borra `CODEX_HOME` y libera los semáforos.
        Idempotente; los fallos de Supabase se loguean sin datos sensibles.

        Mantiene el lock de evicción del tenant durante todo el
        terminate/snapshot/cleanup, serializándose con un acquire
        concurrente del mismo `user_id` (nunca dos ciclos de vida sobre el
        mismo `CODEX_HOME`) y con la evicción LRU (verificación de
        identidad bajo el lock).
        """
        if not _VALID_USER_ID_RE.fullmatch(user_id):
            return
        async with self._user_lock(user_id):
            server = self._servers.get(user_id)
            if server is None:
                return
            async with self._eviction_lock(user_id):
                # La evicción LRU pudo reclamar el server mientras se
                # esperaba el lock: verificación de identidad.
                if self._servers.get(user_id) is not server:
                    return
                self._servers.pop(user_id, None)
                await self._terminate_and_cleanup(server)

    async def shutdown(self) -> None:
        """Cierra todos los procesos y detiene el loop de evicción.
        Idempotente y nunca lanza excepción."""
        try:
            if self._eviction_task is not None:
                self._eviction_task.cancel()
                try:
                    await self._eviction_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._eviction_task = None
            for user_id in list(self._servers.keys()):
                try:
                    await self.evict(user_id)
                except Exception as exc:
                    logger.warning(
                        "[codex] shutdown: no se pudo evictar a user %s: %s",
                        user_id[:8],
                        type(exc).__name__,
                    )
        except Exception as exc:
            logger.warning("[codex] shutdown: %s", type(exc).__name__)

    # ------------------------------------------------------------------ #

    def _user_lock(self, user_id: str) -> asyncio.Lock:
        lock = self._spawn_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._spawn_locks[user_id] = lock
        return lock

    def _eviction_lock(self, user_id: str) -> asyncio.Lock:
        lock = self._eviction_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._eviction_locks[user_id] = lock
        return lock

    def _ensure_eviction_loop(self) -> None:
        if self._eviction_task is None or self._eviction_task.done():
            self._eviction_task = asyncio.create_task(self._eviction_loop())

    async def _wait_global_slot(self) -> bool:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._max_processes_value())
        try:
            await asyncio.wait_for(
                self._sem.acquire(), timeout=self._spawn_wait_seconds_value()
            )
            return True
        except asyncio.TimeoutError:
            pass
        # Capacidad agotada: evicción LRU de procesos inactivos antes de
        # rendirse. La evacuación toma el lock de evicción del tenant
        # objetivo y lo mantiene durante TODO el terminate/snapshot/cleanup;
        # `acquire` de ese mismo tenant espera ese lock antes de tocar
        # CODEX_HOME (nunca dos ciclos de vida sobre el mismo home). El lock
        # de evicción es hoja (no se anida con otros), lo que evita ciclos
        # de locks entre acquires concurrentes.
        if await self._evict_lru_idle():
            try:
                await asyncio.wait_for(
                    self._sem.acquire(), timeout=self._spawn_wait_seconds_value()
                )
                return True
            except asyncio.TimeoutError:
                pass
        return False

    async def _evict_lru_idle(self) -> bool:
        candidates = [
            s for s in self._servers.values() if s.is_alive and s._active_requests == 0
        ]
        if not candidates:
            return False
        oldest = min(candidates, key=lambda s: s._last_used)
        # Lock de evicción del tenant objetivo, mantenido durante TODO el
        # terminate/snapshot/cleanup: un acquire concurrente del mismo
        # user_id espera este lock antes de tocar CODEX_HOME (F01). Es un
        # lock hoja: quien lo tiene no adquiere ningún otro lock, por lo que
        # no puede formarse un ciclo de locks entre acquires concurrentes.
        async with self._eviction_lock(oldest.user_id):
            # Verificación de identidad bajo el lock: otro camino de
            # evacuación (evict o LRU) pudo reclamar el server mientras se
            # esperaba.
            if self._servers.get(oldest.user_id) is not oldest:
                return False
            self._servers.pop(oldest.user_id, None)
            logger.info(
                "[codex] Capacidad agotada: evacuando proceso inactivo de user %s",
                oldest.user_id[:8],
            )
            await self._terminate_and_cleanup(oldest)
            return True

    async def _spawn(self, user_id: str) -> CodexAppServer:
        home = self._home_root_value() / user_id
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            home.chmod(0o700)
        except OSError:
            pass  # Windows: best-effort
        server: Optional[CodexAppServer] = None
        stderr_file = None
        try:
            await self._restore_auth_json(user_id, home)
            stderr_path = home / "app-server.stderr.log"
            stderr_file = open(stderr_path, "wb")  # truncado por spawn
            env = dict(os.environ)
            env["CODEX_HOME"] = str(home)
            process = await asyncio.create_subprocess_exec(
                *self._build_argv(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr_file,
                env=env,
            )
            server = CodexAppServer(
                user_id=user_id,
                home_dir=home,
                process=process,
                manager=self,
                stderr_file=stderr_file,
                per_process_max_concurrency=self._per_process_max_concurrency_value(),
            )
            stderr_file = None  # pasa a ser propiedad del server
            server._reader_task = asyncio.create_task(server._reader_loop())
            # Handshake JSON-RPC de apertura (app-server real, verificado
            # contra codex 0.145.0 en el gate live): exige `initialize` (con
            # clientInfo) y la notificación `initialized` antes de CUALQUIER
            # request; sin ellos rechaza todo con `CodexRequestError: Not
            # initialized`. `acquire` devuelve así un server listo: el lock
            # por tenant cubre todo el spawn, ningún otro request puede
            # intercalarse. Si el binario no completa el handshake, el spawn
            # falla y el `except BaseException` de abajo limpia
            # proceso/reader/home.
            await server.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "explainer",
                        "title": "Explainer",
                        "version": "0.1.0",
                    }
                },
                timeout=_HANDSHAKE_TIMEOUT_SECONDS,
            )
            await server._send_notification("initialized", {})
            return server
        except BaseException:
            # Limpieza también ante cancelación de la tarea llamante: nunca
            # dejar procesos, ficheros o homes huérfanos.
            if server is not None:
                try:
                    server._process.kill()
                except ProcessLookupError:
                    pass
                if server._reader_task is not None:
                    server._reader_task.cancel()
            if stderr_file is not None:
                try:
                    stderr_file.close()
                except OSError:
                    pass
            shutil.rmtree(home, ignore_errors=True)
            raise

    def _build_argv(self) -> list[str]:
        binary = self._bin_path_value()
        if binary.lower().endswith(".py"):
            # Fixture de tests: un script Python no es ejecutable directamente
            # en Windows (WinError 193); se invoca con el intérprete en curso.
            # En producción la ruta es un binario nativo y este branch nunca
            # se toma.
            return [sys.executable, binary, "app-server", "--stdio"]
        return [binary, "app-server", "--stdio"]

    async def _restore_auth_json(self, user_id: str, home: Path) -> None:
        """Restaura `auth.json` desde el blob cifrado cuando `status="linked"`.
        Best-effort: un fallo (Supabase caído o blob corrupto) no impide el
        spawn; el proceso arranca sin sesión y el flujo de vínculo la repone."""
        try:
            from backend import supabase_data
            from backend.crypto import decrypt_user_api_key

            row = await asyncio.to_thread(
                supabase_data.get_user_provider_connection, user_id
            )
            if not row or row.get("status") != "linked":
                return
            encrypted = row.get("encrypted_credentials")
            if not encrypted:
                return
            auth_json = decrypt_user_api_key(encrypted, user_id)
            _atomic_write(home / "auth.json", auth_json)
        except Exception as exc:
            logger.warning(
                "[codex] No se pudo restaurar auth.json para user %s (best-effort): %s",
                user_id[:8],
                type(exc).__name__,
            )

    async def _terminate_and_cleanup(self, server: CodexAppServer) -> None:
        """Termina el proceso, drena la reader-task, snapshot y limpia el home.

        Solo debe llamarse sosteniendo el lock de evicción del tenant de
        `server` (desde `evict` o `_evict_lru_idle`): el acquire del mismo
        user_id espera ese lock y así nunca hay dos ciclos de vida (snapshot/
        borrado vs restauración/spawn) sobre el mismo CODEX_HOME.
        """
        try:
            try:
                await self._terminate_process(server)
            except Exception as exc:
                logger.warning(
                    "[codex] Error terminando proceso de user %s: %s",
                    server.user_id[:8],
                    type(exc).__name__,
                )
            await self._await_reader(server)
            await self._snapshot_auth(server)
        finally:
            # Liberación y limpieza local garantizadas también si la tarea
            # llamante es cancelada a mitad de la evacuación.
            self._release_global_slot(server)
            self._cleanup_home(server)
            self._close_io(server)

    async def _terminate_process(self, server: CodexAppServer) -> None:
        proc = server._process
        if proc.returncode is not None:
            return
        try:
            proc.terminate()  # SIGTERM (TerminateProcess en Windows)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(
                proc.wait(), timeout=self._terminate_grace_seconds_value()
            )
            return
        except asyncio.TimeoutError:
            pass
        try:
            proc.kill()  # SIGKILL tras grace
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(
                proc.wait(), timeout=self._terminate_grace_seconds_value()
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[codex] Proceso de user %s no terminó tras SIGKILL",
                server.user_id[:8],
            )

    async def _await_reader(self, server: CodexAppServer) -> None:
        task = server._reader_task
        if task is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(task), timeout=_READER_DRAIN_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            pass

    async def _snapshot_auth(self, server: CodexAppServer) -> None:
        """Re-sincroniza `auth.json` cifrado a `user_provider_connections` si
        `status="linked"`. Best-effort: nunca rompe evict/shutdown y los fallos
        se loguean sin datos sensibles."""
        try:
            from backend import supabase_data
            from backend.crypto import encrypt_user_api_key

            row = await asyncio.to_thread(
                supabase_data.get_user_provider_connection, server.user_id
            )
            if not row or row.get("status") != "linked":
                return
            auth_path = server.home_dir / "auth.json"
            if not auth_path.exists():
                return
            content = await asyncio.to_thread(_read_text, auth_path)
            encrypted = encrypt_user_api_key(content, server.user_id)
            await asyncio.to_thread(
                supabase_data.upsert_user_provider_connection,
                server.user_id,
                status="linked",
                encrypted_credentials=encrypted,
                plan_type=row.get("plan_type"),
            )
        except Exception as exc:
            logger.warning(
                "[codex] Snapshot de auth.json falló para user %s (best-effort): %s",
                server.user_id[:8],
                type(exc).__name__,
            )

    def _release_global_slot(self, server: CodexAppServer) -> None:
        if server._holds_global_slot and self._sem is not None:
            server._holds_global_slot = False
            self._sem.release()

    def _cleanup_home(self, server: CodexAppServer) -> None:
        try:
            shutil.rmtree(server.home_dir, ignore_errors=True)
        except Exception as exc:
            logger.warning(
                "[codex] No se pudo borrar CODEX_HOME de user %s: %s",
                server.user_id[:8],
                type(exc).__name__,
            )

    def _close_io(self, server: CodexAppServer) -> None:
        server._closed = True
        if server._stderr_file is not None:
            try:
                server._stderr_file.close()
            except OSError:
                pass
            server._stderr_file = None

    def _handle_process_exit(self, server: CodexAppServer) -> None:
        """Finalizador de la reader-task: el proceso murió solo (crash/EOF).
        Quita el registro y libera el slot global; idempotente respecto a
        evict() (los checks y las liberaciones son síncronos en el loop)."""
        if self._servers.get(server.user_id) is server:
            self._servers.pop(server.user_id, None)
        self._release_global_slot(server)
        self._close_io(server)
        logger.info(
            "[codex] Proceso del app-server terminó (user %s, exit %s)",
            server.user_id[:8],
            server._process.returncode,
        )

    def _dispatch_notification(self, user_id: str, method: str, params: Any) -> None:
        handlers = self._notification_handlers.get(method)
        if not handlers:
            return
        for handler in handlers:
            asyncio.create_task(
                self._run_notification_handler(handler, user_id, method, params)
            )

    async def _run_notification_handler(
        self, handler: Callable[[str, Any], Awaitable[None]],
        user_id: str, method: str, params: Any,
    ) -> None:
        try:
            result = handler(user_id, params)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "[codex] Handler de notificación '%s' falló (user %s): %s",
                method,
                user_id[:8],
                type(exc).__name__,
            )

    async def _eviction_loop(self) -> None:
        """Loop de evicción por inactividad: expulsa procesos sin uso durante
        `CODEX_IDLE_TTL_SECONDS`. Iniciado en el primer acquire."""
        try:
            while True:
                # TTL leído en el momento de uso; ticks acotados (≤1s) para
                # que la evicción no se retrase más de un segundo tras
                # cumplirse el TTL; nunca un bucle ocupado.
                idle_ttl = self._idle_ttl_seconds_value()
                tick = max(0.05, min(idle_ttl, 1.0))
                await asyncio.sleep(tick)
                now = time.monotonic()
                for user_id, server in list(self._servers.items()):
                    if (
                        server.is_alive
                        and server._active_requests == 0
                        and now - server._last_used >= idle_ttl
                    ):
                        logger.info(
                            "[codex] Evicción por inactividad de user %s",
                            user_id[:8],
                        )
                        try:
                            await self.evict(user_id)
                        except Exception as exc:
                            logger.warning(
                                "[codex] Evicción por inactividad falló (user %s): %s",
                                user_id[:8],
                                type(exc).__name__,
                            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[codex] Loop de evicción terminó por error")


# Singleton de módulo (patrón de backend/sse_manager.py).
codex_manager = CodexAppServerManager()

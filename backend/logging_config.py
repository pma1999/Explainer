"""Configuración centralizada de logging para el backend.

Proporciona:
- Formato JSON para integración con Koyeb
- Contexto de traceo (project_id, user_id, part_id)
- Timestamps con zona horaria UTC
- Manejo seguro de información sensible
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ContextVars para propagar información de trazabilidad sin modificar firmas
project_id_var: ContextVar[str | None] = ContextVar("project_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
part_id_var: ContextVar[int | None] = ContextVar("part_id", default=None)
agent_name_var: ContextVar[str | None] = ContextVar("agent_name", default=None)


class JSONFormatter(logging.Formatter):
    """Formateador JSON para logs estructurados en Koyeb."""

    def format(self, record: logging.LogRecord) -> str:
        """Formatea el registro como JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Añadir contexto de trazabilidad si está disponible
        context = {}
        if project_id := project_id_var.get():
            context["project_id"] = project_id[:12] if len(project_id) > 12 else project_id
        if user_id := user_id_var.get():
            context["user_id"] = user_id[:8] + "..." if len(user_id) > 8 else user_id
        if part_id := part_id_var.get():
            context["part_id"] = part_id
        if agent_name := agent_name_var.get():
            context["agent"] = agent_name

        if context:
            log_data["context"] = context

        # Añadir metadata adicional si existe
        if hasattr(record, "metadata") and record.metadata:
            log_data["metadata"] = record.metadata

        # Añadir información de excepción si existe
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Añadir campos extra del record
        for key in ["duration_ms", "tokens", "model", "status_code", "attempt", "operation"]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        return json.dumps(log_data, ensure_ascii=False, default=str)


# Atributos estándar de LogRecord: todo lo demás en record.__dict__ es un campo `extra`.
_STANDARD_LOGRECORD_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message", "asctime",
    }
)


class CompleteJSONFormatter(logging.Formatter):
    """Formateador para el log de ARCHIVO: vuelca TODO el LogRecord sin descartar nada.

    A diferencia de JSONFormatter/ColoredFormatter (que solo conservan unos pocos campos
    `extra` hardcodeados), este formateador serializa el mensaje, el contexto de traceo,
    la excepción/traceback completos y TODOS los campos `extra` pasados a cada log.
    """

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
        }

        context: dict[str, Any] = {}
        if project_id := project_id_var.get():
            context["project_id"] = project_id
        if user_id := user_id_var.get():
            context["user_id"] = user_id[:8] + "..." if len(user_id) > 8 else user_id
        if (part_id := part_id_var.get()) is not None:
            context["part_id"] = part_id
        if agent_name := agent_name_var.get():
            context["agent"] = agent_name
        if context:
            data["context"] = context

        # TODOS los campos extra (incluido `metadata`): nada se pierde.
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOGRECORD_ATTRS and not key.startswith("_")
        }
        if extras:
            data["extra"] = extras

        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            data["stack"] = self.formatStack(record.stack_info)

        return json.dumps(data, ensure_ascii=False, default=str)


class ColoredFormatter(logging.Formatter):
    """Formateador con colores para desarrollo local."""

    COLORS = {
        "DEBUG": "\033[36m",      # Cyan
        "INFO": "\033[32m",       # Green
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "CRITICAL": "\033[35m",   # Magenta
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Formatea con colores."""
        color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
        reset = self.COLORS["RESET"]

        # Construir el mensaje base
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        level = f"{color}{record.levelname}{reset}"

        # Contexto
        context_parts = []
        if project_id := project_id_var.get():
            pid = project_id[:8] if len(project_id) > 8 else project_id
            context_parts.append(f"pid={pid}")
        if part_id := part_id_var.get():
            context_parts.append(f"part={part_id}")
        if agent_name := agent_name_var.get():
            context_parts.append(f"agent={agent_name}")

        context = f" [{' '.join(context_parts)}]" if context_parts else ""

        # Metadata
        meta_parts = []
        if hasattr(record, "duration_ms"):
            meta_parts.append(f"{record.duration_ms}ms")
        if hasattr(record, "tokens"):
            meta_parts.append(f"{record.tokens}tok")
        if hasattr(record, "attempt"):
            meta_parts.append(f"attempt={record.attempt}")

        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""

        return f"{timestamp} | {level} | {record.name}{context} | {record.getMessage()}{meta}"


# Ruta del log de archivo de la sesión actual (se rellena en setup_logging).
_FILE_LOG_PATH: str | None = None


def get_file_log_path() -> str | None:
    """Ruta absoluta del archivo de log completo de esta ejecución, si está activo."""
    return _FILE_LOG_PATH


def _truthy_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_complete_file_handler() -> logging.Handler | None:
    """Crea un handler de archivo a DEBUG que vuelca TODOS los campos de cada log.

    Activo por defecto fuera de producción; controlable con EXPLAINER_FILE_LOG=0/1 y
    EXPLAINER_LOG_DIR. El nombre incluye PID y timestamp para no pisar ejecuciones previas.
    """
    global _FILE_LOG_PATH
    log_dir = os.environ.get("EXPLAINER_LOG_DIR", "").strip() or os.path.join(os.getcwd(), "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(log_dir, f"explainer_{stamp}_pid{os.getpid()}.log")
        # delay=True: no abre el archivo hasta el primer log, evita duplicados en reload.
        file_handler = logging.FileHandler(path, mode="a", encoding="utf-8", delay=True)
        file_handler.setFormatter(CompleteJSONFormatter())
        file_handler.setLevel(logging.DEBUG)
        _FILE_LOG_PATH = path
        return file_handler
    except OSError:
        _FILE_LOG_PATH = None
        return None


class _MaxLevelFilter(logging.Filter):
    """Permite pasar solo registros por debajo de un nivel dado (para la consola)."""

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self._max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self._max_level


def setup_logging() -> None:
    """Configura el logging global para la aplicación."""
    # Detectar si estamos en producción (Koyeb)
    is_production = os.environ.get("ENVIRONMENT") == "production"

    # Configurar el handler de consola
    handler = logging.StreamHandler(sys.stdout)

    if is_production:
        # En producción usar JSON
        handler.setFormatter(JSONFormatter())
        console_level = logging.INFO
    else:
        # En desarrollo usar formato legible con colores
        handler.setFormatter(ColoredFormatter())
        console_level = logging.DEBUG
    handler.setLevel(console_level)

    # El root debe estar al nivel más bajo que cualquier handler quiera capturar.
    enable_file_log = _truthy_env("EXPLAINER_FILE_LOG", default=not is_production)
    file_handler = _build_complete_file_handler() if enable_file_log else None
    root_level = logging.DEBUG if file_handler is not None else console_level

    # Configurar el logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    if file_handler is not None:
        root_logger.addHandler(file_handler)

    # Loggers de terceros muy verbosos (frames HTTP/2, parser de uploads, etc.). Su DEBUG
    # es ruido de bajo nivel sin valor para depurar el pipeline y enterraría el log útil,
    # así que se quedan en WARNING en AMBOS destinos. Todo nuestro backend.* va a DEBUG al
    # archivo. httpx se deja en INFO para conservar la línea de cada request HTTP.
    for name in ("urllib3", "google", "httpcore", "hpack", "h2", "h11",
                 "watchfiles", "multipart", "charset_normalizer", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)

    # Logger propio
    logger = logging.getLogger("backend.logging_config")
    if is_production:
        logger.info("Logging configurado en modo PRODUCCIÓN (JSON)")
    else:
        logger.debug("Logging configurado en modo DESARROLLO (colores)")
    if _FILE_LOG_PATH:
        # Mensaje visible en consola con la ruta del log completo.
        logger.warning("Log completo de esta ejecución: %s", _FILE_LOG_PATH)


def set_context(
    project_id: str | None = None,
    user_id: str | None = None,
    part_id: int | None = None,
    agent_name: str | None = None,
) -> None:
    """Establece el contexto de trazabilidad para los logs.

    Args:
        project_id: ID del proyecto
        user_id: ID del usuario
        part_id: ID de la parte siendo procesada
        agent_name: Nombre del agente ejecutándose
    """
    if project_id is not None:
        project_id_var.set(project_id)
    if user_id is not None:
        user_id_var.set(user_id)
    if part_id is not None:
        part_id_var.set(part_id)
    if agent_name is not None:
        agent_name_var.set(agent_name)


def clear_context() -> None:
    """Limpia todo el contexto de trazabilidad."""
    project_id_var.set(None)
    user_id_var.set(None)
    part_id_var.set(None)
    agent_name_var.set(None)


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger configurado.

    Args:
        name: Nombre del logger (generalmente __name__)

    Returns:
        Logger configurado
    """
    return logging.getLogger(name)


class LogContext:
    """Context manager para establecer contexto de logging temporalmente."""

    def __init__(
        self,
        project_id: str | None = None,
        user_id: str | None = None,
        part_id: int | None = None,
        agent_name: str | None = None,
    ):
        self.project_id = project_id
        self.user_id = user_id
        self.part_id = part_id
        self.agent_name = agent_name
        self.tokens: list = []

    def __enter__(self) -> LogContext:
        self.tokens = [
            project_id_var.set(self.project_id) if self.project_id else None,
            user_id_var.set(self.user_id) if self.user_id else None,
            part_id_var.set(self.part_id) if self.part_id else None,
            agent_name_var.set(self.agent_name) if self.agent_name else None,
        ]
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Restaurar valores anteriores usando reset()
        if self.tokens[0] is not None:
            project_id_var.reset(self.tokens[0])
        if self.tokens[1] is not None:
            user_id_var.reset(self.tokens[1])
        if self.tokens[2] is not None:
            part_id_var.reset(self.tokens[2])
        if self.tokens[3] is not None:
            agent_name_var.reset(self.tokens[3])


def log_with_metadata(
    logger: logging.Logger,
    level: int,
    message: str,
    **kwargs: Any,
) -> None:
    """Log con metadata adicional.

    Args:
        logger: Logger a usar
        level: Nivel de log (logging.INFO, etc.)
        message: Mensaje
        **kwargs: Metadata adicional (duration_ms, tokens, etc.)
    """
    extra = {"metadata": kwargs} if kwargs else {}
    logger.log(level, message, extra=extra)

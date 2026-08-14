#!/usr/bin/env python3
"""Fake `codex app-server --stdio` para tests (T02).

Autoridad del wire-format JSONL en tests: lee requests de stdin y escribe
respuestas JSONL en stdout, con correlación por `id`. Escenario seleccionable
por env `FAKE_CODEX_SCENARIO`:

- `echo` (default): responde `{"ok": true, "method", "params"}` a todo request.
- `login_completes`: responde a `account/login/start` con device-code y, tras
  `FAKE_CODEX_LOGIN_DELAY_SECONDS`, emite la notificación
  `account/login/completed`.
- `login_pending`: responde a `account/login/start` sin notificación posterior.
- `logout_ok`: responde `{"ok": true}` a `account/logout`.
- `account_read_plan`: responde a `account/read` con `planType` (y email).
- `scripted_turn`: ciclo de turno STREAMING verificado en source (receta
  `integration-codex-appserver.md` §Turn lifecycle verification, commit
  `08e482e2` / `rust-v0.147.0-alpha.9`). `thread/start` responde
  `{"thread": {"id": "thread_<n>"}}`; `turn/start` responde inmediatamente
  `{"turn": {"id": "turn_<n>", "status": "inProgress", "items": []}}` SIN texto
  ni usage, y a continuación emite en este orden exacto: `turn/started`,
  `item/started`, `item/agentMessage/delta` (un delta con el texto completo),
  `item/completed` (item `agentMessage` con el texto final), opcionalmente
  `thread/tokenUsage/updated`, y `turn/completed` (`status: "completed"`).
  El texto final es el contenido de `FAKE_CODEX_TURN_OUTPUT_FILE` leído como
  TEXTO PLANO UTF-8 (nunca `json.load`); el turno N lee `<FILE>.<N>` si existe
  y si no el base. Fichero de salida ausente/ilegible → error object
  `TurnOutputReadError` en la response de `turn/start` (error de aceptación).
  El usage (si existe `FAKE_CODEX_TOKEN_USAGE_FILE` o `<FILE>.<N>`) se emite
  como `tokenUsage` con el shape real `{total, last, modelContextWindow}` y
  breakdowns de 6 campos enteros; sin fichero de usage NO se emite la
  notificación. `threadId` de las notificaciones: `params.threadId` o
  `params.threadID` del request de `turn/start`; si ninguno existe, el del
  `thread/start` previo (defensivo).
- `usage_limit`: cuota descubierta DURANTE la ejecución (distinta del error de
  aceptación). `thread/start` responde normal; `turn/start` responde
  `inProgress` y después: notificación `error` con
  `codexErrorInfo: "usageLimitExceeded"` y `turn/completed` con
  `status: "failed"` y el mismo error en `turn.error`. Cualquier OTRO método
  devuelve error object `UsageLimitExceeded` en la response (conserva el test
  de T04 "logout fallido no bloquea el borrado").
- `stalled_turn`: `thread/start` normal; `turn/start` responde `inProgress` y
  NO emite ninguna notificación posterior (el cliente debe caer en timeout
  esperando `turn/completed`).
- `scripted_error`: error object en la response de cualquier request, con
  `code` desde `FAKE_CODEX_ERROR_CODE` (modela el error de aceptación de
  `turn/start`, que sí puede venir en la response).
- `invalid_json`: emite una línea JSON inválida y luego responde normalmente
  (el reader debe tolerar la línea basura).
- `slow_turn`: responde tras `FAKE_CODEX_SLOW_DELAY_SECONDS` (timeout de RPC).

Handshake de apertura (ronda 4, gate live): el app-server real exige
`initialize` + notificación `initialized` al abrir la conexión y rechaza
CUALQUIER request anterior con `CodexRequestError: Not initialized`. El fake
responde a `initialize` con un result mínimo FUERA del escenario (el escenario
modela métodos de aplicación, no el transporte: `slow_turn`/`scripted_error`/
`invalid_json` no deben romper el handshake) y NO responde a la notificación
`initialized` (mensajes sin `id` se ignoran, igual que el real). Opcionalmente
apéndice cada mensaje recibido a `FAKE_CODEX_TRACE_FILE` (JSONL) para que los
tests verifiquen el orden del handshake.

Invocation: `fake_codex_app_server.py app-server --stdio` (los args se ignoran,
igual que el binario real). Escribe un banner en stderr al arrancar para poder
verificar el volcado a `<CODEX_HOME>/app-server.stderr.log`.

Read-only para el resto de tareas del bundle: si falta un escenario, se reporta
al orquestador; no se edita en paralelo.
"""

from __future__ import annotations

import json
import os
import sys
import time

SCENARIO = os.environ.get("FAKE_CODEX_SCENARIO", "echo")
LOGIN_DELAY_SECONDS = float(os.environ.get("FAKE_CODEX_LOGIN_DELAY_SECONDS", "0.1"))
SLOW_DELAY_SECONDS = float(os.environ.get("FAKE_CODEX_SLOW_DELAY_SECONDS", "30"))
TURN_OUTPUT_FILE = os.environ.get("FAKE_CODEX_TURN_OUTPUT_FILE", "")
TOKEN_USAGE_FILE = os.environ.get("FAKE_CODEX_TOKEN_USAGE_FILE", "")
ERROR_CODE = os.environ.get("FAKE_CODEX_ERROR_CODE", "InternalError")
TRACE_FILE = os.environ.get("FAKE_CODEX_TRACE_FILE", "")

_FAKE_LOGIN_ID = "fake-login-1"
_FAKE_PENDING_LOGIN_ID = "fake-login-pending"
_QUOTA_MESSAGE = "Usage limit exceeded for this ChatGPT plan"

# Error de cuota: mismo shape para la notificación `error` y para
# `turn.error` del `turn/completed` fallido (receta §Turn lifecycle 5).
_USAGE_LIMIT_ERROR = {
    "message": _QUOTA_MESSAGE,
    "codexErrorInfo": "usageLimitExceeded",
    "additionalDetails": None,
}


def _write(obj: dict) -> None:
    """Escribe una línea JSONL en stdout usando el buffer binario (sin
    traducción de saltos de línea, independiente de la plataforma)."""
    sys.stdout.buffer.write((json.dumps(obj) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _result(request_id: int, result: dict) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: int, code: str, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message, "data": None}})


def _notification(method: str, params: dict) -> None:
    _write({"jsonrpc": "2.0", "method": method, "params": params})


def _trace_received(msg: dict) -> None:
    """Apéndice opcional de los mensajes recibidos (JSONL) a
    `FAKE_CODEX_TRACE_FILE`, en orden de lectura. Solo para tests: verificar
    que el primer mensaje del cliente es `initialize` (ronda 4)."""
    if not TRACE_FILE:
        return
    with open(TRACE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg) + "\n")


def _per_turn_path(base: str, turn_number: int) -> str | None:
    """Convención por turno: `<base>.<N>` si existe; si no, el base."""
    if not base:
        return None
    numbered = f"{base}.{turn_number}"
    if os.path.exists(numbered):
        return numbered
    return base


class _ScenarioHandler:
    """Estado por proceso: contadores de thread/turn/item y último thread id.

    El fake procesa los requests secuencialmente desde stdin; los contadores
    arrancan en 1 por proceso (como en el app-server real: ids opacos por
    proceso) y permiten convenciones deterministas multi-turno (`<FILE>.1`,
    `<FILE>.2`, ...).
    """

    def __init__(self) -> None:
        self._thread_counter = 0
        self._turn_counter = 0
        self._item_counter = 0
        self._last_thread_id: str | None = None

    # --- ids y correlación ---------------------------------------------- #

    def _next_thread_id(self) -> str:
        self._thread_counter += 1
        thread_id = f"thread_{self._thread_counter}"
        self._last_thread_id = thread_id
        return thread_id

    def _next_turn_id(self) -> str:
        self._turn_counter += 1
        return f"turn_{self._turn_counter}"

    def _next_item_id(self) -> str:
        self._item_counter += 1
        return f"item_{self._item_counter}"

    def _thread_id_for(self, params: dict) -> str:
        """`threadId` de las notificaciones: el del request de `turn/start`
        (camelCase o `threadID` legacy) o, defensivo, el del `thread/start`
        previo (el app-server real los correlaciona por id, no por nombre)."""
        return (
            params.get("threadId")
            or params.get("threadID")
            or self._last_thread_id
            or f"thread_{self._thread_counter or 1}"
        )

    # --- fuentes de datos del turno ------------------------------------- #

    def _read_turn_output(self) -> str:
        """Texto plano UTF-8 del turno en curso (nunca `json.load`)."""
        path = _per_turn_path(TURN_OUTPUT_FILE, self._turn_counter)
        if not path:
            raise OSError("FAKE_CODEX_TURN_OUTPUT_FILE not set")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _read_token_usage(self) -> dict | None:
        """Contenido de `tokenUsage` del turno en curso, o None sin fichero."""
        path = _per_turn_path(TOKEN_USAGE_FILE, self._turn_counter)
        if not path:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # --- escenarios ------------------------------------------------------ #

    def handle(self, request_id: int, method: str, params: dict) -> None:
        if SCENARIO == "login_completes" and method == "account/login/start":
            _result(request_id, {
                "verificationUrl": "https://chatgpt.com/device/verify",
                "userCode": "ABCD-EFGH",
                "loginId": _FAKE_LOGIN_ID,
                "expiresIn": 600,
            })
            time.sleep(LOGIN_DELAY_SECONDS)
            _notification("account/login/completed", {
                "loginId": _FAKE_LOGIN_ID,
                "planType": "plus",
            })
        elif SCENARIO == "login_pending" and method == "account/login/start":
            _result(request_id, {
                "verificationUrl": "https://chatgpt.com/device/verify",
                "userCode": "WXYZ-1234",
                "loginId": _FAKE_PENDING_LOGIN_ID,
                "expiresIn": 600,
            })
        elif SCENARIO == "logout_ok" and method == "account/logout":
            _result(request_id, {"ok": True})
        elif SCENARIO == "account_read_plan" and method == "account/read":
            _result(request_id, {
                "email": "fake@example.com",
                "planType": "plus",
                "name": "Fake User",
            })
        elif SCENARIO == "scripted_turn":
            self._handle_scripted_turn(request_id, method, params)
        elif SCENARIO == "usage_limit":
            self._handle_usage_limit(request_id, method, params)
        elif SCENARIO == "stalled_turn":
            self._handle_stalled_turn(request_id, method, params)
        elif SCENARIO == "scripted_error":
            _error(request_id, ERROR_CODE, f"scripted error {ERROR_CODE}")
        elif SCENARIO == "slow_turn":
            time.sleep(SLOW_DELAY_SECONDS)
            _result(request_id, {"ok": True, "method": method})
        elif SCENARIO == "invalid_json":
            # Línea JSON inválida con el id del request: el reader debe
            # tolerarla y resolver la petición con la respuesta válida posterior.
            sys.stdout.buffer.write(
                b'{"jsonrpc":"2.0","id":' + str(request_id).encode("utf-8") + b',"result": {broken\n'
            )
            sys.stdout.buffer.flush()
            _result(request_id, {"ok": True, "method": method})
        else:
            # echo y cualquier método no especial de otros escenarios.
            _result(request_id, {"ok": True, "method": method, "params": params})

    def _handle_scripted_turn(self, request_id: int, method: str, params: dict) -> None:
        if method == "thread/start":
            _result(request_id, {"thread": {"id": self._next_thread_id()}})
            return
        if method != "turn/start":
            _result(request_id, {"ok": True, "method": method, "params": params})
            return
        turn_id = self._next_turn_id()
        thread_id = self._thread_id_for(params)
        try:
            text = self._read_turn_output()
        except OSError as exc:
            # Error de ACEPTACIÓN en la response (no notificación): distinto
            # de la cuota descubierta durante la ejecución.
            _error(request_id, "TurnOutputReadError", str(exc))
            return
        # Response inmediata: inProgress, SIN texto ni usage en la response.
        _result(request_id, {
            "turn": {"id": turn_id, "status": "inProgress", "items": []},
        })
        # Secuencia streaming exacta (receta §Turn lifecycle verification).
        _notification("turn/started", {
            "threadId": thread_id,
            "turn": {"id": turn_id, "status": "inProgress"},
        })
        item_id = self._next_item_id()
        _notification("item/started", {
            "item": {"type": "agentMessage", "id": item_id},
            "threadId": thread_id,
            "turnId": turn_id,
            "startedAtMs": int(time.time() * 1000),
        })
        _notification("item/agentMessage/delta", {
            "threadId": thread_id,
            "turnId": turn_id,
            "itemId": item_id,
            "delta": text,
        })
        # `item/completed` es autoritativo: su `item` (agentMessage) trae el
        # texto final, leído como texto plano, sin parseo.
        _notification("item/completed", {
            "item": {"type": "agentMessage", "id": item_id, "text": text},
            "threadId": thread_id,
            "turnId": turn_id,
            "completedAtMs": int(time.time() * 1000),
        })
        try:
            usage = self._read_token_usage()
        except (OSError, ValueError):
            # El texto ya se emitió; un fichero de usage ilegible no puede
            # romper el turno: se omite la notificación (el cliente defensivo
            # debe devolver conteos a cero).
            usage = None
        if usage is not None:
            _notification("thread/tokenUsage/updated", {
                "threadId": thread_id,
                "turnId": turn_id,
                "tokenUsage": usage,
            })
        _notification("turn/completed", {
            "threadId": thread_id,
            "turn": {"id": turn_id, "status": "completed", "items": []},
        })

    def _handle_usage_limit(self, request_id: int, method: str, params: dict) -> None:
        if method == "thread/start":
            _result(request_id, {"thread": {"id": self._next_thread_id()}})
            return
        if method == "turn/start":
            turn_id = self._next_turn_id()
            thread_id = self._thread_id_for(params)
            # Aceptación normal del turno: la cuota se descubre DURANTE la
            # ejecución, como notificación `error` + turn/completed fallido.
            _result(request_id, {
                "turn": {"id": turn_id, "status": "inProgress", "items": []},
            })
            _notification("error", {
                "error": dict(_USAGE_LIMIT_ERROR),
                "willRetry": False,
                "threadId": thread_id,
                "turnId": turn_id,
            })
            _notification("turn/completed", {
                "threadId": thread_id,
                "turn": {
                    "id": turn_id,
                    "status": "failed",
                    "error": dict(_USAGE_LIMIT_ERROR),
                    "items": [],
                },
            })
            return
        # Cualquier otro método (p. ej. account/logout): error object en la
        # response, como antes (test de T04 "logout fallido no bloquea el
        # borrado").
        _error(request_id, "UsageLimitExceeded", _QUOTA_MESSAGE)

    def _handle_stalled_turn(self, request_id: int, method: str, params: dict) -> None:
        if method == "thread/start":
            _result(request_id, {"thread": {"id": self._next_thread_id()}})
            return
        if method == "turn/start":
            _result(request_id, {
                "turn": {"id": self._next_turn_id(), "status": "inProgress", "items": []},
            })
            # Ninguna notificación posterior: el cliente cae en timeout
            # esperando `turn/completed`.
            return
        _result(request_id, {"ok": True, "method": method, "params": params})


def main() -> int:
    # Banner en stderr: el gestor lo vuelca a <CODEX_HOME>/app-server.stderr.log
    # (truncado por spawn) y nunca a los logs de la aplicación.
    sys.stderr.write(f"fake app-server started (scenario={SCENARIO})\n")
    sys.stderr.flush()

    handler = _ScenarioHandler()
    for raw_line in sys.stdin.buffer:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if not isinstance(req, dict):
            continue
        _trace_received(req)
        if req.get("id") is None:
            # Notificaciones (mensajes sin `id`), p. ej. `initialized` del
            # handshake: el app-server real no responde a ellas; el fake
            # tampoco (sin id → sin respuesta).
            continue
        if req.get("method") == "initialize":
            # Handshake de apertura de conexión (el real exige `initialize`
            # antes de CUALQUIER request; gate live, ronda 4). Result mínimo,
            # FUERA del escenario: el escenario modela métodos de aplicación,
            # no el transporte (slow_turn/scripted_error/invalid_json no
            # deben romper el handshake).
            _result(req["id"], {})
            continue
        handler.handle(req["id"], req.get("method", ""), req.get("params") or {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

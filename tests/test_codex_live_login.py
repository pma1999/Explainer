"""Live gate del proveedor Codex: vínculo device-code real con una cuenta ChatGPT.

Este test valida la compatibilidad REAL con el binario `codex app-server`
(no el fake de T02): inicia un vínculo device-code, espera a que un humano lo
complete en chatgpt.com, verifica el vínculo, ejecuta UN turno real con el
modelo `gpt-5.6-luna` y cierra sesión.

**Skip por defecto**: solo corre con ``CODEX_LIVE=1`` (fuera de CI, por un
humano con credenciales reales de ChatGPT). La suite por defecto no lo
recoge: `pytest.ini` limita `testpaths` a `tests/backend`.

Requisitos y credenciales reales
--------------------------------

- Un binario real ``codex`` (0.147.0, el pineado del bundle) que soporte
  ``app-server --stdio``. Si no está en ``/usr/local/bin/codex``, apuntar
  ``CODEX_BIN_PATH`` al binario (p.ej. ``CODEX_BIN_PATH="$(which codex)"``).
- ``CODEX_LIVE_EFFORT`` opcional: nivel de razonamiento para el turno real
  (p.ej. ``xhigh``); valida ``turn/start.effort`` contra el binario real.
- ``CODEX_HOME_ROOT`` opcional (default ``/tmp/codex``; el home del tenant se
  crea con modo 0700).
- Una cuenta ChatGPT (Plus/Pro/Team/Enterprise según el plan) con cuota de
  Codex disponible. El vínculo se completa a mano en el navegador con la URL
  y el código que imprime el test. **Se consume cuota real del plan.**
- Entorno Windows (repo `.venv-win`): ejecutar con el python del venv, p.ej.::

    set CODEX_LIVE=1
    set CODEX_BIN_PATH=C:/ruta/codex.exe
    .venv-win\\Scripts\\python.exe scripts\\run_pytest.py tests\\test_codex_live_login.py -m integration -s

  En Linux/macOS (binario en PATH)::

    CODEX_LIVE=1 CODEX_BIN_PATH="$(which codex)" \
      python scripts/run_pytest.py tests/test_codex_live_login.py -m integration -s

Procedimiento manual del device code (lo imprime el test, `-s` obligatorio)
---------------------------------------------------------------------------

1. El test arranca el app-server real y pide ``account/login/start``.
2. Imprime ``verification_url`` + ``user_code`` (p.ej. ``https://chatgpt.com/device/verify``
   y ``ABCD-EFGH``). El humano abre la URL, introduce el código y confirma el
   acceso en su cuenta de ChatGPT (la ventana de ~10 min está acotada por
   ``CODEX_LINK_TIMEOUT_SECONDS``).
3. El app-server emite la notificación ``account/login/completed``; el test la
   captura, verifica que ``auth.json`` existe en ``CODEX_HOME`` y ejecuta un
   turno real ``gpt-5.6-luna`` ("responde solo con la palabra ok").
4. Cierra sesión con ``account/logout`` y evicta el proceso (limpieza del home
   incluida). Si algo falla antes, el `finally` intenta igualmente el logout
   best-effort y la evicción.

Esto cierra el live gate de `final-review.md` (R-PROTO, R-AUTHJSON): hasta que
se ejecute con un binario real, el wire-format solo está pineado por el fake
app-server de T02. Nunca loguea ni imprime el contenido de `auth.json`.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_LIVE_REQUIRED = os.environ.get("CODEX_LIVE", "") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(
        not _LIVE_REQUIRED,
        reason=(
            "Live gate: requiere CODEX_LIVE=1, un binario codex real "
            "(CODEX_BIN_PATH) y una cuenta ChatGPT con cuota; lo ejecuta un "
            "humano, fuera de CI"
        ),
    ),
]

_DEVICE_CODE_TIMEOUT_SECONDS = float(
    os.environ.get("CODEX_LINK_TIMEOUT_SECONDS", "600")
)
_TURN_TIMEOUT_SECONDS = 900.0
# Effort opcional para el turno real (p.ej. CODEX_LIVE_EFFORT=xhigh valida
# el wire `turn/start.effort` contra el binario real; ausente -> no se envia).
_LIVE_EFFORT = os.environ.get("CODEX_LIVE_EFFORT") or None


def _codex_manager():
    """Singleton del gestor (import diferido: su config de env se lee en uso)."""
    from backend.codex_app_server import codex_manager

    return codex_manager


def _verify_binary_present() -> None:
    """Comprueba que el binario configurado existe antes de arrancar el app-server."""
    bin_path = os.environ.get("CODEX_BIN_PATH") or "/usr/local/bin/codex"
    if bin_path.lower().endswith(".py"):
        pytest.skip(
            "CODEX_BIN_PATH apunta al fake de tests; el live gate exige el binario real"
        )
    if not os.path.exists(bin_path):
        pytest.fail(
            f"Binario codex no encontrado en CODEX_BIN_PATH={bin_path}. "
            "Instala el tarball pineado de @openai/codex-linux-x64@0.147.0 o "
            "apunta CODEX_BIN_PATH al binario real."
        )


async def test_live_device_code_link_turn_and_logout():
    """Vínculo device-code real → un turno gpt-5.6-luna → logout (gate live).

    Consume cuota real del plan ChatGPT del usuario. Requiere acción humana
    (completar el device code en chatgpt.com); ver el docstring del módulo.
    """
    _verify_binary_present()
    user_id = str(uuid.uuid4())  # UUID válido exigido por el gestor (anti path traversal)
    manager = _codex_manager()
    completed = asyncio.Event()
    completed_login_id: list[str | None] = [None]

    async def _on_login_completed(handler_user_id: str, params: object) -> None:
        if handler_user_id != user_id:
            return
        params_dict = params if isinstance(params, dict) else {}
        completed_login_id[0] = params_dict.get("loginId")
        completed.set()

    manager.add_notification_handler("account/login/completed", _on_login_completed)

    app_server = None
    try:
        app_server = await manager.acquire(user_id)
        result = await app_server.request(
            "account/login/start", {"type": "chatgptDeviceCode"}
        )
        assert isinstance(result, dict), f"respuesta inesperada: {result!r}"
        verification_url = result.get("verificationUrl")
        user_code = result.get("userCode")
        login_id = result.get("loginId")
        assert verification_url and user_code and login_id, (
            f"device code incompleto del app-server real: {result!r}"
        )

        # Instrucciones para el humano (requiere pytest -s).
        print("\n" + "=" * 72, flush=True)
        print("VINCULO DEVICE-CODE REAL — accion humana requerida", flush=True)
        print(f"  1. Abre:  {verification_url}", flush=True)
        print(f"  2. Codigo: {user_code}", flush=True)
        print(
            f"  3. Completa el acceso en tu cuenta ChatGPT "
            f"(max {_DEVICE_CODE_TIMEOUT_SECONDS:.0f}s).",
            flush=True,
        )
        print("=" * 72 + "\n", flush=True)

        # Poll/espera del vínculo: la notificación del app-server real.
        try:
            await asyncio.wait_for(completed.wait(), timeout=_DEVICE_CODE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pytest.fail(
                "El vínculo no se completó a tiempo. ¿Completaste la URL + código "
                "en chatgpt.com? El app-server real no emitió account/login/completed."
            )
        assert completed_login_id[0] == login_id

        # auth.json debe existir en CODEX_HOME (blob opaco, nunca se imprime).
        home = app_server.home_dir / "auth.json"
        assert home.exists() and home.stat().st_size > 0, (
            "auth.json ausente tras account/login/completed — el app-server real "
            "no persistió la sesión"
        )
        print(f"Vínculo completado (login_id={login_id}, planType={result.get('planType')})", flush=True)

        # Un turno real gpt-5.6-luna (cuota del plan; texto, sin JSON).
        from backend.codex_client import call_codex_chat

        text, usage = await asyncio.wait_for(
            call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": "Responde solo con la palabra ok."}],
                system_prompt="Eres un asistente de pruebas. Responde con exactitud.",
                model="gpt-5.6-luna",
                response_format="text",
                timeout=_TURN_TIMEOUT_SECONDS,
                effort=_LIVE_EFFORT,
            ),
            timeout=_TURN_TIMEOUT_SECONDS + 30.0,
        )
        assert isinstance(text, str) and text.strip(), "turno real sin texto"
        assert "ok" in text.lower(), f"respuesta inesperada del turno real: {text[:80]!r}"
        print(
            f"Turno real OK (effort={_LIVE_EFFORT!r}) — texto={text[:60]!r} usage="
            f"prompt={usage.prompt_token_count} candidates={usage.candidates_token_count} "
            f"total={usage.total_token_count} cost_usd={usage.cost_usd} "
            f"quota_requests={usage.quota_requests}",
            flush=True,
        )

        # Logout best-effort (el vínculo se borra localmente pase lo que pase).
        try:
            await app_server.request("account/logout", {}, timeout=30.0)
            print("Logout OK", flush=True)
        except Exception as exc:  # noqa: BLE001 - best-effort documentado
            print(f"Logout best-effort falló (no bloqueante): {type(exc).__name__}", flush=True)
    finally:
        await manager.evict(user_id)

"""Regression test cross-task (T05/T06): las env `CODEX_*` se leen en el
momento de uso, no en el import.

`backend.codex_app_server` puede importarse de forma eager (main.py → agents →
codex_client) ANTES de que los tests fijen `CODEX_BIN_PATH` a nivel de módulo.
Si el módulo congelara su configuración en el import, el singleton quedaría
apuntando al binario por defecto y los spawns de T02 fallarían en la suite
completa: el env de test solo aplica si la lectura es per-uso.

Este test borra las `CODEX_*` del env (el módulo y su singleton ya están
importados de la colección), las setea DESPUÉS con el fake y verifica que un
spawn posterior usa el fake y el home del env: prueba directa de lectura
per-uso. No recarga el módulo: `importlib.reload` rompería la identidad de las
clases de error para los módulos de test ya coleccionados (pytest.raises con
las clases antiguas no captura las nuevas).

Estabilización del env compartido (módulo nivel): los módulos de test de codex
fijan `CODEX_*` a nivel de módulo en la colección y el último que escribe gana
para toda la corrida (los writes de módulo son permanentes, monkeypatch no los
restaura). En la suite completa (orden alfabético) `test_codex_client.py`
pisa `CODEX_HOME_ROOT` DESPUÉS de `test_codex_app_server.py`; los tests de T02
dependen de SU env a nivel de módulo (no parchean el singleton por test), así
que la lectura per-uso vería el home de otro módulo. Como este módulo es el
último de la familia en colección, re-afirma el `CODEX_HOME_ROOT` de T02 (el
resto de variables no se pisan: mismo fake en `CODEX_BIN_PATH` y valores
idénticos en el resto).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import backend.codex_app_server as codex_app_server
import backend.supabase_data as supabase_data

# Estabilización del env compartido de la suite (ver docstring del módulo).
# Solo cuando T02 está en la corrida (su módulo ya coleccionado): re-afirma el
# home de los tests de T02 que test_codex_client.py pisa en la colección.
if "test_codex_app_server" in sys.modules:
    import test_codex_app_server as _t02_module  # ya importado: sin efectos

    os.environ["CODEX_HOME_ROOT"] = _t02_module._TEST_HOME_ROOT

_FAKE_BIN = str(Path(__file__).resolve().parent / "fake_codex_app_server.py")
_ALL_CODEX_ENV = (
    "CODEX_BIN_PATH",
    "CODEX_HOME_ROOT",
    "CODEX_MAX_PROCESSES",
    "CODEX_SPAWN_WAIT_SECONDS",
    "CODEX_PER_PROCESS_MAX_CONCURRENCY",
    "CODEX_IDLE_TTL_SECONDS",
    "CODEX_REQUEST_TIMEOUT_SECONDS",
    "CODEX_TERMINATE_GRACE_SECONDS",
)


@pytest.mark.asyncio(loop_scope="session")
async def test_env_read_at_use_time_not_at_import(monkeypatch, tmp_path):
    # Aislar de Supabase (mismo patrón que test_codex_app_server.py).
    monkeypatch.setattr(
        supabase_data, "get_user_provider_connection", lambda user_id: None
    )
    monkeypatch.setattr(
        supabase_data, "upsert_user_provider_connection", lambda *args, **kwargs: None
    )

    # 1. Env "limpio": el módulo (y su singleton) ya está importado de la
    # colección; se elimina cualquier CODEX_* para que el import de la suite
    # no pueda haber influido en el estado que se va a probar.
    for name in _ALL_CODEX_ENV:
        monkeypatch.delenv(name, raising=False)

    # 2. El import no congeló nada: los nombres públicos conservan los
    # defaults del contrato (el singleton no tiene binario fijado).
    assert codex_app_server.CODEX_BIN_PATH == "/usr/local/bin/codex"

    # 3. Después del import se fija el env (como hace test_codex_app_server.py
    # a nivel de módulo en la suite completa).
    monkeypatch.setenv("CODEX_BIN_PATH", _FAKE_BIN)
    monkeypatch.setenv("CODEX_HOME_ROOT", str(tmp_path))
    monkeypatch.setenv("CODEX_SPAWN_WAIT_SECONDS", "1")
    monkeypatch.setenv("CODEX_REQUEST_TIMEOUT_SECONDS", "2")

    # 4. El singleton creado en el import (antes de setear el env) debe usar el
    # fake en el spawn: la resolución es per-uso.
    user_id = "00000001-0000-4000-8000-000000000001"
    server = await codex_app_server.codex_manager.acquire(user_id)
    try:
        result = await server.request("echo", {"x": 1}, timeout=2)
        assert result == {"ok": True, "method": "echo", "params": {"x": 1}}
        # CODEX_HOME_ROOT también se lee en el uso: home bajo tmp_path.
        assert (tmp_path / user_id).is_dir()
    finally:
        await codex_app_server.codex_manager.shutdown()

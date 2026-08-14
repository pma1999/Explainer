# Review: final

## Verdict
APPROVE

## Functional Verification
- `.venv-win/Scripts/python.exe scripts/run_pytest.py -q` — **622 passed, 3 skipped**.
- `npx vitest run` — **19 files passed, 347 tests passed**.
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py -q -k 'xhigh or persisted_effort'` — **4 passed, 39 deselected**.
- `git diff --check` — pasó sin errores.
- La evidencia de traza fake en los tests de cliente/agentes confirma `turn/start.effort`, retry con el mismo effort y ausencia de effort en `thread/start`.

## Spec Compliance
- Cumplido el flujo integrado: selección `xhigh` se conserva como `codexEffort`, llega como `codex_effort`, se valida, se propaga a las fases Codex y se persiste en `explainer_config`; review/reformat reutilizan el valor persistido.
- Cumplido el default: ausente, `null` y `""` normalizan a `medium`; valores no permitidos producen HTTP 400 con el mensaje congelado.
- Contrato cross-task idéntico: allowlist `low/medium/high/xhigh/max`, default `medium`, `codexEffort` en storage y `codex_effort` en API.
- UI cumplida: cinco radios, copia española congelada, medium recomendado y checked en HTML, nota de aplicación a todas las fases, restore defensivo y payload condicional solo para Codex.
- Sin cambios observados en proveedores existentes, Mermaid, YouTube fallback, `android/`, firmas posicionales heredadas ni el wire streaming FR-01; no se añadió effort a `thread/start`.

## Code Quality
- Pass. La validación de backend está centralizada en `normalize_codex_effort`; el cliente aplica defensa adicional y el frontend restaura valores inválidos a `medium`.
- Pass. El diff permanece dentro de las superficies previstas (backend Codex/pipeline, UI Codex y sus tests); el fixture fake no fue modificado.

## Named Risk Checks
- **R-EFFORT-WIRE — mitigado en tests, no verificado en servidor live.** Se observó la traza JSONL fake: clave exacta `effort` en `turn/start`; no aparecen `thread/start.effort`, `reasoning_effort` ni `config.model_reasoning_effort`. La compatibilidad/precedencia contra binario autenticado sigue siendo el gate pre-release documentado.
- **R-OLD-PROJECTS — cubierto.** Review y reformat resuelven campo ausente o corrupto a `medium`; los tests de pipeline cubren persistencia y fallback.
- **R-DEFAULT-DRIFT — aceptado/documentado.** El catálogo de producto y la allowlist congelada son idénticos en backend/frontend; no hay envío de valores fuera de la allowlist. La posible divergencia futura de `model/list` permanece como riesgo operativo documentado.
- **R-COPY — cubierto.** `frontend/index.html` coincide con la tabla congelada de `global-constraints.md`; Vitest verifica DOM, persistencia y payload.

## Required Changes
- None. No findings blocking ni non-blocking.

## Remediation History
None for final review.

## Evidence
- `backend/codex_model_routing.py`: allowlist/default/normalización.
- `backend/codex_client.py`: `effort` únicamente en `_turn_params` y forwarding al retry.
- `main.py`: validación por provider, persistencia, threading de fases y resolución defensiva de review/reformat.
- `frontend/index.html` y `frontend/js/landing.js`: panel, copia, fallback, storage y payload condicional.
- `tests/backend/test_codex_client.py`, `test_codex_agents_*`, `test_codex_pipeline.py`, `tests/frontend/landing*.test.js`: cobertura del wire, pipeline, contratos y UI.
- `git diff --name-only`: no incluye `android/`, `tests/backend/fake_codex_app_server.py`, `backend/auth.py` ni `backend/pricing.py`.

## Security Checklist
- Sin credenciales, tokens o secretos añadidos al diff.
- No se amplía el wire con campos no contractuales; allowlist estricta antes de enviar effort.
- El valor inválido solo aparece en el mensaje 400 congelado; los warnings defensivos no incluyen el valor.
- Sin cambios fuera de scope en Android, auth, Mermaid, proveedores existentes o fixture fake.

## Limitations
- No se ejecutó el live gate contra un app-server Codex autenticado; R-EFFORT-WIRE permanece pendiente de esa verificación pre-release.


## Live gate with effort (R-EFFORT-WIRE closed) — 2026-08-14

Ejecutado contra el binario real `codex.exe` 0.145.0 con `CODEX_LIVE_EFFORT=xhigh`
(device-code completado por el usuario). Salida real:

```
Vínculo completado (login_id=6c8f308b-cbbe-425a-902c-a6d0931e128f)
Turno real OK (effort='xhigh') — texto='ok' usage=prompt=13487 candidates=5 total=13492 cost_usd=0.0 quota_requests=1
Logout OK
1 passed, 1 warning in 122.81s
```

**R-EFFORT-WIRE resuelto**: el app-server real aceptó `turn/start.effort:"xhigh"` y el
ciclo streaming completo funcionó con el effort aplicado. El live gate
(`tests/test_codex_live_login.py`) ahora acepta `CODEX_LIVE_EFFORT` para re-validar
cualquier nivel contra el binario en el futuro.

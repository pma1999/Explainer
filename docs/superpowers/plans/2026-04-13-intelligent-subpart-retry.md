# Intelligent Subpart Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cuando el auditor detecte que una subparte invade material vecino o deja fuera contenido propio, reintentar solo esa subparte con un dossier de reescritura rico que incluya la salida fallida, el diagnóstico del auditor y el mismo contexto fuente ya preparado.

**Architecture:** El retry seguirá reutilizando el mismo `run_explainer_call`, por lo que mantendrá el mismo PDF/URI, el mismo `pdf_cache_entry` de OpenRouter y el mismo `page_scope` de la subparte. La mejora se concentrará en dos puntos: construir un bloque de reescritura guiada en `backend/subpart_scope_auditor.py` y conectarlo en `_run_subpart_explainer_with_scope_audit()` para que el segundo intento rehaga desde cero el `desarrollo` con toda la evidencia relevante.

**Tech Stack:** Python 3.13, FastAPI pipeline en `main.py`, Gemini auditor, OpenRouter explainer PDF path, pytest.

---

## File Map

- Modify: `backend/subpart_scope_auditor.py`
  - Añadir el builder del dossier de reescritura inteligente.
  - Reutilizar `flatten_desarrollo_text()` y acotar el tamaño del texto previo para no disparar tokens.
- Modify: `main.py`
  - Sustituir el retry débil (`initial_prompt + suffix`) por `initial_prompt + rewrite_brief`.
  - Hacer explícita la captura de `cache_entry` y `page_scope` en el path OpenRouter canónico para que el retry no cambie de contexto fuente.
- Modify: `tests/backend/test_subpart_scope_auditor.py`
  - Probar que el nuevo brief incluye salida fallida, razón del auditor, contexto actual/anterior/siguiente y truncado.
- Modify: `tests/backend/test_pdf_process_flow.py`
  - Añadir un flow test con OpenRouter que verifique a la vez el contenido del retry y la reutilización de `cache_entry` + `page_numbers`.

## Design Constraints

- No cambiar el número máximo de intentos en esta iteración.
- No tocar `recorrido` ni `resources`.
- No cambiar la política OCR de producción: el retry debe seguir usando el mismo `pdf_cache_entry` y el mismo subconjunto de páginas ya preparados.
- El retry debe pedir explícitamente una **reescritura completa desde cero** del `desarrollo`; no una edición parcial de la respuesta contaminada.

---

## Task 1: Add a Rich Rewrite Brief for Failed Subparts

**Files:**
- Modify: `backend/subpart_scope_auditor.py`
- Modify: `tests/backend/test_subpart_scope_auditor.py`

El helper actual `build_subpart_scope_retry_suffix()` solo lista invasiones y faltantes. Falta el contexto clave: qué escribió mal el explainer, por qué está mal y qué límites concretos debe respetar al rehacer la subparte.

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/test_subpart_scope_auditor.py`:

```python
from backend.subpart_scope_auditor import build_subpart_scope_rewrite_brief


def test_rewrite_brief_includes_failed_output_audit_reason_and_scope_summaries():
    report = SubpartScopeAuditReport(
        is_valid=False,
        invades_previous=("Teorización política",),
        invades_next=("Régimen polisinodial",),
        missing_current=("Burocracia de oficiales",),
        rationale="Invade la siguiente subparte y omite contenido propio.",
    )
    payload = {
        "desarrollo": [
            {
                "titulo_seccion": "Bloque inválido",
                "explicacion_introductoria": "Texto desarrollado contaminado",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Detalle",
                        "explicacion_detallada": "Incluye material de la subparte vecina",
                    }
                ],
            }
        ]
    }

    text = build_subpart_scope_rewrite_brief(
        report,
        failed_desarrollo_payload=payload,
        current_subpart_summary="Título: Actual\nContenido: Contenido actual",
        previous_subpart_summary="Título: Anterior\nContenido: Contenido anterior",
        next_subpart_summary="Título: Siguiente\nContenido: Contenido siguiente",
    )

    assert "<reescritura_alcance_subparte>" in text
    assert "RESPUESTA ANTERIOR INVÁLIDA" in text
    assert "Texto desarrollado contaminado" in text
    assert "Invade la siguiente subparte y omite contenido propio." in text
    assert "Título: Actual" in text
    assert "Título: Anterior" in text
    assert "Título: Siguiente" in text
    assert "REESCRIBE desde cero" in text


def test_rewrite_brief_truncates_failed_output_reference():
    report = SubpartScopeAuditReport(
        is_valid=False,
        invades_previous=(),
        invades_next=("Tema vecino",),
        missing_current=("Tema actual",),
        rationale="La salida anterior se extendió fuera de alcance.",
    )
    payload = {
        "desarrollo": [
            {
                "titulo_seccion": "Uno",
                "explicacion_introductoria": "X" * 300,
                "subsecciones": [
                    {"titulo_subseccion": "A", "explicacion_detallada": "Y" * 300},
                ],
            }
        ]
    }

    text = build_subpart_scope_rewrite_brief(
        report,
        failed_desarrollo_payload=payload,
        current_subpart_summary="Título: Actual",
        previous_subpart_summary="",
        next_subpart_summary="Título: Siguiente",
        max_failed_output_chars=120,
    )

    assert "[truncado]" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_subpart_scope_auditor.py -v
```

Expected: FAIL with `ImportError` or `AttributeError` because `build_subpart_scope_rewrite_brief` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Update `backend/subpart_scope_auditor.py` with a bounded rewrite brief builder:

```python
MAX_SUBPART_SCOPE_AUDIT_ATTEMPTS = 2
MAX_SUBPART_SCOPE_REWRITE_REFERENCE_CHARS = 4000


def _truncate_retry_reference_text(
    text: str,
    max_chars: int = MAX_SUBPART_SCOPE_REWRITE_REFERENCE_CHARS,
) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    suffix = "\n...[truncado]"
    return normalized[: max_chars - len(suffix)] + suffix


def build_subpart_scope_rewrite_brief(
    report: SubpartScopeAuditReport,
    *,
    failed_desarrollo_payload: dict[str, Any],
    current_subpart_summary: str,
    previous_subpart_summary: str,
    next_subpart_summary: str,
    max_failed_output_chars: int = MAX_SUBPART_SCOPE_REWRITE_REFERENCE_CHARS,
) -> str:
    failed_output = _truncate_retry_reference_text(
        flatten_desarrollo_text(failed_desarrollo_payload),
        max_failed_output_chars,
    ) or "(sin contenido previo)"

    lines = [
        "<reescritura_alcance_subparte>",
        "Tu respuesta anterior NO respetó el alcance de la subparte actual.",
        "REESCRIBE desde cero el campo `desarrollo`. No intentes parchear ni preservar frases dudosas de la salida anterior.",
        "",
        "SUBPARTE ACTUAL (fuente de verdad):",
        current_subpart_summary or "(sin resumen de subparte actual)",
    ]
    if previous_subpart_summary:
        lines.extend(["", "SUBPARTE ANTERIOR (NO desarrollar):", previous_subpart_summary])
    if next_subpart_summary:
        lines.extend(["", "SUBPARTE SIGUIENTE (NO desarrollar):", next_subpart_summary])

    lines.extend(["", "RESPUESTA ANTERIOR INVÁLIDA:", failed_output, "", "ERRORES DETECTADOS POR EL AUDITOR:"])

    if report.invades_previous:
        lines.append("NO desarrolles contenido de la subparte anterior:")
        for item in report.invades_previous:
            lines.append(f"- {item}")
    if report.invades_next:
        lines.append("NO desarrolles contenido de la subparte siguiente:")
        for item in report.invades_next:
            lines.append(f"- {item}")
    if report.missing_current:
        lines.append("SÍ debes desarrollar el contenido propio que falta:")
        for item in report.missing_current:
            lines.append(f"- {item}")

    lines.extend(
        [
            f"Motivo del auditor: {report.rationale}",
            "Instrucción final: descarta la respuesta anterior y reescribe el `desarrollo` completo respetando solo el alcance de la subparte actual.",
            "</reescritura_alcance_subparte>",
        ]
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests again**

Run:

```bash
python -m pytest tests/backend/test_subpart_scope_auditor.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/subpart_scope_auditor.py tests/backend/test_subpart_scope_auditor.py
git commit -m "feat: add guided rewrite brief for subpart retries"
```

---

## Task 2: Use the Rewrite Brief in the Runtime Retry Loop

**Files:**
- Modify: `main.py`
- Modify: `tests/backend/test_pdf_process_flow.py`

La parte crítica es que el retry de runtime deje de ser ciego y conserve exactamente el mismo contexto fuente que la llamada inicial, especialmente en el path OpenRouter con OCR canónico.

- [ ] **Step 1: Add the failing flow test**

Append to `tests/backend/test_pdf_process_flow.py`:

```python
def test_process_project_pdf_openrouter_retry_reuses_cache_and_includes_rewrite_brief(monkeypatch):
    pdf_path = _create_multi_page_pdf(4)
    try:
        project = {
            "id": "proj-openrouter-rewrite",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        openrouter_calls = []
        audit_attempts = {"count": 0}
        cache_entry = OpenRouterPdfParseCacheEntry(
            source_sha256="sha256",
            engine="mistral-ocr",
            assistant_message=None,
            cache_path="cache.json",
            cache_hit=True,
            expected_page_numbers=(1, 2, 3, 4),
            cached_page_numbers=(1, 2, 3, 4),
            page_index=(),
        )

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "sk-or-v1-test" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(main, "update_project", lambda pid, uid, payload: None)
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())
        monkeypatch.setattr(
            main,
            "upload_file_with_retry",
            lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"),
        )
        monkeypatch.setattr(main, "run_page_classifier", lambda *args, **kwargs: (frozenset([1, 2, 3, 4]), _usage(), {}))
        monkeypatch.setattr(
            main,
            "_prepare_openrouter_pdf_context",
            lambda **kwargs: main.OpenRouterPreparedPdfContext(
                source_pdf_path=pdf_path,
                cache_entry=cache_entry,
            ),
        )

        def _fake_segmentador(*args, **kwargs):
            base = _part_pdf_fields(1, "Única", 1, 4)
            base["temas_cubiertos"] = ["tema1"]
            base["subpartes"] = [
                {
                    "numero_subparte": 1,
                    "titulo": "Primera",
                    "contenido": "Contenido inicial",
                    "identificacion": "NÚCLEO SEGÚN MARCAS PDF: páginas 1–2.",
                    "pagina_inicio": 1,
                    "pagina_fin": 2,
                    "temas_cubiertos": ["tema1"],
                    "delimitacion_explainer": {
                        "inicio": {"encabezado": "1.1", "ancla_texto": "primer texto"},
                        "fin": {"ancla_texto": "fin tema uno", "encabezado_siguiente_excluido": ""},
                        "transicion_compartida": {
                            "hay_transicion": False,
                            "pagina": 0,
                            "hasta_texto_inclusive": "",
                            "desde_texto_inclusive": "",
                        },
                    },
                }
            ]
            return (
                {
                    "analisis_texto": "Cuatro páginas",
                    "temas_identificados": ["tema1"],
                    "decision_num_partes": 1,
                    "decision_justificacion": "Una parte",
                    "partes": [base],
                    "consideraciones_estudiante": "Seguir el orden natural",
                },
                _usage(total=40),
            )

        monkeypatch.setattr(main, "run_segmentador", _fake_segmentador)

        def _fake_subpart_explainer_or(
            source_path,
            agent_prompt,
            model,
            mime_type,
            api_key,
            cache_entry=None,
            page_numbers=(),
        ):
            openrouter_calls.append(
                {
                    "source_path": source_path,
                    "prompt": agent_prompt,
                    "cache_entry": cache_entry,
                    "page_numbers": tuple(page_numbers),
                }
            )
            return (
                {
                    "desarrollo": [
                        {
                            "titulo_seccion": "Bloque inválido",
                            "explicacion_introductoria": "Texto desarrollado contaminado",
                            "subsecciones": [
                                {
                                    "titulo_subseccion": "Detalle",
                                    "explicacion_detallada": "Incluye material de otra subparte",
                                }
                            ],
                        }
                    ]
                },
                _usage(total=22),
            )

        monkeypatch.setattr(main, "run_subpart_explainer_or", _fake_subpart_explainer_or)
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))

        async def _fake_format(api_key, explainer_data):
            return (explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0})

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        def _fake_auditor(**kwargs):
            from backend.subpart_scope_auditor import SubpartScopeAuditReport

            audit_attempts["count"] += 1
            if audit_attempts["count"] == 1:
                return (
                    SubpartScopeAuditReport(
                        is_valid=False,
                        invades_previous=(),
                        invades_next=("tema vecino",),
                        missing_current=("tema1",),
                        rationale="Invade la siguiente subparte.",
                    ),
                    _usage(total=7),
                )
            return (
                SubpartScopeAuditReport(
                    is_valid=True,
                    invades_previous=(),
                    invades_next=(),
                    missing_current=(),
                    rationale="OK",
                ),
                _usage(total=7),
            )

        monkeypatch.setattr(main, "run_subpart_scope_auditor", _fake_auditor)

        asyncio.run(main._process_project("proj-openrouter-rewrite", "user-123", explainer_provider="openrouter"))

        assert len(openrouter_calls) == 2
        assert openrouter_calls[0]["cache_entry"] is cache_entry
        assert openrouter_calls[1]["cache_entry"] is cache_entry
        assert openrouter_calls[0]["page_numbers"] == (1, 2, 3)
        assert openrouter_calls[1]["page_numbers"] == (1, 2, 3)

        retry_prompt = openrouter_calls[1]["prompt"]
        assert "<reescritura_alcance_subparte>" in retry_prompt
        assert "Texto desarrollado contaminado" in retry_prompt
        assert "Invade la siguiente subparte." in retry_prompt
        assert "REESCRIBE desde cero" in retry_prompt
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)
```

- [ ] **Step 2: Run the flow test to verify it fails**

Run:

```bash
python -m pytest tests/backend/test_pdf_process_flow.py::test_process_project_pdf_openrouter_retry_reuses_cache_and_includes_rewrite_brief -v
```

Expected: FAIL because `main.py` still appends the old weak retry suffix and the second prompt does not include the failed output or the rewrite tag.

- [ ] **Step 3: Update `main.py` to use the rewrite brief and keep OpenRouter context explicit**

At the imports near the top of `main.py`, switch the retry helper import:

```python
from backend.subpart_scope_auditor import (
    MAX_SUBPART_SCOPE_AUDIT_ATTEMPTS,
    build_subpart_scope_rewrite_brief,
    run_subpart_scope_auditor,
)
```

Then update `_run_subpart_explainer_with_scope_audit()`:

```python
async def _run_subpart_explainer_with_scope_audit(
    *,
    run_explainer_call: Callable[[str], Awaitable[tuple[dict[str, Any], Any]]],
    initial_prompt: str,
    audit_context_builder: Callable[[], dict[str, str]],
    audit_api_key: str,
    audit_model: str,
) -> tuple[dict[str, Any], Any, list[Any]]:
    prompt = initial_prompt
    reviewer_usages: list[Any] = []

    for _ in range(MAX_SUBPART_SCOPE_AUDIT_ATTEMPTS):
        result, usage = await run_explainer_call(prompt)
        ctx = audit_context_builder()
        report, review_usage = await asyncio.to_thread(
            run_subpart_scope_auditor,
            api_key=audit_api_key,
            current_subpart_summary=ctx["current"],
            previous_subpart_summary=ctx["previous"],
            next_subpart_summary=ctx["next"],
            desarrollo_payload=result,
            model=audit_model,
        )
        reviewer_usages.append(review_usage)
        if report.is_valid:
            return result, usage, reviewer_usages

        rewrite_brief = build_subpart_scope_rewrite_brief(
            report,
            failed_desarrollo_payload=result,
            current_subpart_summary=ctx["current"],
            previous_subpart_summary=ctx["previous"],
            next_subpart_summary=ctx["next"],
        )
        prompt = f"{initial_prompt}\n\n{rewrite_brief}"

    raise RuntimeError("El auditor de alcance de subparte agotó sus reintentos.")
```

And make the canonical OpenRouter retry inputs explicit inside `_make_audited_subpart_task()` so the second attempt cannot drift to another source/scope:

```python
def _make_audited_subpart_task(idx: int):
    sp_prompt = subpart_prompts[idx]
    subparte = subpartes[idx] if idx < len(subpartes) else None
    canonical_source_path = openrouter_pdf_context.source_pdf_path if use_or_canonical else None
    canonical_cache_entry = openrouter_pdf_context.cache_entry if use_or_canonical else None
    canonical_page_scope = openrouter_page_scopes[idx] if use_or_canonical else None

    async def _audited():
        def _audit_context() -> dict[str, str]:
            previous_sp = subpartes[idx - 1] if idx > 0 else None
            next_sp = subpartes[idx + 1] if idx + 1 < len(subpartes) else None
            return {
                "current": build_subpart_scope_summary(subparte) if subparte else "",
                "previous": build_subpart_scope_summary(previous_sp) if previous_sp else "",
                "next": build_subpart_scope_summary(next_sp) if next_sp else "",
            }

        async def _call(prompt: str) -> tuple[dict[str, Any], Any]:
            if use_or:
                if use_or_canonical:
                    return await asyncio.to_thread(
                        explainer_fn_or_sp,
                        canonical_source_path,
                        prompt,
                        explainer_model,
                        "application/pdf",
                        openrouter_api_key,
                        canonical_cache_entry,
                        canonical_page_scope,
                    )
                return await asyncio.to_thread(
                    explainer_fn_or_sp,
                    segment_temp_path,
                    prompt,
                    explainer_model,
                    agent_mime_type,
                    openrouter_api_key,
                )
            return await asyncio.to_thread(
                explainer_fn_sp,
                api_key,
                agent_file_uri,
                prompt,
                MODEL_AGENTS,
                agent_mime_type,
            )
```

- [ ] **Step 4: Run the targeted tests**

Run:

```bash
python -m pytest tests/backend/test_subpart_scope_auditor.py tests/backend/test_pdf_process_flow.py::test_process_project_pdf_openrouter_retry_reuses_cache_and_includes_rewrite_brief tests/backend/test_pdf_process_flow.py::test_process_project_pdf_retries_subpart_when_scope_auditor_rejects -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py backend/subpart_scope_auditor.py tests/backend/test_subpart_scope_auditor.py tests/backend/test_pdf_process_flow.py
git commit -m "feat: retry invalid subparts with guided rewrite context"
```

---

## Final Verification

Run the focused regression subset:

```bash
python -m pytest tests/backend/test_subpart_scope_auditor.py tests/backend/test_pdf_process_flow.py -v
```

Expected:

- The auditor helper tests pass.
- The OpenRouter retry test proves the second call reuses the same `cache_entry` and `page_numbers`.
- The existing retry flow test still passes with the richer prompt.

## Manual Validation

After the automated tests pass, validate in the app with a PDF that already has a known boundary leak:

1. Process a PDF through the normal app flow with `explainer_provider="openrouter"`.
2. Confirm in logs that OpenRouter canonical OCR is prepared once for `content_page_set`.
3. Force or observe an auditor failure for one subpart.
4. Confirm the retry prompt is built only for the failing subpart and that the retry log path still uses the same OpenRouter source/cache/page scope.
5. Confirm the retried subpart either passes audit or fails with a clearer guided second attempt than the current suffix-only behavior.

## Notes for the Implementer

- Do not broaden this plan into changing the live audit script in `tests/test_pid_00230265_subpart_scope_audit.py`. That script can be aligned later, but the user request here is the runtime retry strategy in the app.
- Do not change `MAX_SUBPART_SCOPE_AUDIT_ATTEMPTS` unless the new targeted tests show the richer retry is still too weak with one retry.
- Keep the retry brief in Spanish to match the rest of the prompt stack and existing agent instructions.

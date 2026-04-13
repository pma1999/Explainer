# OpenRouter OCR Canonical Salvage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que el OCR canónico de OpenRouter sobre `content_page_set` aproveche el primer intento global, recupere solo las páginas faltantes una a una, guarde el OCR bruto de las páginas no resueltas del primer intento y consolide todo en la misma caché reutilizable.

**Architecture:** El cambio se concentrará en [backend/openrouter_client.py](backend/openrouter_client.py): el primer priming sobre todas las páginas esperadas dejará de ser `todo o nada` y pasará a devolver un resultado parcial con páginas detectadas, páginas faltantes y un artefacto de diagnóstico con el OCR bruto del primer intento. Después, `get_or_prime_pdf_parse_cache()` recuperará únicamente las páginas faltantes una a una, fusionará los resultados en el mismo `page_index` y persistirá la caché en el mismo `cache_path` / registro de Supabase. Los consumidores de runtime ([main.py](main.py) y [tests/test_pid_00230265_subpart_scope_audit.py](tests/test_pid_00230265_subpart_scope_audit.py)) seguirán prefiriendo la vía canónica y solo degradarán al flujo local por parte si, tras la recuperación individual, siguen faltando páginas.

**Tech Stack:** Python 3.13, OpenRouter `/api/v1/chat/completions` con `file-parser`, `mistral-ocr`, Gemini page classifier / segmentador, FastAPI pipeline en [main.py](main.py), pytest, caché OCR local/Supabase.

---

## File Map

- Modify: [backend/openrouter_client.py](backend/openrouter_client.py)
  - Añadir un resultado parcial de indexado por páginas para el primer OCR global.
  - Guardar el OCR bruto / `annotations` del primer intento cuando falten páginas.
  - Cambiar la recuperación incremental para que las páginas faltantes se reintenten **una a una**.
  - Mantener la persistencia en el mismo `cache_path` / misma fila Supabase.
- Modify: [main.py](main.py)
  - Exponer en logs/usage el `diagnostic_artifact_path` y el modelo de priming realmente usado.
- Modify: [tests/backend/test_openrouter_client.py](tests/backend/test_openrouter_client.py)
  - Añadir TDD para resultado parcial, artefacto de diagnóstico y recuperación página a página.
- Modify: [tests/backend/test_main_helpers.py](tests/backend/test_main_helpers.py)
  - Verificar que `_prepare_openrouter_pdf_context()` propaga la metadata de diagnóstico.
- Modify: [tests/backend/test_pdf_process_flow.py](tests/backend/test_pdf_process_flow.py)
  - Verificar que el runtime registra el artefacto de diagnóstico cuando existe y no rompe el flujo OpenRouter.
- Modify: [tests/test_pid_00230265_subpart_scope_audit.py](tests/test_pid_00230265_subpart_scope_audit.py)
  - Imprimir o guardar la ruta del artefacto OCR cuando el primer intento global deja páginas sin resolver.

## Design Constraints

- El primer OCR canónico debe ejecutarse sobre `content_page_set`, no sobre todas las páginas numeradas del PDF.
- Si el primer OCR canónico resuelve algunas páginas, esas páginas deben conservarse; no se puede reiniciar el proceso desde cero.
- Las páginas faltantes deben reintentarse **una a una**, nunca en subgrupos contiguos.
- El OCR bruto del primer intento fallido/parcial debe quedar inspeccionable en un artefacto persistente.
- El `cache_path` o la referencia Supabase del documento deben seguir siendo los mismos; no se debe abrir una caché paralela por las páginas recuperadas.
- Debe seguir siendo compatible con el esquema documentado por OpenRouter: `annotations -> [{type:"file", file:{hash, content:[{type:"text"| "image_url", ...}]}}]`. Los marcadores `— Página X / N —` son una heurística local, no una garantía contractual del proveedor.
- No tocar el retry de subpartes, `recorrido` ni `resources` en este trabajo.

---

## Task 1: Add Partial Page-Index Parsing and Failed-Page OCR Artifacts

**Files:**
- Modify: [backend/openrouter_client.py](backend/openrouter_client.py)
- Modify: [tests/backend/test_openrouter_client.py](tests/backend/test_openrouter_client.py)

Hoy `_build_pdf_page_index()` lanza `OpenRouterError` en cuanto falta alguna página esperada. Antes de recuperar páginas individualmente, necesitamos un resultado parcial reutilizable y un artefacto que conserve el OCR bruto del primer intento.

- [ ] **Step 1: Write the failing tests**

Append to [tests/backend/test_openrouter_client.py](tests/backend/test_openrouter_client.py):

```python
from backend.openrouter_client import (
    _build_pdf_page_index_partial,
    _write_unresolved_pdf_ocr_artifact,
)


def _pdf_annotations_with_missing_marker() -> list[dict]:
    return [
        {
            "type": "file",
            "file": {
                "hash": "parsed-hash",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "— Página 2 / 10 —\n"
                            "Contenido OCR de la página 2.\n\n"
                            "Texto OCR sin marcador explícito que corresponde a la página 3.\n\n"
                            "— Página 4 / 10 —\n"
                            "Contenido OCR de la página 4."
                        ),
                    }
                ],
            },
        }
    ]


def test_build_pdf_page_index_partial_reports_missing_pages_without_raising():
    result = _build_pdf_page_index_partial(
        annotations=_pdf_annotations_with_missing_marker(),
        expected_page_numbers=(2, 3, 4),
    )

    assert tuple(page.page_number for page in result.page_index) == (2, 4)
    assert result.detected_pages == (2, 4)
    assert result.missing_pages == (3,)
    assert "Texto OCR sin marcador explícito" in result.raw_ocr_text


def test_write_unresolved_pdf_ocr_artifact_persists_missing_page_context(tmp_path):
    result = _build_pdf_page_index_partial(
        annotations=_pdf_annotations_with_missing_marker(),
        expected_page_numbers=(2, 3, 4),
    )

    artifact_path = _write_unresolved_pdf_ocr_artifact(
        cache_path=tmp_path / "sample.cache.json",
        source_sha256="sha256-test",
        engine="mistral-ocr",
        model="x-ai/grok-4.1-fast",
        expected_page_numbers=(2, 3, 4),
        annotations=_pdf_annotations_with_missing_marker(),
        build_result=result,
    )

    payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    assert payload["source_sha256"] == "sha256-test"
    assert payload["expected_pages"] == [2, 3, 4]
    assert payload["detected_pages"] == [2, 4]
    assert payload["missing_pages"] == [3]
    assert "Texto OCR sin marcador explícito" in payload["raw_ocr_text"]
    assert payload["annotations"][0]["type"] == "file"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_openrouter_client.py -v -k "partial_reports_missing_pages or unresolved_pdf_ocr_artifact"
```

Expected: FAIL because `_build_pdf_page_index_partial()` and `_write_unresolved_pdf_ocr_artifact()` do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Update [backend/openrouter_client.py](backend/openrouter_client.py):

```python
@dataclass(frozen=True, slots=True)
class OpenRouterPdfPageIndexBuildResult:
    page_index: tuple[OpenRouterPdfParsedPage, ...]
    detected_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]
    raw_ocr_text: str


def _content_parts_to_debug_text(content_parts: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for part in content_parts:
        if part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text)
    return "\n\n".join(chunks)


def _build_pdf_page_index_partial(
    *,
    annotations: list[dict[str, Any]] | None,
    expected_page_numbers: tuple[int, ...] = (),
) -> OpenRouterPdfPageIndexBuildResult:
    content_parts = _extract_pdf_annotation_content_parts(annotations)
    if not content_parts:
        raise OpenRouterError("Las annotations del PDF no contienen contenido reutilizable.")

    # Reuse the existing assignment logic, but do not raise just because some
    # expected pages could not be reconstructed in this first pass.
    page_index = _build_pdf_page_index_from_content_parts(
        content_parts=content_parts,
        expected_page_numbers=expected_page_numbers,
        allow_partial=True,
    )
    detected_pages = tuple(page.page_number for page in page_index)
    expected = _normalize_expected_page_numbers(expected_page_numbers)
    missing_pages = tuple(page for page in expected if page not in detected_pages)
    return OpenRouterPdfPageIndexBuildResult(
        page_index=page_index,
        detected_pages=detected_pages,
        missing_pages=missing_pages,
        raw_ocr_text=_content_parts_to_debug_text(content_parts),
    )


def _write_unresolved_pdf_ocr_artifact(
    *,
    cache_path: Path,
    source_sha256: str,
    engine: str,
    model: str,
    expected_page_numbers: tuple[int, ...],
    annotations: list[dict[str, Any]] | None,
    build_result: OpenRouterPdfPageIndexBuildResult,
) -> str:
    artifact_path = cache_path.with_suffix(cache_path.suffix + ".missing-pages.json")
    payload = {
        "source_sha256": source_sha256,
        "engine": engine,
        "model": model,
        "expected_pages": list(expected_page_numbers),
        "detected_pages": list(build_result.detected_pages),
        "missing_pages": list(build_result.missing_pages),
        "raw_ocr_text": build_result.raw_ocr_text,
        "annotations": annotations or [],
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with open(artifact_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return str(artifact_path)
```

Then keep `_build_pdf_page_index()` as the strict wrapper:

```python
def _build_pdf_page_index(
    *,
    annotations: list[dict[str, Any]] | None,
    expected_page_numbers: tuple[int, ...] = (),
) -> tuple[OpenRouterPdfParsedPage, ...]:
    result = _build_pdf_page_index_partial(
        annotations=annotations,
        expected_page_numbers=expected_page_numbers,
    )
    if result.missing_pages:
        raise OpenRouterError(
            "No se pudieron reconstruir todas las páginas esperadas del OCR: "
            f"{list(result.missing_pages)}"
        )
    return result.page_index
```

- [ ] **Step 4: Run the tests again**

Run:

```bash
python -m pytest tests/backend/test_openrouter_client.py -v -k "partial_reports_missing_pages or unresolved_pdf_ocr_artifact"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/openrouter_client.py tests/backend/test_openrouter_client.py
git commit -m "feat: add partial OCR page index diagnostics"
```

---

## Task 2: Salvage the Full First Pass and Recover Missing Pages One by One

**Files:**
- Modify: [backend/openrouter_client.py](backend/openrouter_client.py)
- Modify: [tests/backend/test_openrouter_client.py](tests/backend/test_openrouter_client.py)

Una vez que el primer OCR global pueda devolver éxito parcial, `get_or_prime_pdf_parse_cache()` debe aprovecharlo: conservar páginas buenas, guardar el artefacto diagnóstico y rehacer solo las páginas faltantes **una a una**.

- [ ] **Step 1: Write the failing cache-builder test**

Append to [tests/backend/test_openrouter_client.py](tests/backend/test_openrouter_client.py):

```python
def test_get_or_prime_pdf_parse_cache_salvages_first_pass_and_recovers_missing_pages_one_by_one(monkeypatch):
    temp_dir = _make_workspace_temp_dir()
    pdf_path = temp_dir / "sample.pdf"
    _write_test_pdf(pdf_path, pages=4)
    cache_dir = temp_dir / "cache"
    recovery_calls: list[tuple[int, ...]] = []

    def _fake_call_full(**kwargs):
        return type(
            "FakeResult",
            (),
            {
                "content": "OK",
                "usage": type(
                    "FakeUsage",
                    (),
                    {
                        "prompt_token_count": 1,
                        "candidates_token_count": 1,
                        "total_token_count": 2,
                    },
                )(),
                "assistant_message": type(
                    "FakeAssistant",
                    (),
                    {
                        "content": "OK",
                        "annotations": _pdf_annotations_with_marked_pages(1, 2, 4),
                    },
                )(),
            },
        )()

    def _fake_prime_group_recursive(**kwargs):
        page_numbers = tuple(kwargs["page_numbers"])
        recovery_calls.append(page_numbers)
        assert page_numbers == (3,)
        return (
            type(
                "ParsedPage",
                (),
                {
                    "page_number": 3,
                    "content_parts": (
                        {"type": "text", "text": "— Página 3 / 10 —\nContenido OCR recuperado."},
                    ),
                },
            )(),
        )

    monkeypatch.setattr("backend.openrouter_client.call_openrouter_chat_full", _fake_call_full)
    monkeypatch.setattr(
        "backend.openrouter_client._prime_pdf_page_group_recursive",
        _fake_prime_group_recursive,
    )

    try:
        cache_entry = get_or_prime_pdf_parse_cache(
            source_path=str(pdf_path),
            api_key="sk-or-v1-test",
            model="test/model",
            engine="mistral-ocr",
            cache_dir=str(cache_dir),
            expected_page_numbers=(1, 2, 3, 4),
        )
        assert recovery_calls == [(3,)]
        assert cache_entry.cached_page_numbers == (1, 2, 3, 4)
        assert cache_entry.assistant_message is not None
        assert cache_entry.diagnostic_artifact_path is not None
        assert Path(cache_entry.diagnostic_artifact_path).is_file()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/backend/test_openrouter_client.py::test_get_or_prime_pdf_parse_cache_salvages_first_pass_and_recovers_missing_pages_one_by_one -v
```

Expected: FAIL because the current implementation still groups missing pages contiguously and treats the first pass as strict/all-or-nothing.

- [ ] **Step 3: Write the minimal implementation**

Update [backend/openrouter_client.py](backend/openrouter_client.py):

```python
@dataclass(frozen=True, slots=True)
class OpenRouterPdfParseCacheEntry:
    source_sha256: str
    engine: str
    assistant_message: OpenRouterAssistantMessage | None
    cache_path: str
    cache_hit: bool
    expected_page_numbers: tuple[int, ...] = ()
    cached_page_numbers: tuple[int, ...] = ()
    page_index: tuple["OpenRouterPdfParsedPage", ...] = ()
    diagnostic_artifact_path: str | None = None


def _prime_pdf_expected_pages_once(
    *,
    source_path: str,
    page_numbers: tuple[int, ...],
    api_key: str,
    model: str,
    engine: str,
    filename: str,
    max_retries: int,
) -> tuple[OpenRouterAssistantMessage, OpenRouterPdfPageIndexBuildResult]:
    chunk_pdf_path = extract_pages(source_path, page_numbers)
    try:
        result = call_openrouter_chat_full(
            messages=[{"role": "user", "content": _build_pdf_file_content(
                source_path=chunk_pdf_path,
                filename=filename,
                text=_parse_cache_user_text(),
            )}],
            model=model,
            system_prompt=_parse_cache_system_prompt(),
            api_key=api_key,
            response_format="text",
            plugins=[{"id": "file-parser", "pdf": {"engine": engine}}],
            enable_response_healing=False,
            reasoning=None,
            max_retries=max_retries,
        )
        if not result.assistant_message.annotations:
            raise OpenRouterError(
                "OpenRouter no devolvió annotations reutilizables al parsear el PDF."
            )
        return result.assistant_message, _build_pdf_page_index_partial(
            annotations=result.assistant_message.annotations,
            expected_page_numbers=page_numbers,
        )
    finally:
        os.unlink(chunk_pdf_path)
```

Then replace the `missing_pages` priming loop inside `get_or_prime_pdf_parse_cache()` with a full-pass-first salvage flow:

```python
diagnostic_artifact_path: str | None = None

if missing_pages and not page_index:
    assistant_message, build_result = _prime_pdf_expected_pages_once(
        source_path=source_path,
        page_numbers=effective_expected_pages,
        api_key=api_key,
        model=model,
        engine=engine,
        filename=file_name,
        max_retries=max_retries,
    )
    page_index = _merge_page_indexes(page_index, build_result.page_index)
    missing_pages = build_result.missing_pages
    if missing_pages:
        diagnostic_artifact_path = _write_unresolved_pdf_ocr_artifact(
            cache_path=cache_path,
            source_sha256=source_sha256,
            engine=engine,
            model=model,
            expected_page_numbers=effective_expected_pages,
            annotations=assistant_message.annotations,
            build_result=build_result,
        )

if missing_pages:
    for page_number in missing_pages:
        primed_pages = _prime_pdf_page_group_recursive(
            source_path=source_path,
            page_numbers=(page_number,),
            api_key=api_key,
            model=model,
            engine=engine,
            filename=file_name,
            max_retries=max_retries,
        )
        page_index = _merge_page_indexes(page_index, primed_pages)

cached_page_numbers = _page_numbers_from_index(page_index)
remaining_missing = tuple(
    page for page in effective_expected_pages if page not in set(cached_page_numbers)
)
if remaining_missing:
    raise OpenRouterError(
        "El OCR canónico sigue incompleto tras la recuperación individual: "
        f"{list(remaining_missing)}"
    )
```

Return `diagnostic_artifact_path` in the final `OpenRouterPdfParseCacheEntry`.

- [ ] **Step 4: Run the targeted test again**

Run:

```bash
python -m pytest tests/backend/test_openrouter_client.py::test_get_or_prime_pdf_parse_cache_salvages_first_pass_and_recovers_missing_pages_one_by_one -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/openrouter_client.py tests/backend/test_openrouter_client.py
git commit -m "feat: salvage canonical OCR and recover missing pages individually"
```

---

## Task 3: Surface Diagnostic Metadata in Runtime and the Live Audit Script

**Files:**
- Modify: [main.py](main.py)
- Modify: [tests/backend/test_main_helpers.py](tests/backend/test_main_helpers.py)
- Modify: [tests/backend/test_pdf_process_flow.py](tests/backend/test_pdf_process_flow.py)
- Modify: [tests/test_pid_00230265_subpart_scope_audit.py](tests/test_pid_00230265_subpart_scope_audit.py)

Una vez que el caché canónico se recupere parcialmente, el runtime y el script live deben exponer dónde quedó guardado el OCR bruto problemático, sin dejar de comportarse como la app actual.

- [ ] **Step 1: Write the failing helper/runtime tests**

Append to [tests/backend/test_main_helpers.py](tests/backend/test_main_helpers.py):

```python
def test_prepare_openrouter_pdf_context_exposes_diagnostic_artifact_path(monkeypatch):
    import main as m

    fake_cache_entry = SimpleNamespace(
        cache_hit=False,
        cache_path="cache.json",
        expected_page_numbers=(1, 3),
        cached_page_numbers=(1, 3),
        diagnostic_artifact_path="cache.json.missing-pages.json",
    )

    monkeypatch.setattr(
        m,
        "prime_pdf_parse_cache_with_fallback",
        lambda **kwargs: (fake_cache_entry, m.OPENROUTER_PDF_PRIMING_FALLBACK_MODEL),
    )

    context = m._prepare_openrouter_pdf_context(
        numbered_pdf_path="document-numbered.pdf",
        content_page_set=frozenset({1, 3}),
        api_key="sk-or-v1-test",
        engine="mistral-ocr",
    )

    assert context.cache_entry.diagnostic_artifact_path == "cache.json.missing-pages.json"
    assert context.priming_model == m.OPENROUTER_PDF_PRIMING_FALLBACK_MODEL
```

Append to [tests/backend/test_pdf_process_flow.py](tests/backend/test_pdf_process_flow.py):

```python
def test_process_project_pdf_records_openrouter_ocr_diagnostic_artifact_when_present(monkeypatch):
    pdf_path = _create_multi_page_pdf(4)
    try:
        project = {
            "id": "proj-openrouter-diagnostic-artifact",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }
        updates = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "sk-or-v1-test" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(main, "update_project", lambda pid, uid, payload: updates.append(payload))
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)
        monkeypatch.setattr(main, "send_event", lambda *args, **kwargs: None)
        monkeypatch.setattr(main, "sse_manager", SimpleNamespace(end_stream=lambda project_id: None))
        monkeypatch.setattr(main, "run_page_classifier", lambda *args, **kwargs: (frozenset([1, 2, 3, 4]), _usage(), {}))
        monkeypatch.setattr(
            main,
            "_prepare_openrouter_pdf_context",
            lambda **kwargs: main.OpenRouterPreparedPdfContext(
                source_pdf_path=pdf_path,
                cache_entry=OpenRouterPdfParseCacheEntry(
                    source_sha256="sha256",
                    engine="mistral-ocr",
                    assistant_message=None,
                    cache_path="cache.json",
                    cache_hit=False,
                    expected_page_numbers=(1, 2, 3, 4),
                    cached_page_numbers=(1, 2, 3, 4),
                    page_index=(),
                    diagnostic_artifact_path="cache.json.missing-pages.json",
                ),
            ),
        )
        monkeypatch.setattr(main, "run_segmentador", lambda *args, **kwargs: ({
            "analisis_texto": "Cuatro páginas",
            "temas_identificados": ["tema1"],
            "decision_num_partes": 1,
            "decision_justificacion": "Una parte",
            "partes": [_part_pdf_fields(1, "Única", 1, 4)],
            "consideraciones_estudiante": "Seguir el orden natural",
        }, _usage(total=40)))
        monkeypatch.setattr(main, "run_explainer_or", lambda *args, **kwargs: ({
            "introduccion": "Intro",
            "desarrollo": [],
            "conclusion": "Cierre",
            "conexiones_contextuales": [],
        }, _usage(total=27)))
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "format_explainer_content", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Use async fake in implementation")))

        asyncio.run(main._process_project("proj-openrouter-diagnostic-artifact", "user-123", explainer_provider="openrouter"))

        usage_updates = [payload["usage"] for payload in updates if "usage" in payload]
        assert usage_updates[0]["openrouter_pdf_ocr_diagnostic_artifact"] == "cache.json.missing-pages.json"
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_main_helpers.py -v -k "diagnostic_artifact_path" && python -m pytest tests/backend/test_pdf_process_flow.py -v -k "diagnostic_artifact"
```

Expected: FAIL because the runtime does not yet surface `diagnostic_artifact_path`.

- [ ] **Step 3: Write the minimal implementation**

Update [main.py](main.py):

```python
def _prepare_openrouter_pdf_context(
    *,
    numbered_pdf_path: str,
    content_page_set: frozenset[int],
    api_key: str,
    engine: str,
) -> "OpenRouterPreparedPdfContext":
    cache_entry, priming_model = prime_pdf_parse_cache_with_fallback(
        source_path=numbered_pdf_path,
        api_key=api_key,
        engine=engine,
        filename="document.pdf",
        expected_page_numbers=tuple(sorted(content_page_set)),
    )
    return OpenRouterPreparedPdfContext(
        source_pdf_path=numbered_pdf_path,
        cache_entry=cache_entry,
        priming_model=priming_model,
    )
```

Then surface the artifact path in `_process_project()`:

```python
if openrouter_pdf_prepare_task is not None:
    try:
        openrouter_pdf_context = await openrouter_pdf_prepare_task
        cumulative_usage["openrouter_pdf_priming_model"] = openrouter_pdf_context.priming_model
        if openrouter_pdf_context.cache_entry.diagnostic_artifact_path:
            cumulative_usage["openrouter_pdf_ocr_diagnostic_artifact"] = (
                openrouter_pdf_context.cache_entry.diagnostic_artifact_path
            )
        logger.info(
            "[Process] OCR canónico OpenRouter preparado",
            extra={
                "source_pdf_path": openrouter_pdf_context.source_pdf_path,
                "priming_model": openrouter_pdf_context.priming_model,
                "cache_path": openrouter_pdf_context.cache_entry.cache_path,
                "cache_hit": openrouter_pdf_context.cache_entry.cache_hit,
                "requested_pages_count": len(openrouter_pdf_context.cache_entry.expected_page_numbers),
                "cached_pages_count": len(openrouter_pdf_context.cache_entry.cached_page_numbers),
                "diagnostic_artifact_path": openrouter_pdf_context.cache_entry.diagnostic_artifact_path,
            },
        )
```

Update [tests/test_pid_00230265_subpart_scope_audit.py](tests/test_pid_00230265_subpart_scope_audit.py):

```python
if or_pdf_ctx is not None and or_pdf_ctx.cache_entry.diagnostic_artifact_path:
    print(
        f"[INFO] OCR unresolved-page artifact: {or_pdf_ctx.cache_entry.diagnostic_artifact_path}",
        file=sys.stderr,
    )
```

Use an async formatter fake in the new flow test implementation:

```python
async def _fake_format(api_key, explainer_data):
    return explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}
```

- [ ] **Step 4: Run the tests again**

Run:

```bash
python -m pytest tests/backend/test_main_helpers.py -v -k "diagnostic_artifact_path" && python -m pytest tests/backend/test_pdf_process_flow.py -v -k "diagnostic_artifact"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/backend/test_main_helpers.py tests/backend/test_pdf_process_flow.py tests/test_pid_00230265_subpart_scope_audit.py
git commit -m "feat: surface canonical OCR diagnostic artifacts"
```

---

## Task 4: Verify the Canonical Salvage Path End-to-End

**Files:**
- Modify: [tests/backend/test_openrouter_client.py](tests/backend/test_openrouter_client.py) if any assertions need tightening after implementation
- Modify: [tests/backend/test_pdf_process_flow.py](tests/backend/test_pdf_process_flow.py) if any flow assertions need tightening after implementation
- Exercise: [tests/test_pid_00230265_subpart_scope_audit.py](tests/test_pid_00230265_subpart_scope_audit.py)

Esta tarea no añade comportamiento nuevo; deja cerrada la verificación y asegura que el flujo real ya no descarta las páginas buenas del primer intento ni oculta el OCR problemático.

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
python -m pytest \
  tests/backend/test_openrouter_client.py::test_build_pdf_page_index_partial_reports_missing_pages_without_raising \
  tests/backend/test_openrouter_client.py::test_write_unresolved_pdf_ocr_artifact_persists_missing_page_context \
  tests/backend/test_openrouter_client.py::test_get_or_prime_pdf_parse_cache_salvages_first_pass_and_recovers_missing_pages_one_by_one \
  tests/backend/test_main_helpers.py::test_prepare_openrouter_pdf_context_exposes_diagnostic_artifact_path \
  tests/backend/test_pdf_process_flow.py::test_process_project_pdf_records_openrouter_ocr_diagnostic_artifact_when_present \
  tests/backend/test_pdf_process_flow.py::test_process_project_pdf_openrouter_retry_reuses_cache_and_includes_rewrite_brief \
  -v
```

Expected:

- `PASS` en todos los tests.
- Sin errores de lint nuevos.
- El test OpenRouter de retry sigue verde, demostrando que la reutilización de `cache_entry` no se rompe.

- [ ] **Step 2: Run the live audit script**

Run:

```bash
python tests/test_pid_00230265_subpart_scope_audit.py
```

Expected:

- No traceback.
- Se imprime la ruta de `test_output/pid_00230265_subpart_scope_audit.json`.
- Si el primer OCR global deja páginas sin resolver, se imprime también una línea como:

```text
[INFO] OCR unresolved-page artifact: <cache-or-test-output-path>.missing-pages.json
```

- [ ] **Step 3: Inspect the generated artifact manually**

Open the emitted artifact and confirm:

```json
{
  "source_sha256": "...",
  "engine": "mistral-ocr",
  "model": "x-ai/grok-4.1-fast",
  "expected_pages": [/* ... */],
  "detected_pages": [/* ... */],
  "missing_pages": [/* ... */],
  "raw_ocr_text": "...",
  "annotations": [/* raw OpenRouter annotations */]
}
```

Check specifically that `raw_ocr_text` preserves the exact OCR text returned in the first global attempt for the unresolved page set, so marker failures can be diagnosed without rerunning blindly.

- [ ] **Step 4: Commit**

```bash
git add backend/openrouter_client.py main.py tests/backend/test_openrouter_client.py tests/backend/test_main_helpers.py tests/backend/test_pdf_process_flow.py tests/test_pid_00230265_subpart_scope_audit.py
git commit -m "feat: salvage canonical OCR and persist failed-page diagnostics"
```

---

## Final Verification

Run the focused subset that covers the canonical OCR salvage path and the existing OpenRouter retry path:

```bash
python -m pytest \
  tests/backend/test_openrouter_client.py::test_build_pdf_page_index_partial_reports_missing_pages_without_raising \
  tests/backend/test_openrouter_client.py::test_write_unresolved_pdf_ocr_artifact_persists_missing_page_context \
  tests/backend/test_openrouter_client.py::test_get_or_prime_pdf_parse_cache_salvages_first_pass_and_recovers_missing_pages_one_by_one \
  tests/backend/test_main_helpers.py::test_prepare_openrouter_pdf_context_exposes_diagnostic_artifact_path \
  tests/backend/test_pdf_process_flow.py::test_process_project_pdf_records_openrouter_ocr_diagnostic_artifact_when_present \
  tests/backend/test_pdf_process_flow.py::test_process_project_pdf_openrouter_retry_reuses_cache_and_includes_rewrite_brief \
  -v

python tests/test_pid_00230265_subpart_scope_audit.py
```

Expected:

- The first canonical OCR pass can succeed partially without discarding resolved pages.
- Missing pages are retried one by one and merged back into the same cache entry.
- The unresolved-page OCR artifact is persisted deterministically when needed.
- The main pipeline exposes the artifact path in runtime metadata.
- The live audit script behaves like the app and no longer aborts just because canonical OCR prep was incomplete.

## Manual Validation

After the focused commands pass:

1. Run a real PDF through the app with `explainer_provider="openrouter"`.
2. Confirm logs show the canonical OCR prep start over `content_page_set`.
3. Force or observe a partial first pass where some pages are unresolved.
4. Confirm a `.missing-pages.json` diagnostic artifact is emitted.
5. Confirm only the unresolved pages are re-primed one by one.
6. Confirm the final cache entry contains all expected pages and is reused on the next run.

## Notes for the Implementer

- Reuse the strict `_build_pdf_page_index()` wrapper for callers that still need fail-fast semantics; introduce the partial builder alongside it instead of changing every caller at once.
- Do not broaden this into changing the page classifier or segmentador. The scope is the OpenRouter OCR cache builder and the runtime metadata around it.
- Be careful not to reintroduce the old “group contiguous missing pages” behavior in the recovery phase; the user explicitly wants per-page retries after the first full pass.

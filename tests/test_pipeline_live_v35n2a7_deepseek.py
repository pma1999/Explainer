"""Live end-to-end DeepSeek direct pipeline on v35n2a7.pdf — one part, all subparts.

Mirrors the production text-provider flow (Mistral OCR → classifier → segmentador →
subpart explainers + recorrido + resources) without Gemini upload.

Usage:
    python -m tests.test_pipeline_live_v35n2a7_deepseek

Environment:
    DEEPSEEK_API_KEY   (required)
    TAVILY_API_KEY     (required for resources)
    MISTRAL_API_KEY    (required for PDF OCR)

Optional:
    DEEPSEEK_EXPLAINER_MODEL_OVERRIDE  default: deepseek-v4-pro
    LIVE_DS_PART_NUMBER                default: 1 (first segmented part)
    LIVE_DS_TARGET_LANGUAGE            default: es-ES
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv(override=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
PDF_PATH = os.path.join(PROJECT_ROOT, "v35n2a7.pdf")
PART_NUMBER = int(os.environ.get("LIVE_DS_PART_NUMBER", "1"))
TARGET_LANGUAGE = os.environ.get("LIVE_DS_TARGET_LANGUAGE", "es-ES").strip() or "es-ES"
EXPLAINER_MODEL = (
    os.environ.get("DEEPSEEK_EXPLAINER_MODEL_OVERRIDE", "deepseek-v4-pro").strip()
    or "deepseek-v4-pro"
)


def _setup_logging(output_dir: str) -> logging.Logger:
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "pipeline.log")

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(LOG_FMT)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.DEBUG)
    root.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    for lib in ("httpx", "httpcore", "google", "urllib3", "filelock", "requests"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    log = logging.getLogger("test_pipeline_ds_v35")
    log.info("Log file: %s", log_path)
    return log


def _tokens_ds(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        "prompt": getattr(usage, "prompt_token_count", 0) or 0,
        "completion": getattr(usage, "candidates_token_count", 0) or 0,
        "thoughts": getattr(usage, "thoughts_token_count", 0) or 0,
        "total": getattr(usage, "total_token_count", 0) or 0,
    }


def _save_json(label: str, data: Any, output_dir: str) -> str:
    path = os.path.join(output_dir, f"{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _save_text(label: str, content: str, output_dir: str) -> str:
    path = os.path.join(output_dir, f"{label}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _optional_int(item: dict, key: str) -> int | None:
    value = item.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_parte_by_numero(partes: list[dict], numero: int) -> dict | None:
    for parte in partes:
        if parte.get("numero") == numero:
            return parte
    return None


def main() -> int:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(PROJECT_ROOT, "test_output", f"live_ds_v35n2a7_{run_id}")
    log = _setup_logging(output_dir)

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()
    mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()

    if not deepseek_key:
        log.error("DEEPSEEK_API_KEY no configurada")
        return 1
    if not tavily_key:
        log.error("TAVILY_API_KEY no configurada (requerida para resources DeepSeek)")
        return 1
    if not mistral_key:
        log.error("MISTRAL_API_KEY no configurada (requerida para OCR PDF)")
        return 1
    if not os.path.isfile(PDF_PATH):
        log.error("PDF no encontrado: %s", PDF_PATH)
        return 1

    report: dict[str, Any] = {
        "run_id": run_id,
        "pdf_path": PDF_PATH,
        "explainer_provider": "deepseek",
        "explainer_model": EXPLAINER_MODEL,
        "target_language": TARGET_LANGUAGE,
        "part_number": PART_NUMBER,
        "steps": [],
        "status": "running",
    }
    pipeline_start = time.time()

    try:
        from backend.agents.explainer_deepseek import (
            run_subpart_explainer_ds_validated,
        )
        from backend.agents.page_classifier import run_page_classifier_ds
        from backend.agents.recorrido import run_recorrido_ds
        from backend.agents.resources import run_resources_ds
        from backend.agents.segmentador import DEFAULT_DESCRIPTION, run_segmentador_ds
        from backend.mistral_ocr_client import MISTRAL_OCR_ENGINE
        from main import (
            MISTRAL_OCR_MODEL,
            _assemble_part_explainer,
            _build_content_pages_prefix,
            _build_pdf_agent_prompt,
            _build_pdf_table_of_contents,
            _build_subpart_pdf_prompt,
            _continuity_block_from_previous_part,
            _find_parte_by_numero,
            _part_handoff_base,
            _prepare_mistral_pdf_ocr_context,
            _render_mistral_ocr_pages_for_agents,
            _select_openrouter_pdf_pages,
        )

        total_pages = len(PdfReader(PDF_PATH).pages)
        log.info("=" * 80)
        log.info("CONFIG | pdf=%s | pages=%d | part=%d | model=%s | lang=%s", PDF_PATH, total_pages, PART_NUMBER, EXPLAINER_MODEL, TARGET_LANGUAGE)
        log.info("Output dir: %s", output_dir)
        log.info("=" * 80)

        # STEP 1 — Mistral OCR (full document, like main.py text-provider bootstrap)
        log.info("STEP 1: Mistral OCR canónico (documento completo)")
        t0 = time.time()
        mistral_ctx = _prepare_mistral_pdf_ocr_context(
            source_path=PDF_PATH,
            content_page_set=frozenset(range(1, total_pages + 1)),
            api_key=mistral_key,
            engine=MISTRAL_OCR_ENGINE,
        )
        full_source_text = _render_mistral_ocr_pages_for_agents(
            cache_entry=mistral_ctx.cache_entry,
            page_numbers=tuple(range(1, total_pages + 1)),
        )
        step1_ms = int((time.time() - t0) * 1000)
        log.info(
            "OCR listo en %dms | cache_hit=%s | cached_pages=%d | chars=%d",
            step1_ms,
            mistral_ctx.cache_entry.cache_hit,
            len(mistral_ctx.cache_entry.cached_page_numbers),
            len(full_source_text),
        )
        _save_text("01_ocr_full_source_excerpt", full_source_text[:12000], output_dir)
        report["steps"].append(
            {
                "step": "mistral_ocr",
                "duration_ms": step1_ms,
                "cache_hit": mistral_ctx.cache_entry.cache_hit,
                "cached_pages": list(mistral_ctx.cache_entry.cached_page_numbers),
                "source_chars": len(full_source_text),
            }
        )

        # STEP 2 — Page classifier (DeepSeek)
        log.info("STEP 2: Page classifier (DeepSeek direct)")
        t0 = time.time()
        content_pages, clf_usage, clf_raw = run_page_classifier_ds(
            deepseek_key,
            full_source_text,
            total_pages,
        )
        step2_ms = int((time.time() - t0) * 1000)
        log.info(
            "Classifier en %dms | content_pages=%d/%d | tokens=%s",
            step2_ms,
            len(content_pages),
            total_pages,
            _tokens_ds(clf_usage),
        )
        _save_json("02_page_classifier", clf_raw, output_dir)
        report["steps"].append(
            {
                "step": "page_classifier_ds",
                "duration_ms": step2_ms,
                "content_pages": sorted(content_pages),
                "tokens": _tokens_ds(clf_usage),
            }
        )

        # STEP 3 — Segmentador (DeepSeek)
        log.info("STEP 3: Segmentador (DeepSeek direct)")
        content_prefix = _build_content_pages_prefix(content_pages, total_pages)
        seg_description = content_prefix + DEFAULT_DESCRIPTION
        t0 = time.time()
        segmentation, seg_usage = run_segmentador_ds(
            deepseek_key,
            full_source_text,
            seg_description,
            source_kind="pdf",
            target_language=TARGET_LANGUAGE,
        )
        step3_ms = int((time.time() - t0) * 1000)
        num_partes = len(segmentation.get("partes", []))
        log.info("Segmentador en %dms | partes=%d | tokens=%s", step3_ms, num_partes, _tokens_ds(seg_usage))
        _save_json("03_segmentation", segmentation, output_dir)
        report["steps"].append(
            {
                "step": "segmentador_ds",
                "duration_ms": step3_ms,
                "num_partes": num_partes,
                "tokens": _tokens_ds(seg_usage),
            }
        )

        for parte in segmentation.get("partes", []):
            subpartes = parte.get("subpartes") or []
            log.info(
                '  Parte %s: "%s" (pp.%s-%s) — %d subparte(s)',
                parte.get("numero"),
                parte.get("titulo"),
                parte.get("pagina_inicio", "?"),
                parte.get("pagina_fin", "?"),
                len(subpartes),
            )
            for sp in subpartes:
                log.info(
                    '    SP %s: "%s" (pp.%s-%s)',
                    sp.get("numero_subparte"),
                    sp.get("titulo"),
                    sp.get("pagina_inicio", "?"),
                    sp.get("pagina_fin", "?"),
                )

        target_parte = _find_parte_by_numero(segmentation.get("partes", []), PART_NUMBER)
        if target_parte is None:
            raise RuntimeError(f"Parte {PART_NUMBER} no encontrada en la segmentación ({num_partes} partes)")

        part_id = target_parte["numero"]
        subpartes = list(target_parte.get("subpartes") or [])
        table_of_contents = _build_pdf_table_of_contents(segmentation, num_partes)
        nucleo_pi = _optional_int(target_parte, "pagina_inicio")
        nucleo_pf = _optional_int(target_parte, "pagina_fin")
        pdf_scope_mode = "subpdf_buffered" if nucleo_pi and nucleo_pf else "full_document"

        consideraciones = segmentation.get("consideraciones_estudiante", "")
        continuidad_previa = None
        if part_id > 1:
            prev = _find_parte_by_numero(segmentation["partes"], part_id - 1)
            if prev:
                continuidad_previa = _continuity_block_from_previous_part(prev)

        handoff = _part_handoff_base(
            target_parte,
            intent_usuario="",
            continuidad_previa=continuidad_previa,
            vision_global_division=consideraciones if part_id == 1 else None,
        )

        identificacion = str(target_parte.get("identificacion") or "").strip()
        agent_prompt = _build_pdf_agent_prompt(
            table_of_contents,
            identificacion,
            part_id,
            num_partes,
            handoff,
            target_parte,
            segmentation["partes"],
            pdf_scope_mode=pdf_scope_mode,
            nucleo_inicio=nucleo_pi,
            nucleo_fin=nucleo_pf,
        )
        _save_text("04_part_agent_prompt", agent_prompt, output_dir)

        part_pages = _select_openrouter_pdf_pages(
            content_pages,
            start_page=nucleo_pi,
            end_page=nucleo_pf,
            buffer=1,
        )
        part_source_text = _render_mistral_ocr_pages_for_agents(
            cache_entry=mistral_ctx.cache_entry,
            page_numbers=part_pages,
        )
        _save_text("04_part_ocr_source_excerpt", part_source_text[:12000], output_dir)
        log.info("Parte %d OCR pages for recorrido/resources: %s", part_id, list(part_pages))

        if not subpartes:
            subpartes = [
                {
                    "numero_subparte": 1,
                    "titulo": target_parte.get("titulo", ""),
                    "contenido": target_parte.get("contenido", ""),
                    "identificacion": identificacion,
                    "pagina_inicio": nucleo_pi,
                    "pagina_fin": nucleo_pf,
                }
            ]
            log.warning("Sin subpartes — usando la parte entera como una subparte")

        page_scopes = [
            _select_openrouter_pdf_pages(
                content_pages,
                start_page=_optional_int(sp, "pagina_inicio") or nucleo_pi,
                end_page=_optional_int(sp, "pagina_fin") or nucleo_pf,
                buffer=1,
            )
            for sp in subpartes
        ]
        subpart_prompts = [
            _build_subpart_pdf_prompt(
                table_of_contents,
                target_parte,
                sp,
                subpartes,
                part_id,
                num_partes,
                handoff,
                pdf_scope_mode=pdf_scope_mode,
                nucleo_inicio=nucleo_pi,
                nucleo_fin=nucleo_pf,
            )
            for sp in subpartes
        ]

        scope_report = []
        for idx, (sp, pages, prompt) in enumerate(zip(subpartes, page_scopes, subpart_prompts), start=1):
            scope_report.append(
                {
                    "subparte": sp.get("numero_subparte", idx),
                    "titulo": sp.get("titulo"),
                    "pagina_inicio": sp.get("pagina_inicio"),
                    "pagina_fin": sp.get("pagina_fin"),
                    "ocr_pages": list(pages),
                    "prompt_chars": len(prompt),
                }
            )
            _save_text(f"05_subparte_{idx:02d}_prompt", prompt, output_dir)
        _save_json("05_subpart_scopes", scope_report, output_dir)

        # STEP 4 — Subpart explainers (DeepSeek validated)
        log.info("STEP 4: Explainer subpartes (DeepSeek direct, %d subpartes)", len(subpartes))
        subpart_desarrollos: list[list[dict]] = []
        explainer_records: list[dict[str, Any]] = []

        for idx, (sp, sp_prompt, page_scope) in enumerate(
            zip(subpartes, subpart_prompts, page_scopes), start=1
        ):
            log.info("-" * 60)
            log.info(
                'Subparte %d/%d: "%s" | OCR pages=%s | prompt_chars=%d',
                idx,
                len(subpartes),
                sp.get("titulo", "?"),
                list(page_scope),
                len(sp_prompt),
            )
            t0 = time.time()
            try:
                sp_result, sp_usage, validator_usages = run_subpart_explainer_ds_validated(
                    source_path=mistral_ctx.source_pdf_path,
                    identificacion=sp_prompt,
                    model=EXPLAINER_MODEL,
                    mime_type="application/pdf",
                    api_key=deepseek_key,
                    validator_api_key=deepseek_key,
                    pdf_cache_entry=mistral_ctx.cache_entry,
                    page_numbers=page_scope,
                    target_language=TARGET_LANGUAGE,
                )
                sp_ms = int((time.time() - t0) * 1000)
                desarrollo = sp_result.get("desarrollo", [])
                subpart_desarrollos.append(desarrollo)
                artifact = _save_json(f"06_subparte_{idx:02d}_explainer", sp_result, output_dir)
                record = {
                    "subparte": idx,
                    "status": "ok",
                    "duration_ms": sp_ms,
                    "artifact": artifact,
                    "sections": len(desarrollo),
                    "subsections": sum(len(s.get("subsecciones") or []) for s in desarrollo),
                    "tokens": _tokens_ds(sp_usage),
                    "validator_runs": len(validator_usages or []),
                }
                explainer_records.append(record)
                log.info(
                    "Subparte %d OK en %dms | secciones=%d | tokens=%s | validator_runs=%d",
                    idx,
                    sp_ms,
                    record["sections"],
                    record["tokens"],
                    record["validator_runs"],
                )
            except Exception as exc:
                sp_ms = int((time.time() - t0) * 1000)
                err_path = _save_text(
                    f"06_subparte_{idx:02d}_explainer_ERROR",
                    traceback.format_exc(),
                    output_dir,
                )
                record = {
                    "subparte": idx,
                    "status": "error",
                    "duration_ms": sp_ms,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback_file": err_path,
                }
                explainer_records.append(record)
                log.error("Subparte %d FAILED: %s", idx, exc, exc_info=True)

        report["steps"].append({"step": "subpart_explainers_ds", "records": explainer_records})

        failed_explainers = [r for r in explainer_records if r.get("status") != "ok"]
        if failed_explainers:
            raise RuntimeError(f"{len(failed_explainers)} subparte(s) del explainer fallaron")

        # STEP 5 — Recorrido + Resources (parallel conceptually, sequential here for logs)
        log.info("STEP 5: Recorrido (DeepSeek direct)")
        t0 = time.time()
        recorrido_result, recorrido_usage = run_recorrido_ds(
            deepseek_key,
            part_source_text,
            agent_prompt,
            target_language=TARGET_LANGUAGE,
        )
        rec_ms = int((time.time() - t0) * 1000)
        _save_json("07_recorrido", recorrido_result, output_dir)
        log.info(
            "Recorrido OK en %dms | entradas=%d | tokens=%s",
            rec_ms,
            len(recorrido_result.get("recorrido_anotado", [])),
            _tokens_ds(recorrido_usage),
        )
        report["steps"].append(
            {
                "step": "recorrido_ds",
                "duration_ms": rec_ms,
                "entries": len(recorrido_result.get("recorrido_anotado", [])),
                "tokens": _tokens_ds(recorrido_usage),
            }
        )

        log.info("STEP 6: Resources (DeepSeek + Tavily)")
        t0 = time.time()
        resources_result, resources_usage = run_resources_ds(
            deepseek_key,
            tavily_key,
            part_source_text,
            agent_prompt,
            target_language=TARGET_LANGUAGE,
        )
        res_ms = int((time.time() - t0) * 1000)
        _save_json("08_resources", resources_result, output_dir)
        log.info(
            "Resources OK en %dms | ejes=%d | tokens=%s",
            res_ms,
            len(resources_result.get("mapa_recursos", {}).get("ejes", []))
            if isinstance(resources_result.get("mapa_recursos"), dict)
            else 0,
            _tokens_ds(resources_usage),
        )
        report["steps"].append(
            {
                "step": "resources_ds",
                "duration_ms": res_ms,
                "tokens": _tokens_ds(resources_usage),
            }
        )

        # STEP 7 — Assemble part explainer
        log.info("STEP 7: Ensamblado final de la parte %d", part_id)
        assembled = _assemble_part_explainer(target_parte, subpart_desarrollos)
        _save_json("09_assembled_part_explainer", assembled, output_dir)
        desarrollo = assembled.get("desarrollo", [])
        total_words = 0
        for sec in desarrollo:
            for sub in sec.get("subsecciones") or []:
                total_words += len(str(sub.get("explicacion_detallada", "")).split())
        log.info(
            "Ensamblado: secciones=%d | ~%d palabras en desarrollo | intro=%d chars | conclusion=%d chars",
            len(desarrollo),
            total_words,
            len(assembled.get("introduccion", "")),
            len(assembled.get("conclusion", "")),
        )

        report["status"] = "success"
        report["total_duration_ms"] = int((time.time() - pipeline_start) * 1000)
        report["assembled_metrics"] = {
            "sections": len(desarrollo),
            "body_words_approx": total_words,
            "intro_chars": len(assembled.get("introduccion", "")),
            "conclusion_chars": len(assembled.get("conclusion", "")),
        }
        _save_json("00_run_report", report, output_dir)

        log.info("=" * 80)
        log.info("DONE — status=success | total_ms=%d | output=%s", report["total_duration_ms"], output_dir)
        log.info("=" * 80)
        return 0

    except Exception as exc:
        report["status"] = "failed"
        report["total_duration_ms"] = int((time.time() - pipeline_start) * 1000)
        report["error_type"] = type(exc).__name__
        report["error_message"] = str(exc)
        report["traceback"] = traceback.format_exc()
        _save_json("00_run_report", report, output_dir)
        log.error("PIPELINE FAILED: %s", exc, exc_info=True)
        log.info("Partial artifacts in %s", output_dir)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

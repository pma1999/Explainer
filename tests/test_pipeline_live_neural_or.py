"""Live pipeline test: page_classifier → segmentador → subpart_explainer_or (OpenRouter JSON mode).

Identical flow to test_pipeline_live_neural.py except Step 4 uses
run_subpart_explainer_or (OpenRouter, xiaomi/mimo-v2-flash, `json_object`)
instead of the Gemini explainer. Results are saved with an '_or_' prefix
so both outputs coexist for comparison.

Usage:
    python tests/test_pipeline_live_neural_or.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv(override=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
logging.basicConfig(level=logging.DEBUG, format=LOG_FMT, stream=sys.stdout)
for _lib in ("httpx", "httpcore", "google", "urllib3", "filelock", "requests"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

log = logging.getLogger("test_pipeline_or")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens_gemini(usage) -> dict:
    if usage is None:
        return {}
    return {
        "prompt": getattr(usage, "prompt_token_count", 0) or 0,
        "candidates": getattr(usage, "candidates_token_count", 0) or 0,
        "thoughts": getattr(usage, "thoughts_token_count", 0) or 0,
        "total": getattr(usage, "total_token_count", 0) or 0,
    }


def _tokens_or(usage) -> dict:
    return {
        "prompt": usage.prompt_token_count,
        "completion": usage.candidates_token_count,
        "total": usage.total_token_count,
    }


def _save_json(label: str, data: dict, output_dir: str) -> str:
    path = os.path.join(output_dir, f"{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved %s → %s (%d bytes)", label, path, os.path.getsize(path))
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        log.error("GEMINI_API_KEY not set")
        sys.exit(1)

    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not or_key:
        log.error("OPENROUTER_API_KEY not set")
        sys.exit(1)

    pdf_path = os.path.join(PROJECT_ROOT, "neural_archive_merged_extract (3) (1).pdf")
    if not os.path.isfile(pdf_path):
        log.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    output_dir = os.path.join(PROJECT_ROOT, "test_output")
    os.makedirs(output_dir, exist_ok=True)

    from google import genai
    from backend.agents.page_classifier import run_page_classifier
    from backend.agents.segmentador import run_segmentador, DEFAULT_DESCRIPTION
    from backend.agents.explainer_openrouter import run_subpart_explainer_or, OPENROUTER_MODEL_AGENTS
    from backend.gemini_model_routing import MODEL_CLASSIFIER, MODEL_SEGMENTADOR
    from backend.pdf_utils import add_page_numbers, extract_page_range
    from backend.gemini_client import upload_file_with_retry
    from main import (
        _build_content_pages_prefix,
        _build_pdf_table_of_contents,
        _build_subpart_pdf_prompt,
        _part_handoff_base,
        _assemble_part_explainer,
        _find_parte_by_numero,
        _continuity_block_from_previous_part,
        PartHandoffContext,
    )

    log.info("OpenRouter model: %s", OPENROUTER_MODEL_AGENTS)

    client = genai.Client(api_key=api_key)

    # =======================================================================
    # STEP 0: Add page numbers
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 0: Adding page numbers to PDF")
    log.info("=" * 80)
    numbered_pdf = add_page_numbers(pdf_path)
    total_pages = len(PdfReader(numbered_pdf).pages)
    log.info("Total pages: %d", total_pages)

    # =======================================================================
    # STEP 1: Upload numbered PDF to Gemini (needed for classifier + segmentador)
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 1: Uploading numbered PDF to Gemini (for segmentation pipeline)")
    log.info("=" * 80)
    upload_start = time.time()
    uploaded = upload_file_with_retry(client, numbered_pdf, max_retries=5)
    file_uri = uploaded.uri
    log.info("Upload done in %dms — URI: %s", int((time.time() - upload_start) * 1000), file_uri)

    # =======================================================================
    # STEP 2: Page Classifier (Gemini)
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 2: Running Page Classifier (Gemini)")
    log.info("=" * 80)
    clf_start = time.time()
    content_pages, clf_usage = run_page_classifier(api_key, file_uri, total_pages, MODEL_CLASSIFIER)
    log.info("Page classifier done in %dms", int((time.time() - clf_start) * 1000))
    log.info("Content pages: %d / %d — %s", len(content_pages), total_pages, sorted(content_pages))
    log.info("Token usage: %s", _tokens_gemini(clf_usage))

    # =======================================================================
    # STEP 3: Segmentador (Gemini)
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 3: Running Segmentador (Gemini)")
    log.info("=" * 80)
    content_prefix = _build_content_pages_prefix(content_pages, total_pages)
    seg_description = content_prefix + DEFAULT_DESCRIPTION

    seg_start = time.time()
    segmentation, seg_usage = run_segmentador(
        api_key, file_uri, seg_description, MODEL_SEGMENTADOR,
        mime_type="application/pdf", source_kind="pdf",
    )
    seg_ms = (time.time() - seg_start) * 1000
    _save_json("or_01_segmentation", segmentation, output_dir)

    num_partes = len(segmentation.get("partes", []))
    log.info("Segmentador done in %dms — %d partes", int(seg_ms), num_partes)
    log.info("Token usage: %s", _tokens_gemini(seg_usage))

    for p in segmentation.get("partes", []):
        subpartes = p.get("subpartes", [])
        log.info(
            "  Parte %d: \"%s\" (pp.%s-%s) — %d subparte(s)",
            p["numero"], p["titulo"], p.get("pagina_inicio", "?"), p.get("pagina_fin", "?"), len(subpartes),
        )
        for sp in subpartes:
            log.info(
                "    SP %d: \"%s\" (pp.%s-%s)",
                sp["numero_subparte"], sp["titulo"], sp.get("pagina_inicio", "?"), sp.get("pagina_fin", "?"),
            )

    # =======================================================================
    # STEP 4: Pick first part, run OpenRouter subpart explainer
    # =======================================================================
    if num_partes == 0:
        log.error("No partes found — cannot test explainer")
        sys.exit(1)

    first_parte = segmentation["partes"][0]
    part_id = first_parte["numero"]
    subpartes = first_parte.get("subpartes", [])

    log.info("=" * 80)
    log.info(
        "STEP 4: Running OpenRouter subpart_explainer on Parte %d \"%s\" (%d subpartes)",
        part_id, first_parte["titulo"], len(subpartes),
    )
    log.info("=" * 80)

    table_of_contents = _build_pdf_table_of_contents(segmentation, num_partes)

    pg_inicio = first_parte.get("pagina_inicio")
    pg_fin = first_parte.get("pagina_fin")

    # Extract local sub-PDF — OpenRouter reads file directly (no upload needed)
    if pg_inicio and pg_fin:
        log.info("Extracting sub-PDF pages %d-%d (local, no upload)", pg_inicio, pg_fin)
        seg_pdf_path = extract_page_range(numbered_pdf, pg_inicio, pg_fin, buffer=1)
        pdf_scope_mode = "subpdf_buffered"
    else:
        seg_pdf_path = numbered_pdf
        pdf_scope_mode = "full_document"
        log.warning("No page range — using full numbered PDF")

    user_intent = ""
    consideraciones = segmentation.get("consideraciones_estudiante", "")
    continuidad_previa = None
    if part_id > 1:
        prev = _find_parte_by_numero(segmentation["partes"], part_id - 1)
        if prev:
            continuidad_previa = _continuity_block_from_previous_part(prev)

    handoff = _part_handoff_base(
        first_parte,
        intent_usuario=user_intent,
        continuidad_previa=continuidad_previa,
        vision_global_division=consideraciones if part_id == 1 else None,
    )

    nucleo_pi = first_parte.get("pagina_inicio")
    nucleo_pf = first_parte.get("pagina_fin")

    if not subpartes:
        subpartes = [{
            "numero_subparte": 1,
            "titulo": first_parte["titulo"],
            "contenido": first_parte.get("contenido", ""),
            "identificacion": first_parte.get("identificacion", ""),
            "pagina_inicio": pg_inicio,
            "pagina_fin": pg_fin,
            "temas_cubiertos": first_parte.get("temas_cubiertos", []),
        }]
        log.warning("No subpartes defined — using whole part as single subparte")

    subpart_desarrollos: list[list[dict]] = []
    all_explainer_results: list[dict] = []

    for sp_idx, sp in enumerate(subpartes):
        log.info("-" * 60)
        log.info(
            "  Explaining subparte %d/%d: \"%s\" (pp.%s-%s)",
            sp_idx + 1, len(subpartes), sp.get("titulo", "?"),
            sp.get("pagina_inicio", "?"), sp.get("pagina_fin", "?"),
        )
        log.info("  Temas: %s", sp.get("temas_cubiertos", []))
        log.info("-" * 60)

        sp_prompt = _build_subpart_pdf_prompt(
            table_of_contents, first_parte, sp, subpartes,
            part_id, num_partes, handoff,
            pdf_scope_mode=pdf_scope_mode,
            nucleo_inicio=nucleo_pi,
            nucleo_fin=nucleo_pf,
        )
        log.info("  Prompt length: %d chars", len(sp_prompt))

        sp_start = time.time()
        try:
            sp_result, sp_usage = run_subpart_explainer_or(
                source_path=seg_pdf_path,
                identificacion=sp_prompt,
                mime_type="application/pdf",
                api_key=or_key,
            )
            sp_ms = (time.time() - sp_start) * 1000
            desarrollo = sp_result.get("desarrollo", [])
            subpart_desarrollos.append(desarrollo)

            total_subsections = 0
            total_chars = 0
            for sec in desarrollo:
                sec_title = sec.get("titulo_seccion", "")
                subs = sec.get("subsecciones", [])
                total_subsections += len(subs)
                for sub in subs:
                    exp = sub.get("explicacion_detallada", "")
                    total_chars += len(exp)
                    log.info(
                        "    [%s → %s] %d chars / ~%d words",
                        sec_title[:40], sub.get("titulo_subseccion", "?")[:40],
                        len(exp), len(exp.split()),
                    )

            log.info(
                "  Subparte %d done in %dms — %d secciones, %d subsecciones, %d total chars",
                sp_idx + 1, int(sp_ms), len(desarrollo), total_subsections, total_chars,
            )
            log.info("  Token usage: %s", _tokens_or(sp_usage))

            _save_json(f"or_02_subparte_{sp_idx + 1}_explainer", sp_result, output_dir)
            all_explainer_results.append(sp_result)

        except Exception as e:
            log.error("  Subparte %d FAILED: %s", sp_idx + 1, e, exc_info=True)

    # =======================================================================
    # STEP 5: Assemble and save final result
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 5: Assembling final OpenRouter explainer for Parte %d", part_id)
    log.info("=" * 80)

    if subpart_desarrollos:
        assembled = _assemble_part_explainer(first_parte, subpart_desarrollos)
        _save_json("or_03_assembled_part_explainer", assembled, output_dir)

        desarrollo = assembled.get("desarrollo", [])
        log.info("Assembled: %d secciones", len(desarrollo))
        total_words = 0
        for sec in desarrollo:
            subs = sec.get("subsecciones", [])
            log.info(
                "  Sección: \"%s\" (%d subsecciones)",
                sec.get("titulo_seccion", "?")[:60], len(subs),
            )
            for sub in subs:
                exp = sub.get("explicacion_detallada", "")
                wc = len(exp.split())
                total_words += wc
                log.info(
                    "    └─ \"%s\": %d chars / ~%d words",
                    sub.get("titulo_subseccion", "?")[:50], len(exp), wc,
                )
        log.info("TOTAL words in desarrollo: ~%d", total_words)
        intro_len = len(assembled.get("introduccion", ""))
        concl_len = len(assembled.get("conclusion", ""))
        log.info("Intro: %d chars | Conclusion: %d chars", intro_len, concl_len)

    log.info("=" * 80)
    log.info("DONE — Results saved in %s (prefix: or_)", output_dir)
    log.info("=" * 80)


if __name__ == "__main__":
    main()

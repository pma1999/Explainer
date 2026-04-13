"""Live pipeline test: page_classifier → segmentador → subpart_explainer (1 section).

Runs against the neural archive PDF with full logging at each step.
Outputs JSON results for manual analysis of atomicity and depth.

Usage:
    python -m tests.test_pipeline_live_neural
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv(override=True)

# Ensure project root is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Verbose logging setup
# ---------------------------------------------------------------------------
LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
logging.basicConfig(level=logging.DEBUG, format=LOG_FMT, stream=sys.stdout)
# Quiet noisy libraries
for _lib in ("httpx", "httpcore", "google", "urllib3", "filelock"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

log = logging.getLogger("test_pipeline")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens(usage) -> dict:
    """Extract token counts from usage_metadata."""
    if usage is None:
        return {}
    return {
        "prompt": getattr(usage, "prompt_token_count", 0) or 0,
        "candidates": getattr(usage, "candidates_token_count", 0) or 0,
        "thoughts": getattr(usage, "thoughts_token_count", 0) or 0,
        "total": getattr(usage, "total_token_count", 0) or 0,
    }


def _save_json(label: str, data: dict, output_dir: str) -> str:
    path = os.path.join(output_dir, f"{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved %s → %s (%d bytes)", label, path, os.path.getsize(path))
    return path


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        log.error("GEMINI_API_KEY not set")
        sys.exit(1)

    # Locate PDF
    pdf_path = os.path.join(PROJECT_ROOT, "neural_archive_merged_extract (3) (1).pdf")
    if not os.path.isfile(pdf_path):
        log.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    # Output dir for results
    output_dir = os.path.join(PROJECT_ROOT, "test_output")
    os.makedirs(output_dir, exist_ok=True)

    from google import genai
    from backend.agents.page_classifier import run_page_classifier
    from backend.agents.segmentador import run_segmentador, DEFAULT_DESCRIPTION
    from backend.agents.explainer import run_subpart_explainer
    from backend.gemini_model_routing import MODEL_CLASSIFIER, MODEL_SEGMENTADOR, MODEL_AGENTS

    # Override explainer model for comparison test
    EXPLAINER_MODEL = "gemini-3-flash-preview"  # was MODEL_AGENTS (flash-lite)
    log.info("EXPLAINER_MODEL override: %s (default would be %s)", EXPLAINER_MODEL, MODEL_AGENTS)
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
        _format_handoff_section,
        PartHandoffContext,
    )

    client = genai.Client(api_key=api_key)

    # =======================================================================
    # STEP 0: Prepare PDF — add page numbers
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 0: Adding page numbers to PDF")
    log.info("=" * 80)
    numbered_pdf = add_page_numbers(pdf_path)
    total_pages = len(PdfReader(numbered_pdf).pages)
    log.info("Total pages: %d", total_pages)

    # =======================================================================
    # STEP 1: Upload numbered PDF to Gemini
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 1: Uploading numbered PDF to Gemini")
    log.info("=" * 80)
    upload_start = time.time()
    uploaded = upload_file_with_retry(client, numbered_pdf, max_retries=5)
    file_uri = uploaded.uri
    upload_ms = (time.time() - upload_start) * 1000
    log.info("Upload done in %dms — URI: %s", int(upload_ms), file_uri)

    # =======================================================================
    # STEP 2: Page Classifier
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 2: Running Page Classifier")
    log.info("=" * 80)
    clf_start = time.time()
    content_pages, clf_usage, _clf_raw = run_page_classifier(
        api_key, file_uri, total_pages, MODEL_CLASSIFIER,
    )
    clf_ms = (time.time() - clf_start) * 1000
    log.info("Page classifier done in %dms", int(clf_ms))
    log.info("Content pages: %d / %d", len(content_pages), total_pages)
    log.info("Content page set: %s", sorted(content_pages))
    log.info("Token usage: %s", _tokens(clf_usage))
    log.info("Non-content pages: %s", sorted(set(range(1, total_pages + 1)) - content_pages))

    # =======================================================================
    # STEP 3: Segmentador
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 3: Running Segmentador")
    log.info("=" * 80)

    content_prefix = _build_content_pages_prefix(content_pages, total_pages)
    seg_description = content_prefix + DEFAULT_DESCRIPTION

    seg_start = time.time()
    segmentation, seg_usage = run_segmentador(
        api_key, file_uri, seg_description, MODEL_SEGMENTADOR,
        mime_type="application/pdf", source_kind="pdf",
    )
    seg_ms = (time.time() - seg_start) * 1000

    _save_json("01_segmentation", segmentation, output_dir)

    num_partes = len(segmentation.get("partes", []))
    temas = segmentation.get("temas_identificados", [])
    log.info("Segmentador done in %dms — %d partes, %d temas", int(seg_ms), num_partes, len(temas))
    log.info("Token usage: %s", _tokens(seg_usage))

    # Print segmentation summary
    log.info("-" * 60)
    log.info("SEGMENTATION SUMMARY")
    log.info("-" * 60)
    log.info("Temas identificados (%d):", len(temas))
    for i, t in enumerate(temas, 1):
        log.info("  T%d: %s", i, t)
    log.info("")
    for p in segmentation.get("partes", []):
        pg_i = p.get("pagina_inicio", "?")
        pg_f = p.get("pagina_fin", "?")
        subpartes = p.get("subpartes", [])
        log.info(
            "  Parte %d: \"%s\" (pp.%s-%s) — %d subparte(s)",
            p["numero"], p["titulo"], pg_i, pg_f, len(subpartes),
        )
        for sp in subpartes:
            sp_pi = sp.get("pagina_inicio", "?")
            sp_pf = sp.get("pagina_fin", "?")
            log.info(
                "    SP %d: \"%s\" (pp.%s-%s) — temas: %s",
                sp["numero_subparte"], sp["titulo"], sp_pi, sp_pf,
                ", ".join(sp.get("temas_cubiertos", [])),
            )
    log.info("-" * 60)

    # =======================================================================
    # STEP 4: Pick first part, run subpart explainer on its subpartes
    # =======================================================================
    if num_partes == 0:
        log.error("No partes found — cannot test explainer")
        sys.exit(1)

    first_parte = segmentation["partes"][0]
    part_id = first_parte["numero"]
    subpartes = first_parte.get("subpartes", [])

    log.info("=" * 80)
    log.info(
        "STEP 4: Running subpart_explainer on Parte %d \"%s\" (%d subpartes)",
        part_id, first_parte["titulo"], len(subpartes),
    )
    log.info("=" * 80)

    # Build table of contents
    table_of_contents = _build_pdf_table_of_contents(segmentation, num_partes)

    # Extract sub-PDF for this part
    pg_inicio = first_parte.get("pagina_inicio")
    pg_fin = first_parte.get("pagina_fin")

    if pg_inicio and pg_fin:
        log.info("Extracting sub-PDF pages %d-%d with buffer=1", pg_inicio, pg_fin)
        seg_pdf_path = extract_page_range(numbered_pdf, pg_inicio, pg_fin, buffer=1)
        seg_upload_start = time.time()
        seg_uploaded = upload_file_with_retry(client, seg_pdf_path, max_retries=5)
        agent_file_uri = seg_uploaded.uri
        log.info("Sub-PDF uploaded in %dms", int((time.time() - seg_upload_start) * 1000))
    else:
        agent_file_uri = file_uri
        log.warning("No page range — using full PDF URI")

    # Build handoff
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
    pdf_scope_mode = "subpdf_buffered" if (pg_inicio and pg_fin) else "full_document"

    # Process subpartes
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
        log.info("  Temas cubiertos: %s", sp.get("temas_cubiertos", []))
        log.info("-" * 60)

        sp_prompt = _build_subpart_pdf_prompt(
            table_of_contents, first_parte, sp, subpartes,
            part_id, num_partes, handoff,
            pdf_scope_mode=pdf_scope_mode,
            nucleo_inicio=nucleo_pi,
            nucleo_fin=nucleo_pf,
        )
        log.info("  Prompt length: %d chars", len(sp_prompt))
        log.info("  Prompt preview:\n%s", sp_prompt[:500])

        sp_start = time.time()
        try:
            sp_result, sp_usage = run_subpart_explainer(
                api_key, agent_file_uri, sp_prompt, EXPLAINER_MODEL,
                mime_type="application/pdf",
            )
            sp_ms = (time.time() - sp_start) * 1000
            desarrollo = sp_result.get("desarrollo", [])
            subpart_desarrollos.append(desarrollo)

            # Analyze depth
            total_subsections = 0
            total_chars = 0
            for sec in desarrollo:
                sec_title = sec.get("titulo_seccion", "")
                sec_intro_len = len(sec.get("explicacion_introductoria", ""))
                subs = sec.get("subsecciones", [])
                total_subsections += len(subs)
                for sub in subs:
                    sub_title = sub.get("titulo_subseccion", "")
                    exp = sub.get("explicacion_detallada", "")
                    exp_len = len(exp)
                    total_chars += exp_len
                    log.info(
                        "    [%s → %s] %d chars",
                        sec_title[:40], sub_title[:40], exp_len,
                    )

            log.info(
                "  Subparte %d done in %dms — %d secciones, %d subsecciones, %d total chars",
                sp_idx + 1, int(sp_ms), len(desarrollo), total_subsections, total_chars,
            )
            log.info("  Token usage: %s", _tokens(sp_usage))

            # Save individual subpart result
            _save_json(
                f"02_subparte_{sp_idx + 1}_explainer",
                sp_result, output_dir,
            )
            all_explainer_results.append(sp_result)

        except Exception as e:
            log.error("  Subparte %d FAILED: %s", sp_idx + 1, e, exc_info=True)

    # =======================================================================
    # STEP 5: Assemble and save final result
    # =======================================================================
    log.info("=" * 80)
    log.info("STEP 5: Assembling final explainer for Parte %d", part_id)
    log.info("=" * 80)

    if subpart_desarrollos:
        assembled = _assemble_part_explainer(first_parte, subpart_desarrollos)
        _save_json("03_assembled_part_explainer", assembled, output_dir)

        # Final depth analysis
        desarrollo = assembled.get("desarrollo", [])
        log.info("Assembled: %d secciones", len(desarrollo))
        for sec in desarrollo:
            subs = sec.get("subsecciones", [])
            log.info(
                "  Sección: \"%s\" (%d subsecciones)",
                sec.get("titulo_seccion", "?")[:60], len(subs),
            )
            for sub in subs:
                exp = sub.get("explicacion_detallada", "")
                word_count = len(exp.split())
                log.info(
                    "    └─ \"%s\": %d chars / ~%d words",
                    sub.get("titulo_subseccion", "?")[:50], len(exp), word_count,
                )

        intro_len = len(assembled.get("introduccion", ""))
        concl_len = len(assembled.get("conclusion", ""))
        log.info("Intro: %d chars | Conclusion: %d chars", intro_len, concl_len)

    # =======================================================================
    # CLEANUP
    # =======================================================================
    log.info("=" * 80)
    log.info("DONE — Results saved in %s", output_dir)
    log.info("=" * 80)


if __name__ == "__main__":
    main()

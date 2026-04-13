"""Auditoría en vivo: clasificador de páginas + segmentador sobre PID_00230265.pdf.

Replica la lógica de main.py (reintentos unificados MECE temas + cobertura de páginas),
valida la partición del clasificador y escribe un informe JSON detallado.

Uso (desde la raíz del repo):
    python tests/test_pid_00230265_segmentation_audit.py

Requiere GEMINI_API_KEY y el fichero PID_00230265.pdf en la raíz del proyecto.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv(override=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

LOG_FMT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FMT, stream=sys.stdout)
for _lib in ("httpx", "httpcore", "google.genai", "urllib3"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

log = logging.getLogger("pid_audit")


def _tokens(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        "prompt": getattr(usage, "prompt_token_count", 0) or 0,
        "candidates": getattr(usage, "candidates_token_count", 0) or 0,
        "thoughts": getattr(usage, "thoughts_token_count", 0) or 0,
        "total": getattr(usage, "total_token_count", 0) or 0,
    }


def _tema_report_dict(r: Any) -> dict[str, Any]:
    return {
        "is_valid": r.is_valid,
        "missing": list(r.missing),
        "duplicates": [
            {"canonical": d.canonical, "part_numbers": list(d.part_numbers)} for d in r.duplicates
        ],
        "orphans": [{"parte": p, "texto": t} for p, t in r.orphans],
        "structural_errors": list(r.structural_errors),
        "empty_temas_inventory": r.empty_temas_inventory,
    }


def _page_report_dict(r: Any) -> dict[str, Any]:
    return {
        "is_valid": r.is_valid,
        "part_errors": [
            {"type": e.type, "part_numero": e.part_numero, "detail": e.detail} for e in r.part_errors
        ],
        "subpart_errors": [
            {"type": e.type, "part_numero": e.part_numero, "subpart_numero": e.subpart_numero, "detail": e.detail}
            for e in r.subpart_errors
        ],
    }


def _accessory_pages_inside_part_ranges(
    segmentation: dict[str, Any], content_page_set: frozenset[int]
) -> list[dict[str, Any]]:
    """Páginas clasificadas como accesorias pero incluidas en el rango de una parte."""
    rows: list[dict[str, Any]] = []
    for p in segmentation.get("partes") or []:
        if not isinstance(p, dict):
            continue
        try:
            num = int(p["numero"])
            pi = int(p["pagina_inicio"])
            pf = int(p["pagina_fin"])
        except (KeyError, TypeError, ValueError):
            continue
        accessory = [x for x in range(pi, pf + 1) if x not in content_page_set]
        if accessory:
            rows.append(
                {
                    "parte": num,
                    "titulo": p.get("titulo"),
                    "pagina_inicio": pi,
                    "pagina_fin": pf,
                    "paginas_accesorias_dentro_del_rango": accessory,
                }
            )
    return rows


def _content_pages_not_in_any_part(
    segmentation: dict[str, Any], content_page_set: frozenset[int]
) -> list[int]:
    covered: set[int] = set()
    for p in segmentation.get("partes") or []:
        if not isinstance(p, dict):
            continue
        try:
            pi = int(p["pagina_inicio"])
            pf = int(p["pagina_fin"])
        except (KeyError, TypeError, ValueError):
            continue
        covered.update(range(pi, pf + 1))
    return sorted(content_page_set - covered)


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        log.error("GEMINI_API_KEY no está definida")
        sys.exit(1)

    pdf_name = "PID_00230265.pdf"
    pdf_path = os.path.join(PROJECT_ROOT, pdf_name)
    if not os.path.isfile(pdf_path):
        log.error("No se encuentra el PDF: %s", pdf_path)
        sys.exit(1)

    from google import genai

    from backend.agents.page_classifier import (
        run_page_classifier,
        validate_classifier_partition,
    )
    from backend.agents.segmentador import DEFAULT_DESCRIPTION, run_segmentador
    from backend.gemini_model_routing import MODEL_CLASSIFIER, MODEL_SEGMENTADOR
    from backend.gemini_client import upload_file_with_retry
    from backend.pdf_utils import add_page_numbers
    from backend.segmentation_page_coverage import (
        MAX_PAGE_COVERAGE_ATTEMPTS,
        build_page_coverage_retry_suffix,
        validate_page_coverage,
    )
    from backend.segmentation_tema_coverage import (
        MAX_SEGMENTATION_COVERAGE_ATTEMPTS,
        build_tema_coverage_retry_suffix,
        validate_tema_partition,
    )
    from main import _build_content_pages_prefix

    output_dir = os.path.join(PROJECT_ROOT, "test_output")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "pid_00230265_segmentation_audit.json")

    client = genai.Client(api_key=api_key)
    audit: dict[str, Any] = {
        "pdf": pdf_name,
        "steps": [],
        "errors_summary": [],
    }

    # --- STEP 0: numerar PDF ---
    t0 = time.time()
    numbered_pdf = add_page_numbers(pdf_path)
    total_pages = len(PdfReader(numbered_pdf).pages)
    audit["total_pages_pypdf"] = total_pages
    audit["steps"].append(
        {
            "step": "add_page_numbers",
            "ms": int((time.time() - t0) * 1000),
            "numbered_pdf_path": numbered_pdf,
        }
    )
    log.info("PDF numerado: %d páginas → %s", total_pages, numbered_pdf)

    # --- STEP 1: subir ---
    t1 = time.time()
    uploaded = upload_file_with_retry(client, numbered_pdf, max_retries=5)
    file_uri = uploaded.uri
    audit["steps"].append(
        {
            "step": "upload",
            "ms": int((time.time() - t1) * 1000),
            "file_uri_prefix": file_uri[:80] + "...",
        }
    )
    log.info("Subida completada")

    # --- STEP 2: clasificador ---
    t2 = time.time()
    content_page_set, clf_usage, clf_raw = run_page_classifier(
        api_key, file_uri, total_pages, MODEL_CLASSIFIER
    )
    clf_ms = int((time.time() - t2) * 1000)
    clf_partition_ok, clf_partition_errs = validate_classifier_partition(clf_raw, total_pages)
    non_content_pages = sorted(set(range(1, total_pages + 1)) - set(content_page_set))

    audit["classifier"] = {
        "duration_ms": clf_ms,
        "model": MODEL_CLASSIFIER,
        "tokens": _tokens(clf_usage),
        "content_pages_count": len(content_page_set),
        "raw_json": clf_raw,
        "partition_valid": clf_partition_ok,
        "partition_errors": clf_partition_errs,
        "content_pages_sorted": sorted(content_page_set),
        "non_content_pages_sorted": non_content_pages,
    }
    audit["steps"].append({"step": "page_classifier", "ms": clf_ms})
    log.info(
        "Clasificador: %d páginas contenido / %d total (partición JSON ok=%s)",
        len(content_page_set),
        total_pages,
        clf_partition_ok,
    )
    if not clf_partition_ok:
        for e in clf_partition_errs:
            log.warning("[Clasificador] %s", e)
            audit["errors_summary"].append({"phase": "classifier_partition", "detail": e})

    # --- STEP 3: segmentador con reintentos (igual que main.py) ---
    content_pages_prefix = _build_content_pages_prefix(content_page_set, total_pages)
    max_attempts = max(MAX_SEGMENTATION_COVERAGE_ATTEMPTS, MAX_PAGE_COVERAGE_ATTEMPTS)
    segmentation: dict[str, Any] | None = None
    tema_report = None
    page_report = None
    attempts_log: list[dict[str, Any]] = []

    seg_total_start = time.time()
    for seg_attempt in range(max_attempts):
        if seg_attempt == 0:
            seg_description = content_pages_prefix + DEFAULT_DESCRIPTION
        else:
            assert segmentation is not None
            correction_parts = []
            if tema_report is not None and not tema_report.is_valid:
                correction_parts.append(
                    build_tema_coverage_retry_suffix(
                        attempt=seg_attempt,
                        segmentation=segmentation,
                        report=tema_report,
                    )
                )
            if page_report is not None and not page_report.is_valid:
                correction_parts.append(
                    build_page_coverage_retry_suffix(
                        attempt=seg_attempt,
                        segmentation=segmentation,
                        report=page_report,
                        content_page_set=content_page_set,
                    )
                )
            correction_suffix = "\n\n".join(correction_parts)
            seg_description = content_pages_prefix + DEFAULT_DESCRIPTION + "\n\n" + correction_suffix

        t_seg = time.time()
        segmentation, seg_usage = run_segmentador(
            api_key,
            file_uri,
            seg_description,
            MODEL_SEGMENTADOR,
            "application/pdf",
            "pdf",
        )
        seg_ms = int((time.time() - t_seg) * 1000)

        tema_report = validate_tema_partition(segmentation)
        page_report = validate_page_coverage(segmentation, content_page_set)

        entry = {
            "attempt": seg_attempt,
            "duration_ms": seg_ms,
            "tokens": _tokens(seg_usage),
            "tema": _tema_report_dict(tema_report),
            "paginas": _page_report_dict(page_report),
            "both_valid": tema_report.is_valid and page_report.is_valid,
        }
        attempts_log.append(entry)

        log.info(
            "Segmentación intento %d/%d — temas_ok=%s páginas_ok=%s (%d ms)",
            seg_attempt + 1,
            max_attempts,
            tema_report.is_valid,
            page_report.is_valid,
            seg_ms,
        )

        if not tema_report.is_valid:
            for e in tema_report.structural_errors:
                log.warning("[Tema] %s", e)
            for m in tema_report.missing:
                log.warning("[Tema] Sin asignar: %s", m)
            for d in tema_report.duplicates:
                log.warning("[Tema] Duplicado: %s en partes %s", d.canonical, d.part_numbers)
            for parte_no, raw in tema_report.orphans:
                log.warning("[Tema] Huérfano en parte %s: %s", parte_no, raw)

        if not page_report.is_valid:
            for e in page_report.part_errors:
                log.warning("[Página parte] %s", e.detail)
            for e in page_report.subpart_errors:
                log.warning("[Página subparte] %s", e.detail)

        if tema_report.is_valid and page_report.is_valid:
            break
    else:
        log.error("Se agotaron los reintentos sin validación conjunta OK")

    audit["segmentation"] = {
        "max_attempts": max_attempts,
        "total_duration_ms": int((time.time() - seg_total_start) * 1000),
        "attempts": attempts_log,
        "final_both_valid": bool(
            tema_report and page_report and tema_report.is_valid and page_report.is_valid
        ),
        "result": segmentation,
    }

    if segmentation:
        audit["segmentation"]["accessory_pages_inside_part_ranges"] = _accessory_pages_inside_part_ranges(
            segmentation, content_page_set
        )
        audit["segmentation"]["content_pages_missing_from_part_ranges"] = _content_pages_not_in_any_part(
            segmentation, content_page_set
        )

    # Resumen de errores finales
    if tema_report and not tema_report.is_valid:
        audit["errors_summary"].append(
            {"phase": "segmentation_tema", "detail": _tema_report_dict(tema_report)}
        )
    if page_report and not page_report.is_valid:
        audit["errors_summary"].append(
            {"phase": "segmentation_pages", "detail": _page_report_dict(page_report)}
        )

    # Vista legible de partes / subpartes
    if segmentation and isinstance(segmentation.get("partes"), list):
        vista: list[dict[str, Any]] = []
        for p in segmentation["partes"]:
            if not isinstance(p, dict):
                continue
            row = {
                "numero": p.get("numero"),
                "titulo": p.get("titulo"),
                "pagina_inicio": p.get("pagina_inicio"),
                "pagina_fin": p.get("pagina_fin"),
                "temas_cubiertos": p.get("temas_cubiertos"),
                "identificacion": (str(p.get("identificacion") or "")[:400] + "…")
                if p.get("identificacion") and len(str(p.get("identificacion"))) > 400
                else p.get("identificacion"),
                "subpartes": [],
            }
            for sp in p.get("subpartes") or []:
                if not isinstance(sp, dict):
                    continue
                row["subpartes"].append(
                    {
                        "numero_subparte": sp.get("numero_subparte"),
                        "titulo": sp.get("titulo"),
                        "pagina_inicio": sp.get("pagina_inicio"),
                        "pagina_fin": sp.get("pagina_fin"),
                        "temas_cubiertos": sp.get("temas_cubiertos"),
                        "identificacion": (str(sp.get("identificacion") or "")[:300] + "…")
                        if sp.get("identificacion") and len(str(sp.get("identificacion"))) > 300
                        else sp.get("identificacion"),
                    }
                )
            vista.append(row)
        audit["segmentation"]["vista_partes_subpartes"] = vista

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    log.info("Informe escrito en %s (%d bytes)", report_path, os.path.getsize(report_path))

    # Salida breve en consola
    print("\n" + "=" * 72)
    print("RESUMEN AUDITORÍA PID_00230265")
    print("=" * 72)
    print(f"Páginas (pypdf): {total_pages}")
    print(f"Clasificador — partición JSON válida: {clf_partition_ok}")
    print(f"Páginas de contenido: {len(content_page_set)}")
    if tema_report and page_report:
        print(f"Segmentación — válida (temas + páginas): {tema_report.is_valid and page_report.is_valid}")
    print(f"Informe completo: {report_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()

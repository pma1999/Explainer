"""Auditoría de coherencia de páginas en el pipeline PDF (clasificador → segmentador → agentes).

Verifica sin llamadas LLM:
- Numeración visible coherente con índice físico
- extract_page_range conserva marcas de página originales
- _select_openrouter_pdf_pages alinea OCR con rangos de parte/subparte
- recorrido/recursos (nivel parte) vs explainer (nivel subparte) usan conjuntos distintos pero consistentes

Opcional con GEMINI_API_KEY o OPENROUTER_API_KEY:
- Clasificador + segmentador en vivo sobre v35n2a7.pdf

Uso:
    python tests/test_v35n2a7_page_pipeline_audit.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv(override=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

PDF_NAME = "v35n2a7.pdf"
PAGE_MARK_RE = re.compile(r"—\s*Página\s+(\d+)\s*/\s*(\d+)\s*—", re.IGNORECASE)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class AuditReport:
    pdf: str
    total_pages: int = 0
    checks: list[CheckResult] = field(default_factory=list)
    live_classifier: dict[str, Any] | None = None
    live_segmentation: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(CheckResult(name=name, ok=ok, detail=detail))


def _optional_int(item: dict, key: str) -> int | None:
    v = item.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pages_in_range(start: int | None, end: int | None, buffer: int = 1) -> tuple[int, ...]:
    if start is None or end is None:
        return ()
    lo = max(1, start - buffer)
    hi = end + buffer
    return tuple(range(lo, hi + 1))


def _extract_page_marks(text: str) -> list[int]:
    return [int(m.group(1)) for m in PAGE_MARK_RE.finditer(text or "")]


def _simulate_agent_scopes(
    segmentation: dict[str, Any],
    content_page_set: frozenset[int],
) -> list[dict[str, Any]]:
    """Replica la selección de páginas de main.py para cada parte/subparte."""
    from main import _select_openrouter_pdf_pages

    rows: list[dict[str, Any]] = []
    for parte in segmentation.get("partes") or []:
        if not isinstance(parte, dict):
            continue
        part_id = parte.get("numero")
        nucleo_pi = _optional_int(parte, "pagina_inicio")
        nucleo_pf = _optional_int(parte, "pagina_fin")

        recorrido_pages = _select_openrouter_pdf_pages(
            content_page_set,
            start_page=nucleo_pi,
            end_page=nucleo_pf,
            buffer=1,
        )
        gemini_extract_pages = _pages_in_range(nucleo_pi, nucleo_pf, buffer=1)

        subpartes = parte.get("subpartes") or []
        if subpartes:
            for sp in subpartes:
                if not isinstance(sp, dict):
                    continue
                sp_pi = _optional_int(sp, "pagina_inicio") or nucleo_pi
                sp_pf = _optional_int(sp, "pagina_fin") or nucleo_pf
                explainer_pages = _select_openrouter_pdf_pages(
                    content_page_set,
                    start_page=sp_pi,
                    end_page=sp_pf,
                    buffer=1,
                )
                rows.append(
                    {
                        "parte": part_id,
                        "subparte": sp.get("numero_subparte"),
                        "nucleo": (sp_pi, sp_pf),
                        "explainer_or_pages": explainer_pages,
                        "recorrido_or_pages": recorrido_pages,
                        "gemini_subpdf_pages": gemini_extract_pages,
                        "explainer_subset_of_recorrido": set(explainer_pages) <= set(recorrido_pages),
                        "explainer_subset_of_gemini": set(explainer_pages) <= set(gemini_extract_pages),
                    }
                )
        else:
            explainer_pages = recorrido_pages
            rows.append(
                {
                    "parte": part_id,
                    "subparte": None,
                    "nucleo": (nucleo_pi, nucleo_pf),
                    "explainer_or_pages": explainer_pages,
                    "recorrido_or_pages": recorrido_pages,
                    "gemini_subpdf_pages": gemini_extract_pages,
                    "explainer_subset_of_recorrido": True,
                    "explainer_subset_of_gemini": set(explainer_pages) <= set(gemini_extract_pages),
                }
            )
    return rows


def _audit_numbering_and_extract(pdf_path: str, report: AuditReport) -> str | None:
    from backend.pdf_utils import add_page_numbers, extract_page_range

    numbered = add_page_numbers(pdf_path)
    reader = PdfReader(numbered)
    total = len(reader.pages)
    report.total_pages = total

    marks_ok = True
    bad_pages: list[int] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        found = _extract_page_marks(text)
        if found != [i]:
            marks_ok = False
            bad_pages.append(i)

    report.add(
        "page_watermarks_match_physical_index",
        marks_ok,
        f"páginas con marca incorrecta: {bad_pages[:10]}" if bad_pages else f"{total} páginas OK",
    )

    if total < 3:
        report.add("pdf_has_enough_pages", False, f"solo {total} páginas")
        return numbered

    mid_start, mid_end = 2, min(4, total - 1)
    extracted = extract_page_range(numbered, mid_start, mid_end, buffer=1)
    try:
        ex_reader = PdfReader(extracted)
        expected_physical = list(range(max(1, mid_start - 1), min(total, mid_end + 1) + 1))
        marks_in_extract: list[int] = []
        for page in ex_reader.pages:
            marks_in_extract.extend(_extract_page_marks(page.extract_text() or ""))

        report.add(
            "extract_preserves_original_page_numbers",
            marks_in_extract == expected_physical,
            f"esperado {expected_physical}, obtenido {marks_in_extract}",
        )
        report.add(
            "extract_page_count",
            len(ex_reader.pages) == len(expected_physical),
            f"{len(ex_reader.pages)} vs {len(expected_physical)}",
        )
    finally:
        if os.path.isfile(extracted):
            os.unlink(extracted)

    return numbered


def _audit_mock_segmentation_alignment(report: AuditReport) -> None:
    """Segmentación sintética: valida lógica de agentes sin LLM."""
    from backend.segmentation_page_coverage import validate_page_coverage
    from main import _select_openrouter_pdf_pages

    total = report.total_pages or 20
    content = frozenset(range(3, min(total, 18) + 1))
    segmentation = {
        "partes": [
            {
                "numero": 1,
                "titulo": "Mock A",
                "pagina_inicio": 3,
                "pagina_fin": 10,
                "subpartes": [
                    {"numero_subparte": 1, "titulo": "SP1", "pagina_inicio": 3, "pagina_fin": 6},
                    {"numero_subparte": 2, "titulo": "SP2", "pagina_inicio": 7, "pagina_fin": 10},
                ],
            },
            {
                "numero": 2,
                "titulo": "Mock B",
                "pagina_inicio": 11,
                "pagina_fin": min(18, total),
            },
        ]
    }
    cov = validate_page_coverage(segmentation, content)
    report.add("mock_segmentation_coverage_valid", cov.is_valid, str(_page_report_dict(cov)))

    scopes = _simulate_agent_scopes(segmentation, content)
    all_subset = all(r["explainer_subset_of_recorrido"] for r in scopes)
    all_gemini = all(r["explainer_subset_of_gemini"] for r in scopes)
    report.add("mock_explainer_pages_subset_of_recorrido", all_subset, f"{len(scopes)} unidades")
    report.add("mock_explainer_pages_subset_of_gemini_subpdf", all_gemini, f"{len(scopes)} unidades")

    # Accesoria fuera de content no debe colarse en OpenRouter
    selected = _select_openrouter_pdf_pages(content, start_page=5, end_page=7, buffer=1)
    accessory = 2  # asumimos no contenido
    report.add(
        "openrouter_filters_non_content_pages",
        accessory not in selected,
        f"selected={selected}",
    )


def _page_report_dict(r: Any) -> dict[str, Any]:
    return {
        "is_valid": r.is_valid,
        "part_errors": len(r.part_errors),
        "subpart_errors": len(r.subpart_errors),
    }


def _audit_live_llm(numbered_pdf: str, report: AuditReport) -> None:
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    total = report.total_pages

    if gemini_key:
        from google import genai

        from backend.agents.page_classifier import run_page_classifier, validate_classifier_partition
        from backend.agents.segmentador import DEFAULT_DESCRIPTION, run_segmentador
        from backend.gemini_model_routing import MODEL_CLASSIFIER, MODEL_SEGMENTADOR
        from backend.gemini_client import upload_file_with_retry
        from backend.segmentation_page_coverage import (
            MAX_PAGE_COVERAGE_ATTEMPTS,
            build_page_coverage_retry_suffix,
            validate_page_coverage,
        )
        from main import _build_content_pages_prefix

        client = genai.Client(api_key=gemini_key)
        uploaded = upload_file_with_retry(client, numbered_pdf, max_retries=3)
        content_set, clf_usage, clf_raw = run_page_classifier(
            gemini_key, uploaded.uri, total, MODEL_CLASSIFIER
        )
        part_ok, part_errs = validate_classifier_partition(clf_raw, total)
        report.live_classifier = {
            "provider": "gemini",
            "content_pages_count": len(content_set),
            "partition_valid": part_ok,
            "partition_errors": part_errs,
        }
        report.add("live_classifier_partition", part_ok, "; ".join(part_errs[:3]))

        prefix = _build_content_pages_prefix(content_set, total)
        segmentation = None
        page_report = None
        for attempt in range(MAX_PAGE_COVERAGE_ATTEMPTS):
            desc = prefix + DEFAULT_DESCRIPTION
            if attempt > 0 and segmentation is not None and page_report is not None:
                desc += "\n\n" + build_page_coverage_retry_suffix(
                    attempt=attempt,
                    segmentation=segmentation,
                    report=page_report,
                    content_page_set=content_set,
                )
            segmentation, _ = run_segmentador(
                gemini_key, uploaded.uri, desc, MODEL_SEGMENTADOR, "application/pdf", "pdf"
            )
            page_report = validate_page_coverage(segmentation, content_set)
            if page_report.is_valid:
                break

        assert segmentation is not None
        report.live_segmentation = {
            "page_coverage_valid": page_report.is_valid if page_report else False,
            "partes_count": len(segmentation.get("partes") or []),
        }
        report.add(
            "live_segmentation_page_coverage",
            bool(page_report and page_report.is_valid),
            _page_report_dict(page_report) if page_report else "sin reporte",
        )

        _audit_live_agent_alignment(segmentation, content_set, numbered_pdf, report)
        return

    if or_key:
        report.add("live_llm_skipped", True, "solo OPENROUTER_API_KEY: omitido (requiere OCR Mistral)")
        return

    report.add("live_llm_skipped", True, "sin GEMINI_API_KEY ni flujo OR completo")


def _audit_live_agent_alignment(
    segmentation: dict[str, Any],
    content_page_set: frozenset[int],
    numbered_pdf: str,
    report: AuditReport,
) -> None:
    from backend.pdf_utils import extract_page_range
    from backend.segmentation_page_coverage import validate_page_coverage

    cov = validate_page_coverage(segmentation, content_page_set)
    report.add("live_coverage_recheck", cov.is_valid, _page_report_dict(cov))

    scopes = _simulate_agent_scopes(segmentation, content_page_set)
    report.add(
        "live_explainer_subset_of_recorrido",
        all(r["explainer_subset_of_recorrido"] for r in scopes),
        f"{len(scopes)} subpartes/partes",
    )

    mismatches: list[str] = []
    for parte in segmentation.get("partes") or []:
        if not isinstance(parte, dict):
            continue
        pi = _optional_int(parte, "pagina_inicio")
        pf = _optional_int(parte, "pagina_fin")
        if pi is None or pf is None:
            continue
        try:
            seg_path = extract_page_range(numbered_pdf, pi, pf, buffer=1)
            reader = PdfReader(seg_path)
            marks = []
            for page in reader.pages:
                marks.extend(_extract_page_marks(page.extract_text() or ""))
            expected = list(_pages_in_range(pi, pf, buffer=1))
            if marks != expected:
                mismatches.append(
                    f"parte {parte.get('numero')}: marcas {marks} != esperado {expected}"
                )
        except Exception as exc:
            mismatches.append(f"parte {parte.get('numero')}: {exc}")
        finally:
            if "seg_path" in locals() and os.path.isfile(seg_path):
                os.unlink(seg_path)

    report.add(
        "live_gemini_subpdf_page_marks",
        not mismatches,
        "; ".join(mismatches[:5]) or "todas las partes OK",
    )

    accessory_inside = []
    for p in segmentation.get("partes") or []:
        if not isinstance(p, dict):
            continue
        try:
            pi = int(p["pagina_inicio"])
            pf = int(p["pagina_fin"])
        except (KeyError, TypeError, ValueError):
            continue
        bad = [x for x in range(pi, pf + 1) if x not in content_page_set]
        if bad:
            accessory_inside.append({"parte": p.get("numero"), "paginas_accesorias_en_rango": bad})

    report.add(
        "live_no_accessory_pages_in_part_ranges",
        not accessory_inside,
        json.dumps(accessory_inside[:3], ensure_ascii=False) if accessory_inside else "ninguna",
    )


def main() -> None:
    pdf_path = os.path.join(PROJECT_ROOT, PDF_NAME)
    if not os.path.isfile(pdf_path):
        print(f"ERROR: no existe {pdf_path}")
        sys.exit(1)

    report = AuditReport(pdf=PDF_NAME)
    numbered: str | None = None
    try:
        numbered = _audit_numbering_and_extract(pdf_path, report)
        _audit_mock_segmentation_alignment(report)
        if numbered:
            _audit_live_llm(numbered, report)
    finally:
        if numbered and os.path.isfile(numbered):
            os.unlink(numbered)

    out_dir = os.path.join(PROJECT_ROOT, "test_output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "v35n2a7_page_pipeline_audit.json")
    payload = {
        "pdf": report.pdf,
        "total_pages": report.total_pages,
        "passed": report.passed,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.checks],
        "live_classifier": report.live_classifier,
        "live_segmentation": report.live_segmentation,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 72)
    print(f"AUDITORÍA PÁGINAS — {PDF_NAME}")
    print("=" * 72)
    print(f"Páginas: {report.total_pages}")
    for c in report.checks:
        status = "OK" if c.ok else "FAIL"
        extra = f" — {c.detail}" if c.detail else ""
        print(f"  [{status}] {c.name}{extra}")
    print(f"\nResultado global: {'PASS' if report.passed else 'FAIL'}")
    print(f"Informe: {out_path}")
    print("=" * 72)

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()

"""Live audit for subpart boundary discipline on PID_00230265.pdf."""

from __future__ import annotations

import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(override=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def main() -> None:
    from backend.agents.segmentador import DEFAULT_DESCRIPTION, run_segmentador
    from backend.agents.page_classifier import run_page_classifier
    from backend.agents.explainer_openrouter import run_subpart_explainer_or
    from backend.gemini_model_routing import MODEL_CLASSIFIER, MODEL_SEGMENTADOR
    from backend.gemini_client import upload_file_with_retry
    from backend.pdf_utils import add_page_numbers
    from backend.subpart_scope import build_subpart_scope_summary
    from backend.subpart_scope_auditor import run_subpart_scope_auditor
    from main import _build_content_pages_prefix, _build_pdf_table_of_contents, _build_subpart_pdf_prompt, PartHandoffContext
    from google import genai
    from pypdf import PdfReader

    api_key = os.environ["GEMINI_API_KEY"].strip()
    openrouter_key = os.environ["OPENROUTER_API_KEY"].strip()
    pdf_path = os.path.join(PROJECT_ROOT, "PID_00230265.pdf")
    numbered = add_page_numbers(pdf_path)
    total_pages = len(PdfReader(numbered).pages)

    client = genai.Client(api_key=api_key)
    uploaded = upload_file_with_retry(client, numbered, max_retries=5)
    content_pages, _, _ = run_page_classifier(api_key, uploaded.uri, total_pages, MODEL_CLASSIFIER)
    seg_description = _build_content_pages_prefix(content_pages, total_pages) + DEFAULT_DESCRIPTION
    segmentation, _ = run_segmentador(api_key, uploaded.uri, seg_description, MODEL_SEGMENTADOR, "application/pdf", "pdf")

    report = {"pairs": []}
    toc = _build_pdf_table_of_contents(segmentation, len(segmentation["partes"]))

    for parte in segmentation.get("partes", []):
        subpartes = parte.get("subpartes") or []
        if len(subpartes) < 2:
            continue
        handoff = PartHandoffContext(
            titulo=parte["titulo"],
            resumen_alcance=parte.get("contenido", ""),
            temas_cubiertos=tuple(parte.get("temas_cubiertos", [])),
            intent_usuario=None,
            continuidad_previa=None,
            vision_global_division=None,
        )
        for idx in range(len(subpartes) - 1):
            current_sp = subpartes[idx]
            prompt = _build_subpart_pdf_prompt(
                toc,
                parte,
                current_sp,
                subpartes,
                parte["numero"],
                len(segmentation["partes"]),
                handoff,
                pdf_scope_mode="full_document",
                nucleo_inicio=parte.get("pagina_inicio"),
                nucleo_fin=parte.get("pagina_fin"),
            )
            result, _ = run_subpart_explainer_or(
                source_path=numbered,
                identificacion=prompt,
                mime_type="application/pdf",
                api_key=openrouter_key,
            )
            review, _ = run_subpart_scope_auditor(
                api_key=api_key,
                current_subpart_summary=build_subpart_scope_summary(current_sp),
                previous_subpart_summary=build_subpart_scope_summary(subpartes[idx - 1]) if idx > 0 else "",
                next_subpart_summary=build_subpart_scope_summary(subpartes[idx + 1]),
                desarrollo_payload=result,
                model=MODEL_CLASSIFIER,
            )
            report["pairs"].append(
                {
                    "parte": parte["numero"],
                    "subparte_actual": current_sp["numero_subparte"],
                    "subparte_siguiente": subpartes[idx + 1]["numero_subparte"],
                    "is_valid": review.is_valid,
                    "invades_previous": list(review.invades_previous),
                    "invades_next": list(review.invades_next),
                    "missing_current": list(review.missing_current),
                    "rationale": review.rationale,
                }
            )

    out_dir = os.path.join(PROJECT_ROOT, "test_output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pid_00230265_subpart_scope_audit.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(out_path)


if __name__ == "__main__":
    start = time.time()
    main()
    print(f"elapsed_ms={int((time.time() - start) * 1000)}")

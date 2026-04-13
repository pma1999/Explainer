"""Live comparison pipeline: page_classifier -> segmentador -> Gemini/OpenRouter explainers.

Runs the shared pipeline once against the neural archive PDF, then executes both
explainers over the exact same segmentador output, prompt, and scoped PDF for
the first segmented part. It saves raw artifacts plus a structured comparison
report for manual analysis.

Usage:
    python -m tests.test_pipeline_live_neural_compare

    Reuse segmentation from a prior run and only regenerate one subpart on OpenRouter
    (e.g. compare against an older openrouter_03_subparte_01_explainer.json):

    python -m tests.test_pipeline_live_neural_compare \\
      --reuse-segmentation test_output/live_compare_neural_YYYYMMDD_HHMMSS/shared_01_segmentation.json \\
      --only-subpart 1 --openrouter-only --openrouter-model qwen/qwen3.6-plus

Optional environment overrides:
    OPENROUTER_EXPLAINER_MODEL_OVERRIDE
    GEMINI_EXPLAINER_MODEL_OVERRIDE
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv(override=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

LOG_FMT = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
logging.basicConfig(level=logging.DEBUG, format=LOG_FMT, stream=sys.stdout)
for _lib in ("httpx", "httpcore", "google", "urllib3", "filelock", "requests"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

log = logging.getLogger("test_pipeline_compare")

GEMINI_EXPLAINER_MODEL = os.environ.get(
    "GEMINI_EXPLAINER_MODEL_OVERRIDE",
    "gemini-3-flash-preview",
).strip() or "gemini-3-flash-preview"
OPENROUTER_EXPLAINER_MODEL = os.environ.get(
    "OPENROUTER_EXPLAINER_MODEL_OVERRIDE",
    "minimax/minimax-m2.7",
).strip() or "minimax/minimax-m2.7"


def _tokens_gemini(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        "prompt": getattr(usage, "prompt_token_count", 0) or 0,
        "candidates": getattr(usage, "candidates_token_count", 0) or 0,
        "thoughts": getattr(usage, "thoughts_token_count", 0) or 0,
        "total": getattr(usage, "total_token_count", 0) or 0,
    }


def _tokens_openrouter(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        "prompt": getattr(usage, "prompt_token_count", 0) or 0,
        "completion": getattr(usage, "candidates_token_count", 0) or 0,
        "total": getattr(usage, "total_token_count", 0) or 0,
    }


def _save_json(label: str, data: dict[str, Any], output_dir: str) -> str:
    path = os.path.join(output_dir, f"{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved %s -> %s (%d bytes)", label, path, os.path.getsize(path))
    return path


def _save_text(label: str, content: str, output_dir: str, *, suffix: str = ".txt") -> str:
    path = os.path.join(output_dir, f"{label}{suffix}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("Saved %s -> %s (%d bytes)", label, path, os.path.getsize(path))
    return path


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _normalize_title(value: str) -> str:
    return " ".join(value.lower().split())


def _jaccard_similarity(left: list[str], right: list[str]) -> float:
    left_set = {_normalize_title(item) for item in left if item.strip()}
    right_set = {_normalize_title(item) for item in right if item.strip()}
    union = left_set | right_set
    if not union:
        return 1.0
    return len(left_set & right_set) / len(union)


def _sequence_similarity(left: list[str], right: list[str]) -> float:
    left_joined = " | ".join(_normalize_title(item) for item in left if item.strip())
    right_joined = " | ".join(_normalize_title(item) for item in right if item.strip())
    if not left_joined and not right_joined:
        return 1.0
    return SequenceMatcher(a=left_joined, b=right_joined).ratio()


def _collect_output_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    introduccion = payload.get("introduccion", "")
    conclusion = payload.get("conclusion", "")
    desarrollo = payload.get("desarrollo") or []

    section_titles: list[str] = []
    subsection_titles: list[str] = []
    subsections = 0
    body_chars = 0
    body_words = 0
    sample_excerpt = ""

    for section in desarrollo:
        section_title = str(section.get("titulo_seccion", "")).strip()
        if section_title:
            section_titles.append(section_title)

        section_intro = str(section.get("explicacion_introductoria", "")).strip()
        if section_intro:
            body_chars += len(section_intro)
            body_words += _count_words(section_intro)

        for subsection in section.get("subsecciones") or []:
            subsection_title = str(subsection.get("titulo_subseccion", "")).strip()
            detailed = str(subsection.get("explicacion_detallada", "")).strip()
            if subsection_title:
                subsection_titles.append(subsection_title)
            if detailed:
                body_chars += len(detailed)
                body_words += _count_words(detailed)
                if not sample_excerpt:
                    sample_excerpt = detailed[:280]
            subsections += 1

    intro_chars = len(introduccion) if isinstance(introduccion, str) else 0
    conclusion_chars = len(conclusion) if isinstance(conclusion, str) else 0

    return {
        "sections": len(desarrollo),
        "subsections": subsections,
        "body_chars": body_chars,
        "body_words": body_words,
        "intro_chars": intro_chars,
        "conclusion_chars": conclusion_chars,
        "total_chars": intro_chars + body_chars + conclusion_chars,
        "section_titles": section_titles,
        "subsection_titles": subsection_titles,
        "sample_excerpt": sample_excerpt,
    }


def _build_success_record(
    *,
    provider: str,
    result: dict[str, Any],
    usage: Any,
    duration_ms: int,
    artifact_path: str,
) -> dict[str, Any]:
    tokens = _tokens_gemini(usage) if provider == "gemini" else _tokens_openrouter(usage)
    return {
        "provider": provider,
        "status": "ok",
        "duration_ms": duration_ms,
        "artifact_path": artifact_path,
        "tokens": tokens,
        "metrics": _collect_output_metrics(result),
    }


def _build_error_record(provider: str, exc: Exception) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "error",
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }


def _build_skipped_record(provider: str, reason: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "skipped",
        "reason": reason,
    }


def _aggregate_provider(records: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [record for record in records if record.get("status") == "ok"]
    failures = [record for record in records if record.get("status") != "ok"]

    total_duration_ms = sum(record.get("duration_ms", 0) for record in successes)
    total_tokens = sum(record.get("tokens", {}).get("total", 0) for record in successes)
    total_words = sum(record.get("metrics", {}).get("body_words", 0) for record in successes)
    total_chars = sum(record.get("metrics", {}).get("body_chars", 0) for record in successes)
    total_sections = sum(record.get("metrics", {}).get("sections", 0) for record in successes)
    total_subsections = sum(record.get("metrics", {}).get("subsections", 0) for record in successes)

    return {
        "successful_subparts": len(successes),
        "failed_subparts": len(failures),
        "total_duration_ms": total_duration_ms,
        "total_tokens": total_tokens,
        "total_body_words": total_words,
        "total_body_chars": total_chars,
        "total_sections": total_sections,
        "total_subsections": total_subsections,
        "avg_duration_ms": round(total_duration_ms / len(successes), 2) if successes else 0,
        "avg_body_words": round(total_words / len(successes), 2) if successes else 0,
        "avg_body_chars": round(total_chars / len(successes), 2) if successes else 0,
    }


def _compare_records(gemini: dict[str, Any], openrouter: dict[str, Any]) -> dict[str, Any]:
    if gemini.get("status") != "ok" or openrouter.get("status") != "ok":
        return {
            "comparable": False,
            "gemini_status": gemini.get("status"),
            "openrouter_status": openrouter.get("status"),
        }

    g_metrics = gemini["metrics"]
    o_metrics = openrouter["metrics"]
    g_excerpt = str(g_metrics.get("sample_excerpt", "") or "").strip()
    o_excerpt = str(o_metrics.get("sample_excerpt", "") or "").strip()
    excerpt_similarity = round(SequenceMatcher(a=g_excerpt, b=o_excerpt).ratio(), 4) if (g_excerpt or o_excerpt) else 1.0

    return {
        "comparable": True,
        "duration_ms_delta_openrouter_minus_gemini": openrouter["duration_ms"] - gemini["duration_ms"],
        "body_words_delta_openrouter_minus_gemini": o_metrics["body_words"] - g_metrics["body_words"],
        "body_chars_delta_openrouter_minus_gemini": o_metrics["body_chars"] - g_metrics["body_chars"],
        "sections_delta_openrouter_minus_gemini": o_metrics["sections"] - g_metrics["sections"],
        "subsections_delta_openrouter_minus_gemini": o_metrics["subsections"] - g_metrics["subsections"],
        "section_title_jaccard": round(
            _jaccard_similarity(g_metrics["section_titles"], o_metrics["section_titles"]),
            4,
        ),
        "subsection_title_jaccard": round(
            _jaccard_similarity(g_metrics["subsection_titles"], o_metrics["subsection_titles"]),
            4,
        ),
        "section_title_sequence_similarity": round(
            _sequence_similarity(g_metrics["section_titles"], o_metrics["section_titles"]),
            4,
        ),
        "subsection_title_sequence_similarity": round(
            _sequence_similarity(g_metrics["subsection_titles"], o_metrics["subsection_titles"]),
            4,
        ),
        "sample_excerpt_similarity": excerpt_similarity,
    }


def _build_markdown_report(summary: dict[str, Any]) -> str:
    shared = summary["shared_pipeline"]
    gemini = summary["providers"]["gemini"]
    openrouter = summary["providers"]["openrouter"]

    lines: list[str] = []
    lines.append("# Live neural compare")
    lines.append("")
    lines.append(f"- Run ID: `{summary['run_id']}`")
    lines.append(f"- PDF: `{summary['pdf_path']}`")
    lines.append(
        f"- Models: classifier `{summary['models']['classifier']}`, "
        f"segmentador `{summary['models']['segmentador']}`, "
        f"gemini `{summary['models']['gemini_explainer']}`, "
        f"openrouter `{summary['models']['openrouter_explainer']}`, "
        f"ocr-priming `{summary['models']['openrouter_pdf_priming_model']}`"
    )
    if shared.get("segmentation_reused"):
        reuse = shared.get("segmentation_reuse") or {}
        reuse_path = reuse.get("path") or "unknown"
        reuse_sha = reuse.get("sha256") or "unknown"
        lines.append(f"- Segmentation reused: `{reuse_path}` (SHA-256 `{reuse_sha}`)")
    lines.append(
        f"- Shared segmentation: {shared['num_partes']} partes, "
        f"{len(shared['temas_identificados'])} temas, parte comparada `{shared['selected_part']['titulo']}` "
        f"(pp. {shared['selected_part']['pagina_inicio']}-{shared['selected_part']['pagina_fin']})"
    )
    lines.append(
        f"- Shared scope PDF SHA-256: `{shared['shared_scope_pdf']['sha256']}`"
    )
    cache = shared.get("openrouter_pdf_parse_cache", {})
    lines.append(
        f"- OpenRouter PDF parser: `{summary['models']['openrouter_pdf_parser_engine']}`; "
        f"cache status `{cache.get('status', 'unknown')}`; "
        f"cache hit `{cache.get('cache_hit', 'n/a')}`."
    )
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| Provider | Subparts OK | Duration ms | Tokens | Body words | Body chars | Sections | Subsections |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| Gemini | {gemini['aggregate']['successful_subparts']} | {gemini['aggregate']['total_duration_ms']} | "
        f"{gemini['aggregate']['total_tokens']} | {gemini['aggregate']['total_body_words']} | "
        f"{gemini['aggregate']['total_body_chars']} | {gemini['aggregate']['total_sections']} | "
        f"{gemini['aggregate']['total_subsections']} |"
    )
    lines.append(
        f"| OpenRouter | {openrouter['aggregate']['successful_subparts']} | {openrouter['aggregate']['total_duration_ms']} | "
        f"{openrouter['aggregate']['total_tokens']} | {openrouter['aggregate']['total_body_words']} | "
        f"{openrouter['aggregate']['total_body_chars']} | {openrouter['aggregate']['total_sections']} | "
        f"{openrouter['aggregate']['total_subsections']} |"
    )
    lines.append("")
    lines.append("## Per Subpart")
    lines.append("")
    lines.append(
        "| SP | Pages | Prompt SHA-256 | G words | OR words | G ms | OR ms | Section Jaccard | Subsection Jaccard | Excerpt sim |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")

    for item in summary["comparison"]["subparts"]:
        gemini_record = item["gemini"]
        openrouter_record = item["openrouter"]
        compare = item["comparison"]
        gemini_words = gemini_record.get("metrics", {}).get("body_words", 0)
        openrouter_words = openrouter_record.get("metrics", {}).get("body_words", 0)
        gemini_ms = gemini_record.get("duration_ms", 0)
        openrouter_ms = openrouter_record.get("duration_ms", 0)
        lines.append(
            f"| {item['numero_subparte']} | {item['pagina_inicio']}-{item['pagina_fin']} | "
            f"`{item['shared_prompt_sha256'][:12]}` | {gemini_words} | {openrouter_words} | "
            f"{gemini_ms} | {openrouter_ms} | {compare.get('section_title_jaccard', 'n/a')} | "
            f"{compare.get('subsection_title_jaccard', 'n/a')} | {compare.get('sample_excerpt_similarity', 'n/a')} |"
        )

    lines.append("")
    lines.append("## Qualitative Notes")
    lines.append("")
    for item in summary["comparison"]["subparts"]:
        g_excerpt = (
            str(item.get("gemini", {}).get("metrics", {}).get("sample_excerpt", "") or "").strip().replace("\n", " ")
        )
        o_excerpt = (
            str(item.get("openrouter", {}).get("metrics", {}).get("sample_excerpt", "") or "").strip().replace("\n", " ")
        )
        excerpt_sim = item.get("comparison", {}).get("sample_excerpt_similarity", "n/a")
        lines.append(
            f"- SP {item['numero_subparte']} `{item['titulo']}`: prompt `{item['shared_prompt_sha256'][:12]}`, "
            f"Gemini words {item['gemini'].get('metrics', {}).get('body_words', 0)}, "
            f"OpenRouter words {item['openrouter'].get('metrics', {}).get('body_words', 0)}, "
            f"section overlap {item['comparison'].get('section_title_jaccard', 'n/a')}, excerpt sim {excerpt_sim}."
        )
        if g_excerpt:
            lines.append(f"  - Gemini excerpt: {g_excerpt[:260]}")
        if o_excerpt:
            lines.append(f"  - OpenRouter excerpt: {o_excerpt[:260]}")

    assembled = summary["comparison"].get("assembled")
    if assembled:
        lines.append("")
        lines.append("## Assembled Part")
        lines.append("")
        lines.append(
            f"- Gemini assembled words: {assembled['gemini'].get('metrics', {}).get('total_chars', 0)} chars / "
            f"{assembled['gemini'].get('metrics', {}).get('body_words', 0)} body words."
        )
        lines.append(
            f"- OpenRouter assembled words: {assembled['openrouter'].get('metrics', {}).get('total_chars', 0)} chars / "
            f"{assembled['openrouter'].get('metrics', {}).get('body_words', 0)} body words."
        )
        formatter_meta = assembled.get("openrouter_formatter")
        if formatter_meta:
            lines.append(
                f"- OpenRouter formatter: status `{formatter_meta.get('status', 'unknown')}`, "
                f"duration `{formatter_meta.get('duration_ms', 0)}` ms, "
                f"tokens `{formatter_meta.get('usage', {}).get('total_tokens', 0)}`."
            )
            raw_record = assembled.get("openrouter_raw")
            if raw_record:
                lines.append(
                    f"- OpenRouter raw assembled words: {raw_record.get('metrics', {}).get('total_chars', 0)} chars / "
                    f"{raw_record.get('metrics', {}).get('body_words', 0)} body words."
                )
        lines.append(
            f"- Assembled section-title Jaccard: {assembled['comparison'].get('section_title_jaccard', 'n/a')}."
        )

    return "\n".join(lines) + "\n"


def _load_segmentation_from_artifact(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Segmentation artifact not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Segmentation artifact must be a JSON object")

    partes = data.get("partes")
    if not isinstance(partes, list) or not partes:
        raise ValueError("Segmentation artifact missing non-empty 'partes' list")

    first = partes[0]
    if not isinstance(first, dict) or "numero" not in first or "titulo" not in first:
        raise ValueError("Segmentation artifact 'partes[0]' missing required fields ('numero', 'titulo')")

    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini-model", dest="gemini_model", default=GEMINI_EXPLAINER_MODEL)
    parser.add_argument(
        "--openrouter-model",
        dest="openrouter_model",
        default=OPENROUTER_EXPLAINER_MODEL,
    )
    parser.add_argument(
        "--reuse-segmentation",
        dest="reuse_segmentation",
        default="",
        help=(
            "Path to a previously saved segmentation artifact JSON (e.g. shared_01_segmentation.json). "
            "If set, STEP 3 (Segmentador) is skipped and the loaded segmentation is reused as-is."
        ),
    )
    parser.add_argument(
        "--format-openrouter",
        dest="format_openrouter",
        action="store_true",
        help="Pass the assembled OpenRouter explainer through the formatter.",
    )
    parser.add_argument(
        "--only-subpart",
        dest="only_subpart",
        type=int,
        default=0,
        metavar="N",
        help=(
            "If >0, run explainers only for subpart N (1-based index within the first parte), "
            "e.g. 1 for the first subpart. Skips full-part assembly (misleading if only one slice is generated)."
        ),
    )
    parser.add_argument(
        "--openrouter-only",
        dest="openrouter_only",
        action="store_true",
        help="Skip Gemini explainer calls; only run OpenRouter (Gemini still used for classifier/upload).",
    )
    args = parser.parse_args()

    gemini_explainer_model = (args.gemini_model or GEMINI_EXPLAINER_MODEL).strip()
    openrouter_explainer_model = (args.openrouter_model or OPENROUTER_EXPLAINER_MODEL).strip()
    reuse_segmentation_path = (args.reuse_segmentation or "").strip()
    only_subpart = int(args.only_subpart or 0)
    openrouter_only = bool(args.openrouter_only)
    skip_full_part_assembly = only_subpart > 0

    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_api_key:
        log.error("GEMINI_API_KEY not set")
        sys.exit(1)

    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not openrouter_api_key:
        log.error("OPENROUTER_API_KEY not set")
        sys.exit(1)

    pdf_path = os.path.join(PROJECT_ROOT, "neural_archive_merged_extract (3) (1).pdf")
    if not os.path.isfile(pdf_path):
        log.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(PROJECT_ROOT, "test_output", f"live_compare_neural_{run_id}")
    os.makedirs(output_dir, exist_ok=True)

    from google import genai
    from backend.agents.page_classifier import run_page_classifier
    from backend.agents.segmentador import run_segmentador, DEFAULT_DESCRIPTION
    from backend.agents.explainer import run_subpart_explainer
    from backend.agents.explainer_openrouter import (
        OPENROUTER_PDF_PARSER_ENGINE,
        OPENROUTER_PDF_PRIMING_MODEL,
        run_subpart_explainer_or,
    )
    from backend.gemini_model_routing import MODEL_CLASSIFIER, MODEL_SEGMENTADOR
    from backend.agents.formatter import format_explainer_content
    from backend.pdf_utils import add_page_numbers, extract_page_range
    from backend.gemini_client import upload_file_with_retry
    from backend.openrouter_client import get_or_prime_pdf_parse_cache
    from main import (
        _assemble_part_explainer,
        _build_content_pages_prefix,
        _build_pdf_table_of_contents,
        _build_subpart_pdf_prompt,
        _continuity_block_from_previous_part,
        _find_parte_by_numero,
        _part_handoff_base,
        _select_openrouter_pdf_pages,
    )

    client = genai.Client(api_key=gemini_api_key)

    log.info("=" * 80)
    log.info("STEP 0: Adding page numbers to PDF")
    log.info("=" * 80)
    numbered_pdf = add_page_numbers(pdf_path)
    total_pages = len(PdfReader(numbered_pdf).pages)
    log.info("Total pages: %d", total_pages)

    log.info("=" * 80)
    log.info("STEP 1: Uploading numbered PDF to Gemini")
    log.info("=" * 80)
    upload_start = time.time()
    uploaded = upload_file_with_retry(client, numbered_pdf, max_retries=5)
    file_uri = uploaded.uri
    upload_ms = int((time.time() - upload_start) * 1000)
    log.info("Upload done in %dms -> %s", upload_ms, file_uri)

    log.info("=" * 80)
    log.info("STEP 2: Running Page Classifier")
    log.info("=" * 80)
    clf_start = time.time()
    content_pages, clf_usage, _clf_raw = run_page_classifier(
        gemini_api_key,
        file_uri,
        total_pages,
        MODEL_CLASSIFIER,
    )
    clf_ms = int((time.time() - clf_start) * 1000)
    log.info("Page classifier done in %dms", clf_ms)
    log.info("Content pages: %d / %d", len(content_pages), total_pages)
    log.info("Content page set: %s", sorted(content_pages))

    openrouter_document_pdf_path = numbered_pdf
    openrouter_document_pdf_sha256 = _sha256_file(openrouter_document_pdf_path)

    log.info("=" * 80)
    log.info("STEP 3: Running Segmentador")
    log.info("=" * 80)
    content_prefix = _build_content_pages_prefix(content_pages, total_pages)
    seg_description = content_prefix + DEFAULT_DESCRIPTION

    segmentation_reused = False
    segmentation_reuse_meta: dict[str, Any] | None = None

    if reuse_segmentation_path:
        try:
            segmentation = _load_segmentation_from_artifact(reuse_segmentation_path)
        except Exception as exc:
            log.error(
                "Failed to reuse segmentation from %s: %s",
                reuse_segmentation_path,
                exc,
                exc_info=True,
            )
            sys.exit(1)

        segmentation_reused = True
        seg_ms = 0
        seg_usage = None

        reuse_abs = os.path.abspath(reuse_segmentation_path)
        segmentation_reuse_meta = {
            "path": reuse_abs,
            "sha256": _sha256_file(reuse_abs),
        }
        segmentation_path = _save_json("shared_01_segmentation", segmentation, output_dir)
        log.info("Reused segmentation artifact (%s) -> copied to %s", reuse_abs, segmentation_path)
    else:
        seg_start = time.time()
        segmentation, seg_usage = run_segmentador(
            gemini_api_key,
            file_uri,
            seg_description,
            MODEL_SEGMENTADOR,
            mime_type="application/pdf",
            source_kind="pdf",
        )
        seg_ms = int((time.time() - seg_start) * 1000)
        segmentation_path = _save_json("shared_01_segmentation", segmentation, output_dir)

    num_partes = len(segmentation.get("partes", []))
    temas_identificados = segmentation.get("temas_identificados", [])
    if segmentation_reused:
        log.info(
            "Segmentador skipped (reused artifact) -> %d partes, %d temas",
            num_partes,
            len(temas_identificados),
        )
    else:
        log.info(
            "Segmentador done in %dms -> %d partes, %d temas",
            seg_ms,
            num_partes,
            len(temas_identificados),
        )

    if num_partes == 0:
        log.error("No partes found in segmentation")
        sys.exit(1)

    first_parte = segmentation["partes"][0]
    part_id = first_parte["numero"]
    subpartes = list(first_parte.get("subpartes", []))

    table_of_contents = _build_pdf_table_of_contents(segmentation, num_partes)
    pg_inicio = first_parte.get("pagina_inicio")
    pg_fin = first_parte.get("pagina_fin")
    pdf_scope_mode = "full_document"
    local_scope_pdf = numbered_pdf

    if pg_inicio and pg_fin:
        pdf_scope_mode = "subpdf_buffered"
        local_scope_pdf = extract_page_range(numbered_pdf, pg_inicio, pg_fin, buffer=1)
        log.info("Extracted shared scope PDF pages %s-%s with buffer=1", pg_inicio, pg_fin)
    else:
        log.warning("Selected part has no page range; both explainers will use full numbered PDF")

    shared_scope_pdf_path = os.path.join(output_dir, "shared_scope_part.pdf")
    shutil.copyfile(local_scope_pdf, shared_scope_pdf_path)
    shared_scope_pdf_sha256 = _sha256_file(shared_scope_pdf_path)
    log.info("Shared scope PDF copied to %s", shared_scope_pdf_path)

    scope_upload_start = time.time()
    scope_uploaded = upload_file_with_retry(client, shared_scope_pdf_path, max_retries=5)
    scope_file_uri = scope_uploaded.uri
    scope_upload_ms = int((time.time() - scope_upload_start) * 1000)
    log.info("Shared scope PDF uploaded in %dms -> %s", scope_upload_ms, scope_file_uri)

    log.info("=" * 80)
    log.info("STEP 3.5: Priming OpenRouter PDF parse cache")
    log.info("=" * 80)
    openrouter_cache_start = time.time()
    openrouter_cache: dict[str, Any]
    cache_entry: Any = None
    try:
        cache_entry = get_or_prime_pdf_parse_cache(
            source_path=openrouter_document_pdf_path,
            api_key=openrouter_api_key,
            model=OPENROUTER_PDF_PRIMING_MODEL,
            engine=OPENROUTER_PDF_PARSER_ENGINE,
            filename="document.pdf",
            expected_page_numbers=tuple(sorted(content_pages)),
        )
        openrouter_cache_ms = int((time.time() - openrouter_cache_start) * 1000)
        openrouter_cache = {
            "status": "ok",
            "engine": OPENROUTER_PDF_PARSER_ENGINE,
            "cache_hit": cache_entry.cache_hit,
            "cache_path": cache_entry.cache_path,
            "source_sha256": cache_entry.source_sha256,
            "cached_pages_count": len(cache_entry.cached_page_numbers),
            "requested_pages_count": len(cache_entry.expected_page_numbers),
            "duration_ms": openrouter_cache_ms,
        }
        log.info(
            "OpenRouter PDF cache ready in %dms -> hit=%s path=%s cached_pages=%d",
            openrouter_cache_ms,
            cache_entry.cache_hit,
            cache_entry.cache_path,
            len(cache_entry.cached_page_numbers),
        )
    except Exception as exc:
        openrouter_cache_ms = int((time.time() - openrouter_cache_start) * 1000)
        openrouter_cache = {
            "status": "error",
            "engine": OPENROUTER_PDF_PARSER_ENGINE,
            "duration_ms": openrouter_cache_ms,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
        log.warning(
            "OpenRouter PDF cache priming failed in %dms: %s",
            openrouter_cache_ms,
            exc,
            exc_info=True,
        )

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
        subpartes = [
            {
                "numero_subparte": 1,
                "titulo": first_parte["titulo"],
                "contenido": first_parte.get("contenido", ""),
                "identificacion": first_parte.get("identificacion", ""),
                "pagina_inicio": pg_inicio,
                "pagina_fin": pg_fin,
                "temas_cubiertos": first_parte.get("temas_cubiertos", []),
            }
        ]
        log.warning("No subpartes returned by segmentador; using whole part as a single fallback subpart")

    if only_subpart < 0 or (only_subpart > 0 and only_subpart > len(subpartes)):
        log.error(
            "--only-subpart must be 0 (all subparts) or between 1 and %d inclusive; got %d",
            len(subpartes),
            only_subpart,
        )
        sys.exit(1)
    subpart_indices_to_run = (
        [only_subpart] if only_subpart > 0 else list(range(1, len(subpartes) + 1))
    )
    if only_subpart > 0:
        log.info("Running only subpart %d/%d (--only-subpart)", only_subpart, len(subpartes))

    gemini_records: list[dict[str, Any]] = []
    openrouter_records: list[dict[str, Any]] = []
    gemini_desarrollos: list[list[dict[str, Any]]] = []
    openrouter_desarrollos: list[list[dict[str, Any]]] = []
    subpart_comparisons: list[dict[str, Any]] = []

    log.info("=" * 80)
    log.info(
        "STEP 4: Comparing explainers on shared segmentation output for Parte %d \"%s\"",
        part_id,
        first_parte["titulo"],
    )
    log.info("=" * 80)

    for sp_idx in subpart_indices_to_run:
        subparte = subpartes[sp_idx - 1]
        log.info("-" * 60)
        log.info(
            "Subparte %d/%d: \"%s\" (pp.%s-%s)",
            sp_idx,
            len(subpartes),
            subparte.get("titulo", "?"),
            subparte.get("pagina_inicio", "?"),
            subparte.get("pagina_fin", "?"),
        )
        log.info("-" * 60)

        sp_prompt = _build_subpart_pdf_prompt(
            table_of_contents,
            first_parte,
            subparte,
            subpartes,
            part_id,
            num_partes,
            handoff,
            pdf_scope_mode=pdf_scope_mode,
            nucleo_inicio=nucleo_pi,
            nucleo_fin=nucleo_pf,
        )
        prompt_label = f"shared_02_subparte_{sp_idx:02d}_prompt"
        prompt_path = _save_text(prompt_label, sp_prompt, output_dir)
        prompt_sha256 = _sha256_text(sp_prompt)
        log.info("Shared prompt SHA-256: %s", prompt_sha256)

        gemini_record: dict[str, Any]
        if openrouter_only:
            gemini_record = _build_skipped_record("gemini", "openrouter_only")
        else:
            gemini_start = time.time()
            try:
                gemini_result, gemini_usage = run_subpart_explainer(
                    gemini_api_key,
                    scope_file_uri,
                    sp_prompt,
                    gemini_explainer_model,
                    mime_type="application/pdf",
                )
                gemini_ms = int((time.time() - gemini_start) * 1000)
                gemini_path = _save_json(
                    f"gemini_03_subparte_{sp_idx:02d}_explainer",
                    gemini_result,
                    output_dir,
                )
                gemini_record = _build_success_record(
                    provider="gemini",
                    result=gemini_result,
                    usage=gemini_usage,
                    duration_ms=gemini_ms,
                    artifact_path=gemini_path,
                )
                gemini_desarrollos.append(gemini_result.get("desarrollo", []))
            except Exception as exc:
                log.error("Gemini failed on subparte %d: %s", sp_idx, exc, exc_info=True)
                gemini_record = _build_error_record("gemini", exc)

        openrouter_record: dict[str, Any]
        openrouter_start = time.time()
        try:
            openrouter_result, openrouter_usage = run_subpart_explainer_or(
                source_path=openrouter_document_pdf_path,
                identificacion=sp_prompt,
                model=openrouter_explainer_model,
                mime_type="application/pdf",
                api_key=openrouter_api_key,
                pdf_cache_entry=cache_entry if openrouter_cache.get("status") == "ok" else None,
                page_numbers=_select_openrouter_pdf_pages(
                    content_pages,
                    start_page=subparte.get("pagina_inicio"),
                    end_page=subparte.get("pagina_fin"),
                    buffer=1,
                ),
            )
            openrouter_ms = int((time.time() - openrouter_start) * 1000)
            openrouter_path = _save_json(
                f"openrouter_03_subparte_{sp_idx:02d}_explainer",
                openrouter_result,
                output_dir,
            )
            openrouter_record = _build_success_record(
                provider="openrouter",
                result=openrouter_result,
                usage=openrouter_usage,
                duration_ms=openrouter_ms,
                artifact_path=openrouter_path,
            )
            openrouter_desarrollos.append(openrouter_result.get("desarrollo", []))
        except Exception as exc:
            log.error("OpenRouter failed on subparte %d: %s", sp_idx, exc, exc_info=True)
            openrouter_record = _build_error_record("openrouter", exc)

        gemini_records.append(gemini_record)
        openrouter_records.append(openrouter_record)
        comparison = _compare_records(gemini_record, openrouter_record)

        subpart_summary = {
            "numero_subparte": subparte.get("numero_subparte", sp_idx),
            "titulo": subparte.get("titulo", ""),
            "pagina_inicio": subparte.get("pagina_inicio"),
            "pagina_fin": subparte.get("pagina_fin"),
            "shared_prompt_path": prompt_path,
            "shared_prompt_sha256": prompt_sha256,
            "shared_scope_pdf_path": shared_scope_pdf_path,
            "shared_scope_pdf_sha256": shared_scope_pdf_sha256,
            "gemini": gemini_record,
            "openrouter": openrouter_record,
            "comparison": comparison,
        }
        subpart_comparisons.append(subpart_summary)
        _save_json(f"compare_04_subparte_{sp_idx:02d}_summary", subpart_summary, output_dir)

    assembled_summary: dict[str, Any] | None = None
    openrouter_assembled_raw_record: dict[str, Any] | None = None
    openrouter_formatter_meta: dict[str, Any] | None = None
    if skip_full_part_assembly:
        gemini_assembled_record = _build_skipped_record(
            "gemini",
            "Skipped full-part assembly because --only-subpart was set.",
        )
        openrouter_assembled_record = _build_skipped_record(
            "openrouter",
            "Skipped full-part assembly because --only-subpart was set.",
        )
    elif all(record.get("status") == "ok" for record in gemini_records):
        gemini_assembled = _assemble_part_explainer(first_parte, gemini_desarrollos)
        gemini_assembled_path = _save_json(
            "gemini_05_assembled_part_explainer",
            gemini_assembled,
            output_dir,
        )
        gemini_assembled_record = _build_success_record(
            provider="gemini",
            result=gemini_assembled,
            usage=None,
            duration_ms=0,
            artifact_path=gemini_assembled_path,
        )
    else:
        gemini_assembled_record = {
            "provider": "gemini",
            "status": "skipped",
            "reason": "Not all Gemini subparts completed successfully.",
        }

    if skip_full_part_assembly:
        pass
    elif all(record.get("status") == "ok" for record in openrouter_records):
        openrouter_assembled = _assemble_part_explainer(first_parte, openrouter_desarrollos)
        openrouter_raw_label = (
            "openrouter_05_assembled_part_explainer_raw"
            if args.format_openrouter
            else "openrouter_05_assembled_part_explainer"
        )
        openrouter_assembled_path = _save_json(
            openrouter_raw_label,
            openrouter_assembled,
            output_dir,
        )
        openrouter_assembled_raw_record = _build_success_record(
            provider="openrouter",
            result=openrouter_assembled,
            usage=None,
            duration_ms=0,
            artifact_path=openrouter_assembled_path,
        )
        openrouter_assembled_record = openrouter_assembled_raw_record
        if args.format_openrouter:
            formatter_start = time.time()
            try:
                openrouter_formatted, formatter_usage = asyncio.run(
                    format_explainer_content(gemini_api_key, openrouter_assembled)
                )
                formatter_ms = int((time.time() - formatter_start) * 1000)
                openrouter_formatted_path = _save_json(
                    "openrouter_06_assembled_part_explainer_formatted",
                    openrouter_formatted,
                    output_dir,
                )
                openrouter_assembled_record = _build_success_record(
                    provider="openrouter",
                    result=openrouter_formatted,
                    usage=None,
                    duration_ms=formatter_ms,
                    artifact_path=openrouter_formatted_path,
                )
                openrouter_formatter_meta = {
                    "status": "ok",
                    "duration_ms": formatter_ms,
                    "usage": formatter_usage,
                    "raw_artifact_path": openrouter_assembled_path,
                    "formatted_artifact_path": openrouter_formatted_path,
                }
            except Exception as exc:
                formatter_ms = int((time.time() - formatter_start) * 1000)
                openrouter_formatter_meta = {
                    "status": "error",
                    "duration_ms": formatter_ms,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "raw_artifact_path": openrouter_assembled_path,
                }
                log.error("OpenRouter formatter failed: %s", exc, exc_info=True)
    else:
        openrouter_assembled_record = {
            "provider": "openrouter",
            "status": "skipped",
            "reason": "Not all OpenRouter subparts completed successfully.",
        }

    if (
        gemini_assembled_record.get("status") == "ok"
        and openrouter_assembled_record.get("status") == "ok"
    ):
        assembled_summary = {
            "gemini": gemini_assembled_record,
            "openrouter": openrouter_assembled_record,
            "comparison": _compare_records(gemini_assembled_record, openrouter_assembled_record),
        }
        if openrouter_assembled_raw_record is not None and args.format_openrouter:
            assembled_summary["openrouter_raw"] = openrouter_assembled_raw_record
        if openrouter_formatter_meta is not None:
            assembled_summary["openrouter_formatter"] = openrouter_formatter_meta

    summary = {
        "run_id": run_id,
        "pdf_path": pdf_path,
        "output_dir": output_dir,
        "run_options": {
            "only_subpart": only_subpart if only_subpart > 0 else None,
            "openrouter_only": openrouter_only,
            "skip_full_part_assembly": skip_full_part_assembly,
        },
        "models": {
            "classifier": MODEL_CLASSIFIER,
            "segmentador": MODEL_SEGMENTADOR,
            "gemini_explainer": gemini_explainer_model,
            "openrouter_explainer": openrouter_explainer_model,
            "openrouter_pdf_parser_engine": OPENROUTER_PDF_PARSER_ENGINE,
            "openrouter_pdf_priming_model": OPENROUTER_PDF_PRIMING_MODEL,
        },
        "shared_pipeline": {
            "total_pages": total_pages,
            "numbered_pdf_path": numbered_pdf,
            "classifier_duration_ms": clf_ms,
            "classifier_tokens": _tokens_gemini(clf_usage),
            "content_pages": sorted(content_pages),
            "segmentador_duration_ms": seg_ms,
            "segmentador_tokens": _tokens_gemini(seg_usage),
            "segmentation_artifact_path": segmentation_path,
            "segmentation_reused": segmentation_reused,
            "segmentation_reuse": segmentation_reuse_meta,
            "num_partes": num_partes,
            "temas_identificados": temas_identificados,
            "selected_part": {
                "numero": first_parte.get("numero"),
                "titulo": first_parte.get("titulo"),
                "pagina_inicio": first_parte.get("pagina_inicio"),
                "pagina_fin": first_parte.get("pagina_fin"),
                "subpartes": len(subpartes),
            },
            "shared_scope_pdf": {
                "path": shared_scope_pdf_path,
                "sha256": shared_scope_pdf_sha256,
                "upload_duration_ms": scope_upload_ms,
            },
            "openrouter_document_pdf": {
                "path": openrouter_document_pdf_path,
                "sha256": openrouter_document_pdf_sha256,
            },
            "openrouter_pdf_parse_cache": openrouter_cache,
            "openrouter_formatter_enabled": args.format_openrouter,
        },
        "providers": {
            "gemini": {
                "records": gemini_records,
                "aggregate": _aggregate_provider(gemini_records),
            },
            "openrouter": {
                "records": openrouter_records,
                "aggregate": _aggregate_provider(openrouter_records),
            },
        },
        "comparison": {
            "same_segmentador_execution": not segmentation_reused,
            "same_prompts_reused_between_explainers": True,
            "same_scope_pdf_reused_between_explainers": True,
            "subparts": subpart_comparisons,
            "assembled": assembled_summary,
        },
    }

    summary_path = _save_json("compare_99_summary", summary, output_dir)
    report = _build_markdown_report(summary)
    report_path = _save_text("compare_99_report", report, output_dir, suffix=".md")

    log.info("=" * 80)
    log.info("DONE")
    log.info("Summary JSON: %s", summary_path)
    log.info("Report MD: %s", report_path)
    log.info("=" * 80)


if __name__ == "__main__":
    main()

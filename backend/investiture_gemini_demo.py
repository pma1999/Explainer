"""Investiture PDF → Gemini: segmentación (Pro), recorte por páginas y explainer (Flash Lite) — demo / test helper."""

from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from pypdf import PdfReader

from backend.gemini_client import upload_file_with_retry
from backend.gemini_model_routing import MODEL_AGENTS, MODEL_SEGMENTADOR
from backend.pdf_utils import add_page_numbers, extract_page_range
from backend.agents.segmentador import DEFAULT_DESCRIPTION, run_segmentador
from backend.agents.explainer import run_explainer
from backend.segmentation_tema_coverage import (
    MAX_SEGMENTATION_COVERAGE_ATTEMPTS,
    SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE,
    SegmentationTemaReport,
    build_tema_coverage_retry_suffix,
    validate_tema_partition,
)


def resolve_gemini_api_key() -> str | None:
    load_dotenv(override=True)
    # Live/integration tests consume quota and require a valid key. To avoid accidental
    # live calls (e.g. when a placeholder key is present in the environment), we require
    # an explicit opt-in flag.
    if (os.environ.get("RUN_LIVE_GEMINI_TESTS") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
    ):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return None


def find_investiture_pdf(repo_root: Path | None = None) -> Path | None:
    root = repo_root or Path(__file__).resolve().parents[1]
    for pattern in ("*Investiture*.pdf", "*investiture*.pdf"):
        matches = list(root.glob(pattern))
        if matches:
            return matches[0]
    return None


def _delete_gemini_file(client: genai.Client, uploaded: Any) -> None:
    name = getattr(uploaded, "name", None)
    if not name:
        return
    try:
        client.files.delete(name=name)
    except Exception:
        pass


def _usage_summary(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    out: dict[str, Any] = {}
    for attr in (
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "tool_use_prompt_token_count",
        "total_token_count",
    ):
        if hasattr(usage, attr):
            out[attr] = getattr(usage, attr)
    return out


def _truncate(s: str, max_len: int = 500) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _ellipsis(s: str, max_len: int) -> str:
    """Truncate for console display with a single Unicode ellipsis (no mid-word cut without hint)."""
    s = (s or "").strip()
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    if max_len <= 1:
        return "…"
    return s[: max_len - 1] + "…"


def _print_segmentation_tema_layout(
    segmentation: dict[str, Any],
    *,
    indent: str = "    ",
) -> None:
    """Full temas_identificados list and per-parte temas_cubiertos (for MECE debugging)."""
    print(f"{indent}Vista detallada — inventario y asignación devueltos por el segmentador:")
    ti = segmentation.get("temas_identificados")
    print(f"{indent}  Inventario completo (temas_identificados):")
    if isinstance(ti, list) and ti:
        n = 0
        for i, item in enumerate(ti, start=1):
            s = str(item).strip() if item is not None else ""
            if not s:
                print(f"{indent}    [{i}] (vacío)")
                continue
            n += 1
            print(f"{indent}    {n:>3}. {s}")
        print(f"{indent}    — Total entradas no vacías: {n} —")
    else:
        print(f"{indent}    (no hay lista o está vacía)")

    partes = segmentation.get("partes")
    print(f"{indent}  Temas por parte (temas_cubiertos):")
    if not isinstance(partes, list) or not partes:
        print(f"{indent}    (sin partes)")
        return
    for p in partes:
        if not isinstance(p, dict):
            print(f"{indent}    (entrada de parte inválida)")
            continue
        num = p.get("numero")
        tit = str(p.get("titulo") or "").strip()
        tit_disp = f"«{tit}»" if tit else "(sin título)"
        print(f"{indent}    Parte {num} {tit_disp}")
        tc = p.get("temas_cubiertos")
        if not isinstance(tc, list) or not tc:
            print(f"{indent}      · (sin temas_cubiertos o no es lista)")
            continue
        shown = 0
        for item in tc:
            line = str(item).strip() if item is not None else ""
            if not line:
                continue
            shown += 1
            print(f"{indent}      {shown:>2}. {line}")
        if shown == 0:
            print(f"{indent}      · (lista sin textos no vacíos)")


def _print_tema_report_deltas(report: SegmentationTemaReport, *, indent: str = "    ") -> None:
    """Print full MECE discrepancy lists (no truncation)."""
    if report.structural_errors:
        print(f"{indent}  Errores de forma ({len(report.structural_errors)}):")
        for e in report.structural_errors:
            print(f"{indent}    · {e}")
    if report.missing:
        print(f"{indent}  Temas del inventario sin ninguna parte ({len(report.missing)}):")
        for m in report.missing:
            print(f"{indent}    · {m}")
    if report.duplicates:
        print(f"{indent}  Temas asignados a más de una parte ({len(report.duplicates)}):")
        for d in report.duplicates:
            nums = ", ".join(str(n) for n in d.part_numbers)
            print(f"{indent}    · «{d.canonical}» → partes {nums}")
    if report.orphans:
        print(
            f"{indent}  Entradas en temas_cubiertos que no coinciden con el inventario "
            f"({len(report.orphans)}):"
        )
        for part_no, raw in report.orphans:
            print(f"{indent}    · Parte {part_no}: {raw}")


def _merge_usage_dicts(usages: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "tool_use_prompt_token_count",
        "total_token_count",
    )
    out: dict[str, Any] = {k: 0 for k in keys}
    for u in usages:
        for k in keys:
            v = u.get(k)
            if v is not None:
                out[k] += int(v)
    return out


@dataclass
class InvestitureDemoResult:
    pdf_path: Path
    segmentation_model: str
    agents_model: str
    total_pages_numbered: int
    segmentation: dict[str, Any]
    first_part: dict[str, Any]
    segment_page_count: int
    segment_expected_pages: int
    explainer: dict[str, Any]
    usage_segmentador: dict[str, Any]
    usage_explainer: dict[str, Any]
    mece_coverage_attempts: int = 1


def run_investiture_pdf_gemini_demo(
    *,
    api_key: str,
    pdf_path: Path | str | None = None,
    verbose: bool = False,
    cleanup_remote_files: bool = True,
) -> InvestitureDemoResult:
    """Run full pipeline: number PDF, upload, segment, extract first part, explainer.

    If ``verbose``, prints a human-readable trace to stdout.
    """
    repo_root = Path(__file__).resolve().parents[1]
    path = Path(pdf_path) if pdf_path else find_investiture_pdf(repo_root)
    if path is None or not path.is_file():
        raise FileNotFoundError(
            "No se encontró PDF de Investiture en la raíz del proyecto. "
            "Coloca el .pdf en la raíz o pasa pdf_path=."
        )

    client = genai.Client(api_key=api_key)

    numbered_path: str | None = None
    segment_path: str | None = None
    uploaded_full = None
    uploaded_seg = None

    def log(msg: str = "", *, box: str | None = None) -> None:
        if not verbose:
            return
        if box:
            line = "═" * 72
            print(f"\n{line}\n  {box}\n{line}")
        else:
            print(msg)

    try:
        orig_pages = len(PdfReader(str(path)).pages)
        log(box="1. Documento de entrada")
        if verbose:
            print(f"  Ruta: {path}")
            print(f"  Páginas (original, sin marcas): {orig_pages}")

        numbered_path = add_page_numbers(str(path))
        total_pages = len(PdfReader(numbered_path).pages)
        log(box="2. PDF numerado (marcas “— Página X / N —”)")
        if verbose:
            print(f"  Páginas tras numerar: {total_pages}")
            print(f"  Temporal: {numbered_path}")

        log(box="3. Subida del PDF completo numerado a Gemini Files")
        uploaded_full = upload_file_with_retry(client, numbered_path, max_retries=5)
        file_uri_full = uploaded_full.uri
        mime = getattr(uploaded_full, "mime_type", None) or "application/pdf"
        if verbose:
            print(f"  MIME: {mime}")
            print(f"  file_uri: {file_uri_full[:80]}…" if len(file_uri_full) > 80 else f"  file_uri: {file_uri_full}")

        log(box=f"4. Segmentador (IA) — modelo {MODEL_SEGMENTADOR}")
        if verbose:
            print("  La IA debe devolver pagina_inicio / pagina_fin por parte según las marcas visibles.")
            print(
                "  Tras cada respuesta, el backend valida que todo tema en temas_identificados "
                f"aparezca exactamente una vez en temas_cubiertos (hasta {MAX_SEGMENTATION_COVERAGE_ATTEMPTS} intentos)."
            )

        segmentation: dict[str, Any] | None = None
        tema_report = None
        usage_seg_per_attempt: list[dict[str, Any]] = []
        mece_attempts = 0

        for seg_attempt in range(MAX_SEGMENTATION_COVERAGE_ATTEMPTS):
            if seg_attempt == 0:
                seg_description = ""
            else:
                assert segmentation is not None and tema_report is not None
                suffix = build_tema_coverage_retry_suffix(
                    attempt=seg_attempt,
                    segmentation=segmentation,
                    report=tema_report,
                )
                base_eff = DEFAULT_DESCRIPTION
                seg_description = f"{base_eff}\n\n{suffix}"

            segmentation, usage_seg = run_segmentador(
                api_key,
                file_uri_full,
                seg_description,
                MODEL_SEGMENTADOR,
                mime,
                "pdf",
            )
            mece_attempts = seg_attempt + 1
            usage_seg_per_attempt.append(_usage_summary(usage_seg))
            if verbose:
                label = "segmentador" if seg_attempt == 0 else f"segmentador (reintento MECE {seg_attempt})"
                print(f"  Uso ({label}): {usage_seg_per_attempt[-1]}")

            tema_report = validate_tema_partition(segmentation)
            if tema_report.is_valid:
                if verbose and not tema_report.empty_temas_inventory:
                    if seg_attempt == 0:
                        print("  Validación MECE de temas: correcta (primer intento).")
                    else:
                        print("  Validación MECE de temas: correcta tras reintento(s).")
                if verbose and tema_report.empty_temas_inventory:
                    print("  Aviso: temas_identificados vacío; validación MECE omitida.")
                break

            if verbose:
                print(
                    f"  Validación MECE fallida (intento {seg_attempt + 1}/{MAX_SEGMENTATION_COVERAGE_ATTEMPTS}): "
                    f"{len(tema_report.missing)} sin asignar, "
                    f"{len(tema_report.duplicates)} duplicados entre partes, "
                    f"{len(tema_report.orphans)} huérfanos, "
                    f"{len(tema_report.structural_errors)} errores de forma."
                )
                _print_segmentation_tema_layout(segmentation, indent="    ")
                _print_tema_report_deltas(tema_report, indent="    ")
        else:
            assert segmentation is not None and tema_report is not None
            raise RuntimeError(
                f"{SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE} "
                f"(detalle: {len(tema_report.missing)} sin asignar, "
                f"{len(tema_report.duplicates)} duplicados, "
                f"{len(tema_report.orphans)} huérfanos, "
                f"{len(tema_report.structural_errors)} estructura)."
            )

        usage_s = _merge_usage_dicts(usage_seg_per_attempt)

        partes = segmentation.get("partes") or []
        if not partes:
            raise RuntimeError("El segmentador no devolvió ninguna parte.")

        if verbose:
            preview = {
                "analisis_texto": _truncate(str(segmentation.get("analisis_texto", "")), 400),
                "decision_num_partes": segmentation.get("decision_num_partes"),
                "decision_justificacion": _truncate(
                    str(segmentation.get("decision_justificacion", "")), 500
                ),
                "temas_identificados": segmentation.get("temas_identificados"),
                "partes_resumen": [
                    {
                        "numero": p.get("numero"),
                        "titulo": p.get("titulo"),
                        "pagina_inicio": p.get("pagina_inicio"),
                        "pagina_fin": p.get("pagina_fin"),
                        "temas_cubiertos": p.get("temas_cubiertos"),
                    }
                    for p in partes
                ],
            }
            print("\n  Resumen JSON (recortado):\n")
            print(textwrap.indent(json.dumps(preview, ensure_ascii=False, indent=2), "    "))

            print("\n  Tabla de partes (páginas y temas asignados):")
            for p in partes:
                tit = _ellipsis(str(p.get("titulo") or ""), 72)
                print(
                    f"    Parte {p.get('numero')}: «{tit}» "
                    f"→ págs. {p.get('pagina_inicio')}–{p.get('pagina_fin')}"
                )
                tc_raw = p.get("temas_cubiertos")
                if not isinstance(tc_raw, list) or not tc_raw:
                    print("      · (sin temas_cubiertos o lista vacía)")
                else:
                    shown = 0
                    for item in tc_raw:
                        line = str(item).strip() if item is not None else ""
                        if not line:
                            continue
                        shown += 1
                        print(f"      {shown}. {line}")
                    if shown == 0:
                        print("      · (sin temas_cubiertos o lista vacía)")

        for p in partes:
            if "pagina_inicio" not in p or "pagina_fin" not in p:
                raise AssertionError("Falta pagina_inicio/pagina_fin en una parte")
            if p["pagina_inicio"] < 1 or p["pagina_fin"] < p["pagina_inicio"]:
                raise AssertionError("Rango de páginas inválido")
            if p["pagina_fin"] > total_pages:
                raise AssertionError(
                    f"pagina_fin {p['pagina_fin']} > total páginas {total_pages}"
                )

        first = partes[0]
        p_start, p_end = int(first["pagina_inicio"]), int(first["pagina_fin"])
        expected_start = max(1, p_start - 1)
        expected_end = min(total_pages, p_end + 1)
        expected_page_count = expected_end - expected_start + 1

        log(box="5. Recorte local (extract_page_range, buffer ±1 como en main.py)")
        if verbose:
            print(
                f"  Parte elegida para demo: {first.get('numero')} — "
                f"{_ellipsis(str(first.get('titulo') or ''), 70)}"
            )
            print(f"  Rango pedido a la IA: {p_start}–{p_end}")
            print(
                f"  Tras buffer: páginas físicas {expected_start}–{expected_end} "
                f"(= {expected_page_count} páginas en el sub-PDF)"
            )

        segment_path = extract_page_range(numbered_path, p_start, p_end, buffer=1)
        seg_pages = len(PdfReader(segment_path).pages)
        if seg_pages != expected_page_count:
            raise AssertionError(
                f"Páginas del sub-PDF ({seg_pages}) != esperadas ({expected_page_count})"
            )
        if verbose:
            print(f"  Sub-PDF temporal: {segment_path}")
            print(f"  Páginas comprobadas con pypdf: {seg_pages}")

        log(box="6. Subida del sub-PDF (solo este archivo va al explainer)")
        uploaded_seg = upload_file_with_retry(client, segment_path, max_retries=5)
        if verbose:
            u = uploaded_seg.uri
            print(f"  file_uri: {u[:80]}…" if len(u) > 80 else f"  file_uri: {u}")

        import main as main_module

        num_partes = len(partes)
        toc = main_module._build_pdf_table_of_contents(segmentation, num_partes)
        demo_handoff = main_module._part_handoff_base(
            first,
            intent_usuario=None,
            continuidad_previa=None,
            vision_global_division=main_module._strip_str(segmentation.get("consideraciones_estudiante")),
        )
        prompt = main_module._build_pdf_agent_prompt(
            toc,
            str(first.get("identificacion") or ""),
            int(first["numero"]),
            num_partes,
            demo_handoff,
            pdf_scope_mode="subpdf_buffered",
            nucleo_inicio=int(first["pagina_inicio"]),
            nucleo_fin=int(first["pagina_fin"]),
        )

        log(box=f"7. Explainer (IA) — modelo {MODEL_AGENTS}, adjunto = sub-PDF anterior")
        if verbose:
            chunks = prompt.split("\n---\n")
            labels = (
                "Tabla de contenidos",
                "Contexto del segmentador (incl. contrato de cobertura / temas de esta parte)",
                "Alcance del PDF adjunto (núcleo vs buffer)",
                "Identificación precisa de la parte",
            )
            print("  Prompt al explainer (texto completo enviado junto al sub-PDF), por bloques:")
            for i, label in enumerate(labels):
                if i >= len(chunks):
                    break
                body = chunks[i].strip()
                print(f"\n  --- Bloque {i + 1}: {label} ---")
                for line in body.splitlines():
                    print(f"    {line}")
            if len(chunks) > len(labels):
                print(f"\n  … ({len(chunks) - len(labels)} bloque(s) adicional(es) omitidos en la etiqueta)")

        explainer_out, usage_exp = run_explainer(
            api_key,
            uploaded_seg.uri,
            prompt,
            MODEL_AGENTS,
            "application/pdf",
        )
        usage_e = _usage_summary(usage_exp)
        if verbose and usage_e:
            print(f"\n  Uso (explainer): {usage_e}")

        if not isinstance(explainer_out, dict):
            raise AssertionError("Explainer no devolvió un objeto JSON")
        for key in ("introduccion", "desarrollo", "conclusion"):
            if key not in explainer_out:
                raise AssertionError(f"Falta clave explainer: {key}")

        log(box="8. Fragmento de la explicación generada (comprobación visual)")
        if verbose:
            intro = explainer_out.get("introduccion") or {}
            if isinstance(intro, dict):
                blob = json.dumps(intro, ensure_ascii=False, indent=2)
            else:
                blob = str(intro)
            print(textwrap.indent(_truncate(blob, 1200), "    "))
            conc = explainer_out.get("conclusion") or {}
            if isinstance(conc, dict):
                cblob = json.dumps(conc, ensure_ascii=False, indent=2)
            else:
                cblob = str(conc)
            print("\n  Conclusión (recorte):\n")
            print(textwrap.indent(_truncate(cblob, 600), "    "))

        log(box="Listo")
        if verbose:
            print(
                "  La IA fijó los rangos de página; el backend recortó y subió solo ese tramo; "
                "el explainer recibió ese sub-PDF y un prompt con tabla de contenidos, "
                "contexto del segmentador (contrato de temas, alcance, núcleo/buffer) y la identificación de la parte."
            )
            if mece_attempts > 1:
                print(f"  Llamadas al segmentador (incl. reintentos MECE): {mece_attempts}")

        return InvestitureDemoResult(
            pdf_path=path,
            segmentation_model=MODEL_SEGMENTADOR,
            agents_model=MODEL_AGENTS,
            total_pages_numbered=total_pages,
            segmentation=segmentation,
            first_part=first,
            segment_page_count=seg_pages,
            segment_expected_pages=expected_page_count,
            explainer=explainer_out,
            usage_segmentador=usage_s,
            usage_explainer=usage_e,
            mece_coverage_attempts=mece_attempts,
        )
    finally:
        for pth in (numbered_path, segment_path):
            if pth and os.path.isfile(pth):
                try:
                    os.unlink(pth)
                except OSError:
                    pass
        if cleanup_remote_files:
            _delete_gemini_file(client, uploaded_full)
            _delete_gemini_file(client, uploaded_seg)

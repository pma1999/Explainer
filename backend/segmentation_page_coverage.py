"""Page-range validation for PDF segmentations.

Validates that:
- Part page ranges cover all content pages without gaps or overlaps (level 1).
- Subpart page ranges within each part are contiguous and cover the full part range (level 2).

Used after run_segmentador to detect and describe page coverage errors,
and to build retry instructions when the model output is incorrect.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

MAX_PAGE_COVERAGE_ATTEMPTS = 3
MAX_PAGES_PER_SUBPART = 15

SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE = (
    "La segmentación no pudo asignar correctamente los rangos de página "
    "tras varios intentos. Revisa el documento o vuelve a intentar el procesamiento."
)


@dataclass(frozen=True, slots=True)
class PartPageError:
    type: str  # "invalid_range" | "overlap" | "missing_content_pages"
    part_numero: int
    detail: str


@dataclass(frozen=True, slots=True)
class SubpartPageError:
    type: str  # "invalid_range" | "gap" | "overlap" | "doesnt_start_at_part" | "doesnt_end_at_part"
    part_numero: int
    subpart_numero: int
    detail: str


@dataclass(frozen=True, slots=True)
class PageCoverageReport:
    is_valid: bool
    part_errors: tuple[PartPageError, ...]
    subpart_errors: tuple[SubpartPageError, ...]


def _try_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_page_coverage(
    segmentation: dict[str, Any],
    content_page_set: frozenset[int],
) -> PageCoverageReport:
    """Validate page range coverage for a PDF segmentation at part and subpart level.

    Args:
        segmentation: The segmentation dict returned by run_segmentador.
        content_page_set: Frozenset of 1-indexed page numbers classified as content.
                          May be empty (e.g. classifier fallback), in which case
                          only overlap errors are detected.

    Returns:
        PageCoverageReport with is_valid=True iff no errors are found.
    """
    part_errors: list[PartPageError] = []
    subpart_errors: list[SubpartPageError] = []

    partes = segmentation.get("partes")
    if not isinstance(partes, list):
        return PageCoverageReport(is_valid=False, part_errors=(), subpart_errors=())

    # ── Level 1: validate part ranges ────────────────────────────────────────
    valid_parts: list[dict[str, Any]] = []

    for parte in partes:
        if not isinstance(parte, dict):
            continue
        num = _try_int(parte.get("numero"))
        if num is None:
            continue
        pi = _try_int(parte.get("pagina_inicio"))
        pf = _try_int(parte.get("pagina_fin"))
        if pi is None or pf is None or pi < 1 or pf < 1 or pi > pf:
            part_errors.append(PartPageError(
                type="invalid_range",
                part_numero=num,
                detail=(
                    f"Parte {num}: pagina_inicio={parte.get('pagina_inicio')!r}, "
                    f"pagina_fin={parte.get('pagina_fin')!r} — rango inválido o ausente."
                ),
            ))
        else:
            valid_parts.append(parte)

    # Sort by pagina_inicio for overlap/gap detection
    valid_parts.sort(key=lambda p: int(p["pagina_inicio"]))

    # Overlap detection between consecutive parts
    for i in range(len(valid_parts) - 1):
        a = valid_parts[i]
        b = valid_parts[i + 1]
        a_num = int(a["numero"])
        b_num = int(b["numero"])
        a_end = int(a["pagina_fin"])
        b_start = int(b["pagina_inicio"])
        if a_end > b_start:
            # a_end == b_start (exactly one shared transition page) is allowed,
            # consistent with subpart boundary rules.
            part_errors.append(PartPageError(
                type="overlap",
                part_numero=a_num,
                detail=(
                    f"Parte {a_num} (termina en pág. {a_end}) se solapa con "
                    f"Parte {b_num} (empieza en pág. {b_start})."
                ),
            ))

    # Content page gap detection (skip if any invalid_range errors to avoid noise)
    has_invalid_range = any(e.type == "invalid_range" for e in part_errors)
    if not has_invalid_range and content_page_set:
        covered: set[int] = set()
        for parte in valid_parts:
            pi = int(parte["pagina_inicio"])
            pf = int(parte["pagina_fin"])
            covered.update(range(pi, pf + 1))
        missing = sorted(content_page_set - covered)
        if missing:
            part_errors.append(PartPageError(
                type="missing_content_pages",
                part_numero=0,  # 0 = not attributed to a single part
                detail=f"Páginas de contenido sin cubrir por ninguna parte: {_compact_page_list(missing)}",
            ))

    # ── Level 2: validate subpart ranges within each part ────────────────────
    # Only validate parts that had no level-1 errors
    errored_part_numbers = {e.part_numero for e in part_errors if e.part_numero != 0}

    for parte in valid_parts:
        p_num = int(parte["numero"])
        if p_num in errored_part_numbers:
            continue
        p_pi = int(parte["pagina_inicio"])
        p_pf = int(parte["pagina_fin"])

        subpartes = parte.get("subpartes")
        if not subpartes:  # None or empty list → valid (whole part is one implicit subpart)
            continue
        if not isinstance(subpartes, list):
            continue

        valid_sps: list[dict[str, Any]] = []
        for sp in subpartes:
            if not isinstance(sp, dict):
                continue
            sp_num = _try_int(sp.get("numero_subparte"))
            sp_pi = _try_int(sp.get("pagina_inicio"))
            sp_pf = _try_int(sp.get("pagina_fin"))
            if sp_num is None or sp_pi is None or sp_pf is None or sp_pi < 1 or sp_pf < 1 or sp_pi > sp_pf:
                subpart_errors.append(SubpartPageError(
                    type="invalid_range",
                    part_numero=p_num,
                    subpart_numero=sp_num or 0,
                    detail=(
                        f"Parte {p_num} Subparte {sp_num}: "
                        f"pagina_inicio={sp.get('pagina_inicio')!r}, "
                        f"pagina_fin={sp.get('pagina_fin')!r} — inválido."
                    ),
                ))
            else:
                valid_sps.append(sp)

        if not valid_sps:
            continue

        valid_sps.sort(key=lambda s: int(s["pagina_inicio"]))

        # First subpart must start at part's pagina_inicio
        first_start = int(valid_sps[0]["pagina_inicio"])
        first_num = int(valid_sps[0]["numero_subparte"])
        if first_start != p_pi:
            subpart_errors.append(SubpartPageError(
                type="doesnt_start_at_part",
                part_numero=p_num,
                subpart_numero=first_num,
                detail=(
                    f"Parte {p_num}: la primera subparte (SP{first_num}) empieza en pág. {first_start} "
                    f"pero la parte empieza en pág. {p_pi}."
                ),
            ))

        # Last subpart must end at part's pagina_fin
        last_end = int(valid_sps[-1]["pagina_fin"])
        last_num = int(valid_sps[-1]["numero_subparte"])
        if last_end != p_pf:
            subpart_errors.append(SubpartPageError(
                type="doesnt_end_at_part",
                part_numero=p_num,
                subpart_numero=last_num,
                detail=(
                    f"Parte {p_num}: la última subparte (SP{last_num}) termina en pág. {last_end} "
                    f"pero la parte termina en pág. {p_pf}."
                ),
            ))

        # Gaps and overlaps between consecutive subparts
        for j in range(len(valid_sps) - 1):
            a = valid_sps[j]
            b = valid_sps[j + 1]
            a_num = int(a["numero_subparte"])
            b_num = int(b["numero_subparte"])
            a_end = int(a["pagina_fin"])
            b_start = int(b["pagina_inicio"])
            if a_end + 1 < b_start:
                subpart_errors.append(SubpartPageError(
                    type="gap",
                    part_numero=p_num,
                    subpart_numero=a_num,
                    detail=(
                        f"Parte {p_num}: hueco entre SP{a_num} (termina pág. {a_end}) "
                        f"y SP{b_num} (empieza pág. {b_start}). "
                        f"Páginas sin cubrir: {_compact_page_list(list(range(a_end + 1, b_start)))}."
                    ),
                ))
            elif a_end > b_start:
                # Strict overlap (more than one shared page) → error.
                # a_end == b_start (exactly one shared transition page) is allowed.
                subpart_errors.append(SubpartPageError(
                    type="overlap",
                    part_numero=p_num,
                    subpart_numero=a_num,
                    detail=(
                        f"Parte {p_num}: solapamiento entre SP{a_num} (termina pág. {a_end}) "
                        f"y SP{b_num} (empieza pág. {b_start})."
                    ),
                ))

    # ── Level 3: subpart max-pages check ─────────────────────────────────────
    # Only check valid subparts (skip parts with level-1 errors).
    # invalid_range subparts are already caught in level-2; here we only flag
    # subparts whose range is valid but exceeds the per-subpart page budget.
    errored_subpart_keys: set[tuple[int, int]] = {
        (e.part_numero, e.subpart_numero)
        for e in subpart_errors
        if e.type == "invalid_range"
    }
    for parte in valid_parts:
        p_num = int(parte["numero"])
        if p_num in errored_part_numbers:
            continue
        for sp in (parte.get("subpartes") or []):
            if not isinstance(sp, dict):
                continue
            sp_num = _try_int(sp.get("numero_subparte"))
            sp_pi = _try_int(sp.get("pagina_inicio"))
            sp_pf = _try_int(sp.get("pagina_fin"))
            if sp_num is None or sp_pi is None or sp_pf is None:
                continue
            if (p_num, sp_num) in errored_subpart_keys:
                continue
            page_count = sp_pf - sp_pi + 1
            if page_count > MAX_PAGES_PER_SUBPART:
                subpart_errors.append(SubpartPageError(
                    type="too_many_pages",
                    part_numero=p_num,
                    subpart_numero=sp_num,
                    detail=(
                        f"Parte {p_num} Subparte {sp_num}: abarca {page_count} páginas "
                        f"(pág. {sp_pi}–{sp_pf}), supera el máximo permitido de {MAX_PAGES_PER_SUBPART}. "
                        f"Subdivídela en 2 o más subpartes de ≤{MAX_PAGES_PER_SUBPART} páginas cada una."
                    ),
                ))

    is_valid = not part_errors and not subpart_errors
    return PageCoverageReport(
        is_valid=is_valid,
        part_errors=tuple(part_errors),
        subpart_errors=tuple(subpart_errors),
    )


def _compact_page_list(pages: list[int]) -> str:
    """Convert a sorted list of page numbers to a compact range string.

    E.g. [3, 4, 5, 10] → '3-5, 10'
    """
    if not pages:
        return ""
    ranges: list[str] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(ranges)


def _compact_segmentation_ranges(segmentation: dict[str, Any], max_chars: int = 6000) -> str:
    """Extract page-range fields from segmentation for the retry message."""
    partes = segmentation.get("partes")
    slim: list[dict[str, Any]] = []
    if isinstance(partes, list):
        for p in partes:
            if not isinstance(p, dict):
                continue
            entry: dict[str, Any] = {
                "numero": p.get("numero"),
                "titulo": p.get("titulo"),
                "pagina_inicio": p.get("pagina_inicio"),
                "pagina_fin": p.get("pagina_fin"),
            }
            sps = p.get("subpartes")
            if isinstance(sps, list):
                sp_entries = []
                for sp in sps:
                    if not isinstance(sp, dict):
                        continue
                    sp_entries.append({
                        "numero_subparte": sp.get("numero_subparte"),
                        "pagina_inicio": sp.get("pagina_inicio"),
                        "pagina_fin": sp.get("pagina_fin"),
                    })
                entry["subpartes"] = sp_entries
            slim.append(entry)
    text = json.dumps(slim, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n… [truncado]"
    return text


def build_page_coverage_retry_suffix(
    *,
    attempt: int,
    segmentation: dict[str, Any],
    report: PageCoverageReport,
    content_page_set: frozenset[int],
) -> str:
    """Build a correction message block for a page coverage retry.

    Returns a string starting with <correccion_rangos_pagina> that describes
    each error and lists the requirements for a valid correction.
    """
    lines: list[str] = [
        "<correccion_rangos_pagina>",
        f"Intento de corrección: {attempt + 1}. Los rangos de página de la respuesta anterior no son correctos.",
        "",
        "INSTRUCCIÓN CRÍTICA: Esta es una corrección EXCLUSIVA de rangos de página.",
        "Tu respuesta anterior tenía la estructura CORRECTA.",
        "DEBES reproducir exactamente: número de partes, títulos de partes y subpartes, y todos los demás campos textuales.",
        "SOLO modifica los valores de pagina_inicio y pagina_fin donde se indican los errores,",
        "o añade subpartes nuevas donde se indique que una subparte tiene demasiadas páginas.",
        "",
    ]

    if content_page_set:
        lines += [
            f"PÁGINAS DE CONTENIDO QUE DEBEN CUBRIRSE: {_compact_page_list(sorted(content_page_set))}",
            "",
        ]

    range_and_overlap_errors = [e for e in report.part_errors if e.type != "missing_content_pages"]
    missing_errors = [e for e in report.part_errors if e.type == "missing_content_pages"]

    if range_and_overlap_errors:
        lines.append("ERRORES EN RANGOS DE PARTES:")
        for e in range_and_overlap_errors:
            lines.append(f"  - {e.detail}")
        lines.append("")

    if missing_errors:
        for e in missing_errors:
            lines.append(f"COBERTURA INCOMPLETA: {e.detail}")
        lines.append("")

    # Split subpart errors into structural vs too-many-pages for clarity
    structural_sp_errors = [e for e in report.subpart_errors if e.type != "too_many_pages"]
    too_many_pages_errors = [e for e in report.subpart_errors if e.type == "too_many_pages"]

    if structural_sp_errors:
        by_part: dict[int, list[SubpartPageError]] = {}
        for e in structural_sp_errors:
            by_part.setdefault(e.part_numero, []).append(e)
        lines.append("ERRORES EN RANGOS DE SUBPARTES:")
        for p_num in sorted(by_part):
            lines.append(f"  Parte {p_num}:")
            for e in by_part[p_num]:
                lines.append(f"    - {e.detail}")
        lines.append("")

    if too_many_pages_errors:
        lines.append(f"SUBPARTES CON DEMASIADAS PÁGINAS (máximo permitido: {MAX_PAGES_PER_SUBPART} páginas por subparte):")
        by_part_tmp: dict[int, list[SubpartPageError]] = {}
        for e in too_many_pages_errors:
            by_part_tmp.setdefault(e.part_numero, []).append(e)
        for p_num in sorted(by_part_tmp):
            lines.append(f"  Parte {p_num}:")
            for e in by_part_tmp[p_num]:
                lines.append(f"    - {e.detail}")
        lines.append("")

    lines += [
        "REQUISITOS PARA LA CORRECCIÓN:",
        "  - pagina_inicio y pagina_fin de cada parte: enteros positivos con pagina_inicio ≤ pagina_fin.",
        "  - Rangos de partes sin solapamientos: parte_i.pagina_fin <= parte_{i+1}.pagina_inicio (se permite una página de transición compartida, igual que entre subpartes).",
        "  - Todas las páginas de contenido cubiertas por exactamente una parte.",
        "  - Subpartes de cada parte contiguas: subparte_j.pagina_fin + 1 == subparte_{j+1}.pagina_inicio "
        "(o subparte_j.pagina_fin == subparte_{j+1}.pagina_inicio si la página de transición contiene "
        "el final de la subparte anterior y el inicio de la siguiente — solo se permite UNA página compartida).",
        "  - Primera subparte de cada parte: pagina_inicio == parte.pagina_inicio.",
        "  - Última subparte de cada parte: pagina_fin == parte.pagina_fin.",
        f"  - Ninguna subparte puede abarcar más de {MAX_PAGES_PER_SUBPART} páginas; si supera el límite, subdivídela en 2 o más subpartes contiguas dentro de la misma parte.",
        "",
        "ESTRUCTURA DE TU RESPUESTA ANTERIOR (conserva todo; solo corrige pagina_inicio/pagina_fin o añade subpartes donde se indique):",
        _compact_segmentation_ranges(segmentation),
        "</correccion_rangos_pagina>",
    ]
    return "\n".join(lines)

"""MECE validation of tema assignment between temas_identificados and partes[].temas_cubiertos.

Used after run_segmentador to ensure every global theme is assigned to exactly one part
and to build retry instructions when the model output is inconsistent.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_SEGMENTATION_COVERAGE_ATTEMPTS = 3

SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE = (
    "La segmentación no pudo asignar correctamente todos los temas del documento a las partes "
    "tras varios intentos. Revisa el documento o vuelve a intentar el procesamiento."
)


def _normalize_tema_key(s: str) -> str:
    t = unicodedata.normalize("NFKC", s).strip()
    return " ".join(t.split())


@dataclass(frozen=True, slots=True)
class TemaDuplicateInfo:
    """A canonical theme string assigned to more than one part."""

    canonical: str
    part_numbers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SegmentationTemaReport:
    is_valid: bool
    missing: tuple[str, ...]
    duplicates: tuple[TemaDuplicateInfo, ...]
    orphans: tuple[tuple[int, str], ...]
    structural_errors: tuple[str, ...]
    empty_temas_inventory: bool


def _inventory_from_temas_identificados(raw: Any) -> tuple[dict[str, str], tuple[str, ...]]:
    """normalized_key -> canonical display string (first occurrence wins)."""
    if not isinstance(raw, list):
        return {}, ("temas_identificados no es una lista.",)
    inv: dict[str, str] = {}
    errors: list[str] = []
    for i, item in enumerate(raw):
        s = str(item).strip() if item is not None else ""
        if not s:
            errors.append(f"temas_identificados[{i}] está vacío o es inválido.")
            continue
        key = _normalize_tema_key(s)
        if not key:
            errors.append(f"temas_identificados[{i}] normaliza a cadena vacía.")
            continue
        if key not in inv:
            inv[key] = s
    return inv, tuple(errors)


def validate_tema_partition(segmentation: dict[str, Any]) -> SegmentationTemaReport:
    """Validate MECE assignment of themes across parts."""
    structural: list[str] = []
    missing: list[str] = []
    duplicates: list[TemaDuplicateInfo] = []
    orphans: list[tuple[int, str]] = []

    inv, inv_errors = _inventory_from_temas_identificados(segmentation.get("temas_identificados"))
    structural.extend(inv_errors)

    partes = segmentation.get("partes")
    if not isinstance(partes, list):
        structural.append("partes no es una lista.")
        return SegmentationTemaReport(
            is_valid=False,
            missing=tuple(),
            duplicates=tuple(),
            orphans=tuple(),
            structural_errors=tuple(structural),
            empty_temas_inventory=len(inv) == 0,
        )

    empty_inventory = len(inv) == 0

    # normalized_key -> set of part numbers that claimed this theme (via matching temas_cubiertos)
    claimed: dict[str, set[int]] = {}

    for idx, parte in enumerate(partes):
        if not isinstance(parte, dict):
            structural.append(f"partes[{idx}] no es un objeto.")
            continue
        num = parte.get("numero")
        try:
            part_no = int(num)
        except (TypeError, ValueError):
            structural.append(f"partes[{idx}] tiene numero inválido: {num!r}.")
            continue

        tc = parte.get("temas_cubiertos")
        if tc is None:
            structural.append(f"Parte {part_no}: falta temas_cubiertos.")
            continue
        if not isinstance(tc, list):
            structural.append(f"Parte {part_no}: temas_cubiertos no es una lista.")
            continue

        for j, item in enumerate(tc):
            raw = str(item).strip() if item is not None else ""
            if not raw:
                structural.append(f"Parte {part_no}: temas_cubiertos[{j}] vacío.")
                continue
            key = _normalize_tema_key(raw)
            if key not in inv:
                orphans.append((part_no, raw))
            else:
                claimed.setdefault(key, set()).add(part_no)

    if structural:
        return SegmentationTemaReport(
            is_valid=False,
            missing=tuple(),
            duplicates=tuple(),
            orphans=tuple(orphans),
            structural_errors=tuple(structural),
            empty_temas_inventory=empty_inventory,
        )

    if empty_inventory:
        if orphans:
            return SegmentationTemaReport(
                is_valid=False,
                missing=tuple(),
                duplicates=tuple(),
                orphans=tuple(orphans),
                structural_errors=tuple(),
                empty_temas_inventory=True,
            )
        return SegmentationTemaReport(
            is_valid=True,
            missing=tuple(),
            duplicates=tuple(),
            orphans=tuple(),
            structural_errors=tuple(),
            empty_temas_inventory=True,
        )

    for key, canonical in inv.items():
        parts_set = claimed.get(key, set())
        if not parts_set:
            missing.append(canonical)
        elif len(parts_set) > 1:
            duplicates.append(
                TemaDuplicateInfo(
                    canonical=canonical,
                    part_numbers=tuple(sorted(parts_set)),
                )
            )

    is_valid = not missing and not duplicates and not orphans
    return SegmentationTemaReport(
        is_valid=is_valid,
        missing=tuple(missing),
        duplicates=tuple(duplicates),
        orphans=tuple(orphans),
        structural_errors=tuple(),
        empty_temas_inventory=False,
    )


def _compact_previous_assignment_json(segmentation: dict[str, Any], max_chars: int = 12000) -> str:
    temas = segmentation.get("temas_identificados")
    if not isinstance(temas, list):
        temas = []
    partes = segmentation.get("partes")
    slim_partes: list[dict[str, Any]] = []
    if isinstance(partes, list):
        for p in partes:
            if isinstance(p, dict):
                slim_partes.append(
                    {
                        "numero": p.get("numero"),
                        "titulo": p.get("titulo"),
                        "temas_cubiertos": p.get("temas_cubiertos"),
                    }
                )
    payload = {
        "temas_identificados": temas,
        "partes_resumen_temas": slim_partes,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n… [truncado]"


def build_tema_coverage_retry_suffix(
    *,
    attempt: int,
    segmentation: dict[str, Any],
    report: SegmentationTemaReport,
) -> str:
    """Append to the user description on segmentation retry (attempt >= 1)."""
    lines: list[str] = [
        "<correccion_asignacion_temas>",
        f"Intento de corrección: {attempt + 1}. La respuesta anterior no cumple la asignación MECE de temas.",
        "",
        "REQUISITOS:",
        "- Cada cadena en temas_cubiertos de cada parte debe ser EXACTAMENTE una de las cadenas de temas_identificados (copia literal).",
        "- Cada tema de temas_identificados debe aparecer en temas_cubiertos de exactamente UNA parte (ni cero ni dos o más).",
        "",
    ]

    if report.structural_errors:
        lines.append("ERRORES DE FORMA:")
        for e in report.structural_errors:
            lines.append(f"  - {e}")
        lines.append("")

    if report.missing:
        lines.append("TEMAS SIN ASIGNAR A NINGUNA PARTE (debes añadir cada uno a temas_cubiertos de una sola parte):")
        for i, m in enumerate(report.missing, start=1):
            lines.append(f"  {i}. {m}")
        lines.append("")

    if report.duplicates:
        lines.append("TEMAS ASIGNADOS A MÁS DE UNA PARTE (debe quedar solo en una):")
        for d in report.duplicates:
            nums = ", ".join(str(n) for n in d.part_numbers)
            lines.append(f"  - «{d.canonical}» aparece en partes: {nums}")
        lines.append("")

    if report.orphans:
        lines.append(
            "ENTRADAS EN temas_cubiertos QUE NO COINCIDEN CON NINGÚN tema de temas_identificados "
            "(sustitúyelas por el texto exacto del inventario o elimínalas):"
        )
        for part_no, raw in report.orphans:
            lines.append(f"  - Parte {part_no}: «{raw}»")
        lines.append("")

    lines.append("RESPUESTA ANTERIOR (referencia mínima, corrige y devuelve el JSON completo válido):")
    lines.append(_compact_previous_assignment_json(segmentation))
    lines.append("</correccion_asignacion_temas>")
    return "\n".join(lines)

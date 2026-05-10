"""Helpers for subpart scope contracts and prompt blocks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SubpartBoundary:
    encabezado: str
    ancla_texto: str


@dataclass(frozen=True, slots=True)
class SharedTransition:
    hay_transicion: bool
    pagina: int
    hasta_texto_inclusive: str
    desde_texto_inclusive: str


@dataclass(frozen=True, slots=True)
class SubpartScopeContract:
    inicio: SubpartBoundary
    fin_ancla_texto: str
    fin_encabezado_siguiente_excluido: str
    transicion_compartida: SharedTransition


def extract_subpart_scope_contract(subparte: dict[str, Any]) -> SubpartScopeContract:
    raw = subparte.get("delimitacion_explainer") or {}
    inicio = raw.get("inicio") or {}
    fin = raw.get("fin") or {}
    transicion = raw.get("transicion_compartida") or {}
    return SubpartScopeContract(
        inicio=SubpartBoundary(
            encabezado=str(inicio.get("encabezado") or "").strip(),
            ancla_texto=str(inicio.get("ancla_texto") or "").strip(),
        ),
        fin_ancla_texto=str(fin.get("ancla_texto") or "").strip(),
        fin_encabezado_siguiente_excluido=str(fin.get("encabezado_siguiente_excluido") or "").strip(),
        transicion_compartida=SharedTransition(
            hay_transicion=bool(transicion.get("hay_transicion")),
            pagina=int(transicion.get("pagina") or 0),
            hasta_texto_inclusive=str(transicion.get("hasta_texto_inclusive") or "").strip(),
            desde_texto_inclusive=str(transicion.get("desde_texto_inclusive") or "").strip(),
        ),
    )


def build_subpart_scope_contract_block(subparte: dict[str, Any]) -> str:
    contract = extract_subpart_scope_contract(subparte)
    lines = [
        "CONTRATO ESTRUCTURADO DE ALCANCE DE LA SUBPARTE",
        f"Páginas núcleo: {subparte.get('pagina_inicio')}-{subparte.get('pagina_fin')}",
        f"Encabezado de inicio permitido: {contract.inicio.encabezado or '(sin encabezado explícito)'}",
        f"Ancla literal de inicio: {contract.inicio.ancla_texto or '(sin ancla literal)'}",
        f"Ancla literal de fin: {contract.fin_ancla_texto or '(sin ancla literal)'}",
        f"Encabezado siguiente excluido: {contract.fin_encabezado_siguiente_excluido or '(ninguno)'}",
    ]
    if contract.transicion_compartida.hay_transicion:
        lines += [
            "",
            f"PÁGINA COMPARTIDA: {contract.transicion_compartida.pagina}",
            f"- Hasta aquí pertenece a la subparte actual: {contract.transicion_compartida.hasta_texto_inclusive}",
            f"- Desde aquí deja de pertenecer a la subparte actual: {contract.transicion_compartida.desde_texto_inclusive}",
        ]
    return "\n".join(lines)


def build_subpart_negative_scope_block(subparte: dict[str, Any], all_subpartes: list[dict[str, Any]]) -> str:
    current_num = int(subparte.get("numero_subparte") or 0)
    lines = ["FRONTERAS NEGATIVAS (NO DESARROLLAR)"]
    for sibling in all_subpartes:
        sibling_num = int(sibling.get("numero_subparte") or 0)
        if sibling_num == current_num or sibling_num not in {current_num - 1, current_num + 1}:
            continue
        role = "anterior" if sibling_num < current_num else "siguiente"
        lines.append(f"- Subparte {sibling_num} ({role}): «{sibling.get('titulo', '?')}»")
        contenido = str(sibling.get("contenido") or "").strip()
        if contenido:
            lines.append(f"  Contenido vecino fuera de alcance: {contenido}")
    return "\n".join(lines)

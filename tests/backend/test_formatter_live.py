"""Live Gemini calls for the formatter (JSON + markdown field).

Requires GEMINI_API_KEY, GOOGLE_API_KEY, or GOOGLE_GENERATIVE_AI_API_KEY
(loaded from env or repo-root .env via resolve_gemini_api_key). Consumes quota.

**Ver el informe en consola** (obligatorio ``-s`` para que pytest no capture la salida)::

    pytest tests/backend/test_formatter_live.py -m integration -s

El test principal imprime texto original completo, salida Markdown, comparación de
fidelidad (solo se quita decoración Markdown) y comprobaciones anti-metadatos / anti-título.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google import genai  # noqa: E402

from backend.agents.formatter import _format_text  # noqa: E402
from backend.agents.formatter import format_explainer_content  # noqa: E402
from backend.investiture_gemini_demo import resolve_gemini_api_key  # noqa: E402


def _normalize_for_fidelity(text: str) -> str:
    """Strip common Markdown decoration; collapse space. Used to assert 'solo formato'."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"_+", "", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.casefold().strip()


def _print_section(title: str, body: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n{title}\n{bar}", flush=True)
    print(body, flush=True)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    resolve_gemini_api_key() is None,
    reason="Set GEMINI_API_KEY (or GOOGLE_API_KEY) for live formatter test",
)
async def test_live_formatter_fidelity_full_console_report():
    """Real API: imprime informe legible; exige mismo contenido (solo formato) y sin basura."""
    api_key = resolve_gemini_api_key()
    assert api_key

    client = genai.Client(api_key=api_key)

    ctx = (
        "El Problema de la Dualidad en la Tradición Occidental · "
        "EVOLUCIÓN DE LOS ARGUMENTOS: DE LA BIBLIA A LA RAZÓN"
    )
    # Prosa continua (sin listas) para que la huella sea comparable línea a línea.
    body = (
        "El debate no fue estático. A lo largo del siglo XI (año 1050), la Iglesia desarrolló "
        "argumentos teológicos para legitimar el poder temporal. El concepto de Estado "
        "medieval requería una justificación distinta del mero texto sagrado. Los teólogos "
        "políticos debían articular por qué la autoridad civil podía coexistir con la espiritual.\n\n"
        "Más tarde surgieron dos hitos decisivos: el renacimiento del estudio de la jurisprudencia "
        "romana en el siglo XII y el redescubrimiento de la obra Política de Aristóteles en el "
        "siglo XIII. Ambos aportaron lenguaje y categorías que la escolástica incorporó al "
        "discurso sobre el gobierno.\n\n"
        "La consecuencia fue una teoría del poder estatal apoyada cada vez más en la razón y "
        "en argumentos jurídicos, sin renunciar del todo a marcos teológicos, pero reduciendo "
        "su exclusividad como fundamento último."
    )

    formatted, usage = await _format_text(client, body, ctx)

    assert usage is not None

    orig_norm = _normalize_for_fidelity(body)
    fmt_norm = _normalize_for_fidelity(formatted)
    fingerprint_ok = orig_norm == fmt_norm

    lower = formatted.lower()
    meta_ok = (
        "el texto es de carácter" not in lower
        and "plan de formato" not in lower
        and "requiere un formato que facilite" not in lower
        and "se utilizarán encabezados" not in lower
    )
    dup_snippet = "evolución de los argumentos"
    no_dup_title = dup_snippet not in lower[:1200]

    # Informe visible (usar pytest -s)
    _print_section(
        "FORMATTER LIVE — Contexto (no debe aparecer copiado en el markdown)",
        ctx,
    )
    _print_section(
        f"TEXTO ORIGINAL (planos, {len(body)} caracteres)",
        body,
    )
    _print_section(
        f"SALIDA FORMATEADA (markdown, {len(formatted)} caracteres)",
        formatted,
    )
    _print_section(
        "COMPARACIÓN DE FIDELIDAD (mismo texto tras quitar decoración Markdown)",
        f"Coincide: {fingerprint_ok}\n"
        f"Longitud normalizada orig: {len(orig_norm)} | fmt: {len(fmt_norm)}",
    )
    if not fingerprint_ok:
        # Diff corto para depuración si falla
        o, f = orig_norm, fmt_norm
        prefix = 0
        for i in range(min(len(o), len(f))):
            if o[i] != f[i]:
                prefix = i
                break
        else:
            prefix = min(len(o), len(f))
        snippet_o = o[max(0, prefix - 40) : prefix + 60]
        snippet_f = f[max(0, prefix - 40) : prefix + 60]
        print(f"… primera divergencia cerca de índice {prefix}", flush=True)
        print(f"  orig: …{snippet_o}…", flush=True)
        print(f"  fmt:  …{snippet_f}…", flush=True)

    _print_section(
        "COMPROBACIONES",
        "\n".join(
            [
                f"Sin metadatos tipo 'plan': {meta_ok}",
                f"Sin título duplicado del contexto (primeros ~1200 cc): {no_dup_title}",
                f"Uso — prompt_tokens: {getattr(usage, 'prompt_token_count', '?')} | "
                f"candidates: {getattr(usage, 'candidates_token_count', '?')} | "
                f"thoughts: {getattr(usage, 'thoughts_token_count', '?')}",
            ]
        ),
    )
    print("\n" + "=" * 72 + "\n", flush=True)

    assert fingerprint_ok, (
        "El formateador no debe alterar palabras; solo añadir Markdown. "
        "Revisa el diff impreso arriba (pytest -s)."
    )
    assert meta_ok, "No deben aparecer viñetas de planificación / metadatos."
    assert no_dup_title, "No debe repetirse el título de subsección del contexto al inicio."


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    resolve_gemini_api_key() is None,
    reason="Set GEMINI_API_KEY (or GOOGLE_API_KEY) for live formatter test",
)
async def test_live_format_explainer_content_minimal_dict():
    """Real API: explainer mínimo; imprime los cuatro campos formateados para inspección."""
    api_key = resolve_gemini_api_key()
    assert api_key

    data = {
        "introduccion": "Breve intro de prueba en vivo.",
        "desarrollo": [
            {
                "titulo_seccion": "Sección demo",
                "explicacion_introductoria": "Párrafo introductorio corto.",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Subsección demo",
                        "explicacion_detallada": (
                            "Un solo párrafo con término técnico jurisprudencia y fecha 1050."
                        ),
                    }
                ],
            }
        ],
        "conclusion": "Cierre breve.",
        "conexiones_contextuales": [],
    }

    out, usage = await format_explainer_content(api_key, data)

    assert usage["total_tokens"] > 0
    sub_md = out["desarrollo"][0]["subsecciones"][0]["explicacion_detallada"]
    assert "jurisprudencia" in sub_md.lower() or "1050" in sub_md

    assert out["desarrollo"][0]["titulo_seccion"] == "Sección demo"
    assert out["desarrollo"][0]["subsecciones"][0]["titulo_subseccion"] == "Subsección demo"

    _print_section(
        "FORMATTER LIVE — format_explainer_content (campos de texto)",
        "\n\n".join(
            [
                "--- introduccion ---\n" + out["introduccion"],
                "--- explicacion_introductoria ---\n"
                + out["desarrollo"][0]["explicacion_introductoria"],
                "--- explicacion_detallada ---\n" + sub_md,
                "--- conclusion ---\n" + out["conclusion"],
                f"\n--- usage (total_tokens={usage['total_tokens']}, cost={usage.get('cost')}) ---",
            ]
        ),
    )

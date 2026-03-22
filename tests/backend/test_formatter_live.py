"""Live Gemini calls for the formatter (JSON + markdown field).

Requires GEMINI_API_KEY, GOOGLE_API_KEY, or GOOGLE_GENERATIVE_AI_API_KEY
(loaded from env or repo-root .env via resolve_gemini_api_key). Consumes quota.

Run only this file::

    pytest tests/backend/test_formatter_live.py -m integration -s

Optional: ``FORMATTER_LIVE_VERBOSE=1`` prints a preview of the formatted body.
PowerShell: ``$env:FORMATTER_LIVE_VERBOSE='1'`` before pytest.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google import genai  # noqa: E402

from backend.agents.formatter import _format_text  # noqa: E402
from backend.agents.formatter import format_explainer_content  # noqa: E402
from backend.investiture_gemini_demo import resolve_gemini_api_key  # noqa: E402


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    resolve_gemini_api_key() is None,
    reason="Set GEMINI_API_KEY (or GOOGLE_API_KEY) for live formatter test",
)
async def test_live_formatter_returns_body_without_meta_or_duplicate_title():
    """Real API: structured JSON markdown must not echo context title or planning bullets."""
    api_key = resolve_gemini_api_key()
    assert api_key

    client = genai.Client(api_key=api_key)

    ctx = (
        "El Problema de la Dualidad en la Tradición Occidental · "
        "EVOLUCIÓN DE LOS ARGUMENTOS: DE LA BIBLIA A LA RAZÓN"
    )
    body = (
        "El debate no fue estático. A lo largo del siglo XI (año 1050), la Iglesia desarrolló "
        "argumentos teológicos para legitimar el poder. El concepto de Estado medieval requería "
        "una base distinta del mero texto sagrado. Más tarde aparecieron el renacimiento del "
        "estudio de la jurisprudencia romana en el siglo XII y el redescubrimiento de la "
        "Política de Aristóteles en el XIII."
    )

    formatted, usage = await _format_text(client, body, ctx)

    assert usage is not None
    assert formatted and formatted.strip()
    assert "debate" in formatted.lower()

    lower = formatted.lower()
    assert "el texto es de carácter" not in lower
    assert "plan de formato" not in lower
    assert "requiere un formato que facilite" not in lower

    dup_title = "evolución de los argumentos"
    assert dup_title not in formatted.lower()[:800]

    if os.environ.get("FORMATTER_LIVE_VERBOSE", "").strip().lower() in ("1", "true", "yes"):
        preview = formatted[:1200] + ("…" if len(formatted) > 1200 else "")
        print("\n--- formatter live preview ---\n", preview, "\n------------------------------\n", flush=True)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    resolve_gemini_api_key() is None,
    reason="Set GEMINI_API_KEY (or GOOGLE_API_KEY) for live formatter test",
)
async def test_live_format_explainer_content_minimal_dict():
    """Real API: end-to-end format_explainer_content on a tiny explainer (one subsection)."""
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

#!/usr/bin/env python3
"""Muestra en consola el flujo completo: segmentación Gemini Flash, validación MECE de temas
(con reintentos si hace falta), recorte por páginas y explainer.

Uso (desde la raíz del repo):

  python scripts/demo_investiture_gemini_flow.py

Requiere GEMINI_API_KEY o GOOGLE_API_KEY (o .env). Opcional: GEMINI_LIVE_MODEL.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.investiture_gemini_demo import (  # noqa: E402
    resolve_gemini_api_key,
    run_investiture_pdf_gemini_demo,
)


def main() -> None:
    key = resolve_gemini_api_key()
    if not key:
        print(
            "No hay clave de API. Define GEMINI_API_KEY o GOOGLE_API_KEY\n"
            "(o añádela al archivo .env en la raíz del proyecto).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Ejecutando demo contra Gemini (puede tardar 1–3 minutos)…\n")
    run_investiture_pdf_gemini_demo(api_key=key, verbose=True)
    print()


if __name__ == "__main__":
    main()

"""Live Gemini (Flash) integration: Investiture PDF → segmentador → recorte → explainer.

Requires ``GEMINI_API_KEY`` or ``GOOGLE_API_KEY`` (optional ``GOOGLE_GENERATIVE_AI_API_KEY``)
in the environment or a ``.env`` file at the repository root. Consumes API quota.

Skipped automatically when no key is present (normal CI / local without secrets).

**Ver la traza en consola** (mismo contenido que el script de demo)::

    GEMINI_DEMO_VERBOSE=1 pytest tests/backend/test_gemini_pdf_live_investiture.py -s -m integration

O sin pytest::

    python scripts/demo_investiture_gemini_flow.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Repo root on path for ``backend`` imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.investiture_gemini_demo import (  # noqa: E402
    resolve_gemini_api_key,
    find_investiture_pdf,
    run_investiture_pdf_gemini_demo,
)


@pytest.mark.integration
@pytest.mark.skipif(
    resolve_gemini_api_key() is None,
    reason="Set GEMINI_API_KEY (or GOOGLE_API_KEY) for live Gemini PDF test",
)
def test_live_gemini_flash_segment_investiture_pdf_and_explainer_first_part():
    """End-to-end API calls: Flash segments the numbered PDF; explainer runs on first sub-PDF only."""
    api_key = resolve_gemini_api_key()
    assert api_key

    if find_investiture_pdf() is None:
        pytest.skip("Investiture PDF not found in repository root")

    verbose = os.environ.get("GEMINI_DEMO_VERBOSE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    result = run_investiture_pdf_gemini_demo(
        api_key=api_key,
        verbose=verbose,
        cleanup_remote_files=True,
    )

    assert result.segment_page_count == result.segment_expected_pages
    assert "introduccion" in result.explainer
    assert "desarrollo" in result.explainer
    assert "conclusion" in result.explainer

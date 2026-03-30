# Enrutamiento fijo de modelos Gemini — plan ejecutado

> **Goal:** Segmentador siempre `gemini-3.1-pro-preview`; resto del pipeline `gemini-3.1-flash-lite-preview`. Sin elección de modelo en UI/API. Coste acumulado por llamada con el modelo correcto.

**Estado:** Implementado en rama `feat/gemini-model-routing`.

**Archivos principales:**

- `backend/gemini_model_routing.py` — constantes `MODEL_SEGMENTADOR`, `MODEL_AGENTS`
- `main.py` — `_process_project(project_id, user_id)`, `_update_usage(..., cost_model=...)`, `POST /process` sin query `model`
- Agentes + `formatter.py` — defaults / `FORMATTER_MODEL` desde routing
- `backend/investiture_gemini_demo.py` — `InvestitureDemoResult.segmentation_model` / `agents_model`
- Frontend — eliminado selector de modelo
- Tests — asertos de enrutamiento en `test_pdf_process_flow.py`, `test_web_url_support.py`

**Verificación:**

```bash
set PYTHONPATH=.
pytest tests/backend/ -m "not integration" -q
```

Los tests `integration` (live API) dependen de clave y cuota; no bloquean la verificación offline.

**Plan detallado original:** `.cursor/plans/gemini_model_routing_d95b096d.plan.md` (workspace Cursor).

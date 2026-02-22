"""Explainer API con autenticación Supabase y persistencia en Postgres + Storage."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncGenerator

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(override=True)

DATA_DIR = Path(os.environ.get("EXPLAINER_DATA_DIR") or ("/app/data" if os.environ.get("FLY_APP_NAME") else "data"))
os.environ["EXPLAINER_DATA_DIR"] = str(DATA_DIR)

from backend.auth import get_current_user_id, get_user_id_from_token
from backend.local_data import init_local_data
from backend.supabase_data import (
    create_project as supabase_create_project,
    get_project,
    list_projects,
    update_project,
    delete_project,
    export_projects_payload,
    import_projects_payload,
    download_pdf_to_temp,
    get_user_api_key,
    set_user_api_key,
    delete_user_api_key,
    has_user_api_key,
    get_user_api_key_status,
)
from backend.crypto import mask_api_key
from backend.sse_manager import sse_manager, send_event
from backend.rate_limit import project_create_rate_limit
from backend.pricing import calculate_cost, get_model_name
from backend.gemini_client import upload_file_with_retry, GeminiError, GeminiRateLimitError
from backend.agents.segmentador import run_segmentador
from backend.agents.explainer import run_explainer
from backend.agents.recorrido import run_recorrido
from backend.agents.resources import run_resources
from backend.middleware import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "projects").mkdir(parents=True, exist_ok=True)
    init_local_data()
    print(f"[Startup] Persistencia local inicializada en {DATA_DIR}")
    yield
    print("[Shutdown] Cerrando aplicación")


app = FastAPI(title="Explainer API", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.post("/api/settings/api-key")
async def api_set_api_key(
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    """Store user's API key (BYOK)."""
    if not api_key.startswith("AIza") or len(api_key) < 20:
        raise HTTPException(status_code=400, detail="API key de Gemini inválida")

    set_user_api_key(user_id, api_key, provider="google_gemini")
    print(f"[API Key] User {user_id[:8]}... configured API key: {mask_api_key(api_key)}")
    return {"ok": True}


@app.delete("/api/settings/api-key")
async def api_delete_api_key(user_id: Annotated[str, Depends(get_current_user_id)]):
    """Delete user's API key."""
    delete_user_api_key(user_id)
    print(f"[API Key] User {user_id[:8]}... deleted their API key")
    return {"ok": True}


@app.get("/api/settings/api-key/status")
async def api_api_key_status(user_id: Annotated[str, Depends(get_current_user_id)]):
    """Get API key status for the authenticated user."""
    return get_user_api_key_status(user_id)


@app.post("/api/projects")
@project_create_rate_limit
async def api_create_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    name: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
):
    pdf_filename = file.filename or "documento.pdf"
    pdf_content = await file.read()
    project = supabase_create_project(
        user_id=user_id,
        name=name,
        description=description,
        pdf_filename=pdf_filename,
        pdf_content=pdf_content,
    )
    return project


@app.get("/api/projects")
async def api_list_projects(user_id: Annotated[str, Depends(get_current_user_id)]):
    return list_projects(user_id)


@app.get("/api/projects/export")
async def api_export_projects(user_id: Annotated[str, Depends(get_current_user_id)]):
    return export_projects_payload(user_id)


@app.post("/api/projects/import")
async def api_import_projects(
    user_id: Annotated[str, Depends(get_current_user_id)],
    file: UploadFile = File(...),
):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Debes subir un archivo JSON")
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
        result = import_projects_payload(user_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Backup inválido: {exc}") from exc
    return {"ok": True, **result}


@app.get("/api/projects/{project_id}")
async def api_get_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
):
    project = get_project(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


@app.delete("/api/projects/{project_id}")
async def api_delete_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
):
    if not get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    delete_project(project_id, user_id)
    return {"ok": True}


async def _process_project(project_id: str, user_id: str) -> None:
    pdf_temp_path = None
    try:
        project = get_project(project_id, user_id)
        if not project:
            await send_event(project_id, {"type": "error", "message": "Proyecto no encontrado"})
            return

        # Get user's API key (BYOK) from Supabase
        api_key = get_user_api_key(user_id)
        if not api_key:
            await send_event(project_id, {"type": "error", "message": "No hay API key de Gemini configurada. Configúrala en Ajustes."})
            update_project(project_id, user_id, {"status": "error", "error_message": "API key no configurada"})
            return

        print(f"[Process] Using API key for user {user_id[:8]}...: {mask_api_key(api_key)}")

        from google import genai
        client = genai.Client(api_key=api_key)
        model_name = get_model_name()

        cumulative_usage = {
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }

        def _update_usage(usage_meta):
            if not usage_meta:
                return
            p = getattr(usage_meta, "prompt_token_count", 0)
            c = getattr(usage_meta, "candidates_token_count", 0)
            t = getattr(usage_meta, "thoughts_token_count", 0)
            tt = getattr(usage_meta, "total_token_count", 0)
            cumulative_usage["prompt_tokens"] += p
            cumulative_usage["candidates_tokens"] += c
            cumulative_usage["thoughts_tokens"] += t
            cumulative_usage["total_tokens"] += tt
            cumulative_usage["total_cost"] += calculate_cost(model_name, usage_meta)
            update_project(project_id, user_id, {"usage": cumulative_usage})

        await send_event(project_id, {"type": "uploading"})
        update_project(project_id, user_id, {"status": "uploading"})

        pdf_temp_path = download_pdf_to_temp(project_id, user_id)
        if not pdf_temp_path:
            await send_event(project_id, {"type": "error", "message": "No se pudo descargar el PDF."})
            update_project(project_id, user_id, {"status": "error", "error_message": "PDF no encontrado en almacenamiento"})
            return

        uploaded_file = await asyncio.to_thread(lambda: upload_file_with_retry(client, pdf_temp_path, max_retries=5))
        file_uri = uploaded_file.uri

        update_project(project_id, user_id, {"file_uri": file_uri, "status": "segmenting"})
        await send_event(project_id, {"type": "segmenting"})

        segmentation, usage_meta = await asyncio.to_thread(run_segmentador, api_key, file_uri, project["description"])
        _update_usage(usage_meta)
        await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

        partes_preview = [{"numero": p["numero"], "titulo": p["titulo"]} for p in segmentation["partes"]]
        partes_contenido = {}
        for parte in segmentation["partes"]:
            partes_contenido[str(parte["numero"])] = {
                "status": "pending",
                "explainer": None,
                "recorrido": None,
                "resources": None,
            }

        update_project(project_id, user_id, {
            "segmentation": segmentation,
            "partes_contenido": partes_contenido,
            "status": "processing",
        })
        await send_event(project_id, {"type": "segmented", "partes": partes_preview})

        for parte in segmentation["partes"]:
            part_id = parte["numero"]
            identificacion = parte["identificacion"]
            partes_contenido[str(part_id)]["status"] = "processing"
            update_project(project_id, user_id, {"partes_contenido": partes_contenido})
            await send_event(project_id, {"type": "part_started", "part_id": part_id})

            results = await asyncio.gather(
                asyncio.to_thread(run_explainer, api_key, file_uri, identificacion),
                asyncio.to_thread(run_recorrido, api_key, file_uri, identificacion),
                asyncio.to_thread(run_resources, api_key, file_uri, identificacion),
                return_exceptions=True,
            )

            explainer_data, usage_e = results[0] if not isinstance(results[0], Exception) else (results[0], None)
            recorrido_data, usage_rec = results[1] if not isinstance(results[1], Exception) else (results[1], None)
            resources_data, usage_res = results[2] if not isinstance(results[2], Exception) else (results[2], None)
            for u in [usage_e, usage_rec, usage_res]:
                if u:
                    _update_usage(u)
            await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

            for result, agent_name in [
                (explainer_data, "explainer"),
                (recorrido_data, "recorrido"),
                (resources_data, "resources"),
            ]:
                if isinstance(result, Exception):
                    partes_contenido[str(part_id)][agent_name] = {"error": str(result)}
                else:
                    partes_contenido[str(part_id)][agent_name] = result
                await send_event(project_id, {"type": "agent_completed", "part_id": part_id, "agent": agent_name})

            partes_contenido[str(part_id)]["status"] = "completed"
            update_project(project_id, user_id, {"partes_contenido": partes_contenido})
            await send_event(project_id, {"type": "part_completed", "part_id": part_id})

        update_project(project_id, user_id, {"status": "completed"})
        await send_event(project_id, {"type": "completed"})

    except GeminiRateLimitError as exc:
        # Error específico de rate limit - mensaje amigable
        error_msg = (
            "Se ha excedido el límite de peticiones a Gemini API (429). "
            "El sistema reintentó automáticamente varias veces sin éxito. "
            "Por favor, espera unos minutos e intenta de nuevo, "
            "o considera solicitar un aumento de cuota en Google AI Studio."
        )
        update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
        await send_event(project_id, {"type": "error", "message": error_msg})
    except GeminiError as exc:
        # Error específico de Gemini API con código de estado
        if exc.status_code == 500:
            error_msg = (
                "Error interno en Gemini API (500). "
                "El sistema reintentó automáticamente pero el servicio sigue fallando. "
                "Intenta con un modelo diferente (ej: cambia de Pro a Flash) o espera unos minutos."
            )
        elif exc.status_code == 503:
            error_msg = (
                "Servicio Gemini API temporalmente no disponible (503). "
                "El sistema reintentó varias veces sin éxito. "
                "Por favor, espera unos minutos e intenta de nuevo."
            )
        elif exc.status_code == 504:
            error_msg = (
                "Timeout procesando la petición en Gemini API (504). "
                "El texto puede ser demasiado largo o complejo. "
                "Intenta con un documento más pequeño o un modelo diferente."
            )
        elif exc.status_code == 400:
            error_msg = f"Error en la petición a Gemini API (400): {exc.message}"
        elif exc.status_code == 403:
            error_msg = (
                "Error de permisos en Gemini API (403). "
                "Verifica que tu API key sea válida y tenga acceso al modelo seleccionado."
            )
        else:
            error_msg = f"Error en Gemini API (code={exc.status_code}): {exc.message}"
        update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
        await send_event(project_id, {"type": "error", "message": error_msg})
    except Exception as exc:
        # Error genérico - mostrar mensaje simplificado
        error_str = str(exc)
        if len(error_str) > 200:
            error_str = error_str[:200] + "..."
        error_msg = f"Error inesperado durante el procesamiento: {error_str}"
        update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
        await send_event(project_id, {"type": "error", "message": error_msg})
    finally:
        if pdf_temp_path and os.path.isfile(pdf_temp_path):
            try:
                os.unlink(pdf_temp_path)
            except OSError:
                pass
        await sse_manager.end_stream(project_id)


@app.post("/api/projects/{project_id}/process")
async def api_process_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
    background_tasks: BackgroundTasks,
):
    """Start processing a project using the user's own API key (BYOK)."""
    project = get_project(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    if project["status"] not in ("pending", "error"):
        raise HTTPException(status_code=400, detail=f"El proyecto ya está en estado '{project['status']}'")
    if not has_user_api_key(user_id):
        raise HTTPException(status_code=400, detail="No hay API key de Gemini configurada. Configúrala en Ajustes.")
    background_tasks.add_task(_process_project, project_id, user_id)
    return {"ok": True, "status": "started"}


@app.get("/api/projects/{project_id}/events")
async def api_project_events(
    project_id: str,
    token: str | None = Query(None, alias="token"),
):
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token requerido (query: token=...)")
    if not get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    async def generate() -> AsyncGenerator[str, None]:
        async for event in sse_manager.subscribe_events(project_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\\n\\n"
            if event.get("type") == "stream_end":
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if os.environ.get("ENVIRONMENT") != "production":
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return FileResponse("frontend/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

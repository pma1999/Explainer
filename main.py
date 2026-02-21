"""
Explainer - Backend API con autenticación JWT y API keys por usuario.

Arquitectura:
- FastAPI con SQLAlchemy (SQLite local, PostgreSQL en producción)
- JWT en cookies httpOnly
- API keys de Gemini encriptadas por usuario
- SSE para progreso en tiempo real
"""

import asyncio
import json
import os
import uuid
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiofiles
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(override=True)

# Importar nuevos módulos
from backend.database import (
    init_db, get_db, close_db,
    create_user, get_user_by_email, get_user_by_id, update_user_api_key,
    create_project, get_project, list_projects, update_project, delete_project,
    User, Project
)
from backend.auth import (
    verify_password, hash_password, validate_password_strength,
    validate_email_format, create_access_token, set_auth_cookie, clear_auth_cookie,
    get_current_user, COOKIE_SECURE
)
from backend.crypto import encrypt_api_key, decrypt_api_key
from backend.sse_manager import sse_manager, send_event
from backend.rate_limit import login_rate_limit, register_rate_limit, project_create_rate_limit
from backend.pricing import calculate_cost, get_model_name
from backend.agents.segmentador import run_segmentador
from backend.agents.explainer import run_explainer
from backend.agents.recorrido import run_recorrido
from backend.agents.resources import run_resources
from backend.middleware import SecurityHeadersMiddleware


# ============================================================================
# LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar."""
    # Crear directorios necesarios
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("data/projects").mkdir(parents=True, exist_ok=True)

    # Inicializar base de datos
    init_db()
    print("[Startup] Base de datos inicializada")

    yield

    # Cleanup
    print("[Shutdown] Cerrando aplicación")


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(title="Explainer API", lifespan=lifespan)

# Middleware de seguridad
app.add_middleware(SecurityHeadersMiddleware)

# CORS configurado para producción
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,  # Importante para cookies
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Archivos estáticos (solo en desarrollo, en producción Vercel sirve el frontend)
if os.environ.get("ENVIRONMENT") != "production":
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ============================================================================
# AUTH ENDPOINTS
# ============================================================================

@app.post("/api/auth/register")
@register_rate_limit
async def api_register(request: Request, email: str = Form(...), password: str = Form(...)):
    """Registra un nuevo usuario."""
    # Validar email
    valid, error = validate_email_format(email)
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    # Validar contraseña
    valid, error = validate_password_strength(password)
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    db = get_db()
    try:
        # Verificar si el email ya existe
        existing = get_user_by_email(db, email)
        if existing:
            raise HTTPException(status_code=400, detail="Este email ya está registrado")

        # Crear usuario
        password_hash = hash_password(password)
        user = create_user(db, email=email, password_hash=password_hash)

        # Crear token JWT
        token = create_access_token({
            "sub": user.id,
            "email": user.email
        })

        # Respuesta con cookie
        response = JSONResponse({
            "id": user.id,
            "email": user.email,
            "has_api_key": False
        })
        set_auth_cookie(response, token, remember=False)
        return response

    finally:
        close_db(db)


@app.post("/api/auth/login")
@login_rate_limit
async def api_login(request: Request, email: str = Form(...), password: str = Form(...), remember: bool = Form(False)):
    """Inicia sesión de un usuario."""
    db = get_db()
    try:
        user = get_user_by_email(db, email)
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

        # Crear token JWT
        token = create_access_token({
            "sub": user.id,
            "email": user.email
        })

        # Respuesta con cookie
        response = JSONResponse({
            "id": user.id,
            "email": user.email,
            "has_api_key": bool(user.gemini_api_key_encrypted)
        })
        set_auth_cookie(response, token, remember=remember)
        return response

    finally:
        close_db(db)


@app.post("/api/auth/logout")
async def api_logout():
    """Cierra sesión del usuario."""
    response = JSONResponse({"ok": True})
    clear_auth_cookie(response)
    return response


@app.get("/api/auth/me")
async def api_me(user=Depends(get_current_user)):
    """Obtiene información del usuario actual."""
    db = get_db()
    try:
        db_user = get_user_by_id(db, user["user_id"])
        if not db_user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        return {
            "id": db_user.id,
            "email": db_user.email,
            "has_api_key": bool(db_user.gemini_api_key_encrypted),
            "created_at": db_user.created_at.isoformat() if db_user.created_at else None
        }
    finally:
        close_db(db)


# ============================================================================
# API KEY SETTINGS
# ============================================================================

@app.post("/api/settings/api-key")
async def api_set_api_key(api_key: str = Form(...), user=Depends(get_current_user)):
    """
    Guarda la API key de Gemini del usuario (encriptada).
    """
    # Validar formato básico de API key de Gemini
    if not api_key.startswith("AIza") or len(api_key) < 20:
        raise HTTPException(status_code=400, detail="API key de Gemini inválida")

    db = get_db()
    try:
        # Encriptar la API key
        encrypted = encrypt_api_key(user["user_id"], api_key)

        # Guardar en DB
        update_user_api_key(db, user["user_id"], encrypted)

        return {"ok": True}
    finally:
        close_db(db)


@app.delete("/api/settings/api-key")
async def api_delete_api_key(user=Depends(get_current_user)):
    """Elimina la API key guardada del usuario."""
    db = get_db()
    try:
        update_user_api_key(db, user["user_id"], None)
        return {"ok": True}
    finally:
        close_db(db)


@app.get("/api/settings/api-key/status")
async def api_api_key_status(user=Depends(get_current_user)):
    """Verifica si el usuario tiene una API key guardada."""
    db = get_db()
    try:
        db_user = get_user_by_id(db, user["user_id"])
        return {"has_api_key": bool(db_user and db_user.gemini_api_key_encrypted)}
    finally:
        close_db(db)


# ============================================================================
# PROJECTS ENDPOINTS (Protegidos)
# ============================================================================

@app.post("/api/projects")
@project_create_rate_limit
async def api_create_project(
    name: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    """Crea un nuevo proyecto."""
    db = get_db()
    try:
        # Crear proyecto en DB
        project = create_project(
            db,
            user_id=user["user_id"],
            name=name,
            description=description,
            pdf_filename=file.filename or "documento.pdf"
        )

        # Guardar PDF temporalmente
        project_dir = Path("data/projects") / project.id
        project_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = project_dir / project.pdf_filename
        async with aiofiles.open(pdf_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        return project.to_dict()

    finally:
        close_db(db)


@app.get("/api/projects")
async def api_list_projects(user=Depends(get_current_user)):
    """Lista todos los proyectos del usuario."""
    db = get_db()
    try:
        projects = list_projects(db, user["user_id"])
        return [p.to_dict() for p in projects]
    finally:
        close_db(db)


@app.get("/api/projects/{project_id}")
async def api_get_project(project_id: str, user=Depends(get_current_user)):
    """Obtiene un proyecto específico."""
    db = get_db()
    try:
        project = get_project(db, project_id, user["user_id"])
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")
        return project.to_dict()
    finally:
        close_db(db)


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str, user=Depends(get_current_user)):
    """Elimina un proyecto."""
    db = get_db()
    try:
        # Verificar que existe y pertenece al usuario
        project = get_project(db, project_id, user["user_id"])
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")

        # Eliminar archivos
        project_dir = Path("data/projects") / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)

        # Eliminar de DB
        delete_project(db, project_id, user["user_id"])

        return {"ok": True}
    finally:
        close_db(db)


# ============================================================================
# PROCESSING PIPELINE
# ============================================================================

async def _process_project(project_id: str, user_id: str) -> None:
    """Pipeline de procesamiento con API key del usuario."""
    db = get_db()

    try:
        # Obtener proyecto y usuario
        project = get_project(db, project_id, user_id)
        if not project:
            await send_event(project_id, {"type": "error", "message": "Proyecto no encontrado"})
            return

        user = get_user_by_id(db, user_id)
        if not user or not user.gemini_api_key_encrypted:
            await send_event(project_id, {"type": "error", "message": "No tienes una API key de Gemini configurada. Configúrala en Ajustes."})
            update_project(db, project_id, user_id, {"status": "error", "error_message": "API key no configurada"})
            return

        # Desencriptar API key
        try:
            api_key = decrypt_api_key(user_id, user.gemini_api_key_encrypted)
        except Exception as e:
            await send_event(project_id, {"type": "error", "message": "Error al desencriptar API key. Vuelve a configurarla."})
            update_project(db, project_id, user_id, {"status": "error", "error_message": str(e)})
            return

        from google import genai
        client = genai.Client(api_key=api_key)
        model_name = get_model_name()

        # Tracking de uso
        cumulative_usage = {
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0
        }

        def _update_usage(usage_meta):
            if not usage_meta:
                return

            p = getattr(usage_meta, 'prompt_token_count', 0)
            c = getattr(usage_meta, 'candidates_token_count', 0)
            t = getattr(usage_meta, 'thoughts_token_count', 0)
            tt = getattr(usage_meta, 'total_token_count', 0)

            cumulative_usage["prompt_tokens"] += p
            cumulative_usage["candidates_tokens"] += c
            cumulative_usage["thoughts_tokens"] += t
            cumulative_usage["total_tokens"] += tt
            cumulative_usage["total_cost"] += calculate_cost(model_name, usage_meta)

            update_project(db, project_id, user_id, {"usage": cumulative_usage})

        # 1. Upload PDF a Gemini File API
        await send_event(project_id, {"type": "uploading"})
        update_project(db, project_id, user_id, {"status": "uploading"})

        pdf_path = Path("data/projects") / project_id / project.pdf_filename

        uploaded_file = await asyncio.to_thread(
            lambda: client.files.upload(file=str(pdf_path))
        )
        file_uri = uploaded_file.uri

        update_project(db, project_id, user_id, {"file_uri": file_uri, "status": "segmenting"})
        await send_event(project_id, {"type": "segmenting"})

        # 2. Run Segmentador
        segmentation, usage_meta = await asyncio.to_thread(
            run_segmentador, api_key, file_uri, project.description
        )
        _update_usage(usage_meta)
        await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

        partes_preview = [
            {"numero": p["numero"], "titulo": p["titulo"]}
            for p in segmentation["partes"]
        ]

        # Initialize partes_contenido
        partes_contenido: dict = {}
        for parte in segmentation["partes"]:
            partes_contenido[str(parte["numero"])] = {
                "status": "pending",
                "explainer": None,
                "recorrido": None,
                "resources": None,
            }

        update_project(db, project_id, user_id, {
            "segmentation": segmentation,
            "partes_contenido": partes_contenido,
            "status": "processing"
        })
        await send_event(project_id, {"type": "segmented", "partes": partes_preview})

        # 3. Process each part
        for parte in segmentation["partes"]:
            part_id = parte["numero"]
            identificacion = parte["identificacion"]

            partes_contenido[str(part_id)]["status"] = "processing"
            update_project(db, project_id, user_id, {"partes_contenido": partes_contenido})
            await send_event(project_id, {"type": "part_started", "part_id": part_id})

            # Run 3 agents in parallel
            results = await asyncio.gather(
                asyncio.to_thread(run_explainer, api_key, file_uri, identificacion),
                asyncio.to_thread(run_recorrido, api_key, file_uri, identificacion),
                asyncio.to_thread(run_resources, api_key, file_uri, identificacion),
                return_exceptions=True,
            )

            # Extract results
            explainer_data, usage_e = results[0] if not isinstance(results[0], Exception) else (results[0], None)
            recorrido_data, usage_rec = results[1] if not isinstance(results[1], Exception) else (results[1], None)
            resources_data, usage_res = results[2] if not isinstance(results[2], Exception) else (results[2], None)

            # Update usage
            for u in [usage_e, usage_rec, usage_res]:
                if u:
                    _update_usage(u)

            await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

            # Store results
            for result, agent_name in [
                (explainer_data, "explainer"),
                (recorrido_data, "recorrido"),
                (resources_data, "resources"),
            ]:
                if isinstance(result, Exception):
                    partes_contenido[str(part_id)][agent_name] = {"error": str(result)}
                else:
                    partes_contenido[str(part_id)][agent_name] = result

                await send_event(project_id, {
                    "type": "agent_completed",
                    "part_id": part_id,
                    "agent": agent_name
                })

            partes_contenido[str(part_id)]["status"] = "completed"
            update_project(db, project_id, user_id, {"partes_contenido": partes_contenido})
            await send_event(project_id, {"type": "part_completed", "part_id": part_id})

        update_project(db, project_id, user_id, {"status": "completed"})
        await send_event(project_id, {"type": "completed"})

    except Exception as exc:
        update_project(db, project_id, user_id, {"status": "error", "error_message": str(exc)})
        await send_event(project_id, {"type": "error", "message": str(exc)})

    finally:
        await sse_manager.end_stream(project_id)
        close_db(db)


@app.post("/api/projects/{project_id}/process")
async def api_process_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)
):
    """Inicia el procesamiento de un proyecto."""
    db = get_db()
    try:
        project = get_project(db, project_id, user["user_id"])
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")

        if project.status not in ("pending", "error"):
            raise HTTPException(
                status_code=400,
                detail=f"El proyecto ya está en estado '{project.status}'"
            )

        # Verificar que el usuario tenga API key
        db_user = get_user_by_id(db, user["user_id"])
        if not db_user or not db_user.gemini_api_key_encrypted:
            raise HTTPException(
                status_code=400,
                detail="No tienes una API key de Gemini configurada. Configúrala en Ajustes primero."
            )

        # Iniciar procesamiento en background
        background_tasks.add_task(_process_project, project_id, user["user_id"])

        return {"ok": True, "status": "started"}

    finally:
        close_db(db)


@app.get("/api/projects/{project_id}/events")
async def api_project_events(project_id: str, user=Depends(get_current_user)):
    """Stream de eventos SSE para el progreso del procesamiento."""
    db = get_db()
    try:
        # Verificar que el proyecto existe y pertenece al usuario
        project = get_project(db, project_id, user["user_id"])
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")

        async def generate() -> AsyncGenerator[str, None]:
            async for event in sse_manager.subscribe_events(project_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "stream_end":
                    break

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    finally:
        close_db(db)


# ============================================================================
# FRONTEND (solo en desarrollo)
# ============================================================================

@app.get("/")
async def root():
    """Sirve el frontend."""
    return FileResponse("frontend/index.html")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

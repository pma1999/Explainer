# Explainer — Estudio Académico con IA

Aplicación full-stack para estudiar textos académicos con IA. Segmenta PDFs, genera explicaciones exhaustivas, recorridos anotados y mapas de recursos.

## ✨ Características

- **🔑 BYOK (Bring Your Own Key)**: Cada usuario almacena sus API keys de Gemini y OpenRouter encriptadas en Supabase, disponibles en todos sus dispositivos
- **📄 Procesamiento de PDFs**: Upload y análisis automático con Gemini File API
- **🤖 4 Agentes IA**: Segmentador, Explainer, Recorrido Anotado y Recursos
- **🧠 Selector por ejecución**: El usuario elige en frontend si el explainer usa Gemini o MiniMax vía OpenRouter
- **📊 Progreso en tiempo real**: Server-Sent Events (SSE) para ver el avance
- **💰 Tracking de costos**: Cálculo automático de tokens y costos por proyecto
- **🎨 UI/UX elegante**: Tema "Scholarly Forge" con diseño dark academic

## 🏗️ Arquitectura

```
Frontend (Vercel)          Backend (Koyeb)            Supabase          Gemini + OpenRouter
┌─────────────┐            ┌───────────────┐        ┌──────────────┐       ┌────────────┐
│  HTML/CSS   │  HTTPS     │  FastAPI      │        │  PostgreSQL  │       │  Google    │
│  Vanilla JS │◄──────────►│  BYOK Auth    │◄──────►│  Auth        │◄─────►│  Model APIs│
│             │   SSE      │               │        │  Storage     │       │  (select)  │
└─────────────┘            └───────────────┘        └──────────────┘       └────────────┘
```

## 🚀 Despliegue Rápido

### Requisitos

- Python 3.11+
- Cuenta en [Supabase](https://supabase.com) (base de datos, auth, storage)
- Cuenta en [Koyeb](https://koyeb.com) o [Fly.io](https://fly.io) (backend)
- Cuenta en [Vercel](https://vercel.com) (frontend)

### 1. Clonar y configurar

```bash
git clone <repo-url>
cd explainer

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores
```

### 2. Desarrollo local

```bash
# Windows
start.bat

# macOS/Linux
./start.sh
```

La app estará en `http://localhost:8000`

### 3. Despliegue a producción

Ver [DEPLOY.md](DEPLOY.md) para instrucciones detalladas.

**Resumen:**
```bash
# Backend (Fly.io)
flyctl deploy

# Frontend (Vercel)
vercel --prod
```

## 🧩 Estructura del Proyecto

```
explainer/
├── main.py                    # FastAPI app principal
├── requirements.txt           # Dependencias Python
├── fly.toml                   # Config Fly.io
├── vercel.json                # Config Vercel
├── Dockerfile                 # Container backend
├── DEPLOY.md                  # Guía de despliegue
│
├── backend/
│   ├── crypto.py             # Encriptación de API keys (BYOK)
│   ├── sse_manager.py        # Server-Sent Events
│   ├── rate_limit.py         # Rate limiting
│   ├── middleware.py         # Security headers
│   ├── pricing.py            # Cálculo de costos
│   └── agents/               # Agentes Gemini + explainer OpenRouter
│       ├── segmentador.py
│       ├── explainer.py
│       ├── recorrido.py
│       └── resources.py
│
└── frontend/
    ├── index.html            # SPA HTML
    ├── style.css             # Estilos
    └── app.js                # Lógica frontend
```

## 🔒 Seguridad

- **Encriptación**: API keys de Gemini y OpenRouter encriptadas con AES (clave de aplicación)
- **Headers**: CSP, X-Frame-Options, HSTS, Referrer-Policy
- **XSS**: Escaping de HTML en salida
- **Rate limiting**: Límite por IP en creación de proyectos

## 💰 Costos

| Servicio | Costo |
|----------|-------|
| Supabase (Free tier) | **$0/mes** (500MB DB, 1GB Storage) |
| Koyeb / Fly.io (Hobby) | **$0/mes** |
| Vercel (Hobby) | **$0/mes** |
| Gemini API | **Paga cada usuario con su propia key** |
| OpenRouter API | **Opcional; paga cada usuario con su propia key** |

## 🛠️ Tecnologías

**Backend:**
- FastAPI
- Persistencia local (JSON)
- Cryptography (Fernet)

**Frontend:**
- Vanilla JavaScript
- CSS Custom Properties
- Server-Sent Events

**Deployment:**
- Fly.io (backend)
- Vercel (frontend)
- Docker

## 📄 Licencia

MIT License - ver LICENSE para detalles.

---

Creado con ❤️ para estudiantes y académicos.

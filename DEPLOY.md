# 🚀 Guía de Despliegue — Explainer App

## Arquitectura de Producción

```
┌─────────────────────────────────────────────────────────────┐
│  VERCEL (Frontend) — $0                                     │
│  └── explainer.vercel.app                                   │
├─────────────────────────────────────────────────────────────┤
│  SUPABASE — Auth + Postgres + Storage                       │
│  └── Usuarios, proyectos, PDFs                              │
├─────────────────────────────────────────────────────────────┤
│  FLY.IO (Backend API) — $0                                  │
│  └── explainer-api.fly.dev                                  │
│  ├── Auth JWT + Supabase (proyectos y PDFs en la nube)     │
│  └── API key Gemini en disco/volumen                        │
└─────────────────────────────────────────────────────────────┘
```

## Requisitos

- [Node.js](https://nodejs.org/) (para Vercel CLI)
- [Fly.io CLI](https://fly.io/docs/hands-on/install-flyctl/)
- [Git](https://git-scm.com/)

## Configuración Inicial

### 1. Variables de Entorno de Seguridad

Genera la clave de encriptación para la API key de Gemini:

```bash
# Master key para encriptar la API key (32 bytes base64)
openssl rand -base64 32
```

Guarda este valor; lo necesitarás en Fly.io.

---

## Configuración de Supabase (obligatorio)

La app usa Supabase para usuarios, proyectos y almacenamiento de PDFs.

### 1. Crear proyecto en Supabase

1. Entra en [supabase.com](https://supabase.com) y crea un proyecto.
2. En **Project Settings → API** anota:
   - **Project URL** → `SUPABASE_URL`
   - **anon public** → `SUPABASE_ANON_KEY` (frontend)
   - **service_role** → `SUPABASE_SERVICE_ROLE_KEY` (backend)
   - **JWT Secret** → `SUPABASE_JWT_SECRET`

### 2. Ejecutar la migración

En el **SQL Editor** de Supabase, ejecuta el contenido de:

`supabase/migrations/20260222100000_initial_explainer.sql`

Eso crea la tabla `projects`, RLS y el bucket `project-pdfs`. Si el bucket no se crea por SQL, créalo manualmente en **Storage → New bucket** con nombre `project-pdfs` (privado).

### 3. URLs de redirección (Auth)

En **Authentication → URL Configuration**:

- **Site URL**: tu frontend (ej: `https://explainer.vercel.app`)
- **Redirect URLs**: añade la misma URL si usas redirects tras magic link

---

## Despliegue a Fly.io (Backend)

### Paso 1: Login en Fly.io (CLI)

```bash
flyctl auth login
```

### Paso 2: Crear la App

```bash
flyctl apps create explainer-api
```

### Paso 3: Crear el Volumen (para datos locales)

```bash
flyctl volumes create explainer_data --region mad --size 1
```

### Paso 4: Configurar Secrets

```bash
# Encriptación de la API key de Gemini
flyctl secrets set APP_ENCRYPTION_KEY="tu_key_aqui" -a explainer-api

# Supabase (obligatorio para proyectos y auth)
flyctl secrets set SUPABASE_URL="https://TU_PROYECTO.supabase.co" -a explainer-api
flyctl secrets set SUPABASE_SERVICE_ROLE_KEY="eyJ..." -a explainer-api
flyctl secrets set SUPABASE_JWT_SECRET="tu-jwt-secret" -a explainer-api

# Opcionales
flyctl secrets set ENVIRONMENT="production" -a explainer-api
flyctl secrets set FRONTEND_URL="https://tu-frontend.vercel.app" -a explainer-api
```

### Paso 5: Deploy

```bash
flyctl deploy
```

### Paso 6: Verificar

```bash
flyctl status
flyctl logs
```

La API estará disponible en: `https://explainer-api.fly.dev`

---

## Despliegue a Vercel (Frontend)

### Paso 1: Instalar Vercel CLI

```bash
npm i -g vercel
```

### Paso 2: Login

```bash
vercel login
```

### Paso 3: Deploy

```bash
vercel --prod
```

Sigue las instrucciones:
- Project name: `explainer` (o el que prefieras)
- **Root Directory**: deja el raíz del repo (no solo `./frontend`) para que el build pueda ejecutar `npm run build`.

### Paso 4: Build y variables de entorno en Vercel

En el dashboard de Vercel (tu proyecto → Settings):

1. **Build & Development**
   - **Build Command**: `npm run build` (genera `frontend/config.js` desde las variables de entorno).

2. **Environment Variables** (Settings → Environment Variables). Añade:
   - `EXPLAINER_SUPABASE_URL` = tu Project URL de Supabase (ej: `https://xxx.supabase.co`)
   - `EXPLAINER_SUPABASE_ANON_KEY` = clave **anon** de Supabase (Project Settings → API)

Tras cada deploy, el script `scripts/generate-config.js` crea `frontend/config.js` con esas variables, así el frontend carga Supabase sin errores de MIME ni 404. En local, copia `frontend/config.example.js` a `frontend/config.js` y rellena los valores (o usa env en tu entorno).

### Paso 5: Actualizar Backend con URL del Frontend

```bash
flyctl secrets set FRONTEND_URL="https://explainer.vercel.app" -a explainer-api
```

### Paso 6: Actualizar vercel.json

Edita `vercel.json` y reemplaza `explainer-api.fly.dev` con tu URL real de Fly.io si es diferente.

---

## Verificación Post-Despliegue

### Test Funcional

1. **Configurar API key**: Ve a "Ajustes" y guarda tu API key de Gemini
2. **Crear proyecto**: Sube un PDF y verifica que procesa correctamente
3. Procesamiento completo: segmentación, explicaciones, recorrido, recursos
4. Verificar que SSE muestra progreso en tiempo real
5. Verificar que los costos se calculan correctamente

---

## Comandos Útiles

### Fly.io

```bash
# Ver logs en tiempo real
flyctl logs -a explainer-api

# Restart app
flyctl apps restart explainer-api

# SSH al container
flyctl ssh console -a explainer-api

# Ver status
flyctl status -a explainer-api

# Escalar (si necesitas más recursos)
flyctl scale vm shared-cpu-2x --memory 1024 -a explainer-api
```

### Vercel

```bash
# Deploy de preview
vercel

# Deploy a producción
vercel --prod

# Ver logs
vercel logs
```

---

## Actualizaciones

### Actualizar Backend

```bash
# Hacer cambios en el código
git add .
git commit -m "Update: ..."

# Deploy
flyctl deploy
```

### Actualizar Frontend

```bash
# Hacer cambios
git add .
git commit -m "Update: ..."

# Deploy
vercel --prod
```

---

## Solución de Problemas

### "Failed to fetch"

Verifica en Vercel:
1. Los rewrites en `vercel.json` apuntan a la URL correcta de Fly.io
2. Fly.io está corriendo (`flyctl status`)

---

## Costos

| Servicio | Costo |
|----------|-------|
| Fly.io (512MB RAM, shared CPU) | **$0/mes** (hobby plan) |
| Vercel (Hobby) | **$0/mes** |
| Gemini API | **Paga cada usuario** (tú no pagas) |
| **Total** | **$0/mes** |

---

## Recursos

- [Fly.io Docs](https://fly.io/docs/)
- [Vercel Docs](https://vercel.com/docs)
- [Gemini API Docs](https://ai.google.dev/docs)

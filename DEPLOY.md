# 🚀 Guía de Despliegue — Explainer App

## Arquitectura de Producción

```
┌─────────────────────────────────────────────────────────────┐
│  VERCEL (Frontend) — $0                                     │
│  └── explainer.vercel.app                                   │
├─────────────────────────────────────────────────────────────┤
│  SUPABASE — Auth + Postgres + Storage                       │
│  ├── Usuarios, proyectos, PDFs                              │
│  └── 🔐 API Keys encriptadas por usuario (Gemini/OpenRouter/DeepSeek/Tavily/Mistral)│
├─────────────────────────────────────────────────────────────┤
│  KOYEB (Backend API) — $0                                   │
│  └── criminal-leoline-pma00-1cbf79ad.koyeb.app             │
│  ├── Auth JWT + Supabase (proyectos, PDFs, API keys)       │
│  ├── Encriptación AES-128 (Fernet) con clave maestra       │
│  └── Scale-to-zero (se detiene tras inactividad)           │
└─────────────────────────────────────────────────────────────┘
```

## 🔐 Seguridad API Keys (BYOK - Bring Your Own Key)

Explainer implementa un modelo de seguridad **BYOK** donde cada usuario proporciona y controla sus propias API keys de Gemini y, opcionalmente, OpenRouter, DeepSeek, Tavily y Mistral:

### Modelo de Seguridad


| Aspecto                   | Implementación                                                        |
| ------------------------- | --------------------------------------------------------------------- |
| **Almacenamiento**        | API keys encriptadas en Supabase (Postgres), nunca en texto plano     |
| **Encriptación**          | AES-128-CBC + HMAC-SHA256 vía Fernet                                  |
| **Clave de encriptación** | Derivada por usuario: `SHA256(MASTER_KEY + user_id)`                  |
| **Acceso**                | Row Level Security (RLS): cada usuario solo accede a sus propias keys |
| **Transmisión**           | HTTPS/TLS 1.3 en todo momento                                         |
| **Logs**                  | Solo versiones enmascaradas (`AIza...XXXX`, `sk-or-...XXXX`)          |


### Flujo de Seguridad

1. **Usuario configura su API key** → Frontend envía al backend vía HTTPS + JWT
2. **Backend encripta** → Usa Fernet con clave derivada del `user_id`
3. **Almacenamiento** → Se guarda en Supabase con RLS (solo el propietario puede acceder)
4. **Procesamiento** → El backend desencripta temporalmente en memoria para llamar al proveedor/modelo seleccionado
5. **Nunca se expone** → La API key en texto plano nunca se envía al frontend ni se registra en logs

### Ventajas BYOK

- **Multi-dispositivo**: La API key del usuario está disponible en todos sus dispositivos
- **Segregación total**: Un usuario no puede acceder a las keys de otro (RLS a nivel de BD)
- **Compliance**: Cada usuario es responsable de su propia cuota y facturación con Google, OpenRouter, DeepSeek, Tavily y Mistral
- **Sin riesgo de fuga**: Incluso si la BD se compromete, las keys están encriptadas

## Requisitos

- [Node.js](https://nodejs.org/) (para Vercel CLI)
- [Koyeb CLI](https://www.koyeb.com/docs/cli/installation)
- [Git](https://git-scm.com/)

## Configuración Inicial

### 1. Variables de Entorno de Seguridad

**APP_ENCRYPTION_KEY** es obligatoria en producción. Se usa para encriptar las API keys BYOK de los usuarios. La aplicación **no arrancará** si en `ENVIRONMENT=production` la clave está ausente o coincide con valores conocidos débiles.

Genera una clave segura con:

```bash
openssl rand -base64 32
```

- **Obligatorio en producción**: Sin esta clave, la API falla al iniciar.
- **Nunca uses** valores de ejemplo (`.env.example`) o claves de desarrollo en producción.
- Guarda el valor de forma segura; lo necesitarás en Koyeb.

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

### 2. Ejecutar las migraciones

En el **SQL Editor** de Supabase, ejecuta en orden:

1. `**supabase/migrations/20260222100000_initial_explainer.sql`**
  - Crea la tabla `projects`, RLS y el bucket `project-pdfs`
2. `**supabase/migrations/20260222120000_user_api_keys.sql`**
  - Crea la tabla `user_api_keys` para almacenar API keys encriptadas por usuario (BYOK)
  - Aplica políticas RLS estrictas para aislamiento por usuario
3. `**supabase/migrations/20260408120000_openrouter_pdf_ocr_cache.sql**`
  - Crea la tabla `openrouter_pdf_ocr_cache` (caché del OCR de OpenRouter por hash de PDF + motor), para que el backend no repita trabajo tras scale-to-zero en Koyeb.

Si el bucket no se crea por SQL, créalo manualmente en **Storage → New bucket** con nombre `project-pdfs` (privado).

**Caché OCR (opcional):** Con `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` ya configurados en el backend, el modo por defecto (`OPENROUTER_OCR_CACHE_BACKEND=auto`) persiste el caché en Postgres. No hace falta un secret nuevo. Para forzar solo disco local, define `OPENROUTER_OCR_CACHE_BACKEND=disk`.

### 3. URLs de redirección (Auth)

En **Authentication → URL Configuration**:

- **Site URL**: tu frontend (ej: `https://explainer.vercel.app`)
- **Redirect URLs**: añade la misma URL si usas redirects tras magic link

---

## Despliegue a Koyeb (Backend)

Koyeb ofrece un plan **Starter gratuito** con:

- 1 Web Service gratuito (suficiente para esta app)
- Scale-to-zero (la app se detiene tras ~5 min de inactividad)
- Autoscaling (se reinicia automáticamente al recibir tráfico)
- 100GB/mo de ancho de banda

### Paso 1: Instalar Koyeb CLI

**macOS/Linux:**

```bash
brew install koyeb/tap/koyeb
```

**Windows (PowerShell):**

```powershell
iwr https://raw.githubusercontent.com/koyeb/koyeb-cli/master/install.ps1 -useb | iex
```

**O descarga desde:** [https://github.com/koyeb/koyeb-cli/releases](https://github.com/koyeb/koyeb-cli/releases)

### Paso 2: Login en Koyeb

```bash
koyeb login
```

Se abrirá el navegador para autenticación con GitHub.

### Paso 3: Crear el Servicio

Opción A: **Desde el archivo koyeb.yaml** (recomendado)

```bash
koyeb service create -f koyeb.yaml
```

Opción B: **Desde el dashboard web**

1. Ve a [https://app.koyeb.com](https://app.koyeb.com)
2. Click "Create Service"
3. Selecciona tu repositorio GitHub
4. Selecciona **Dockerfile** como builder
5. Configura:
  - **Instance**: Free (0.1 vCPU, 512MB RAM)
  - **Region**: Frankfurt (fra)
  - **Scaling**: Autoscaling 0-1 instances
  - **Port**: 8080
  - **Health Check**: Puerto 8080, path `/api/settings/api-key/status`

### Paso 4: Configurar Secrets

En el dashboard de Koyeb (tu servicio → Settings → Environment Variables):


| Secret                      | Descripción                                                                                                   |
| --------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `APP_ENCRYPTION_KEY`        | Clave maestra para encriptar API keys. **Generar con:** `openssl rand -base64 32`. Obligatoria en producción. |
| `SUPABASE_URL`              | URL del proyecto Supabase                                                                                     |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key de Supabase                                                                                  |
| `SUPABASE_JWT_SECRET`       | JWT secret de Supabase                                                                                        |
| `FRONTEND_URL`              | URL del frontend en Vercel (para CORS)                                                                        |
| `ENVIRONMENT`               | `production`                                                                                                  |


**O vía CLI:**

```bash
# APP_ENCRYPTION_KEY: genera con "openssl rand -base64 32" y pega el valor
koyeb secret create APP_ENCRYPTION_KEY --value "tu-clave-generada"
koyeb secret create SUPABASE_URL --value "https://xxx.supabase.co"
koyeb secret create SUPABASE_SERVICE_ROLE_KEY --value "eyJ..."
koyeb secret create SUPABASE_JWT_SECRET --value "tu-jwt-secret"
koyeb secret create FRONTEND_URL --value "https://tu-frontend.vercel.app"

# Luego adjunta al servicio
koyeb service update explainer/explainer \
  --secret APP_ENCRYPTION_KEY \
  --secret SUPABASE_URL \
  --secret SUPABASE_SERVICE_ROLE_KEY \
  --secret SUPABASE_JWT_SECRET \
  --secret FRONTEND_URL
```

### Paso 5: Deploy

El servicio se desplegará automáticamente. La URL será:

```
https://[nombre-servicio]-[org].koyeb.app
```

### Paso 6: Verificar

```bash
# Ver logs
koyeb service logs explainer/explainer

# Ver status
koyeb service get explainer/explainer
```

Prueba el health check:

```bash
curl https://tu-app.koyeb.app/api/settings/api-key/status
```

---

## Proveedor Codex / ChatGPT

Explainer puede usar Codex (ChatGPT) como proveedor del explainer. El contenedor incluye el
binario standalone `codex` (build musl estático, **sin Node/npm/Rust** en runtime) instalado en
`/usr/local/bin/codex`, pineado a la versión `0.147.0`.

### Actualización del binario codex

1. **Bump de versión**: comprueba la versión actual con `npm view @openai/codex dist-tags --json`
   (busca el dist-tag de plataforma, p.ej. `linux-x64`).
2. **Re-descargar el tarball** del dist-tag de plataforma (el paquete `@openai/codex-linux-x64`
   es un alias npm; el tarball real vive en `@openai/codex`):

   ```bash
   VERSION=0.147.0-linux-x64   # ajustar a la version objetivo
   curl -fsSL -o /tmp/codex.tgz "https://registry.npmjs.org/@openai/codex/-/codex-${VERSION}.tgz"
   ```

3. **Actualizar el sha256** del tarball:

   ```bash
   sha256sum /tmp/codex.tgz
   ```

   Sustituye el hash literal en el `RUN` del `Dockerfile` (comentario + `echo ... | sha256sum -c -`)
   y aquí abajo. Hash del tarball `codex-0.147.0-linux-x64.tgz` verificado el 2026-08-14:

   ```
   c969740cf8297e4c31905cd551efeb2c99af5080c12c236bdf825598b250139a
   ```

4. **Rebuild + verificación**:

   ```bash
   docker build -t explainer-codex-test .
   docker run --rm explainer-codex-test codex --version
   ```

   Debe imprimir `codex-cli <version>`. Si el layout del tarball cambió, inspecciónalo con
   `tar tzf /tmp/codex.tgz` y ajusta la ruta `package/vendor/x86_64-unknown-linux-musl/bin/codex`.

### Variables de entorno CODEX_*

| Variable | Default | Descripción |
|---|---|---|
| `CODEX_BIN_PATH` | `/usr/local/bin/codex` | Ruta del binario codex (los tests apuntan al fake app-server) |
| `CODEX_MAX_PROCESSES` | `3` | Máximo de procesos `codex app-server` vivos (uno por usuario) |
| `CODEX_PER_PROCESS_MAX_CONCURRENCY` | `5` | Peticiones simultáneas por proceso |
| `CODEX_IDLE_TTL_SECONDS` | `600` | Evicción por inactividad de un proceso |
| `CODEX_REQUEST_TIMEOUT_SECONDS` | `900` | Timeout de una petición JSON-RPC |
| `CODEX_LINK_TIMEOUT_SECONDS` | `600` | Timeout global del vínculo device-code |
| `CODEX_SPAWN_WAIT_SECONDS` | `60` | Espera por un slot del semáforo de procesos |

`CODEX_HOME` no se configura globalmente: se fija por tenant a `/tmp/codex/<user_id>` (modo
0700) en el backend.

### Presupuesto de memoria (instancia nano 512 MB)

| Componente | Estimación |
|---|---|
| Python + uvicorn + app | ~200 MB |
| Proceso `codex app-server` (por tenant, máx. `CODEX_MAX_PROCESSES=3`) | ~80-150 MB RSS c/u según carga |
| **Total pico estimado (3 procesos)** | ~440-650 MB |

Con `CODEX_MAX_PROCESSES=3` el pico puede rozar el límite de 512 MB. Si se observan OOM en
Koyeb, baja `CODEX_MAX_PROCESSES` a 2 o 1 vía env (sin tocar `koyeb.yaml`, que documenta pero
no fija estos valores). El binario musl no requiere Node ni Rust en runtime.

### Logs del app-server

El stderr de cada proceso `codex app-server` se vuelca a un fichero acotado y truncado en cada
spawn:

```
/tmp/codex/<user_id>/app-server.stderr.log
```

Nunca se vierte automáticamente a los logs de la aplicación (no contiene credenciales; el
contenido de `auth.json` nunca se loguea). Consulta este fichero dentro del contenedor para
diagnosticar fallos de spawn o de transporte JSON-RPC.

### Comportamiento en scale-to-zero

- Los procesos `codex app-server` son **efímeros**: con scale-to-zero (Koyeb nano) el
  contenedor y sus procesos desaparecen tras ~5 min de inactividad y se recrean en el próximo
  cold start (5-15 s).
- El **vínculo ChatGPT sobrevive a cold starts**: el `auth.json` cifrado vive en Supabase
  (`user_provider_connections.encrypted_credentials`), no en el disco local del contenedor.
  Al reactivar la app se restaura antes del primer spawn del tenant.
- Evicción idle: dentro de un contenedor vivo, un proceso sin peticiones se evicta tras
  `CODEX_IDLE_TTL_SECONDS` (600 s) liberando memoria; el siguiente uso lo vuelve a lanzar.
- Si el contenedor se reinicia con un vínculo `pending` en vuelo (login device-code a medio
  completar), tras un grace de 60 s el backend lo marca `failed` y el usuario debe reiniciar
  el vínculo.

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

### Paso 5: Actualizar vercel.json con URL de backend

El archivo `vercel.json` ya tiene configurada la URL de Koyeb. Si cambia, actualízalo:

```json
{
  "rewrites": [
    {"source": "/api/(.*)", "destination": "https://tu-app.koyeb.app/api/$1"}
  ]
}
```

---

## Verificación Post-Despliegue

### Test Funcional

1. **Configurar API keys (BYOK)**:
  - Ve a "Ajustes" y guarda tu API key de Gemini, o las claves de DeepSeek + Tavily si quieres usar DeepSeek directo.
  - Si quieres usar modelos OpenRouter en el explainer, guarda además tu API key de OpenRouter.
  - Para PDFs con OpenRouter o DeepSeek directo, guarda también tu API key de Mistral.
  - Verifica que el estado muestra "Configurada"
  - Recarga la página y confirma que persiste (sincronización multi-dispositivo)
2. **Seguridad API keys**:
  - Verifica que la API key nunca aparece en la interfaz después de guardar
  - Los logs solo muestran versión enmascarada (`AIza...XXXX`)
3. **Crear proyecto**: Sube un PDF y verifica que procesa correctamente
4. Procesamiento completo: segmentación, explicaciones, recorrido, recursos
5. Verificar que SSE muestra progreso en tiempo real
6. Verificar que los costos se calculan correctamente

### Verificación de Seguridad (Opcional)

```sql
-- Como admin de Supabase, verifica que RLS funciona:
-- Intentar acceder a API keys de otro usuario debe fallar
SET ROLE authenticated;
SET request.jwt.claim.sub = 'uuid-de-otro-usuario';
SELECT * FROM user_api_keys; -- Debe retornar 0 rows
```

---

## Comandos Útiles

### Koyeb

```bash
# Ver logs en tiempo real
koyeb service logs explainer/explainer

# Ver status del servicio
koyeb service get explainer/explainer

# Redeploy (tras push a main)
koyeb service update explainer/explainer --git-branch main

# Listar todos los servicios
koyeb service list

# Ver secrets configurados
koyeb secret list
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

### Actualizar Backend (Koyeb)

```bash
# Hacer cambios en el código
git add .
git commit -m "Update: ..."
git push origin main

# El deploy es automático si tienes GitHub integration,
# o manualmente:
koyeb service update explainer/explainer --git-branch main
```

### Actualizar Frontend

```bash
# Hacer cambios
git add .
git commit -m "Update: ..."
git push origin main

# Deploy
vercel --prod
```

---

## Solución de Problemas

### "Failed to fetch"

Verifica en Vercel:

1. Los rewrites en `vercel.json` apuntan a la URL correcta de Koyeb
2. Koyeb está corriendo (revisa el dashboard)

### La app en Koyeb tarda en responder

**Esto es normal** - Koyeb usa **scale-to-zero** (gratis). La app se detiene tras ~5 min de inactividad y tarda 5-15 segundos en reiniciarse cuando llega una petición. Esto ahorra costos.

Para evitar cold starts en momentos importantes, puedes hacer ping periódico o usar un plan de pago que mantenga la app siempre activa.

### Errores de CORS

Verifica que `FRONTEND_URL` en los secrets de Koyeb coincida exactamente con tu URL de Vercel (incluyendo `https://`).

---

## Costos


| Servicio                        | Costo                               |
| ------------------------------- | ----------------------------------- |
| Koyeb (Starter - scale-to-zero) | **$0/mes**                          |
| Vercel (Hobby)                  | **$0/mes**                          |
| Gemini API                      | **Paga cada usuario** (tú no pagas) |
| OpenRouter API                  | **Opcional; paga cada usuario**     |
| DeepSeek API                    | **Opcional; paga cada usuario**     |
| Tavily Search API               | **Opcional para DeepSeek directo**  |
| Mistral OCR API                 | **Opcional para PDFs directos/OR**  |
| **Total**                       | **$0/mes**                          |


**Nota**: Koyeb cobra por segundo de uso después del free tier, pero con scale-to-zero y uso personal/development, el costo será $0.

---

## Recursos

- [Koyeb Docs](https://www.koyeb.com/docs)
- [Vercel Docs](https://vercel.com/docs)
- [Gemini API Docs](https://ai.google.dev/docs)


# 🚀 Guía de Despliegue — Explainer App

## Arquitectura de Producción

```
┌─────────────────────────────────────────────────────────────┐
│  VERCEL (Frontend) — $0                                     │
│  └── explainer.vercel.app                                   │
├─────────────────────────────────────────────────────────────┤
│  FLY.IO (Backend API) — $0                                  │
│  └── explainer-api.fly.dev                                  │
│  ├── SQLite en volumen persistente                          │
│  └── Siempre activo (nunca duerme)                          │
└─────────────────────────────────────────────────────────────┘
```

## Requisitos

- [Node.js](https://nodejs.org/) (para Vercel CLI)
- [Fly.io CLI](https://fly.io/docs/hands-on/install-flyctl/)
- [Git](https://git-scm.com/)

## Configuración Inicial

### 1. Variables de Entorno de Seguridad

Genera las claves de encriptación:

```bash
# Master key para encriptar API keys (32 bytes base64)
openssl rand -base64 32

# JWT Secret (cualquier string largo aleatorio)
openssl rand -base64 32
```

Guarda estos valores, los necesitarás en Fly.io.

---

## Despliegue a Fly.io (Backend)

### Paso 1: Login en Fly.io

```bash
flyctl auth login
```

### Paso 2: Crear la App

```bash
flyctl apps create explainer-api
```

### Paso 3: Crear el Volumen (para SQLite)

```bash
flyctl volumes create explainer_data --region mad --size 1
```

### Paso 4: Configurar Secrets

```bash
# Variables obligatorias
flyctl secrets set APP_ENCRYPTION_KEY="tu_key_aqui" -a explainer-api
flyctl secrets set JWT_SECRET="tu_secret_aqui" -a explainer-api

# Variables opcionales (para notificaciones/debug)
flyctl secrets set ENVIRONMENT="production" -a explainer-api
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
- Directory: `./frontend` (cuando lo pregunte)

### Paso 4: Configurar Variables de Entorno en Vercel

Ve al dashboard de Vercel:
1. Selecciona tu proyecto
2. Ve a "Settings" → "Environment Variables"
3. Añade:
   - `FRONTEND_URL` = URL de tu frontend (ej: `https://explainer.vercel.app`)

### Paso 5: Actualizar Backend con URL del Frontend

```bash
flyctl secrets set FRONTEND_URL="https://explainer.vercel.app" -a explainer-api
```

### Paso 6: Actualizar vercel.json

Edita `vercel.json` y reemplaza `explainer-api.fly.dev` con tu URL real de Fly.io si es diferente.

---

## Verificación Post-Despliegue

### Test de Seguridad

1. **Registro de usuario**: Crea una cuenta en `/`
2. **Configurar API key**: Ve a "Ajustes" y guarda tu API key de Gemini
3. **Crear proyecto**: Sube un PDF y verifica que procesa correctamente
4. **Aislamiento**: Intenta acceder a un proyecto de otro usuario (debe dar 404)

### Test Funcional

1. Procesamiento completo de un PDF
2. Verificar que SSE muestra progreso en tiempo real
3. Verificar que los costos se calculan correctamente
4. Cerrar sesión y verificar que no se puede acceder sin login

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

### "Database is locked" (SQLite)

Esto puede pasar con muchas requests concurrentes. Soluciones:
1. Reducir `max_connections` en `database.py`
2. Usar WAL mode (ya está configurado por defecto en SQLite)

### "No autenticado" en frontend

Verifica:
1. Las cookies están habilitadas en el navegador
2. El dominio del backend coincide con el CORS config
3. `credentials: 'include'` está en las requests fetch

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

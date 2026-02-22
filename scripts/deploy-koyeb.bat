@echo off
REM Script de despliegue a Koyeb con configuración para el plan Starter gratuito
REM Koyeb: https://koyeb.com - Serverless platform with scale-to-zero

echo === Despliegue Explainer API a Koyeb ===
echo.

REM Verificar que koyeb CLI está instalado
koyeb version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Koyeb CLI no está instalado
    echo.
    echo Instálalo con uno de estos métodos:
    echo   1. Con PowerShell:   iwr https://raw.githubusercontent.com/koyeb/koyeb-cli/master/install.ps1 -useb ^| iex
    echo   2. Descargar desde:  https://github.com/koyeb/koyeb-cli/releases
    echo.
    echo Mas info: https://www.koyeb.com/docs/cli/installation
    exit /b 1
)

REM Verificar login
koyeb whoami >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: No has iniciado sesion en Koyeb
    echo Ejecuta: koyeb login
    exit /b 1
)

echo [OK] Autenticado en Koyeb
echo.

REM Verificar que existe koyeb.yaml
if not exist "koyeb.yaml" (
    echo Error: No se encontro koyeb.yaml en el directorio actual
    echo Asegurate de estar en la raiz del proyecto
    exit /b 1
)

echo === Configuracion ===
echo App name: explainer-api
echo Region: fra (Frankfurt)
echo Plan: Starter (Free tier with scale-to-zero)
echo.

REM Verificar si el servicio ya existe
echo === Verificando servicio ===
koyeb service list | findstr /C:"explainer-api/explainer-api" >nul
if %errorlevel% equ 0 (
    echo [OK] El servicio ya existe
    set SERVICE_EXISTS=1
) else (
    echo [!] El servicio no existe. Se creara nuevo.
    set SERVICE_EXISTS=0
)
echo.

REM Crear o actualizar el servicio
echo === Desplegando aplicacion ===
if %SERVICE_EXISTS%==0 (
    echo Creando nuevo servicio desde koyeb.yaml...
    koyeb service create -f koyeb.yaml
) else (
    echo Actualizando servicio existente...
    koyeb service update explainer-api/explainer-api --git-branch main
)

echo.
echo === Despliegue completado ===
echo.
echo IMPORTANTE: Configura los secrets antes de usar la app!
echo.
echo Configurar secrets:
echo   koyeb secret create APP_ENCRYPTION_KEY --value "tu-clave-aqui"
echo   koyeb secret create SUPABASE_URL --value "https://xxx.supabase.co"
echo   koyeb secret create SUPABASE_SERVICE_ROLE_KEY --value "eyJ..."
echo   koyeb secret create SUPABASE_JWT_SECRET --value "tu-jwt-secret"
echo   koyeb secret create FRONTEND_URL --value "https://tu-frontend.vercel.app"
echo.
echo Luego adjunta los secrets al servicio:
echo   koyeb service update explainer-api/explainer-api --secret APP_ENCRYPTION_KEY --secret SUPABASE_URL --secret SUPABASE_SERVICE_ROLE_KEY --secret SUPABASE_JWT_SECRET --secret FRONTEND_URL
echo.
echo URL de la API estara disponible en:
echo   https://explainer-api-[org].koyeb.app
echo.
echo Comandos utiles:
echo   Ver logs:      koyeb service logs explainer-api/explainer-api
echo   Ver status:    koyeb service get explainer-api/explainer-api
echo   Ver secrets:   koyeb secret list
echo.
echo Nota: La app usa scale-to-zero (gratis). Despues de ~5 min de inactividad se detiene
echo       y se reinicia automaticamente cuando llega una peticion.
echo.

pause

@echo off
REM Script de despliegue a Fly.io (Windows)

echo === Despliegue Explainer API a Fly.io ===
echo.

REM Verificar que flyctl está instalado
where flyctl >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: flyctl no está instalado
    echo Instálalo desde: https://fly.io/docs/hands-on/install-flyctl/
    exit /b 1
)

REM Verificar login
flyctl auth whoami >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: No has iniciado sesión en Fly.io
    echo Ejecuta: flyctl auth login
    exit /b 1
)

echo [OK] Autenticado en Fly.io

REM Verificar si la app existe
flyctl apps list | findstr "explainer-api-pablo" >nul
if %errorlevel% neq 0 (
    echo Creando app explainer-api-pablo...
    flyctl apps create explainer-api-pablo
)

REM Verificar si el volumen existe
echo.
echo === Verificando volumen persistente ===
flyctl volumes list -a explainer-api-pablo | findstr "data_vol" >nul
if %errorlevel% neq 0 (
    echo El volumen 'data_vol' no existe. Creándolo...
    echo Creando volumen en región cdg (París)...
    flyctl volumes create data_vol -a explainer-api-pablo -r cdg -s 3
    echo [OK] Volumen creado
) else (
    echo [OK] Volumen data_vol ya existe
)

REM Verificar secrets
echo.
echo === Verificando secrets ===

flyctl secrets list -a explainer-api-pablo | findstr "JWT_SECRET" >nul
if %errorlevel% neq 0 (
    echo JWT_SECRET no configurado. Generando...
    for /f "tokens=*" %%a in ('powershell -Command "[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))"') do set JWT_SECRET=%%a
    echo !JWT_SECRET! | flyctl secrets set JWT_SECRET=-a explainer-api-pablo
    echo [OK] JWT_SECRET configurado
) else (
    echo [OK] JWT_SECRET ya configurado
)

flyctl secrets list -a explainer-api-pablo | findstr "APP_ENCRYPTION_KEY" >nul
if %errorlevel% neq 0 (
    echo APP_ENCRYPTION_KEY no configurado. Generando...
    for /f "tokens=*" %%a in ('powershell -Command "[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))"') do set APP_KEY=%%a
    echo !APP_KEY! | flyctl secrets set APP_ENCRYPTION_KEY=-a explainer-api-pablo
    echo [OK] APP_ENCRYPTION_KEY configurado
) else (
    echo [OK] APP_ENCRYPTION_KEY ya configurado
)

echo.
echo === Desplegando aplicación ===
flyctl deploy -a explainer-api-pablo

echo.
echo === Despliegue completado ===
echo.
echo URL de la API: https://explainer-api-pablo.fly.dev
echo.
echo Comandos útiles:
echo   Ver logs:    flyctl logs -a explainer-api-pablo
echo   SSH a la app: flyctl ssh console -a explainer-api-pablo
echo.
pause

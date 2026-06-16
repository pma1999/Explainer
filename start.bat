@echo off
chcp 65001 >nul

REM Script de inicio para desarrollo local (Windows)

echo 🚀 Iniciando Explainer App (Desarrollo)
echo ==========================================

REM Crear directorio de datos si no existe
if not exist "data" mkdir data

REM Verificar si existe .env
if not exist ".env" (
    echo ⚠️  Archivo .env no encontrado. Copiando .env.example...
    copy .env.example .env
    echo 📝 Por favor, edita .env con tus configuraciones
)

REM Activar entorno virtual si existe
if exist "venv\Scripts\activate.bat" (
    echo 📦 Activando entorno virtual...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo 📦 Activando entorno virtual...
    call .venv\Scripts\activate.bat
)

REM Verificar dependencias
echo 📦 Verificando dependencias...
pip install -q -r requirements.txt

REM Generar configuración del frontend desde .env
echo 🔐 Generando configuración del frontend...
where node >nul 2>nul
if errorlevel 1 (
    if not exist "frontend\config.js" (
        echo ❌ Node.js no encontrado y frontend\config.js no existe.
        echo    Instala Node.js o copia frontend\config.example.js a frontend\config.js.
        exit /b 1
    )
    echo ⚠️  Node.js no encontrado. Usando frontend\config.js existente.
) else (
    node scripts\generate-config.cjs
    if errorlevel 1 (
        echo ❌ No se pudo generar frontend\config.js
        exit /b 1
    )
)

REM Iniciar servidor
echo.
echo 🌐 Iniciando servidor en http://localhost:8000
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

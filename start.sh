#!/bin/bash

# Script de inicio para desarrollo local

echo "🚀 Iniciando Explainer App (Desarrollo)"
echo "=========================================="

# Crear directorio de datos si no existe
mkdir -p data

# Verificar si existe .env
if [ ! -f .env ]; then
    echo "⚠️  Archivo .env no encontrado. Copiando .env.example..."
    cp .env.example .env
    echo "📝 Por favor, edita .env con tus configuraciones"
fi

# Activar entorno virtual si existe
if [ -d "venv" ]; then
    echo "📦 Activando entorno virtual..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "📦 Activando entorno virtual..."
    source .venv/bin/activate
fi

# Verificar dependencias
echo "📦 Verificando dependencias..."
pip install -q -r requirements.txt

# Iniciar servidor
echo ""
echo "🌐 Iniciando servidor en http://localhost:8000"
echo ""

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

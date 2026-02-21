#!/bin/bash
# Script de despliegue a Fly.io con configuración correcta para persistencia

set -e

echo "=== Despliegue Explainer API a Fly.io ==="
echo ""

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar que flyctl está instalado
if ! command -v flyctl &> /dev/null; then
    echo -e "${RED}Error: flyctl no está instalado${NC}"
    echo "Instálalo desde: https://fly.io/docs/hands-on/install-flyctl/"
    exit 1
fi

# Verificar login
if ! flyctl auth whoami &> /dev/null; then
    echo -e "${RED}Error: No has iniciado sesión en Fly.io${NC}"
    echo "Ejecuta: flyctl auth login"
    exit 1
fi

echo -e "${GREEN}✓ Autenticado en Fly.io${NC}"

# Verificar si la app existe
if ! flyctl apps list | grep -q "explainer-api-pablo"; then
    echo -e "${YELLOW}! La app explainer-api-pablo no existe. Creándola...${NC}"
    flyctl apps create explainer-api-pablo
fi

# Verificar si el volumen existe
echo ""
echo "=== Verificando volumen persistente ==="
if ! flyctl volumes list -a explainer-api-pablo | grep -q "data_vol"; then
    echo -e "${YELLOW}! El volumen 'data_vol' no existe. Creándolo...${NC}"
    echo "Creando volumen en región cdg (París)..."
    flyctl volumes create data_vol -a explainer-api-pablo -r cdg -s 3
    echo -e "${GREEN}✓ Volumen creado${NC}"
else
    echo -e "${GREEN}✓ Volumen data_vol ya existe${NC}"
fi

# Verificar y configurar secrets
echo ""
echo "=== Verificando secrets ==="

# Verificar JWT_SECRET
if ! flyctl secrets list -a explainer-api-pablo | grep -q "JWT_SECRET"; then
    echo -e "${YELLOW}! JWT_SECRET no configurado${NC}"
    JWT_SECRET=$(openssl rand -base64 32)
    echo "Configurando JWT_SECRET..."
    echo "$JWT_SECRET" | flyctl secrets set JWT_SECRET=-a explainer-api-pablo
    echo -e "${GREEN}✓ JWT_SECRET configurado${NC}"
else
    echo -e "${GREEN}✓ JWT_SECRET ya configurado${NC}"
fi

# Verificar APP_ENCRYPTION_KEY
if ! flyctl secrets list -a explainer-api-pablo | grep -q "APP_ENCRYPTION_KEY"; then
    echo -e "${YELLOW}! APP_ENCRYPTION_KEY no configurado${NC}"
    APP_KEY=$(openssl rand -base64 32)
    echo "Configurando APP_ENCRYPTION_KEY..."
    echo "$APP_KEY" | flyctl secrets set APP_ENCRYPTION_KEY=-a explainer-api-pablo
    echo -e "${GREEN}✓ APP_ENCRYPTION_KEY configurado${NC}"
else
    echo -e "${GREEN}✓ APP_ENCRYPTION_KEY ya configurado${NC}"
fi

# Verificar GEMINI_API_KEY (opcional)
if ! flyctl secrets list -a explainer-api-pablo | grep -q "GEMINI_API_KEY"; then
    echo -e "${YELLOW}! GEMINI_API_KEY no configurado (opcional, como fallback)${NC}"
    read -p "¿Quieres configurar una API key de Gemini como fallback? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Introduce tu GEMINI_API_KEY: " GEMINI_KEY
        echo "$GEMINI_KEY" | flyctl secrets set GEMINI_API_KEY=-a explainer-api-pablo
        echo -e "${GREEN}✓ GEMINI_API_KEY configurado${NC}"
    fi
else
    echo -e "${GREEN}✓ GEMINI_API_KEY ya configurado${NC}"
fi

# Desplegar
echo ""
echo "=== Desplegando aplicación ==="
flyctl deploy -a explainer-api-pablo

echo ""
echo -e "${GREEN}=== Despliegue completado ===${NC}"
echo ""
echo "URL de la API: https://explainer-api-pablo.fly.dev"
echo ""
echo "Comandos útiles:"
echo "  Ver logs:    flyctl logs -a explainer-api-pablo"
echo "  SSH a la app: flyctl ssh console -a explainer-api-pablo"
echo "  Ver DB:      flyctl ssh console -a explainer-api-pablo -C 'sqlite3 /app/data/explainer.db .tables'"
echo ""

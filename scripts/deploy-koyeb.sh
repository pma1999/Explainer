#!/bin/bash
# Script de despliegue a Koyeb con configuración para el plan Starter gratuito
# Koyeb: https://koyeb.com - Serverless platform with scale-to-zero

set -e

echo "=== Despliegue Explainer API a Koyeb ==="
echo ""

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Verificar que koyeb CLI está instalado
if ! command -v koyeb &> /dev/null; then
    echo -e "${RED}Error: Koyeb CLI no está instalado${NC}"
    echo ""
    echo "Instálalo con uno de estos métodos:"
    echo "  1. Con Homebrew:    brew install koyeb/tap/koyeb"
    echo "  2. Con curl:        curl -fsSL https://raw.githubusercontent.com/koyeb/koyeb-cli/master/install.sh | sh"
    echo ""
    echo "Más info: https://www.koyeb.com/docs/cli/installation"
    exit 1
fi

# Verificar login
if ! koyeb whoami &> /dev/null; then
    echo -e "${RED}Error: No has iniciado sesión en Koyeb${NC}"
    echo "Ejecuta: koyeb login"
    exit 1
fi

echo -e "${GREEN}✓ Autenticado en Koyeb${NC}"
echo ""

# Verificar que existe koyeb.yaml
if [ ! -f "koyeb.yaml" ]; then
    echo -e "${RED}Error: No se encontró koyeb.yaml en el directorio actual${NC}"
    echo "Asegúrate de estar en la raíz del proyecto"
    exit 1
fi

echo -e "${BLUE}=== Configuración ===${NC}"
echo "App name: explainer-api"
echo "Region: fra (Frankfurt)"
echo "Plan: Starter (Free tier with scale-to-zero)"
echo ""

# Verificar si el servicio ya existe
echo -e "${BLUE}=== Verificando servicio ===${NC}"
if koyeb service list | grep -q "explainer-api/explainer-api"; then
    echo -e "${GREEN}✓ El servicio ya existe${NC}"
    SERVICE_EXISTS=true
else
    echo -e "${YELLOW}! El servicio no existe. Se creará nuevo.${NC}"
    SERVICE_EXISTS=false
fi
echo ""

# Crear o actualizar el servicio
echo -e "${BLUE}=== Desplegando aplicación ===${NC}"
if [ "$SERVICE_EXISTS" = false ]; then
    echo "Creando nuevo servicio desde koyeb.yaml..."
    koyeb service create -f koyeb.yaml
else
    echo "Actualizando servicio existente..."
    koyeb service update explainer-api/explainer-api --git-branch main
fi

echo ""
echo -e "${GREEN}=== Despliegue completado ===${NC}"
echo ""
echo -e "${YELLOW}IMPORTANTE: Configura los secrets antes de usar la app!${NC}"
echo ""
echo "Configurar secrets:"
echo "  koyeb secret create APP_ENCRYPTION_KEY --value 'tu-clave-aqui'"
echo "  koyeb secret create SUPABASE_URL --value 'https://xxx.supabase.co'"
echo "  koyeb secret create SUPABASE_SERVICE_ROLE_KEY --value 'eyJ...'"
echo "  koyeb secret create SUPABASE_JWT_SECRET --value 'tu-jwt-secret'"
echo "  koyeb secret create FRONTEND_URL --value 'https://tu-frontend.vercel.app'"
echo ""
echo "Luego adjunta los secrets al servicio:"
echo "  koyeb service update explainer-api/explainer-api \\"
echo "    --secret APP_ENCRYPTION_KEY \\"
echo "    --secret SUPABASE_URL \\"
echo "    --secret SUPABASE_SERVICE_ROLE_KEY \\"
echo "    --secret SUPABASE_JWT_SECRET \\"
echo "    --secret FRONTEND_URL"
echo ""
echo "URL de la API estará disponible en:"
echo "  https://explainer-api-[org].koyeb.app"
echo ""
echo "Comandos útiles:"
echo "  Ver logs:      koyeb service logs explainer-api/explainer-api"
echo "  Ver status:    koyeb service get explainer-api/explainer-api"
echo "  Ver secrets:   koyeb secret list"
echo ""
echo -e "${YELLOW}Nota: La app usa scale-to-zero (gratis). Después de ~5 min de inactividad se detiene${NC}"
echo -e "${YELLOW}      y se reinicia automáticamente cuando llega una petición.${NC}"
echo ""

"""
Autenticación JWT con cookies httpOnly.

Seguridad:
- Contraseñas hasheadas con bcrypt
- JWT firmados con secret
- Cookies httpOnly (no accesibles por JS)
- Cookies SameSite=Strict (protección CSRF)
- Opción "remember me" con expiración configurable
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from email_validator import validate_email, EmailNotValidError


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

# Secrets - DEBEN estar en variables de entorno
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_secret_insecure_change_in_production")
JWT_ALGORITHM = "HS256"

# Tiempo de expiración
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 días por defecto
ACCESS_TOKEN_EXPIRE_MINUTES_SHORT = 60 * 8  # 8 horas (sin "recordar")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Cookie settings
COOKIE_NAME = "explainer_auth"
COOKIE_SECURE = os.environ.get("ENVIRONMENT", "development") == "production"  # True en prod
COOKIE_SAMESITE = "strict"
COOKIE_PATH = "/"


# ============================================================================
# FUNCIONES DE PASSWORD
# ============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash."""
    # Truncar a 72 bytes (límite de bcrypt)
    plain_password = plain_password.encode('utf-8')[:72].decode('utf-8', errors='ignore')
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Genera el hash de una contraseña."""
    # Truncar a 72 bytes (límite de bcrypt)
    password = password.encode('utf-8')[:72].decode('utf-8', errors='ignore')
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """
    Valida que la contraseña cumpla requisitos mínimos de seguridad.

    Retorna: (es_válida, mensaje_error)
    """
    if len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres"
    if not any(c.isupper() for c in password):
        return False, "La contraseña debe tener al menos una mayúscula"
    if not any(c.islower() for c in password):
        return False, "La contraseña debe tener al menos una minúscula"
    if not any(c.isdigit() for c in password):
        return False, "La contraseña debe tener al menos un número"
    return True, None


# ============================================================================
# FUNCIONES JWT
# ============================================================================

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un JWT token de acceso.

    Args:
        data: Datos a incluir en el token (user_id, email, etc.)
        expires_delta: Tiempo de expiración personalizado
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decodifica y valida un JWT token.

    Args:
        token: El JWT token

    Returns:
        Los claims del token si es válido, None si no lo es
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


# ============================================================================
# COOKIES
# ============================================================================

def set_auth_cookie(response: JSONResponse, token: str, remember: bool = False):
    """
    Establece la cookie de autenticación httpOnly.

    Args:
        response: La respuesta FastAPI
        token: El JWT token
        remember: Si True, la cookie dura 7 días, si no, 8 horas
    """
    max_age = None
    if remember:
        max_age = 60 * 60 * 24 * 7  # 7 días
    else:
        max_age = 60 * 60 * 8  # 8 horas

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,  # No accesible por JavaScript
        secure=COOKIE_SECURE,  # Solo HTTPS en producción
        samesite=COOKIE_SAMESITE,  # Protección CSRF
        path=COOKIE_PATH,
        max_age=max_age,
    )


def clear_auth_cookie(response: JSONResponse):
    """Elimina la cookie de autenticación."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
    )


def get_token_from_request(request: Request) -> Optional[str]:
    """
    Extrae el token JWT de la cookie de la request.

    Args:
        request: El objeto Request de FastAPI

    Returns:
        El token si existe, None si no
    """
    return request.cookies.get(COOKIE_NAME)


# ============================================================================
# VALIDACIÓN EMAIL
# ============================================================================

def validate_email_format(email: str) -> tuple[bool, Optional[str]]:
    """
    Valida el formato de un email.

    Retorna: (es_válido, mensaje_error)
    """
    try:
        validate_email(email)
        return True, None
    except EmailNotValidError as e:
        return False, str(e)


# ============================================================================
# DEPENDENCIAS FASTAPI
# ============================================================================

async def get_current_user(request: Request) -> Dict[str, Any]:
    """
    Dependencia de FastAPI que extrae y valida el usuario actual.

    Usar así:
        @app.get("/api/protected")
        async def protected_endpoint(user=Depends(get_current_user)):
            return {"user_id": user["user_id"]}

    Raises:
        HTTPException: 401 si no hay token o es inválido
    """
    token = get_token_from_request(request)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    email = payload.get("email")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": user_id,
        "email": email,
        "exp": payload.get("exp"),
    }


async def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    """
    Versión opcional de get_current_user que no lanza excepción.
    Útil para endpoints que pueden funcionar con o sin autenticación.
    """
    try:
        return await get_current_user(request)
    except HTTPException:
        return None

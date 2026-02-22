"""
Encriptación de API keys de Gemini (BYOK - Bring Your Own Key).

Soporta dos modos:
1. Modo legacy (global): API key única para toda la app (deprecated)
2. Modo BYOK (per-user): Cada usuario tiene su propia API key encriptada

La encriptación usa Fernet (AES-128-CBC + HMAC-SHA256) con claves derivadas
de APP_ENCRYPTION_KEY. En modo BYOK, cada usuario tiene clave de encriptación
única derivada de: SHA256(MASTER_KEY + user_id)
"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet


# Master key de la aplicación - DEBE estar en variable de entorno
MASTER_KEY = os.environ.get("APP_ENCRYPTION_KEY")
if not MASTER_KEY:
    # En desarrollo, generar una key temporal (advertencia en logs)
    import warnings
    warnings.warn(
        "APP_ENCRYPTION_KEY no configurada. Usando key temporal INSEGURA. "
        "Configura APP_ENCRYPTION_KEY en producción con: openssl rand -base64 32",
        RuntimeWarning
    )
    MASTER_KEY = "dev_key_insecure_do_not_use_in_production_32bytes!"


def mask_api_key(api_key: str) -> str:
    """
    Mascara una API key para mostrar en logs o UI (útil para debugging).

    Args:
        api_key: La API key en texto plano

    Returns:
        str: Versión enmascarada (ej: "AIza...XXXX")
    """
    if not api_key or len(api_key) < 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"


def _derive_app_key() -> bytes:
    """Deriva una clave única de aplicación para secretos globales."""
    app_key = hashlib.sha256(MASTER_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(app_key)


def encrypt_global_api_key(api_key: str) -> str:
    """Encripta la API key de Gemini (modo local)."""
    if not api_key:
        raise ValueError("api_key es requerida")

    f = Fernet(_derive_app_key())
    return f.encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_global_api_key(encrypted_key: str) -> str:
    """Desencripta la API key de Gemini (modo local)."""
    if not encrypted_key:
        raise ValueError("encrypted_key es requerida")

    f = Fernet(_derive_app_key())
    return f.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")


# ========== User-specific encryption (BYOK) ==========

def derive_user_key(user_id: str) -> bytes:
    """
    Deriva una clave de encriptación única para un usuario específico.

    La derivación usa SHA256(MASTER_KEY + user_id) lo que garantiza que:
    - Cada usuario tiene una clave de encriptación única
    - Incluso si dos usuarios tienen la misma API key, el texto encriptado será diferente
    - La clave no puede ser derivada sin conocer tanto MASTER_KEY como user_id

    Args:
        user_id: UUID del usuario (de auth.users)

    Returns:
        bytes: Clave derivada en formato URL-safe base64 (compatible con Fernet)
    """
    if not user_id:
        raise ValueError("user_id es requerido")

    # Derivar clave única combinando master key + user_id
    key_material = f"{MASTER_KEY}:{user_id}"
    derived_key = hashlib.sha256(key_material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(derived_key)


def encrypt_user_api_key(api_key: str, user_id: str) -> str:
    """
    Encripta una API key para un usuario específico (modo BYOK).

    Args:
        api_key: La API key en texto plano (ej: "AIza...")
        user_id: UUID del usuario propietario

    Returns:
        str: API key encriptada (token Fernet)

    Raises:
        ValueError: Si api_key o user_id son inválidos
    """
    if not api_key:
        raise ValueError("api_key es requerida")
    if not user_id:
        raise ValueError("user_id es requerido")

    f = Fernet(derive_user_key(user_id))
    return f.encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_user_api_key(encrypted_key: str, user_id: str) -> str:
    """
    Desencripta una API key de un usuario específico (modo BYOK).

    Args:
        encrypted_key: Token Fernet encriptado
        user_id: UUID del usuario propietario (debe ser el mismo que en encrypt_user_api_key)

    Returns:
        str: API key en texto plano

    Raises:
        ValueError: Si los parámetros son inválidos
        cryptography.fernet.InvalidToken: Si la clave es inválida o fue encriptada con otro user_id
    """
    if not encrypted_key:
        raise ValueError("encrypted_key es requerida")
    if not user_id:
        raise ValueError("user_id es requerido")

    f = Fernet(derive_user_key(user_id))
    return f.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")

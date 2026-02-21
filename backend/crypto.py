"""
Encriptación segura de API keys por usuario.

Cada API key se encripta con una clave única derivada del user_id + master key.
Esto garantiza:
- Aislamiento: usuario A no puede descifrar la key de usuario B
- Seguridad: incluso con acceso a la DB, sin MASTER_KEY no se pueden descifrar
- Flexibilidad: el user_id es necesario para descifrar (vinculado al JWT)
"""

import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


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


def _derive_user_key(user_id: str) -> bytes:
    """
    Deriva una clave única para cada usuario basada en su ID y el master key.

    Args:
        user_id: UUID del usuario (string)

    Returns:
        bytes: Clave de 32 bytes para Fernet
    """
    # Combinar MASTER_KEY + user_id para crear una clave única por usuario
    key_material = f"{MASTER_KEY}:{user_id}".encode('utf-8')

    # Usar SHA-256 para derivar una clave de 32 bytes
    # Esto es seguro porque el input (MASTER_KEY) es de alta entropía
    user_key = hashlib.sha256(key_material).digest()

    # Fernet requiere exactamente 32 bytes base64-urlsafe encoded
    return base64.urlsafe_b64encode(user_key)


def encrypt_api_key(user_id: str, api_key: str) -> str:
    """
    Encripta una API key de Gemini para un usuario específico.

    Args:
        user_id: UUID del usuario que posee la API key
        api_key: La API key de Gemini en texto plano

    Returns:
        str: API key encriptada (token Fernet)

    Raises:
        ValueError: Si user_id o api_key están vacíos
    """
    if not user_id or not api_key:
        raise ValueError("user_id y api_key son requeridos")

    user_key = _derive_user_key(user_id)
    f = Fernet(user_key)

    # Encriptar la API key
    encrypted = f.encrypt(api_key.encode('utf-8'))
    return encrypted.decode('utf-8')


def decrypt_api_key(user_id: str, encrypted_key: str) -> str:
    """
    Desencripta una API key de Gemini para un usuario específico.

    Args:
        user_id: UUID del usuario que posee la API key
        encrypted_key: La API key encriptada (token Fernet)

    Returns:
        str: API key en texto plano

    Raises:
        ValueError: Si user_id o encrypted_key están vacíos
        InvalidToken: Si la clave está corrupta o el user_id es incorrecto
    """
    if not user_id or not encrypted_key:
        raise ValueError("user_id y encrypted_key son requeridos")

    user_key = _derive_user_key(user_id)
    f = Fernet(user_key)

    # Desencriptar
    decrypted = f.decrypt(encrypted_key.encode('utf-8'))
    return decrypted.decode('utf-8')


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
    """Encripta la API key para modo sin usuarios."""
    if not api_key:
        raise ValueError("api_key es requerida")

    f = Fernet(_derive_app_key())
    return f.encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_global_api_key(encrypted_key: str) -> str:
    """Desencripta la API key para modo sin usuarios."""
    if not encrypted_key:
        raise ValueError("encrypted_key es requerida")

    f = Fernet(_derive_app_key())
    return f.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")

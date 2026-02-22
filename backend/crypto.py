"""
Encriptación de la API key de Gemini (modo local).

La API key se guarda encriptada con una clave derivada de APP_ENCRYPTION_KEY.
Solo se usa encrypt_global_api_key / decrypt_global_api_key (sin usuarios).
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

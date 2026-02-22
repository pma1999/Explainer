"""Herramienta de cálculo de costes y gestión de modelos para Gemini API."""
from __future__ import annotations
import os
from typing import Any

# Precios actualizados según la documentación proporcionada (por 1M de tokens en USD)
# Basado en Gemini 3.1 Pro Preview y Gemini 3 Flash Preview
PRICING = {
    "gemini-3.1-pro-preview": {
        "input_small": 2.00,  # <= 200k tokens
        "input_large": 4.00,  # > 200k tokens
        "cached_small": 0.20, # <= 200k tokens
        "cached_large": 0.40, # > 200k tokens
        "output_small": 12.00, # <= 200k tokens
        "output_large": 18.00, # > 200k tokens
        "storage": 4.50, # per 1M tokens per hour
    },
    "gemini-3-flash-preview": {
        "input_small": 0.50,
        "input_large": 0.50,
        "cached_small": 0.05,
        "cached_large": 0.05,
        "output_small": 3.00,
        "output_large": 3.00,
        "storage": 1.00,
    },
    # Valores por defecto para otros modelos
    "default": {
        "input_small": 0.50,
        "input_large": 0.50,
        "cached_small": 0.05,
        "cached_large": 0.05,
        "output_small": 3.00,
        "output_large": 3.00,
        "storage": 1.00,
    }
}

def get_model_name() -> str:
    """Obtiene el nombre del modelo configurado en .env o variables de entorno."""
    return os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

def calculate_cost(model_name: str, usage: Any) -> float:
    """
    Calcula el coste en USD basado en usage_metadata.
    
    usage puede ser un objeto de la SDK de Google GenAI o un dict.
    """
    if not usage:
        return 0.0
    
    # Extraer tokens (maneja tanto objetos como diccionarios)
    if hasattr(usage, 'prompt_token_count'):
        prompt_tokens = usage.prompt_token_count
        cached_tokens = getattr(usage, 'cached_content_token_count', 0)
        output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    else:
        prompt_tokens = usage.get('prompt_token_count', 0)
        cached_tokens = usage.get('cached_content_token_count', 0)
        output_tokens = usage.get('candidates_token_count', 0) + usage.get('thoughts_token_count', 0)
    
    # Restamos los tokens cacheados del total del prompt porque se facturan a diferente tarifa
    uncached_prompt_tokens = max(0, prompt_tokens - cached_tokens)
    
    is_large = prompt_tokens > 200000
    model_pricing = PRICING.get(model_name, PRICING["default"])
    
    input_rate = model_pricing["input_large"] if is_large else model_pricing["input_small"]
    cached_rate = model_pricing["cached_large"] if is_large else model_pricing["cached_small"]
    output_rate = model_pricing["output_large"] if is_large else model_pricing["output_small"]
    
    cost = ((uncached_prompt_tokens / 1000000) * input_rate + 
            (cached_tokens / 1000000) * cached_rate + 
            (output_tokens / 1000000) * output_rate)
    
    return round(cost, 6)

def calculate_storage_cost(model_name: str, token_count: int, duration_seconds: float) -> float:
    """
    Calcula el coste de almacenamiento del caché en base al tiempo que existió de forma prorrateada.
    """
    if not token_count or duration_seconds <= 0:
        return 0.0
    
    model_pricing = PRICING.get(model_name, PRICING["default"])
    storage_rate_per_hour = model_pricing.get("storage", 1.00)
    
    cost = (token_count / 1000000) * storage_rate_per_hour * (duration_seconds / 3600.0)
    
    return round(cost, 6)


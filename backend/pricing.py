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
        "output_small": 12.00, # <= 200k tokens
        "output_large": 18.00, # > 200k tokens
    },
    "gemini-3-flash-preview": {
        "input_small": 0.50,
        "input_large": 0.50,  # Flash suele tener precio plano o escalar distinto, según docs es 0.50
        "output_small": 3.00,
        "output_large": 3.00,
    },
    "gemini-3.1-flash-lite-preview": {
        "input_small": 0.25,   # $0.25 / 1M tokens (texto/imagen/vídeo)
        "input_large": 0.25,   # precio plano sin sobrecargo por prompt largo
        "output_small": 1.50,  # $1.50 / 1M tokens
        "output_large": 1.50,
    },
    # OpenRouter models
    "xiaomi/mimo-v2-flash": {
        "input_small": 0.09,   # $0.09 / 1M tokens
        "input_large": 0.09,
        "output_small": 0.29,  # $0.29 / 1M tokens
        "output_large": 0.29,
    },
    "xiaomi/mimo-v2.5-pro": {
        # Fallback only. For OpenRouter calls, prefer usage.cost from the API response.
        "input_small": 1.00,   # $1.00 / 1M tokens
        "input_large": 1.00,
        "output_small": 3.00,  # $3.00 / 1M tokens
        "output_large": 3.00,
    },
    "xiaomi/mimo-v2.5": {
        # Fallback only. For OpenRouter calls, prefer usage.cost from the API response.
        "input_small": 0.40,   # $0.40 / 1M tokens
        "input_large": 0.40,
        "output_small": 2.00,  # $2.00 / 1M tokens
        "output_large": 2.00,
    },
    "minimax/minimax-m2.7": {
        "input_small": 0.30,   # $0.30 / 1M tokens
        "input_large": 0.30,
        "output_small": 1.20,  # $1.20 / 1M tokens
        "output_large": 1.20,
    },
    "qwen/qwen3.6-plus": {
        # From provided pricing screenshot (USD per 1M tokens):
        # Input:  <=256K $0.325, >256K $1.30
        # Output: <=256K $1.95,  >256K $3.90
        "input_small": 0.325,
        "input_large": 1.30,
        "output_small": 1.95,
        "output_large": 3.90,
    },
    "deepseek/deepseek-v4-flash": {
        # Fallback only. For OpenRouter calls, prefer usage.cost from the API response.
        "input_small": 0.14,
        "input_large": 0.14,
        "output_small": 0.28,
        "output_large": 0.28,
    },
    "deepseek/deepseek-v4-pro": {
        # Fallback only. For OpenRouter calls, prefer usage.cost from the API response.
        "input_small": 0.50,
        "input_large": 0.50,
        "output_small": 1.50,
        "output_large": 1.50,
    },
    # Valores por defecto para otros modelos
    "default": {
        "input_small": 0.50,
        "input_large": 0.50,
        "output_small": 3.00,
        "output_large": 3.00,
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
        prompt_tokens = usage.prompt_token_count or 0
        tool_use_prompt_tokens = getattr(usage, 'tool_use_prompt_token_count', 0) or 0
        # Incluimos candidates y thoughts en el output
        output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    else:
        prompt_tokens = usage.get('prompt_token_count', 0)
        tool_use_prompt_tokens = usage.get('tool_use_prompt_token_count', 0)
        output_tokens = usage.get('candidates_token_count', 0) + usage.get('thoughts_token_count', 0)

    total_input_tokens = prompt_tokens + tool_use_prompt_tokens
    
    # Determinar tier de precios
    # El tier depende de si el PROMPT es > 200k
    is_large = total_input_tokens > 200000
    
    model_pricing = PRICING.get(model_name, PRICING["default"])
    
    input_rate = model_pricing["input_large"] if is_large else model_pricing["input_small"]
    output_rate = model_pricing["output_large"] if is_large else model_pricing["output_small"]
    
    cost = (total_input_tokens / 1000000) * input_rate + (output_tokens / 1000000) * output_rate
    
    return round(cost, 6)

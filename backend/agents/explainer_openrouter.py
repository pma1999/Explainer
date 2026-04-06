"""Agente Explainer — implementación OpenRouter con JSON mode."""
from __future__ import annotations

import base64
import time
from typing import Any

from backend.logging_config import get_logger
from backend.openrouter_client import OpenRouterError, OpenRouterUsage, call_openrouter_chat
from backend.agents.language_policy import CASTELLANO_ESPANIA_XML

logger = get_logger("backend.agents.explainer_openrouter")

OPENROUTER_MODEL_AGENTS = "xiaomi/mimo-v2-flash"

# PDF parsing plugin (cloudflare-ai es gratis y funciona con cualquier modelo)
_PDF_PLUGIN = [{"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}}]

# ---------------------------------------------------------------------------
# System prompts para JSON mode
# ---------------------------------------------------------------------------

OR_EXPLAINER_SYSTEM_PROMPT = (
"""<system_instruction>
  <role>
  Eres un **Experto Didáctico de Alto Rendimiento**, especializado en transformar contenido técnico o académico en explicaciones exhaustivas que garanticen comprensión completa.

  **Tu expertise específica:**
  - Pedagogía avanzada y teoría del aprendizaje significativo
  - Estructuración óptima de contenido para retención y comprensión
  - Capacidad para detectar y explicar conexiones implícitas entre conceptos
  - Dominio en la expansión explicativa de material denso

  **Principios metodológicos que guían tu trabajo:**
  1. **Expansión obligatoria**: Tu función es AMPLIAR, nunca condensar. Cada concepto del texto principal merece desarrollo explicativo.
  2. **Cobertura total**: No existe concepto menor. Todo elemento del texto principal debe ser explicado hasta que sea plenamente comprensible.
  3. **Pedagogía activa**: Los ejemplos, analogías y reformulaciones no son opcionales; son herramientas necesarias para asentar el conocimiento.
  4. **Rigor terminológico**: Los términos técnicos deben preservarse exactamente, pero siempre acompañados de explicación accesible.
  5. **Fidelidad absoluta al contenido fuente**: TODA información sustantiva debe derivarse exclusivamente del texto principal y los textos complementarios. Puedes explicar, reformular, crear ejemplos ilustrativos y analogías para clarificar, pero NUNCA añadir datos, hechos, normas, fechas, cifras o contenido conceptual que no esté presente en los materiales proporcionados.
  6. **Responsabilidad académica**: El usuario puede suspender un examen si omites cualquier elemento. Cada tema, subtema, matiz, excepción, requisito o detalle es potencialmente preguntable y OBLIGATORIO de desarrollar.
  </role>
"""
+ CASTELLANO_ESPANIA_XML
+ """

  <output_contract>
  Devuelve EXCLUSIVAMENTE un único objeto JSON válido. No escribas nada antes ni después del objeto. No uses bloques ```json.

  La forma exacta del objeto es:
  {
    "introduccion": "string",
    "desarrollo": [
      {
        "titulo_seccion": "string",
        "explicacion_introductoria": "string",
        "subsecciones": [
          {
            "titulo_subseccion": "string",
            "explicacion_detallada": "string"
          }
        ]
      }
    ],
    "conclusion": "string",
    "conexiones_contextuales": [
      {
        "seccion_temario_relacionada": "string",
        "descripcion_conexion": "string"
      }
    ]
  }

  Reglas JSON obligatorias:
  - Todas esas claves deben existir SIEMPRE.
  - `conexiones_contextuales` debe ser `[]` cuando no aplique.
  - No añadas claves extra.
  - Cada valor debe respetar exactamente su tipo.
  - Escapa correctamente comillas, saltos de línea y caracteres especiales para que el JSON sea parseable.
  - `titulo_seccion` y `titulo_subseccion` son títulos breves; no los repitas dentro del cuerpo.
  - `introduccion` y `conclusion` contienen solo sus párrafos; no incluyas los rótulos literales "Introducción" o "Conclusión".
  - `explicacion_introductoria` y `explicacion_detallada` contienen solo el cuerpo explicativo de ese bloque, sin encabezados duplicados ni metacomentarios.
  - Tu límite de tokens existe para ser USADO, no para ser ahorrado. Sé exhaustivo.
  </output_contract>

  <coverage_guarantee_protocol>
  **CRÍTICO:** Si algo aparece en el texto principal, DEBE aparecer desarrollado en tu explicación. "Desarrollado" significa explicado hasta que el usuario pueda responder una pregunta de examen sobre ese elemento, NO solo mencionado.
  </coverage_guarantee_protocol>

  <source_fidelity_protocol>
  Toda información sustantiva debe provenir de los textos proporcionados. Puedes reformular, crear ejemplos ilustrativos y analogías, pero NO añadir datos externos no mencionados.
  </source_fidelity_protocol>
</system_instruction>

<context>
{{TEXTO_PRINCIPAL}}
[El contenido que debe ser explicado exhaustivamente.]

{{TEXTOS_COMPLEMENTARIOS}} (opcional)
[Leyes, sentencias, artículos o material de apoyo.]

{{TABLA_DE_CONTENIDOS}} (opcional)
[Posición del texto principal en el temario. Usar solo para Conexiones Contextuales.]

{{INSTRUCCIÓN_DEL_USUARIO}} (opcional)
[Si el usuario especifica que solo quiere explicación de una parte concreta.]
</context>

<task>
Basándote en el contexto proporcionado, genera una explicación exhaustiva del texto principal que garantice comprensión completa. Si no hay instrucción específica, explica TODO el contenido. Mantén profundidad uniforme desde el primer hasta el último concepto y devuelve únicamente el objeto JSON descrito.
</task>"""
)

OR_SUBPART_EXPLAINER_SYSTEM_PROMPT = (
"""<system_instruction>
  <role>
  Eres un **Experto Didáctico de Alto Rendimiento**, especializado en transformar contenido técnico o académico en explicaciones exhaustivas que garanticen comprensión completa.

  **Principios metodológicos:**
  1. **Expansión obligatoria**: Tu función es AMPLIAR, nunca condensar.
  2. **Cobertura total**: Todo elemento del texto asignado debe ser explicado exhaustivamente.
  3. **Pedagogía activa**: Ejemplos, analogías y reformulaciones son herramientas necesarias.
  4. **Fidelidad absoluta**: TODA información sustantiva debe derivarse exclusivamente de los textos proporcionados.
  5. **Responsabilidad académica**: Cada tema, subtema, matiz o detalle es potencialmente preguntable y OBLIGATORIO de desarrollar.
  </role>
"""
+ CASTELLANO_ESPANIA_XML
+ """

  <output_contract>
  Devuelve EXCLUSIVAMENTE un único objeto JSON válido. No escribas nada antes ni después del objeto.

  La forma exacta del objeto es:
  {
    "desarrollo": [
      {
        "titulo_seccion": "string",
        "explicacion_introductoria": "string",
        "subsecciones": [
          {
            "titulo_subseccion": "string",
            "explicacion_detallada": "string"
          }
        ]
      }
    ]
  }

  Reglas JSON obligatorias:
  - Devuelve SOLO la clave `desarrollo`.
  - No añadas introducción, conclusión ni conexiones contextuales.
  - No añadas claves extra.
  - Cada `titulo_*` debe ser breve y no repetirse dentro del cuerpo.
  - Cada `explicacion_*` contiene solo el cuerpo explicativo, sin encabezados duplicados ni metacomentarios.
  - Escapa correctamente comillas, saltos de línea y caracteres especiales para que el JSON sea parseable.
  - Tu límite de tokens existe para ser USADO. Sé exhaustivo.
  </output_contract>

  <coverage_guarantee_protocol>
  **CRÍTICO:** Si algo aparece en el texto de esta subparte, DEBE aparecer desarrollado exhaustivamente. No solo mencionado.
  </coverage_guarantee_protocol>

  <source_fidelity_protocol>
  Toda información sustantiva debe provenir de los textos proporcionados. Puedes reformular y crear ejemplos ilustrativos, pero NO añadir datos externos.
  </source_fidelity_protocol>
</system_instruction>

<context>
{{TEXTO_PRINCIPAL}}
[El contenido que debe ser explicado exhaustivamente. TODO su contenido debe ser cubierto.]

{{TEXTOS_COMPLEMENTARIOS}} (opcional)
[Material de apoyo.]
</context>

<task>
Basándote en el contexto proporcionado, genera el desarrollo exhaustivo de la subparte asignada. Mantén profundidad uniforme desde el primer hasta el último concepto. Sin introducción ni conclusión. Devuelve únicamente el objeto JSON descrito.
</task>"""
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_object(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OpenRouterError(f"Campo inválido en {path}: se esperaba un objeto JSON.")
    return value


def _require_string(value: Any, *, path: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise OpenRouterError(f"Campo inválido en {path}: se esperaba una cadena.")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise OpenRouterError(f"Campo inválido en {path}: la cadena no puede estar vacía.")
    return normalized


def _validate_subsections(raw: Any, *, path: str) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise OpenRouterError(f"Campo inválido en {path}: se esperaba una lista no vacía.")
    validated: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        subsection = _require_object(item, path=f"{path}[{index}]")
        validated.append(
            {
                "titulo_subseccion": _require_string(
                    subsection.get("titulo_subseccion"),
                    path=f"{path}[{index}].titulo_subseccion",
                ),
                "explicacion_detallada": _require_string(
                    subsection.get("explicacion_detallada"),
                    path=f"{path}[{index}].explicacion_detallada",
                ),
            }
        )
    return validated


def _validate_desarrollo(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise OpenRouterError("Campo inválido en desarrollo: se esperaba una lista no vacía.")
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        section = _require_object(item, path=f"desarrollo[{index}]")
        validated.append(
            {
                "titulo_seccion": _require_string(
                    section.get("titulo_seccion"),
                    path=f"desarrollo[{index}].titulo_seccion",
                ),
                "explicacion_introductoria": _require_string(
                    section.get("explicacion_introductoria"),
                    path=f"desarrollo[{index}].explicacion_introductoria",
                ),
                "subsecciones": _validate_subsections(
                    section.get("subsecciones"),
                    path=f"desarrollo[{index}].subsecciones",
                ),
            }
        )
    return validated


def _validate_conexiones(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OpenRouterError(
            "Campo inválido en conexiones_contextuales: se esperaba una lista o []."
        )
    validated: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        connection = _require_object(item, path=f"conexiones_contextuales[{index}]")
        validated.append(
            {
                "seccion_temario_relacionada": _require_string(
                    connection.get("seccion_temario_relacionada"),
                    path=f"conexiones_contextuales[{index}].seccion_temario_relacionada",
                ),
                "descripcion_conexion": _require_string(
                    connection.get("descripcion_conexion"),
                    path=f"conexiones_contextuales[{index}].descripcion_conexion",
                ),
            }
        )
    return validated


def _validate_full_explainer_payload(payload: Any) -> dict[str, Any]:
    data = _require_object(payload, path="root")
    return {
        "introduccion": _require_string(data.get("introduccion"), path="introduccion"),
        "desarrollo": _validate_desarrollo(data.get("desarrollo")),
        "conclusion": _require_string(data.get("conclusion"), path="conclusion"),
        "conexiones_contextuales": _validate_conexiones(data.get("conexiones_contextuales")),
    }


def _validate_subpart_explainer_payload(payload: Any) -> dict[str, Any]:
    data = _require_object(payload, path="root")
    return {"desarrollo": _validate_desarrollo(data.get("desarrollo"))}


def _count_desarrollo_subsections(desarrollo: list[dict[str, Any]]) -> int:
    return sum(len(section.get("subsecciones") or []) for section in desarrollo)


def _count_payload_chars(payload: dict[str, Any]) -> int:
    total = 0
    for key in ("introduccion", "conclusion"):
        value = payload.get(key)
        if isinstance(value, str):
            total += len(value)

    for section in payload.get("desarrollo") or []:
        total += len(section.get("titulo_seccion", ""))
        total += len(section.get("explicacion_introductoria", ""))
        for subsection in section.get("subsecciones") or []:
            total += len(subsection.get("titulo_subseccion", ""))
            total += len(subsection.get("explicacion_detallada", ""))

    for connection in payload.get("conexiones_contextuales") or []:
        total += len(connection.get("seccion_temario_relacionada", ""))
        total += len(connection.get("descripcion_conexion", ""))

    return total

def _build_content(source_path: str, identificacion: str, mime_type: str) -> tuple[list[dict], list[dict] | None]:
    """
    Construye el array de content y la lista de plugins para OpenRouter.

    - PDF: base64 + file-parser plugin
    - Texto/web: texto inline
    """
    if mime_type == "application/pdf":
        with open(source_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        content = [
            {"type": "text", "text": identificacion},
            {
                "type": "file",
                "file": {
                    "filename": "document.pdf",
                    "file_data": f"data:application/pdf;base64,{b64}",
                },
            },
        ]
        return content, _PDF_PLUGIN

    # Texto plano (web/texto)
    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
        text_content = f.read()

    content = [{"type": "text", "text": f"{text_content}\n\n{identificacion}"}]
    return content, None


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def run_explainer_or(
    source_path: str,
    identificacion: str,
    model: str = OPENROUTER_MODEL_AGENTS,
    mime_type: str = "application/pdf",
    api_key: str = "",
) -> tuple[dict[str, Any], OpenRouterUsage]:
    """Explainer completo vía OpenRouter. Retorna (structured_result, usage)."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer (openrouter)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
        },
    )

    content, plugins = _build_content(source_path, identificacion, mime_type)
    messages = [{"role": "user", "content": content}]

    raw, usage = call_openrouter_chat(
        messages=messages,
        model=model,
        system_prompt=OR_EXPLAINER_SYSTEM_PROMPT,
        api_key=api_key,
        response_format="json_object",
        plugins=plugins,
        enable_response_healing=True,
        reasoning={"effort": "xhigh", "exclude": True},
    )

    result = _validate_full_explainer_payload(raw)
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Explainer (openrouter) completado: %s secciones, %s subsecciones, %s chars en %sms",
        len(desarrollo),
        total_subsections,
        total_chars,
        total_ms,
        extra={
            "num_sections": len(desarrollo),
            "num_subsections": total_subsections,
            "content_length": total_chars,
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
        },
    )

    return result, usage


def run_subpart_explainer_or(
    source_path: str,
    identificacion: str,
    model: str = OPENROUTER_MODEL_AGENTS,
    mime_type: str = "application/pdf",
    api_key: str = "",
) -> tuple[dict[str, Any], OpenRouterUsage]:
    """Explainer de subparte vía OpenRouter — retorna solo `desarrollo` estructurado."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer subparte (openrouter)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
        },
    )

    content, plugins = _build_content(source_path, identificacion, mime_type)
    messages = [{"role": "user", "content": content}]

    raw, usage = call_openrouter_chat(
        messages=messages,
        model=model,
        system_prompt=OR_SUBPART_EXPLAINER_SYSTEM_PROMPT,
        api_key=api_key,
        response_format="json_object",
        plugins=plugins,
        enable_response_healing=True,
        reasoning={"effort": "xhigh", "exclude": True},
    )

    result = _validate_subpart_explainer_payload(raw)
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Subpart explainer (openrouter) completado: %s secciones, %s subsecciones, %s chars en %sms",
        len(desarrollo),
        total_subsections,
        total_chars,
        total_ms,
        extra={
            "num_sections": len(desarrollo),
            "num_subsections": total_subsections,
            "content_length": total_chars,
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
        },
    )

    return result, usage

"""Shared target-language policy for model-generated study content."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LanguageContext = Literal["segmentador", "explainer", "recorrido", "resources", "formatter", "generic"]


@dataclass(frozen=True)
class TargetLanguage:
    """Canonical description of an output language selected by the user."""

    code: str
    label: str
    instruction_name: str
    variant_note: str = ""
    forbidden_note: str = ""


TARGET_LANGUAGES: dict[str, TargetLanguage] = {
    "es-ES": TargetLanguage(
        code="es-ES",
        label="Castellano de España",
        instruction_name="castellano de España / español de España",
        variant_note=(
            "Usa español peninsular culto: léxico y construcciones propias de España "
            "(p. ej. «ordenador», «móvil», «coche», «portátil»)."
        ),
        forbidden_note=(
            "Prohibido escribir en español hispanoamericano o latinoamericano: nada de voseo "
            "ni usos como «computadora», «celular», «carro», «platicar», etc., salvo que aparezcan "
            "literalmente en una cita del texto fuente."
        ),
    ),
    "en": TargetLanguage(code="en", label="English", instruction_name="English"),
    "fr": TargetLanguage(code="fr", label="Français", instruction_name="French"),
    "de": TargetLanguage(code="de", label="Deutsch", instruction_name="German"),
    "it": TargetLanguage(code="it", label="Italiano", instruction_name="Italian"),
    "pt-PT": TargetLanguage(
        code="pt-PT",
        label="Português de Portugal",
        instruction_name="European Portuguese / português de Portugal",
        variant_note="Use European Portuguese, not Brazilian Portuguese.",
    ),
}

_LANGUAGE_ALIASES = {
    "es": "es-ES",
    "es-es": "es-ES",
    "castellano": "es-ES",
    "español": "es-ES",
    "espanol": "es-ES",
    "spanish": "es-ES",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",
    "fr-fr": "fr",
    "french": "fr",
    "de-de": "de",
    "german": "de",
    "it-it": "it",
    "italian": "it",
    "pt": "pt-PT",
    "pt-pt": "pt-PT",
    "portuguese": "pt-PT",
}


def normalize_target_language(value: str | TargetLanguage | None = None) -> TargetLanguage:
    """Return a supported target language, defaulting to Spain Spanish."""

    if isinstance(value, TargetLanguage):
        return value
    if value is None or not str(value).strip():
        return TARGET_LANGUAGES["es-ES"]
    raw = str(value).strip()
    if raw in TARGET_LANGUAGES:
        return TARGET_LANGUAGES[raw]
    alias = _LANGUAGE_ALIASES.get(raw.casefold())
    if alias and alias in TARGET_LANGUAGES:
        return TARGET_LANGUAGES[alias]
    supported = ", ".join(lang.code for lang in TARGET_LANGUAGES.values())
    raise ValueError(f"Idioma objetivo no soportado: {raw}. Idiomas soportados: {supported}.")


def _language_header(target_language: str | TargetLanguage | None) -> tuple[TargetLanguage, str]:
    target = normalize_target_language(target_language)
    heading = f"Idioma objetivo elegido por el usuario: {target.label} ({target.code})."
    return target, heading


def build_language_policy_xml(
    target_language: str | TargetLanguage | None = None,
    *,
    context: LanguageContext = "generic",
) -> str:
    """Build an XML-style system-prompt block for the selected output language."""

    target, heading = _language_header(target_language)
    generated_fields = "todo el contenido que redactes tú"
    extra_lines: list[str] = []

    if context == "segmentador":
        generated_fields = "títulos, descripciones, identificaciones, delimitaciones y toda metainformación que redactes tú"
    elif context == "explainer":
        generated_fields = "introducciones, secciones, explicaciones, ejemplos, analogías, conclusiones y conexiones contextuales"
    elif context == "recorrido":
        generated_fields = "traducciones, apuntes traductológicos, anotaciones, síntesis y observaciones que redactes tú"
        extra_lines.append(
            "- Las citas textuales (`cita_textual`) se conservan SIEMPRE literales, exactas y en el idioma original del texto fuente; no las traduzcas dentro del campo de cita."
        )
        extra_lines.append(
            f"- El campo `traduccion` debe estar en {target.instruction_name}; si la cita ya está en el idioma objetivo, indica de forma natural que el original ya está en el idioma objetivo o deja vacío solo si el esquema lo exige para evitar duplicidad."
        )
    elif context == "resources":
        generated_fields = "título del mapa, visión general, nombres de ejes, conexiones, notas de accesibilidad, notas de integridad y cualquier explicación propia"
        extra_lines.append(
            "- Selecciona los mejores recursos disponibles en cualquier idioma. No filtres, rebajes ni penalices un recurso por no estar en el idioma objetivo; importa su calidad, rigor y pertinencia."
        )
        extra_lines.append(
            "- Los títulos oficiales, autores, nombres de instituciones y datos bibliográficos permanecen en su idioma original o en la forma académica/editorial establecida."
        )
    elif context == "formatter":
        generated_fields = "el Markdown formateado y cualquier ajuste lingüístico imprescindible"

    lines = [
        "  <idioma_salida>",
        f"  **{heading}**",
        f"  - Redacta {generated_fields} en {target.instruction_name}.",
        "  - Preserva sin traducir citas literales del texto fuente, nombres propios, títulos oficiales, artículos normativos, nomenclatura y términos técnicos cuando el rigor o el uso establecido lo exijan.",
    ]
    if target.variant_note:
        lines.append(f"  - {target.variant_note}")
    if target.forbidden_note:
        lines.append(f"  - {target.forbidden_note}")
    lines.extend(f"  {line}" for line in extra_lines)
    lines.append("  </idioma_salida>")
    return "\n".join(lines) + "\n"


def build_formatter_language_rule(target_language: str | TargetLanguage | None = None) -> str:
    """Return the formatter-specific final rule for the selected language."""

    target = normalize_target_language(target_language)
    base = (
        f"\n5. El texto de entrada ya está redactado en {target.instruction_name}; al aplicar Markdown "
        "no cambies el idioma objetivo, no introduzcas traducciones nuevas y no alteres el registro. "
        "Solo formato y correcciones mínimas de artefactos lingüísticos evidentes, sin acortar ni cambiar significado."
    )
    if target.code == "es-ES":
        base += (
            " Mantén castellano de España / español de España: no introduzcas sinonimia latinoamericana "
            "ni normalices a español hispanoamericano."
        )
    return base


# Backwards-compatible default constants used by older imports/tests. New code should
# call the builder functions with the request's target language.
CASTELLANO_ESPANIA_XML = build_language_policy_xml("es-ES", context="generic")
CASTELLANO_ESPANIA_RESOURCES_XML = build_language_policy_xml("es-ES", context="resources")
CASTELLANO_RECORRIDO_REFUERZO_XML = build_language_policy_xml("es-ES", context="recorrido")
FORMATTER_CASTELLANO_RULE = build_formatter_language_rule("es-ES")

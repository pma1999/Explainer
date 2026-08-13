package com.explainer.app.ui.content

import com.explainer.app.core.model.ContextualConnection
import com.explainer.app.core.model.ExplainSection
import com.explainer.app.core.model.ReaderTab

/**
 * Modelo de presentación de un tab del lector (T08), derivado por
 * [PartContentParser] del `JsonObject` crudo de T02.
 *
 * Los ocho estados de las variantes cubren el contenido renderizable y los
 * tres estados de no-render: ausencia ([Missing], estado válido), error del
 * agente ([AgentError]) y contenido presente pero con shape no usable
 * ([Malformed]). Ningún estado deja pantalla en blanco; todos los estados
 * fallback son accesibles.
 */
sealed interface PartRenderModel {

    /** Explicación renderizable: estructurada (con markdown por campo) o markdown puro. */
    data class Explanation(val content: ExplanationModel) : PartRenderModel

    /** Recorrido anotado con su síntesis de cobertura opcional. */
    data class Walkthrough(
        val entries: List<WalkthroughEntry>,
        val sintesis: CoberturaSintesis?,
    ) : PartRenderModel

    /** Mapa de recursos con ejes temáticos. */
    data class Resources(
        val titulo: String?,
        val visionGeneral: String?,
        val ejes: List<ResourceAxis>,
        val notaIntegridad: String?,
    ) : PartRenderModel

    /** Esquema Mermaid listo para render local (sin ejecutar nada en la app). */
    data class Diagram(
        val code: String,
        val analysis: String?,
        val readingGuide: String?,
        val synthesisDecisions: String?,
    ) : PartRenderModel

    /** Repaso activo con preguntas y respuesta oculta hasta revelarla. */
    data class Review(
        val preguntas: List<ReviewQuestion>,
        val nota: String?,
    ) : PartRenderModel

    /** Contenido ausente del agente (estado válido, no corrupción). */
    data class Missing(val tab: ReaderTab) : PartRenderModel

    /** Error declarado por el agente (`{"error": ...}`). */
    data class AgentError(val tab: ReaderTab, val message: String) : PartRenderModel

    /** Presente pero con shape no usable (p. ej. código vacío, sin preguntas). */
    data class Malformed(val tab: ReaderTab, val message: String) : PartRenderModel
}

/** Forma renderizable de la explicación (paridad `projectView.js renderExplainer`). */
sealed interface ExplanationModel {
    /** `{_format:"markdown", content}` → renderer Markdown nativo. */
    data class Markdown(val content: String) : ExplanationModel

    /** JSON estructurado; los campos de texto admiten markdown inline. */
    data class Structured(
        val introduccion: String?,
        val desarrollo: List<ExplainSection>,
        val conclusion: String?,
        val conexionesContextuales: List<ContextualConnection>,
    ) : ExplanationModel
}

/** Entrada de `recorrido.recorrido_anotado[]`. */
data class WalkthroughEntry(
    val ubicacion: String?,
    val tipoEntrada: String?,
    val citaTextual: String?,
    val traduccion: String?,
    val apuntesTraductologicos: String?,
    val anotacion: String?,
)

/** `recorrido.sintesis_de_cobertura`. */
data class CoberturaSintesis(
    val seccionesProcesadas: String?,
    val alcance: String?,
    val contenidoExcluido: String?,
    val idiomaOriginal: String?,
    val observacionesGlobales: String?,
)

/** Eje temático de `resources.ejes_tematicos[]`. */
data class ResourceAxis(
    val nombreEje: String?,
    val recursos: List<ResourceItem>,
)

/** Recurso individual; la `url` se conserva cruda y solo se abre si la aprueba
 * [SafeExternalUrlPolicy] (http/https). */
data class ResourceItem(
    val formato: String?,
    val titulo: String?,
    val autorCreador: String?,
    val tipoYDatos: String?,
    val conexionConTexto: String?,
    val nivelYAccesibilidad: String?,
    val idioma: String?,
    val nota: String?,
    val url: String?,
)

/** Pregunta de `review.preguntas[]`; la respuesta se revela bajo demanda. */
data class ReviewQuestion(
    val numero: Int?,
    val pregunta: String?,
    val respuestaRazonada: String?,
    val referencia: String?,
)

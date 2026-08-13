package com.explainer.app.core.model

import kotlinx.serialization.json.JsonObject

/**
 * Explicación de una parte en sus dos formas wire (paridad con
 * projectView.js renderExplainer): JSON estructurado, `{_format:"markdown",
 * content}` o error de agente `{error}`.
 */
sealed interface ExplainerDocument {
    data class Structured(
        val introduccion: String?,
        val desarrollo: List<ExplainSection>,
        val conclusion: String?,
        val conexionesContextuales: List<ContextualConnection>,
    ) : ExplainerDocument

    data class Markdown(val content: String) : ExplainerDocument

    data class Error(val message: String) : ExplainerDocument
}

data class ExplainSection(
    val tituloSeccion: String,
    val explicacionIntroductoria: String?,
    val subsecciones: List<ExplainSubsection>,
)

data class ExplainSubsection(
    val tituloSubseccion: String,
    val explicacionDetallada: String?,
)

data class ContextualConnection(
    val seccionTemarioRelacionada: String,
    val descripcionConexion: String?,
)

/**
 * Esquema visual Mermaid. `Ok` lleva el código canónico `mermaid_code`
 * (alias `code` como fallback de lectura, resuelto por
 * `PartContentContract`); `AgentError` es el estado de generación fallida
 * `{"error": ...}`. La ausencia de `mermaid` se representa como `null` en
 * [PartContentDocument.mermaid]: `Missing` (null) y `AgentError` son estados
 * distintos y ambos válidos.
 */
sealed interface MermaidDocument {
    data class Ok(
        val code: String,
        val analysis: String? = null,
        val readingGuide: String? = null,
        val synthesisDecisions: String? = null,
    ) : MermaidDocument

    data class AgentError(val message: String) : MermaidDocument
}

/**
 * Vista de dominio de una entrada de `partes_contenido[part_id]`.
 *
 * Contrato compartido de `plan.md` L266: `val raw: JsonObject` es la fuente
 * de verdad completa (campos de agentes, `formatter_version`,
 * `formatter_usage` y cualquier campo futuro). `status`, `explainer`,
 * `recorrido`, `resources`, `review` y `mermaid` son vistas derivadas que
 * resuelve el mapper; un consumidor que necesite un estado sin vista tipada
 * (o campos futuros) lee `raw` directamente. `review`/`mermaid` ausentes o
 * con `error` son estados válidos.
 */
data class PartContentDocument(
    val raw: JsonObject,
    val partId: Int,
    val status: PartStatus = PartStatus.Pending,
    val explainer: ExplainerDocument? = null,
    val recorrido: JsonObject? = null,
    val resources: JsonObject? = null,
    val review: JsonObject? = null,
    val mermaid: MermaidDocument? = null,
)

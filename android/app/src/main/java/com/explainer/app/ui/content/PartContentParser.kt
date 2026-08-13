package com.explainer.app.ui.content

import com.explainer.app.core.model.ContextualConnection
import com.explainer.app.core.model.ExplainerDocument
import com.explainer.app.core.model.MermaidDocument
import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.data.remote.contract.PartContentContract
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Parser de presentación (T08): transforma el `JsonObject` de T02
 * (`PartContentDocument.raw`, fuente de verdad completa) en [PartRenderModel]
 * por tab, sin perder los estados ausente/error y degradando el contenido
 * malformado a [PartRenderModel.Malformed].
 *
 * Reglas:
 * - Ausencia (`null`) → [PartRenderModel.Missing]: estado válido.
 * - `{"error": ...}` → [PartRenderModel.AgentError].
 * - Presente pero con shape no usable (no-objeto, vacío, código en blanco,
 *   sin preguntas) → [PartRenderModel.Malformed]. Nada de esto ejecuta
 *   HTML/JS ni deja pantalla en blanco.
 * - `review` con explainer en error hereda ese error (paridad web
 *   `projectView.js _renderReviewTab`).
 */
object PartContentParser {

    fun parse(document: PartContentDocument): ParsedPartContent {
        val raw = document.raw
        return ParsedPartContent(
            explanation = explanation(raw),
            walkthrough = walkthrough(raw),
            resources = resources(raw),
            diagram = diagram(raw),
            review = review(raw),
        )
    }

    // ── explainer ──

    private fun explanation(raw: JsonObject): PartRenderModel {
        val tab = ReaderTab.EXPLANATION
        if (raw.containsKey(KEY_EXPLAINER) && raw[KEY_EXPLAINER] !is JsonObject) {
            return PartRenderModel.Malformed(tab, "explicación con forma inesperada")
        }
        return when (val doc = PartContentContract.explainer(raw)) {
            null -> PartRenderModel.Missing(tab)
            is ExplainerDocument.Error -> PartRenderModel.AgentError(tab, doc.message)
            is ExplainerDocument.Markdown ->
                if (doc.content.isBlank()) PartRenderModel.Malformed(tab, "explicación vacía")
                else PartRenderModel.Explanation(ExplanationModel.Markdown(doc.content))

            is ExplainerDocument.Structured -> {
                val empty = doc.introduccion == null &&
                    doc.desarrollo.isEmpty() &&
                    doc.conclusion == null &&
                    doc.conexionesContextuales.isEmpty()
                if (empty) {
                    PartRenderModel.Malformed(tab, "explicación vacía")
                } else {
                    PartRenderModel.Explanation(
                        ExplanationModel.Structured(
                            introduccion = doc.introduccion,
                            desarrollo = doc.desarrollo,
                            conclusion = doc.conclusion,
                            conexionesContextuales = doc.conexionesContextuales,
                        ),
                    )
                }
            }
        }
    }

    // ── recorrido ──

    private fun walkthrough(raw: JsonObject): PartRenderModel {
        val tab = ReaderTab.WALKTHROUGH
        if (raw.containsKey(KEY_RECORRIDO) && raw[KEY_RECORRIDO] !is JsonObject) {
            return PartRenderModel.Malformed(tab, "recorrido con forma inesperada")
        }
        val recorrido = PartContentContract.recorrido(raw)
        if (recorrido == null) {
            return PartRenderModel.Missing(tab)
        }
        PartContentContract.agentError(raw, KEY_RECORRIDO)?.let {
            return PartRenderModel.AgentError(tab, it)
        }
        val entries = recorrido.arrOrNull(KEY_RECORRIDO_ANOTADO).orEmpty()
            .mapNotNull { it as? JsonObject }
            .map { entry ->
                WalkthroughEntry(
                    ubicacion = entry.stringOrNull(KEY_UBICACION),
                    tipoEntrada = entry.stringOrNull(KEY_TIPO_ENTRADA),
                    citaTextual = entry.stringOrNull(KEY_CITA_TEXTUAL),
                    traduccion = entry.stringOrNull(KEY_TRADUCCION),
                    apuntesTraductologicos = entry.stringOrNull(KEY_APUNTES_TRADUCTOLOGICOS),
                    anotacion = entry.stringOrNull(KEY_ANOTACION),
                )
            }
        val sintesis = recorrido.objOrNull(KEY_SINTESIS_DE_COBERTURA)?.let { s ->
            CoberturaSintesis(
                seccionesProcesadas = s.stringOrNull(KEY_SECCIONES_PROCESADAS),
                alcance = s.stringOrNull(KEY_ALCANCE),
                contenidoExcluido = s.stringOrNull(KEY_CONTENIDO_EXCLUIDO),
                idiomaOriginal = s.stringOrNull(KEY_IDIOMA_ORIGINAL),
                observacionesGlobales = s.stringOrNull(KEY_OBSERVACIONES_GLOBALES),
            )
        }
        return if (entries.isEmpty() && sintesis == null) {
            PartRenderModel.Malformed(tab, "recorrido sin contenido")
        } else {
            PartRenderModel.Walkthrough(entries = entries, sintesis = sintesis)
        }
    }

    // ── resources ──

    private fun resources(raw: JsonObject): PartRenderModel {
        val tab = ReaderTab.RESOURCES
        if (raw.containsKey(KEY_RESOURCES) && raw[KEY_RESOURCES] !is JsonObject) {
            return PartRenderModel.Malformed(tab, "recursos con forma inesperada")
        }
        val resources = PartContentContract.resources(raw)
        if (resources == null) {
            return PartRenderModel.Missing(tab)
        }
        PartContentContract.agentError(raw, KEY_RESOURCES)?.let {
            return PartRenderModel.AgentError(tab, it)
        }
        val ejes = resources.arrOrNull(KEY_EJES_TEMATICOS).orEmpty()
            .mapNotNull { it as? JsonObject }
            .map { eje ->
                ResourceAxis(
                    nombreEje = eje.stringOrNull(KEY_NOMBRE_EJE),
                    recursos = eje.arrOrNull(KEY_RECURSOS).orEmpty()
                        .mapNotNull { it as? JsonObject }
                        .map { r ->
                            ResourceItem(
                                formato = r.stringOrNull(KEY_FORMATO),
                                titulo = r.stringOrNull(KEY_TITULO),
                                autorCreador = r.stringOrNull(KEY_AUTOR_CREADOR),
                                tipoYDatos = r.stringOrNull(KEY_TIPO_Y_DATOS),
                                conexionConTexto = r.stringOrNull(KEY_CONEXION_CON_TEXTO),
                                nivelYAccesibilidad = r.stringOrNull(KEY_NIVEL_Y_ACCESIBILIDAD),
                                idioma = r.stringOrNull(KEY_IDIOMA),
                                nota = r.stringOrNull(KEY_NOTA),
                                url = r.stringOrNull(KEY_URL),
                            )
                        },
                )
            }
        val model = PartRenderModel.Resources(
            titulo = resources.stringOrNull(KEY_TITULO_MAPA),
            visionGeneral = resources.stringOrNull(KEY_VISION_GENERAL),
            ejes = ejes,
            notaIntegridad = resources.stringOrNull(KEY_NOTA_DE_INTEGRIDAD),
        )
        val empty = model.titulo == null &&
            model.visionGeneral == null &&
            model.ejes.isEmpty() &&
            model.notaIntegridad == null
        return if (empty) PartRenderModel.Malformed(tab, "recursos sin contenido") else model
    }

    // ── mermaid ──

    private fun diagram(raw: JsonObject): PartRenderModel {
        val tab = ReaderTab.DIAGRAM
        if (raw.containsKey(KEY_MERMAID) && raw[KEY_MERMAID] !is JsonObject) {
            return PartRenderModel.Malformed(tab, "esquema con forma inesperada")
        }
        val mermaid = PartContentContract.mermaid(raw)
        if (mermaid == null) {
            // Objeto presente pero sin código (`{}`) es malformado; ausencia es Missing.
            return if (raw.containsKey(KEY_MERMAID)) {
                PartRenderModel.Malformed(tab, "esquema sin código")
            } else {
                PartRenderModel.Missing(tab)
            }
        }
        return when (mermaid) {
            is MermaidDocument.AgentError -> PartRenderModel.AgentError(tab, mermaid.message)
            is MermaidDocument.Ok ->
                if (mermaid.code.isBlank()) {
                    PartRenderModel.Malformed(tab, "esquema sin código")
                } else {
                    PartRenderModel.Diagram(
                        code = mermaid.code,
                        analysis = mermaid.analysis,
                        readingGuide = mermaid.readingGuide,
                        synthesisDecisions = mermaid.synthesisDecisions,
                    )
                }
        }
    }

    // ── review ──

    private fun review(raw: JsonObject): PartRenderModel {
        val tab = ReaderTab.REVIEW
        if (raw.containsKey(KEY_REVIEW) && raw[KEY_REVIEW] !is JsonObject) {
            return PartRenderModel.Malformed(tab, "repaso con forma inesperada")
        }
        // Paridad web (_renderReviewTab): el error del explainer gana sobre la
        // ausencia/error de review, porque el repaso depende del pipeline.
        val explainer = PartContentContract.explainer(raw)
        if (explainer is ExplainerDocument.Error) {
            return PartRenderModel.AgentError(tab, explainer.message)
        }
        val review = PartContentContract.review(raw)
        if (review == null) {
            return PartRenderModel.Missing(tab)
        }
        PartContentContract.agentError(raw, KEY_REVIEW)?.let {
            return PartRenderModel.AgentError(tab, it)
        }
        val preguntas = review.arrOrNull(KEY_PREGUNTAS).orEmpty()
            .mapNotNull { it as? JsonObject }
            .map { q ->
                ReviewQuestion(
                    numero = q.intOrNull(KEY_NUMERO),
                    pregunta = q.stringOrNull(KEY_PREGUNTA),
                    respuestaRazonada = q.stringOrNull(KEY_RESPUESTA_RAZONADA),
                    referencia = q.stringOrNull(KEY_REFERENCIA),
                )
            }
        return if (preguntas.isEmpty()) {
            PartRenderModel.Malformed(tab, "repaso sin preguntas")
        } else {
            PartRenderModel.Review(preguntas = preguntas, nota = review.stringOrNull(KEY_NOTA))
        }
    }

    // ── accesos seguros (un valor no-string/no-int se omite, no crashea) ──

    private fun JsonObject.stringOrNull(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun JsonObject.intOrNull(key: String): Int? =
        (this[key] as? JsonPrimitive)?.let { runCatching { it.content.toInt() }.getOrNull() }

    private fun JsonObject.objOrNull(key: String): JsonObject? = this[key] as? JsonObject

    private fun JsonObject.arrOrNull(key: String): kotlinx.serialization.json.JsonArray? =
        this[key] as? kotlinx.serialization.json.JsonArray

    private const val KEY_EXPLAINER = "explainer"
    private const val KEY_RECORRIDO = "recorrido"
    private const val KEY_RESOURCES = "resources"
    private const val KEY_REVIEW = "review"
    private const val KEY_MERMAID = "mermaid"

    private const val KEY_RECORRIDO_ANOTADO = "recorrido_anotado"
    private const val KEY_UBICACION = "ubicacion"
    private const val KEY_TIPO_ENTRADA = "tipo_entrada"
    private const val KEY_CITA_TEXTUAL = "cita_textual"
    private const val KEY_TRADUCCION = "traduccion"
    private const val KEY_APUNTES_TRADUCTOLOGICOS = "apuntes_traductologicos"
    private const val KEY_ANOTACION = "anotacion"
    private const val KEY_SINTESIS_DE_COBERTURA = "sintesis_de_cobertura"
    private const val KEY_SECCIONES_PROCESADAS = "secciones_procesadas"
    private const val KEY_ALCANCE = "alcance"
    private const val KEY_CONTENIDO_EXCLUIDO = "contenido_excluido"
    private const val KEY_IDIOMA_ORIGINAL = "idioma_original"
    private const val KEY_OBSERVACIONES_GLOBALES = "observaciones_globales"

    private const val KEY_TITULO_MAPA = "titulo_mapa"
    private const val KEY_VISION_GENERAL = "vision_general"
    private const val KEY_EJES_TEMATICOS = "ejes_tematicos"
    private const val KEY_NOMBRE_EJE = "nombre_eje"
    private const val KEY_RECURSOS = "recursos"
    private const val KEY_FORMATO = "formato"
    private const val KEY_TITULO = "titulo"
    private const val KEY_AUTOR_CREADOR = "autor_creador"
    private const val KEY_TIPO_Y_DATOS = "tipo_y_datos"
    private const val KEY_CONEXION_CON_TEXTO = "conexion_con_texto"
    private const val KEY_NIVEL_Y_ACCESIBILIDAD = "nivel_y_accesibilidad"
    private const val KEY_IDIOMA = "idioma"
    private const val KEY_NOTA = "nota"
    private const val KEY_URL = "url"
    private const val KEY_NOTA_DE_INTEGRIDAD = "nota_de_integridad"

    private const val KEY_PREGUNTAS = "preguntas"
    private const val KEY_NUMERO = "numero"
    private const val KEY_PREGUNTA = "pregunta"
    private const val KEY_RESPUESTA_RAZONADA = "respuesta_razonada"
    private const val KEY_REFERENCIA = "referencia"
}

/** Resultado del parse de los cinco tabs del lector. */
data class ParsedPartContent(
    val explanation: PartRenderModel,
    val walkthrough: PartRenderModel,
    val resources: PartRenderModel,
    val diagram: PartRenderModel,
    val review: PartRenderModel,
) {
    /** Modelo del tab canónico (orden web: explicacion, recorrido, recursos, esquema, repaso). */
    fun forTab(tab: ReaderTab): PartRenderModel = when (tab) {
        ReaderTab.EXPLANATION -> explanation
        ReaderTab.WALKTHROUGH -> walkthrough
        ReaderTab.RESOURCES -> resources
        ReaderTab.DIAGRAM -> diagram
        ReaderTab.REVIEW -> review
    }
}

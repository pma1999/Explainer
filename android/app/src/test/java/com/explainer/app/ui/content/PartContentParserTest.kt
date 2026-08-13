package com.explainer.app.ui.content

import com.explainer.app.core.model.ContextualConnection
import com.explainer.app.core.model.MermaidDocument
import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.PartStatus
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.data.remote.contract.PartContentContract
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Aceptación del parser de presentación (T08): transforma el `JsonObject` de
 * T02 en [PartRenderModel] por tab sin perder los estados ausente/error y
 * degradando el contenido malformado a [PartRenderModel.Malformed] (nunca
 * pantalla en blanco). Los fixtures se construyen como raw JSON y pasan por
 * `PartContentContract` igual que el mapper de T02.
 */
class PartContentParserTest {

    // ── helpers ──

    private fun document(rawJson: String): PartContentDocument {
        val raw = Json.parseToJsonElement(rawJson) as JsonObject
        return PartContentDocument(
            raw = raw,
            partId = 1,
            status = PartStatus.Completed,
            explainer = PartContentContract.explainer(raw),
            recorrido = PartContentContract.recorrido(raw),
            resources = PartContentContract.resources(raw),
            review = PartContentContract.review(raw),
            mermaid = PartContentContract.mermaid(raw),
        )
    }

    private fun parse(rawJson: String): ParsedPartContent = PartContentParser.parse(document(rawJson))

    // ── explainer estructurado ──

    @Test
    fun `explicacion estructurada completa produce Explanation Structured`() {
        val model = parse(
            """
            {
              "explainer": {
                "introduccion": "Intro **con markdown**",
                "desarrollo": [
                  {
                    "titulo_seccion": "Sección 1",
                    "explicacion_introductoria": "Intro de la sección",
                    "subsecciones": [
                      { "titulo_subseccion": "Sub 1", "explicacion_detallada": "Detalle 1" },
                      { "titulo_subseccion": "Sub 2", "explicacion_detallada": null }
                    ]
                  }
                ],
                "conclusion": "Conclusión",
                "conexiones_contextuales": [
                  { "seccion_temario_relacionada": "Tema A", "descripcion_conexion": "Conexión" }
                ]
              }
            }
            """.trimIndent(),
        ).explanation as PartRenderModel.Explanation

        val structured = model.content as ExplanationModel.Structured
        assertEquals("Intro **con markdown**", structured.introduccion)
        assertEquals(1, structured.desarrollo.size)
        assertEquals("Sección 1", structured.desarrollo[0].tituloSeccion)
        assertEquals(2, structured.desarrollo[0].subsecciones.size)
        assertNull(structured.desarrollo[0].subsecciones[1].explicacionDetallada)
        assertEquals("Conclusión", structured.conclusion)
        assertEquals(
            listOf(ContextualConnection("Tema A", "Conexión")),
            structured.conexionesContextuales,
        )
    }

    @Test
    fun `explicacion markdown produce Explanation Markdown`() {
        val model = parse(
            """{"explainer": {"_format": "markdown", "content": "# Título\n\nTexto."}}""",
        ).explanation as PartRenderModel.Explanation
        assertEquals(ExplanationModel.Markdown("# Título\n\nTexto."), model.content)
    }

    @Test
    fun `explicacion con error de agente produce AgentError`() {
        val model = parse(
            """{"explainer": {"error": "El agente de explicación falló"}}""",
        ).explanation
        assertEquals(PartRenderModel.AgentError(ReaderTab.EXPLANATION, "El agente de explicación falló"), model)
    }

    @Test
    fun `explicacion ausente produce Missing`() {
        val model = parse("""{"status": "processing"}""").explanation
        assertEquals(PartRenderModel.Missing(ReaderTab.EXPLANATION), model)
    }

    @Test
    fun `explicacion con shape inesperado produce Malformed`() {
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.EXPLANATION, "explicación con forma inesperada"),
            parse("""{"explainer": "texto plano"}""").explanation,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.EXPLANATION, "explicación vacía"),
            parse("""{"explainer": {"introduccion": null, "desarrollo": [], "conclusion": null}}""").explanation,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.EXPLANATION, "explicación vacía"),
            parse("""{"explainer": {"_format": "markdown", "content": "   "}}""").explanation,
        )
    }

    // ── recorrido ──

    @Test
    fun `recorrido completo produce Walkthrough con entradas y sintesis`() {
        val model = parse(
            """
            {
              "recorrido": {
                "recorrido_anotado": [
                  {
                    "ubicacion": "Línea 3",
                    "tipo_entrada": "cita_anotada",
                    "cita_textual": "Cita…",
                    "traduccion": "Traducción",
                    "apuntes_traductologicos": "Apuntes",
                    "anotacion": "Anotación"
                  },
                  { "ubicacion": "Línea 9" },
                  "entrada-no-objeto"
                ],
                "sintesis_de_cobertura": {
                  "secciones_procesadas": "1-4",
                  "alcance": "Todo",
                  "contenido_excluido": "Nada",
                  "idioma_original": "griego",
                  "observaciones_globales": "Obs"
                }
              }
            }
            """.trimIndent(),
        ).walkthrough as PartRenderModel.Walkthrough

        assertEquals(2, model.entries.size)
        val first = model.entries[0]
        assertEquals("Línea 3", first.ubicacion)
        assertEquals("cita_anotada", first.tipoEntrada)
        assertEquals("Cita…", first.citaTextual)
        assertEquals("Traducción", first.traduccion)
        assertEquals("Apuntes", first.apuntesTraductologicos)
        assertEquals("Anotación", first.anotacion)
        assertNull(model.entries[1].tipoEntrada)
        val s = checkNotNull(model.sintesis)
        assertEquals("1-4", s.seccionesProcesadas)
        assertEquals("Todo", s.alcance)
        assertEquals("Nada", s.contenidoExcluido)
        assertEquals("griego", s.idiomaOriginal)
        assertEquals("Obs", s.observacionesGlobales)
    }

    @Test
    fun `recorrido ausente produce Missing`() {
        assertEquals(PartRenderModel.Missing(ReaderTab.WALKTHROUGH), parse("""{}""").walkthrough)
    }

    @Test
    fun `recorrido con error produce AgentError`() {
        assertEquals(
            PartRenderModel.AgentError(ReaderTab.WALKTHROUGH, "fallo del recorrido"),
            parse("""{"recorrido": {"error": "fallo del recorrido"}}""").walkthrough,
        )
    }

    @Test
    fun `recorrido malformado produce Malformed`() {
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.WALKTHROUGH, "recorrido con forma inesperada"),
            parse("""{"recorrido": [1, 2]}""").walkthrough,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.WALKTHROUGH, "recorrido sin contenido"),
            parse("""{"recorrido": {"recorrido_anotado": [], "sintesis_de_cobertura": null}}""").walkthrough,
        )
    }

    // ── resources ──

    @Test
    fun `resources completo produce Resources con ejes y URLs crudas`() {
        val model = parse(
            """
            {
              "resources": {
                "titulo_mapa": "Mapa",
                "vision_general": "Visión general",
                "ejes_tematicos": [
                  {
                    "nombre_eje": "Fuentes",
                    "recursos": [
                      {
                        "formato": "pdf",
                        "titulo": "Texto",
                        "autor_creador": "Autor",
                        "tipo_y_datos": "edición",
                        "conexion_con_texto": "Conexión",
                        "nivel_y_accesibilidad": "básico",
                        "idioma": "es",
                        "nota": "Ojo",
                        "url": "https://example.com/archivo.pdf"
                      },
                      { "titulo": "Sin URL", "url": "javascript:alert(1)" }
                    ]
                  }
                ],
                "nota_de_integridad": "Nota"
              }
            }
            """.trimIndent(),
        ).resources as PartRenderModel.Resources

        assertEquals("Mapa", model.titulo)
        assertEquals("Visión general", model.visionGeneral)
        assertEquals("Nota", model.notaIntegridad)
        assertEquals(1, model.ejes.size)
        assertEquals("Fuentes", model.ejes[0].nombreEje)
        val item = model.ejes[0].recursos[0]
        assertEquals("Texto", item.titulo)
        assertEquals("Autor", item.autorCreador)
        assertEquals("edición", item.tipoYDatos)
        assertEquals("https://example.com/archivo.pdf", item.url)
        // La URL peligrosa se conserva cruda en el modelo; la política la filtra en UI.
        assertEquals("javascript:alert(1)", model.ejes[0].recursos[1].url)
    }

    @Test
    fun `resources ausente produce Missing`() {
        assertEquals(PartRenderModel.Missing(ReaderTab.RESOURCES), parse("""{}""").resources)
    }

    @Test
    fun `resources con error produce AgentError`() {
        assertEquals(
            PartRenderModel.AgentError(ReaderTab.RESOURCES, "fallo de resources"),
            parse("""{"resources": {"error": "fallo de resources"}}""").resources,
        )
    }

    @Test
    fun `resources malformado produce Malformed`() {
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.RESOURCES, "recursos con forma inesperada"),
            parse("""{"resources": true}""").resources,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.RESOURCES, "recursos sin contenido"),
            parse("""{"resources": {}}""").resources,
        )
    }

    // ── mermaid ──

    @Test
    fun `mermaid Ok produce Diagram con metadata`() {
        val model = parse(
            """
            {
              "mermaid": {
                "mermaid_code": "graph TD\n  A --> B",
                "analysis": "Análisis",
                "reading_guide": "Guía",
                "synthesis_decisions": "Decisiones"
              }
            }
            """.trimIndent(),
        ).diagram as PartRenderModel.Diagram

        assertEquals("graph TD\n  A --> B", model.code)
        assertEquals("Análisis", model.analysis)
        assertEquals("Guía", model.readingGuide)
        assertEquals("Decisiones", model.synthesisDecisions)
    }

    @Test
    fun `mermaid con alias code produce Diagram`() {
        val model = parse(
            """{"mermaid": {"code": "graph LR\n  X --> Y"}}""",
        ).diagram as PartRenderModel.Diagram
        assertEquals("graph LR\n  X --> Y", model.code)
    }

    @Test
    fun `mermaid ausente produce Missing`() {
        assertEquals(PartRenderModel.Missing(ReaderTab.DIAGRAM), parse("""{}""").diagram)
    }

    @Test
    fun `mermaid con error de agente produce AgentError distinguible de ausencia`() {
        assertEquals(
            PartRenderModel.AgentError(ReaderTab.DIAGRAM, "El agente de mermaid falló"),
            parse("""{"mermaid": {"error": "El agente de mermaid falló"}}""").diagram,
        )
        // Missing (ausencia) y AgentError son estados distintos.
        assertEquals(PartRenderModel.Missing(ReaderTab.DIAGRAM), parse("""{}""").diagram)
    }

    @Test
    fun `mermaid malformado produce Malformed`() {
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.DIAGRAM, "esquema con forma inesperada"),
            parse("""{"mermaid": "graph TD"}""").diagram,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.DIAGRAM, "esquema sin código"),
            parse("""{"mermaid": {}}""").diagram,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.DIAGRAM, "esquema sin código"),
            parse("""{"mermaid": {"mermaid_code": "  \n "}}""").diagram,
        )
    }

    // ── review ──

    @Test
    fun `review completo produce Review con preguntas y nota`() {
        val model = parse(
            """
            {
              "review": {
                "preguntas": [
                  {
                    "numero": 1,
                    "pregunta": "¿Qué es X?",
                    "respuesta_razonada": "X es…",
                    "referencia": "§2.3"
                  },
                  { "pregunta": "Sin número" }
                ],
                "nota": "Nota de estudio"
              }
            }
            """.trimIndent(),
        ).review as PartRenderModel.Review

        assertEquals(2, model.preguntas.size)
        assertEquals(1, model.preguntas[0].numero)
        assertEquals("¿Qué es X?", model.preguntas[0].pregunta)
        assertEquals("X es…", model.preguntas[0].respuestaRazonada)
        assertEquals("§2.3", model.preguntas[0].referencia)
        assertNull(model.preguntas[1].numero)
        assertEquals("Nota de estudio", model.nota)
    }

    @Test
    fun `review ausente produce Missing`() {
        assertEquals(PartRenderModel.Missing(ReaderTab.REVIEW), parse("""{}""").review)
    }

    @Test
    fun `review con error produce AgentError`() {
        assertEquals(
            PartRenderModel.AgentError(ReaderTab.REVIEW, "fallo del repaso"),
            parse("""{"review": {"error": "fallo del repaso"}}""").review,
        )
    }

    @Test
    fun `review hereda el error de explainer cuando falta review - paridad web`() {
        // projectView.js _renderReviewTab: `contenido.explainer?.error` gana
        // sobre la ausencia de review.
        val model = parse(
            """{"explainer": {"error": "pipeline roto"}, "review": {"error": "fallo propio"}}""",
        ).review
        assertEquals(PartRenderModel.AgentError(ReaderTab.REVIEW, "pipeline roto"), model)
    }

    @Test
    fun `review malformado produce Malformed`() {
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.REVIEW, "repaso con forma inesperada"),
            parse("""{"review": "texto"}""").review,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.REVIEW, "repaso sin preguntas"),
            parse("""{"review": {"preguntas": []}}""").review,
        )
        assertEquals(
            PartRenderModel.Malformed(ReaderTab.REVIEW, "repaso sin preguntas"),
            parse("""{"review": {"preguntas": ["no-objeto"], "nota": "solo nota"}}""").review,
        )
    }

    // ── ParsedPartContent.forTab ──

    @Test
    fun `forTab devuelve el modelo de cada tab canonica`() {
        val parsed = parse(
            """
            {
              "explainer": {"_format": "markdown", "content": "md"},
              "recorrido": {"recorrido_anotado": [{"ubicacion": "L1"}]},
              "resources": {"titulo_mapa": "Mapa"},
              "mermaid": {"mermaid_code": "graph TD; A-->B"},
              "review": {"preguntas": [{"pregunta": "P"}]}
            }
            """.trimIndent(),
        )
        assertTrue(parsed.forTab(ReaderTab.EXPLANATION) is PartRenderModel.Explanation)
        assertTrue(parsed.forTab(ReaderTab.WALKTHROUGH) is PartRenderModel.Walkthrough)
        assertTrue(parsed.forTab(ReaderTab.RESOURCES) is PartRenderModel.Resources)
        assertTrue(parsed.forTab(ReaderTab.DIAGRAM) is PartRenderModel.Diagram)
        assertTrue(parsed.forTab(ReaderTab.REVIEW) is PartRenderModel.Review)
    }

    @Test
    fun `parse conserva raw del documento para estados no tipados`() {
        // MermaidDocument.AgentError (T02) se preserva como estado tipado.
        val raw = Json.parseToJsonElement(
            """{"mermaid": {"error": "fallo"}}""",
        ) as JsonObject
        val mermaid = PartContentContract.mermaid(raw)
        assertTrue(mermaid is MermaidDocument.AgentError)
        assertEquals(
            PartRenderModel.AgentError(ReaderTab.DIAGRAM, "fallo"),
            PartContentParser.parse(document("""{"mermaid": {"error": "fallo"}}""")).diagram,
        )
    }
}

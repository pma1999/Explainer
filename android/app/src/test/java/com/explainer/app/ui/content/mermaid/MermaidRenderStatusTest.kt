package com.explainer.app.ui.content.mermaid

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Estado visible del render (remediación R-T08-01): un resultado `null`
 * (timeout de página, timeout de polling, WebView ausente o excepción de
 * evaluación) es un fallo visible — nunca un éxito — para auto-revelar el
 * código fuente y mostrar un estado accesible.
 */
class MermaidRenderStatusTest {

    @Test
    fun `resultado nulo o ausente es UNAVAILABLE (timeout o pagina no lista)`() {
        val result: MermaidRenderResult? = null
        assertEquals(MermaidRenderStatus.UNAVAILABLE, result.renderStatus())
    }

    @Test
    fun `resultado ok es RENDERED`() {
        val result = MermaidRenderResult(ok = true, svg = "<svg/>", renderId = "r1")
        assertEquals(MermaidRenderStatus.RENDERED, result.renderStatus())
    }

    @Test
    fun `resultado con ok false es FAILED`() {
        val result = MermaidRenderResult(ok = false, error = "parse error", renderId = "r1")
        assertEquals(MermaidRenderStatus.FAILED, result.renderStatus())
    }

    @Test
    fun `solo RENDERED cuenta como exito para la UI`() {
        val statuses = listOf<MermaidRenderResult?>(
            null,
            MermaidRenderResult(ok = false, error = "e", renderId = "r1"),
        ).map { it.renderStatus() }
        assertEquals(
            listOf(MermaidRenderStatus.UNAVAILABLE, MermaidRenderStatus.FAILED),
            statuses,
        )
    }

    @Test
    fun `la webview notifica fallo visible cuando la pagina no llega o la evaluacion falla`() {
        val source = mainSource("mermaid/HardenedMermaidWebView.kt").readText()
        val notifyCount = Regex("onRenderFinished\\?\\.invoke\\(null\\)").findAll(source).count()
        assertTrue(
            "debe notificar fallo en timeout de página y en excepción de evaluación (visto $notifyCount)",
            notifyCount >= 2,
        )
        assertTrue(
            "el polling debe correlacionar el resultado por renderId",
            source.contains("MermaidResultCorrelation.matches"),
        )
    }

    @Test
    fun `la UI marca fallo visible y auto-revela el codigo para cualquier resultado distinto de RENDERED`() {
        val source = mainSource("mermaid/MermaidContent.kt").readText()
        assertTrue(
            "el estado debe derivarse del clasificador del resultado",
            source.contains("renderStatus = result.renderStatus()"),
        )
        assertTrue(
            "debe mostrar un estado accesible al fallar",
            source.contains("content_diagram_render_failed"),
        )
        assertTrue(
            "debe auto-revelar el código cuando falla",
            source.contains("if (renderFailed) codeExpanded = true"),
        )
    }

    private fun mainSource(relative: String): File =
        listOf(
            File(System.getProperty("user.dir") ?: "", "src/main/java/com/explainer/app/ui/content"),
            File("src/main/java/com/explainer/app/ui/content"),
            File("app/src/main/java/com/explainer/app/ui/content"),
        ).firstOrNull { it.isDirectory }
            ?.resolve(relative)
            ?: error("fuente ui/content no encontrada")
}

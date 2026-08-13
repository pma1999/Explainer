package com.explainer.app.ui.content.mermaid

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Correlación de resultados por renderId (remediación R-T08-04): un
 * resultado obsoleto de un render anterior (cambio rápido de código/tema
 * mientras el anterior sigue pendiente) nunca satisface el polling del render
 * nuevo; el wrapper local limpia el slot al iniciar cada render.
 */
class MermaidResultCorrelationTest {

    @Test
    fun `resultado del render esperado coincide por renderId`() {
        val result = MermaidRenderResult(ok = true, svg = "<svg/>", renderId = "mermaid-render-1")
        assertTrue(MermaidResultCorrelation.matches(result, "mermaid-render-1"))
    }

    @Test
    fun `resultado de un render anterior no satisface el polling nuevo`() {
        val stale = MermaidRenderResult(ok = true, svg = "<svg-old/>", renderId = "mermaid-render-0")
        assertFalse(MermaidResultCorrelation.matches(stale, "mermaid-render-1"))
    }

    @Test
    fun `sin resultado o sin renderId no coincide`() {
        assertFalse(MermaidResultCorrelation.matches(null, "mermaid-render-1"))
        val noId = MermaidRenderResult(ok = true, svg = "<svg/>")
        assertFalse(MermaidResultCorrelation.matches(noId, "mermaid-render-1"))
    }

    @Test
    fun `un fallo del render esperado si coincide por renderId`() {
        val failed = MermaidRenderResult(ok = false, error = "parse error", renderId = "mermaid-render-1")
        assertTrue(MermaidResultCorrelation.matches(failed, "mermaid-render-1"))
    }

    @Test
    fun `decodeResult preserva el renderId`() {
        val decoded = MermaidRequestCodec.decodeResult(
            """{"ok":true,"svg":"<svg></svg>","renderId":"mermaid-render-7"}""",
        )
        assertEquals(
            MermaidRenderResult(ok = true, svg = "<svg></svg>", renderId = "mermaid-render-7"),
            decoded,
        )
    }

    @Test
    fun `el wrapper incluye renderId en los resultados y descarta el anterior`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        // Ambas ramas (ok y error) devuelven el renderId del request.
        val occurrences = Regex("renderId: renderId").findAll(wrapper).count()
        assertTrue(
            "las ramas ok/error deben incluir renderId (visto $occurrences)",
            occurrences >= 2,
        )
        // El render nuevo limpia el slot del resultado anterior.
        assertTrue(wrapper.contains("pendingResult = null"))
    }
}

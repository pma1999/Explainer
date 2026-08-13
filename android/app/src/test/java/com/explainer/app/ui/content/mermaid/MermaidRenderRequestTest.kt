package com.explainer.app.ui.content.mermaid

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Contrato de serialización del render request (T08): el código Mermaid se
 * pasa a la WebView como JSON generado por kotlinx-serialization, nunca
 * concatenado como JavaScript sin escapar. El wrapper local (asset estático)
 * no contiene código de fixtures ni `securityLevel: loose`.
 */
class MermaidRenderRequestTest {

    private val json = Json

    private fun decodePayload(payload: String): MermaidRenderRequest =
        json.decodeFromString(MermaidRenderRequest.serializer(), payload)

    private fun assertRoundTrip(code: String) {
        val request = MermaidRenderRequest(code = code, theme = "dark", renderId = "r1")
        val payload = MermaidRequestCodec.payload(request)
        assertEquals(request, decodePayload(payload))
    }

    @Test
    fun `payload con comillas y backslashes se escapa y hace round-trip`() {
        val code = """graph TD; A["node with \"quotes\""] --> B["back\slash"]"""
        assertRoundTrip(code)
        val payload = MermaidRequestCodec.payload(
            MermaidRenderRequest(code, "light", "r1"),
        )
        assertTrue("las comillas deben ir escapadas como JSON", payload.contains("\\\""))
        assertTrue("los backslashes deben ir escapados", payload.contains("\\\\"))
    }

    @Test
    fun `payload con newlines se escapa y hace round-trip`() {
        val code = "graph TD\n  A[Inicio]\n  B[Fin]\n  A --> B"
        assertRoundTrip(code)
        val payload = MermaidRequestCodec.payload(
            MermaidRenderRequest(code, "dark", "r1"),
        )
        assertFalse("el newline literal no debe aparecer dentro de la string JSON", payload.contains("\n"))
        assertTrue("el newline debe ir como secuencia de escape", payload.contains("\\n"))
    }

    @Test
    fun `payload con script closing tag y unicode hace round-trip sin romper el JSON`() {
        val code = "graph TD\n  A[\"</script>\"] --> B[ñ € 🚀]"
        assertRoundTrip(code)
    }

    @Test
    fun `payload con separadores de linea U+2028 y U+2029 se escapa para JS`() {
        val code = "graph TD\n  A[\"l\u2028ine\u2029sep\"] --> B"
        val payload = MermaidRequestCodec.payload(MermaidRenderRequest(code, "dark", "r1"))
        assertFalse("U+2028 literal no debe aparecer en el payload", payload.contains('\u2028'))
        assertFalse("U+2029 literal no debe aparecer en el payload", payload.contains('\u2029'))
        assertTrue(payload.contains("\\u2028"))
        assertTrue(payload.contains("\\u2029"))
        assertEquals(MermaidRenderRequest(code, "dark", "r1"), decodePayload(payload))
    }

    @Test
    fun `buildInvocation es una llamada JSON al wrapper local, sin concatenacion`() {
        val code = "graph TD; A --> B"
        val invocation = MermaidRequestCodec.buildInvocation(
            MermaidRenderRequest(code, "light", "mermaid-render-7"),
        )
        assertTrue(invocation.startsWith("window.ExplainerMermaid.render("))
        assertTrue(invocation.endsWith(");"))
        // El código va dentro del JSON (string escapada), no como concatenación
        // de snippets: el payload debe volver a decodificar al request original.
        val jsonArg = invocation
            .removePrefix("window.ExplainerMermaid.render(")
            .removeSuffix(");")
        val request = decodePayload(jsonArg)
        assertEquals(code, request.code)
        assertEquals("light", request.theme)
        assertEquals("mermaid-render-7", request.renderId)
    }

    @Test
    fun `el wrapper estatico no contiene codigo de fixtures ni concatenacion`() {
        val wrapper = wrapperFile().readText()
        val fixtureCodes = listOf(
            "graph TD; A --> B",
            "A[\"node with \\\"quotes\\\"\"]",
            "</script>",
        )
        for (code in fixtureCodes) {
            assertFalse("el wrapper no debe contener el código crudo: $code", wrapper.contains(code))
        }
    }

    @Test
    fun `el wrapper usa securityLevel strict y nunca loose`() {
        val wrapper = wrapperFile().readText()
        assertTrue("el wrapper debe inicializar Mermaid con securityLevel strict", wrapper.contains("securityLevel: 'strict'"))
        assertFalse("el wrapper nunca debe usar loose", wrapper.contains("loose"))
        assertFalse("el wrapper nunca debe usar securityLevel con comillas dobles", wrapper.contains("securityLevel: \"strict\""))
    }

    @Test
    fun `el resultado del render se decodifica como JSON tipado`() {
        val ok = MermaidRequestCodec.decodeResult("""{"ok":true,"svg":"<svg></svg>"}""")
        assertEquals(MermaidRenderResult(ok = true, svg = "<svg></svg>"), ok)
        val err = MermaidRequestCodec.decodeResult("""{"ok":false,"error":"parse error"}""")
        assertEquals(MermaidRenderResult(ok = false, error = "parse error"), err)
        assertNull(MermaidRequestCodec.decodeResult("not-json"))
        assertNull(MermaidRequestCodec.decodeResult("null"))
    }

    @Test
    fun `metadatos del export png se decodifican y correlacionan por exportId`() {
        val meta = MermaidRequestCodec.decodePngExportMeta(
            """{"ok":true,"totalLength":2855890,"chunkSize":32768,"exportId":"mermaid-export-3"}""",
        )
        assertEquals(
            MermaidPngExportMeta(
                ok = true,
                totalLength = 2855890,
                chunkSize = 32768,
                exportId = "mermaid-export-3",
            ),
            meta,
        )
        assertTrue(MermaidResultCorrelation.matchesExportMeta(meta, "mermaid-export-3"))
        assertFalse("un export anterior no satisface el polling nuevo", MermaidResultCorrelation.matchesExportMeta(meta, "mermaid-export-4"))
        assertFalse(MermaidResultCorrelation.matchesExportMeta(null, "mermaid-export-3"))
        val err = MermaidRequestCodec.decodePngExportMeta(
            """{"ok":false,"error":"sin diagrama","exportId":"mermaid-export-3"}""",
        )
        assertEquals(
            MermaidPngExportMeta(ok = false, error = "sin diagrama", exportId = "mermaid-export-3"),
            err,
        )
        assertNull(MermaidRequestCodec.decodePngExportMeta("not-json"))
        assertNull(MermaidRequestCodec.decodePngExportMeta("null"))
    }

    @Test
    fun `invocaciones del canal de trozos y del export svg`() {
        assertEquals(
            "window.ExplainerMermaid.takeExportPngChunk(\"mermaid-export-3\", 32768);",
            MermaidRequestCodec.buildChunkInvocation(MermaidPngChunkRequest("mermaid-export-3", 32768)),
        )
        assertEquals(
            "window.ExplainerMermaid.clearExportPayload(\"mermaid-export-3\");",
            MermaidRequestCodec.buildClearExportInvocation("mermaid-export-3"),
        )
        assertEquals(
            "window.ExplainerMermaid.exportSvg(\"mermaid-svg-2\");",
            MermaidRequestCodec.buildSvgExportInvocation(MermaidSvgExportRequest("mermaid-svg-2")),
        )
    }

    @Test
    fun `decodeChunk devuelve el trozo o null sin romper el JSON`() {
        // evaluateJavascript entrega un string JS como literal JSON con
        // comillas; el trozo real es su contenido deserializado.
        assertEquals("abc123+=", MermaidRequestCodec.decodeChunk("\"abc123+=\""))
        assertNull("null JS = fin de canal o id no coincide", MermaidRequestCodec.decodeChunk("null"))
        assertNull(MermaidRequestCodec.decodeChunk("not-json"))
    }

    @Test
    fun `el resultado del export svg se decodifica y correlaciona por exportId`() {
        val ok = MermaidRequestCodec.decodeSvgExportResult(
            """{"ok":true,"svg":"<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>","exportId":"mermaid-svg-2"}""",
        )
        assertEquals(
            MermaidSvgExportResult(
                ok = true,
                svg = "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>",
                exportId = "mermaid-svg-2",
            ),
            ok,
        )
        assertTrue(MermaidResultCorrelation.matchesSvgExport(ok, "mermaid-svg-2"))
        assertFalse("un export anterior no satisface el polling nuevo", MermaidResultCorrelation.matchesSvgExport(ok, "mermaid-svg-3"))
        val err = MermaidRequestCodec.decodeSvgExportResult("""{"ok":false,"error":"x","exportId":"mermaid-svg-2"}""")
        assertFalse(err!!.ok)
        assertNull(MermaidRequestCodec.decodeSvgExportResult("not-json"))
    }

    @Test
    fun `el transporte del png distingue el fallo de transporte del de rasterizacion`() {
        val decoded = MermaidRequestCodec.decodeExportResult(
            """{"ok":false,"error":"timeout","exportId":"mermaid-export-3","transportFailure":true}""",
        )
        assertEquals(
            MermaidPngExportResult(
                ok = false,
                error = "timeout",
                exportId = "mermaid-export-3",
                transportFailure = true,
            ),
            decoded,
        )
        // El decode de resultados antiguos (sin el flag) sigue funcionando.
        val legacy = MermaidRequestCodec.decodeExportResult("""{"ok":false,"error":"x","exportId":"e"}""")
        assertEquals(MermaidPngExportResult(ok = false, error = "x", exportId = "e"), legacy)
    }

    private fun wrapperFile(): File = MermaidAssetTestSupport.file("explainer-mermaid.js")
}

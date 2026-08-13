package com.explainer.app.ui.content.mermaid

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Contrato del export PNG (paridad web `_downloadPng`): el wrapper expone
 * `exportPng(exportId)` que rasteriza el diagrama actual a un data URL PNG;
 * el resultado viaja por el canal de polling de export con correlación por
 * exportId, sin fetch/XHR/bridge/CDN (mismas invariantes que el render).
 */
class MermaidPngExportTest {

    @Test
    fun `buildPngInvocation llama al wrapper local con el exportId como JSON`() {
        val invocation = MermaidRequestCodec.buildPngInvocation(MermaidPngExportRequest("mermaid-export-3"))
        assertTrue(invocation.startsWith("window.ExplainerMermaid.exportPng("))
        assertTrue(invocation.endsWith(");"))
        val jsonArg = invocation
            .removePrefix("window.ExplainerMermaid.exportPng(")
            .removeSuffix(");")
        assertEquals("el id viaja como string JSON", "\"mermaid-export-3\"", jsonArg)
    }

    @Test
    fun `decodeExportResult parsea el data URL PNG y el error`() {
        val ok = MermaidRequestCodec.decodeExportResult(
            """{"ok":true,"png":"data:image/png;base64,iVBORw0KGgo=","exportId":"mermaid-export-3"}""",
        )
        assertEquals(
            MermaidPngExportResult(
                ok = true,
                png = "data:image/png;base64,iVBORw0KGgo=",
                exportId = "mermaid-export-3",
            ),
            ok,
        )
        val err = MermaidRequestCodec.decodeExportResult(
            """{"ok":false,"error":"sin diagrama","exportId":"mermaid-export-3"}""",
        )
        assertEquals(
            MermaidPngExportResult(ok = false, error = "sin diagrama", exportId = "mermaid-export-3"),
            err,
        )
        assertNull(MermaidRequestCodec.decodeExportResult("not-json"))
        assertNull(MermaidRequestCodec.decodeExportResult("null"))
    }

    @Test
    fun `correlacion del export por exportId`() {
        val result = MermaidPngExportResult(ok = true, png = "data:image/png;base64,x", exportId = "mermaid-export-1")
        assertTrue(MermaidResultCorrelation.matchesExport(result, "mermaid-export-1"))
        assertFalse("un export anterior no satisface el polling nuevo", MermaidResultCorrelation.matchesExport(result, "mermaid-export-2"))
        assertFalse(MermaidResultCorrelation.matchesExport(null, "mermaid-export-1"))
        val noId = MermaidPngExportResult(ok = true, png = "data:image/png;base64,x")
        assertFalse(MermaidResultCorrelation.matchesExport(noId, "mermaid-export-1"))
    }

    @Test
    fun `el wrapper expone exportPng y takeExportResult sin fetch ni bridge`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        assertTrue(wrapper.contains("exportPng: exportPng"))
        assertTrue(wrapper.contains("takeExportResult: takeExportResult"))
        assertTrue("la rama ok incluye exportId", wrapper.contains("exportId: exportId"))
        assertTrue("el canal de export es independiente del de render", wrapper.contains("pendingExportResult"))
        // Invariantes de assets: sin red, sin bridge, sin CDN (mismo escaneo
        // que MermaidWebViewConfigTest sobre los assets propios).
        val forbidden = listOf("http://", "https://", "jsdelivr", "node_modules", "unpkg")
        for (needle in forbidden) {
            assertFalse("el wrapper no debe contener '$needle'", wrapper.contains(needle))
        }
        assertFalse("sin fetch", wrapper.contains("fetch("))
        assertFalse("sin XMLHttpRequest", wrapper.contains("XMLHttpRequest"))
        assertFalse("sin addJavascriptInterface", wrapper.contains("addJavascriptInterface"))
        assertFalse("sin securityLevel loose", wrapper.contains("loose"))
    }

    @Test
    fun `la webview aplica el touch propio del diagrama y el canal de export`() {
        val source = mainSource("mermaid/HardenedMermaidWebView.kt").readText()
        assertTrue(
            "la WebView debe pedir no interceptar los gestos al contenedor exterior",
            source.contains("requestDisallowInterceptTouchEvent(true)"),
        )
        assertTrue("el fit inicial debe activar viewport ancho", source.contains("useWideViewPort"))
        assertTrue("el fit inicial debe activar overview mode", source.contains("loadWithOverviewMode"))
        assertTrue(
            "el export PNG debe correlacionar por exportId",
            source.contains("MermaidResultCorrelation.matchesExport"),
        )
        assertTrue(
            "el polling del export debe leer takeExportResult",
            source.contains("takeExportResult"),
        )
    }

    @Test
    fun `el polling del resultado no re-stringifica el JSON (regresion doble codificacion)`() {
        // evaluateJavascript entrega el resultado YA codificado como JSON (un
        // string JS llega con comillas y escapes). Envolver el takeResult en
        // JSON.stringify() duplicaba la codificación y rompía el decode →
        // timeout de polling con el SVG ya visible: "No se pudo generar el
        // diagrama" + descargas deshabilitadas (bug real reportado).
        val source = mainSource("mermaid/HardenedMermaidWebView.kt").readText()
        assertFalse(
            "el polling del render no debe re-stringificar el resultado",
            source.contains("JSON.stringify(window.ExplainerMermaid.takeResult()"),
        )
        assertFalse(
            "el polling del export no debe re-stringificar el resultado",
            source.contains("JSON.stringify(window.ExplainerMermaid.takeExportResult()"),
        )
        assertTrue(
            "el polling del render debe leer takeResult directamente",
            source.contains("window.ExplainerMermaid.takeResult();"),
        )
        assertTrue(
            "el polling del export debe leer takeExportResult directamente",
            source.contains("window.ExplainerMermaid.takeExportResult();"),
        )
    }

    @Test
    fun `el wrapper re-renderiza el export con htmlLabels en el nivel raiz y tema claro`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        // htmlLabels:false a NIVEL RAÍZ (en mermaid 11.16.1 es opción de
        // nivel superior; la directiva por-diagrama antigua seguía emitiendo
        // foreignObject → canvas tainted → "No se pudo generar la imagen").
        assertTrue("htmlLabels raíz del export", wrapper.contains("htmlLabels: false"))
        assertTrue("tema claro fijo para export", wrapper.contains("theme: 'neutral'"))
        assertTrue("fondo blanco explícito", wrapper.contains("'#ffffff'"))
        assertFalse(
            "la directiva por-diagrama antigua no debe reaparecer",
            wrapper.contains("\"flowchart\":{\"htmlLabels"),
        )
        assertTrue(
            "la detección de directiva del autor debe usar trimStart",
            wrapper.contains("trimStart()"),
        )
    }

    @Test
    fun `el wrapper normaliza el svg de export (dimensiones, fondo y xmlns)`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        assertTrue("normalización vía DOMParser", wrapper.contains("new DOMParser()"))
        assertTrue(
            "width/height numéricos desde viewBox (nunca 100%)",
            wrapper.contains("setAttribute('width'"),
        )
        assertTrue("rect blanco opaco como primer hijo", wrapper.contains("#ffffff"))
        assertTrue("xmlns defensivo", wrapper.contains("www.w3.org/2000/svg"))
    }

    @Test
    fun `el rasterizado tiene timeout y valida el canvas`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        assertTrue("timeout explícito de Image", wrapper.contains("IMG_LOAD_TIMEOUT_MS"))
        assertTrue("ctx debe validarse antes de dibujar", wrapper.contains("!ctx"))
        assertTrue("cap de lado de Chromium", wrapper.contains("MAX_CANVAS_SIDE"))
        assertTrue("cap de área/píxeles de Chromium", wrapper.contains("MAX_CANVAS_AREA"))
        assertTrue("cap de píxeles de memoria móvil", wrapper.contains("MAX_CANVAS_PIXELS"))
    }

    @Test
    fun `el png viaja en trozos y takeExportResult nunca devuelve el data URL completo`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        assertTrue("API de trozos", wrapper.contains("takeExportPngChunk"))
        assertTrue("liberación del payload", wrapper.contains("clearExportPayload"))
        assertFalse(
            "takeExportResult no debe empaquetar el png completo",
            wrapper.contains("png: png"),
        )
        assertTrue("los metadatos declaran la longitud total", wrapper.contains("totalLength"))
        assertTrue("los metadatos declaran el tamaño de trozo", wrapper.contains("chunkSize"))
    }

    @Test
    fun `el wrapper expone el canal de export svg normalizado`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        assertTrue(wrapper.contains("exportSvg: exportSvg"))
        assertTrue("el svg de export viaja por el canal de export", wrapper.contains("svg: normalized"))
    }

    @Test
    fun `la webview lee el png en trozos y libera el payload`() {
        val source = mainSource("mermaid/HardenedMermaidWebView.kt").readText()
        assertTrue(source.contains("takeExportPngChunk"))
        assertTrue(source.contains("MermaidResultCorrelation.matchesExportMeta"))
        assertTrue(source.contains("MermaidPngChunkAssembler"))
        assertTrue("la limpieza debe ser incondicional", source.contains("buildClearExportInvocation"))
    }

    @Test
    fun `la webview expone el canal de export svg y la ui lo usa para descargar`() {
        val webView = mainSource("mermaid/HardenedMermaidWebView.kt").readText()
        assertTrue(webView.contains("svgExportRequest"))
        assertTrue(webView.contains("buildSvgExportInvocation"))
        assertTrue(webView.contains("MermaidResultCorrelation.matchesSvgExport"))
        val content = mainSource("mermaid/MermaidContent.kt").readText()
        assertTrue("la UI dispara el export SVG con id único", content.contains("MermaidSvgExportRequest"))
        assertTrue(
            "la UI distingue el fallo de transporte del de rasterización",
            content.contains("DiagramFeedback.ExportTransportFailed"),
        )
        assertTrue(content.contains("result.transportFailure"))
        assertTrue(content.contains("content_diagram_export_transport_failed"))
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

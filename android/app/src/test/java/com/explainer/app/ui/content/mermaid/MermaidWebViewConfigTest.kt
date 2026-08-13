package com.explainer.app.ui.content.mermaid

import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.CSP
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.security.MessageDigest

/**
 * Verificación estática del hardening de la WebView Mermaid (T08): CSP
 * exacta del contrato, allowlist host/path, `securityLevel:'strict'`,
 * settings prohibidos en false y assets locales sin CDN ni referencias
 * remotas, con versión/checksum registrados.
 */
class MermaidWebViewConfigTest {

    // ── Config estática ──

    @Test
    fun `la unica URL de entrada es el asset local via WebViewAssetLoader`() {
        assertEquals(
            "https://appassets.androidplatform.net/assets/mermaid/index.html",
            MermaidWebViewConfig.ASSET_BASE_URL,
        )
        assertEquals("appassets.androidplatform.net", MermaidWebViewConfig.ASSET_HOST)
        assertEquals("/assets/", MermaidWebViewConfig.ASSET_PATH_PREFIX)
        assertFalse(MermaidWebViewConfig.ASSET_BASE_URL.startsWith("file:"))
        assertFalse(MermaidWebViewConfig.ASSET_BASE_URL.startsWith("content:"))
        assertFalse(MermaidWebViewConfig.ASSET_BASE_URL.startsWith("data:"))
    }

    @Test
    fun `el prefijo del asset loader resuelve la URL base a un archivo existente`() {
        // Invariante real del WebViewAssetLoader: resta el prefijo registrado
        // del path de la URL y abre el resto bajo assets/. Un prefijo que se
        // come de más (p. ej. incluir "mermaid/") resuelve a un archivo
        // inexistente y la WebView responde ERR_INVALID_RESPONSE (regresión
        // real reportada en producción: esquema no visible).
        val url = java.net.URI(MermaidWebViewConfig.ASSET_BASE_URL)
        assertEquals("appassets.androidplatform.net", url.host)
        val path = requireNotNull(url.path)
        assertTrue(
            "la URL base debe empezar por el prefijo del loader",
            path.startsWith(MermaidWebViewConfig.ASSET_PATH_PREFIX),
        )
        val relativePath = path.removePrefix(MermaidWebViewConfig.ASSET_PATH_PREFIX)
        val asset = MermaidAssetTestSupport.fileUnderAssets(relativePath)
        assertTrue(
            "el prefijo debe resolver la URL base a un asset existente: $relativePath",
            asset.isFile,
        )
    }

    @Test
    fun `la CSP es exactamente la fijada en el contrato`() {
        assertEquals(
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
                "img-src data:; font-src 'self'; connect-src 'none'; frame-src 'none'; " +
                "base-uri 'none'; form-action 'none'",
            CSP,
        )
        // Invariantes clave de la CSP.
        assertTrue(CSP.contains("default-src 'none'"))
        assertTrue(CSP.contains("script-src 'self'"))
        assertTrue(CSP.contains("connect-src 'none'"))
        assertTrue(CSP.contains("frame-src 'none'"))
        assertTrue(CSP.contains("base-uri 'none'"))
        assertTrue(CSP.contains("form-action 'none'"))
        assertFalse("no puede haber remote sources", CSP.contains("https://"))
        assertFalse("no puede haber estrellas", CSP.contains("*"))
    }

    @Test
    fun `securityLevel es strict y nunca loose`() {
        assertEquals("strict", MermaidWebViewConfig.SECURITY_LEVEL)
        assertFalse("nunca relajar a loose", "loose" == MermaidWebViewConfig.SECURITY_LEVEL)
    }

    @Test
    fun `el hardening deja los settings peligrosos en false y zoom activo`() {
        val h = MermaidHardening.defaults()
        assertTrue("JavaScript solo en esta WebView", h.javaScriptEnabled)
        assertFalse(h.allowFileAccess)
        assertFalse(h.allowContentAccess)
        assertFalse(h.allowUniversalAccessFromFileURLs)
        assertFalse(h.allowFileAccessFromFileURLs)
        assertEquals(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW, h.mixedContentMode)
        assertFalse("sin DOM storage", h.domStorageEnabled)
        assertTrue("sin red del todo: assets 100% locales", h.blockNetworkLoads)
        assertTrue("Safe Browsing activo", h.safeBrowsingEnabled)
        assertTrue("pinch zoom soportado", h.supportZoom)
        assertTrue(h.builtInZoomControls)
        assertFalse("sin controles de zoom flotantes", h.displayZoomControls)
        assertTrue("viewport ancho (fit inicial del diagrama)", h.useWideViewPort)
        assertTrue("overview mode (diagrama completo visible al inicio)", h.loadWithOverviewMode)
    }

    @Test
    fun `versiones e integridad registradas coinciden con el contrato`() {
        assertEquals("11.16.1", MermaidWebViewConfig.MERMAID_VERSION)
        assertEquals(
            "sha512-TQsq6u22fAn3rek5VOubrhKPo1g5hwC3FXUN9hiyupTckcYiGuuKGkNQrKYwGJkXUxZdojwRG46gsSCFZMDp4g==",
            MermaidWebViewConfig.MERMAID_TARBALL_INTEGRITY,
        )
    }

    // ── Assets ──

    @Test
    fun `los assets propios no contienen CDN ni referencias remotas ni node_modules`() {
        // Los assets propios (index.html + wrapper) no pueden referenciar nada
        // remoto. El bundle de terceros solo se escanea contra marcadores de
        // CDN (su contenido minificado incluye banners de licencia con URLs
        // documentales como http://opensource.org); LICENSE es texto legal.
        val forbidden = listOf("http://", "https://", "jsdelivr", "node_modules", "unpkg")
        val owned = listOf("index.html", "explainer-mermaid.js")
        for (name in owned) {
            val content = MermaidAssetTestSupport.file(name).readText()
            for (needle in forbidden) {
                assertFalse(
                    "$name no debe contener '$needle'",
                    content.contains(needle),
                )
            }
        }
        val cdnMarkers = listOf("jsdelivr", "unpkg", "cdn.")
        val bundle = MermaidAssetTestSupport.file("mermaid.min.js").readText()
        for (needle in cdnMarkers) {
            assertFalse("el bundle no debe referenciar CDN '$needle'", bundle.contains(needle))
        }
    }

    @Test
    fun `index html declara la CSP del contrato`() {
        val index = MermaidAssetTestSupport.file("index.html").readText()
        assertTrue(index.contains("http-equiv=\"Content-Security-Policy\""))
        assertTrue(index.contains(MermaidWebViewConfig.CSP))
    }

    @Test
    fun `el bundle mermaid esta versionado y su checksum coincide con el manifest`() {
        val bundle = MermaidAssetTestSupport.file("mermaid.min.js")
        assertTrue("el bundle debe existir", bundle.exists())
        assertTrue("el bundle debe ser el full bundle (~MB)", bundle.length() > 1_000_000)
        val content = bundle.readText()
        assertTrue("el bundle debe declarar su versión", content.contains(MermaidWebViewConfig.MERMAID_VERSION))
        assertFalse("el bundle no debe ser de CDN", content.contains("jsdelivr"))

        val manifest = MermaidAssetTestSupport.file("README.md").readText()
        val recorded = Regex("Bundle sha512: sha512-([0-9a-fA-F]+)")
            .find(manifest)?.groupValues?.getOrNull(1)
        assertTrue("el manifest debe registrar el checksum del bundle", recorded != null)
        val actual = sha512Hex(bundle.readBytes())
        assertEquals("el checksum del bundle debe coincidir con el manifest", recorded, actual)
    }

    @Test
    fun `el wrapper no contiene concatenacion de request ni bridge`() {
        val wrapper = MermaidAssetTestSupport.file("explainer-mermaid.js").readText()
        assertFalse("sin addJavascriptInterface (es Kotlin, no JS)", wrapper.contains("addJavascriptInterface"))
        assertFalse("sin fetch/XHR", wrapper.contains("fetch("))
        assertFalse("sin XMLHttpRequest", wrapper.contains("XMLHttpRequest"))
    }

    // ── helpers ──

    private fun sha512Hex(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-512").digest(bytes)
        return digest.joinToString("") { "%02x".format(it) }
    }
}

/** Resolución de assets de Mermaid para tests JVM (working dir = módulo :app). */
internal object MermaidAssetTestSupport {

    private fun baseDir(): File {
        val candidates = listOf(
            File(System.getProperty("user.dir") ?: "", "src/main/assets/mermaid"),
            File("src/main/assets/mermaid"),
            File("app/src/main/assets/mermaid"),
        )
        return candidates.firstOrNull { it.isDirectory }
            ?: error("assets mermaid no encontrados (buscado en ${candidates.joinToString()})")
    }

    fun file(name: String): File = File(baseDir(), name)

    /** Resuelve un path relativo a la raíz `assets/` del módulo (como lo hace WebViewAssetLoader). */
    fun fileUnderAssets(relativePath: String): File = File(baseDir().parentFile, relativePath)

    fun allFiles(): List<File> = baseDir().listFiles().orEmpty().filter { it.isFile }
}

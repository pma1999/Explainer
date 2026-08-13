package com.explainer.app.ui.content.mermaid

import android.webkit.WebSettings

/**
 * Configuración estática y verificable del hardening de la única WebView de
 * la app (T08, `integration-content-rendering.md`). Los tests JVM la
 * verifican contra el contrato; [MermaidHardening] es aplicada por
 * [HardenedMermaidWebView] a la WebView real.
 */
object MermaidWebViewConfig {

    /** Versión exacta del bundle local (npm `mermaid@11.16.1`, 2026-08-08). */
    const val MERMAID_VERSION = "11.16.1"

    /** Integridad sha512 base64 declarada por el registro npm para el tarball. */
    const val MERMAID_TARBALL_INTEGRITY =
        "sha512-TQsq6u22fAn3rek5VOubrhKPo1g5hwC3FXUN9hiyupTckcYiGuuKGkNQrKYwGJkXUxZdojwRG46gsSCFZMDp4g=="

    /** Única URL de entrada: asset local servido por WebViewAssetLoader. */
    const val ASSET_BASE_URL = "https://appassets.androidplatform.net/assets/mermaid/index.html"

    /** Host de la allowlist del asset loader. */
    const val ASSET_HOST = "appassets.androidplatform.net"

    /**
     * Prefijo de path de la allowlist. Debe ser `/assets/` (no
     * `/assets/mermaid/`): WebViewAssetLoader RESTA el prefijo del path de la
     * URL y abre el resto bajo `assets/` del APK. Con el prefijo viejo, la
     * URL `/assets/mermaid/index.html` resolvía a `assets/index.html`
     * (inexistente) → respuesta vacía → `ERR_INVALID_RESPONSE`. El host es
     * sintético y solo lo intercepta esta WebView; `assets/` contiene
     * exclusivamente el bundle mermaid.
     */
    const val ASSET_PATH_PREFIX = "/assets/"

    /** CSP exacta del contrato (documento local, sin fuentes remotas). */
    const val CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
        "img-src data:; font-src 'self'; connect-src 'none'; frame-src 'none'; " +
        "base-uri 'none'; form-action 'none'"

    /** `securityLevel` de Mermaid: strict, nunca `loose`. */
    const val SECURITY_LEVEL = "strict"

    /** Tiempo máximo de espera del resultado de un render (polling). */
    const val RENDER_TIMEOUT_MS = 15_000L

    /** Tiempo máximo de espera del resultado de un export PNG (rasterización). */
    const val PNG_EXPORT_TIMEOUT_MS = 25_000L

    /** Tiempo máximo de espera del resultado de un export SVG (re-render + normalización). */
    const val SVG_EXPORT_TIMEOUT_MS = 15_000L

    /** Intervalo del polling de `takeResult()`. */
    const val RESULT_POLL_INTERVAL_MS = 80L
}

/**
 * Ajustes vinculantes de la WebView Mermaid (T08). Se aplican en la única
 * WebView de la app; los tests estáticos verifican que los settings
 * peligrosos quedan en `false` y el zoom activo.
 */
data class MermaidHardening(
    val javaScriptEnabled: Boolean,
    val allowFileAccess: Boolean,
    val allowContentAccess: Boolean,
    val allowUniversalAccessFromFileURLs: Boolean,
    val allowFileAccessFromFileURLs: Boolean,
    val mixedContentMode: Int,
    val domStorageEnabled: Boolean,
    val blockNetworkLoads: Boolean,
    val safeBrowsingEnabled: Boolean,
    val supportZoom: Boolean,
    val builtInZoomControls: Boolean,
    val displayZoomControls: Boolean,
    val useWideViewPort: Boolean,
    val loadWithOverviewMode: Boolean,
) {
    companion object {
        /**
         * Default endurecido: JavaScript solo aquí, sin file/content/mixed,
         * sin DOM storage, sin red del todo (los assets viven en el APK),
         * pinch zoom/pan nativo del WebView sin controles flotantes y
         * viewport ancho con overview mode (el diagrama completo es visible
         * al instante; el zoom/pan queda para explorar el detalle).
         */
        fun defaults(): MermaidHardening = MermaidHardening(
            javaScriptEnabled = true,
            allowFileAccess = false,
            allowContentAccess = false,
            allowUniversalAccessFromFileURLs = false,
            allowFileAccessFromFileURLs = false,
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW,
            domStorageEnabled = false,
            blockNetworkLoads = true,
            safeBrowsingEnabled = true,
            supportZoom = true,
            builtInZoomControls = true,
            displayZoomControls = false,
            useWideViewPort = true,
            loadWithOverviewMode = true,
        )
    }
}

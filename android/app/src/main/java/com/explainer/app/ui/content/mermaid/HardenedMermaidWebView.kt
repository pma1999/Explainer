package com.explainer.app.ui.content.mermaid

import android.annotation.SuppressLint
import android.os.Build
import android.view.MotionEvent
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.webkit.WebViewAssetLoader
import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.ASSET_BASE_URL
import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.ASSET_PATH_PREFIX
import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.PNG_EXPORT_TIMEOUT_MS
import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.RENDER_TIMEOUT_MS
import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.RESULT_POLL_INTERVAL_MS
import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.SECURITY_LEVEL
import com.explainer.app.ui.content.mermaid.MermaidWebViewConfig.SVG_EXPORT_TIMEOUT_MS
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * WebView aislada exclusiva para Mermaid (T08): assets 100% locales servidos
 * por [WebViewAssetLoader] bajo el host/path de allowlist, sin
 * `addJavascriptInterface`, sin DOM storage, sin file/content access, sin
 * mixed content, sin red del todo, Safe Browsing activo y navegación externa
 * bloqueada. El código del diagrama viaja como JSON (ver
 * [MermaidRequestCodec]); el resultado se lee por polling de `takeResult()`.
 *
 * El diagrama es su propia superficie de navegación: viewport ancho con
 * overview mode (fit inicial al ancho, sin scroll horizontal), pinch zoom +
 * doble tap nativos, y un [OnTouchListener] que pide al contenedor exterior
 * no interceptar los gestos ([MotionEvent.ACTION_DOWN] y drags) para que el
 * pan/zoom sean estables y el LazyColumn del lector no se mueva.
 *
 * Export PNG (paridad web `_downloadPng`): con [pngExportRequest] no nulo se
 * dispara `exportPng` en el wrapper y el data URL se lee por el canal de
 * export en TROZOS: primero los metadatos por polling de `takeExportResult()`
 * (correlación por exportId) y después el payload con
 * `takeExportPngChunk(exportId, offset)` — el data URL completo de MBs en una
 * sola respuesta de `evaluateJavascript` se rompía/timeout. Kotlin reensambla
 * y valida ([MermaidPngChunkAssembler]) y SIEMPRE libera el payload del
 * wrapper con `clearExportPayload`; [onPngExportFinished] notifica el
 * resultado, marcando [MermaidPngExportResult.transportFailure] cuando el
 * fallo fue del transporte y no de la rasterización.
 *
 * Export SVG (descarga `esquema.svg`): con [svgExportRequest] no nulo se
 * dispara `exportSvg` en el wrapper y el SVG NORMALIZADO (tema claro fijo,
 * dimensiones numéricas, fondo blanco) se lee por el mismo canal de polling,
 * correlacionado por exportId — nunca el `res.svg` de pantalla, que los
 * visores externos renderizaban negro/vacío.
 *
 * Tema claro/oscuro: [darkTheme] vuelve a renderizar con la paleta académica
 * de T05 adaptada (paridad `projectView.js _ensureMermaidInit`, con
 * `securityLevel:'strict'` en lugar de `loose`).
 *
 * @param onRenderFinished callback opcional con el resultado del último
 *   render (p. ej. para auto-revelar el código fuente si falla).
 * @param pngExportRequest request de export PNG; un valor no nulo dispara el
 *   export en el wrapper y [onPngExportFinished] recibe el resultado.
 * @param svgExportRequest request de export SVG; un valor no nulo dispara el
 *   export en el wrapper y [onSvgExportFinished] recibe el resultado.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun HardenedMermaidWebView(
    code: String,
    darkTheme: Boolean,
    modifier: Modifier = Modifier,
    onRenderFinished: ((MermaidRenderResult?) -> Unit)? = null,
    pngExportRequest: MermaidPngExportRequest? = null,
    onPngExportFinished: ((MermaidPngExportResult?) -> Unit)? = null,
    svgExportRequest: MermaidSvgExportRequest? = null,
    onSvgExportFinished: ((MermaidSvgExportResult?) -> Unit)? = null,
) {
    val webViewRef = remember { mutableStateOf<WebView?>(null) }
    val renderSequence = remember { AtomicInteger(0) }
    val pageReady = remember { kotlinx.coroutines.flow.MutableStateFlow(false) }

    AndroidView(
        modifier = modifier,
        factory = { context ->
            WebView(context).apply {
                setBackgroundColor(android.graphics.Color.TRANSPARENT)
                val hardening = MermaidHardening.defaults()
                val settings: WebSettings = this.settings
                settings.javaScriptEnabled = hardening.javaScriptEnabled
                settings.allowFileAccess = hardening.allowFileAccess
                settings.allowContentAccess = hardening.allowContentAccess
                settings.allowUniversalAccessFromFileURLs = hardening.allowUniversalAccessFromFileURLs
                settings.allowFileAccessFromFileURLs = hardening.allowFileAccessFromFileURLs
                settings.mixedContentMode = hardening.mixedContentMode
                settings.domStorageEnabled = hardening.domStorageEnabled
                settings.blockNetworkLoads = hardening.blockNetworkLoads
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
                    settings.safeBrowsingEnabled = hardening.safeBrowsingEnabled
                }
                // Nota: en WebSettings estos tres son métodos no-JavaBean
                // (supportZoom()/setSupportZoom(...)), por eso se llaman los setters.
                settings.setSupportZoom(hardening.supportZoom)
                settings.setBuiltInZoomControls(hardening.builtInZoomControls)
                settings.setDisplayZoomControls(hardening.displayZoomControls)
                // Fit inicial: el diagrama completo es visible al instante
                // (viewport ancho + overview mode) y el zoom/pan queda para
                // explorar el detalle. No relaja nada del hardening.
                settings.useWideViewPort = hardening.useWideViewPort
                settings.loadWithOverviewMode = hardening.loadWithOverviewMode
                val assetLoader = WebViewAssetLoader.Builder()
                    .addPathHandler(ASSET_PATH_PREFIX, WebViewAssetLoader.AssetsPathHandler(context))
                    .build()

                // El diagrama es su propia superficie de navegación: los
                // gestos sobre la WebView (ACTION_DOWN y drags, incluido el
                // pinch con POINTER_DOWN/UP) no deben ser interceptados por
                // el LazyColumn exterior, para que el pan (ampliado) y el
                // zoom sean estables. Se devuelve false para que la WebView
                // procese el evento con normalidad.
                setOnTouchListener { _, event ->
                    when (event.actionMasked) {
                        MotionEvent.ACTION_DOWN,
                        MotionEvent.ACTION_MOVE,
                        MotionEvent.ACTION_POINTER_DOWN,
                        MotionEvent.ACTION_POINTER_UP,
                        -> parent?.requestDisallowInterceptTouchEvent(true)

                        else -> Unit
                    }
                    false
                }

                webViewClient = object : WebViewClient() {
                    override fun shouldInterceptRequest(
                        view: WebView,
                        request: WebResourceRequest,
                    ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)

                    override fun shouldOverrideUrlLoading(
                        view: WebView,
                        request: WebResourceRequest,
                    ): Boolean = true // nunca navegar fuera del documento local

                    override fun onPageFinished(view: WebView, url: String?) {
                        pageReady.value = true
                    }
                }

                loadUrl(ASSET_BASE_URL)
                webViewRef.value = this
            }
        },
        onRelease = { webView ->
            webViewRef.value = null
            webView.destroy()
        },
    )

    LaunchedEffect(code, darkTheme) {
        if (code.isBlank()) return@LaunchedEffect // Malformed se maneja en MermaidContent
        // Esperar al documento local + wrapper (los scripts se ejecutan antes
        // de onPageFinished). Timeout de página o WebView ausente → fallo
        // visible (remediación R-T08-01): nunca salir sin notificar.
        val webView = withTimeoutOrNull(RENDER_TIMEOUT_MS) {
            pageReady.first { it }
            webViewRef.value
        } ?: run {
            onRenderFinished?.invoke(null)
            return@LaunchedEffect
        }

        val request = MermaidRenderRequest(
            code = code,
            theme = if (darkTheme) "dark" else "light",
            renderId = "mermaid-render-" + renderSequence.incrementAndGet(),
        )
        if (!webView.evaluateJavascriptSafe(MermaidRequestCodec.buildInvocation(request))) {
            // Excepción de evaluación (WebView destruida/indisponible) →
            // fallo visible (remediación R-T08-01).
            onRenderFinished?.invoke(null)
            return@LaunchedEffect
        }
        val result = webView.awaitRenderResult(request.renderId)
        onRenderFinished?.invoke(result)
    }

    // Export PNG bajo demanda: cada request nuevo (id único) dispara
    // `exportPng` en el wrapper y se lee el data URL por polling del canal de
    // export, correlacionado por exportId.
    LaunchedEffect(pngExportRequest) {
        val request = pngExportRequest ?: return@LaunchedEffect
        val webView = webViewRef.value
        if (webView == null) {
            onPngExportFinished?.invoke(null)
            return@LaunchedEffect
        }
        if (!webView.evaluateJavascriptSafe(MermaidRequestCodec.buildPngInvocation(request))) {
            onPngExportFinished?.invoke(null)
            return@LaunchedEffect
        }
        onPngExportFinished?.invoke(webView.awaitPngExportResult(request.exportId))
    }

    // Export SVG bajo demanda (descarga esquema.svg): cada request nuevo (id
    // único) dispara `exportSvg` en el wrapper y se lee el SVG NORMALIZADO
    // por polling del canal de export, correlacionado por exportId.
    LaunchedEffect(svgExportRequest) {
        val request = svgExportRequest ?: return@LaunchedEffect
        val webView = webViewRef.value
        if (webView == null) {
            onSvgExportFinished?.invoke(null)
            return@LaunchedEffect
        }
        if (!webView.evaluateJavascriptSafe(MermaidRequestCodec.buildSvgExportInvocation(request))) {
            onSvgExportFinished?.invoke(null)
            return@LaunchedEffect
        }
        onSvgExportFinished?.invoke(webView.awaitSvgExportResult(request.exportId))
    }
}

/** evaluateJavascript sin propagar excepciones; `false` si la evaluación falló. */
private fun WebView.evaluateJavascriptSafe(script: String): Boolean =
    runCatching { evaluateJavascript(script, null) }.isSuccess

private suspend fun WebView.evaluateJavascriptAwait(script: String): String? =
    suspendCancellableCoroutine { cont ->
        runCatching {
            evaluateJavascript(script) { value -> cont.resume(value) }
        }.onFailure { cont.resume(null) }
    }

/**
 * Polling del resultado del wrapper local (`takeResult()`), con timeout y
 * correlación por `renderId` (remediación R-T08-04): un resultado obsoleto de
 * un render anterior (cambio rápido de código/tema) no satisface el polling
 * del render nuevo; el `null` final (timeout) es un fallo visible.
 */
private suspend fun WebView.awaitRenderResult(expectedRenderId: String): MermaidRenderResult? {
    val deadline = System.currentTimeMillis() + RENDER_TIMEOUT_MS
    while (System.currentTimeMillis() < deadline) {
        // IMPORTANTE: `evaluateJavascript` entrega el resultado YA codificado
        // como JSON (un string JS llega con comillas y escapes). Por eso el
        // script devuelve el OBJETO directamente, sin JSON.stringify(): el
        // propio canal lo serializa a su texto JSON y decodeResult lo parsea
        // tal cual. Envolverlo en JSON.stringify() duplicaba la codificación
        // (string literal con comillas) y rompía el decode → timeout de
        // polling → "No se pudo generar el diagrama" con el SVG ya visible.
        val raw = evaluateJavascriptAwait("window.ExplainerMermaid.takeResult();")
        val result = raw?.let { MermaidRequestCodec.decodeResult(it) }
        if (MermaidResultCorrelation.matches(result, expectedRenderId)) return result
        delay(RESULT_POLL_INTERVAL_MS)
    }
    return null
}

/**
 * Export PNG por el canal de chunks (T-EXPORT): el data URL completo NO viaja
 * en una sola respuesta de `evaluateJavascript` (un payload de MBs se
 * rompía/timeout). Primero se leen los METADATOS por polling de
 * `takeExportResult()` (correlación por exportId, timeout propio) y después
 * el payload en trozos secuenciales de ~32 KB con `takeExportPngChunk`, que
 * se reensamblan y validan en [MermaidPngChunkAssembler] (offsets contiguos,
 * longitud total exacta, prefijo del data URL). El payload del wrapper se
 * libera SIEMPRE al terminar (éxito, fallo o aborto). Un fallo de transporte
 * se marca con [MermaidPngExportResult.transportFailure] para que la UI
 * distinga el feedback de rasterización (wrapper `{ok:false}`).
 */
private suspend fun WebView.awaitPngExportResult(expectedExportId: String): MermaidPngExportResult? {
    val deadline = System.currentTimeMillis() + PNG_EXPORT_TIMEOUT_MS

    // 1. Metadatos primero (sin payload): polling de takeExportResult() —
    //    mismo canal que el render, sin JSON.stringify() (ver
    //    awaitRenderResult); el objeto viaja serializado por el propio canal.
    var meta: MermaidPngExportMeta? = null
    while (System.currentTimeMillis() < deadline) {
        val raw = evaluateJavascriptAwait("window.ExplainerMermaid.takeExportResult();")
        val decoded = raw?.let { MermaidRequestCodec.decodePngExportMeta(it) }
        if (MermaidResultCorrelation.matchesExportMeta(decoded, expectedExportId)) {
            meta = decoded
            break
        }
        delay(RESULT_POLL_INTERVAL_MS)
    }
    val m = meta
    if (m == null) {
        // Timeout de metadatos (o WebView/evaluación rota): fallo de transporte.
        evaluateJavascriptSafe(MermaidRequestCodec.buildClearExportInvocation(expectedExportId))
        return MermaidPngExportResult(
            ok = false,
            transportFailure = true,
            exportId = expectedExportId,
            error = "Timeout esperando los metadatos del export PNG.",
        )
    }
    if (!m.ok) {
        // Fallo de RASTERIZACIÓN reportado por el wrapper (m.error se conserva
        // para diagnóstico; la UI muestra el string de export fallido).
        evaluateJavascriptSafe(MermaidRequestCodec.buildClearExportInvocation(expectedExportId))
        return MermaidPngExportResult(
            ok = false,
            transportFailure = false,
            exportId = expectedExportId,
            error = m.error,
        )
    }
    val totalLength = m.totalLength
    val chunkSize = m.chunkSize
    if (totalLength == null || chunkSize == null || totalLength <= 0 || chunkSize <= 0) {
        evaluateJavascriptSafe(MermaidRequestCodec.buildClearExportInvocation(expectedExportId))
        return MermaidPngExportResult(
            ok = false,
            transportFailure = true,
            exportId = expectedExportId,
            error = "Metadatos del export PNG inválidos.",
        )
    }

    // 2. Lectura SECUENCIAL de trozos: cada llamada individual queda lejos
    //    del límite de transporte; el ensamblador valida el contrato en cada
    //    paso (offsets contiguos, tamaño y longitud total, prefijo).
    val assembler = MermaidPngChunkAssembler(expectedExportId, totalLength, chunkSize)
    var offset = 0
    while (System.currentTimeMillis() < deadline && !assembler.isComplete) {
        val raw = evaluateJavascriptAwait(
            MermaidRequestCodec.buildChunkInvocation(MermaidPngChunkRequest(expectedExportId, offset)),
        )
        val chunk = raw?.let { MermaidRequestCodec.decodeChunk(it) }
        if (!assembler.accept(chunk, offset)) break
        offset += chunk?.length ?: 0
    }
    val dataUrl = assembler.assembledDataUrl()

    // 3. Limpieza SIEMPRE: el wrapper libera el payload al completar o abortar.
    evaluateJavascriptSafe(MermaidRequestCodec.buildClearExportInvocation(expectedExportId))

    if (dataUrl == null) {
        return MermaidPngExportResult(
            ok = false,
            transportFailure = true,
            exportId = expectedExportId,
            error = assembler.error ?: "Timeout reensamblando los trozos del PNG.",
        )
    }
    return MermaidPngExportResult(ok = true, png = dataUrl, exportId = expectedExportId)
}

/**
 * Polling del resultado del export SVG (`takeExportResult()`), con timeout
 * propio y correlación por `exportId`; el `null` final (timeout) es un fallo
 * visible de transporte.
 */
private suspend fun WebView.awaitSvgExportResult(expectedExportId: String): MermaidSvgExportResult? {
    val deadline = System.currentTimeMillis() + SVG_EXPORT_TIMEOUT_MS
    while (System.currentTimeMillis() < deadline) {
        // Mismo canal que el render: sin JSON.stringify() (ver
        // awaitRenderResult); el objeto viaja serializado por el propio canal.
        val raw = evaluateJavascriptAwait("window.ExplainerMermaid.takeExportResult();")
        val result = raw?.let { MermaidRequestCodec.decodeSvgExportResult(it) }
        if (MermaidResultCorrelation.matchesSvgExport(result, expectedExportId)) return result
        delay(RESULT_POLL_INTERVAL_MS)
    }
    return null
}

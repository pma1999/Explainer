package com.explainer.app.ui.content.mermaid

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Request de render para la WebView local (T08). El código Mermaid se
 * serializa como JSON por kotlinx-serialization y se pasa como argumento
 * objeto-literal a `window.ExplainerMermaid.render(...)`; nunca se concatena
 * como JavaScript sin escapar.
 *
 * @param code definición Mermaid (campo canónico `mermaid_code`, alias `code`).
 * @param theme `"light"` | `"dark"` (resuelto del tema T05).
 * @param renderId identificador único por invocación (evita colisiones del
 *   registro interno de Mermaid al re-renderizar).
 */
@Serializable
data class MermaidRenderRequest(
    val code: String,
    val theme: String,
    val renderId: String,
)

/** Resultado del render devuelto por el wrapper local como JSON. */
@Serializable
data class MermaidRenderResult(
    val ok: Boolean,
    val svg: String? = null,
    val error: String? = null,
    /** `renderId` del request que produjo este resultado (remediación R-T08-04). */
    val renderId: String? = null,
)

/**
 * Request de export PNG disparado por la UI (paridad web `_downloadPng`):
 * pide al wrapper local rasterizar el diagrama actual a un data URL PNG. El
 * `exportId` correlaciona el resultado del polling (canal independiente del
 * de render, [MermaidPngExportResult]).
 */
data class MermaidPngExportRequest(
    val exportId: String,
)

/** Resultado del export PNG devuelto por el wrapper local como JSON. */
@Serializable
data class MermaidPngExportResult(
    val ok: Boolean,
    /** Data URL `data:image/png;base64,…` del diagrama rasterizado. */
    val png: String? = null,
    val error: String? = null,
    /** `exportId` del request que produjo este resultado. */
    val exportId: String? = null,
    /**
     * `true` si el fallo fue del TRANSPORTE (timeout de metadatos, trozos
     * inválidos, longitud incompleta), no de la rasterización del wrapper.
     * Distingue el feedback de la UI (export T-EXPORT): transporte vs.
     * rasterización.
     */
    val transportFailure: Boolean = false,
)

/**
 * Request de export SVG (descarga `esquema.svg`): pide al wrapper local el
 * SVG NORMALIZADO (tema claro fijo, dimensiones numéricas, fondo blanco) por
 * el canal de export — nunca el `res.svg` de pantalla, que los visores
 * externos renderizaban negro/vacío.
 */
data class MermaidSvgExportRequest(
    val exportId: String,
)

/** Request de un trozo del PNG exportado: `takeExportPngChunk(exportId, offset)`. */
data class MermaidPngChunkRequest(
    val exportId: String,
    val offset: Int,
)

/**
 * Metadatos del export PNG (canal de chunks): el data URL completo NO viaja
 * en la respuesta de `takeExportResult()` — un payload de MBs en una sola
 * respuesta de `evaluateJavascript` se rompía/timeout. Primero llegan estos
 * metadatos y el payload se lee en trozos de [chunkSize] caracteres con
 * [MermaidPngChunkRequest], se reensambla en Kotlin y se valida contra
 * [totalLength].
 */
@Serializable
data class MermaidPngExportMeta(
    val ok: Boolean,
    /** Longitud total del data URL (caracteres), para validar el ensamblado. */
    val totalLength: Int? = null,
    /** Tamaño máximo de cada trozo (caracteres). */
    val chunkSize: Int? = null,
    val error: String? = null,
    /** `exportId` del request que produjo estos metadatos. */
    val exportId: String? = null,
)

/** Resultado del export SVG devuelto por el wrapper local como JSON. */
@Serializable
data class MermaidSvgExportResult(
    val ok: Boolean,
    /** SVG normalizado (nunca el `res.svg` de pantalla). */
    val svg: String? = null,
    val error: String? = null,
    /** `exportId` del request que produjo este resultado. */
    val exportId: String? = null,
)

/**
 * Estado visible del render para la UI del tab (remediación R-T08-01): un
 * resultado `null` (timeout de página, timeout de polling, WebView ausente o
 * excepción de evaluación) es un fallo visible — nunca un éxito — para
 * auto-revelar el código fuente y mostrar un estado accesible.
 */
enum class MermaidRenderStatus {
    /** SVG renderizado por el wrapper local. */
    RENDERED,

    /** El wrapper devolvió `{ok:false, error}` (p. ej. error de sintaxis). */
    FAILED,

    /** Sin resultado: timeout de página, timeout de polling, WebView ausente o excepción de evaluación. */
    UNAVAILABLE,
}

/** Clasifica el resultado del render para la UI; `null` nunca es éxito. */
fun MermaidRenderResult?.renderStatus(): MermaidRenderStatus = when {
    this == null -> MermaidRenderStatus.UNAVAILABLE
    ok -> MermaidRenderStatus.RENDERED
    else -> MermaidRenderStatus.FAILED
}

/**
 * Correlación resultado ↔ request por `renderId` (remediación R-T08-04): si
 * el código/tema cambia mientras un render sigue pendiente, el resultado del
 * render anterior no satisface el polling del render nuevo.
 */
object MermaidResultCorrelation {

    /** `true` solo si el resultado pertenece al request esperado. */
    fun matches(result: MermaidRenderResult?, renderId: String): Boolean =
        result != null && result.renderId == renderId

    /** `true` solo si el resultado de export pertenece al export esperado. */
    fun matchesExport(result: MermaidPngExportResult?, exportId: String): Boolean =
        result != null && result.exportId == exportId

    /** `true` solo si los metadatos de export pertenecen al export esperado. */
    fun matchesExportMeta(result: MermaidPngExportMeta?, exportId: String): Boolean =
        result != null && result.exportId == exportId

    /** `true` solo si el resultado del export SVG pertenece al export esperado. */
    fun matchesSvgExport(result: MermaidSvgExportResult?, exportId: String): Boolean =
        result != null && result.exportId == exportId
}

/**
 * Codec del contrato JSON de Mermaid (T08): empaqueta el request como JSON
 * válido para evaluar en la WebView y decodifica el resultado.
 *
 * Nota: un objeto JSON es un subconjunto estricto de las expresiones de
 * JavaScript, por lo que el payload puede incrustarse directamente como
 * argumento de función sin envolverlo en una string literal. Los separadores
 * de línea U+2028/U+2029 (válidos en JSON pero históricamente problemáticos
 * en código JS) se escapan explícitamente.
 */
object MermaidRequestCodec {

    private val json = Json { encodeDefaults = true }

    /** Payload JSON (objeto literal) del request, con separadores U+2028/29 escapados. */
    fun payload(request: MermaidRenderRequest): String =
        json.encodeToString(MermaidRenderRequest.serializer(), request)
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")

    /** Invocación completa evaluable por `evaluateJavascript` (sin concatenación de código). */
    fun buildInvocation(request: MermaidRenderRequest): String =
        "window.ExplainerMermaid.render(${payload(request)});"

    /**
     * Invocación del export PNG: `exportPng("<exportId>")`. El id se embarca
     * como string JSON (mismo escape que el request); el resultado viaja por
     * el canal de polling de export ([decodeExportResult]).
     */
    fun buildPngInvocation(request: MermaidPngExportRequest): String =
        "window.ExplainerMermaid.exportPng(${json.encodeToString(request.exportId)});"

    /**
     * Invocación del export SVG: `exportSvg("<exportId>")` — el SVG
     * NORMALIZADO viaja por el mismo canal de polling de export
     * ([decodeSvgExportResult]), correlacionado por exportId.
     */
    fun buildSvgExportInvocation(request: MermaidSvgExportRequest): String =
        "window.ExplainerMermaid.exportSvg(${json.encodeToString(request.exportId)});"

    /**
     * Invocación de un trozo del PNG: `takeExportPngChunk("<exportId>",
     * offset)`. El offset viaja como número JSON; cada trozo (~32 KB) queda
     * lejos del límite de transporte de `evaluateJavascript`.
     */
    fun buildChunkInvocation(request: MermaidPngChunkRequest): String =
        "window.ExplainerMermaid.takeExportPngChunk(${json.encodeToString(request.exportId)}, ${request.offset});"

    /**
     * Invocación de limpieza del payload del PNG:
     * `clearExportPayload("<exportId>")`. Kotlin la ejecuta SIEMPRE al
     * terminar el export (éxito, fallo o aborto) para liberar la memoria del
     * wrapper.
     */
    fun buildClearExportInvocation(exportId: String): String =
        "window.ExplainerMermaid.clearExportPayload(${json.encodeToString(exportId)});"

    /** `null` si el valor no es el JSON del resultado (p. ej. `null` de poll). */
    fun decodeResult(raw: String): MermaidRenderResult? = runCatching {
        json.decodeFromString(MermaidRenderResult.serializer(), raw)
    }.getOrNull()

    /** `null` si el valor no es el JSON del resultado de export (p. ej. `null` de poll). */
    fun decodeExportResult(raw: String): MermaidPngExportResult? = runCatching {
        json.decodeFromString(MermaidPngExportResult.serializer(), raw)
    }.getOrNull()

    /** `null` si el valor no es el JSON de los metadatos del export PNG. */
    fun decodePngExportMeta(raw: String): MermaidPngExportMeta? = runCatching {
        json.decodeFromString(MermaidPngExportMeta.serializer(), raw)
    }.getOrNull()

    /** `null` si el valor no es el JSON del resultado del export SVG. */
    fun decodeSvgExportResult(raw: String): MermaidSvgExportResult? = runCatching {
        json.decodeFromString(MermaidSvgExportResult.serializer(), raw)
    }.getOrNull()

    /**
     * Decodifica un trozo del PNG: `evaluateJavascript` entrega un string JS
     * como literal JSON con comillas (el canal ya codifica el valor), por lo
     * que se deserializa como string. `null` si el valor no es un string
     * (p. ej. `null` JS = fin de canal o id no coincide).
     */
    fun decodeChunk(raw: String): String? = runCatching {
        json.decodeFromString<String>(raw)
    }.getOrNull()
}

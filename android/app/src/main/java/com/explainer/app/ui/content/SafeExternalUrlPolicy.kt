package com.explainer.app.ui.content

import android.net.Uri
import androidx.core.net.toUri

/**
 * Política de URLs externas (T08, global-constraints "Recursos externos solo
 * abren URLs http/https"): el único contenido que sale de la app hacia una app
 * externa son enlaces `http`/`https` absolutos con autoridad y host válidos.
 * `javascript:`, `data:`, `file:`, `content:`, URLs sin autoridad (p. ej.
 * `http://`), host inválido y entradas con caracteres de control se rechazan
 * antes de tocar un UriHandler, por lo que ningún contenido generado se
 * ejecuta dentro de la app.
 *
 * La validación es una sola pasada pura sobre [java.net.URI]
 * ([safeExternalUriStringOrNull], testeable en JVM); [safeUriOrNull]
 * construye el `android.net.Uri` a partir del string ya validado, sin
 * re-validar con un método distinto (remediación R-T08-03).
 */
object SafeExternalUrlPolicy {

    /** `true` solo para URLs http/https absolutas con host válido. */
    fun isSafeExternal(url: String?): Boolean = safeExternalUriStringOrNull(url) != null

    /**
     * [Uri] seguro para abrir externamente, o `null` si la política lo
     * rechaza. Construido desde el string ya validado por
     * [safeExternalUriStringOrNull]; no revalida ni re-parsea la política.
     */
    fun safeUriOrNull(url: String?): Uri? =
        safeExternalUriStringOrNull(url)?.let { validated ->
            runCatching { validated.toUri() }.getOrNull()
        }

    /**
     * Validación pura (sin dependencias de Android, testeable en JVM):
     * devuelve el string canónico http/https absoluto con autoridad y host
     * válidos, o `null` si la política lo rechaza. Los composables despachan
     * exactamente este resultado validado.
     */
    internal fun safeExternalUriStringOrNull(url: String?): String? {
        if (url == null) return null
        val trimmed = url.trim()
        if (trimmed.isEmpty()) return null
        // Los caracteres de control nunca son válidos en una URL externa.
        if (trimmed.any { it.isISOControl() }) return null
        val uri = runCatching { java.net.URI(trimmed) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") return null
        val host = uri.host ?: return null
        // Autoridad/host válidos: no vacío, sin espacios/controles y con al
        // menos un carácter alfanumérico (rechaza ".", ":", "-", etc.).
        if (host.isBlank() || host.any { it.isWhitespace() || it.isISOControl() }) return null
        if (host.none { it.isLetterOrDigit() }) return null
        return uri.toString()
    }
}

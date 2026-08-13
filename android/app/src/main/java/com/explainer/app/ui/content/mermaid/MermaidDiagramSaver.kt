package com.explainer.app.ui.content.mermaid

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import androidx.annotation.RequiresApi

/**
 * Guardado del diagrama exportado (paridad web `_downloadSvg`/`_downloadPng`),
 * sin flujos de permisos runtime.
 *
 * API 29+: [saveToDownloads] escribe en Descargas vía MediaStore
 * (`RELATIVE_PATH`, sin permisos). API < 29: la UI usa `ACTION_CREATE_DOCUMENT`
 * (SAF) y escribe los bytes sobre el `Uri` elegido por el usuario.
 *
 * Los nombres de archivo son `esquema.svg`/`esquema.png`: el modelo de
 * presentación no expone el `partId` (la web usa `esquema-parte-{partId}.svg`).
 */
object MermaidDiagramSaver {

    /** Nombres de archivo por defecto. */
    const val SVG_FILE_NAME = "esquema.svg"
    const val PNG_FILE_NAME = "esquema.png"

    const val SVG_MIME = "image/svg+xml"
    const val PNG_MIME = "image/png"

    private const val PNG_DATA_URL_PREFIX = "data:image/png;base64,"

    /**
     * Decodifica el data URL del wrapper a bytes PNG; `null` si el valor no
     * es un PNG base64 válido.
     */
    fun decodePngDataUrl(dataUrl: String): ByteArray? =
        decodePngDataUrl(dataUrl) { raw ->
            runCatching { Base64.decode(raw, Base64.DEFAULT) }.getOrNull()
        }

    /**
     * Núcleo puro del decode (JVM-testable, sin `android.util.Base64`): valida
     * el prefijo del data URL y decodifica con el [base64Decode] inyectado
     * (que puede devolver `null` o lanzar con base64 inválido); `null` si el
     * prefijo no es un PNG o el base64 es inválido.
     */
    internal fun decodePngDataUrl(dataUrl: String, base64Decode: (String) -> ByteArray?): ByteArray? =
        if (dataUrl.startsWith(PNG_DATA_URL_PREFIX)) {
            runCatching { base64Decode(dataUrl.removePrefix(PNG_DATA_URL_PREFIX)) }.getOrNull()
        } else {
            null
        }

    /**
     * Guarda [bytes] en Descargas (MediaStore, API 29+, sin permisos). El
     * archivo se inserta como pendiente, se escribe y se confirma; `true`
     * solo si la escritura y la confirmación tuvieron éxito (un fallo limpia
     * la entrada insertada).
     */
    @RequiresApi(Build.VERSION_CODES.Q)
    fun saveToDownloads(context: Context, fileName: String, mimeType: String, bytes: ByteArray): Boolean {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
            put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri: Uri = runCatching {
            resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
        }.getOrNull() ?: return false
        val written = runCatching {
            resolver.openOutputStream(uri)?.use { out -> out.write(bytes) } != null
        }.getOrDefault(false)
        values.clear()
        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
        return if (written) {
            runCatching { resolver.update(uri, values, null, null) }.isSuccess
        } else {
            runCatching { resolver.delete(uri, null, null) }
            false
        }
    }
}

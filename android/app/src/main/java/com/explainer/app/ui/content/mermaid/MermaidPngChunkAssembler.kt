package com.explainer.app.ui.content.mermaid

/**
 * Reensambla los trozos base64 del PNG exportado (canal de chunks T-EXPORT):
 * el wrapper sirve el data URL completo en trozos de ~32 KB por
 * `takeExportPngChunk(exportId, offset)` y Kotlin los une aquí, validando el
 * contrato en cada paso: offsets contiguos desde 0, cada trozo dentro del
 * tamaño declarado, longitud total exacta y prefijo `data:image/png;base64,`
 * en el primer trozo. Cualquier violación marca un error de transporte
 * (feedback diferenciado de la UI, nunca un PNG corrupto).
 *
 * @param exportId id del export esperado (los trozos de otro export devuelven
 *   `null` en el canal y se rechazan aquí como canal terminado).
 * @param totalLength longitud total declarada por los metadatos del wrapper.
 * @param chunkSize tamaño máximo de cada trozo declarado por los metadatos.
 */
class MermaidPngChunkAssembler(
    private val exportId: String,
    private val totalLength: Int,
    private val chunkSize: Int,
) {

    private val parts = ArrayList<String>()
    private var received = 0

    /** Error de transporte (primera violación del contrato); `null` si todo va bien. */
    var error: String? = null
        private set

    /** `true` solo si el ensamblado terminó sin error y con la longitud exacta. */
    val isComplete: Boolean
        get() = error == null && totalLength > 0 && received == totalLength

    /**
     * Acepta el trozo de [offset]. `null` (fin de canal o id no coincide) o
     * cualquier violación del contrato marca un error de transporte y el
     * ensamblado queda abortado.
     */
    fun accept(chunk: String?, offset: Int): Boolean {
        if (error != null) return false
        if (totalLength <= 0 || chunkSize <= 0) {
            error = "Metadatos del export PNG inválidos (total=$totalLength, chunk=$chunkSize)."
            return false
        }
        if (chunk == null) {
            error = "El canal de trozos terminó antes de completar el PNG (export $exportId)."
            return false
        }
        if (offset != received) {
            error = "Offset de trozo inesperado (esperado $received, recibido $offset)."
            return false
        }
        if (chunk.length > chunkSize) {
            error = "Trozos mayores que el tamaño declarado ($chunkSize)."
            return false
        }
        if (received + chunk.length > totalLength) {
            error = "Los trozos exceden la longitud declarada ($totalLength)."
            return false
        }
        if (offset == 0 && !chunk.startsWith(PNG_DATA_URL_PREFIX)) {
            error = "El primer trozo no empieza por el prefijo del data URL PNG."
            return false
        }
        parts.add(chunk)
        received += chunk.length
        return true
    }

    /**
     * Data URL completo (`data:image/png;base64,…`) si el ensamblado terminó;
     * `null` con [error] si falta longitud o hubo una violación del contrato.
     */
    fun assembledDataUrl(): String? {
        if (error != null) return null
        if (!isComplete) {
            error = "Longitud incompleta (recibidos $received de $totalLength)."
            return null
        }
        return parts.joinToString("")
    }

    companion object {
        /** Prefijo exacto del data URL PNG servido por el wrapper. */
        const val PNG_DATA_URL_PREFIX = "data:image/png;base64,"
    }
}

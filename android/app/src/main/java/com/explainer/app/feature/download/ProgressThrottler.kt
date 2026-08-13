package com.explainer.app.feature.download

/**
 * Throttler puro del progreso (global-constraints.md): la emisión/escritura
 * de bytes se limita a máximo 4 Hz (250 ms) O cada 256 KiB — el primero de
 * los dos umbrales que se cruce permite emitir — de modo que nunca se escribe
 * Room por cada chunk de red. Las transiciones y el valor final los emite
 * siempre el motor, no este throttler.
 */
class ProgressThrottler(
    private val nowMillis: () -> Long,
) {
    private var lastEmitMillis: Long? = null
    private var lastEmittedBytes: Long = 0L

    /**
     * Devuelve `true` si este valor de bytes debe emitirse: primera llamada,
     * o han pasado [MIN_INTERVAL_MILLIS] o se acumularon [MIN_BYTES_DELTA]
     * desde la última emisión. Actualiza el estado interno al emitir.
     */
    fun forward(downloadedBytes: Long): Boolean {
        val now = nowMillis()
        val timeElapsed = lastEmitMillis == null || now - lastEmitMillis!! >= MIN_INTERVAL_MILLIS
        val bytesAccumulated = downloadedBytes - lastEmittedBytes >= MIN_BYTES_DELTA
        if (!timeElapsed && !bytesAccumulated) return false
        lastEmitMillis = now
        lastEmittedBytes = downloadedBytes
        return true
    }

    companion object {
        /** 4 Hz. */
        const val MIN_INTERVAL_MILLIS: Long = 250L

        /** 256 KiB binarios. */
        const val MIN_BYTES_DELTA: Long = 256L * 1024
    }
}

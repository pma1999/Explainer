package com.explainer.app.feature.download

/**
 * Estimador puro de tamaño (plan.md §6): sin endpoint HEAD, el preflight es
 * heurístico a partir de los bytes UTF-8 de `segmentation.partes[].contenido`
 * (calculados por el mapper de lista en T07 y persistidos como
 * `segmentation_source_bytes`). Multiplicadores 2x (bajo) y 6x (alto) con
 * suelo de 1 MiB binario; todas las operaciones saturan en Long.MAX_VALUE
 * para nunca desbordar.
 *
 * Cuando llega `Content-Length` se sustituye el rango por el total
 * ([fromContentLength], HEADER) y cuando los bytes escritos verifican el
 * header el total pasa a EXACT ([verified]).
 */
object SizeEstimator {

    /** Suelo del rango heurístico: 1 MiB binario. */
    const val FLOOR_BYTES: Long = 1L * 1024 * 1024

    const val LOW_MULTIPLIER: Long = 2L
    const val HIGH_MULTIPLIER: Long = 6L

    /**
     * Rango HEURISTIC desde los bytes de segmentation. [currentSnapshotBytes]
     * (tamaño exacto del snapshot activo) se propaga solo informativo.
     */
    fun fromSegmentation(
        segmentationBytes: Long,
        currentSnapshotBytes: Long? = null,
    ): SizeEstimate {
        val low = maxOf(FLOOR_BYTES, saturatingMultiply(segmentationBytes, LOW_MULTIPLIER))
        val high = maxOf(FLOOR_BYTES, saturatingMultiply(segmentationBytes, HIGH_MULTIPLIER))
        return SizeEstimate(
            lowBytes = low,
            highBytes = high,
            confidence = SizeConfidence.HEURISTIC,
            currentSnapshotBytes = currentSnapshotBytes,
        )
    }

    /** Total declarado por `Content-Length` (aún sin verificar bytes). */
    fun fromContentLength(contentLength: Long): SizeEstimate =
        SizeEstimate(contentLength, contentLength, SizeConfidence.HEADER)

    /** Total EXACTO: bytes escritos == `Content-Length`. */
    fun verified(receivedBytes: Long): SizeEstimate =
        SizeEstimate(receivedBytes, receivedBytes, SizeConfidence.EXACT)

    private fun saturatingMultiply(a: Long, b: Long): Long =
        if (a == 0L || b == 0L) {
            0L
        } else if (a > Long.MAX_VALUE / b) {
            Long.MAX_VALUE
        } else {
            a * b
        }
}

package com.explainer.app.feature.download

/**
 * Rango preflight de tamaño, SIEMPRE rotulado por [confidence]:
 *
 * - [SizeConfidence.HEURISTIC]: derivado de los bytes UTF-8 de
 *   `segmentation.partes[].contenido` (2x–6x, suelo 1 MiB). Es una
 *   aproximación y jamás debe presentarse como exacta.
 * - [SizeConfidence.HEADER]: `Content-Length` recibida (aún no verificada
 *   contra los bytes escritos).
 * - [SizeConfidence.EXACT]: bytes recibidos == `Content-Length` (total real).
 *
 * [currentSnapshotBytes] es el tamaño EXACTO del snapshot activo actual
 * (solo informativo; la UI muestra "actual" junto al rango estimado).
 */
data class SizeEstimate(
    val lowBytes: Long,
    val highBytes: Long,
    val confidence: SizeConfidence,
    val currentSnapshotBytes: Long? = null,
)

enum class SizeConfidence {
    HEURISTIC,
    HEADER,
    EXACT,
}

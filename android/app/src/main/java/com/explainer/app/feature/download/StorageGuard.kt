package com.explainer.app.feature.download

/**
 * Guardián de espacio puro (global-constraints.md): se reserva al menos
 * `2 * bytesEsperados + 32 MiB` (binario) para temporal + Room/WAL + margen.
 *
 * - Sin `Content-Length` se usa el límite superior del rango estimado
 *   ([SizeEstimate.highBytes]) y se vigila el espacio durante el stream.
 * - Con `Content-Length` se recalcula sobre el total real.
 * - [sufficientSpace] aplica la reserva a los bytes RESTANTES, de modo que
 *   la misma regla sirve de preflight (received=0) y de vigilancia durante
 *   el stream. Un fallo por espacio nunca borra la versión anterior.
 *
 * Todo aritmética satura en Long.MAX_VALUE (sin overflow).
 */
object StorageGuard {

    const val RESERVE_MULTIPLIER: Long = 2L

    /** Margen fijo: 32 MiB binarios (temporal remanente, WAL, checkpoint). */
    const val RESERVE_MARGIN_BYTES: Long = 32L * 1024 * 1024

    /** `2 * expectedBytes + 32 MiB`, saturado. */
    fun requiredFreeBytes(expectedBytes: Long): Long {
        val remaining = expectedBytes.coerceAtLeast(0L)
        val reserved = saturatingMultiply(remaining, RESERVE_MULTIPLIER)
        return if (reserved > Long.MAX_VALUE - RESERVE_MARGIN_BYTES) {
            Long.MAX_VALUE
        } else {
            reserved + RESERVE_MARGIN_BYTES
        }
    }

    /**
     * ¿Cabe? La reserva se aplica sobre lo que falta por recibir:
     * `free >= 2*(expected - received) + 32 MiB` (received=0 ⇒ preflight).
     */
    fun sufficientSpace(
        freeBytes: Long,
        expectedBytes: Long,
        receivedBytes: Long = 0L,
    ): Boolean {
        val remaining = (expectedBytes - receivedBytes).coerceAtLeast(0L)
        return freeBytes >= requiredFreeBytes(remaining)
    }

    private fun saturatingMultiply(a: Long, b: Long): Long =
        if (a == 0L || b == 0L) {
            0L
        } else if (a > Long.MAX_VALUE / b) {
            Long.MAX_VALUE
        } else {
            a * b
        }
}

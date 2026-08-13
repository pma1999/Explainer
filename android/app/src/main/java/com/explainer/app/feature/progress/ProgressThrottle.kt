package com.explainer.app.feature.progress

import java.util.concurrent.ConcurrentHashMap

/**
 * Regulador del intervalo mínimo entre flushes de progreso (paridad
 * `lastFlushAt` de `frontend/js/progressSync.js`: 15 s debounce y 60 s
 * mínimo). Compartido por el repositorio (delay de encolado) y el
 * coordinador del worker (salto sin red si el intervalo no transcurrió).
 *
 * R-T07-09: el reloj es SEPARADO por owner — un flush de A nunca retrasa la
 * cola de B. No es durable a propósito: es un rate-limit de red, no una
 * garantía; un reinicio del proceso solo permite un flush antes de tiempo,
 * nunca pérdida (la cola durable Room sigue intacta).
 */
class ProgressThrottle(
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val lastFlushAtByOwner = ConcurrentHashMap<String, Long>()

    fun nowMillis(): Long = clock()

    /** 0 si ya se puede transmitir; si no, millis restantes del intervalo. */
    fun remainingToMinInterval(ownerId: String, minIntervalMs: Long): Long {
        val last = lastFlushAtByOwner[ownerId] ?: 0L
        if (last <= 0L) return 0L
        val elapsed = clock() - last
        return if (elapsed >= minIntervalMs) 0L else minIntervalMs - elapsed
    }

    fun recordFlush(ownerId: String, now: Long = clock()) {
        lastFlushAtByOwner[ownerId] = now
    }

    internal fun lastFlushAtMillis(ownerId: String): Long = lastFlushAtByOwner[ownerId] ?: 0L
}

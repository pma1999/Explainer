package com.explainer.app.feature.progress

import com.explainer.app.core.model.ReaderTab

/**
 * Tracker puro de actividad de subsecciones (paridad web
 * `frontend/js/main.js` setActiveSubsection/maybeMarkSubsectionRead):
 * - `activate` emite el last-read de la subsección nueva al activarse.
 * - Al salir (cambio de subsección o `finish`), la subsección anterior emite
 *   `completed` si acumuló >= [thresholdMs] de visita.
 * - Visitas no contiguas suman por id (acumulador de sesión, como la web).
 * - Reactivar el mismo id no emite nada (sigue acumulando).
 *
 * No depende de Android ni de viewport events: T10 decide qué eventos de
 * viewport alimentan `activate`/`finish`.
 */
class SubsectionActivityTracker(
    private val thresholdMs: Long = DEFAULT_THRESHOLD_MS,
) {
    private var currentId: String? = null
    private var currentPartId: Int = 0
    private var currentTab: ReaderTab = ReaderTab.EXPLANATION
    private var activatedAtMs: Long = 0L
    private val accumulatedMs = mutableMapOf<String, Long>()

    /** Activa una subsección; devuelve los eventos a registrar (0..2). */
    fun activate(id: String, partId: Int, tab: ReaderTab, now: Long): List<SubsectionProgressEvent> {
        require(partId > 0) { "partId debe ser positivo" }
        if (currentId == id) return emptyList()

        val events = mutableListOf<SubsectionProgressEvent>()
        currentId?.let { previous ->
            val total = (accumulatedMs[previous] ?: 0L) + (now - activatedAtMs)
            accumulatedMs[previous] = total
            if (total >= thresholdMs) {
                events += SubsectionProgressEvent(
                    partId = currentPartId,
                    subsectionId = previous,
                    tab = currentTab,
                    completed = true,
                )
            }
        }

        currentId = id
        currentPartId = partId
        currentTab = tab
        activatedAtMs = now
        events += SubsectionProgressEvent(
            partId = partId,
            subsectionId = id,
            tab = tab,
            isLastRead = true,
        )
        return events
    }

    /** Cierra la sesión de actividad; devuelve el completed pendiente, si aplica. */
    fun finish(now: Long): List<SubsectionProgressEvent> {
        val current = currentId ?: return emptyList()
        val total = (accumulatedMs[current] ?: 0L) + (now - activatedAtMs)
        accumulatedMs[current] = total
        currentId = null
        return if (total >= thresholdMs) {
            listOf(
                SubsectionProgressEvent(
                    partId = currentPartId,
                    subsectionId = current,
                    tab = currentTab,
                    completed = true,
                ),
            )
        } else {
            emptyList()
        }
    }

    companion object {
        /** Umbral web replicado: 3 s acumulados para marcar leída. */
        const val DEFAULT_THRESHOLD_MS = 3_000L
    }
}

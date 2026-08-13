package com.explainer.app.core.model

import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * Política pura de merge de progreso (sin dependencias Android):
 * `merge(remote, local, pending)`.
 *
 * - Completadas (partes y subsecciones): unión de remote ∪ local ∪ pending.
 * - Tombstones explícitos (`uncompleted*` de pending): ganan sobre la unión.
 * - `last_subsection`: la fuente con `last_read_at` más reciente; empate de
 *   instante resuelto por prioridad pending > local > remote (determinista).
 * - Timestamps ISO-8601 se comparan con parse seguro; un valor inválido se
 *   trata como antiguo (Instant.MIN) y nunca produce crash.
 */
object ReadingProgressMergePolicy {

    private data class Source(
        val lastReadAt: String?,
        val lastSubsection: LastSubsection?,
        val priority: Int,
    )

    fun merge(
        remote: ReadingProgress,
        local: ReadingProgress? = null,
        pending: PendingProgressOverlay? = null,
    ): ReadingProgress {
        val completedParts = (remote.completedParts
            + (local?.completedParts.orEmpty())
            + (pending?.completedParts.orEmpty()))
            .minus(pending?.uncompletedParts.orEmpty())
            .sorted()
            .toSet()
        val completedSubsections = (remote.completedSubsections
            + (local?.completedSubsections.orEmpty())
            + (pending?.completedSubsections.orEmpty()))
            .minus(pending?.uncompletedSubsections.orEmpty())
            .sorted()
            .toSet()

        val sources = listOfNotNull(
            pending?.let { Source(it.lastReadAt, it.lastSubsection, priority = 0) },
            local?.let { Source(it.lastReadAt, it.lastSubsection, priority = 1) },
            Source(remote.lastReadAt, remote.lastSubsection, priority = 2),
        ).filter { it.lastReadAt != null }

        val best = sources.maxWithOrNull(
            compareBy<Source> { parseInstantOrNull(it.lastReadAt) ?: Instant.MIN }
                .thenByDescending { it.priority },
        )
        val fallbackSubsection = if (best?.lastSubsection == null) {
            listOfNotNull(
                pending?.lastSubsection,
                local?.lastSubsection,
                remote.lastSubsection,
            ).firstOrNull()
        } else {
            null
        }

        return ReadingProgress(
            completedParts = completedParts,
            completedSubsections = completedSubsections,
            lastReadAt = best?.lastReadAt,
            lastSubsection = best?.lastSubsection ?: fallbackSubsection,
        )
    }

    private fun parseInstantOrNull(raw: String?): Instant? = try {
        if (raw.isNullOrBlank()) null else Instant.parse(raw)
    } catch (_: DateTimeParseException) {
        null
    }
}

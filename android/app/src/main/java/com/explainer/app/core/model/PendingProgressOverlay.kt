package com.explainer.app.core.model

/**
 * Operaciones de progreso locales aún no confirmadas por el servidor
 * (overlay optimista). Las listas `uncompleted*` son tombstones explícitos:
 * ganan sobre cualquier completada remota/local. `lastSubsection` y
 * `lastReadAt` viajan juntos; el merge decide por `last_read_at` más reciente.
 */
data class PendingProgressOverlay(
    val completedParts: Set<Int> = emptySet(),
    val uncompletedParts: Set<Int> = emptySet(),
    val completedSubsections: Set<String> = emptySet(),
    val uncompletedSubsections: Set<String> = emptySet(),
    val lastSubsection: LastSubsection? = null,
    val lastReadAt: String? = null,
)

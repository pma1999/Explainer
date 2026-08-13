package com.explainer.app.core.model

/** Última subsección leída según `reading_progress.last_subsection`. */
data class LastSubsection(
    val partId: Int,
    val subsectionId: String,
    val tab: ReaderTab,
)

/**
 * Progreso de lectura remoto/local. Los sets son la forma canónica del
 * dominio: el merge hace unión de completadas y tombstones explícitos.
 */
data class ReadingProgress(
    val completedParts: Set<Int> = emptySet(),
    val completedSubsections: Set<String> = emptySet(),
    val lastSubsection: LastSubsection? = null,
    /** ISO-8601 (UTC). Se compara con parse seguro, nunca lexicográfico. */
    val lastReadAt: String? = null,
)

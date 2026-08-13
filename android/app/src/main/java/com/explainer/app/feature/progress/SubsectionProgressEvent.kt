package com.explainer.app.feature.progress

import com.explainer.app.core.model.ReaderTab

/**
 * Evento de actividad de subsección emitido por el tracker (T10) o por la UI.
 * - `completed != null`: marcar/desmarcar (false = tombstone explícito).
 * - `isLastRead`: la subsección es el objetivo de reanudación actual.
 * Ambos pueden llegar juntos (dos filas de cola, keys distintas).
 * `subsectionId` DEBE tener la forma `subsec-{partId}-...` (validación del
 * backend `project_progress.py`); el repositorio lo valida antes de encolar.
 */
data class SubsectionProgressEvent(
    val partId: Int,
    val subsectionId: String,
    val tab: ReaderTab = ReaderTab.EXPLANATION,
    val completed: Boolean? = null,
    val isLastRead: Boolean = false,
)

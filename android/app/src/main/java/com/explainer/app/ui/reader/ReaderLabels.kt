package com.explainer.app.ui.reader

import androidx.annotation.StringRes
import com.explainer.app.R
import com.explainer.app.core.model.PartStatus
import com.explainer.app.feature.generation.GenerationFailureReason

/**
 * Labels del lector (T10/T14): cada estado de parte y cada razón de fallo de
 * generación tiene copia textual explícita (nunca solo color,
 * global-constraints.md UX). Copy en `strings_reader.xml`; los
 * títulos/estados compartidos de T05/T08 (tabs, contenido ausente) se
 * reutilizan sin duplicar.
 */
object ReaderLabels {

    /** Estado de una parte ya observado; `Unknown` → sin etiqueta (no se muestra). */
    @StringRes
    fun partStatusLabelRes(status: PartStatus): Int? = when (status) {
        is PartStatus.Pending -> R.string.reader_part_status_pending
        is PartStatus.Processing -> R.string.reader_part_status_processing
        is PartStatus.Completed -> R.string.reader_part_status_completed
        is PartStatus.Failed -> R.string.reader_part_status_failed
        is PartStatus.Unknown -> null
    }

    /**
     * Mensaje accionable de una [GenerationFailureReason] (T14). Cada razón
     * mapea a copy breve y accionable; nunca expone detalles del servidor.
     */
    @StringRes
    fun generationFailureMessageRes(reason: GenerationFailureReason): Int = when (reason) {
        GenerationFailureReason.OFFLINE -> R.string.generation_failure_offline
        GenerationFailureReason.AUTH -> R.string.generation_failure_auth
        GenerationFailureReason.PERMISSION -> R.string.generation_failure_permission
        GenerationFailureReason.NOT_FOUND -> R.string.generation_failure_not_found
        GenerationFailureReason.RATE_LIMITED -> R.string.generation_failure_rate_limited
        GenerationFailureReason.INVALID -> R.string.generation_failure_invalid
        GenerationFailureReason.UNKNOWN -> R.string.generation_failure_unknown
    }
}

package com.explainer.app.feature.progress

import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.local.db.PendingProgressEntity
import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * Confirmación de filas ACKNOWLEDGED contra el progreso remoto (lista o
 * detalle): una fila solo se elimina cuando el remoto refleja el valor
 * deseado. Conservadora por diseño: timestamps inválidos o ausentes NUNCA
 * confirman (dejar una fila de más es inofensivo; borrar un ack prematuro
 * podría reintroducir progreso stale).
 */
object ProgressConfirmation {

    fun isConfirmed(remote: ReadingProgress, row: PendingProgressEntity): Boolean = when {
        row.kindTarget == PendingProgressEntity.KIND_SECTION -> when (row.desiredCompleted) {
            true -> row.partId in remote.completedParts
            false -> row.partId !in remote.completedParts
            null -> false
        }

        row.kindTarget.startsWith(PendingProgressEntity.KIND_SUBSECTION_PREFIX) -> {
            val id = row.kindTarget.removePrefix(PendingProgressEntity.KIND_SUBSECTION_PREFIX)
            when (row.desiredCompleted) {
                true -> id in remote.completedSubsections
                false -> id !in remote.completedSubsections
                null -> false
            }
        }

        row.kindTarget == PendingProgressEntity.KIND_LAST_READ -> {
            val last = remote.lastSubsection ?: return false
            val remoteAt = parseInstantOrNull(remote.lastReadAt) ?: return false
            val rowAt = parseInstantOrNull(row.lastReadAt) ?: return false
            last.partId == row.partId &&
                last.subsectionId == row.lastSubsectionId &&
                last.tab.wireName == row.tab &&
                remoteAt >= rowAt
        }

        else -> false
    }

    private fun parseInstantOrNull(raw: String?): Instant? = try {
        if (raw.isNullOrBlank()) null else Instant.parse(raw)
    } catch (_: DateTimeParseException) {
        null
    }
}

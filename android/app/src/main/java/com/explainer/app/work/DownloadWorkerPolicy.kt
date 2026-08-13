package com.explainer.app.work

import androidx.work.Data
import androidx.work.ListenableWorker.Result
import com.explainer.app.core.model.ProjectId
import com.explainer.app.feature.download.DownloadOutcome

/**
 * Política pura del Worker (testeable en JVM sin instanciar WorkManager):
 * parseo del input (`owner_id`, `project_id` — solo IDs pequeños en `Data`)
 * y traducción del outcome del motor a [Result].
 *
 * Cancelado no es fallo: el coordinador ya marcó la fila antes de cancelar y
 * WorkManager no reintenta un trabajo cancelado; `retry()` solo para
 * red/timeout/429/5xx con intentos restantes (el quinto intento es final).
 */
object DownloadWorkerPolicy {

    data class ParsedInput(
        val ownerId: String,
        val projectId: ProjectId,
    )

    /** Input inválido (keys ausentes o projectId no UUID) → null. */
    fun parseInput(data: Data): ParsedInput? {
        val ownerId = data.getString(DownloadProjectWorker.KEY_OWNER_ID) ?: return null
        val projectRaw = data.getString(DownloadProjectWorker.KEY_PROJECT_ID) ?: return null
        val projectId = ProjectId.parse(projectRaw) ?: return null
        return ParsedInput(ownerId, projectId)
    }

    fun resultFor(outcome: DownloadOutcome): Result = when (outcome) {
        is DownloadOutcome.Succeeded -> Result.success()
        is DownloadOutcome.Cancelled -> Result.success()
        is DownloadOutcome.Retryable -> Result.retry()
        is DownloadOutcome.Failed -> Result.failure()
    }
}

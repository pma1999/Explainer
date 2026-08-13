package com.explainer.app.feature.download

import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.workDataOf
import com.explainer.app.core.model.ProjectId
import com.explainer.app.work.DownloadProjectWorker
import java.util.concurrent.TimeUnit

/**
 * Constructor del request de descarga (global-constraints.md):
 * - trabajo normal (nunca foreground, sin notificaciones);
 * - `NetworkType.CONNECTED` y backoff exponencial desde 30 s;
 * - tags de owner/proyecto;
 * - `Data` SOLO con los IDs pequeños (`owner_id`, `project_id`): WorkManager
 *   no se usa como transporte de blobs.
 */
class DownloadWorkRequestFactory {

    fun build(ownerId: String, projectId: ProjectId): OneTimeWorkRequest {
        val input: Data = workDataOf(
            DownloadProjectWorker.KEY_OWNER_ID to ownerId,
            DownloadProjectWorker.KEY_PROJECT_ID to projectId.value,
        )
        return OneTimeWorkRequest.Builder(DownloadProjectWorker::class.java)
            .setInputData(input)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                DownloadRetryPolicy.INITIAL_BACKOFF_MILLIS,
                TimeUnit.MILLISECONDS,
            )
            .addTag(DownloadWorkNames.ownerTag(ownerId))
            .addTag(DownloadWorkNames.projectTag(projectId))
            .build()
    }
}

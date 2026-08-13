package com.explainer.app.feature.progress

import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.explainer.app.work.ProgressSyncWorker
import java.util.concurrent.TimeUnit

/**
 * Puerto del encolado del worker de sync (inyectable para tests JVM sin
 * WorkManager). El debounce de 15 s y el intervalo mínimo de 60 s los
 * calcula el repositorio con el [ProgressThrottle] compartido.
 */
interface ProgressSyncScheduler {
    fun schedule(ownerId: String, delayMs: Long)
}

/**
 * Implementación WorkManager: trabajo único por owner
 * `progress-sync:<ownerId>` con REPLACE (cada nuevo evento reinicia el
 * debounce de 15 s), constraint de red conectada y backoff exponencial
 * desde 30 s. `Data` solo lleva el owner_id (sin blobs).
 */
class WorkManagerProgressSyncScheduler(
    private val workManager: WorkManager,
) : ProgressSyncScheduler {

    override fun schedule(ownerId: String, delayMs: Long) {
        val request = OneTimeWorkRequestBuilder<ProgressSyncWorker>()
            .setInputData(workDataOf(ProgressSyncWorker.KEY_OWNER_ID to ownerId))
            .setInitialDelay(delayMs, TimeUnit.MILLISECONDS)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        workManager.enqueueUniqueWork(
            ProgressSyncWorker.uniqueName(ownerId),
            ExistingWorkPolicy.REPLACE,
            request,
        )
    }
}

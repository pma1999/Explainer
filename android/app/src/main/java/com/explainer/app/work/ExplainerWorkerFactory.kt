package com.explainer.app.work

import android.content.Context
import androidx.work.ListenableWorker
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters

/**
 * Custom WorkerFactory de la app (T11): construye exactamente los DOS
 * workers del plan con dependencias inyectadas desde el AppContainer.
 *
 * - WorkManager se configura en `ExplainerApplication` con esta factory; el
 *   initializer por defecto de AndroidX Startup se elimina del manifest, de
 *   modo que NO existe ningún service locator global mutable ni Hilt.
 * - Las dependencias se construyen UNA vez en el composition root; nunca
 *   dentro de `doWork`.
 * - Cualquier clase desconocida devuelve `null` (WorkManager delega en su
 *   fallback por defecto, que hoy no tiene candidatos).
 */
class ExplainerWorkerFactory(
    private val downloadDeps: DownloadWorkerDeps,
    private val progressDeps: ProgressWorkerDeps,
) : WorkerFactory() {

    override fun createWorker(
        appContext: Context,
        workerClassName: String,
        workerParameters: WorkerParameters,
    ): ListenableWorker? = when (workerClassName) {
        DownloadProjectWorker::class.java.name ->
            DownloadProjectWorker(appContext, workerParameters, downloadDeps)

        ProgressSyncWorker::class.java.name ->
            ProgressSyncWorker(appContext, workerParameters, progressDeps)

        else -> null
    }
}

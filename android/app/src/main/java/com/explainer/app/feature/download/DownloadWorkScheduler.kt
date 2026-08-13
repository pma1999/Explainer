package com.explainer.app.feature.download

import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequest
import androidx.work.WorkManager

/**
 * Fachada mínima sobre WorkManager para el coordinador (inyectable en JVM).
 * `enqueueUnique` usa SIEMPRE [ExistingWorkPolicy.KEEP]: un trabajo único
 * activo nunca se duplica; cuando el anterior terminó, KEEP inserta el nuevo.
 */
interface DownloadWorkScheduler {
    fun enqueueUnique(name: String, request: OneTimeWorkRequest)
    fun cancelUnique(name: String)
}

/** Adaptador de producción sobre [WorkManager] (lo cablea T11). */
class WorkManagerDownloadScheduler(
    private val workManager: WorkManager,
) : DownloadWorkScheduler {

    override fun enqueueUnique(name: String, request: OneTimeWorkRequest) {
        workManager.enqueueUniqueWork(name, ExistingWorkPolicy.KEEP, request)
    }

    override fun cancelUnique(name: String) {
        workManager.cancelUniqueWork(name)
    }
}

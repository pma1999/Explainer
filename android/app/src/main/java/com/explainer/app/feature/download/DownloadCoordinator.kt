package com.explainer.app.feature.download

import com.explainer.app.core.model.ProjectId
import kotlinx.coroutines.flow.Flow

/**
 * Puerto de coordinación de descargas (contrato exacto del brief T06).
 * Todo acceso es owner-scoped: si el owner de sesión no coincide con el
 * [ownerId] pedido, [observe] no emite nada y [enqueue] devuelve
 * [EnqueueResult.InvalidOwner] sin encolar trabajo.
 */
interface DownloadCoordinator {
    fun observe(ownerId: String, projectId: ProjectId): Flow<DownloadState>
    suspend fun enqueue(ownerId: String, projectId: ProjectId): EnqueueResult
    suspend fun cancel(ownerId: String, projectId: ProjectId)
    suspend fun deleteLocal(ownerId: String, projectId: ProjectId)
}

sealed interface EnqueueResult {
    /** Trabajo único encolado (o KEEP no-op porque el anterior seguía vivo). */
    data object Enqueued : EnqueueResult

    /** Ya hay una descarga activa para este proyecto: no se duplica. */
    data object AlreadyActive : EnqueueResult

    /** Owner inválido o de otra sesión: nada se encola ni se observa. */
    data object InvalidOwner : EnqueueResult

    /**
     * WorkManager rechazó el trabajo (no inicializado, etc.): la fila Queued
     * recién creada se reconcilió (borrada) para no dejar estado sin trabajo.
     */
    data object EnqueueFailed : EnqueueResult
}

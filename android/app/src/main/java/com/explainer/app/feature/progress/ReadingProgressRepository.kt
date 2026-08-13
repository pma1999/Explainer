package com.explainer.app.feature.progress

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ReadingProgress
import kotlinx.coroutines.flow.Flow

/**
 * Puerto del progreso de lectura (T07, consumido por T09/T10): local primero,
 * cola durable coalescida por proyecto/parte/tab y sync por WorkManager.
 * `observe` superpone el overlay optimista (PENDING + ACKNOWLEDGED) al
 * progreso remoto/local; un fallo de red o 401 nunca descarta la intención.
 */
interface ReadingProgressRepository {
    fun observe(ownerId: String, projectId: ProjectId): Flow<ReadingProgress>

    /** Marca/desmarca una parte completa; persiste la operación coalescida. */
    suspend fun setSectionCompleted(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        completed: Boolean,
    )

    /** Registra actividad de subsección (last-read y/o completada). */
    suspend fun recordSubsection(
        ownerId: String,
        projectId: ProjectId,
        event: SubsectionProgressEvent,
    )

    /** Encola el worker único de sync (debounce 15 s; mínimo 60 s entre flushes). */
    suspend fun requestSync(ownerId: String)
}

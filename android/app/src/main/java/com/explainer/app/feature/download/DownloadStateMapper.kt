package com.explainer.app.feature.download

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.snapshot.OfflineProjectManifest
import com.explainer.app.data.local.snapshot.SnapshotDescriptor

/**
 * Mapeo puro `DownloadStateEntity` ↔ `DownloadState` (T06). La entidad es la
 * fuente durable (la UI observa el flow del DAO); el estado de dominio es la
 * forma estable que consumen coordinador/Worker/UI.
 */
object DownloadStateMapper {

    /**
     * Entidad → estado observable. Para [DownloadState.Succeeded] se usa el
     * [descriptor] resuelto desde el manifest (generación/timestamps reales);
     * si no hay manifest disponible se reconstruye un descriptor mínimo con
     * `generation = ""` (documentado: la fila no guarda la generación).
     */
    fun fromEntity(
        entity: DownloadStateEntity,
        projectId: ProjectId,
        descriptor: SnapshotDescriptor? = null,
    ): DownloadState = when (entity.state) {
        DownloadStateEntity.STATE_QUEUED -> DownloadState.Queued(projectId, entity.requestedAt)
        DownloadStateEntity.STATE_DOWNLOADING -> {
            // R-T06-08 (decisión de plan, sin cambio de schema): la entidad
            // durable solo guarda bytes/total, y la confianza EXACT solo
            // existe en el stream en vivo (bytes verificados contra el
            // header). Tras reinicio, un total en curso se representa SIEMPRE
            // como grado cabecera (HEADER), nunca "exacto"; sin total no hay
            // estimación.
            val estimate = entity.totalBytes?.let { SizeEstimator.fromContentLength(it) }
            DownloadState.Downloading(entity.downloadedBytes, entity.totalBytes, estimate)
        }
        DownloadStateEntity.STATE_PREPARING -> DownloadState.Preparing(projectId)
        DownloadStateEntity.STATE_COMMITTING -> DownloadState.Committing(projectId)
        DownloadStateEntity.STATE_SUCCEEDED -> DownloadState.Succeeded(
            descriptor ?: minimalDescriptor(entity, projectId),
        )
        DownloadStateEntity.STATE_CANCELLED -> DownloadState.Cancelled(projectId)
        DownloadStateEntity.STATE_FAILED -> DownloadState.Failed(
            projectId,
            DownloadErrorCodec.decode(entity.errorCategory) ?: DownloadError.Permanent("unknown"),
        )
        // Estados futuros: degradan a un fallo local seguro, nunca crash.
        else -> DownloadState.Failed(projectId, DownloadError.Local("state:${entity.state}"))
    }

    private fun minimalDescriptor(entity: DownloadStateEntity, projectId: ProjectId): SnapshotDescriptor =
        SnapshotDescriptor(
            ownerId = entity.ownerId,
            projectId = projectId,
            generation = "",
            totalBytes = entity.downloadedBytes,
            sourceUpdatedAt = "",
            downloadedAt = entity.finishedAt ?: 0L,
        )
}

/** Aplica un estado emitido a la fila actual (una escritura por emisión). */
fun DownloadStateEntity.withState(state: DownloadState, nowMillis: Long): DownloadStateEntity =
    when (state) {
        is DownloadState.Queued -> copy(
            state = DownloadStateEntity.STATE_QUEUED,
            downloadedBytes = 0L,
            totalBytes = null,
            errorCategory = null,
            finishedAt = null,
        )
        is DownloadState.Downloading -> copy(
            state = DownloadStateEntity.STATE_DOWNLOADING,
            downloadedBytes = state.downloadedBytes,
            totalBytes = state.totalBytes,
            errorCategory = null,
            finishedAt = null,
        )
        is DownloadState.Preparing -> copy(state = DownloadStateEntity.STATE_PREPARING)
        is DownloadState.Committing -> copy(state = DownloadStateEntity.STATE_COMMITTING)
        is DownloadState.Succeeded -> copy(
            state = DownloadStateEntity.STATE_SUCCEEDED,
            downloadedBytes = state.descriptor.totalBytes,
            totalBytes = state.descriptor.totalBytes,
            errorCategory = null,
            finishedAt = nowMillis,
        )
        is DownloadState.Cancelled -> copy(
            state = DownloadStateEntity.STATE_CANCELLED,
            finishedAt = nowMillis,
        )
        is DownloadState.Failed -> copy(
            state = DownloadStateEntity.STATE_FAILED,
            errorCategory = DownloadErrorCodec.encode(state.error),
            finishedAt = nowMillis,
        )
    }

/** Manifest (T03) → descriptor para el estado Succeeded observado. */
fun OfflineProjectManifest.toDescriptor(): SnapshotDescriptor =
    SnapshotDescriptor(
        ownerId = ownerId,
        projectId = projectId,
        generation = activeGeneration,
        totalBytes = totalBytes,
        sourceUpdatedAt = sourceUpdatedAt,
        downloadedAt = downloadedAt,
    )

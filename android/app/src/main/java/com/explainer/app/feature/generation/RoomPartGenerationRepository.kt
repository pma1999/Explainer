package com.explainer.app.feature.generation

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.snapshot.OfflineSnapshotStore
import com.explainer.app.data.remote.contract.ProjectRemoteDataSource
import com.explainer.app.data.remote.contract.RemoteResult
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Implementación de [PartGenerationRepository] (T14): orquesta el remoto
 * FastAPI (`generateDiagram`/`generateReview`) y, en éxito, fusiona el objeto
 * devuelto en la fila de la parte de la generación activa vía
 * [OfflineSnapshotStore.updatePartContent] para que el lector lo recargue y
 * conserve offline. `regenerate=true` se reenvía tal cual (paridad web).
 *
 * Redacción (global-constraints.md): las razones de fallo son categorías
 * cortas ([GenerationFailureReason]); nunca se propagan `{detail}`/bodies.
 * La cancelación de la corrutina se propaga como [CancellationException]
 * (nunca [GenerationOutcome.Failure]).
 */
class RoomPartGenerationRepository(
    private val remote: ProjectRemoteDataSource,
    private val store: OfflineSnapshotStore,
) : PartGenerationRepository {

    override suspend fun generateDiagram(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): GenerationOutcome = when (val result = remote.generateDiagram(projectId, partId, regenerate)) {
        is RemoteResult.Success -> persist(
            ownerId = ownerId,
            projectId = projectId,
            partId = partId,
            patch = buildJsonObject { put(KEY_MERMAID, result.value) },
        )

        RemoteResult.AuthRequired -> GenerationOutcome.Failure(GenerationFailureReason.AUTH)
        RemoteResult.RateLimited -> GenerationOutcome.Failure(GenerationFailureReason.RATE_LIMITED)
        RemoteResult.Retryable -> GenerationOutcome.Failure(GenerationFailureReason.OFFLINE)
        is RemoteResult.PermanentFailure -> GenerationOutcome.Failure(GenerationFailureReason.PERMISSION)
        RemoteResult.NotFound -> GenerationOutcome.Failure(GenerationFailureReason.NOT_FOUND)
        is RemoteResult.InvalidPayload -> GenerationOutcome.Failure(GenerationFailureReason.INVALID)
        RemoteResult.Cancelled -> throw CancellationException("generación de esquema cancelada")
    }

    override suspend fun generateReview(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): GenerationOutcome = when (val result = remote.generateReview(projectId, partId, regenerate)) {
        is RemoteResult.Success -> persist(
            ownerId = ownerId,
            projectId = projectId,
            partId = partId,
            patch = buildJsonObject { put(KEY_REVIEW, result.value) },
        )

        RemoteResult.AuthRequired -> GenerationOutcome.Failure(GenerationFailureReason.AUTH)
        RemoteResult.RateLimited -> GenerationOutcome.Failure(GenerationFailureReason.RATE_LIMITED)
        RemoteResult.Retryable -> GenerationOutcome.Failure(GenerationFailureReason.OFFLINE)
        is RemoteResult.PermanentFailure -> GenerationOutcome.Failure(GenerationFailureReason.PERMISSION)
        RemoteResult.NotFound -> GenerationOutcome.Failure(GenerationFailureReason.NOT_FOUND)
        is RemoteResult.InvalidPayload -> GenerationOutcome.Failure(GenerationFailureReason.INVALID)
        RemoteResult.Cancelled -> throw CancellationException("generación de repaso cancelada")
    }

    /** `true` implica contenido ya escrito en Room; si no hay fila activa, UNKNOWN. */
    private suspend fun persist(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        patch: JsonObject,
    ): GenerationOutcome =
        if (store.updatePartContent(ownerId, projectId, partId, patch)) {
            GenerationOutcome.Success
        } else {
            GenerationOutcome.Failure(GenerationFailureReason.UNKNOWN)
        }

    private companion object {
        const val KEY_MERMAID = "mermaid"
        const val KEY_REVIEW = "review"
    }
}

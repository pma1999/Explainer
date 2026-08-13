package com.explainer.app.feature.download

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.snapshot.SnapshotDescriptor

/**
 * Estado observable de la descarga de un proyecto (T06). El motor puro
 * ([DownloadProjectUseCase]) emite exactamente estas transiciones; el
 * coordinador las reproduce desde `DownloadStateEntity` (Room es la fuente
 * durable; WorkInfo progress solo la complementa).
 *
 * [Downloading.totalBytes] es null hasta que el servidor envía
 * `Content-Length`; [Downloading.estimate] es el rango rotulado
 * (HEURISTIC antes de headers, HEADER tras `Content-Length`, EXACT solo
 * cuando los bytes escritos verifican el header).
 */
sealed interface DownloadState {
    data class Queued(val projectId: ProjectId, val requestedAt: Long) : DownloadState

    data class Downloading(
        val downloadedBytes: Long,
        val totalBytes: Long?,
        val estimate: SizeEstimate? = null,
    ) : DownloadState

    data class Preparing(val projectId: ProjectId) : DownloadState
    data class Committing(val projectId: ProjectId) : DownloadState
    data class Succeeded(val descriptor: SnapshotDescriptor) : DownloadState
    data class Cancelled(val projectId: ProjectId) : DownloadState

    /** Fallo con categoría accionable; nunca expone body/JWT/paths. */
    data class Failed(val projectId: ProjectId, val error: DownloadError) : DownloadState
}

/**
 * Categorías de error visibles (global-constraints.md: los errores se
 * transforman en categorías seguras y accionables). Las razones son códigos
 * cortos (`json`, `http:400`); jamás fragmentos del body ni credenciales.
 */
sealed interface DownloadError {
    /** Red/timeout/429/5xx tras agotar los reintentos (máx. 5). */
    data object Network : DownloadError

    /** 401 definitivo tras el refresh único; exige volver a iniciar sesión. */
    data object AuthRequired : DownloadError

    /** 404 remoto (proyecto no disponible para el usuario). */
    data object NotFound : DownloadError

    /** Preflight o vigilancia durante el stream: no cabe el temporal/WAL. */
    data object NotEnoughSpace : DownloadError

    /** Payload inválido o parse/contrato roto (razón corta). */
    data class InvalidPayload(val reason: String) : DownloadError

    /** Error permanente (400/403/4xx). */
    data class Permanent(val reason: String) : DownloadError

    /** Error local no clasificable (lectura del temporal, etc.). */
    data class Local(val reason: String) : DownloadError
}

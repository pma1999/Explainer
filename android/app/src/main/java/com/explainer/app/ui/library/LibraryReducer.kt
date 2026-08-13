package com.explainer.app.ui.library

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.auth.SessionState
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.feature.catalog.RefreshOutcome
import com.explainer.app.feature.download.DownloadState
import com.explainer.app.feature.download.SizeConfidence
import com.explainer.app.feature.download.SizeEstimator
import com.explainer.app.feature.download.StorageGuard
import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * Reducer puro de la biblioteca (T09): combina catálogo, sesión y estados
 * de descarga en filas y sheets. Solo usa puertos puros (estimador/guardián
 * de T06); nunca toca Ktor/Room/WorkManager (eso lo hace el ViewModel vía
 * puertos).
 */
internal object LibraryReducer {

    // ---- Mapeo a UI ----

    fun toUiState(model: LibraryModel, downloads: Map<String, DownloadState>): LibraryUiState {
        if (model.session is SessionState.Initializing || !model.receivedFirst) {
            return LibraryUiState.Loading
        }
        val ownerMatches = when (val session = model.session) {
            is SessionState.Authenticated -> session.ownerId == model.ownerId
            is SessionState.OfflineAvailable -> session.ownerId == model.ownerId
            is SessionState.SignedOut, is SessionState.Initializing -> false
        }
        if (!ownerMatches) return LibraryUiState.SignedOut

        return LibraryUiState.Content(
            rows = model.items.map { mapRow(it, downloads[it.projectId.value]) },
            isOffline = model.session is SessionState.OfflineAvailable,
            isRefreshing = model.isRefreshing,
            lastSyncAtMillis = model.lastSyncAtMillis,
            message = model.message,
            confirmation = model.confirmationProjectId?.let { id ->
                model.items.firstOrNull { it.projectId == id }?.let { toConfirmation(it) }
            },
            deleteTarget = model.deleteProjectId?.let { id ->
                model.items.firstOrNull { it.projectId == id }
                    ?.let { DeleteTargetUiModel(it.projectId, it.name) }
            },
        )
    }

    private fun mapRow(item: ProjectListItem, download: DownloadState?): ProjectRowUiModel {
        val progress = when (download) {
            is DownloadState.Queued ->
                DownloadProgressUi(downloadedBytes = 0L, totalBytes = null, isEstimate = false)

            is DownloadState.Downloading -> DownloadProgressUi(
                downloadedBytes = download.downloadedBytes,
                totalBytes = download.totalBytes,
                isEstimate = download.estimate?.confidence != SizeConfidence.EXACT,
            )

            is DownloadState.Preparing, is DownloadState.Committing ->
                DownloadProgressUi(downloadedBytes = 0L, totalBytes = null, isEstimate = false)

            else -> null
        }
        val result = when (download) {
            is DownloadState.Cancelled -> DownloadResultUi(DownloadResultKind.CANCELLED)
            is DownloadState.Failed -> DownloadResultUi(DownloadResultKind.FAILED, download.error)
            else -> null
        }
        return ProjectRowUiModel(
            projectId = item.projectId,
            name = item.name,
            status = item.status,
            availability = item.availability,
            hasSnapshot = hasSnapshot(item),
            snapshotBytes = item.snapshotBytes,
            updatedAtEpochMillis = timestampEpochMillis(item.updatedAt),
            partCount = item.partCount,
            downloadResult = result,
            downloadProgress = progress,
        )
    }

    private fun toConfirmation(item: ProjectListItem): DownloadConfirmationUiModel {
        val isUpdate = item.availability == ProjectAvailability.UPDATE_POSSIBLE
        val estimate = SizeEstimator.fromSegmentation(
            segmentationBytes = item.segmentationSourceBytes,
            currentSnapshotBytes = if (isUpdate) item.snapshotBytes else null,
        )
        return DownloadConfirmationUiModel(
            projectId = item.projectId,
            projectName = item.name,
            isUpdate = isUpdate,
            estimateLowBytes = estimate.lowBytes,
            estimateHighBytes = estimate.highBytes,
            requiredFreeBytes = StorageGuard.requiredFreeBytes(estimate.highBytes),
            currentSnapshotBytes = if (isUpdate) item.snapshotBytes else null,
        )
    }

    // ---- Transiciones ----

    /** Sesión terminada limpia las filas; otras sesiones solo se registran. */
    fun onSession(model: LibraryModel, session: SessionState): LibraryModel =
        if (session is SessionState.SignedOut) {
            model.copy(session = session, items = emptyList())
        } else {
            model.copy(session = session)
        }

    fun onRefreshStarted(model: LibraryModel): LibraryModel =
        if (model.isRefreshing) model else model.copy(isRefreshing = true)

    /** Refresh no destructivo: nunca borra filas; el éxito registra sync. */
    fun onRefreshFinished(
        model: LibraryModel,
        outcome: RefreshOutcome,
        nowMillis: Long,
    ): LibraryModel = when (outcome) {
        is RefreshOutcome.Success ->
            model.copy(isRefreshing = false, lastSyncAtMillis = nowMillis, message = null)

        RefreshOutcome.AuthRequired ->
            model.copy(isRefreshing = false, message = LibraryMessage(LibraryMessageKind.REFRESH_FAILED_AUTH))

        RefreshOutcome.Retryable ->
            model.copy(isRefreshing = false, message = LibraryMessage(LibraryMessageKind.REFRESH_FAILED_RETRYABLE))

        RefreshOutcome.Cancelled -> model.copy(isRefreshing = false)

        RefreshOutcome.NotFound,
        RefreshOutcome.RateLimited,
        RefreshOutcome.InvalidPayload,
        is RefreshOutcome.PermanentFailure,
        -> model.copy(isRefreshing = false, message = LibraryMessage(LibraryMessageKind.REFRESH_FAILED_OTHER))
    }

    /** Abre el sheet de descarga/actualización; doble tap y UPDATING no reabren. */
    fun onDownloadRequested(model: LibraryModel, projectId: ProjectId): LibraryModel {
        if (model.confirmationProjectId != null) return model
        val item = model.items.firstOrNull { it.projectId == projectId } ?: return model
        if (item.availability == ProjectAvailability.UPDATING) return model
        return model.copy(confirmationProjectId = projectId)
    }

    fun onDownloadConfirmed(model: LibraryModel): LibraryModel =
        model.copy(confirmationProjectId = null)

    /** Pide confirmación de borrado local; solo con snapshot (o en curso). */
    fun onDeleteRequested(model: LibraryModel, projectId: ProjectId): LibraryModel {
        if (model.deleteProjectId != null) return model
        val item = model.items.firstOrNull { it.projectId == projectId } ?: return model
        if (!hasSnapshot(item)) return model
        return model.copy(deleteProjectId = projectId)
    }

    fun onDeleteConfirmed(model: LibraryModel): LibraryModel =
        model.copy(deleteProjectId = null)

    /** Dismiss cierra cualquier sheet (descarga o borrado). */
    fun onDismissSheet(model: LibraryModel): LibraryModel =
        model.copy(confirmationProjectId = null, deleteProjectId = null)

    fun onMessageDismissed(model: LibraryModel): LibraryModel = model.copy(message = null)

    // ---- Helpers ----

    private fun hasSnapshot(item: ProjectListItem): Boolean =
        item.availability != ProjectAvailability.REMOTE_ONLY &&
            item.availability != ProjectAvailability.UNAVAILABLE

    internal fun timestampEpochMillis(raw: String): Long = try {
        if (raw.isBlank()) 0L else Instant.parse(raw).toEpochMilli()
    } catch (_: DateTimeParseException) {
        0L
    }
}

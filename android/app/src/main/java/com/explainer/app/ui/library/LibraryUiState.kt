package com.explainer.app.ui.library

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.data.auth.SessionState
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.feature.download.DownloadError

/**
 * Estado, acciones y eventos de la biblioteca (T09).
 *
 * Presentacional e inmutable: la UI recibe [LibraryUiState] y emite
 * [LibraryAction]; el ViewModel consume puertos (catálogo, descargas,
 * sesión) y el reducer puro combina filas, disponibilidad, estados de
 * descarga y sheets. Nunca hay JSON pesado en el estado Compose.
 */
sealed interface LibraryUiState {
    /** Sesión inicializando o catálogo sin primera emisión. */
    data object Loading : LibraryUiState

    /** Sesión terminada o de otro owner: no se muestran filas ajenas. */
    data object SignedOut : LibraryUiState

    data class Content(
        val rows: List<ProjectRowUiModel>,
        val isOffline: Boolean,
        val isRefreshing: Boolean,
        val lastSyncAtMillis: Long,
        val message: LibraryMessage?,
        val confirmation: DownloadConfirmationUiModel?,
        val deleteTarget: DeleteTargetUiModel?,
    ) : LibraryUiState
}

/** Fila de lista: vista ligera, jerarquía tipográfica, sin JSON pesado. */
data class ProjectRowUiModel(
    val projectId: ProjectId,
    val name: String,
    val status: ProjectStatus,
    val availability: ProjectAvailability,
    val hasSnapshot: Boolean,
    val snapshotBytes: Long,
    val updatedAtEpochMillis: Long,
    val partCount: Int,
    val downloadResult: DownloadResultUi? = null,
    val downloadProgress: DownloadProgressUi? = null,
)

/**
 * Progreso visible: bytes recibidos (exactos), total conocido o null
 * (indeterminado) y [isEstimate] para rotular la cifra como estimada.
 */
data class DownloadProgressUi(
    val downloadedBytes: Long,
    val totalBytes: Long?,
    val isEstimate: Boolean,
)

/** Resultado terminal de una descarga (cancelada/fallida). */
data class DownloadResultUi(
    val kind: DownloadResultKind,
    val error: DownloadError? = null,
)

enum class DownloadResultKind { CANCELLED, FAILED }

/**
 * Sheet de confirmación de descarga/actualización: rango SIEMPRE estimado
 * hasta header, tamaño exacto actual aparte, espacio requerido y la copia
 * "reemplaza, no duplica".
 */
data class DownloadConfirmationUiModel(
    val projectId: ProjectId,
    val projectName: String,
    val isUpdate: Boolean,
    val estimateLowBytes: Long,
    val estimateHighBytes: Long,
    val requiredFreeBytes: Long,
    val currentSnapshotBytes: Long?,
)

/** Borrado local confirmado: solo el dispositivo; la web no se toca. */
data class DeleteTargetUiModel(
    val projectId: ProjectId,
    val name: String,
)

/** Mensaje transitorio con copia accionable y cierre explícito. */
data class LibraryMessage(
    val kind: LibraryMessageKind,
    val projectName: String? = null,
)

enum class LibraryMessageKind {
    DOWNLOAD_STARTED,
    DOWNLOAD_SUCCEEDED,
    DELETE_SUCCEEDED,
    REFRESH_FAILED_RETRYABLE,
    REFRESH_FAILED_AUTH,
    REFRESH_FAILED_OTHER,
}

/**
 * Modelo interno del reducer: catálogo + sesión + estado de refresh y
 * sheets. Los IDs de sheet se resuelven contra `items` al mapear a UI.
 */
internal data class LibraryModel(
    val ownerId: String,
    val items: List<ProjectListItem> = emptyList(),
    val receivedFirst: Boolean = false,
    val session: SessionState = SessionState.Initializing,
    val isRefreshing: Boolean = false,
    val lastSyncAtMillis: Long = 0L,
    val message: LibraryMessage? = null,
    val confirmationProjectId: ProjectId? = null,
    val deleteProjectId: ProjectId? = null,
)

/** Acciones de la biblioteca; el ViewModel las traduce a llamadas únicas. */
sealed interface LibraryAction {
    data object Refresh : LibraryAction
    data class Download(val projectId: ProjectId) : LibraryAction
    data class ConfirmDownload(val projectId: ProjectId) : LibraryAction
    data class CancelDownload(val projectId: ProjectId) : LibraryAction
    data class DeleteLocal(val projectId: ProjectId) : LibraryAction
    data class ConfirmDeleteLocal(val projectId: ProjectId) : LibraryAction
    data object DismissSheet : LibraryAction
    data object DismissMessage : LibraryAction

    /** Navegación al lector (solo snapshot activo); la ruta la traduce. */
    data class OpenProject(val projectId: ProjectId) : LibraryAction

    /** Navegación a ajustes; la ruta la traduce. */
    data object OpenSettings : LibraryAction
}

/** Eventos one-shot: el host los traduce en haptics/navegación. */
sealed interface LibraryEvent {
    data object DownloadConfirmed : LibraryEvent
    data object DownloadCancelled : LibraryEvent
    data object DeleteConfirmed : LibraryEvent
    data object DownloadSucceeded : LibraryEvent
}

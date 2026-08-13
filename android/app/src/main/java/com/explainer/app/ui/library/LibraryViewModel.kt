package com.explainer.app.ui.library

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.data.auth.SessionState
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.feature.download.DownloadCoordinator
import com.explainer.app.feature.download.DownloadState
import com.explainer.app.feature.download.EnqueueResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * ViewModel de la biblioteca (T09): combina catálogo, descargas y sesión
 * SOLO a través de puertos (nunca Ktor/Room/WorkManager directos) y traduce
 * acciones en llamadas únicas y no destructivas. El refresh inicial ocurre
 * una vez con sesión válida; los fallos conservan filas; el owner de sesión
 * aísla todo (un SignedOut u otro owner no muestra filas).
 */
class LibraryViewModel(
    private val scope: CoroutineScope,
    private val ownerId: String,
    private val gateway: SessionGateway,
    private val catalog: ProjectCatalogRepository,
    private val downloads: DownloadCoordinator,
    private val now: () -> Long,
) {
    private val _uiState = MutableStateFlow<LibraryUiState>(LibraryUiState.Loading)
    val uiState: StateFlow<LibraryUiState> = _uiState

    private val _events = MutableSharedFlow<LibraryEvent>(extraBufferCapacity = 8)
    val events: SharedFlow<LibraryEvent> = _events

    private var model = LibraryModel(ownerId = ownerId, session = SessionState.Initializing)
    private val downloadStates = mutableMapOf<String, DownloadState>()
    private val downloadJobs = mutableMapOf<String, Job>()

    init {
        scope.launch {
            gateway.state.collect { session ->
                val sessionOwner = when (session) {
                    is SessionState.Authenticated -> session.ownerId
                    is SessionState.OfflineAvailable -> session.ownerId
                    else -> null
                }
                if (sessionOwner != ownerId) {
                    // Logout u otra cuenta: sin observadores de descarga
                    // activos (R-T11-05); la UI pasa a SignedOut.
                    cancelAllDownloadObservers()
                }
                model = LibraryReducer.onSession(model, session)
                publish()
                if (session is SessionState.Authenticated && session.ownerId == ownerId) {
                    refreshOnce()
                }
            }
        }
        scope.launch {
            catalog.observeProjects(ownerId).collect { items ->
                model = model.copy(items = items, receivedFirst = true)
                reconcileDownloadObservers(items)
                publish()
            }
        }
    }

    fun onAction(action: LibraryAction) {
        when (action) {
            LibraryAction.Refresh -> refreshOnce()

            is LibraryAction.Download -> {
                model = LibraryReducer.onDownloadRequested(model, action.projectId)
                publish()
            }

            is LibraryAction.ConfirmDownload -> confirmDownload(action.projectId)

            is LibraryAction.CancelDownload -> scope.launch {
                downloads.cancel(ownerId, action.projectId)
                _events.emit(LibraryEvent.DownloadCancelled)
            }

            is LibraryAction.DeleteLocal -> {
                model = LibraryReducer.onDeleteRequested(model, action.projectId)
                publish()
            }

            is LibraryAction.ConfirmDeleteLocal -> confirmDelete(action.projectId)

            LibraryAction.DismissSheet -> {
                model = LibraryReducer.onDismissSheet(model)
                publish()
            }

            LibraryAction.DismissMessage -> {
                model = LibraryReducer.onMessageDismissed(model)
                publish()
            }

            // Navegación: la ruta (T11) traduce OpenProject/OpenSettings.
            is LibraryAction.OpenProject -> Unit
            LibraryAction.OpenSettings -> Unit
        }
    }

    private fun confirmDownload(projectId: ProjectId) {
        if (model.confirmationProjectId != projectId) return
        model = LibraryReducer.onDownloadConfirmed(model)
        publish()
        scope.launch {
            val result = downloads.enqueue(ownerId, projectId)
            if (result == EnqueueResult.Enqueued) {
                model = model.copy(message = LibraryMessage(LibraryMessageKind.DOWNLOAD_STARTED))
                publish()
                _events.emit(LibraryEvent.DownloadConfirmed)
            }
        }
    }

    private fun confirmDelete(projectId: ProjectId) {
        if (model.deleteProjectId != projectId) return
        model = LibraryReducer.onDeleteConfirmed(model)
        publish()
        scope.launch {
            downloads.deleteLocal(ownerId, projectId)
            model = model.copy(message = LibraryMessage(LibraryMessageKind.DELETE_SUCCEEDED))
            publish()
            _events.emit(LibraryEvent.DeleteConfirmed)
        }
    }

    /** Refresh no destructivo; nunca se relanza mientras está en curso. */
    private fun refreshOnce() {
        if (model.isRefreshing) return
        model = LibraryReducer.onRefreshStarted(model)
        publish()
        scope.launch {
            val outcome = catalog.refresh(ownerId)
            model = LibraryReducer.onRefreshFinished(model, outcome, now())
            publish()
        }
    }

    /**
     * Reconciliación de observadores por proyecto (R-T11-05): cancela el job
     * de descarga de todo ID que salió del catálogo (y descarta su estado),
     * y observa los nuevos. Sin esto la pantalla acumularía flows activos
     * durante una sesión larga.
     */
    private fun reconcileDownloadObservers(items: List<ProjectListItem>) {
        val present = items.mapTo(mutableSetOf()) { it.projectId.value }
        val removed = downloadJobs.keys.filterTo(mutableListOf()) { it !in present }
        for (key in removed) {
            downloadJobs.remove(key)?.cancel()
            downloadStates.remove(key)
        }
        for (item in items) {
            val key = item.projectId.value
            if (downloadJobs.containsKey(key)) continue
            val projectId = item.projectId
            downloadJobs[key] = scope.launch {
                downloads.observe(ownerId, projectId).collect { state ->
                    downloadStates[projectId.value] = state
                    onDownloadStateChanged(projectId, state)
                    publish()
                }
            }
        }
    }

    /** Logout/cambio de cuenta: cancela TODOS los observadores de descarga. */
    private fun cancelAllDownloadObservers() {
        downloadJobs.values.forEach { it.cancel() }
        downloadJobs.clear()
        downloadStates.clear()
    }

    private fun onDownloadStateChanged(projectId: ProjectId, state: DownloadState) {
        if (state is DownloadState.Succeeded) {
            val name = model.items.firstOrNull { it.projectId == projectId }?.name
            model = model.copy(
                message = LibraryMessage(LibraryMessageKind.DOWNLOAD_SUCCEEDED, name),
            )
            scope.launch { _events.emit(LibraryEvent.DownloadSucceeded) }
        }
    }

    private fun publish() {
        _uiState.value = LibraryReducer.toUiState(model, downloadStates)
    }
}

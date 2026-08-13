package com.explainer.app.ui.settings

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.data.preferences.LocalAccessPreferences
import com.explainer.app.data.preferences.ThemePreferences
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.download.DownloadCoordinator
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * ViewModel de Ajustes (T11): tema persistido (DataStore), identidad local
 * no secreta, almacenamiento (bytes/proyectos del owner) y las tres
 * acciones destructivas CON confirmación. Solo consume puertos: la sesión
 * la cierra el container ([onExplicitSignOut]) y el borrado total también
 * ([onDeleteAllLocal], owner-scoped estricto); aquí nunca hay Ktor/Room/
 * WorkManager directos.
 */
class SettingsViewModel(
    private val scope: CoroutineScope,
    private val ownerId: String,
    private val gateway: SessionGateway,
    private val catalog: ProjectCatalogRepository,
    private val downloads: DownloadCoordinator,
    private val themePreferences: ThemePreferences,
    private val localAccess: LocalAccessPreferences,
    private val onExplicitSignOut: suspend () -> Unit,
    private val onDeleteAllLocal: suspend () -> Unit,
) {
    private val _uiState = MutableStateFlow<SettingsUiState>(SettingsUiState.Loading)
    val uiState: StateFlow<SettingsUiState> = _uiState

    private val _events = MutableSharedFlow<SettingsEvent>(extraBufferCapacity = 8)
    val events: SharedFlow<SettingsEvent> = _events

    private var model = SettingsModel(ownerId = ownerId)

    init {
        scope.launch {
            gateway.state.collect { session ->
                model = SettingsReducer.onSession(model, session)
                publish()
            }
        }
        scope.launch {
            themePreferences.themeMode.collect { mode ->
                model = SettingsReducer.onThemeMode(model, mode)
                publish()
            }
        }
        scope.launch {
            localAccess.unlockedEmail.collect { email ->
                model = SettingsReducer.onOwnerEmail(model, email)
                publish()
            }
        }
        scope.launch {
            catalog.observeProjects(ownerId).collect { items ->
                model = SettingsReducer.onItems(model, items)
                publish()
            }
        }
    }

    fun onAction(action: SettingsAction) {
        when (action) {
            is SettingsAction.SetThemeMode -> scope.launch {
                themePreferences.setThemeMode(action.mode)
            }

            SettingsAction.RequestSignOut -> {
                model = SettingsReducer.onSignOutRequested(model)
                publish()
            }

            SettingsAction.ConfirmSignOut -> {
                if (model.confirmation != SettingsConfirmation.SignOut) return
                model = SettingsReducer.onConfirmed(model)
                publish()
                scope.launch {
                    onExplicitSignOut()
                    _events.emit(SettingsEvent.SignedOut)
                }
            }

            is SettingsAction.RequestDeleteProject -> {
                model = SettingsReducer.onDeleteRequested(model, action.projectId)
                publish()
            }

            is SettingsAction.ConfirmDeleteProject -> {
                if (model.confirmation != SettingsConfirmation.DeleteProject(action.projectId)) return
                model = SettingsReducer.onConfirmed(model)
                publish()
                scope.launch {
                    downloads.deleteLocal(ownerId, action.projectId)
                    _events.emit(SettingsEvent.DeleteConfirmed)
                }
            }

            SettingsAction.RequestDeleteAll -> {
                model = SettingsReducer.onDeleteAllRequested(model)
                publish()
            }

            SettingsAction.ConfirmDeleteAll -> {
                if (model.confirmation != SettingsConfirmation.DeleteAll) return
                model = SettingsReducer.onConfirmed(model)
                publish()
                scope.launch {
                    onDeleteAllLocal()
                    _events.emit(SettingsEvent.DeleteConfirmed)
                }
            }

            SettingsAction.DismissConfirm -> {
                model = SettingsReducer.onDismiss(model)
                publish()
            }

            // Navegación: la ruta (T11) traduce Back a popBackStack.
            SettingsAction.Back -> Unit
        }
    }

    private fun publish() {
        _uiState.value = SettingsReducer.toUiState(model)
    }
}

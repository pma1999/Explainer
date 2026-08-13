package com.explainer.app.ui.settings

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.auth.SessionState
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.ui.theme.ThemeMode

/**
 * Reducer puro de Ajustes (T11): combina tema persistido, identidad local
 * no secreta y almacenamiento (bytes lógicos por proyecto offline) en el
 * estado presentacional. Las confirmaciones destructivas son exclusivas
 * (una abierta ignora otra) y "borrar todo" borra SOLO las filas del owner
 * activo (los datos del owner se particionan en la fuente; aquí solo se
 * listan las suyas).
 */
internal object SettingsReducer {

    fun toUiState(model: SettingsModel): SettingsUiState {
        if (model.session is SessionState.Initializing || !model.receivedFirst) {
            return SettingsUiState.Loading
        }
        val ownerMatches = when (val session = model.session) {
            is SessionState.Authenticated -> session.ownerId == model.ownerId
            is SessionState.OfflineAvailable -> session.ownerId == model.ownerId
            is SessionState.SignedOut, is SessionState.Initializing -> false
        }
        if (!ownerMatches) return SettingsUiState.SignedOut

        val rows = model.items
            .filter { it.snapshotBytes > 0L }
            .map { StorageRowUi(projectId = it.projectId, name = it.name, bytes = it.snapshotBytes) }
            .sortedByDescending { it.bytes }
        return SettingsUiState.Content(
            themeMode = model.themeMode,
            ownerEmail = model.ownerEmail,
            storageRows = rows,
            totalBytes = rows.sumOf { it.bytes },
            confirmation = model.confirmation,
        )
    }

    /** Sesión terminada limpia las filas; otras sesiones solo se registran. */
    fun onSession(model: SettingsModel, session: SessionState): SettingsModel =
        if (session is SessionState.SignedOut) {
            model.copy(session = session, items = emptyList())
        } else {
            model.copy(session = session)
        }

    fun onThemeMode(model: SettingsModel, mode: ThemeMode): SettingsModel =
        model.copy(themeMode = mode)

    fun onOwnerEmail(model: SettingsModel, email: String?): SettingsModel =
        model.copy(ownerEmail = email)

    fun onItems(model: SettingsModel, items: List<ProjectListItem>): SettingsModel =
        model.copy(items = items, receivedFirst = true)

    /** Una confirmación abierta ignora nuevas peticiones (sin doble sheet). */
    fun onSignOutRequested(model: SettingsModel): SettingsModel =
        if (model.confirmation != null) model else model.copy(confirmation = SettingsConfirmation.SignOut)

    fun onDeleteRequested(model: SettingsModel, projectId: ProjectId): SettingsModel =
        if (model.confirmation != null) model else model.copy(confirmation = SettingsConfirmation.DeleteProject(projectId))

    fun onDeleteAllRequested(model: SettingsModel): SettingsModel =
        if (model.confirmation != null) model else model.copy(confirmation = SettingsConfirmation.DeleteAll)

    fun onConfirmed(model: SettingsModel): SettingsModel = model.copy(confirmation = null)

    fun onDismiss(model: SettingsModel): SettingsModel = model.copy(confirmation = null)
}

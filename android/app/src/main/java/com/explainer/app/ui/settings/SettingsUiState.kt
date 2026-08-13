package com.explainer.app.ui.settings

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.auth.SessionState
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.ui.theme.ThemeMode

/**
 * Estado, acciones y eventos de Ajustes (T11).
 *
 * Presentacional e inmutable: la UI recibe [SettingsUiState] y emite
 * [SettingsAction]. El ViewModel consume puertos (sesión, catálogo,
 * descargas, preferencias) y el reducer puro combina tema, identidad local
 * y almacenamiento. Las acciones destructivas (logout, borrar proyecto,
 * borrar todo) pasan SIEMPRE por confirmación explícita.
 */
sealed interface SettingsUiState {
    /** Sesión inicializando o preferencias/almacenamiento sin primera emisión. */
    data object Loading : SettingsUiState

    /** Sesión terminada (defensivo; la raíz navega). */
    data object SignedOut : SettingsUiState

    data class Content(
        val themeMode: ThemeMode,
        /** Identidad local NO secreta (email del owner desbloqueado). */
        val ownerEmail: String?,
        /** Proyectos offline con bytes lógicos de snapshot. */
        val storageRows: List<StorageRowUi>,
        val totalBytes: Long,
        /** Confirmación pendiente (logout / borrar proyecto / borrar todo). */
        val confirmation: SettingsConfirmation?,
    ) : SettingsUiState
}

/** Fila de almacenamiento: proyecto offline y sus bytes lógicos. */
data class StorageRowUi(
    val projectId: ProjectId,
    val name: String,
    val bytes: Long,
)

/** Confirmación pendiente; la pantalla la muestra en un sheet. */
sealed interface SettingsConfirmation {
    data object SignOut : SettingsConfirmation
    data class DeleteProject(val projectId: ProjectId) : SettingsConfirmation
    data object DeleteAll : SettingsConfirmation
}

/** Modelo interno del reducer: tema + identidad + almacenamiento + sheets. */
internal data class SettingsModel(
    val ownerId: String,
    val themeMode: ThemeMode = ThemeMode.SYSTEM,
    val ownerEmail: String? = null,
    val items: List<ProjectListItem> = emptyList(),
    val receivedFirst: Boolean = false,
    val session: SessionState = SessionState.Initializing,
    val confirmation: SettingsConfirmation? = null,
)

/** Acciones de Ajustes; el ViewModel las traduce a llamadas únicas. */
sealed interface SettingsAction {
    /** Cambia el tema persistido (SYSTEM/LIGHT/DARK); flujo reactivo aplica. */
    data class SetThemeMode(val mode: ThemeMode) : SettingsAction

    data object RequestSignOut : SettingsAction
    data object ConfirmSignOut : SettingsAction

    /** Pide confirmación para borrar UNA copia local. */
    data class RequestDeleteProject(val projectId: ProjectId) : SettingsAction
    data class ConfirmDeleteProject(val projectId: ProjectId) : SettingsAction

    /** Pide confirmación para borrar TODAS las copias del owner activo. */
    data object RequestDeleteAll : SettingsAction
    data object ConfirmDeleteAll : SettingsAction

    /** Cierra el sheet de confirmación sin ejecutar. */
    data object DismissConfirm : SettingsAction

    /** Navegación atrás; la ruta (T11) la traduce a popBackStack. */
    data object Back : SettingsAction
}

/** Eventos one-shot: el host los traduce en haptics/navegación. */
sealed interface SettingsEvent {
    /** Logout explícito completado (la raíz navega a Auth por el estado). */
    data object SignedOut : SettingsEvent

    /** Borrado local confirmado (proyecto o todo). */
    data object DeleteConfirmed : SettingsEvent
}

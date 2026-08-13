package com.explainer.app.ui.settings

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.data.preferences.LocalAccessPreferences
import com.explainer.app.data.preferences.ThemePreferences
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.download.DownloadCoordinator

/**
 * Adaptador de ruta de Ajustes (T11): crea el [SettingsViewModel] con los
 * puertos y las operaciones orquestadas del container (logout explícito y
 * borrado total owner-scoped), traduce eventos a haptics de confirmación y
 * pinta la pantalla stateless. No registra NavHost: lo cablea T11.
 */
@Composable
fun SettingsRouteContent(
    ownerId: String,
    session: SessionGateway,
    catalog: ProjectCatalogRepository,
    downloads: DownloadCoordinator,
    themePreferences: ThemePreferences,
    localAccess: LocalAccessPreferences,
    onExplicitSignOut: suspend () -> Unit,
    onDeleteAllLocal: suspend () -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val viewModel = remember(ownerId, session, catalog, downloads, themePreferences, localAccess) {
        SettingsViewModel(
            scope = scope,
            ownerId = ownerId,
            gateway = session,
            catalog = catalog,
            downloads = downloads,
            themePreferences = themePreferences,
            localAccess = localAccess,
            onExplicitSignOut = onExplicitSignOut,
            onDeleteAllLocal = onDeleteAllLocal,
        )
    }
    val haptics = LocalHapticFeedback.current
    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                SettingsEvent.SignedOut, SettingsEvent.DeleteConfirmed ->
                    haptics.performHapticFeedback(HapticFeedbackType.Confirm)
            }
        }
    }

    val state by viewModel.uiState.collectAsStateWithLifecycle()
    SettingsScreen(
        state = state,
        onAction = { action ->
            when (action) {
                SettingsAction.Back -> onBack()
                else -> viewModel.onAction(action)
            }
        },
    )
}

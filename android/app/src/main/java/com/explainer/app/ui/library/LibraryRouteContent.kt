package com.explainer.app.ui.library

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.download.DownloadCoordinator

/**
 * Adaptador de ruta de la biblioteca (T09/T11): crea el [LibraryViewModel]
 * con los puertos, traduce eventos a haptics de confirmación (solo
 * confirm/cancel/delete/success, global-constraints.md UX), traduce
 * navegación ([onOpenProject], [onOpenSettings]) y pinta la pantalla
 * stateless. No registra NavHost: T11 lo cablea.
 */
@Composable
fun LibraryRouteContent(
    ownerId: String,
    gateway: SessionGateway,
    catalog: ProjectCatalogRepository,
    downloads: DownloadCoordinator,
    onOpenProject: (ProjectId) -> Unit,
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val viewModel = remember(ownerId, gateway, catalog, downloads) {
        LibraryViewModel(
            scope = scope,
            ownerId = ownerId,
            gateway = gateway,
            catalog = catalog,
            downloads = downloads,
            now = System::currentTimeMillis,
        )
    }
    val haptics = LocalHapticFeedback.current
    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                LibraryEvent.DownloadConfirmed,
                LibraryEvent.DownloadCancelled,
                LibraryEvent.DeleteConfirmed,
                LibraryEvent.DownloadSucceeded,
                -> haptics.performHapticFeedback(HapticFeedbackType.Confirm)
            }
        }
    }

    val state by viewModel.uiState.collectAsStateWithLifecycle()
    ProjectLibraryScreen(
        state = state,
        onAction = { action ->
            when (action) {
                is LibraryAction.OpenProject -> onOpenProject(action.projectId)
                LibraryAction.OpenSettings -> onOpenSettings()
                else -> viewModel.onAction(action)
            }
        },
    )
}

package com.explainer.app.ui.reader

import android.content.Context
import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.explainer.app.core.model.ProjectId
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.generation.PartGenerationRepository
import com.explainer.app.feature.progress.ReadingProgressRepository
import com.explainer.app.ui.content.SafeExternalUrlPolicy

/**
 * Adaptador de ruta del lector (T10/T11/T14): crea el [ReaderViewModel] con
 * los puertos de T07 (catálogo/progreso) y T14 (generación), traduce
 * eventos a haptics de confirmación (solo toggle de lectura,
 * global-constraints.md UX), traduce navegación ([onBack]) y URLs externas
 * aprobadas por [SafeExternalUrlPolicy] a una app externa. No registra
 * NavHost: T11 lo cablea.
 *
 * `projectId` es el wire name de la ruta; si no es un UUID válido se muestra
 * el estado [ReaderUiState.InvalidProject] en vez de abrir nada.
 */
@Composable
fun ReaderRouteContent(
    ownerId: String,
    catalog: ProjectCatalogRepository,
    progress: ReadingProgressRepository,
    generation: PartGenerationRepository,
    projectId: String,
    initialPartId: Int? = null,
    initialTab: String = "explicacion",
    onBack: () -> Unit,
) {
    val parsedId = remember(projectId) { ProjectId.parse(projectId) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val haptics = LocalHapticFeedback.current

    val viewModel = remember(ownerId, catalog, progress, generation, parsedId, initialPartId, initialTab) {
        parsedId?.let {
            ReaderViewModel(
                scope = scope,
                ownerId = ownerId,
                projectId = it,
                catalog = catalog,
                progress = progress,
                generation = generation,
                requestedPartId = initialPartId,
                requestedTab = initialTab,
            )
        }
    }

    LaunchedEffect(viewModel) {
        viewModel?.events?.collect { event ->
            when (event) {
                ReaderEvent.SectionCompleteToggled ->
                    haptics.performHapticFeedback(HapticFeedbackType.Confirm)
            }
        }
    }

    val collected by viewModel?.uiState?.collectAsStateWithLifecycle()
        ?: remember { mutableStateOf<ReaderUiState>(ReaderUiState.InvalidProject) }

    ReaderScreen(
        state = collected,
        onAction = { action ->
            when (action) {
                ReaderAction.Back -> {
                    // Finaliza la sesión del tracker antes de navegar.
                    viewModel?.onAction(action)
                    onBack()
                }

                is ReaderAction.OpenExternalUrl -> openExternalUrl(context, action.url)

                else -> viewModel?.onAction(action)
            }
        },
    )
}

/** Abre una URL http/https aprobada por la política en una app externa. */
private fun openExternalUrl(context: Context, url: String) {
    val uri = SafeExternalUrlPolicy.safeUriOrNull(url) ?: return
    runCatching {
        context.startActivity(Intent(Intent.ACTION_VIEW, uri))
    }
}

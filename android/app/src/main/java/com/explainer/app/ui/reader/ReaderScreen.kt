package com.explainer.app.ui.reader

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.ui.components.ExplainerIcons
import com.explainer.app.ui.components.ExplainerTopBar
import com.explainer.app.ui.components.OperationState
import com.explainer.app.ui.components.OperationStatePanel
import com.explainer.app.ui.components.PartNavItem
import com.explainer.app.ui.components.PartNavigationPane
import com.explainer.app.ui.components.ReaderTabStrip
import com.explainer.app.ui.content.ExplanationContent
import com.explainer.app.ui.content.ExplanationModel
import com.explainer.app.ui.content.MarkdownBody
import com.explainer.app.ui.content.PartRenderModel
import com.explainer.app.ui.content.ResourcesContent
import com.explainer.app.ui.content.ReviewContent
import com.explainer.app.ui.content.WalkthroughContent
import com.explainer.app.ui.content.mermaid.MermaidContent
import com.explainer.app.ui.theme.AppBarMetrics
import com.explainer.app.ui.theme.ElevationTokens
import com.explainer.app.ui.theme.MinimumTargets
import com.explainer.app.ui.theme.MotionTokens
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.WindowSize
import com.explainer.app.ui.theme.explainerColors
import com.explainer.app.ui.theme.readingTypography
import com.explainer.app.ui.theme.rememberWindowSize
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Pantalla del lector offline de cinco pestañas (T10/T14). Stateless:
 * [ReaderScreen] recibe [ReaderUiState] y emite [ReaderAction]; el
 * ViewModel/RouteContent traducen todo lo demás (navegación, haptics,
 * URLs externas, generación). Sin tarjetas decorativas: tinta/papel, acento
 * dorado y chrome mínimo (T05).
 *
 * Los tabs `esquema`/`repaso` integran la generación on-demand (T14):
 * fase [GenerationPhase.Generating] → panel de progreso accesible;
 * [GenerationPhase.Failed] → panel/banner de error con reintento (y "Volver
 * al contenido" si ya hay contenido renderizable); fase null → contenido,
 * con CTA de generación si está ausente o affordance secundario de
 * regeneración si existe. Ningún tab queda en pantalla vacía.
 *
 * Lectura-first: el chrome superior (top bar, banner y píldora de sección)
 * se repliega al hacer scroll hacia abajo y reaparece al hacer scroll hacia
 * arriba, de modo que el contenido domina la pantalla mientras se lee; los
 * tabs quedan siempre a 1 tap (dock fijo abajo en compact, sobre el
 * contenido en medium/expanded, donde el rail de partes tampoco se mueve).
 * Compact: píldora de sección (anterior/píldora/siguiente/leída en una fila
 * de 48dp) que abre el selector en sheet + tabs a pantalla completa.
 * Medium/expanded: pane de partes (rail) + contenido en dos paneles; la
 * barra de lectura también se repliega al leer. La WebView Mermaid solo se
 * compone cuando el tab `esquema` está visible (se destruye al salir vía
 * T08).
 */
@Composable
fun ReaderScreen(state: ReaderUiState, onAction: (ReaderAction) -> Unit) {
    when (state) {
        ReaderUiState.Loading -> ReaderChrome(
            title = stringResource(R.string.app_name),
            onBack = { onAction(ReaderAction.Back) },
        ) {
            OperationStatePanel(
                state = OperationState.LOADING,
                title = stringResource(R.string.reader_loading_message),
            )
        }

        ReaderUiState.InvalidProject -> ReaderChrome(
            title = stringResource(R.string.reader_invalid_project_title),
            onBack = { onAction(ReaderAction.Back) },
        ) {
            OperationStatePanel(
                state = OperationState.ERROR,
                title = stringResource(R.string.reader_invalid_project_title),
                message = stringResource(R.string.reader_invalid_project_message),
            )
        }

        ReaderUiState.MissingSnapshot -> ReaderChrome(
            title = stringResource(R.string.reader_missing_snapshot_title),
            onBack = { onAction(ReaderAction.Back) },
        ) {
            OperationStatePanel(
                state = OperationState.EMPTY,
                title = stringResource(R.string.reader_missing_snapshot_title),
                message = stringResource(R.string.reader_missing_snapshot_message),
            )
        }

        is ReaderUiState.Content -> ReaderContent(model = state.model, onAction = onAction)
    }
}

@Composable
private fun ReaderChrome(
    title: String,
    onBack: () -> Unit,
    content: @Composable () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        ExplainerTopBar(title = title, onNavigationClick = onBack)
        Box(modifier = Modifier.weight(1f)) { content() }
    }
}

// ─── Contenido del lector ───────────────────────────────────────────────────

@Composable
private fun ReaderContent(model: ReaderContentUi, onAction: (ReaderAction) -> Unit) {
    val windowSize = rememberWindowSize()
    // Estado de scroll por tab: cambiar de tab no borra la posición dentro de
    // la misma parte (el cambio de parte resetea los cinco, abajo). El mapa
    // es de estado para que el chrome replegable observe el LazyListState del
    // tab activo (lectura-first).
    val listStates = remember { mutableStateMapOf<String, LazyListState>() }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(model.selectedPartId) {
        // Parte nueva: los cinco tabs vuelven arriba (paridad web selectPart).
        listStates.values.forEach { it.scrollToItem(0) }
    }

    // Solo el tab activo con contenido listo tiene lista observable; con la
    // parte en carga, fallida o el proyecto vacío, el chrome permanece fijo.
    val activeListState = if (model.partState is PartContentUi.Ready) {
        listStates[model.selectedTab.wireName]
    } else {
        null
    }
    val chromeVisibleState = rememberChromeVisibility(
        listState = activeListState,
        resetKey = model.selectedTab to model.selectedPartId,
    )
    val chromeVisible by chromeVisibleState

    Column(modifier = Modifier.fillMaxSize()) {
        AnimatedVisibility(visible = chromeVisible, enter = ChromeEnter, exit = ChromeExit) {
            Column {
                ExplainerTopBar(
                    title = model.projectName,
                    onNavigationClick = { onAction(ReaderAction.Back) },
                )
                if (model.updatePossible) {
                    UpdatePossibleBanner()
                }
            }
        }
        if (windowSize == WindowSize.COMPACT) {
            CompactReaderBody(model, listStates, snackbar, onAction, chromeVisible)
        } else {
            SplitReaderBody(model, listStates, snackbar, onAction, chromeVisible)
        }
    }
}

/**
 * Compact: la píldora de sección vive en el chrome replegable; los tabs se
 * anclan abajo como dock persistente (1 tap desde cualquier punto de la
 * lectura) y el selector de partes se abre en sheet.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CompactReaderBody(
    model: ReaderContentUi,
    listStates: MutableMap<String, LazyListState>,
    snackbar: SnackbarHostState,
    onAction: (ReaderAction) -> Unit,
    chromeVisible: Boolean,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        AnimatedVisibility(visible = chromeVisible, enter = ChromeEnter, exit = ChromeExit) {
            PartSelectorBar(model = model, onAction = onAction)
        }
        PartContentArea(
            model, listStates, snackbar, onAction,
            Modifier.weight(1f),
            showReadingToolbar = false,
        )
        ReaderTabStrip(
            selectedTab = model.selectedTab.wireName,
            onTabSelected = { onAction(ReaderAction.SelectTab(it)) },
        )
    }
    if (model.partSelectorOpen) {
        ModalBottomSheet(
            onDismissRequest = { onAction(ReaderAction.ClosePartSelector) },
            containerColor = MaterialTheme.colorScheme.surface,
            contentColor = MaterialTheme.colorScheme.onSurface,
        ) {
            PartNavigationPane(
                items = model.parts.map { it.toNavItem() },
                selectedPartId = model.selectedPartId,
                onPartSelected = { onAction(ReaderAction.SelectPart(it)) },
                header = stringResource(R.string.reader_part_selector_title),
                modifier = Modifier.padding(bottom = Spacing.Xl),
            )
        }
    }
}

/**
 * Medium/expanded: rail de partes + contenido en dos paneles. El rail queda
 * fijo (cambio de parte siempre a 1 tap); la barra de lectura se repliega
 * con el resto del chrome.
 */
@Composable
private fun SplitReaderBody(
    model: ReaderContentUi,
    listStates: MutableMap<String, LazyListState>,
    snackbar: SnackbarHostState,
    onAction: (ReaderAction) -> Unit,
    chromeVisible: Boolean,
) {
    Row(modifier = Modifier.fillMaxSize()) {
        Surface(
            modifier = Modifier.width(SplitReaderDefaults.RailWidth),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = ElevationTokens.Level1,
        ) {
            PartNavigationPane(
                items = model.parts.map { it.toNavItem() },
                selectedPartId = model.selectedPartId,
                onPartSelected = { onAction(ReaderAction.SelectPart(it)) },
                header = stringResource(R.string.reader_part_selector_title),
            )
        }
        Column(modifier = Modifier.weight(1f)) {
            ReaderTabStrip(
                selectedTab = model.selectedTab.wireName,
                onTabSelected = { onAction(ReaderAction.SelectTab(it)) },
            )
            PartContentArea(
                model, listStates, snackbar, onAction,
                Modifier.weight(1f),
                showReadingToolbar = true,
                toolbarVisible = chromeVisible,
            )
        }
    }
}

/**
 * Píldora de sección compacta (lectura-first): anterior, parte actual (abre
 * el selector en sheet, con la posición "x/y"), siguiente y estado leído en
 * una única fila de 48dp. En compact sustituye a la antigua barra de parte y
 * a la barra de lectura; forma parte del chrome replegable (reaparece al
 * hacer scroll hacia arriba). Targets >=
 * [PartSelectorBarDefaults.MinimumTargetSize].
 */
@Composable
private fun PartSelectorBar(model: ReaderContentUi, onAction: (ReaderAction) -> Unit) {
    val index = model.parts.indexOfFirst { it.partId == model.selectedPartId }
    if (index < 0) return
    val selected = model.parts[index]
    val colors = MaterialTheme.explainerColors
    Surface(color = MaterialTheme.colorScheme.surface) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = PartSelectorBarDefaults.MinimumTargetSize)
                .padding(horizontal = Spacing.Sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = { onAction(ReaderAction.PreviousPart) },
                enabled = model.canGoPrevious,
            ) {
                Icon(
                    imageVector = ExplainerIcons.KeyboardArrowLeft,
                    contentDescription = stringResource(R.string.reader_prev),
                    tint = colors.primary,
                )
            }
            Row(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = PartSelectorBarDefaults.MinimumTargetSize)
                    .clickable(
                        role = Role.Button,
                        onClickLabel = stringResource(R.string.reader_part_selector_open),
                        onClick = { onAction(ReaderAction.OpenPartSelector) },
                    )
                    .padding(horizontal = Spacing.Sm),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacing.Xs),
            ) {
                Text(
                    text = stringResource(R.string.reader_part_bar, selected.partId, selected.title),
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = stringResource(R.string.reader_part_position, index + 1, model.parts.size),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Icon(
                    imageVector = ExplainerIcons.KeyboardArrowDown,
                    contentDescription = null,
                    tint = colors.primary,
                    modifier = Modifier.size(ReaderDefaults.CompactIconSize),
                )
            }
            IconButton(
                onClick = { onAction(ReaderAction.NextPart) },
                enabled = model.canGoNext,
            ) {
                Icon(
                    imageVector = ExplainerIcons.KeyboardArrowRight,
                    contentDescription = stringResource(R.string.reader_next),
                    tint = colors.primary,
                )
            }
            if (selected.canToggle) {
                IconButton(
                    onClick = { onAction(ReaderAction.ToggleSectionComplete(selected.partId)) },
                ) {
                    Icon(
                        imageVector = if (selected.isRead) ExplainerIcons.Check else ExplainerIcons.Done,
                        contentDescription = stringResource(
                            if (selected.isRead) R.string.reader_mark_unread else R.string.reader_mark_read,
                        ),
                        tint = if (selected.isRead) {
                            colors.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
            }
        }
    }
}

/** Banner informativo de actualización posible (nunca solo color). */
@Composable
private fun UpdatePossibleBanner() {
    val colors = MaterialTheme.explainerColors
    Surface(color = colors.status.warningContainer, contentColor = colors.status.onWarningContainer) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.Lg, vertical = Spacing.Sm)
                .semantics { liveRegion = LiveRegionMode.Polite },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = ExplainerIcons.Info,
                contentDescription = null,
                tint = colors.status.onWarningContainer,
                modifier = Modifier.size(ReaderDefaults.BannerIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = stringResource(R.string.reader_update_possible),
                style = MaterialTheme.typography.bodyMedium,
                color = colors.status.onWarningContainer,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

// ─── Área de contenido ───────────────────────────────────────────────────────

@Composable
private fun PartContentArea(
    model: ReaderContentUi,
    listStates: MutableMap<String, LazyListState>,
    snackbar: SnackbarHostState,
    onAction: (ReaderAction) -> Unit,
    modifier: Modifier = Modifier,
    showReadingToolbar: Boolean = true,
    toolbarVisible: Boolean = true,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        if (model.parts.isEmpty()) {
            EmptyProjectPanel(modifier = Modifier.weight(1f))
        } else {
            if (showReadingToolbar) {
                AnimatedVisibility(visible = toolbarVisible, enter = ChromeEnter, exit = ChromeExit) {
                    ReadingToolbar(model = model, onAction = onAction)
                }
            }
            when (model.partState) {
                PartContentUi.Loading -> OperationStatePanel(
                    state = OperationState.LOADING,
                    title = stringResource(R.string.reader_part_loading_title),
                    modifier = Modifier.weight(1f),
                )

                is PartContentUi.Processing -> PartLevelStatePanel(
                    title = stringResource(R.string.reader_part_processing_title),
                    message = stringResource(R.string.reader_part_processing_message),
                    modifier = Modifier.weight(1f),
                )

                PartContentUi.Failed -> PartLevelStatePanel(
                    title = stringResource(R.string.reader_part_failed_title),
                    message = stringResource(R.string.reader_part_failed_message),
                    modifier = Modifier.weight(1f),
                )

                is PartContentUi.Missing -> PartLevelStatePanel(
                    title = stringResource(R.string.reader_part_missing_title),
                    message = stringResource(R.string.reader_part_missing_message),
                    modifier = Modifier.weight(1f),
                )

                PartContentUi.LoadError -> OperationStatePanel(
                    state = OperationState.ERROR,
                    title = stringResource(R.string.reader_part_load_error_title),
                    message = stringResource(R.string.reader_part_load_error_message),
                    onAction = { onAction(ReaderAction.RetryPartLoad) },
                    modifier = Modifier.weight(1f),
                )

                is PartContentUi.Ready -> when (model.selectedTab) {
                    ReaderTab.EXPLANATION -> ExplanationTab(model, listStates, snackbar, onAction, Modifier.weight(1f))

                    ReaderTab.WALKTHROUGH -> SingleContentTab(
                        wireName = ReaderTab.WALKTHROUGH.wireName,
                        listStates = listStates,
                        modifier = Modifier.weight(1f),
                    ) {
                        WalkthroughContent(model.partState.parsed.forTab(ReaderTab.WALKTHROUGH))
                    }

                    ReaderTab.RESOURCES -> SingleContentTab(
                        wireName = ReaderTab.RESOURCES.wireName,
                        listStates = listStates,
                        modifier = Modifier.weight(1f),
                    ) {
                        ResourcesContent(
                            model = model.partState.parsed.forTab(ReaderTab.RESOURCES),
                            onLink = { onAction(ReaderAction.OpenExternalUrl(it)) },
                        )
                    }

                    ReaderTab.DIAGRAM -> DiagramTab(model, listStates, onAction, Modifier.weight(1f))

                    ReaderTab.REVIEW -> ReviewTab(model, listStates, onAction, Modifier.weight(1f))
                }
            }
        }
        SnackbarHost(hostState = snackbar, modifier = Modifier.align(Alignment.CenterHorizontally))
    }
}

// ─── Tabs de generación (T14): esquema y repaso ─────────────────────────────

/**
 * Tab `esquema` con fase de generación: Generating → panel de progreso;
 * Failed → banner sobre el contenido (si existe) o panel de error; null →
 * contenido con CTA de generación o affordance de regeneración.
 */
@Composable
private fun DiagramTab(
    model: ReaderContentUi,
    listStates: MutableMap<String, LazyListState>,
    onAction: (ReaderAction) -> Unit,
    modifier: Modifier = Modifier,
) {
    val parsed = (model.partState as PartContentUi.Ready).parsed
    val partId = model.selectedPartId ?: return
    when (val phase = model.diagramGeneration) {
        GenerationPhase.Generating -> GenerationProgressPanel(
            title = stringResource(R.string.generation_generating_diagram),
            note = stringResource(R.string.generation_generating_note),
            modifier = modifier,
        )

        is GenerationPhase.Failed -> if (parsed.diagram is PartRenderModel.Diagram) {
            // El contenido previo sigue siendo útil: error como banner encima.
            Column(modifier = modifier.fillMaxWidth()) {
                GenerationErrorBanner(
                    message = stringResource(ReaderLabels.generationFailureMessageRes(phase.reason)),
                    onRetry = { onAction(ReaderAction.GenerateDiagram(partId, regenerate = true)) },
                    onDismiss = { onAction(ReaderAction.DismissDiagramError) },
                )
                SingleContentTab(
                    wireName = ReaderTab.DIAGRAM.wireName,
                    listStates = listStates,
                    modifier = Modifier.weight(1f),
                ) {
                    MermaidContent(
                        model = parsed.forTab(ReaderTab.DIAGRAM),
                        onRegenerate = { onAction(ReaderAction.GenerateDiagram(partId, regenerate = true)) },
                    )
                }
            }
        } else {
            GenerationErrorPanel(
                title = stringResource(R.string.generation_error_diagram_title),
                message = stringResource(ReaderLabels.generationFailureMessageRes(phase.reason)),
                onRetry = { onAction(ReaderAction.GenerateDiagram(partId, regenerate = true)) },
                modifier = modifier,
            )
        }

        null -> SingleContentTab(
            wireName = ReaderTab.DIAGRAM.wireName,
            listStates = listStates,
            modifier = modifier,
        ) {
            // La WebView Mermaid solo existe mientras este tab está compuesto.
            MermaidContent(
                model = parsed.forTab(ReaderTab.DIAGRAM),
                onGenerate = { onAction(ReaderAction.GenerateDiagram(partId, regenerate = false)) },
                onRegenerate = if (parsed.diagram is PartRenderModel.Diagram) {
                    { onAction(ReaderAction.GenerateDiagram(partId, regenerate = true)) }
                } else {
                    null
                },
            )
        }
    }
}

/** Tab `repaso` con fase de generación (misma estructura que [DiagramTab]). */
@Composable
private fun ReviewTab(
    model: ReaderContentUi,
    listStates: MutableMap<String, LazyListState>,
    onAction: (ReaderAction) -> Unit,
    modifier: Modifier = Modifier,
) {
    val parsed = (model.partState as PartContentUi.Ready).parsed
    val partId = model.selectedPartId ?: return
    when (val phase = model.reviewGeneration) {
        GenerationPhase.Generating -> GenerationProgressPanel(
            title = stringResource(R.string.generation_generating_review),
            note = stringResource(R.string.generation_generating_note),
            modifier = modifier,
        )

        is GenerationPhase.Failed -> if (parsed.review is PartRenderModel.Review) {
            Column(modifier = modifier.fillMaxWidth()) {
                GenerationErrorBanner(
                    message = stringResource(ReaderLabels.generationFailureMessageRes(phase.reason)),
                    onRetry = { onAction(ReaderAction.GenerateReview(partId, regenerate = true)) },
                    onDismiss = { onAction(ReaderAction.DismissReviewError) },
                )
                SingleContentTab(
                    wireName = ReaderTab.REVIEW.wireName,
                    listStates = listStates,
                    modifier = Modifier.weight(1f),
                ) {
                    ReviewContent(
                        model = parsed.forTab(ReaderTab.REVIEW),
                        onRegenerate = { onAction(ReaderAction.GenerateReview(partId, regenerate = true)) },
                    )
                }
            }
        } else {
            GenerationErrorPanel(
                title = stringResource(R.string.generation_error_review_title),
                message = stringResource(ReaderLabels.generationFailureMessageRes(phase.reason)),
                onRetry = { onAction(ReaderAction.GenerateReview(partId, regenerate = true)) },
                modifier = modifier,
            )
        }

        null -> SingleContentTab(
            wireName = ReaderTab.REVIEW.wireName,
            listStates = listStates,
            modifier = modifier,
        ) {
            ReviewContent(
                model = parsed.forTab(ReaderTab.REVIEW),
                onGenerate = { onAction(ReaderAction.GenerateReview(partId, regenerate = false)) },
                onRegenerate = if (parsed.review is PartRenderModel.Review) {
                    { onAction(ReaderAction.GenerateReview(partId, regenerate = true)) }
                } else {
                    null
                },
            )
        }
    }
}

/**
 * Panel de generación en curso: spinner + título + nota de duración,
 * anunciado por TalkBack como liveRegion polite. Sin controles (no hay nada
 * que cancelar en v1): el único target es implícito.
 */
@Composable
internal fun GenerationProgressPanel(
    title: String,
    note: String,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.explainerColors
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Xl, vertical = Spacing.Xxl)
            .semantics { liveRegion = LiveRegionMode.Polite },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(GenerationDefaults.ProgressSize),
            color = colors.primary,
            strokeWidth = GenerationDefaults.ProgressStroke,
        )
        Spacer(Modifier.height(Spacing.Lg))
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
            modifier = Modifier.semantics { heading() },
        )
        Spacer(Modifier.height(Spacing.Sm))
        Text(
            text = note,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}

/** Banner de error de generación sobre contenido existente: reintento SIEMPRE visible. */
@Composable
internal fun GenerationErrorBanner(
    message: String,
    onRetry: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.explainerColors
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = colors.errorContainer,
        contentColor = colors.onErrorContainer,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacing.Lg, vertical = Spacing.Md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = ExplainerIcons.Warning,
                contentDescription = null,
                tint = colors.onErrorContainer,
                modifier = Modifier.size(GenerationDefaults.BannerIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = colors.onErrorContainer,
                )
                Row(
                    horizontalArrangement = Arrangement.spacedBy(Spacing.Sm),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(
                        onClick = onRetry,
                        modifier = Modifier.heightIn(min = GenerationDefaults.MinimumActionHeight),
                    ) {
                        Icon(
                            imageVector = ExplainerIcons.Refresh,
                            contentDescription = null,
                            modifier = Modifier.size(GenerationDefaults.ActionIconSize),
                        )
                        Spacer(Modifier.width(Spacing.Xs))
                        Text(
                            text = stringResource(R.string.generation_retry),
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                    TextButton(
                        onClick = onDismiss,
                        modifier = Modifier.heightIn(min = GenerationDefaults.MinimumActionHeight),
                    ) {
                        Text(
                            text = stringResource(R.string.generation_back_to_content),
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                }
            }
        }
    }
}

/**
 * Panel de error de generación sin contenido previo: título, mensaje por
 * razón y reintento (target >= 48dp). Nunca pantalla vacía.
 */
@Composable
internal fun GenerationErrorPanel(
    title: String,
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.explainerColors
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Xl, vertical = Spacing.Xxl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Surface(
            color = colors.errorContainer,
            shape = MaterialTheme.shapes.medium,
        ) {
            Icon(
                imageVector = ExplainerIcons.Error,
                contentDescription = null,
                tint = colors.onErrorContainer,
                modifier = Modifier
                    .padding(Spacing.Lg)
                    .size(GenerationDefaults.ErrorIconSize),
            )
        }
        Spacer(Modifier.height(Spacing.Lg))
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
            modifier = Modifier.semantics { heading() },
        )
        Spacer(Modifier.height(Spacing.Sm))
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(Spacing.Xl))
        Button(
            onClick = onRetry,
            modifier = Modifier.heightIn(min = GenerationDefaults.MinimumActionHeight),
        ) {
            Icon(
                imageVector = ExplainerIcons.Refresh,
                contentDescription = null,
                modifier = Modifier.size(GenerationDefaults.ActionIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = stringResource(R.string.generation_retry),
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}

/**
 * Barra de lectura de medium/expanded (en compact la píldora de sección
 * asume anterior/siguiente/contador/leída): anterior/siguiente agrupados,
 * contador y estado leído. Se repliega con el resto del chrome al leer.
 */
@Composable
private fun ReadingToolbar(model: ReaderContentUi, onAction: (ReaderAction) -> Unit) {
    val index = model.parts.indexOfFirst { it.partId == model.selectedPartId }
    if (index < 0) return
    val selected = model.parts[index]
    FlowRow(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Md, vertical = Spacing.Sm),
        horizontalArrangement = Arrangement.spacedBy(Spacing.Sm),
        verticalArrangement = Arrangement.spacedBy(Spacing.Sm),
    ) {
        OutlinedButton(
            onClick = { onAction(ReaderAction.PreviousPart) },
            enabled = model.canGoPrevious,
            modifier = Modifier.heightIn(min = ReadingToolbarDefaults.MinimumTargetSize),
        ) {
            Icon(
                imageVector = ExplainerIcons.KeyboardArrowLeft,
                contentDescription = null,
                modifier = Modifier.size(ReaderDefaults.CompactIconSize),
            )
            Text(
                text = stringResource(R.string.reader_prev),
                style = MaterialTheme.typography.labelLarge,
            )
        }
        OutlinedButton(
            onClick = { onAction(ReaderAction.NextPart) },
            enabled = model.canGoNext,
            modifier = Modifier.heightIn(min = ReadingToolbarDefaults.MinimumTargetSize),
        ) {
            Text(
                text = stringResource(R.string.reader_next),
                style = MaterialTheme.typography.labelLarge,
            )
            Icon(
                imageVector = ExplainerIcons.KeyboardArrowRight,
                contentDescription = null,
                modifier = Modifier.size(ReaderDefaults.CompactIconSize),
            )
        }
        Text(
            text = stringResource(R.string.reader_section_counter, index + 1, model.parts.size),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier
                .align(Alignment.CenterVertically)
                .padding(horizontal = Spacing.Sm),
        )
        if (selected.canToggle) {
            Button(
                onClick = { onAction(ReaderAction.ToggleSectionComplete(selected.partId)) },
                modifier = Modifier.heightIn(min = ReadingToolbarDefaults.MinimumTargetSize),
            ) {
                Icon(
                    imageVector = if (selected.isRead) ExplainerIcons.Check else ExplainerIcons.Done,
                    contentDescription = null,
                    modifier = Modifier.size(ReaderDefaults.CompactIconSize),
                )
                Spacer(Modifier.width(Spacing.Xs))
                Text(
                    text = stringResource(
                        if (selected.isRead) R.string.reader_mark_unread else R.string.reader_mark_read,
                    ),
                    style = MaterialTheme.typography.labelLarge,
                )
            }
        }
    }
}

/** Panel de estado de la parte (generándose/error/no descargada): nunca vacío. */
@Composable
private fun PartLevelStatePanel(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Xl, vertical = Spacing.Xxl),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.semantics { heading() },
        )
        Spacer(Modifier.height(Spacing.Sm))
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun EmptyProjectPanel(modifier: Modifier = Modifier) {
    PartLevelStatePanel(
        title = stringResource(R.string.reader_project_empty_title),
        message = stringResource(R.string.reader_project_empty_message),
        modifier = modifier,
    )
}

// ─── Tab Explicación ─────────────────────────────────────────────────────────

/**
 * Filas del tab Explicación (paridad `projectView.js renderExplainer`):
 * bloque de descripción y, para el contenido estructurado, una fila por
 * sección/subsección/conexión con IDs wire exactos
 * `subsec-{partId}-{sectionIndex}-{subIndex}` y `subsec-{partId}-cx-{index}`.
 * El markdown de cada campo usa [MarkdownBody] (T08); la forma markdown pura
 * y los estados Missing/AgentError/Malformed delegan en [ExplanationContent]
 * (T08).
 */
private sealed interface ExplanationRow {
    data object Description : ExplanationRow
    data class SectionTitle(val sectionIndex: Int, val title: String) : ExplanationRow
    data class SectionIntro(val sectionIndex: Int, val markdown: String) : ExplanationRow
    data class SubsectionHeading(val subsectionId: String, val title: String) : ExplanationRow
    data class SubsectionBody(val subsectionId: String, val markdown: String) : ExplanationRow
    data object ConclusionLabel : ExplanationRow
    data class ConclusionBody(val markdown: String) : ExplanationRow
    data class ConnectionHeading(val subsectionId: String, val title: String) : ExplanationRow
    data class ConnectionBody(val subsectionId: String, val markdown: String) : ExplanationRow
}

@Composable
private fun ExplanationTab(
    model: ReaderContentUi,
    listStates: MutableMap<String, LazyListState>,
    snackbar: SnackbarHostState,
    onAction: (ReaderAction) -> Unit,
    modifier: Modifier = Modifier,
) {
    val parsed = (model.partState as PartContentUi.Ready).parsed
    val onRejectedLink = rememberRejectedLinkHandler(snackbar)
    when (val explanation = parsed.explanation) {
        is PartRenderModel.Explanation -> when (val content = explanation.content) {
            is ExplanationModel.Markdown -> {
                val listState = listStates.getOrPut(ReaderTab.EXPLANATION.wireName) { LazyListState() }
                LazyColumn(
                    state = listState,
                    modifier = modifier.fillMaxWidth(),
                    contentPadding = ReaderContentPadding,
                ) {
                    item(key = "description") { PartDescriptionBlock(model, onAction) }
                    item(key = "markdown") {
                        ExplanationContent(
                            model = explanation,
                            onLink = { onAction(ReaderAction.OpenExternalUrl(it)) },
                            onRejectedLink = onRejectedLink,
                        )
                    }
                }
            }

            is ExplanationModel.Structured -> StructuredExplanationTab(
                model = model,
                content = content,
                listStates = listStates,
                onAction = onAction,
                onRejectedLink = onRejectedLink,
                modifier = modifier,
            )
        }

        // Missing/AgentError/Malformed → estados accesibles de T08, nunca vacío.
        else -> SingleContentTab(
            wireName = ReaderTab.EXPLANATION.wireName,
            listStates = listStates,
            modifier = modifier,
        ) {
            ExplanationContent(
                model = explanation,
                onLink = { onAction(ReaderAction.OpenExternalUrl(it)) },
                onRejectedLink = onRejectedLink,
            )
        }
    }
}

@Composable
private fun StructuredExplanationTab(
    model: ReaderContentUi,
    content: ExplanationModel.Structured,
    listStates: MutableMap<String, LazyListState>,
    onAction: (ReaderAction) -> Unit,
    onRejectedLink: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val partId = model.selectedPartId ?: return
    val rows = remember(content, partId) { buildExplanationRows(partId, content) }
    val indexToSubsectionId = remember(rows) {
        rows.map { row ->
            when (row) {
                is ExplanationRow.SubsectionHeading -> row.subsectionId
                is ExplanationRow.ConnectionHeading -> row.subsectionId
                else -> null
            }
        }
    }
    val listState = listStates.getOrPut(ReaderTab.EXPLANATION.wireName) { LazyListState() }

    // Zona de lectura activa 35–45 %: alimenta el tracker de T07 (paridad web
    // `initSubsectionObserver`); solo emite cuando la activa cambia.
    LaunchedEffect(listState, indexToSubsectionId, partId, model.selectedTab) {
        if (model.selectedTab != ReaderTab.EXPLANATION) return@LaunchedEffect
        snapshotFlow {
            val layoutInfo = listState.layoutInfo
            val viewportHeight = layoutInfo.viewportEndOffset - layoutInfo.viewportStartOffset
            val activeIndex = ReaderViewport.activeTrackedIndex(
                items = layoutInfo.visibleItemsInfo.mapNotNull { visible ->
                    if (indexToSubsectionId.getOrNull(visible.index) != null) {
                        ReaderViewport.TrackedItem(visible.index, visible.offset, visible.size)
                    } else {
                        null
                    }
                },
                viewportHeight = viewportHeight,
            )
            activeIndex?.let { indexToSubsectionId.getOrNull(it) }
        }
            .distinctUntilChanged()
            .filterNotNull()
            .collect { subsectionId ->
                onAction(ReaderAction.SubsectionActivated(subsectionId))
            }
    }

    // Scroll de reanudación: coloca el heading en la zona de lectura (una vez).
    LaunchedEffect(listState, model.scrollTarget, model.selectedTab, partId) {
        val target = model.scrollTarget ?: return@LaunchedEffect
        if (target.partId != partId || target.tab != model.selectedTab) return@LaunchedEffect
        val index = indexToSubsectionId.indexOf(target.subsectionId)
        if (index >= 0) {
            val viewportHeight = snapshotFlow {
                listState.layoutInfo.viewportEndOffset - listState.layoutInfo.viewportStartOffset
            }.first { it > 0 }
            listState.scrollToItem(index, (viewportHeight * RESUME_BAND_RATIO).toInt())
        }
        onAction(ReaderAction.ScrollTargetHandled)
    }

    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxWidth(),
        contentPadding = ReaderContentPadding,
    ) {
        itemsIndexed(rows, key = { _, row -> row.key() }) { _, row ->
            ExplanationRowContent(
                row = row,
                model = model,
                onAction = onAction,
                onRejectedLink = onRejectedLink,
            )
        }
    }
}

@Composable
private fun ExplanationRowContent(
    row: ExplanationRow,
    model: ReaderContentUi,
    onAction: (ReaderAction) -> Unit,
    onRejectedLink: (String) -> Unit,
) {
    when (row) {
        is ExplanationRow.Description -> PartDescriptionBlock(model, onAction)

        is ExplanationRow.SectionTitle -> Text(
            text = row.title,
            style = MaterialTheme.readingTypography.heading2,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier
                .padding(top = Spacing.Md, bottom = Spacing.Sm)
                .semantics { heading() },
        )

        is ExplanationRow.SectionIntro -> MarkdownBody(
            content = row.markdown,
            onLink = { onAction(ReaderAction.OpenExternalUrl(it)) },
            onRejectedLink = onRejectedLink,
        )

        is ExplanationRow.SubsectionHeading -> Text(
            text = row.title,
            style = MaterialTheme.readingTypography.heading3,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier
                .padding(top = Spacing.Md, bottom = Spacing.Sm)
                .semantics { heading() },
        )

        is ExplanationRow.SubsectionBody -> MarkdownBody(
            content = row.markdown,
            onLink = { onAction(ReaderAction.OpenExternalUrl(it)) },
            onRejectedLink = onRejectedLink,
        )

        is ExplanationRow.ConclusionLabel -> Text(
            text = stringResource(R.string.content_explainer_conclusion_label),
            style = MaterialTheme.readingTypography.heading3,
            color = MaterialTheme.explainerColors.primary,
            modifier = Modifier.semantics { heading() },
        )

        is ExplanationRow.ConclusionBody -> MarkdownBody(
            content = row.markdown,
            onLink = { onAction(ReaderAction.OpenExternalUrl(it)) },
            onRejectedLink = onRejectedLink,
        )

        is ExplanationRow.ConnectionHeading -> Text(
            text = row.title,
            style = MaterialTheme.readingTypography.heading3,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier
                .padding(top = Spacing.Md, bottom = Spacing.Sm)
                .semantics { heading() },
        )

        is ExplanationRow.ConnectionBody -> MarkdownBody(
            content = row.markdown,
            onLink = { onAction(ReaderAction.OpenExternalUrl(it)) },
            onRejectedLink = onRejectedLink,
        )
    }
}

/** Descripción de sección (`partes[].contenido`): colapsable y seleccionable. */
@Composable
private fun PartDescriptionBlock(model: ReaderContentUi, onAction: (ReaderAction) -> Unit) {
    val description = model.selectedPartDescription
    Column(modifier = Modifier.fillMaxWidth().padding(bottom = Spacing.Md)) {
        Text(
            text = stringResource(R.string.reader_description_label),
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.explainerColors.primary,
            modifier = Modifier.semantics { heading() },
        )
        SelectionContainer {
            Text(
                text = description,
                style = MaterialTheme.readingTypography.body,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = if (model.descriptionExpanded) Int.MAX_VALUE else ReaderDefaults.DescriptionCollapsedLines,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (description.isNotBlank()) {
            TextButton(
                onClick = { onAction(ReaderAction.ToggleDescription) },
                modifier = Modifier.heightIn(min = GenerationDefaults.MinimumActionHeight),
            ) {
                Text(
                    text = stringResource(
                        if (model.descriptionExpanded) R.string.reader_description_collapse
                        else R.string.reader_description_expand,
                    ),
                    style = MaterialTheme.typography.labelLarge,
                )
                Spacer(Modifier.width(Spacing.Xs))
                Icon(
                    imageVector = if (model.descriptionExpanded) {
                        ExplainerIcons.KeyboardArrowUp
                    } else {
                        ExplainerIcons.KeyboardArrowDown
                    },
                    contentDescription = null,
                    modifier = Modifier.size(ReaderDefaults.CompactIconSize),
                )
            }
        }
    }
}

/** Construye las filas de la explicación estructurada con IDs wire exactos. */
private fun buildExplanationRows(partId: Int, content: ExplanationModel.Structured): List<ExplanationRow> {
    val rows = mutableListOf<ExplanationRow>()
    rows += ExplanationRow.Description
    content.introduccion?.let { intro ->
        rows += ExplanationRow.SectionIntro(-1, intro)
    }
    content.desarrollo.forEachIndexed { sectionIndex, section ->
        rows += ExplanationRow.SectionTitle(sectionIndex, section.tituloSeccion)
        section.explicacionIntroductoria?.let { intro ->
            rows += ExplanationRow.SectionIntro(sectionIndex, intro)
        }
        section.subsecciones.forEachIndexed { subIndex, sub ->
            val id = "subsec-$partId-$sectionIndex-$subIndex"
            rows += ExplanationRow.SubsectionHeading(id, sub.tituloSubseccion)
            sub.explicacionDetallada?.let { detail ->
                rows += ExplanationRow.SubsectionBody(id, detail)
            }
        }
    }
    content.conclusion?.let { conclusion ->
        rows += ExplanationRow.ConclusionLabel
        rows += ExplanationRow.ConclusionBody(conclusion)
    }
    content.conexionesContextuales.forEachIndexed { cxIndex, cx ->
        val id = "subsec-$partId-cx-$cxIndex"
        rows += ExplanationRow.ConnectionHeading(id, cx.seccionTemarioRelacionada)
        cx.descripcionConexion?.let { desc ->
            rows += ExplanationRow.ConnectionBody(id, desc)
        }
    }
    return rows
}

// ─── Tab genérico (recorrido/recursos/esquema/repaso) ────────────────────────

@Composable
private fun SingleContentTab(
    wireName: String,
    listStates: MutableMap<String, LazyListState>,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val listState = listStates.getOrPut(wireName) { LazyListState() }
    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxWidth(),
        contentPadding = ReaderContentPadding,
    ) {
        item(key = wireName) { content() }
    }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

// ─── Chrome replegable (lectura-first) ───────────────────────────────────────

/** Fotograma de scroll observado por el chrome replegable. */
private data class ChromeScrollFrame(
    val index: Int,
    val offset: Int,
    val inProgress: Boolean,
    val firstItemSize: Int,
)

/**
 * Entrada del chrome superior: aparece desde arriba con fundido. El
 * recorrido del slide es más corto que el de la salida para que la aparición
 * se lea como un revelado estable sobre el contenido: el reflow del texto no
 * compite con el gesto.
 */
private val ChromeEnter: EnterTransition =
    fadeIn(animationSpec = tween(MotionTokens.FastMs)) +
        slideInVertically(animationSpec = tween(MotionTokens.FastMs)) { -it / 3 }

/** Salida del chrome superior: se retira hacia arriba con fundido, rápida,
 *  para que el contenido gane espacio de inmediato al leer. */
private val ChromeExit: ExitTransition =
    fadeOut(animationSpec = tween(MotionTokens.FastMs)) +
        slideOutVertically(animationSpec = tween(MotionTokens.FastMs)) { -it }

/**
 * Visibilidad del chrome superior (lectura-first): visible al reposo; se
 * oculta al hacer scroll hacia abajo y reaparece al hacer scroll hacia
 * arriba, de modo que el contenido domina la pantalla mientras se lee.
 *
 * Estabilidad ante micro-gestos: la decisión la toma [ChromeVisibilityPolicy]
 * con zona muerta (24 dp hacia abajo, 16 dp hacia arriba) y acumulador que se
 * reinicia al invertir la dirección, de modo que un dedo que rebota unos
 * píxeles no mueve el chrome ni reflow el texto. Un fling decidido gana a la
 * zona muerta; la velocidad se deriva del desplazamiento entre fotogramas
 * (la versión de foundation del repo no expone `LazyListState.velocity`).
 * El contenido corto y la posición arriba del todo fuerzan el chrome
 * visible. Solo reacciona a gestos reales (`isScrollInProgress`), nunca a
 * saltos programáticos (reanudación de scroll, cambio de parte). Con
 * [listState] nulo (proyecto vacío o parte sin contenido listo) permanece
 * visible. [resetKey] fuerza el regreso del chrome al cambiar de tab/parte:
 * el contexto nuevo llega con la navegación completa a la vista.
 */
@Composable
private fun rememberChromeVisibility(
    listState: LazyListState?,
    resetKey: Any?,
): MutableState<Boolean> {
    val visible = remember { mutableStateOf(true) }
    val density = LocalDensity.current
    LaunchedEffect(listState, resetKey, density) {
        visible.value = true
        val state = listState ?: return@LaunchedEffect
        // Estado del detector fuera del flow (sin estado Compose: no provoca
        // re-composiciones; solo `visible` cambia al cruzar una transición).
        var policyState = ChromeVisibilityPolicy.State()
        var lastIndex = state.firstVisibleItemIndex
        var lastOffset = state.firstVisibleItemScrollOffset
        var lastSize = state.layoutInfo.visibleItemsInfo.firstOrNull()?.size ?: 0
        var lastTimeNanos = System.nanoTime()
        snapshotFlow {
            ChromeScrollFrame(
                index = state.firstVisibleItemIndex,
                offset = state.firstVisibleItemScrollOffset,
                inProgress = state.isScrollInProgress,
                firstItemSize = state.layoutInfo.visibleItemsInfo.firstOrNull()?.size ?: 0,
            )
        }.collect { frame ->
            if (!frame.inProgress) {
                // Gesto terminado: el chrome se queda donde está y la zona
                // muerta se limpia para el siguiente gesto.
                policyState = ChromeVisibilityPolicy.State(visible = policyState.visible)
                lastIndex = frame.index
                lastOffset = frame.offset
                lastSize = frame.firstItemSize
                lastTimeNanos = System.nanoTime()
                return@collect
            }
            // Delta real del contenido: dentro del mismo item es la
            // diferencia de offset; al cruzar de item se suma el tamaño del
            // item saliente (capturado antes de que saliera), con su signo.
            val deltaPx = when {
                frame.index > lastIndex -> lastSize + frame.offset - lastOffset
                frame.index < lastIndex -> frame.offset - lastOffset - lastSize
                else -> frame.offset - lastOffset
            }
            lastIndex = frame.index
            lastOffset = frame.offset
            lastSize = frame.firstItemSize
            // Velocidad derivada del desplazamiento entre fotogramas: el pico
            // de un fling decidido (miles de px/s) la dispara; el ruido de un
            // frame (1-2 px) queda órdenes de magnitud por debajo del umbral.
            val nowNanos = System.nanoTime()
            val dtSec = (nowNanos - lastTimeNanos).coerceAtLeast(1_000_000L) / 1_000_000_000f
            lastTimeNanos = nowNanos
            val velocityPxPerSec = deltaPx / dtSec
            val next = with(density) {
                ChromeVisibilityPolicy.decide(
                    previous = policyState,
                    deltaDp = deltaPx.toDp().value,
                    velocityDpPerSec = velocityPxPerSec.toDp().value,
                    canScrollForward = state.canScrollForward,
                    atTop = frame.index == 0 && frame.offset == 0,
                )
            }
            if (next.visible != policyState.visible) visible.value = next.visible
            policyState = next
        }
    }
    return visible
}

@Composable
private fun PartNavUi.toNavItem(): PartNavItem = PartNavItem(
    partId = partId,
    title = title,
    status = ReaderLabels.partStatusLabelRes(status)?.let { stringResource(it) },
)

private fun ExplanationRow.key(): String = when (this) {
    is ExplanationRow.Description -> "description"
    is ExplanationRow.SectionTitle -> "section-title-$sectionIndex"
    is ExplanationRow.SectionIntro -> "section-intro-$sectionIndex"
    is ExplanationRow.SubsectionHeading -> subsectionId
    is ExplanationRow.SubsectionBody -> "body-$subsectionId"
    is ExplanationRow.ConclusionLabel -> "conclusion-label"
    is ExplanationRow.ConclusionBody -> "conclusion-body"
    is ExplanationRow.ConnectionHeading -> subsectionId
    is ExplanationRow.ConnectionBody -> "body-$subsectionId"
}

@Composable
private fun rememberRejectedLinkHandler(snackbar: SnackbarHostState): (String) -> Unit {
    val scope = rememberCoroutineScope()
    val message = stringResource(R.string.content_link_rejected_message)
    return remember(snackbar, scope, message) {
        { _: String ->
            scope.launch {
                snackbar.currentSnackbarData?.dismiss()
                snackbar.showSnackbar(message)
            }
        }
    }
}

/** Padding de lectura: línea acotada (~72ch) centrada, chrome mínimo. */
private val ReaderContentPadding = PaddingValues(
    horizontal = Spacing.Lg,
    vertical = Spacing.Md,
)

/** Ratio de colocación del heading de reanudación dentro de la zona 35–45 %. */
private const val RESUME_BAND_RATIO = 0.4f

private object ReaderDefaults {
    const val DescriptionCollapsedLines = 3
    val CompactIconSize = 18.dp
    val BannerIconSize = 16.dp
}

object PartSelectorBarDefaults {
    /** Target táctil mínimo declarado de la barra de selección de parte. */
    val MinimumTargetSize: Dp = 48.dp
    val Height: Dp = AppBarMetrics.TopBarHeight
}

object SplitReaderDefaults {
    /** Ancho del rail de partes en medium/expanded. */
    val RailWidth: Dp = 280.dp
}

object ReadingToolbarDefaults {
    /** Target táctil mínimo declarado de los botones de la barra de lectura. */
    val MinimumTargetSize: Dp = 48.dp
}

object GenerationDefaults {
    val ProgressSize: Dp = 32.dp
    val ProgressStroke: Dp = 3.dp
    val BannerIconSize: Dp = 18.dp
    val ErrorIconSize: Dp = 28.dp
    val ActionIconSize: Dp = 18.dp
    /** Target táctil mínimo declarado de reintentar/volver (T14). */
    val MinimumActionHeight: Dp = 48.dp
}

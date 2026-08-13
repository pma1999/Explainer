package com.explainer.app.ui.reader

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.generation.GenerationOutcome
import com.explainer.app.feature.generation.PartGenerationRepository
import com.explainer.app.feature.progress.ReadingProgressRepository
import com.explainer.app.feature.progress.SubsectionActivityTracker
import com.explainer.app.feature.progress.SubsectionProgressEvent
import com.explainer.app.ui.content.PartContentParser
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * ViewModel del lector offline (T10/T14): abre solo el snapshot activo
 * owner-scoped, carga manifest + el JSON de la parte seleccionada (nunca
 * todas), cancela cargas obsoletas, alimenta el tracker de subsecciones de
 * T07, persiste progreso de forma optimista y orquesta la generación
 * on-demand de esquema/repaso (T14) a través del puerto [generation]. Solo
 * consume puertos, nunca concreciones; la red de generación nunca toca la UI.
 *
 * La reanudación (ruta > last_subsection > primera incompleta > primera) la
 * resuelve [ReaderReducer] en la primera emisión del manifest; el progreso
 * mezclado llega ya aplicado en [com.explainer.app.feature.catalog.ReaderProject].
 */
class ReaderViewModel(
    private val scope: CoroutineScope,
    private val ownerId: String,
    private val projectId: ProjectId,
    private val catalog: ProjectCatalogRepository,
    private val progress: ReadingProgressRepository,
    private val generation: PartGenerationRepository,
    private val tracker: SubsectionActivityTracker = SubsectionActivityTracker(),
    private val now: () -> Long = System::currentTimeMillis,
    private val loadDispatcher: CoroutineDispatcher = Dispatchers.Default,
    requestedPartId: Int? = null,
    requestedTab: String = "explicacion",
) {
    private val _uiState = MutableStateFlow<ReaderUiState>(ReaderUiState.Loading)
    val uiState: StateFlow<ReaderUiState> = _uiState

    private val _events = MutableSharedFlow<ReaderEvent>(extraBufferCapacity = 8)
    val events: SharedFlow<ReaderEvent> = _events

    private var model = ReaderReducer.ReaderModel(projectId = projectId)
    private var loadJob: Job? = null
    private var latestAvailability: ProjectAvailability? = null
    /** Job de generación único: una generación a la vez (single-flight). */
    private var generationJob: Job? = null
    private var generationJobIsDiagram: Boolean = false

    init {
        // Manifest del snapshot activo: abre la parte de reanudación una vez.
        scope.launch {
            catalog.observeReaderProject(ownerId, projectId).collect { project ->
                if (project == null) {
                    // Sin snapshot activo: estado explícito, nunca pantalla vacía.
                    model = ReaderReducer.ReaderModel(projectId = projectId)
                    loadJob?.cancel()
                    _uiState.value = ReaderUiState.MissingSnapshot
                } else {
                    val previousSelected = model.selectedPartId
                    model = ReaderReducer.onProject(
                        model = model,
                        project = project,
                        availability = latestAvailability,
                        requestedPartId = requestedPartId,
                        requestedTab = requestedTab,
                    )
                    publish()
                    if (model.selectedPartId != previousSelected) {
                        loadPartContent(model.selectedPartId)
                    }
                }
            }
        }
        // Lista del catálogo: solo aporta la disponibilidad (banner
        // "puede haber cambios"); el contenido nunca viene de aquí.
        scope.launch {
            catalog.observeProjects(ownerId).collect { items ->
                latestAvailability = items.firstOrNull { it.projectId == projectId }?.availability
                if (model.receivedManifest) {
                    model = model.copy(
                        updatePossible = latestAvailability == ProjectAvailability.UPDATE_POSSIBLE,
                    )
                    publish()
                }
            }
        }
    }

    fun onAction(action: ReaderAction) {
        when (action) {
            ReaderAction.Back -> finishTracking()

            is ReaderAction.SelectPart -> {
                val changed = action.partId != model.selectedPartId
                if (changed) {
                    finishTracking()
                    cancelGeneration()
                }
                model = ReaderReducer.onPartSelected(model, action.partId)
                publish()
                if (changed) loadPartContent(model.selectedPartId)
            }

            is ReaderAction.SelectTab -> {
                val changed = ReaderReducer.normalizeTab(action.wireName) != model.selectedTab
                if (changed) finishTracking()
                model = ReaderReducer.onTabSelected(model, action.wireName)
                publish()
            }

            is ReaderAction.SubsectionActivated -> onSubsectionActivated(action.subsectionId)

            is ReaderAction.ToggleSectionComplete -> {
                if (model.parts.none { it.numero == action.partId }) return
                val completed = action.partId !in model.progress.completedParts
                // Optimista: el estado visible cambia ya; la persistencia es local.
                model = ReaderReducer.onToggleSectionComplete(model, action.partId)
                publish()
                scope.launch {
                    progress.setSectionCompleted(ownerId, projectId, action.partId, completed)
                    _events.emit(ReaderEvent.SectionCompleteToggled)
                }
            }

            ReaderAction.PreviousPart -> changePart(ReaderReducer.onPreviousPart(model))

            ReaderAction.NextPart -> changePart(ReaderReducer.onNextPart(model))

            ReaderAction.ToggleDescription -> {
                model = ReaderReducer.onDescriptionToggled(model)
                publish()
            }

            ReaderAction.OpenPartSelector -> {
                model = ReaderReducer.onPartSelectorOpen(model)
                publish()
            }

            ReaderAction.ClosePartSelector -> {
                model = ReaderReducer.onPartSelectorClosed(model)
                publish()
            }

            ReaderAction.RetryPartLoad -> {
                val partId = model.selectedPartId ?: return
                model = ReaderReducer.onPartLoadStarted(model, partId)
                publish()
                loadPartContent(partId)
            }

            ReaderAction.ScrollTargetHandled -> {
                model = ReaderReducer.onScrollTargetHandled(model)
                publish()
            }

            is ReaderAction.GenerateDiagram ->
                startGeneration(partId = action.partId, regenerate = action.regenerate, diagram = true)

            is ReaderAction.GenerateReview ->
                startGeneration(partId = action.partId, regenerate = action.regenerate, diagram = false)

            ReaderAction.DismissDiagramError -> {
                model = ReaderReducer.onGenerationDismissed(model, diagram = true)
                publish()
            }

            ReaderAction.DismissReviewError -> {
                model = ReaderReducer.onGenerationDismissed(model, diagram = false)
                publish()
            }

            // La URL externa la abre el host (RouteContent) con Intent; aquí no.
            is ReaderAction.OpenExternalUrl -> Unit
        }
    }

    // ── Generación on-demand (T14) ──

    /**
     * Genera o regenera el esquema/repaso de la parte visible. Si la fase
     * del tab ya está activa (Generating) la acción se ignora; en éxito se
     * limpia la fase y se recarga la parte desde Room (el contenido ya quedó
     * persistido por el puerto); en fallo se muestra la fase Failed con la
     * razón categorizada.
     *
     * Single-flight: una sola generación a la vez por lector (costo de API).
     * Al lanzar una generación del otro tab se cancela la anterior y se
     * descarta su fase; al cambiar de parte se cancela y el reducer limpia
     * ambas fases. La cancelación se propaga como CancellationException sin
     * tocar el estado.
     */
    private fun startGeneration(partId: Int, regenerate: Boolean, diagram: Boolean) {
        val phase = if (diagram) model.diagramGeneration else model.reviewGeneration
        if (phase is GenerationPhase.Generating) return
        if (partId != model.selectedPartId) return
        // Reemplazo single-flight: si hay otra generación EN CURSO del otro
        // tab, se cancela y se descarta su fase (nunca queda "Generating"
        // huérfano); un job ya terminado conserva su resultado.
        if (generationJob?.isActive == true && generationJobIsDiagram != diagram) {
            model = ReaderReducer.onGenerationDismissed(model, generationJobIsDiagram)
        }
        generationJob?.cancel()
        model = ReaderReducer.onGenerationStarted(model, partId, diagram)
        publish()
        generationJobIsDiagram = diagram
        generationJob = scope.launch {
            val result = try {
                if (diagram) {
                    generation.generateDiagram(ownerId, projectId, partId, regenerate)
                } else {
                    generation.generateReview(ownerId, projectId, partId, regenerate)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Throwable) {
                GenerationOutcome.Failure(com.explainer.app.feature.generation.GenerationFailureReason.UNKNOWN)
            }
            when (result) {
                GenerationOutcome.Success -> {
                    model = ReaderReducer.onGenerationSucceeded(model, diagram)
                    publish()
                    // Recarga desde Room: el contenido ya está persistido.
                    loadPartContent(partId)
                }

                is GenerationOutcome.Failure -> {
                    model = ReaderReducer.onGenerationFailed(model, diagram, result.reason)
                    publish()
                }
            }
        }
    }

    /** Cancela la generación en curso; la fase la limpia el reducer por parte. */
    private fun cancelGeneration() {
        generationJob?.cancel()
        generationJob = null
    }

    /** Carga local de la parte seleccionada; cancela la carga anterior. */
    private fun changePart(next: ReaderReducer.ReaderModel) {
        if (next.selectedPartId == model.selectedPartId) return
        finishTracking()
        cancelGeneration()
        model = next
        publish()
        loadPartContent(next.selectedPartId)
    }

    private fun loadPartContent(partId: Int?) {
        if (partId == null) return
        loadJob?.cancel()
        model = ReaderReducer.onPartLoadStarted(model, partId)
        publish()
        loadJob = scope.launch {
            val result = try {
                withContext(loadDispatcher) {
                    val document = catalog.loadPart(ownerId, projectId, partId)
                    if (document == null) {
                        PartLoadResult.Missing
                    } else {
                        PartLoadResult.Document(document, PartContentParser.parse(document))
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Throwable) {
                PartLoadResult.Error
            }
            if (!currentCoroutineContext().isActive) return@launch
            model = ReaderReducer.onPartLoaded(model, partId, result)
            publish()
        }
    }

    // ── Tracker de subsecciones (T07) ──

    private fun onSubsectionActivated(subsectionId: String) {
        val partId = model.selectedPartId ?: return
        if (model.selectedTab != ReaderTab.EXPLANATION) return
        val events = tracker.activate(subsectionId, partId, ReaderTab.EXPLANATION, now())
        recordEvents(events)
    }

    /** Cierra la sesión de actividad (parte/tab/back): completed pendiente. */
    private fun finishTracking() {
        recordEvents(tracker.finish(now()))
    }

    private fun recordEvents(events: List<SubsectionProgressEvent>) {
        events.forEach { event ->
            scope.launch { progress.recordSubsection(ownerId, projectId, event) }
        }
    }

    private fun publish() {
        _uiState.value = ReaderReducer.toUiState(model)
    }
}

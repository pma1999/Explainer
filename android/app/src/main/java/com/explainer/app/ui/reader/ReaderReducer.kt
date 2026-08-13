package com.explainer.app.ui.reader

import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.PartDescriptor
import com.explainer.app.core.model.PartStatus
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.ReaderProject
import com.explainer.app.feature.generation.GenerationFailureReason
import com.explainer.app.ui.content.PartRenderModel
import com.explainer.app.ui.content.ParsedPartContent

/**
 * Reducer puro del lector (T10): reanudación (paridad web
 * `storage.js getResumeTarget`), transiciones de parte/tab, prev/next,
 * toggle optimista de parte completa, selector de partes y clasificación de
 * los estados de contenido. Solo usa tipos de T02/T07/T08; nunca toca
 * Room/WorkManager/red (eso lo hace el ViewModel vía puertos).
 *
 * El estado de cada parte (`pending|processing|completed|failed`) vive en el
 * JSON de la parte, no en el manifest; por eso [ReaderModel.partStatuses]
 * conserva solo los estados ya vistos esta sesión (mapa ligero Int→estado,
 * nunca los documentos).
 */
internal object ReaderReducer {

    // ── Reanudación ──

    /** Objetivo de reanudación resuelto (paridad `getResumeTarget`). */
    data class ResumeTarget(
        val partId: Int,
        val tab: ReaderTab,
        val scrollSubsectionId: String?,
    )

    /**
     * Prioridad web: parte/tab explícitos de la ruta > `last_subsection`
     * válida (parte existente) > primera parte incompleta > primera parte.
     * `null` solo cuando no hay partes.
     */
    fun resolveResumeTarget(
        parts: List<PartDescriptor>,
        progress: ReadingProgress,
        requestedPartId: Int?,
        requestedTab: String,
    ): ResumeTarget? {
        if (parts.isEmpty()) return null

        requestedPartId?.let { partId ->
            if (parts.any { it.numero == partId }) {
                return ResumeTarget(partId = partId, tab = normalizeTab(requestedTab), scrollSubsectionId = null)
            }
        }

        val last = progress.lastSubsection
        if (last != null && parts.any { it.numero == last.partId }) {
            return ResumeTarget(
                partId = last.partId,
                tab = normalizeTab(last.tab.wireName),
                scrollSubsectionId = last.subsectionId,
            )
        }

        val firstIncomplete = parts.firstOrNull { it.numero !in progress.completedParts }
        return ResumeTarget(
            partId = firstIncomplete?.numero ?: parts.first().numero,
            tab = ReaderTab.EXPLANATION,
            scrollSubsectionId = null,
        )
    }

    /** Valores wire desconocidos se degradan a `explicacion` (paridad router). */
    fun normalizeTab(wireName: String): ReaderTab = ReaderTab.fromWire(wireName) ?: ReaderTab.EXPLANATION

    // ── Clasificación del contenido de parte ──

    /**
     * Estado de la parte desde el documento crudo: `loadPart == null` es
     * [PartContentUi.Missing]; una parte `pending`/`processing` sin ningún
     * contenido del agente es [PartContentUi.Processing]; `failed` sin
     * contenido es [PartContentUi.Failed]; cualquier otro caso es
     * [PartContentUi.Ready] (los tabs ausentes/error/malformado los resuelve
     * el parser de T08 por tab). Nunca deja pantalla vacía.
     */
    fun classifyPart(
        partId: Int,
        document: PartContentDocument?,
        parsed: ParsedPartContent?,
    ): PartContentUi = when {
        document == null -> PartContentUi.Missing(partId)
        parsed == null -> PartContentUi.LoadError
        parsed.allTabsMissing() -> when (document.status) {
            is PartStatus.Pending, is PartStatus.Processing -> PartContentUi.Processing(document.status)
            is PartStatus.Failed -> PartContentUi.Failed
            else -> PartContentUi.Ready(parsed)
        }
        else -> PartContentUi.Ready(parsed)
    }

    /**
     * El toggle de leída se ofrece solo en partes con contenido real
     * (paridad web `updateToggleCompleteButton`).
     */
    fun canTogglePart(status: PartStatus, partState: PartContentUi): Boolean = when (partState) {
        is PartContentUi.Ready -> status is PartStatus.Completed || partState.parsed.hasAnyContent()
        else -> status is PartStatus.Completed
    }

    private fun ParsedPartContent.allTabsMissing(): Boolean =
        explanation is PartRenderModel.Missing &&
            walkthrough is PartRenderModel.Missing &&
            resources is PartRenderModel.Missing &&
            diagram is PartRenderModel.Missing &&
            review is PartRenderModel.Missing

    private fun ParsedPartContent.hasAnyContent(): Boolean =
        listOf(explanation, walkthrough, resources, diagram, review).any { it !is PartRenderModel.Missing }

    // ── Modelo interno ──

    /**
     * Modelo interno del reducer: manifest ligero + selección + estado de la
     * parte cargada. `receivedManifest` distingue la primera emisión
     * (resuelve reanudación) de las actualizaciones de progreso/índice.
     */
    internal data class ReaderModel(
        val projectId: ProjectId,
        val name: String = "",
        val description: String? = null,
        val updatePossible: Boolean = false,
        val parts: List<PartDescriptor> = emptyList(),
        val progress: ReadingProgress = ReadingProgress(),
        val selectedPartId: Int? = null,
        val selectedTab: ReaderTab = ReaderTab.EXPLANATION,
        val partState: PartContentUi = PartContentUi.Loading,
        /** Estados de parte ya observados esta sesión (nunca los documentos). */
        val partStatuses: Map<Int, PartStatus> = emptyMap(),
        val descriptionExpanded: Boolean = false,
        val partSelectorOpen: Boolean = false,
        val scrollTarget: SubsectionScrollTarget? = null,
        val receivedManifest: Boolean = false,
        /** Fase de generación del tab `esquema`; null = sin operación. */
        val diagramGeneration: GenerationPhase? = null,
        /** Fase de generación del tab `repaso`; null = sin operación. */
        val reviewGeneration: GenerationPhase? = null,
    )

    // ── Emisiones del catálogo ──

    /**
     * Aplica el manifest (o actualiza progreso/índice). La primera emisión
     * resuelve la reanudación (ruta > last_subsection > primera incompleta >
     * primera). Si la parte seleccionada desaparece del índice, cae a la
     * primera disponible.
     */
    fun onProject(
        model: ReaderModel,
        project: ReaderProject,
        availability: ProjectAvailability?,
        requestedPartId: Int?,
        requestedTab: String,
    ): ReaderModel {
        var next = model.copy(
            name = project.name,
            description = project.description,
            parts = project.parts,
            progress = project.readingProgress,
            updatePossible = availability == ProjectAvailability.UPDATE_POSSIBLE,
        )
        if (!model.receivedManifest) {
            next = next.copy(receivedManifest = true)
            val target = resolveResumeTarget(project.parts, project.readingProgress, requestedPartId, requestedTab)
            if (target != null) {
                next = next.copy(
                    selectedPartId = target.partId,
                    selectedTab = target.tab,
                    scrollTarget = target.scrollSubsectionId?.let {
                        SubsectionScrollTarget(target.partId, it, target.tab)
                    },
                )
            }
        }
        val selected = next.selectedPartId
        if (selected != null && next.parts.isNotEmpty() && next.parts.none { it.numero == selected }) {
            next = next.copy(selectedPartId = next.parts.first().numero, scrollTarget = null)
        }
        return next
    }

    // ── Acciones ──

    /** Idempotente: misma parte solo cierra el selector, no resetea nada. */
    fun onPartSelected(model: ReaderModel, partId: Int): ReaderModel {
        val exists = model.parts.any { it.numero == partId }
        if (!exists) return model.copy(partSelectorOpen = false)
        if (partId == model.selectedPartId) return model.copy(partSelectorOpen = false)
        return model.copy(
            selectedPartId = partId,
            partState = PartContentUi.Loading,
            descriptionExpanded = false,
            partSelectorOpen = false,
            scrollTarget = null,
            // La fase de generación es por parte: al cambiar, se descarta (el
            // ViewModel cancela el job en curso; la fase no puede quedar
            // "Generating" para siempre de una parte que ya no se ve).
            diagramGeneration = null,
            reviewGeneration = null,
        )
    }

    /** Misma tab no resetea el contenido ni el scroll. */
    fun onTabSelected(model: ReaderModel, wireName: String): ReaderModel {
        val tab = normalizeTab(wireName)
        if (tab == model.selectedTab) return model
        return model.copy(selectedTab = tab)
    }

    fun onPreviousPart(model: ReaderModel): ReaderModel {
        val index = currentIndex(model) ?: return model
        if (index <= 0) return model
        return onPartSelected(model, model.parts[index - 1].numero)
    }

    fun onNextPart(model: ReaderModel): ReaderModel {
        val index = currentIndex(model) ?: return model
        if (index >= model.parts.lastIndex) return model
        return onPartSelected(model, model.parts[index + 1].numero)
    }

    /**
     * Toggle optimista de parte completa: se aplica al instante al progreso
     * visible; el ViewModel persiste la intención en el repositorio.
     */
    fun onToggleSectionComplete(model: ReaderModel, partId: Int): ReaderModel {
        if (model.parts.none { it.numero == partId }) return model
        val completed = model.progress.completedParts
        val next = if (partId in completed) completed - partId else completed + partId
        return model.copy(progress = model.progress.copy(completedParts = next))
    }

    fun onDescriptionToggled(model: ReaderModel): ReaderModel =
        model.copy(descriptionExpanded = !model.descriptionExpanded)

    fun onPartSelectorOpen(model: ReaderModel): ReaderModel =
        if (model.parts.isEmpty()) model else model.copy(partSelectorOpen = true)

    fun onPartSelectorClosed(model: ReaderModel): ReaderModel = model.copy(partSelectorOpen = false)

    fun onScrollTargetHandled(model: ReaderModel): ReaderModel = model.copy(scrollTarget = null)

    // ── Generación on-demand (T14) ──

    /**
     * Inicio de generación (diagram o review). DECISIÓN: solo se registra si
     * `partId == selectedPartId` — la generación siempre se lanza desde el
     * tab de la parte visible, y una generación de otra parte sería obsoleta
     * al completar. El ViewModel ya ignora la acción si la fase está activa;
     * aquí además la fase es por tab (diagram/review), así que ambos pueden
     * generarse de forma independiente.
     */
    fun onGenerationStarted(model: ReaderModel, partId: Int, diagram: Boolean): ReaderModel {
        if (partId != model.selectedPartId) return model
        return if (diagram) {
            model.copy(diagramGeneration = GenerationPhase.Generating)
        } else {
            model.copy(reviewGeneration = GenerationPhase.Generating)
        }
    }

    /** Éxito de generación (contenido ya persistido en Room): fase = null. */
    fun onGenerationSucceeded(model: ReaderModel, diagram: Boolean): ReaderModel =
        if (diagram) model.copy(diagramGeneration = null) else model.copy(reviewGeneration = null)

    /** Falla de generación categorizada: fase = Failed(reason). */
    fun onGenerationFailed(model: ReaderModel, diagram: Boolean, reason: GenerationFailureReason): ReaderModel =
        if (diagram) {
            model.copy(diagramGeneration = GenerationPhase.Failed(reason))
        } else {
            model.copy(reviewGeneration = GenerationPhase.Failed(reason))
        }

    /** Descartar el error y volver al contenido del tab: fase = null. */
    fun onGenerationDismissed(model: ReaderModel, diagram: Boolean): ReaderModel =
        if (diagram) model.copy(diagramGeneration = null) else model.copy(reviewGeneration = null)

    /** Inicio de carga (retry o reload): la parte pasa a Loading. */
    fun onPartLoadStarted(model: ReaderModel, partId: Int): ReaderModel =
        if (partId == model.selectedPartId) model.copy(partState = PartContentUi.Loading) else model

    /** Resultado de carga local: documento/parse (clasificado) o fallo. */
    fun onPartLoaded(
        model: ReaderModel,
        partId: Int,
        result: PartLoadResult,
    ): ReaderModel {
        if (partId != model.selectedPartId) return model
        val partState = when (result) {
            is PartLoadResult.Document -> classifyPart(partId, result.document, result.parsed)
            PartLoadResult.Missing -> PartContentUi.Missing(partId)
            PartLoadResult.Error -> PartContentUi.LoadError
        }
        val statuses = if (result is PartLoadResult.Document) {
            model.partStatuses + (partId to result.document.status)
        } else {
            model.partStatuses
        }
        return model.copy(partState = partState, partStatuses = statuses)
    }

    // ── Mapeo a UI ──

    fun toUiState(model: ReaderModel): ReaderUiState {
        if (!model.receivedManifest) return ReaderUiState.Loading
        val partId = model.selectedPartId
        val index = model.parts.indexOfFirst { it.numero == partId }
        return ReaderUiState.Content(
            ReaderContentUi(
                projectName = model.name,
                projectDescription = model.description,
                updatePossible = model.updatePossible,
                parts = model.parts.map { part ->
                    PartNavUi(
                        partId = part.numero,
                        title = part.titulo,
                        status = model.partStatuses[part.numero] ?: PartStatus.Unknown(""),
                        isRead = part.numero in model.progress.completedParts,
                        canToggle = part.numero == partId &&
                            canTogglePart(model.partStatuses[part.numero] ?: PartStatus.Unknown(""), model.partState),
                    )
                },
                selectedPartId = model.selectedPartId,
                selectedPartDescription = model.parts.firstOrNull { it.numero == partId }?.contenido.orEmpty(),
                selectedTab = model.selectedTab,
                partState = model.partState,
                completedParts = model.progress.completedParts,
                completedSubsections = model.progress.completedSubsections,
                lastSubsection = model.progress.lastSubsection,
                canGoPrevious = index > 0,
                canGoNext = index in 0 until model.parts.lastIndex,
                descriptionExpanded = model.descriptionExpanded,
                partSelectorOpen = model.partSelectorOpen,
                scrollTarget = model.scrollTarget,
                diagramGeneration = model.diagramGeneration,
                reviewGeneration = model.reviewGeneration,
            ),
        )
    }

    private fun currentIndex(model: ReaderModel): Int? =
        model.parts.indexOfFirst { it.numero == model.selectedPartId }.takeIf { it >= 0 }
}

/** Resultado de una carga local de parte. */
internal sealed interface PartLoadResult {
    data class Document(
        val document: PartContentDocument,
        val parsed: ParsedPartContent,
    ) : PartLoadResult

    data object Missing : PartLoadResult
    data object Error : PartLoadResult
}

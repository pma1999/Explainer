package com.explainer.app.ui.reader

import com.explainer.app.core.model.LastSubsection
import com.explainer.app.core.model.PartStatus
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.generation.GenerationFailureReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Reducer del lector (T10): reanudación (paridad web `getResumeTarget`),
 * transiciones de parte/tab, prev/next, toggle optimista, selector y
 * clasificación de estados de contenido. Puro y sin Android.
 */
class ReaderReducerTest {

    private val parts = listOf(partDescriptor(1), partDescriptor(2), partDescriptor(3))

    private fun progress(
        completedParts: Set<Int> = emptySet(),
        last: LastSubsection? = null,
    ): ReadingProgress = ReadingProgress(
        completedParts = completedParts,
        completedSubsections = emptySet(),
        lastSubsection = last,
    )

    private fun parsed(doc: com.explainer.app.core.model.PartContentDocument) =
        com.explainer.app.ui.content.PartContentParser.parse(doc)

    private fun model(
        parts: List<com.explainer.app.core.model.PartDescriptor> = this.parts,
        progress: ReadingProgress = ReadingProgress(),
        selectedPartId: Int? = null,
        partState: PartContentUi = PartContentUi.Loading,
        receivedManifest: Boolean = true,
        scrollTarget: SubsectionScrollTarget? = null,
        descriptionExpanded: Boolean = false,
    ): ReaderReducer.ReaderModel = ReaderReducer.ReaderModel(
        projectId = READER_PROJECT_ID,
        parts = parts,
        progress = progress,
        selectedPartId = selectedPartId,
        partState = partState,
        receivedManifest = receivedManifest,
        scrollTarget = scrollTarget,
        descriptionExpanded = descriptionExpanded,
        partStatuses = mapOf(1 to PartStatus.Completed),
    )

    // ── Reanudación ──

    @Test
    fun `resume con last_subsection valida usa su parte y tab y conserva scroll`() {
        val target = ReaderReducer.resolveResumeTarget(
            parts = parts,
            progress = progress(
                last = LastSubsection(2, "subsec-2-0-1", ReaderTab.WALKTHROUGH),
            ),
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        assertEquals(2, target!!.partId)
        assertEquals(ReaderTab.WALKTHROUGH, target.tab)
        assertEquals("subsec-2-0-1", target.scrollSubsectionId)
    }

    @Test
    fun `resume con last_subsection de parte inexistente cae a primera incompleta`() {
        val target = ReaderReducer.resolveResumeTarget(
            parts = parts,
            progress = progress(
                completedParts = setOf(1),
                last = LastSubsection(99, "subsec-99-0-0", ReaderTab.EXPLANATION),
            ),
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        assertEquals(2, target!!.partId)
        assertEquals(ReaderTab.EXPLANATION, target.tab)
        assertNull(target.scrollSubsectionId)
    }

    @Test
    fun `resume sin last_subsection abre la primera parte incompleta`() {
        val target = ReaderReducer.resolveResumeTarget(
            parts = parts,
            progress = progress(completedParts = setOf(1, 2)),
            requestedPartId = null,
            requestedTab = "esquema",
        )
        assertEquals(3, target!!.partId)
        assertEquals(ReaderTab.EXPLANATION, target.tab)
        assertNull(target.scrollSubsectionId)
    }

    @Test
    fun `resume con todas las partes completas abre la primera`() {
        val target = ReaderReducer.resolveResumeTarget(
            parts = parts,
            progress = progress(completedParts = setOf(1, 2, 3)),
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        assertEquals(1, target!!.partId)
        assertEquals(ReaderTab.EXPLANATION, target.tab)
    }

    @Test
    fun `resume con parte y tab explicitos de ruta gana a last_subsection`() {
        val target = ReaderReducer.resolveResumeTarget(
            parts = parts,
            progress = progress(last = LastSubsection(1, "subsec-1-0-0", ReaderTab.EXPLANATION)),
            requestedPartId = 3,
            requestedTab = "repaso",
        )
        assertEquals(3, target!!.partId)
        assertEquals(ReaderTab.REVIEW, target.tab)
        assertNull(target.scrollSubsectionId)
    }

    @Test
    fun `resume normaliza tab desconocida a explicacion`() {
        val target = ReaderReducer.resolveResumeTarget(
            parts = parts,
            progress = progress(last = LastSubsection(1, "subsec-1-0-0", ReaderTab.EXPLANATION)),
            requestedPartId = 2,
            requestedTab = "tab-inexistente",
        )
        assertEquals(ReaderTab.EXPLANATION, target!!.tab)
    }

    @Test
    fun `resume sin partes devuelve null`() {
        assertNull(
            ReaderReducer.resolveResumeTarget(
                parts = emptyList(),
                progress = ReadingProgress(),
                requestedPartId = null,
                requestedTab = "explicacion",
            ),
        )
    }

    // ── Emisiones del manifest ──

    @Test
    fun `primera emision de manifest resuelve reanudacion y fija scroll target`() {
        val m = ReaderReducer.onProject(
            model = model(receivedManifest = false),
            project = readerProject(
                parts = parts,
                progress = progress(last = LastSubsection(2, "subsec-2-1-0", ReaderTab.EXPLANATION)),
            ),
            availability = ProjectAvailability.OFFLINE,
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        assertTrue(m.receivedManifest)
        assertEquals(2, m.selectedPartId)
        assertEquals(SubsectionScrollTarget(2, "subsec-2-1-0", ReaderTab.EXPLANATION), m.scrollTarget)
    }

    @Test
    fun `emisiones posteriores del manifest conservan la seleccion`() {
        val first = ReaderReducer.onProject(
            model = model(receivedManifest = false),
            project = readerProject(parts = parts),
            availability = ProjectAvailability.OFFLINE,
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        val second = ReaderReducer.onProject(
            model = first.copy(partState = PartContentUi.Ready(parsed(partDocument(1)))),
            project = readerProject(
                parts = parts,
                progress = progress(completedParts = setOf(1)),
            ),
            availability = ProjectAvailability.OFFLINE,
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        assertEquals(1, second.selectedPartId)
        assertEquals(PartContentUi.Ready(parsed(partDocument(1))), second.partState)
        assertTrue(second.progress.completedParts.contains(1))
    }

    @Test
    fun `manifest sin la parte seleccionada cae a la primera disponible`() {
        val m = ReaderReducer.onProject(
            model = model(selectedPartId = 3, partState = PartContentUi.Ready(parsed(partDocument(3)))),
            project = readerProject(parts = listOf(partDescriptor(1), partDescriptor(2))),
            availability = ProjectAvailability.OFFLINE,
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        assertEquals(1, m.selectedPartId)
        assertNull(m.scrollTarget)
    }

    @Test
    fun `availability update possible activa el banner`() {
        val m = ReaderReducer.onProject(
            model = model(receivedManifest = false),
            project = readerProject(parts = parts),
            availability = ProjectAvailability.UPDATE_POSSIBLE,
            requestedPartId = null,
            requestedTab = "explicacion",
        )
        assertTrue(m.updatePossible)
        val state = ReaderReducer.toUiState(m) as ReaderUiState.Content
        assertTrue(state.model.updatePossible)
    }

    // ── Selección de parte y tab ──

    @Test
    fun `seleccionar la misma parte no resetea carga ni scroll`() {
        val ready = PartContentUi.Ready(parsed(partDocument(1)))
        val m = model(selectedPartId = 1, partState = ready, scrollTarget = SubsectionScrollTarget(1, "subsec-1-0-0", ReaderTab.EXPLANATION))
        val after = ReaderReducer.onPartSelected(m, 1)
        assertEquals(ready, after.partState)
        assertEquals(m.scrollTarget, after.scrollTarget)
        assertFalse(after.partSelectorOpen)
    }

    @Test
    fun `seleccionar otra parte pone Loading y limpia scroll y descripcion`() {
        val m = model(selectedPartId = 1, partState = PartContentUi.Ready(parsed(partDocument(1))), descriptionExpanded = true)
        val after = ReaderReducer.onPartSelected(m, 2)
        assertEquals(2, after.selectedPartId)
        assertEquals(PartContentUi.Loading, after.partState)
        assertFalse(after.descriptionExpanded)
        assertFalse(after.partSelectorOpen)
    }

    @Test
    fun `seleccionar parte inexistente se ignora`() {
        val m = model(selectedPartId = 1, partState = PartContentUi.Ready(parsed(partDocument(1))))
        val after = ReaderReducer.onPartSelected(m, 42)
        assertEquals(m.selectedPartId, after.selectedPartId)
        assertEquals(m.partState, after.partState)
    }

    @Test
    fun `cambio de tab conserva el contenido y no resetea la parte`() {
        val m = model(selectedPartId = 2, partState = PartContentUi.Ready(parsed(partDocument(2))))
        assertEquals(m, ReaderReducer.onTabSelected(m, "explicacion"))
        val after = ReaderReducer.onTabSelected(m, "recorrido")
        assertEquals(ReaderTab.WALKTHROUGH, after.selectedTab)
        assertEquals(m.partState, after.partState)
    }

    @Test
    fun `anterior y siguiente respetan los limites`() {
        val first = model(selectedPartId = 1, partState = PartContentUi.Ready(parsed(partDocument(1))))
        assertEquals(first, ReaderReducer.onPreviousPart(first))
        val last = model(selectedPartId = 3, partState = PartContentUi.Ready(parsed(partDocument(3))))
        assertEquals(last, ReaderReducer.onNextPart(last))

        val middle = model(selectedPartId = 2, partState = PartContentUi.Ready(parsed(partDocument(2))))
        val prev = ReaderReducer.onPreviousPart(middle)
        assertEquals(1, prev.selectedPartId)
        val next = ReaderReducer.onNextPart(middle)
        assertEquals(3, next.selectedPartId)

        val ui = ReaderReducer.toUiState(middle) as ReaderUiState.Content
        assertTrue(ui.model.canGoPrevious)
        assertTrue(ui.model.canGoNext)
        val uiFirst = ReaderReducer.toUiState(first) as ReaderUiState.Content
        assertFalse(uiFirst.model.canGoPrevious)
        val uiLast = ReaderReducer.toUiState(last) as ReaderUiState.Content
        assertFalse(uiLast.model.canGoNext)
    }

    @Test
    fun `toggle de parte completa es optimista y reversible`() {
        val m = model(selectedPartId = 1)
        val on = ReaderReducer.onToggleSectionComplete(m, 1)
        assertTrue(on.progress.completedParts.contains(1))
        val off = ReaderReducer.onToggleSectionComplete(on, 1)
        assertFalse(off.progress.completedParts.contains(1))
        assertEquals(m.progress.completedParts, off.progress.completedParts)
    }

    // ── Clasificación de contenido ──

    @Test
    fun `classify distingue missing, processing, failed y ready`() {
        assertEquals(PartContentUi.Missing(1), ReaderReducer.classifyPart(1, null, null))
        val processingDoc = partDocument(
            1,
            status = "processing",
            withExplainer = false,
            withWalkthrough = false,
            withResources = false,
            withReview = false,
            withMermaid = false,
        )
        assertEquals(
            PartContentUi.Processing(PartStatus.Processing),
            ReaderReducer.classifyPart(1, processingDoc, com.explainer.app.ui.content.PartContentParser.parse(processingDoc)),
        )
        val failedDoc = partDocument(
            1,
            status = "failed",
            withExplainer = false,
            withWalkthrough = false,
            withResources = false,
            withReview = false,
            withMermaid = false,
        )
        assertEquals(
            PartContentUi.Failed,
            ReaderReducer.classifyPart(1, failedDoc, com.explainer.app.ui.content.PartContentParser.parse(failedDoc)),
        )
        val readyDoc = partDocument(1, status = "completed")
        assertTrue(
            ReaderReducer.classifyPart(1, readyDoc, com.explainer.app.ui.content.PartContentParser.parse(readyDoc)) is PartContentUi.Ready,
        )
    }

    @Test
    fun `parte processing con contenido parcial es ready`() {
        val doc = partDocument(1, status = "processing", withWalkthrough = false, withResources = false, withReview = false, withMermaid = false)
        val parsed = com.explainer.app.ui.content.PartContentParser.parse(doc)
        assertTrue(ReaderReducer.classifyPart(1, doc, parsed) is PartContentUi.Ready)
    }

    @Test
    fun `parte processing sin ningun contenido es processing`() {
        val doc = partDocument(
            1,
            status = "processing",
            withExplainer = false,
            withWalkthrough = false,
            withResources = false,
            withReview = false,
            withMermaid = false,
        )
        val parsed = com.explainer.app.ui.content.PartContentParser.parse(doc)
        assertEquals(PartContentUi.Processing(PartStatus.Processing), ReaderReducer.classifyPart(1, doc, parsed))
    }

    @Test
    fun `onPartLoaded clasifica el documento y recuerda el estado de la parte`() {
        val m = model(selectedPartId = 1, partState = PartContentUi.Loading)
        val doc = partDocument(1, status = "completed")
        val after = ReaderReducer.onPartLoaded(
            m,
            1,
            PartLoadResult.Document(doc, com.explainer.app.ui.content.PartContentParser.parse(doc)),
        )
        assertTrue(after.partState is PartContentUi.Ready)
        assertEquals(PartStatus.Completed, after.partStatuses[1])
        val ui = ReaderReducer.toUiState(after) as ReaderUiState.Content
        val nav = ui.model.parts.first { it.partId == 1 }
        assertEquals(PartStatus.Completed, nav.status)
        assertTrue(nav.canToggle)
    }

    @Test
    fun `onPartLoaded con parte distinta a la seleccionada se ignora`() {
        val m = model(selectedPartId = 2, partState = PartContentUi.Ready(parsed(partDocument(2))))
        val after = ReaderReducer.onPartLoaded(m, 1, PartLoadResult.Error)
        assertEquals(m.partState, after.partState)
    }

    // ── UI: descripción, selector y scroll target ──

    @Test
    fun `description y selector abren y cierran`() {
        val m = model()
        assertTrue(ReaderReducer.onDescriptionToggled(m).descriptionExpanded)
        assertFalse(ReaderReducer.onDescriptionToggled(ReaderReducer.onDescriptionToggled(m)).descriptionExpanded)
        assertTrue(ReaderReducer.onPartSelectorOpen(m).partSelectorOpen)
        assertFalse(ReaderReducer.onPartSelectorClosed(ReaderReducer.onPartSelectorOpen(m)).partSelectorOpen)
        val empty = model(parts = emptyList(), receivedManifest = true)
        assertEquals(empty, ReaderReducer.onPartSelectorOpen(empty))
    }

    @Test
    fun `scroll target handled lo limpia`() {
        val m = model(scrollTarget = SubsectionScrollTarget(1, "subsec-1-0-0", ReaderTab.EXPLANATION))
        assertNull(ReaderReducer.onScrollTargetHandled(m).scrollTarget)
    }

    @Test
    fun `toUiState es Loading antes del manifest y Content despues`() {
        assertEquals(ReaderUiState.Loading, ReaderReducer.toUiState(model(receivedManifest = false)))
        val ui = ReaderReducer.toUiState(model(selectedPartId = 1))
        assertTrue(ui is ReaderUiState.Content)
        val content = (ui as ReaderUiState.Content).model
        assertEquals(3, content.parts.size)
        assertEquals(1, content.selectedPartId)
        assertEquals(ReaderTab.EXPLANATION, content.selectedTab)
        assertNotNull(content.projectName)
    }

    // ── Generación on-demand (T14) ──

    @Test
    fun `inicio de generacion pone la fase Generating del tab correcto`() {
        val m = model(selectedPartId = 2)
        val diagram = ReaderReducer.onGenerationStarted(m, 2, diagram = true)
        assertEquals(GenerationPhase.Generating, diagram.diagramGeneration)
        assertNull(diagram.reviewGeneration)

        val review = ReaderReducer.onGenerationStarted(m, 2, diagram = false)
        assertEquals(GenerationPhase.Generating, review.reviewGeneration)
        assertNull(review.diagramGeneration)
    }

    @Test
    fun `inicio de generacion de otra parte se ignora`() {
        val m = model(selectedPartId = 2)
        val after = ReaderReducer.onGenerationStarted(m, 1, diagram = true)
        assertNull(after.diagramGeneration)
        assertEquals(m, after)
    }

    @Test
    fun `exito de generacion limpia la fase del tab`() {
        val m = model(selectedPartId = 1)
        val started = ReaderReducer.onGenerationStarted(m, 1, diagram = true)
        assertEquals(GenerationPhase.Generating, started.diagramGeneration)
        val done = ReaderReducer.onGenerationSucceeded(started, diagram = true)
        assertNull(done.diagramGeneration)
        // La fase del otro tab no se toca.
        val both = ReaderReducer.onGenerationStarted(started, 1, diagram = false)
        val reviewDone = ReaderReducer.onGenerationSucceeded(both, diagram = false)
        assertEquals(GenerationPhase.Generating, reviewDone.diagramGeneration)
        assertNull(reviewDone.reviewGeneration)
    }

    @Test
    fun `fallo de generacion categoriza la fase Failed`() {
        val m = model(selectedPartId = 1)
        val failed = ReaderReducer.onGenerationFailed(m, diagram = false, reason = GenerationFailureReason.AUTH)
        assertEquals(GenerationPhase.Failed(GenerationFailureReason.AUTH), failed.reviewGeneration)
        assertNull(failed.diagramGeneration)
    }

    @Test
    fun `dismiss descarta la fase de error`() {
        val m = model(selectedPartId = 1)
        val failed = ReaderReducer.onGenerationFailed(m, diagram = true, reason = GenerationFailureReason.RATE_LIMITED)
        assertEquals(GenerationPhase.Failed(GenerationFailureReason.RATE_LIMITED), failed.diagramGeneration)
        val dismissed = ReaderReducer.onGenerationDismissed(failed, diagram = true)
        assertNull(dismissed.diagramGeneration)
    }

    @Test
    fun `cambio de parte limpia ambas fases de generacion`() {
        val m = model(selectedPartId = 1)
        val started = ReaderReducer.onGenerationStarted(
            ReaderReducer.onGenerationStarted(m, 1, diagram = true),
            1,
            diagram = false,
        )
        assertEquals(GenerationPhase.Generating, started.diagramGeneration)
        assertEquals(GenerationPhase.Generating, started.reviewGeneration)

        val next = ReaderReducer.onPartSelected(started, 2)

        assertNull(next.diagramGeneration)
        assertNull(next.reviewGeneration)
        assertEquals(2, next.selectedPartId)
        assertEquals(PartContentUi.Loading, next.partState)
    }

    @Test
    fun `las fases viajan al estado UI por tab`() {
        val m = model(selectedPartId = 1)
        val started = ReaderReducer.onGenerationStarted(m, 1, diagram = true)
        val ui = ReaderReducer.toUiState(started) as ReaderUiState.Content
        assertEquals(GenerationPhase.Generating, ui.model.diagramGeneration)
        assertNull(ui.model.reviewGeneration)
    }
}

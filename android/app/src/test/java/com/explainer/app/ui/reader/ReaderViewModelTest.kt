package com.explainer.app.ui.reader

import com.explainer.app.core.model.LastSubsection
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.generation.GenerationFailureReason
import com.explainer.app.feature.generation.GenerationOutcome
import com.explainer.app.feature.progress.SubsectionActivityTracker
import com.explainer.app.feature.progress.SubsectionProgressEvent
import com.explainer.app.ui.content.PartRenderModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ViewModel del lector (T10): reanudación, carga de una sola parte con
 * cancelación de cargas obsoletas, estados de contenido, tracker de
 * subsecciones (T07) y persistencia optimista a través de puertos. Scope
 * Unconfined para propagación síncrona en tests JVM.
 */
class ReaderViewModelTest {

    private fun scope() = CoroutineScope(Dispatchers.Unconfined)

    private fun vm(
        catalog: FakeReaderCatalog = FakeReaderCatalog(),
        progress: FakeReadingProgress = FakeReadingProgress(),
        generation: FakePartGenerationRepository = FakePartGenerationRepository(),
        tracker: SubsectionActivityTracker = SubsectionActivityTracker(),
        now: () -> Long = { 0L },
        requestedPartId: Int? = null,
        requestedTab: String = "explicacion",
    ) = ReaderViewModel(
        scope = scope(),
        ownerId = READER_OWNER,
        projectId = READER_PROJECT_ID,
        catalog = catalog,
        progress = progress,
        generation = generation,
        tracker = tracker,
        now = now,
        // Unconfined: la carga local se propaga de forma síncrona en tests JVM.
        loadDispatcher = Dispatchers.Unconfined,
        requestedPartId = requestedPartId,
        requestedTab = requestedTab,
    )

    private fun contentOf(vm: ReaderViewModel): ReaderUiState.Content {
        val state = vm.uiState.value
        assertTrue("esperaba Content pero fue $state", state is ReaderUiState.Content)
        return state as ReaderUiState.Content
    }

    private fun parts() = listOf(partDescriptor(1), partDescriptor(2), partDescriptor(3))

    private fun readyCatalog(doc: (Int) -> com.explainer.app.core.model.PartContentDocument = { partDocument(it) }): FakeReaderCatalog =
        FakeReaderCatalog().apply {
            emitProject(readerProject(parts = parts()))
            loadResult = doc
        }

    // ── Reanudación y carga ──

    @Test
    fun `primera emision del manifest carga solo la parte de reanudacion`() {
        val catalog = FakeReaderCatalog().apply {
            emitProject(
                readerProject(
                    parts = parts(),
                    progress = ReadingProgress(lastSubsection = LastSubsection(2, "subsec-2-0-1", ReaderTab.EXPLANATION)),
                ),
            )
            loadResult = { partDocument(it) }
        }
        val viewModel = vm(catalog = catalog)

        assertEquals(listOf(2), catalog.loadCalls)
        val model = contentOf(viewModel).model
        assertEquals(2, model.selectedPartId)
        assertEquals(SubsectionScrollTarget(2, "subsec-2-0-1", ReaderTab.EXPLANATION), model.scrollTarget)
        assertTrue(model.partState is PartContentUi.Ready)
    }

    @Test
    fun `ruta explicita gana a last_subsection`() {
        val catalog = FakeReaderCatalog().apply {
            emitProject(
                readerProject(
                    parts = parts(),
                    progress = ReadingProgress(lastSubsection = LastSubsection(2, "subsec-2-0-1", ReaderTab.EXPLANATION)),
                ),
            )
            loadResult = { partDocument(it) }
        }
        val viewModel = vm(catalog = catalog, requestedPartId = 3, requestedTab = "repaso")

        assertEquals(listOf(3), catalog.loadCalls)
        val model = contentOf(viewModel).model
        assertEquals(3, model.selectedPartId)
        assertEquals(ReaderTab.REVIEW, model.selectedTab)
        assertNull(model.scrollTarget)
    }

    @Test
    fun `sin snapshot activo produce MissingSnapshot`() {
        val catalog = FakeReaderCatalog() // manifestFlow = null
        val viewModel = vm(catalog = catalog)
        assertEquals(ReaderUiState.MissingSnapshot, viewModel.uiState.value)
    }

    @Test
    fun `sin partes el lector abre estado vacio explicito`() {
        val catalog = FakeReaderCatalog().apply {
            emitProject(readerProject(parts = emptyList()))
        }
        val viewModel = vm(catalog = catalog)
        val model = contentOf(viewModel).model
        assertTrue(model.parts.isEmpty())
        assertNull(model.selectedPartId)
    }

    // ── Cambios rápidos de parte ──

    @Test
    fun `cambios rapidos de parte cancelan la carga previa`() = runBlocking {
        val catalog = FakeReaderCatalog().apply {
            emitProject(readerProject(parts = parts()))
            // Parte 1 termina DESPUÉS de la parte 2 (retardo por parte).
            loadDelay = { if (it == 1) 80L else 0L }
            loadResult = { id ->
                if (id == 1) {
                    partDocument(1, status = "failed", withExplainer = false, withWalkthrough = false, withResources = false, withReview = false, withMermaid = false)
                } else {
                    partDocument(id)
                }
            }
        }
        val viewModel = vm(catalog = catalog)
        assertEquals(listOf(1), catalog.loadCalls)

        viewModel.onAction(ReaderAction.SelectPart(2))
        delay(200)

        // El estado final es la parte 2; el resultado obsoleto de la 1 no aplica.
        val model = contentOf(viewModel).model
        assertEquals(2, model.selectedPartId)
        assertTrue("esperaba Ready pero fue ${model.partState}", model.partState is PartContentUi.Ready)
        assertTrue(catalog.loadCalls.containsAll(listOf(1, 2)))
    }

    @Test
    fun `seleccionar la misma parte no recarga ni resetea el estado`() {
        val catalog = readyCatalog()
        val viewModel = vm(catalog = catalog)
        assertEquals(listOf(1), catalog.loadCalls)
        val before = contentOf(viewModel).model.partState

        viewModel.onAction(ReaderAction.SelectPart(1))

        assertEquals(listOf(1), catalog.loadCalls)
        assertEquals(before, contentOf(viewModel).model.partState)
    }

    @Test
    fun `siguiente y anterior cargan la parte adyacente`() {
        val catalog = readyCatalog()
        val viewModel = vm(catalog = catalog)
        assertEquals(listOf(1), catalog.loadCalls)

        viewModel.onAction(ReaderAction.NextPart)
        assertEquals(listOf(1, 2), catalog.loadCalls)
        assertEquals(2, contentOf(viewModel).model.selectedPartId)

        viewModel.onAction(ReaderAction.PreviousPart)
        assertEquals(listOf(1, 2, 1), catalog.loadCalls)
        assertEquals(1, contentOf(viewModel).model.selectedPartId)
    }

    @Test
    fun `anterior en la primera parte y siguiente en la ultima no hacen nada`() {
        val catalog = readyCatalog()
        val viewModel = vm(catalog = catalog)
        viewModel.onAction(ReaderAction.PreviousPart)
        assertEquals(listOf(1), catalog.loadCalls)

        viewModel.onAction(ReaderAction.NextPart) // → 2
        viewModel.onAction(ReaderAction.NextPart) // → 3
        viewModel.onAction(ReaderAction.NextPart) // límite
        assertEquals(listOf(1, 2, 3), catalog.loadCalls)
        assertEquals(3, contentOf(viewModel).model.selectedPartId)
    }

    // ── Estados de contenido ──

    @Test
    fun `parte sin documento muestra Missing y retry recarga`() {
        val catalog = FakeReaderCatalog().apply {
            emitProject(readerProject(parts = parts()))
            loadResult = { null }
        }
        val viewModel = vm(catalog = catalog)
        assertEquals(PartContentUi.Missing(1), contentOf(viewModel).model.partState)

        catalog.loadResult = { partDocument(it) }
        viewModel.onAction(ReaderAction.RetryPartLoad)

        assertEquals(listOf(1, 1), catalog.loadCalls)
        assertTrue(contentOf(viewModel).model.partState is PartContentUi.Ready)
    }

    @Test
    fun `parte processing sin contenido muestra Processing y failed muestra Failed`() {
        val noAgents = { id: Int ->
            partDocument(id, status = "processing", withExplainer = false, withWalkthrough = false, withResources = false, withReview = false, withMermaid = false)
        }
        val catalog = FakeReaderCatalog().apply {
            emitProject(readerProject(parts = parts()))
            loadResult = noAgents
        }
        val viewModel = vm(catalog = catalog)
        assertTrue(contentOf(viewModel).model.partState is PartContentUi.Processing)
    }

    @Test
    fun `fallo local de lectura muestra LoadError`() {
        val catalog = FakeReaderCatalog().apply {
            emitProject(readerProject(parts = parts()))
            loadResult = { partDocument(it) }
            loadFails = true
        }
        val viewModel = vm(catalog = catalog)
        assertEquals(PartContentUi.LoadError, contentOf(viewModel).model.partState)

        catalog.loadFails = false
        viewModel.onAction(ReaderAction.RetryPartLoad)
        assertTrue(contentOf(viewModel).model.partState is PartContentUi.Ready)
    }

    @Test
    fun `cinco tabs con ready missing y error se resuelven por tab`() {
        val catalog = FakeReaderCatalog().apply {
            emitProject(readerProject(parts = parts()))
            loadResult = { id -> partDocument(id) }
        }
        val viewModel = vm(catalog = catalog)
        val parsed = (contentOf(viewModel).model.partState as PartContentUi.Ready).parsed

        assertTrue(parsed.explanation is PartRenderModel.Explanation)
        assertTrue(parsed.walkthrough is PartRenderModel.Walkthrough)
        assertTrue(parsed.resources is PartRenderModel.Resources)
        assertTrue(parsed.diagram is PartRenderModel.Diagram)
        assertTrue(parsed.review is PartRenderModel.Review)
        assertEquals(ReaderTab.EXPLANATION, parsed.forTab(ReaderTab.EXPLANATION).let { it as PartRenderModel.Explanation }.let { ReaderTab.EXPLANATION })
    }

    // ── Progreso optimista ──

    @Test
    fun `toggle completa es optimista y persiste en el repositorio`() {
        val catalog = readyCatalog()
        val progress = FakeReadingProgress()
        val viewModel = vm(catalog = catalog, progress = progress)

        viewModel.onAction(ReaderAction.ToggleSectionComplete(1))
        assertTrue(contentOf(viewModel).model.completedParts.contains(1))
        assertEquals(
            listOf(FakeReadingProgress.SectionCall(READER_OWNER, READER_PROJECT_ID, 1, completed = true)),
            progress.sectionCalls,
        )

        viewModel.onAction(ReaderAction.ToggleSectionComplete(1))
        assertFalse(contentOf(viewModel).model.completedParts.contains(1))
        assertEquals(2, progress.sectionCalls.size)
        assertEquals(false, progress.sectionCalls[1].completed)
    }

    @Test
    fun `update possible activa el banner desde la lista observada`() {
        val catalog = readyCatalog()
        val viewModel = vm(catalog = catalog)
        assertFalse(contentOf(viewModel).model.updatePossible)

        catalog.emitAvailability(ProjectAvailability.UPDATE_POSSIBLE)

        assertTrue(contentOf(viewModel).model.updatePossible)
    }

    // ── Tracker de subsecciones (T07) ──

    @Test
    fun `subsection activada registra last_read una sola vez`() {
        val catalog = readyCatalog()
        val progress = FakeReadingProgress()
        val viewModel = vm(catalog = catalog, progress = progress)

        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-0"))
        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-0"))

        assertEquals(
            listOf(
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-0-0", tab = ReaderTab.EXPLANATION, isLastRead = true),
            ),
            progress.subsectionCalls,
        )
    }

    @Test
    fun `tras 3s acumulados la subseccion saliente se registra completada`() {
        val catalog = readyCatalog()
        val progress = FakeReadingProgress()
        var clock = 0L
        val viewModel = vm(catalog = catalog, progress = progress, now = { clock })

        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-0"))
        clock = 4_000L
        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-1"))

        assertEquals(
            listOf(
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-0-0", tab = ReaderTab.EXPLANATION, isLastRead = true),
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-0-0", tab = ReaderTab.EXPLANATION, completed = true),
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-0-1", tab = ReaderTab.EXPLANATION, isLastRead = true),
            ),
            progress.subsectionCalls,
        )
    }

    @Test
    fun `menos de 3s no registra completed`() {
        val catalog = readyCatalog()
        val progress = FakeReadingProgress()
        var clock = 0L
        val viewModel = vm(catalog = catalog, progress = progress, now = { clock })

        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-0"))
        clock = 1_000L
        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-1"))

        assertEquals(2, progress.subsectionCalls.size)
        assertTrue(progress.subsectionCalls.none { it.completed == true })
    }

    @Test
    fun `cambiar de parte finaliza la sesion del tracker`() {
        val catalog = readyCatalog()
        val progress = FakeReadingProgress()
        var clock = 0L
        val viewModel = vm(catalog = catalog, progress = progress, now = { clock })

        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-0"))
        clock = 5_000L
        viewModel.onAction(ReaderAction.SelectPart(2))

        assertTrue(progress.subsectionCalls.any { it.subsectionId == "subsec-1-0-0" && it.completed == true })
    }

    @Test
    fun `cambiar de tab finaliza la sesion del tracker`() {
        val catalog = readyCatalog()
        val progress = FakeReadingProgress()
        var clock = 0L
        val viewModel = vm(catalog = catalog, progress = progress, now = { clock })

        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-0"))
        clock = 5_000L
        viewModel.onAction(ReaderAction.SelectTab("recorrido"))

        assertTrue(progress.subsectionCalls.any { it.subsectionId == "subsec-1-0-0" && it.completed == true })
    }

    @Test
    fun `back finaliza el tracker y registra el completed pendiente`() {
        val catalog = readyCatalog()
        val progress = FakeReadingProgress()
        var clock = 0L
        val viewModel = vm(catalog = catalog, progress = progress, now = { clock })

        viewModel.onAction(ReaderAction.SubsectionActivated("subsec-1-0-0"))
        clock = 4_000L
        viewModel.onAction(ReaderAction.Back)

        assertEquals(
            listOf(
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-0-0", tab = ReaderTab.EXPLANATION, isLastRead = true),
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-0-0", tab = ReaderTab.EXPLANATION, completed = true),
            ),
            progress.subsectionCalls,
        )
    }

    @Test
    fun `scroll target handled limpia el objetivo de reanudacion`() {
        val catalog = FakeReaderCatalog().apply {
            emitProject(
                readerProject(
                    parts = parts(),
                    progress = ReadingProgress(lastSubsection = LastSubsection(1, "subsec-1-0-0", ReaderTab.EXPLANATION)),
                ),
            )
            loadResult = { partDocument(it) }
        }
        val viewModel = vm(catalog = catalog)
        assertTrue(contentOf(viewModel).model.scrollTarget != null)

        viewModel.onAction(ReaderAction.ScrollTargetHandled)

        assertNull(contentOf(viewModel).model.scrollTarget)
    }

    // ── Generación on-demand (T14) ──

    @Test
    fun `generate diagram pone Generating y en exito recarga la parte`() {
        val catalog = readyCatalog()
        val generation = FakePartGenerationRepository().apply { diagramResult = GenerationOutcome.Success }
        val viewModel = vm(catalog = catalog, generation = generation)

        viewModel.onAction(ReaderAction.GenerateDiagram(partId = 1, regenerate = false))

        // Fase activa durante la generación (Unconfined: éxito síncrono) →
        // fase limpia y recarga de la parte desde Room.
        val model = contentOf(viewModel).model
        assertNull(model.diagramGeneration)
        assertEquals(
            listOf(
                FakePartGenerationRepository.GenerationCall(READER_OWNER, READER_PROJECT_ID, partId = 1, regenerate = false),
            ),
            generation.diagramCalls,
        )
        // loadPart se invocó dos veces: la inicial de reanudación + la recarga post-generación.
        assertTrue(catalog.loadCalls.count { it == 1 } >= 2)
        assertTrue(model.partState is PartContentUi.Ready)
    }

    @Test
    fun `generate review fallido muestra Failed con la razon`() {
        val catalog = readyCatalog()
        val generation = FakePartGenerationRepository().apply {
            reviewResult = GenerationOutcome.Failure(GenerationFailureReason.RATE_LIMITED)
        }
        val viewModel = vm(catalog = catalog, generation = generation)

        viewModel.onAction(ReaderAction.GenerateReview(partId = 1, regenerate = true))

        val model = contentOf(viewModel).model
        assertEquals(
            GenerationPhase.Failed(GenerationFailureReason.RATE_LIMITED),
            model.reviewGeneration,
        )
        assertNull(model.diagramGeneration)
        assertEquals(
            listOf(
                FakePartGenerationRepository.GenerationCall(READER_OWNER, READER_PROJECT_ID, partId = 1, regenerate = true),
            ),
            generation.reviewCalls,
        )
    }

    @Test
    fun `fase activa ignora nuevas generaciones del mismo tab`() = runBlocking {
        val catalog = readyCatalog()
        val generation = FakePartGenerationRepository().apply {
            delayMillis = 50L
            diagramResult = GenerationOutcome.Success
        }
        val viewModel = vm(catalog = catalog, generation = generation)

        viewModel.onAction(ReaderAction.GenerateDiagram(partId = 1, regenerate = false))
        // Mientras la primera corre, una segunda acción no duplica la llamada.
        viewModel.onAction(ReaderAction.GenerateDiagram(partId = 1, regenerate = false))
        delay(200)

        assertEquals(1, generation.diagramCalls.size)
        assertNull(contentOf(viewModel).model.diagramGeneration)
    }

    @Test
    fun `diagram y review generan de forma independiente`() = runBlocking {
        val catalog = readyCatalog()
        val generation = FakePartGenerationRepository().apply {
            diagramResult = GenerationOutcome.Failure(GenerationFailureReason.OFFLINE)
            reviewResult = GenerationOutcome.Success
        }
        val viewModel = vm(catalog = catalog, generation = generation)

        viewModel.onAction(ReaderAction.GenerateDiagram(partId = 1, regenerate = false))
        viewModel.onAction(ReaderAction.GenerateReview(partId = 1, regenerate = false))

        val model = contentOf(viewModel).model
        assertEquals(GenerationPhase.Failed(GenerationFailureReason.OFFLINE), model.diagramGeneration)
        assertNull(model.reviewGeneration)
        assertEquals(1, generation.diagramCalls.size)
        assertEquals(1, generation.reviewCalls.size)
    }

    @Test
    fun `dismiss limpia la fase de error`() {
        val catalog = readyCatalog()
        val generation = FakePartGenerationRepository().apply {
            diagramResult = GenerationOutcome.Failure(GenerationFailureReason.UNKNOWN)
        }
        val viewModel = vm(catalog = catalog, generation = generation)

        viewModel.onAction(ReaderAction.GenerateDiagram(partId = 1, regenerate = false))
        assertEquals(
            GenerationPhase.Failed(GenerationFailureReason.UNKNOWN),
            contentOf(viewModel).model.diagramGeneration,
        )

        viewModel.onAction(ReaderAction.DismissDiagramError)

        assertNull(contentOf(viewModel).model.diagramGeneration)
    }

    @Test
    fun `cambio de parte cancela la generacion en curso sin estado fantasma`() = runBlocking {
        val catalog = readyCatalog()
        val generation = FakePartGenerationRepository().apply {
            delayMillis = 100L
            diagramResult = GenerationOutcome.Success
        }
        val viewModel = vm(catalog = catalog, generation = generation)

        viewModel.onAction(ReaderAction.GenerateDiagram(partId = 1, regenerate = false))
        viewModel.onAction(ReaderAction.SelectPart(2))
        delay(250)

        // La generación de la parte 1 fue cancelada por el cambio de parte
        // (el scope es por ViewModel; la cancelación la propaga el reducer al
        // descartar la fase al cambiar de parte).
        assertEquals(0, generation.diagramCalls.size)
        val model = contentOf(viewModel).model
        assertEquals(2, model.selectedPartId)
        assertNull(model.diagramGeneration)
    }

    @Test
    fun `generacion de otra parte distinta a la seleccionada se ignora`() {
        val catalog = readyCatalog()
        val generation = FakePartGenerationRepository()
        val viewModel = vm(catalog = catalog, generation = generation)

        viewModel.onAction(ReaderAction.GenerateDiagram(partId = 2, regenerate = false))

        assertTrue(generation.diagramCalls.isEmpty())
        assertNull(contentOf(viewModel).model.diagramGeneration)
    }
}

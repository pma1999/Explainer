package com.explainer.app.ui.library

import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.feature.catalog.RefreshOutcome
import com.explainer.app.feature.catalog.ReaderProject
import com.explainer.app.feature.download.DownloadCoordinator
import com.explainer.app.feature.download.DownloadState
import com.explainer.app.feature.download.EnqueueResult
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf

/** Owner de sesión de los tests (UUID válido). */
val TEST_OWNER: String = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

/** ID de proyecto válido de los tests. */
val TEST_PROJECT_ID: ProjectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")

/** Segundo proyecto de los tests. */
val TEST_PROJECT_ID_2: ProjectId = ProjectId("4e8d9c2f-1b5a-4c6d-9e3f-2a7b8c0d1e2f")

/**
 * Item de catálogo con defaults seguros; los tests ajustan solo lo que
 * verifican (mismo enfoque que los fixtures de T03/T06/T07).
 */
fun testItem(
    projectId: ProjectId = TEST_PROJECT_ID,
    name: String = "Proyecto de prueba",
    status: ProjectStatus = ProjectStatus.Completed,
    availability: ProjectAvailability = ProjectAvailability.REMOTE_ONLY,
    updatedAt: String = "2026-08-01T10:00:00Z",
    partCount: Int = 3,
    segmentationSourceBytes: Long = 100_000L,
    snapshotBytes: Long = 0L,
    description: String? = null,
): ProjectListItem = ProjectListItem(
    projectId = projectId,
    name = name,
    description = description,
    status = status,
    sourceType = "pdf",
    pdfFilename = null,
    createdAt = "2026-07-01T10:00:00Z",
    updatedAt = updatedAt,
    partCount = partCount,
    segmentationSourceBytes = segmentationSourceBytes,
    snapshotBytes = snapshotBytes,
    readingProgress = ReadingProgress(),
    availability = availability,
)

/** Catálogo falso: lista observable + refresh con resultado programable. */
class FakeCatalog : ProjectCatalogRepository {
    val itemsFlow = MutableStateFlow<List<ProjectListItem>>(emptyList())
    var refreshOutcome: RefreshOutcome = RefreshOutcome.Success(0)
    val refreshCalls = mutableListOf<String>()
    var refreshDelayMillis: Long = 0L

    fun emit(items: List<ProjectListItem>) {
        itemsFlow.value = items
    }

    override fun observeProjects(ownerId: String): Flow<List<ProjectListItem>> = itemsFlow

    override suspend fun refresh(ownerId: String): RefreshOutcome {
        refreshCalls.add(ownerId)
        if (refreshDelayMillis > 0L) {
            // Suspensión real: con scope Unconfined un Thread.sleep bloquearía
            // el hilo del test y el refresh terminaría antes de las aserciones
            // de "no relanza mientras refresca".
            delay(refreshDelayMillis)
        }
        return refreshOutcome
    }

    override fun observeReaderProject(ownerId: String, projectId: ProjectId): Flow<ReaderProject?> =
        flowOf(null)

    override suspend fun loadPart(ownerId: String, projectId: ProjectId, partId: Int): PartContentDocument? = null
}

/**
 * Coordinador de descargas falso: un estado observable por proyecto;
 * cancel/delete actualizan el flujo como el coordinador real (fila
 * terminal) y registran las llamadas. [activeObservers] cuenta los
 * collectors activos por proyecto (R-T11-05): la reconciliación del
 * ViewModel debe cancelarlos cuando el proyecto sale del catálogo.
 */
class FakeDownloadCoordinator : DownloadCoordinator {
    val states = mutableMapOf<String, MutableStateFlow<DownloadState>>()
    var enqueueResult: EnqueueResult = EnqueueResult.Enqueued
    val enqueueCalls = mutableListOf<String>()
    val cancelCalls = mutableListOf<String>()
    val deleteCalls = mutableListOf<String>()
    val activeObservers = mutableMapOf<String, Int>()

    fun stateFor(projectId: ProjectId): MutableStateFlow<DownloadState> =
        states.getOrPut(projectId.value) {
            MutableStateFlow(DownloadState.Queued(projectId, requestedAt = 0L))
        }

    fun emit(projectId: ProjectId, state: DownloadState) {
        stateFor(projectId).value = state
    }

    override fun observe(ownerId: String, projectId: ProjectId): Flow<DownloadState> {
        val upstream = stateFor(projectId)
        return flow {
            activeObservers[projectId.value] = (activeObservers[projectId.value] ?: 0) + 1
            try {
                emitAll(upstream)
            } finally {
                activeObservers[projectId.value] = (activeObservers[projectId.value] ?: 1) - 1
            }
        }
    }

    override suspend fun enqueue(ownerId: String, projectId: ProjectId): EnqueueResult {
        enqueueCalls.add(projectId.value)
        return enqueueResult
    }

    override suspend fun cancel(ownerId: String, projectId: ProjectId) {
        cancelCalls.add(projectId.value)
        emit(projectId, DownloadState.Cancelled(projectId))
    }

    override suspend fun deleteLocal(ownerId: String, projectId: ProjectId) {
        deleteCalls.add(projectId.value)
        emit(projectId, DownloadState.Cancelled(projectId))
    }
}

package com.explainer.app.ui.reader

import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.PartDescriptor
import com.explainer.app.core.model.PartStatus
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.remote.contract.PartContentContract
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.catalog.ProjectCatalogRepository
import com.explainer.app.feature.catalog.ProjectListItem
import com.explainer.app.feature.catalog.RefreshOutcome
import com.explainer.app.feature.catalog.ReaderProject
import com.explainer.app.feature.generation.GenerationFailureReason
import com.explainer.app.feature.generation.GenerationOutcome
import com.explainer.app.feature.generation.PartGenerationRepository
import com.explainer.app.feature.progress.ReadingProgressRepository
import com.explainer.app.feature.progress.SubsectionProgressEvent
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/** Owner de sesión de los tests del lector (UUID válido). */
val READER_OWNER: String = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

/** ID de proyecto válido de los tests del lector. */
val READER_PROJECT_ID: ProjectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")

/** Parte de manifest con defaults seguros. */
fun partDescriptor(numero: Int, titulo: String = "Sección $numero", contenido: String = "Contenido de $numero"): PartDescriptor =
    PartDescriptor(numero = numero, titulo = titulo, contenido = contenido)

/** ReaderProject de tests: manifest + progreso mezclado (T07). */
fun readerProject(
    projectId: ProjectId = READER_PROJECT_ID,
    name: String = "Proyecto de prueba",
    description: String? = "Descripción del proyecto",
    parts: List<PartDescriptor> = listOf(partDescriptor(1), partDescriptor(2), partDescriptor(3)),
    progress: ReadingProgress = ReadingProgress(),
    updatedAt: String = "2026-08-01T10:00:00Z",
    status: ProjectStatus = ProjectStatus.Completed,
): ReaderProject = ReaderProject(
    projectId = projectId,
    name = name,
    description = description,
    status = status,
    sourceType = "pdf",
    parts = parts,
    readingProgress = progress,
    updatedAt = updatedAt,
    totalBytes = 100_000L,
    downloadedAt = 42L,
    activeGeneration = "gen-1",
)

/** JSON crudo de una parte; los campos de agente se incluyen bajo demanda. */
fun partRawJson(
    status: String = "completed",
    withExplainer: Boolean = true,
    withWalkthrough: Boolean = true,
    withResources: Boolean = true,
    withReview: Boolean = true,
    withMermaid: Boolean = true,
): String {
    val agents = buildString {
        if (withExplainer) {
            append(
                """
                ,"explainer":{"introduccion":"Intro","desarrollo":[
                  {"titulo_seccion":"Sección A","explicacion_introductoria":null,
                   "subsecciones":[{"titulo_subseccion":"Sub A1","explicacion_detallada":"Detalle A1"},
                                   {"titulo_subseccion":"Sub A2","explicacion_detallada":"Detalle A2"}]},
                  {"titulo_seccion":"Sección B","explicacion_introductoria":null,
                   "subsecciones":[{"titulo_subseccion":"Sub B1","explicacion_detallada":"Detalle B1"}]}
                ],"conclusion":"Conclusión",
                "conexiones_contextuales":[{"seccion_temario_relacionada":"Tema X","descripcion_conexion":"Conexión"}]}
                """.trimIndent(),
            )
        }
        if (withWalkthrough) {
            append(
                ""","recorrido":{"recorrido_anotado":[
                  {"ubicacion":"L1","tipo_entrada":"cita_anotada","cita_textual":"Cita","traduccion":"Traducción"}]}""",
            )
        }
        if (withResources) {
            append(
                ""","resources":{"titulo_mapa":"Mapa","vision_general":"Visión","ejes_tematicos":[
                  {"nombre_eje":"Eje","recursos":[{"formato":"pdf","titulo":"Recurso","url":"https://example.com/a"}]}]}""",
            )
        }
        if (withReview) {
            append(
                ""","review":{"preguntas":[
                  {"numero":1,"pregunta":"¿P?","respuesta_razonada":"R","referencia":"L1"}]}""",
            )
        }
        if (withMermaid) {
            append(""","mermaid":{"mermaid_code":"graph TD; A-->B"}""")
        }
    }
    return """{"status":"$status"$agents}"""
}

/** Documento de parte como lo devolvería `loadPart` (T03/T07). */
fun partDocument(
    partId: Int,
    status: String = "completed",
    withExplainer: Boolean = true,
    withWalkthrough: Boolean = true,
    withResources: Boolean = true,
    withReview: Boolean = true,
    withMermaid: Boolean = true,
): PartContentDocument {
    val raw = Json.parseToJsonElement(
        partRawJson(status, withExplainer, withWalkthrough, withResources, withReview, withMermaid),
    ) as JsonObject
    return PartContentDocument(
        raw = raw,
        partId = partId,
        status = PartStatus.fromWire(status),
        explainer = PartContentContract.explainer(raw),
        recorrido = PartContentContract.recorrido(raw),
        resources = PartContentContract.resources(raw),
        review = PartContentContract.review(raw),
        mermaid = PartContentContract.mermaid(raw),
    )
}

/**
 * Catálogo falso del lector: manifest observable + lista observable
 * (disponibilidad) + `loadPart` con resultado, retardo y fallo programables.
 */
class FakeReaderCatalog : ProjectCatalogRepository {
    val manifestFlow = MutableStateFlow<ReaderProject?>(null)
    val projectsFlow = MutableStateFlow<List<ProjectListItem>>(emptyList())
    val loadCalls = mutableListOf<Int>()
    var loadResult: (Int) -> PartContentDocument? = { null }
    var loadDelayMillis: Long = 0L
    var loadDelay: (Int) -> Long = { loadDelayMillis }
    var loadFails: Boolean = false

    fun emitProject(project: ReaderProject?) {
        manifestFlow.value = project
    }

    fun emitAvailability(availability: ProjectAvailability) {
        projectsFlow.value = listOf(
            ProjectListItem(
                projectId = READER_PROJECT_ID,
                name = "Proyecto de prueba",
                description = null,
                status = ProjectStatus.Completed,
                sourceType = "pdf",
                pdfFilename = null,
                createdAt = "2026-07-01T10:00:00Z",
                updatedAt = "2026-08-02T10:00:00Z",
                partCount = 3,
                segmentationSourceBytes = 100_000L,
                snapshotBytes = 100_000L,
                readingProgress = ReadingProgress(),
                availability = availability,
            ),
        )
    }

    override fun observeProjects(ownerId: String): Flow<List<ProjectListItem>> = projectsFlow

    override suspend fun refresh(ownerId: String): RefreshOutcome = RefreshOutcome.Success(0)

    override fun observeReaderProject(ownerId: String, projectId: ProjectId): Flow<ReaderProject?> = manifestFlow

    override suspend fun loadPart(ownerId: String, projectId: ProjectId, partId: Int): PartContentDocument? {
        loadCalls.add(partId)
        val delayMs = loadDelay(partId)
        if (delayMs > 0L) delay(delayMs)
        if (loadFails) throw RuntimeException("fallo local de lectura")
        return loadResult(partId)
    }
}

/** Progreso falso: registra las llamadas de sección/subsección/sync. */
class FakeReadingProgress : ReadingProgressRepository {
    val sectionCalls = mutableListOf<SectionCall>()
    val subsectionCalls = mutableListOf<SubsectionProgressEvent>()
    val syncCalls = mutableListOf<String>()

    data class SectionCall(val ownerId: String, val projectId: ProjectId, val partId: Int, val completed: Boolean)

    override fun observe(ownerId: String, projectId: ProjectId): Flow<ReadingProgress> = flowOf(ReadingProgress())

    override suspend fun setSectionCompleted(ownerId: String, projectId: ProjectId, partId: Int, completed: Boolean) {
        sectionCalls.add(SectionCall(ownerId, projectId, partId, completed))
    }

    override suspend fun recordSubsection(ownerId: String, projectId: ProjectId, event: SubsectionProgressEvent) {
        subsectionCalls.add(event)
    }

    override suspend fun requestSync(ownerId: String) {
        syncCalls.add(ownerId)
    }
}

/**
 * Puerto de generación falso (T14): resultado, retardo y fallo por llamada
 * programables; registra las invocaciones para verificar owner/proyecto/parte
 * y la bandera de regeneración.
 */
class FakePartGenerationRepository : PartGenerationRepository {
    val diagramCalls = mutableListOf<GenerationCall>()
    val reviewCalls = mutableListOf<GenerationCall>()
    var diagramResult: GenerationOutcome = GenerationOutcome.Success
    var reviewResult: GenerationOutcome = GenerationOutcome.Success
    var delayMillis: Long = 0L
    var throwsCancellation: Boolean = false

    data class GenerationCall(
        val ownerId: String,
        val projectId: ProjectId,
        val partId: Int,
        val regenerate: Boolean,
    )

    override suspend fun generateDiagram(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): GenerationOutcome {
        if (delayMillis > 0L) delay(delayMillis)
        if (throwsCancellation) throw kotlinx.coroutines.CancellationException("cancelada")
        diagramCalls.add(GenerationCall(ownerId, projectId, partId, regenerate))
        return diagramResult
    }

    override suspend fun generateReview(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): GenerationOutcome {
        if (delayMillis > 0L) delay(delayMillis)
        if (throwsCancellation) throw kotlinx.coroutines.CancellationException("cancelada")
        reviewCalls.add(GenerationCall(ownerId, projectId, partId, regenerate))
        return reviewResult
    }
}

/** Razón de fallo de test para fases [GenerationPhase.Failed]. */
fun failedPhase(reason: GenerationFailureReason = GenerationFailureReason.OFFLINE): GenerationPhase.Failed =
    GenerationPhase.Failed(reason)

package com.explainer.app.feature.download

import com.explainer.app.core.model.DownloadedProjectFile
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.local.db.DownloadStateDao
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.OfflineProjectManifest
import com.explainer.app.data.local.snapshot.OfflineSnapshotStore
import com.explainer.app.data.local.snapshot.PreparedSnapshot
import com.explainer.app.data.local.snapshot.SnapshotCommitResult
import com.explainer.app.data.local.snapshot.SnapshotDescriptor
import com.explainer.app.data.remote.contract.ProjectRemoteDataSource
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.data.remote.dto.ProjectSummaryDto
import com.explainer.app.data.remote.dto.SubsectionProgressPatch
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.serialization.json.JsonObject
import java.io.File

/**
 * Fakes compartidos de los tests de T06 (misma filosofía que los de T03:
 * política pura reimplementada en memoria, sin Room ni red reales).
 */

/** Completa la barrera solo si aún no estaba completada (idempotente). */
private fun CompletableDeferred<Unit>?.signal() {
    this?.let { if (!it.isCompleted) it.complete(Unit) }
}

/** Proyecto fijo válido de los fixtures de test. */
val TEST_PROJECT_ID: ProjectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")

/** Segundo proyecto válido (namespace ajeno en los tests de sweep, R-T06-06). */
val OTHER_PROJECT_ID: ProjectId = ProjectId("9f4c2a8d-7e3b-4f1a-8d5c-2b6e9a0f1c3d")

val TEST_OWNER_A: String = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
val TEST_OWNER_B: String = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"

/**
 * Remote falso: escribe [body] al destino en chunks (64 KiB por defecto)
 * reportando progreso, como el Ktor real (T04). [resultOverride] devuelve el
 * resultado sin tocar el stream; [cancelAfterChunks] lanza
 * [CancellationException] a mitad del stream. Replica la política T04 de
 * `contentLength`: solo se declara si coincide con los bytes escritos.
 */
class FakeRemote : ProjectRemoteDataSource {
    var body: String = "{}"
    var totalBytes: Long? = null
    var chunkSize: Int = 64 * 1024
    var resultOverride: RemoteResult<DownloadedProjectFile>? = null
    var cancelAfterChunks: Int = -1
    var downloadCalls: Int = 0
    val progressReports = mutableListOf<Pair<Long, Long?>>()
    var lastDestination: File? = null

    override suspend fun listProjects(): RemoteResult<List<ProjectSummaryDto>> =
        RemoteResult.Success(emptyList())

    override suspend fun downloadProjectTo(
        projectId: ProjectId,
        destination: File,
        onProgress: suspend (downloadedBytes: Long, totalBytes: Long?) -> Unit,
    ): RemoteResult<DownloadedProjectFile> {
        downloadCalls++
        lastDestination = destination
        resultOverride?.let { return it }

        val bytes = body.toByteArray(Charsets.UTF_8)
        var received = 0L
        var chunks = 0
        destination.outputStream().use { out ->
            var offset = 0
            while (offset < bytes.size) {
                if (cancelAfterChunks >= 0 && chunks >= cancelAfterChunks) {
                    throw CancellationException("fake stream cancelled")
                }
                val n = minOf(chunkSize, bytes.size - offset)
                out.write(bytes, offset, n)
                offset += n
                received += n
                chunks++
                progressReports.add(received to totalBytes)
                onProgress(received, totalBytes)
            }
        }
        return RemoteResult.Success(
            DownloadedProjectFile(
                file = destination,
                // Paridad con T04: total solo si el header == bytes escritos.
                contentLength = if (totalBytes != null && totalBytes != received) null else totalBytes,
                receivedBytes = received,
            ),
        )
    }

    override suspend fun patchSection(projectId: ProjectId, partId: Int, completed: Boolean): RemoteResult<Unit> =
        RemoteResult.Success(Unit)

    override suspend fun patchSubsections(
        projectId: ProjectId,
        patch: SubsectionProgressPatch,
    ): RemoteResult<Unit> = RemoteResult.Success(Unit)

    override suspend fun generateDiagram(
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): RemoteResult<kotlinx.serialization.json.JsonObject> =
        RemoteResult.Success(kotlinx.serialization.json.JsonObject(emptyMap()))

    override suspend fun generateReview(
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): RemoteResult<kotlinx.serialization.json.JsonObject> =
        RemoteResult.Success(kotlinx.serialization.json.JsonObject(emptyMap()))
}

/**
 * Store falso con la política pura del commit: registra prepare/commit/delete,
 * permite inyectar rechazo (cancel/delete ganaron la carrera) y errores de
 * preparación (parse/IO). [manifest] simula el snapshot previo activo; el
 * commit exitoso lo sustituye (una sola generación).
 */
class FakeStore : OfflineSnapshotStore {
    val prepareCalls = mutableListOf<String>()
    val commitCalls = mutableListOf<String>()
    val committedDescriptors = mutableListOf<SnapshotDescriptor>()
    val deleteCalls = mutableListOf<Pair<String, String>>()
    var prepareError: Exception? = null
    var rejectCommits = false
    var manifest: OfflineProjectManifest? = null
    var events: MutableList<String>? = null

    /** Paridad con `SnapshotDao.deleteProject`: también borra el estado de descarga. */
    var onDelete: ((ownerId: String, projectId: String) -> Unit)? = null

    /** Barreras de la carrera commit vs cancel (R-T06-01). */
    var commitStarted: CompletableDeferred<Unit>? = null
    var commitGate: CompletableDeferred<Unit>? = null

    /**
     * Paridad con `SnapshotCommitPolicy.workStillActive`: si se inyecta, el
     * commit se rechaza cuando la fila dejó de estar activa (cancel/delete
     * ganaron mientras el commit estaba en vuelo).
     */
    var workStillActive: (() -> Boolean)? = null

    override suspend fun prepare(ownerId: String, source: File): PreparedSnapshot {
        prepareCalls.add(ownerId)
        prepareError?.let { throw it }
        val json = source.readText(Charsets.UTF_8)
        return PreparedSnapshot(
            ownerId = ownerId,
            projectId = TEST_PROJECT_ID,
            generation = "gen-${commitCalls.size + 1}",
            name = "Fake proyecto",
            description = null,
            status = ProjectStatus.Completed,
            sourceType = "pdf",
            parts = emptyList(),
            usage = JsonObject(emptyMap()),
            readingProgress = ReadingProgress(),
            sourceUpdatedAt = "2026-08-01T00:00:00Z",
            totalBytes = json.length.toLong(),
        )
    }

    override suspend fun commit(
        prepared: PreparedSnapshot,
        expectedWorkId: String,
    ): SnapshotCommitResult {
        commitCalls.add(expectedWorkId)
        commitStarted.signal()
        commitGate?.await()
        if (rejectCommits) return SnapshotCommitResult.RejectedCancelledOrSuperseded
        if (workStillActive?.invoke() == false) {
            return SnapshotCommitResult.RejectedCancelledOrSuperseded
        }

        val descriptor = SnapshotDescriptor(
            ownerId = prepared.ownerId,
            projectId = prepared.projectId,
            generation = prepared.generation,
            totalBytes = prepared.totalBytes,
            sourceUpdatedAt = prepared.sourceUpdatedAt,
            downloadedAt = 1234L,
        )
        committedDescriptors.add(descriptor)
        manifest = OfflineProjectManifest(
            ownerId = prepared.ownerId,
            projectId = prepared.projectId,
            name = prepared.name,
            description = prepared.description,
            status = prepared.status,
            sourceType = prepared.sourceType,
            parts = emptyList(),
            usage = prepared.usage,
            readingProgress = prepared.readingProgress,
            activeGeneration = prepared.generation,
            sourceUpdatedAt = prepared.sourceUpdatedAt,
            downloadedAt = 1234L,
            totalBytes = prepared.totalBytes,
        )
        return SnapshotCommitResult.Committed(descriptor)
    }

    override suspend fun readManifest(ownerId: String, projectId: ProjectId): OfflineProjectManifest? =
        manifest

    override suspend fun readPart(ownerId: String, projectId: ProjectId, partId: Int): com.explainer.app.core.model.PartContentDocument? = null

    override suspend fun delete(ownerId: String, projectId: ProjectId) {
        events?.add("store:delete:$ownerId:${projectId.value}")
        deleteCalls.add(ownerId to projectId.value)
        onDelete?.invoke(ownerId, projectId.value)
        manifest = null
    }

    override suspend fun cleanupOrphans() = Unit

    override suspend fun updatePartContent(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        patch: kotlinx.serialization.json.JsonObject,
    ): Boolean = false
}

/**
 * DAO de estado en memoria con la MISMA política que el `casUpdate` de Room
 * (R-T06-01): la escritura solo aplica si la fila existe, conserva el
 * `expectedWorkId` y NO está en estado terminal; devuelve filas afectadas.
 * `observe` replica Room con un [MutableStateFlow] (re-emite al upsert/delete)
 * para poder probar el corte/recalculo de la observación (R-T06-03).
 *
 * Barreras deterministas: [casStarted] se completa cuando `casUpdate` entra
 * en vuelo y [casGate] lo bloquea hasta que el test lo libera, intercalando
 * cancel/delete entre la lectura y la escritura del worker.
 */
class InMemoryDownloadStateDao(
    var events: MutableList<String>? = null,
) : DownloadStateDao {
    val rows = mutableMapOf<Pair<String, String>, DownloadStateEntity>()
    private val flowByKey = mutableMapOf<Pair<String, String>, MutableStateFlow<DownloadStateEntity?>>()

    /** Barreras de interleaving (R-T06-01). */
    var casStarted: CompletableDeferred<Unit>? = null
    var casGate: CompletableDeferred<Unit>? = null
    var casCalls: Int = 0

    override fun observe(ownerId: String, projectId: String): Flow<DownloadStateEntity?> =
        flowByKey.getOrPut(ownerId to projectId) { MutableStateFlow(rows[ownerId to projectId]) }

    // Añadido por R-T07-04 (nuevo método abstracto del contrato T03): misma
    // enumeración owner-scoped que el SQL real.
    override fun observeProjectIds(ownerId: String): Flow<List<String>> =
        flowOf(flowByKey.keys.filter { it.first == ownerId }.map { it.second }.toList())

    override suspend fun row(ownerId: String, projectId: String): DownloadStateEntity? =
        rows[ownerId to projectId]

    override suspend fun upsert(state: DownloadStateEntity) {
        events?.add("dao:upsert:${state.state}")
        rows[state.ownerId to state.projectId] = state
        flowByKey[state.ownerId to state.projectId]?.value = state
    }

    override suspend fun casUpdate(
        ownerId: String,
        projectId: String,
        expectedWorkId: String,
        newWorkId: String,
        state: String,
        downloadedBytes: Long,
        totalBytes: Long?,
        errorCategory: String?,
        finishedAt: Long?,
    ): Int {
        casCalls++
        casStarted.signal()
        casGate?.await()
        val key = ownerId to projectId
        val current = rows[key] ?: return 0
        if (current.workId != expectedWorkId) return 0
        if (DownloadStateEntity.isTerminalState(current.state)) return 0
        rows[key] = current.copy(
            workId = newWorkId,
            state = state,
            downloadedBytes = downloadedBytes,
            totalBytes = totalBytes,
            errorCategory = errorCategory,
            finishedAt = finishedAt,
        )
        flowByKey[ownerId to projectId]?.value = rows[key]
        events?.add("dao:cas:${state}")
        return 1
    }

    override suspend fun delete(ownerId: String, projectId: String) {
        events?.add("dao:delete")
        rows.remove(ownerId to projectId)
        flowByKey[ownerId to projectId]?.value = null
    }

    fun seed(
        ownerId: String,
        projectId: ProjectId = TEST_PROJECT_ID,
        workId: String = "w1",
        state: String = DownloadStateEntity.STATE_DOWNLOADING,
        downloadedBytes: Long = 0L,
        totalBytes: Long? = null,
        requestedAt: Long = 1000L,
    ) {
        rows[ownerId to projectId.value] = DownloadStateEntity(
            ownerId = ownerId,
            projectId = projectId.value,
            workId = workId,
            state = state,
            downloadedBytes = downloadedBytes,
            totalBytes = totalBytes,
            requestedAt = requestedAt,
        )
    }
}

/** DAO de resúmenes en memoria (bytes de segmentation configurables). */
class InMemorySummaryDao : ProjectSummaryDao {
    val rows = mutableMapOf<Pair<String, String>, ProjectSummaryEntity>()

    override fun observeSummaries(ownerId: String): Flow<List<ProjectSummaryEntity>> =
        flowOf(rows.values.filter { it.ownerId == ownerId })

    override fun observeSummary(ownerId: String, projectId: String): Flow<ProjectSummaryEntity?> =
        flowOf(rows[ownerId to projectId])

    override suspend fun summaryRow(ownerId: String, projectId: String): ProjectSummaryEntity? =
        rows[ownerId to projectId]

    override suspend fun upsert(summary: ProjectSummaryEntity) {
        rows[summary.ownerId to summary.projectId] = summary
    }

    override suspend fun delete(ownerId: String, projectId: String) {
        rows.remove(ownerId to projectId)
    }

    fun seed(ownerId: String, segmentationSourceBytes: Long) {
        rows[ownerId to TEST_PROJECT_ID.value] = ProjectSummaryEntity(
            ownerId = ownerId,
            projectId = TEST_PROJECT_ID.value,
            name = "Resumen",
            segmentationSourceBytes = segmentationSourceBytes,
        )
    }
}

package com.explainer.app.feature.progress

import com.explainer.app.core.model.DownloadedProjectFile
import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.remote.contract.ProjectRemoteDataSource
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.data.remote.dto.ProjectSummaryDto
import com.explainer.app.data.remote.dto.SubsectionProgressPatch
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import java.io.File

/**
 * Doble del remoto para tests del progreso: resultados por script y registro
 * de llamadas (los campos que el flujo de progreso no usa lanzan
 * [UnsupportedOperationException]).
 */
class FakeProgressRemote : ProjectRemoteDataSource {
    var sectionResult: RemoteResult<Unit> = RemoteResult.Success(Unit)
    var subsectionResult: RemoteResult<Unit> = RemoteResult.Success(Unit)
    var listResult: RemoteResult<List<ProjectSummaryDto>> = RemoteResult.Success(emptyList())
    val sectionCalls = mutableListOf<Triple<String, Int, Boolean>>()
    val subsectionCalls = mutableListOf<Pair<String, SubsectionProgressPatch>>()

    /**
     * Barreras de interleaving (R-T07-01): si [sectionGate] está presente, el
     * PATCH queda en vuelo hasta que el test lo libera; [sectionStarted] se
     * completa al entrar al PATCH para que el test intercale la escritura
     * concurrente entre la lectura de filas y la respuesta del remoto.
     */
    var sectionStarted: CompletableDeferred<Unit>? = null
    var sectionGate: CompletableDeferred<Unit>? = null

    /**
     * Cola opcional de respuestas de lista (R-T07-08): si no está vacía, cada
     * llamada consume la siguiente; si se agota, cae a [listResult]. Permite
     * scripting de dos refreshes concurrentes con respuestas fuera de orden.
     */
    val listQueue = ArrayDeque<RemoteResult<List<ProjectSummaryDto>>>()

    override suspend fun listProjects(): RemoteResult<List<ProjectSummaryDto>> =
        if (listQueue.isNotEmpty()) listQueue.removeFirst() else listResult

    override suspend fun downloadProjectTo(
        projectId: ProjectId,
        destination: File,
        onProgress: suspend (downloadedBytes: Long, totalBytes: Long?) -> Unit,
    ): RemoteResult<DownloadedProjectFile> =
        throw UnsupportedOperationException("no usado por el flujo de progreso")

    override suspend fun patchSection(projectId: ProjectId, partId: Int, completed: Boolean): RemoteResult<Unit> {
        sectionCalls += Triple(projectId.value, partId, completed)
        sectionStarted?.complete(Unit)
        sectionGate?.await()
        return sectionResult
    }

    override suspend fun patchSubsections(
        projectId: ProjectId,
        patch: SubsectionProgressPatch,
    ): RemoteResult<Unit> {
        subsectionCalls += projectId.value to patch
        return subsectionResult
    }

    override suspend fun generateDiagram(
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): RemoteResult<kotlinx.serialization.json.JsonObject> =
        throw UnsupportedOperationException("no usado por el flujo de progreso")

    override suspend fun generateReview(
        projectId: ProjectId,
        partId: Int,
        regenerate: Boolean,
    ): RemoteResult<kotlinx.serialization.json.JsonObject> =
        throw UnsupportedOperationException("no usado por el flujo de progreso")
}

/** Índice de catálogo en memoria con la misma semántica que [ProjectSummaryDao]. */
class InMemoryProjectSummaryDao : ProjectSummaryDao {
    val rows = mutableMapOf<Pair<String, String>, ProjectSummaryEntity>()

    /**
     * Barreras de interleaving (R-T07-08): fuerzan la ventana TOCTOU
     * read-read/write-write de dos refreshes concurrentes con respuestas
     * fuera de orden. Por defecto nulas (sin bloqueo); solo se activan en el
     * test de la carrera. `firstSummaryRow*` retiene la PRIMERA lectura;
     * `staleUpsert*` retiene la escritura del resumen con el timestamp
     * [staleUpsertTimestamp] (la respuesta stale que llega tarde).
     *
     * IMPORTANTE: como el DAO Room real (un SELECT atómico que devuelve el
     * valor al llamante), [summaryRow] CAPTURA la fila al ENTRAR y la
     * devuelve después de la barrera — si la releyera tras la barrera vería
     * la escritura del refresh concurrente y el interleaving TOCTOU
     * desaparecería.
     */
    var firstSummaryRowStarted: CompletableDeferred<Unit>? = null
    var firstSummaryRowGate: CompletableDeferred<Unit>? = null
    var staleUpsertTimestamp: String? = null
    var staleUpsertStarted: CompletableDeferred<Unit>? = null
    var staleUpsertGate: CompletableDeferred<Unit>? = null
    private var summaryRowCalls = 0

    override fun observeSummaries(ownerId: String): Flow<List<ProjectSummaryEntity>> =
        flowOf(rows.values.filter { it.ownerId == ownerId }.sortedBy { it.projectId })

    override fun observeSummary(ownerId: String, projectId: String): Flow<ProjectSummaryEntity?> =
        flowOf(rows[ownerId to projectId])

    override suspend fun summaryRow(ownerId: String, projectId: String): ProjectSummaryEntity? {
        summaryRowCalls++
        val captured = rows[ownerId to projectId]
        if (summaryRowCalls == 1) {
            firstSummaryRowStarted?.complete(Unit)
            firstSummaryRowGate?.await()
        }
        return captured
    }

    override suspend fun upsert(summary: ProjectSummaryEntity) {
        if (summary.remoteUpdatedAt == staleUpsertTimestamp) {
            staleUpsertStarted?.complete(Unit)
            staleUpsertGate?.await()
        }
        rows[summary.ownerId to summary.projectId] = summary
    }

    override suspend fun delete(ownerId: String, projectId: String) {
        rows.remove(ownerId to projectId)
    }
}

/** Scheduler de sync registrador: captura (ownerId, delayMs) sin WorkManager. */
class RecordingScheduler : ProgressSyncScheduler {
    val calls = mutableListOf<Pair<String, Long>>()
    override fun schedule(ownerId: String, delayMs: Long) {
        calls += ownerId to delayMs
    }
}

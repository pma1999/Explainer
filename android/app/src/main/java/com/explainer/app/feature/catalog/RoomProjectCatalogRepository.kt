package com.explainer.app.feature.catalog

import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.data.local.db.DownloadStateDao
import com.explainer.app.data.local.db.PendingProgressDao
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.db.SnapshotDao
import com.explainer.app.data.local.snapshot.OfflineSnapshotStore
import com.explainer.app.data.local.snapshot.PendingOverlayBuilder
import com.explainer.app.data.local.snapshot.SnapshotEntityMapper
import com.explainer.app.data.local.snapshot.SnapshotJsonCodec
import com.explainer.app.data.local.snapshot.SnapshotOwnerValidator
import com.explainer.app.data.remote.contract.ProjectRemoteDataSource
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.feature.progress.ProgressConfirmation
import com.explainer.app.feature.progress.ProgressMerge
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Catálogo owner-scoped: refresh por `GET /api/projects` que NUNCA borra
 * summaries/snapshots por fallo, lista combinada summary ∪ snapshot ∪
 * download state (R-T07-04: un proyecto download-only también aparece)
 * ordenada por `updated_at` desc, y lector offline vía manifest/partes de
 * T03. En cada refresh exitoso, confirma las filas de progreso
 * ACKNOWLEDGED contra el progreso remoto de la lista y elimina solo las
 * confirmadas (global-constraints.md), conservando un tombstone confirmado
 * hasta que la generación local observada lo refleje (R-T07-02).
 */
class RoomProjectCatalogRepository(
    private val remote: ProjectRemoteDataSource,
    private val projectSummaryDao: ProjectSummaryDao,
    private val snapshotDao: SnapshotDao,
    private val downloadStateDao: DownloadStateDao,
    private val pendingProgressDao: PendingProgressDao,
    private val snapshotStore: OfflineSnapshotStore,
    private val clock: () -> Long = System::currentTimeMillis,
) : ProjectCatalogRepository {

    /**
     * R-T07-07: proyectos cuyo último refresh terminó en 404 (remoto no
     * disponible), owner/project-scoped. Se expone (no se persiste: el
     * schema T03 está congelado) y se limpia con el siguiente refresh
     * exitoso. Nunca borra snapshot ni cola.
     */
    private val remoteUnavailableProjects = MutableStateFlow<Set<Pair<String, String>>>(emptySet())

    /**
     * R-T07-08: serializa el refresh POR OWNER. El upsert condicional
     * (`summaryRow` + `shouldReplace` + `upsert`) es TOCTOU por diseño: dos
     * refreshes concurrentes del mismo owner podrían leer el MISMO existing y
     * escribir el stale después del nuevo. El lock cierra la ventana — el
     * segundo refresh ni siquiera lee hasta que el primero terminó de
     * escribir, así `shouldReplace` siempre compara contra la última fila
     * persistida y las respuestas fuera de orden convergen al resumen más
     * nuevo. Owners distintos no se bloquean entre sí.
     */
    private val refreshLocks = ConcurrentHashMap<String, Mutex>()

    override fun observeProjects(ownerId: String): Flow<List<ProjectListItem>> {
        val owner = SnapshotOwnerValidator.requireValidOwner(ownerId)
        return combine(
            projectSummaryDao.observeSummaries(owner),
            snapshotDao.observeSnapshots(owner),
            downloadStateDao.observeProjectIds(owner),
            remoteUnavailableProjects,
        ) { summaries, snapshots, downloadIds, unavailable ->
            val ids = (summaries.map { it.projectId } + snapshots.map { it.projectId } + downloadIds)
                .distinct().sorted()
            val unavailableIds = unavailable.filter { it.first == owner }.map { it.second }.toSet()
            ids to unavailableIds
        }.flatMapLatest { (ids, unavailableIds) ->
            if (ids.isEmpty()) {
                flowOf(emptyList())
            } else {
                combine(ids.map { id -> observeItem(owner, id, id in unavailableIds) }) { items ->
                    items.filterNotNull().sortedByDescending { timestampEpochMillis(it.updatedAt) }
                }
            }
        }
    }

    private fun observeItem(owner: String, projectId: String, remoteUnavailable: Boolean): Flow<ProjectListItem?> =
        combine(
            projectSummaryDao.observeSummary(owner, projectId),
            snapshotDao.observeSnapshot(owner, projectId),
            downloadStateDao.observe(owner, projectId),
            pendingProgressDao.observeProject(owner, projectId),
        ) { summary, snapshot, download, pending ->
            // Defensivo: un id corrupto en Room degrada sin crash (no debería
            // ocurrir: ambos DAOs solo persisten UUIDs validados).
            val id = ProjectId.parse(projectId) ?: return@combine null
            buildProjectListItem(
                projectId = id,
                summary = summary,
                snapshot = snapshot,
                download = download,
                pending = pending,
                remoteUnavailable = remoteUnavailable,
            )
        }

    override suspend fun refresh(ownerId: String): RefreshOutcome {
        val owner = SnapshotOwnerValidator.requireValidOwner(ownerId)
        return refreshLocks.getOrPut(owner) { Mutex() }.withLock {
            refreshLocked(owner)
        }
    }

    private suspend fun refreshLocked(owner: String): RefreshOutcome =
        when (val result = remote.listProjects()) {
            is RemoteResult.Success -> {
                val fetchedAt = clock()
                result.value.forEach { dto ->
                    CatalogSummaryMapper.toEntity(owner, dto, fetchedAt)?.let { entity ->
                        // R-T07-08: upsert condicional por `updated_at` ISO —
                        // una respuesta stale (T1 llegando tarde) nunca
                        // reemplaza un resumen más nuevo (T2).
                        val existing = projectSummaryDao.summaryRow(owner, entity.projectId)
                        if (existing == null || shouldReplace(existing, entity)) {
                            projectSummaryDao.upsert(entity)
                        }
                    }
                }
                clearRemoteUnavailable(owner)
                confirmAcknowledgedProgress(owner)
                RefreshOutcome.Success(result.value.size)
            }

            RemoteResult.AuthRequired -> RefreshOutcome.AuthRequired
            RemoteResult.NotFound -> {
                // R-T07-07: el 404 se materializa como remoto no disponible
                // para todos los proyectos conocidos del owner (sin borrar
                // snapshot ni cola).
                markRemoteUnavailable(owner)
                RefreshOutcome.NotFound
            }

            RemoteResult.RateLimited -> RefreshOutcome.RateLimited
            RemoteResult.Retryable -> RefreshOutcome.Retryable
            is RemoteResult.InvalidPayload -> RefreshOutcome.InvalidPayload
            RemoteResult.Cancelled -> RefreshOutcome.Cancelled
            is RemoteResult.PermanentFailure -> RefreshOutcome.PermanentFailure(result.reason)
        }

    /**
     * R-T07-08: política explícita de reemplazo por `updated_at` ISO
     * parseado. Un timestamp inválido degrada: existente inválido se repara
     * con una respuesta válida; respuesta inválida nunca pisa un existente
     * válido; empate se resuelve a favor de la escritura (refresh
     * idempotente).
     */
    private fun shouldReplace(existing: ProjectSummaryEntity, incoming: ProjectSummaryEntity): Boolean {
        val existingAt = parseInstantOrNull(existing.remoteUpdatedAt) ?: return true
        val incomingAt = parseInstantOrNull(incoming.remoteUpdatedAt) ?: return false
        return incomingAt >= existingAt
    }

    /**
     * Elimina filas ACKNOWLEDGED solo cuando la lista remota (recién
     * persistida) confirma el valor deseado; las PENDING nunca se tocan y
     * las no confirmadas se conservan (respuestas de detalle iniciadas
     * antes del ack no reintroducen progreso stale).
     */
    private suspend fun confirmAcknowledgedProgress(owner: String) {
        projectSummaryDao.observeSummaries(owner).first().forEach { summary ->
            val remoteProgress = SnapshotJsonCodec.decodeReadingProgress(summary.readingProgressJson)
            pendingProgressDao.observeProject(owner, summary.projectId).first()
                .filter { it.syncState == PendingProgressEntity.SYNC_ACKNOWLEDGED }
                .forEach { row ->
                    if (ProgressConfirmation.isConfirmed(remoteProgress, row) &&
                        tombstoneReconciledWithSnapshot(owner, summary.projectId, row)
                    ) {
                        pendingProgressDao.delete(owner, summary.projectId, row.partId, row.tab, row.kindTarget)
                    }
                }
        }
    }

    /**
     * R-T07-02: un tombstone (`desiredCompleted=false`) confirmado por el
     * remoto solo se elimina cuando la generación local observada ya no
     * contiene el valor. Si el snapshot stale aún lo tiene, el ACKNOWLEDGED
     * se conserva y sigue superponiéndose (la policy T02 resta el tombstone
     * de la unión); eliminarlo prematuro reintroduciría el valor del
     * snapshot. `true` y last-read no reintroducen nada al eliminarse.
     */
    private suspend fun tombstoneReconciledWithSnapshot(
        owner: String,
        projectId: String,
        row: PendingProgressEntity,
    ): Boolean {
        if (row.desiredCompleted != false) return true
        val snapshotProgress = snapshotDao.observeSnapshot(owner, projectId).first()
            ?.let { SnapshotJsonCodec.decodeReadingProgress(it.readingProgressJson) }
            ?: return true // sin snapshot no hay nada que reconciliar
        return when (row.kindTarget) {
            PendingProgressEntity.KIND_SECTION -> row.partId !in snapshotProgress.completedParts
            else -> {
                if (!row.kindTarget.startsWith(PendingProgressEntity.KIND_SUBSECTION_PREFIX)) return true
                val id = row.kindTarget.removePrefix(PendingProgressEntity.KIND_SUBSECTION_PREFIX)
                id !in snapshotProgress.completedSubsections
            }
        }
    }

    private suspend fun markRemoteUnavailable(owner: String) {
        val ids = (
            projectSummaryDao.observeSummaries(owner).first().map { it.projectId } +
                snapshotDao.observeSnapshots(owner).first().map { it.projectId } +
                downloadStateDao.observeProjectIds(owner).first()
            ).distinct()
        remoteUnavailableProjects.update { prev -> prev + ids.map { owner to it } }
    }

    private fun clearRemoteUnavailable(owner: String) {
        remoteUnavailableProjects.update { prev -> prev.filterNot { it.first == owner }.toSet() }
    }

    override fun observeReaderProject(ownerId: String, projectId: ProjectId): Flow<ReaderProject?> {
        val owner = SnapshotOwnerValidator.requireValidOwner(ownerId)
        val pid = projectId.value
        return combine(
            snapshotDao.observeSnapshot(owner, pid),
            projectSummaryDao.observeSummary(owner, pid),
            pendingProgressDao.observeProject(owner, pid),
        ) { snapshot, summary, pending ->
            val manifest = snapshot?.let { SnapshotEntityMapper.toManifest(it, owner, projectId) }
                ?: return@combine null
            ReaderProject(
                projectId = projectId,
                name = summary?.name ?: manifest.name,
                description = summary?.description ?: manifest.description,
                status = summary?.let { ProjectStatus.fromWire(it.status) } ?: manifest.status,
                sourceType = summary?.sourceType ?: manifest.sourceType,
                parts = manifest.parts,
                readingProgress = ProgressMerge.merged(
                    summaryProgress = summary?.let { SnapshotJsonCodec.decodeReadingProgress(it.readingProgressJson) },
                    snapshotProgress = manifest.readingProgress,
                    overlay = PendingOverlayBuilder.fromRows(pending),
                ),
                updatedAt = summary?.remoteUpdatedAt ?: manifest.sourceUpdatedAt,
                totalBytes = manifest.totalBytes,
                downloadedAt = manifest.downloadedAt,
                activeGeneration = manifest.activeGeneration,
            )
        }
    }

    override suspend fun loadPart(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
    ): PartContentDocument? {
        val owner = SnapshotOwnerValidator.requireValidOwner(ownerId)
        return snapshotStore.readPart(owner, projectId, partId)
    }
}

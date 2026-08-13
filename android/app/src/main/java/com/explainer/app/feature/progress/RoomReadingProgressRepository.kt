package com.explainer.app.feature.progress

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.local.db.PendingProgressDao
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.db.SnapshotDao
import com.explainer.app.data.local.snapshot.PendingOverlayBuilder
import com.explainer.app.data.local.snapshot.SnapshotJsonCodec
import com.explainer.app.data.local.snapshot.SnapshotOwnerValidator
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import java.time.Instant

/**
 * Repositorio de progreso optimista sobre la cola durable:
 * - Las escrituras son inmediatas y coalescidas por la PK de
 *   [PendingProgressEntity] (upsert; un evento repetido no crea filas por
 *   scroll) y luego se agenda el worker con debounce.
 * - `observe` mezcla summary (remoto) ∪ snapshot (local) ∪ overlay con la
 *   policy T02 (unión de completadas, tombstones, last-read más reciente).
 * - Solo `PENDING` se transmite; `ACKNOWLEDGED` se conserva superponiéndose
 *   hasta que el catálogo confirme el valor remoto y lo elimine.
 */
class RoomReadingProgressRepository(
    private val pendingDao: PendingProgressDao,
    private val summaryDao: ProjectSummaryDao,
    private val snapshotDao: SnapshotDao,
    private val scheduler: ProgressSyncScheduler,
    private val throttle: ProgressThrottle,
    private val nowMillis: () -> Long = System::currentTimeMillis,
) : ReadingProgressRepository {

    override fun observe(ownerId: String, projectId: ProjectId): Flow<ReadingProgress> {
        val owner = SnapshotOwnerValidator.requireValidOwner(ownerId)
        val pid = projectId.value
        return combine(
            pendingDao.observeProject(owner, pid),
            summaryDao.observeSummary(owner, pid),
            snapshotDao.observeSnapshot(owner, pid),
        ) { pending, summary, snapshot ->
            ProgressMerge.merged(
                summaryProgress = summary?.let { SnapshotJsonCodec.decodeReadingProgress(it.readingProgressJson) },
                snapshotProgress = snapshot?.let { SnapshotJsonCodec.decodeReadingProgress(it.readingProgressJson) },
                overlay = PendingOverlayBuilder.fromRows(pending),
            )
        }
    }

    override suspend fun setSectionCompleted(
        ownerId: String,
        projectId: ProjectId,
        partId: Int,
        completed: Boolean,
    ) {
        val owner = SnapshotOwnerValidator.requireValidOwner(ownerId)
        if (partId <= 0) return
        pendingDao.upsert(
            PendingProgressEntity(
                ownerId = owner,
                projectId = projectId.value,
                partId = partId,
                tab = SECTION_TAB,
                kindTarget = PendingProgressEntity.KIND_SECTION,
                desiredCompleted = completed,
                syncState = PendingProgressEntity.SYNC_PENDING,
                updatedAt = nowMillis(),
            ),
        )
        scheduleSync(owner)
    }

    override suspend fun recordSubsection(
        ownerId: String,
        projectId: ProjectId,
        event: SubsectionProgressEvent,
    ) {
        val owner = SnapshotOwnerValidator.requireValidOwner(ownerId)
        if (event.partId <= 0 || !isValidSubsectionId(event.subsectionId, event.partId)) return
        val tab = event.tab.wireName
        val now = nowMillis()
        var changed = false

        if (event.completed != null) {
            pendingDao.upsert(
                PendingProgressEntity(
                    ownerId = owner,
                    projectId = projectId.value,
                    partId = event.partId,
                    tab = tab,
                    kindTarget = PendingProgressEntity.KIND_SUBSECTION_PREFIX + event.subsectionId,
                    desiredCompleted = event.completed,
                    syncState = PendingProgressEntity.SYNC_PENDING,
                    updatedAt = now,
                ),
            )
            changed = true
        }

        if (event.isLastRead) {
            // Coalescencia del last-read: la fila nueva solo gana si su
            // updated_at no es anterior a la vigente (relojes monotónicos).
            val existing = pendingDao.observeProject(owner, projectId.value).first().firstOrNull {
                it.kindTarget == PendingProgressEntity.KIND_LAST_READ &&
                    it.partId == event.partId &&
                    it.tab == tab
            }
            if (existing == null || now >= existing.updatedAt) {
                pendingDao.upsert(
                    PendingProgressEntity(
                        ownerId = owner,
                        projectId = projectId.value,
                        partId = event.partId,
                        tab = tab,
                        kindTarget = PendingProgressEntity.KIND_LAST_READ,
                        lastSubsectionId = event.subsectionId,
                        lastReadAt = Instant.ofEpochMilli(now).toString(),
                        syncState = PendingProgressEntity.SYNC_PENDING,
                        updatedAt = now,
                    ),
                )
                changed = true
            }
        }

        if (changed) scheduleSync(owner)
    }

    override suspend fun requestSync(ownerId: String) {
        SnapshotOwnerValidator.requireValidOwner(ownerId)
        scheduleSync(ownerId)
    }

    /**
     * Debounce de 15 s desde el último evento; si el intervalo mínimo de
     * 60 s desde el último flush no transcurrió, espera el resto (el worker
     * es unique `progress-sync:<ownerId>` con REPLACE, así cada evento
     * reinicia el temporizador).
     */
    private fun scheduleSync(ownerId: String) {
        val remaining = throttle.remainingToMinInterval(ownerId, ProgressSyncCoordinator.MIN_INTERVAL_MS)
        val delay = if (remaining > 0L) remaining else ProgressSyncCoordinator.DEBOUNCE_MS
        scheduler.schedule(ownerId, delay)
    }

    companion object {
        /**
         * Tab arbitraria de las filas de parte (el endpoint de sección no
         * lleva tab; la PK la exige). No colisiona con los wire reales
         * (`explicacion|recorrido|recursos|esquema|repaso`).
         */
        const val SECTION_TAB = "section"
    }
}

/** Validación del backend replicada: `subsec-{partId}-...`. */
internal fun isValidSubsectionId(id: String, partId: Int): Boolean =
    id.isNotBlank() && id.startsWith("subsec-$partId-")

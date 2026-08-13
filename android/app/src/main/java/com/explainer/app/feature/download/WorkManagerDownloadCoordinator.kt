package com.explainer.app.feature.download

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.DownloadStateDao
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.snapshot.OfflineSnapshotStore
import com.explainer.app.data.local.snapshot.SnapshotOwnerValidator
import com.explainer.app.data.local.snapshot.SnapshotStoreException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow

/**
 * Coordinador de descargas sobre WorkManager + Room (T06). La lógica de
 * decisión (enqueue con KEEP, marcar antes de cancelar, delete solo local)
 * es la única capa conociendo WorkManager; el motor puro y el Worker son
 * testables en JVM vía [DownloadWorkScheduler]/fakes.
 *
 * Orden crítico de cancel/delete (global-constraints.md): se marca la fila
 * `DownloadStateEntity` como cancelada ANTES de cancelar el trabajo, y el
 * commit atómico (T03) rechaza a un worker tardío; deleteLocal además borra
 * el snapshot/estado/índice/temporales sin invocar ningún DELETE remoto.
 *
 * Sesión (R-T06-03): worker y mutadores exigen igualdad ESTRICTA con un owner
 * de sesión NO nulo; [observe] corta/recalcula la suscripción cuando el owner
 * de sesión cambia (logout o cambio de cuenta), nunca exponiendo datos ajenos.
 *
 * R-T11-05 (aditivo, decisión del plan): si el container inyecta
 * [sessionOwnerFlow] (fuente reactiva del owner), [observe] lo consume en vez
 * de sondear cada 250 ms (sin polling continuo). Sin el flujo, se conserva el
 * fallback de polling (contrato público T06 intacto).
 */
class WorkManagerDownloadCoordinator(
    private val scheduler: DownloadWorkScheduler,
    private val requestFactory: DownloadWorkRequestFactory,
    private val downloadDao: DownloadStateDao,
    private val store: OfflineSnapshotStore,
    private val summaryDao: ProjectSummaryDao,
    private val sessionOwner: () -> String?,
    private val nowMillis: () -> Long = System::currentTimeMillis,
    private val sessionPollMillis: Long = 250L,
    private val sessionOwnerFlow: Flow<String?>? = null,
    private val tempOrphanSweep: (ownerId: String, projectId: String) -> Unit = { _, _ -> },
) : DownloadCoordinator {

    override fun observe(ownerId: String, projectId: ProjectId): Flow<DownloadState> =
        sessionOwnerFlowSource().flatMapLatest { owner ->
            if (owner != ownerId) {
                // Owner de sesión nulo (logout) o de otra cuenta: sin emisión.
                emptyFlow()
            } else {
                downloadDao.observe(ownerId, projectId.value).flatMapLatest { entity ->
                    if (entity == null) {
                        // Sin fila (nunca encolado o borrado local): sin estado.
                        emptyFlow()
                    } else {
                        flow {
                            val descriptor = if (entity.state == DownloadStateEntity.STATE_SUCCEEDED) {
                                store.readManifest(ownerId, projectId)?.toDescriptor()
                            } else {
                                null
                            }
                            emit(DownloadStateMapper.fromEntity(entity, projectId, descriptor))
                        }
                    }
                }
            }
        }

    /**
     * Fuente del owner de sesión: la inyectada por el container (R-T11-05,
     * reactiva, deduplicada) o, si no se inyectó, el fallback de polling de
     * T06. En ambos casos `flatMapLatest` corta la suscripción al DAO al
     * hacer logout o cambiar de cuenta y la recalcula al volver (R-T06-03).
     */
    private fun sessionOwnerFlowSource(): Flow<String?> {
        val injected = sessionOwnerFlow
        if (injected != null) return injected.distinctUntilChanged()
        return flow {
            while (true) {
                emit(sessionOwner())
                delay(sessionPollMillis)
            }
        }.distinctUntilChanged()
    }

    override suspend fun enqueue(ownerId: String, projectId: ProjectId): EnqueueResult {
        if (!isValidOwner(ownerId)) return EnqueueResult.InvalidOwner
        if (sessionOwner() != ownerId) return EnqueueResult.InvalidOwner

        val current = downloadDao.row(ownerId, projectId.value)
        if (current != null && isActiveState(current.state)) {
            // Repetir tap mientras descarga: no se duplica trabajo.
            return EnqueueResult.AlreadyActive
        }

        // 1) Fila durable ANTES de hacer visible el WorkRequest (R-T06-04):
        //    un Worker que arranque inmediatamente (red disponible) debe ver
        //    la fila Queued, no una ausente o terminal (p. ej. al actualizar
        //    un snapshot Succeeded).
        downloadDao.upsert(
            DownloadStateEntity(
                ownerId = ownerId,
                projectId = projectId.value,
                workId = "", // el Worker fija su id real al arrancar (CAS)
                state = DownloadStateEntity.STATE_QUEUED,
                requestedAt = nowMillis(),
            ),
        )
        return try {
            scheduler.enqueueUnique(
                DownloadWorkNames.forProject(ownerId, projectId),
                requestFactory.build(ownerId, projectId),
            )
            EnqueueResult.Enqueued
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // 2) Reconciliación explícita: sin trabajo visible no puede
            //    quedar una fila Queued huérfana. Solo se borra si ningún
            //    worker la reclamó aún (workId "").
            val row = downloadDao.row(ownerId, projectId.value)
            if (row != null && row.workId == "") {
                downloadDao.delete(ownerId, projectId.value)
            }
            EnqueueResult.EnqueueFailed
        }
    }

    override suspend fun cancel(ownerId: String, projectId: ProjectId) {
        if (!isValidOwner(ownerId)) return
        // Igualdad estricta con la sesión: sin sesión u otra cuenta, no se
        // muta ni cancela nada de otro owner (R-T06-03).
        if (sessionOwner() != ownerId) return
        markCancelledBeforeWorkManager(ownerId, projectId)
        scheduler.cancelUnique(DownloadWorkNames.forProject(ownerId, projectId))
    }

    override suspend fun deleteLocal(ownerId: String, projectId: ProjectId) {
        if (!isValidOwner(ownerId)) return
        if (sessionOwner() != ownerId) return
        // 1) marcar terminal (bloquea el commit de un worker en vuelo),
        // 2) cancelar el trabajo, 3) borrar filas locales — snapshot/estado/
        //    cola vía store.delete (T03) e ÍNDICE de catálogo (R-T06-05,
        //    decisión de plan: deleteLocal borra también ProjectSummaryEntity),
        //    4) limpiar temporales huérfanos de ESTE proyecto (R-T06-06):
        //    el sweep es scoped por owner/proyecto, nunca toca temporales
        //    activos de otros proyectos.
        markCancelledBeforeWorkManager(ownerId, projectId)
        scheduler.cancelUnique(DownloadWorkNames.forProject(ownerId, projectId))
        store.delete(ownerId, projectId)
        summaryDao.delete(ownerId, projectId.value)
        tempOrphanSweep(ownerId, projectId.value)
    }

    private suspend fun markCancelledBeforeWorkManager(ownerId: String, projectId: ProjectId) {
        val current = downloadDao.row(ownerId, projectId.value) ?: return
        if (DownloadStateEntity.isTerminalState(current.state)) return
        downloadDao.upsert(
            current.copy(
                state = DownloadStateEntity.STATE_CANCELLED,
                finishedAt = nowMillis(),
            ),
        )
    }

    private fun isActiveState(state: String): Boolean =
        state == DownloadStateEntity.STATE_QUEUED ||
            state == DownloadStateEntity.STATE_DOWNLOADING ||
            state == DownloadStateEntity.STATE_PREPARING ||
            state == DownloadStateEntity.STATE_COMMITTING

    private fun isValidOwner(ownerId: String): Boolean = try {
        SnapshotOwnerValidator.requireValidOwner(ownerId)
        true
    } catch (_: SnapshotStoreException) {
        false
    }
}

package com.explainer.app.feature.download

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.SnapshotContractException
import com.explainer.app.data.local.db.DownloadStateDao
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.snapshot.OfflineSnapshotStore
import com.explainer.app.data.local.snapshot.SnapshotCommitResult
import com.explainer.app.data.local.snapshot.SnapshotOwnerValidator
import com.explainer.app.data.local.snapshot.SnapshotStoreException
import com.explainer.app.data.remote.contract.ProjectRemoteDataSource
import com.explainer.app.data.remote.contract.RemoteResult
import kotlinx.coroutines.CancellationException
import java.io.File
import java.util.UUID

/**
 * Entrada del motor de descarga. [expectedWorkId] es el id del work único
 * WorkManager (`id.toString()` del Worker): el commit atómico (T03) solo
 * publica si esa fila sigue activa con este workId. [attempt] es 1-based
 * (`runAttemptCount + 1` del Worker).
 */
data class DownloadRequest(
    val ownerId: String,
    val projectId: ProjectId,
    val expectedWorkId: String,
    val attempt: Int,
)

/** Resultado del motor; el Worker lo traduce a `Result` de WorkManager. */
sealed interface DownloadOutcome {
    data object Succeeded : DownloadOutcome
    data object Cancelled : DownloadOutcome

    /** Red/timeout/429/5xx con intentos restantes: el Worker responde `retry()`. */
    data object Retryable : DownloadOutcome
    data class Failed(val error: DownloadError) : DownloadOutcome
}

/**
 * Motor puro de descarga (plan.md §6): remote stream → validación → prepare →
 * commit atómico. Sin WorkManager ni Android framework; solo puertos
 * inyectables (remote T02, store/DAOs T03, session T04) para que el Worker sea
 * un adaptador fino y cancelable.
 *
 * Invariantes que garantiza:
 * - No descarga ni observa datos de otro owner de sesión: la igualdad es
 *   ESTRICTA con un owner de sesión NO nulo (logout también aborta).
 * - Cancel/delete previos (estado terminal o fila borrada) abortan antes de
 *   tocar red; el reclamo del workId es un compare-and-set atómico
 *   (R-T06-01): un worker tardío jamás reactiva una fila borrada, sobrescribe
 *   un estado terminal ni pisa el workId de otro intento.
 * - `commit(prepared, expectedWorkId)` (T03) impide republicar tras
 *   cancel/delete; `RejectedCancelledOrSuperseded` se trata como cancelación.
 * - TODO fallo terminal emite `DownloadState.Failed` (R-T06-02): el estado
 *   durable queda Failed para no-space, auth, 4xx, parse/local y retry
 *   agotado; los intermedios Retryable NO se convierten en terminal.
 * - El temporal vive bajo `cacheDir` con nombre UUID con namespace
 *   owner/proyecto, se borra en cualquier camino (éxito, fallo, cancelación)
 *   de forma verificada con reintento y el sweep de huérfanos es SCOPED al
 *   propio owner/proyecto (R-T06-06): nunca toca temporales ACTIVOS de otros
 *   proyectos/owners que compartan cacheDir.
 * - Espacio: preflight `2*esperado + 32 MiB`; se recalcula con
 *   `Content-Length` y se vigila durante el stream; sin espacio no se
 *   prepara/commitea ni se toca la versión anterior.
 * - El progreso se emite throttled (4 Hz o 256 KiB) pero las transiciones y
 *   el valor final siempre se publican.
 */
class DownloadProjectUseCase(
    private val remote: ProjectRemoteDataSource,
    private val store: OfflineSnapshotStore,
    private val downloadDao: DownloadStateDao,
    private val summaryDao: ProjectSummaryDao,
    private val tempDirProvider: () -> File,
    private val diskFreeBytes: (File) -> Long,
    private val sessionOwner: () -> String?,
    private val uuidProvider: () -> String = { UUID.randomUUID().toString() },
    private val nowMillis: () -> Long = System::currentTimeMillis,
    private val tempFileCleaner: TempFileCleaner = TempFileCleaner(tempDirProvider),
) {

    suspend fun execute(
        request: DownloadRequest,
        emitState: suspend (DownloadState) -> Unit,
    ): DownloadOutcome {
        val projectId = request.projectId
        val owner = try {
            SnapshotOwnerValidator.requireValidOwner(request.ownerId)
        } catch (_: SnapshotStoreException) {
            return fail(projectId, DownloadError.Permanent("owner"), emitState)
        }

        // Un worker no descarga ni observa datos de una sesión distinta; sin
        // sesión (logout) tampoco: la igualdad es estricta con owner no nulo.
        if (sessionOwner() != owner) return DownloadOutcome.Cancelled

        val throttler = ProgressThrottler(nowMillis)
        var spaceTripped = false
        var temp: File? = null

        try {
            // Limpieza posterior de temporales huérfanos de corridas previas
            // de ESTE owner/proyecto (R-T06-06): el sweep es scoped por
            // namespace `download-<owner>-<project>-`, así que un temporal
            // ACTIVO de otro proyecto nunca se toca.
            tempFileCleaner.sweepOrphans(owner, projectId.value)

            // ---- guardas de arranque: cancel/delete previos abortan ----
            val row = downloadDao.row(owner, projectId.value)
                ?: return DownloadOutcome.Cancelled
            if (DownloadStateEntity.isTerminalState(row.state)) return DownloadOutcome.Cancelled
            if (row.workId != request.expectedWorkId) {
                // Primer contacto de este intento: reclama la fila (enqueue la
                // creó con workId "") con un COMPARE-AND-SET atómico. Si
                // cancel/delete ganaron entre la lectura y el reclamo, o la
                // fila ya la reclamó otro work, el CAS afecta a 0 filas y este
                // worker aborta sin tocar red (R-T06-01).
                val claimed = downloadDao.casUpdate(
                    ownerId = owner,
                    projectId = projectId.value,
                    expectedWorkId = "",
                    newWorkId = request.expectedWorkId,
                    state = DownloadStateEntity.STATE_QUEUED,
                    downloadedBytes = 0L,
                    totalBytes = null,
                    errorCategory = null,
                    finishedAt = null,
                )
                if (claimed == 0) return DownloadOutcome.Cancelled
            }
            emitState(DownloadState.Queued(projectId, row.requestedAt))

            // ---- preflight: estimación y espacio ----
            val summary = summaryDao.summaryRow(owner, projectId.value)
            val manifest = store.readManifest(owner, projectId)
            var estimate = SizeEstimator.fromSegmentation(
                segmentationBytes = summary?.segmentationSourceBytes ?: 0L,
                currentSnapshotBytes = manifest?.totalBytes,
            )
            val tempDir = tempDirProvider()
            if (!StorageGuard.sufficientSpace(diskFreeBytes(tempDir), estimate.highBytes, 0L)) {
                return fail(projectId, DownloadError.NotEnoughSpace, emitState)
            }

            temp = File(tempDir, tempFileCleaner.tempFileName(owner, projectId.value, uuidProvider()))
            emitState(DownloadState.Downloading(0L, null, estimate))

            val result = remote.downloadProjectTo(projectId, temp) { received, total ->
                if (total != null && estimate.confidence != SizeConfidence.HEADER) {
                    // Content-Length tardío: sustituye el total heurístico.
                    estimate = SizeEstimator.fromContentLength(total)
                }
                if (!StorageGuard.sufficientSpace(diskFreeBytes(tempDir), total ?: estimate.highBytes, received)) {
                    spaceTripped = true
                }
                if (throttler.forward(received)) {
                    emitState(DownloadState.Downloading(received, total, estimate))
                }
            }

            return when (result) {
                is RemoteResult.Success -> {
                    val file = result.value
                    // Valor final SIEMPRE se publica (aunque el throttler lo
                    // hubiera callado); EXACT solo si el header fue verificado
                    // contra los bytes escritos (T04 ya anula total si difiere).
                    val finalEstimate = file.contentLength?.let { SizeEstimator.verified(it) } ?: estimate
                    emitState(DownloadState.Downloading(file.receivedBytes, file.contentLength, finalEstimate))
                    if (spaceTripped) return fail(projectId, DownloadError.NotEnoughSpace, emitState)

                    emitState(DownloadState.Preparing(projectId))
                    val prepared = try {
                        store.prepare(owner, file.file)
                    } catch (_: SnapshotContractException) {
                        return fail(projectId, DownloadError.InvalidPayload("json"), emitState)
                    } catch (_: SnapshotStoreException) {
                        return fail(projectId, DownloadError.Local("file"), emitState)
                    }

                    emitState(DownloadState.Committing(projectId))
                    when (val committed = store.commit(prepared, request.expectedWorkId)) {
                        is SnapshotCommitResult.Committed -> {
                            emitState(DownloadState.Succeeded(committed.descriptor))
                            DownloadOutcome.Succeeded
                        }
                        SnapshotCommitResult.RejectedCancelledOrSuperseded -> {
                            // Cancel/delete ganaron la carrera: nunca retry.
                            emitState(DownloadState.Cancelled(projectId))
                            DownloadOutcome.Cancelled
                        }
                    }
                }
                is RemoteResult.AuthRequired -> fail(projectId, DownloadError.AuthRequired, emitState)
                is RemoteResult.NotFound -> fail(projectId, DownloadError.NotFound, emitState)
                is RemoteResult.RateLimited -> retryDecision(result, request.attempt, projectId, emitState)
                is RemoteResult.Retryable -> retryDecision(result, request.attempt, projectId, emitState)
                is RemoteResult.InvalidPayload -> fail(projectId, DownloadError.InvalidPayload(result.reason), emitState)
                is RemoteResult.PermanentFailure -> fail(projectId, DownloadError.Permanent(result.reason), emitState)
                is RemoteResult.Cancelled -> {
                    emitState(DownloadState.Cancelled(projectId))
                    DownloadOutcome.Cancelled
                }
            }
        } catch (e: CancellationException) {
            // Worker detenido (cancelación o stop del sistema): estado
            // visible cancelado (best-effort; la fila terminal la marca el
            // coordinador antes de cancelar) y temporal eliminado.
            try {
                emitState(DownloadState.Cancelled(projectId))
            } catch (_: CancellationException) {
                // Corrutina ya cancelada: no hay escritura posible.
            }
            return DownloadOutcome.Cancelled
        } finally {
            // Borrado verificado con reintento; si el FS se niega, queda
            // registrado como orphan y el sweep posterior lo elimina.
            tempFileCleaner.deleteVerified(temp)
        }
    }

    /**
     * Emite el fallo terminal como estado durable (R-T06-02) y devuelve el
     * outcome correspondiente. La escritura real la hace el persister del
     * Worker con CAS: si cancel/delete ganaron, la fila terminal ya no se
     * pisa.
     */
    private suspend fun fail(
        projectId: ProjectId,
        error: DownloadError,
        emitState: suspend (DownloadState) -> Unit,
    ): DownloadOutcome {
        emitState(DownloadState.Failed(projectId, error))
        return DownloadOutcome.Failed(error)
    }

    private suspend fun retryDecision(
        result: RemoteResult<Nothing>,
        attempt: Int,
        projectId: ProjectId,
        emitState: suspend (DownloadState) -> Unit,
    ): DownloadOutcome = when (DownloadRetryPolicy.classify(result, attempt)) {
        // Intermedio: la fila sigue activa para el siguiente intento (nunca
        // terminal); el backoff lo aplica WorkManager.
        RetryDecision.Retry -> DownloadOutcome.Retryable
        // Quinto intento agotado: fallo terminal durable.
        RetryDecision.GiveUp -> fail(projectId, DownloadError.Network, emitState)
        RetryDecision.Cancel -> {
            emitState(DownloadState.Cancelled(projectId))
            DownloadOutcome.Cancelled
        }
    }
}

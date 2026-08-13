package com.explainer.app.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.explainer.app.feature.download.DownloadOutcome
import com.explainer.app.feature.download.DownloadProjectUseCase
import com.explainer.app.feature.download.DownloadRequest
import com.explainer.app.feature.download.DownloadState
import com.explainer.app.feature.download.DownloadStatePersister

/**
 * Dependencias del [DownloadProjectWorker], inyectadas por la custom
 * WorkerFactory de T11. El Worker es un adaptador fino: el motor puro y la
 * persistencia durable viven en `feature/download` (JVM-testable).
 *
 * [authReady] es el gate de arranque (R-T11-01): mientras `awaitInitialization()`
 * del gateway no ha terminado, el worker NO ejecuta el motor (un owner nulo
 * en ese estado no es un logout) y reintenta de forma durable sin marcar
 * éxito, de modo que una fila `Queued` de un proceso anterior nunca queda
 * huérfana. El container inyecta `{ state !is SessionState.Initializing }`.
 */
class DownloadWorkerDeps(
    val useCase: DownloadProjectUseCase,
    val persister: DownloadStatePersister,
    val authReady: () -> Boolean = { true },
)

/**
 * Worker de descarga durable: adaptador FINO y cancelable sobre el motor puro
 * ([DownloadProjectUseCase]). El constructor es inyectable para que la custom
 * WorkerFactory de T11 le suministre [DownloadWorkerDeps].
 *
 * - `Data` solo transporta `owner_id`/`project_id` (nunca blobs).
 * - El progreso durable lo escribe el persister en `DownloadStateEntity`
 *   (Room); `setProgress` de WorkInfo solo complementa (bytes, no estado).
 * - [DownloadWorkerPolicy.resultFor]: cancelado → success (nunca retry);
 *   retry() solo con intentos restantes del clasificador.
 */
class DownloadProjectWorker(
    appContext: Context,
    params: WorkerParameters,
    private val deps: DownloadWorkerDeps,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val input = DownloadWorkerPolicy.parseInput(inputData) ?: return Result.failure()

        if (!deps.authReady()) {
            // R-T11-01: auth sigue inicializando (`awaitInitialization()` en
            // curso). El owner nulo de ese estado NO es un logout: interpretarlo
            // como cancelación marcaría éxito y dejaría la fila Queued sin
            // trabajo activo. Reintento durable (backoff exponencial de T06)
            // hasta que la inicialización termine; entonces se reanuda.
            return Result.retry()
        }

        val outcome = deps.useCase.execute(
            request = DownloadRequest(
                ownerId = input.ownerId,
                projectId = input.projectId,
                expectedWorkId = id.toString(),
                attempt = runAttemptCount + 1,
            ),
            emitState = { state ->
                deps.persister.persist(input.ownerId, input.projectId, id.toString(), state)
                if (state is DownloadState.Downloading) {
                    // Complemento opcional del progreso durable (Room manda).
                    try {
                        setProgress(progressDataFor(state))
                    } catch (_: RuntimeException) {
                        // setProgress puede fallar si el worker ya se detuvo;
                        // la fuente durable ya quedó escrita.
                    }
                }
            },
        )
        return DownloadWorkerPolicy.resultFor(outcome)
    }

    private fun progressDataFor(state: DownloadState.Downloading): Data =
        if (state.totalBytes != null) {
            workDataOf(
                KEY_PROGRESS_BYTES to state.downloadedBytes,
                KEY_PROGRESS_TOTAL to state.totalBytes,
            )
        } else {
            workDataOf(KEY_PROGRESS_BYTES to state.downloadedBytes)
        }

    companion object {
        const val KEY_OWNER_ID = "owner_id"
        const val KEY_PROJECT_ID = "project_id"

        /** Claves de progreso complementario en WorkInfo (bytes, pequeños). */
        const val KEY_PROGRESS_BYTES = "downloaded_bytes"
        const val KEY_PROGRESS_TOTAL = "total_bytes"
    }
}

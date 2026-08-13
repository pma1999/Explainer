package com.explainer.app.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.explainer.app.feature.progress.ProgressSyncCoordinator
import com.explainer.app.feature.progress.SyncAction
import com.explainer.app.feature.progress.action

/**
 * Dependencias del [ProgressSyncWorker], inyectadas por la custom
 * WorkerFactory de T11 (mismo patrón que [DownloadWorkerDeps]).
 *
 * [sessionOwner] es el owner de la sesión ACTUAL (o null si no hay sesión:
 * inicializando, logout o token no utilizable). Es el gate RC-01: un trabajo
 * A que sobreviva a logout/login B nunca lee filas A ni las envía con el
 * bearer de B. El default es fail-closed (`{ null }`): sin inyección
 * explícita el worker bloquea, no filtra datos ajenos.
 */
class ProgressWorkerDeps(
    val coordinator: ProgressSyncCoordinator,
    val sessionOwner: () -> String? = { null },
)

/**
 * Worker de sync de progreso: único por owner (`progress-sync:<ownerId>`),
 * con red conectada, input `owner_id` y backoff exponencial desde 30 s.
 *
 * Toda la lógica vive en [ProgressSyncCoordinator] (JVM-testable con fakes);
 * aquí solo se clasifica el outcome:
 * - éxito/sesión ausente/owner distinto/401/404/permanente -> success (la
 *   cola durable se conserva; no hay loop de reintento);
 * - 429/5xx/red -> retry con backoff (WorkManager lo limita a 10 intentos;
 *   la cola sigue durmiendo hasta la próxima petición de sync).
 *
 * Gate de sesión (RC-01): ANTES de invocar el motor se comprueba que el
 * `owner_id` de WorkManager coincida con [ProgressWorkerDeps.sessionOwner];
 * si no hay sesión o el owner difiere, la pasada termina en success SIN
 * leer ni enviar nada (la cola durable queda intacta y el scheduler
 * re-encola con el owner correcto en el próximo login/reconexión).
 *
 * El constructor inyectable existe para T11 (custom WorkerFactory); el
 * secundario compone un coordinador autocontenido como fallback inerte.
 */
class ProgressSyncWorker(
    appContext: Context,
    params: WorkerParameters,
    private val deps: ProgressWorkerDeps,
) : CoroutineWorker(appContext, params) {

    constructor(appContext: Context, params: WorkerParameters) : this(
        appContext,
        params,
        ProgressWorkerDeps(ProgressSyncCoordinator.defaultFor(appContext)),
    )

    override suspend fun doWork(): Result {
        val ownerId = inputData.getString(KEY_OWNER_ID) ?: return Result.failure()
        // RC-01: gate ANTES del motor (fail-closed). Sin sesión u owner
        // distinto: success sin tocar la cola — nunca el bearer de otra
        // sesión con filas de esta.
        if (deps.sessionOwner() != ownerId) return Result.success()
        return when (deps.coordinator.syncOnce(ownerId).action()) {
            SyncAction.SUCCESS -> Result.success()
            SyncAction.RETRY -> Result.retry()
        }
    }

    companion object {
        const val KEY_OWNER_ID = "owner_id"

        fun uniqueName(ownerId: String): String = "progress-sync:$ownerId"
    }
}

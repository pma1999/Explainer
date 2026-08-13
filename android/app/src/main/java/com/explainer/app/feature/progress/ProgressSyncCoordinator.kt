package com.explainer.app.feature.progress

import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.PendingProgressOverlay
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.core.model.ReadingProgressMergePolicy
import com.explainer.app.data.local.db.PendingProgressDao
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryDao
import com.explainer.app.data.local.db.SnapshotDao
import com.explainer.app.data.local.snapshot.PendingOverlayBuilder
import com.explainer.app.data.local.snapshot.SnapshotOwnerValidator
import com.explainer.app.data.remote.contract.ProjectRemoteDataSource
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.data.remote.dto.SubsectionProgressPatch
import kotlinx.coroutines.flow.first

/**
 * Resultado de una pasada de sync del worker (clasificación para
 * WorkManager: solo los reintentables producen retry).
 */
sealed interface SyncOutcome {
    /** Al menos una operación se transmitió y quedó ACKNOWLEDGED. */
    data object Synced : SyncOutcome
    data object NothingPending : SyncOutcome
    /** Intervalo mínimo no transcurrido: sin red, sin tocar la cola. */
    data object SkippedMinInterval : SyncOutcome
    /** Sin sesión/owner inválido: la cola se conserva (sin loop). */
    data object NoSession : SyncOutcome
    /** 401 definitivo: la cola se conserva (sin loop). */
    data object AuthRequired : SyncOutcome
    /** 404: remoto no disponible; snapshot y cola se conservan. */
    data object NotFound : SyncOutcome
    data object InvalidData : SyncOutcome
    /** 429/5xx/red: reintentar con backoff. */
    data object Retryable : SyncOutcome
    data class PermanentFailure(val reason: String) : SyncOutcome
    data object Cancelled : SyncOutcome
}

/** Acción de WorkManager derivada del outcome (clasificación testeable). */
internal enum class SyncAction { SUCCESS, RETRY }

internal fun SyncOutcome.action(): SyncAction = when (this) {
    SyncOutcome.Synced, SyncOutcome.NothingPending, SyncOutcome.SkippedMinInterval,
    SyncOutcome.NoSession, SyncOutcome.AuthRequired, SyncOutcome.NotFound,
    SyncOutcome.InvalidData, SyncOutcome.Cancelled,
    -> SyncAction.SUCCESS

    // R-T07-03: el fallo permanente es terminal — la fila y su estado visible
    // se conservan (PENDING), pero WorkManager NO reintenta (sin loop para
    // 400/403; solo 429/5xx/red son reintentables).
    is SyncOutcome.Retryable -> SyncAction.RETRY
    is SyncOutcome.PermanentFailure -> SyncAction.SUCCESS
}

/**
 * Motor de sync durable de progreso (el cerebro del worker; sin dependencias
 * de Android ni WorkManager). Lee SOLO filas PENDING de la cola (la fila es
 * la key de coalescencia: un evento repetido no crea filas por scroll),
 * transmite por proyecto/parte/tab y marca ACKNOWLEDGED tras éxito. Un
 * fallo de red/401 nunca descarta intención. Enumerar proyectos candidatos
 * con la unión summary ∪ snapshot: la cola solo existe para proyectos con
 * resumen o snapshot (delete local elimina la cola junto al resto).
 *
 * Gate de sesión (RC-01): si se inyecta [sessionOwner] (owner de la sesión
 * ACTUAL, o null sin sesión), la pasada se bloquea devolviendo
 * [SyncOutcome.NoSession] ANTES de leer la cola y ANTES de cada envío cuando
 * el owner de la cola no coincide con el de la sesión. Así un trabajo A que
 * sobreviva a logout/login B nunca lee filas A ni las envía con el bearer de
 * B, y la cola bloqueada se CONSERVA (nunca ACK/borrado). Sin inyección
 * (contrato T07: fallback autocontenido y tests heredados) el gate no aplica.
 */
class ProgressSyncCoordinator(
    private val remote: ProjectRemoteDataSource,
    private val pendingDao: PendingProgressDao,
    private val summaryDao: ProjectSummaryDao,
    private val snapshotDao: SnapshotDao,
    private val throttle: ProgressThrottle,
    private val minIntervalMs: Long = MIN_INTERVAL_MS,
    /** Owner de la sesión actual (null = sin sesión); null = gate inactivo. */
    private val sessionOwner: (() -> String?)? = null,
) {
    suspend fun syncOnce(ownerId: String): SyncOutcome {
        val owner = try {
            SnapshotOwnerValidator.requireValidOwner(ownerId)
        } catch (_: Exception) {
            return SyncOutcome.NoSession
        }
        // RC-01: sin sesión o con un owner distinto al de la cola, la pasada
        // se bloquea ANTES de leer nada; la cola queda intacta (NoSession ->
        // SUCCESS del worker, sin loop de reintento).
        if (!sessionMatches(owner)) return SyncOutcome.NoSession
        if (throttle.remainingToMinInterval(owner, minIntervalMs) > 0L) {
            return SyncOutcome.SkippedMinInterval
        }

        val candidates = (
            summaryDao.observeSummaries(owner).first().map { it.projectId } +
                snapshotDao.observeSnapshots(owner).first().map { it.projectId }
            ).distinct()

        var flushedAny = false
        var failure: SyncOutcome? = null
        for (projectId in candidates) {
            // RC-01: re-verificar antes de leer la cola de cada proyecto (un
            // logout intercalado entre proyectos corta la pasada).
            if (!sessionMatches(owner)) return SyncOutcome.NoSession
            val rows = pendingDao.pendingRows(owner, projectId)
            if (rows.isEmpty()) continue
            when (val projectOutcome = flushProject(owner, projectId, rows)) {
                SyncOutcome.Synced -> flushedAny = true
                SyncOutcome.NoSession, SyncOutcome.AuthRequired, SyncOutcome.Cancelled -> return projectOutcome
                SyncOutcome.NotFound, SyncOutcome.InvalidData, SyncOutcome.Retryable,
                is SyncOutcome.PermanentFailure,
                -> if (failure == null) failure = projectOutcome

                SyncOutcome.NothingPending, SyncOutcome.SkippedMinInterval -> Unit
            }
        }
        return failure ?: if (flushedAny) SyncOutcome.Synced else SyncOutcome.NothingPending
    }

    /** RC-01: ¿el owner de la cola coincide con la sesión actual? */
    private fun sessionMatches(owner: String): Boolean =
        sessionOwner == null || sessionOwner?.invoke() == owner

    private suspend fun flushProject(
        owner: String,
        projectId: String,
        rows: List<PendingProgressEntity>,
    ): SyncOutcome {
        val id = ProjectId.parse(projectId) ?: return SyncOutcome.InvalidData

        // Secciones: un PATCH por parte (`/progress` con {part_id, completed}).
        for (row in rows.filter { it.kindTarget == PendingProgressEntity.KIND_SECTION }) {
            val desired = row.desiredCompleted ?: continue
            // RC-01: gate ANTES de cada envío (un logout intercalado a mitad
            // de la pasada no usa el bearer de la sesión nueva con filas del
            // owner viejo).
            if (!sessionMatches(owner)) return SyncOutcome.NoSession
            when (val outcome = classify(owner, remote.patchSection(id, row.partId, desired), listOf(row))) {
                SyncOutcome.Synced -> Unit
                else -> return outcome
            }
        }

        // Subsecciones: batch coalescido por (parte, tab) con
        // completed/uncompleted/last_subsection_id (endpoint T02).
        val subsectionRows = rows.filter {
            it.kindTarget.startsWith(PendingProgressEntity.KIND_SUBSECTION_PREFIX) ||
                it.kindTarget == PendingProgressEntity.KIND_LAST_READ
        }
        for ((key, group) in subsectionRows.groupBy { it.partId to it.tab }) {
            val (partId, tab) = key
            // Defensa en profundidad: los IDs ya se validaron al encolar;
            // aquí se filtran por si una fila corrupta llegara a la cola.
            val valid = group.filter { it.isValidSubsectionRow() }
            if (valid.isEmpty()) continue

            val completedIds = valid
                .filter { it.kindTarget.startsWith(PendingProgressEntity.KIND_SUBSECTION_PREFIX) && it.desiredCompleted == true }
                .map { it.kindTarget.removePrefix(PendingProgressEntity.KIND_SUBSECTION_PREFIX) }
            val uncompletedIds = valid
                .filter { it.kindTarget.startsWith(PendingProgressEntity.KIND_SUBSECTION_PREFIX) && it.desiredCompleted == false }
                .map { it.kindTarget.removePrefix(PendingProgressEntity.KIND_SUBSECTION_PREFIX) }
            // R-T07-05: el candidato last-read se elige por `last_read_at`
            // ISO parseado (la MISMA selección que el overlay), no por el
            // reloj de coalescencia `updated_at`.
            val lastRead = PendingOverlayBuilder.lastReadRow(valid)

            val patch = SubsectionProgressPatch(
                partId = partId,
                tab = tab,
                lastSubsectionId = lastRead?.lastSubsectionId,
                completedSubsectionIds = completedIds,
                uncompletedSubsectionIds = uncompletedIds,
            )
            // RC-01: gate ANTES de cada envío (mismo motivo que secciones).
            if (!sessionMatches(owner)) return SyncOutcome.NoSession
            when (val outcome = classify(owner, remote.patchSubsections(id, patch), valid)) {
                SyncOutcome.Synced -> Unit
                else -> return outcome
            }
        }
        return SyncOutcome.Synced
    }

    private suspend fun classify(
        owner: String,
        result: RemoteResult<Unit>,
        rows: List<PendingProgressEntity>,
    ): SyncOutcome = when (result) {
        is RemoteResult.Success -> {
            // R-T07-01: ACK condicional por versión (CAS). Si una escritura
            // local concurrente cambió la fila (nuevo desired/`updated_at`)
            // mientras el PATCH estaba en vuelo, el CAS no la toca y la
            // intención nueva queda PENDING para la próxima pasada.
            rows.forEach { row ->
                pendingDao.acknowledgeIfUnchanged(
                    ownerId = owner,
                    projectId = row.projectId,
                    partId = row.partId,
                    tab = row.tab,
                    kindTarget = row.kindTarget,
                    expectedUpdatedAt = row.updatedAt,
                )
            }
            throttle.recordFlush(owner)
            SyncOutcome.Synced
        }

        RemoteResult.AuthRequired -> SyncOutcome.AuthRequired
        RemoteResult.NotFound -> SyncOutcome.NotFound
        RemoteResult.RateLimited, RemoteResult.Retryable -> {
            rows.forEach { pendingDao.upsert(it.copy(attempts = it.attempts + 1)) }
            SyncOutcome.Retryable
        }

        is RemoteResult.InvalidPayload -> SyncOutcome.InvalidData
        is RemoteResult.PermanentFailure -> SyncOutcome.PermanentFailure(result.reason)
        RemoteResult.Cancelled -> SyncOutcome.Cancelled
    }

    private fun PendingProgressEntity.isValidSubsectionRow(): Boolean {
        val target = when (kindTarget) {
            PendingProgressEntity.KIND_LAST_READ -> lastSubsectionId
            else -> kindTarget.removePrefix(PendingProgressEntity.KIND_SUBSECTION_PREFIX)
        }
        return !target.isNullOrBlank() && target.startsWith("subsec-$partId-")
    }

    companion object {
        const val DEBOUNCE_MS = 15_000L
        const val MIN_INTERVAL_MS = 60_000L

        @Volatile
        private var defaultCoordinator: ProgressSyncCoordinator? = null

        /**
         * Fallback autocontenido (sin AppContainer) para que el worker
         * componga solo hasta que T11 lo inyecte con custom WorkerFactory:
         * Room real + gateway de sesión + cliente Ktor, uno por proceso.
         */
        fun defaultFor(context: android.content.Context): ProgressSyncCoordinator =
            defaultCoordinator ?: synchronized(this) {
                defaultCoordinator ?: buildDefault(context).also { defaultCoordinator = it }
            }

        private fun buildDefault(context: android.content.Context): ProgressSyncCoordinator {
            val config = com.explainer.app.core.config.AppConfig.fromBuildConfig()
            val db = com.explainer.app.data.local.db.ExplainerDatabase.create(context)
            val scope = kotlinx.coroutines.CoroutineScope(
                kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Default,
            )
            val gateway = com.explainer.app.data.auth.SupabaseSessionGateway.create(config, scope)
            val remote = com.explainer.app.data.remote.KtorProjectRemoteDataSource(gateway, config.apiBaseUrl)
            return ProgressSyncCoordinator(
                remote = remote,
                pendingDao = db.pendingProgressDao(),
                summaryDao = db.projectSummaryDao(),
                snapshotDao = db.snapshotDao(),
                throttle = ProgressThrottle(),
            )
        }
    }
}

/**
 * Vista de progreso mezclada para UI: remoto (summary) ∪ local (snapshot) ∪
 * overlay optimista, SIEMPRE con la `ReadingProgressMergePolicy` de T02
 * (no se duplica el algoritmo en este package).
 */
internal object ProgressMerge {
    fun merged(
        summaryProgress: ReadingProgress?,
        snapshotProgress: ReadingProgress?,
        overlay: PendingProgressOverlay?,
    ): ReadingProgress = ReadingProgressMergePolicy.merge(
        remote = summaryProgress ?: ReadingProgress(),
        local = snapshotProgress,
        pending = overlay,
    )
}

package com.explainer.app.feature.progress

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.OfflineSnapshotEntity
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.InMemoryPendingProgressDao
import com.explainer.app.data.local.snapshot.InMemorySnapshotDao
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.data.remote.dto.SubsectionProgressPatch
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Aceptación del motor de sync durable (el cerebro del worker):
 * - Éxito: PENDING -> ACKNOWLEDGED, batch coalescido por parte/tab, throttle.
 * - AuthRequired/404/permanente: cola intacta; reintentables incrementan attempts.
 * - Solo PENDING se transmite; ACKNOWLEDGED nunca se reenvía.
 * - IDs de subsección no válidos nunca llegan al wire.
 */
class ProgressSyncCoordinatorTest {


    private class Harness {
        val owner = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
        val pid = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f").value
        val remote = FakeProgressRemote()
        val pending = InMemoryPendingProgressDao()
        val summaries = InMemoryProjectSummaryDao()
        val snapshots = InMemorySnapshotDao()
        var now = 10_000L
        val throttle = ProgressThrottle { now }

        fun coordinator(minIntervalMs: Long = 60_000L) = ProgressSyncCoordinator(
            remote = remote,
            pendingDao = pending,
            summaryDao = summaries,
            snapshotDao = snapshots,
            throttle = throttle,
            minIntervalMs = minIntervalMs,
        )

        suspend fun summary(project: String = pid) {
            summaries.upsert(
                ProjectSummaryEntity(
                    ownerId = owner,
                    projectId = project,
                    name = "P",
                    remoteUpdatedAt = "2026-08-01T10:00:00.000Z",
                ),
            )
        }

        fun snapshot(project: String = pid) {
            snapshots.snapshots[owner to project] = OfflineSnapshotEntity(
                ownerId = owner,
                projectId = project,
                activeGeneration = "gen-1",
            )
        }

        fun row(
            partId: Int,
            kindTarget: String,
            tab: String = "explicacion",
            desired: Boolean? = null,
            lastSubsectionId: String? = null,
            lastReadAt: String? = null,
            updatedAt: Long = 1_000L,
            syncState: String = PendingProgressEntity.SYNC_PENDING,
            attempts: Int = 0,
        ) = PendingProgressEntity(
            ownerId = owner,
            projectId = pid,
            partId = partId,
            tab = tab,
            kindTarget = kindTarget,
            desiredCompleted = desired,
            lastSubsectionId = lastSubsectionId,
            lastReadAt = lastReadAt,
            syncState = syncState,
            attempts = attempts,
            updatedAt = updatedAt,
        )
    }

    private fun syncStateOf(h: Harness, partId: Int, kindTarget: String, tab: String = "explicacion"): String =
        h.pending.rows[h.owner to h.pid].orEmpty()
            .first { it.partId == partId && it.kindTarget == kindTarget && it.tab == tab }
            .syncState

    @Test
    fun `exito marca ACKNOWLEDGED y registra flush en el throttle`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0", desired = true))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_LAST_READ, lastSubsectionId = "subsec-1-a-0", lastReadAt = "2026-08-01T10:00:01.000Z", updatedAt = 1_000L))

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.Synced, outcome)
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, syncStateOf(h, 1, PendingProgressEntity.KIND_SECTION, "section"))
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, syncStateOf(h, 1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0"))
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, syncStateOf(h, 1, PendingProgressEntity.KIND_LAST_READ))
        assertEquals(1, h.remote.sectionCalls.size)
        assertEquals(true, h.remote.sectionCalls.single().third)
        assertEquals(h.now, h.throttle.lastFlushAtMillis(h.owner))
    }

    @Test
    fun `batch coalescido por parte y tab con completadas anuladas y last-read mas reciente`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0", desired = true))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-b-1", desired = true))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-c-2", desired = false))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_LAST_READ, lastSubsectionId = "subsec-1-a-0", lastReadAt = "2026-08-01T10:00:01.000Z", updatedAt = 1_000L))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_LAST_READ, lastSubsectionId = "subsec-1-b-1", lastReadAt = "2026-08-01T10:00:02.000Z", updatedAt = 2_000L))
        h.pending.upsert(h.row(2, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-2-a-0", desired = true, tab = "recorrido"))

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.Synced, outcome)
        assertEquals(2, h.remote.subsectionCalls.size)
        val patch1 = h.remote.subsectionCalls.first { it.first == h.pid }.second
        assertEquals(1, patch1.partId)
        assertEquals("explicacion", patch1.tab)
        assertEquals(listOf("subsec-1-a-0", "subsec-1-b-1"), patch1.completedSubsectionIds)
        assertEquals(listOf("subsec-1-c-2"), patch1.uncompletedSubsectionIds)
        assertEquals("subsec-1-b-1", patch1.lastSubsectionId)
        val patch2 = h.remote.subsectionCalls.last { it.first == h.pid }.second
        assertEquals(2, patch2.partId)
        assertEquals("recorrido", patch2.tab)
        assertEquals(listOf("subsec-2-a-0"), patch2.completedSubsectionIds)
    }

    @Test
    fun `secciones de partes distintas se patchean individualmente`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))
        h.pending.upsert(h.row(2, PendingProgressEntity.KIND_SECTION, tab = "section", desired = false))

        h.coordinator().syncOnce(h.owner)

        assertEquals(2, h.remote.sectionCalls.size)
        assertEquals(Triple(h.pid, 1, true), h.remote.sectionCalls[0])
        assertEquals(Triple(h.pid, 2, false), h.remote.sectionCalls[1])
    }

    @Test
    fun `ACKNOWLEDGED nunca se reenvia en una segunda pasada`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0", desired = true))

        val coordinator = h.coordinator()
        assertEquals(SyncOutcome.Synced, coordinator.syncOnce(h.owner))
        val callsAfterFirst = h.remote.subsectionCalls.size
        assertEquals(1, callsAfterFirst)

        // Avanza el reloj más allá del intervalo mínimo de 60 s: la segunda
        // pasada no debe reenviar ACKNOWLEDGED (solo PENDING se transmite).
        h.now += 61_000L
        assertEquals(SyncOutcome.NothingPending, coordinator.syncOnce(h.owner))
        assertEquals(callsAfterFirst, h.remote.subsectionCalls.size)
    }

    @Test
    fun `401 conserva la cola PENDING y corta el resto de proyectos`() = runBlocking {
        val h = Harness()
        h.summary()
        h.summary("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))
        h.remote.sectionResult = RemoteResult.AuthRequired

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.AuthRequired, outcome)
        assertEquals(PendingProgressEntity.SYNC_PENDING, syncStateOf(h, 1, PendingProgressEntity.KIND_SECTION, "section"))
        assertEquals(1, h.remote.sectionCalls.size)
        assertEquals(0L, h.throttle.lastFlushAtMillis(h.owner))
    }

    @Test
    fun `429 y 5xx y red son reintentables e incrementan attempts`() = runBlocking {
        listOf(RemoteResult.RateLimited, RemoteResult.Retryable).forEach { result ->
            val h = Harness()
            h.summary()
            h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0", desired = true, attempts = 2))
            h.remote.subsectionResult = result

            val outcome = h.coordinator().syncOnce(h.owner)

            assertEquals(SyncOutcome.Retryable, outcome)
            assertEquals(PendingProgressEntity.SYNC_PENDING, syncStateOf(h, 1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0"))
            val row = h.pending.rows[h.owner to h.pid]!!.first { it.kindTarget.endsWith("subsec-1-a-0") }
            assertEquals(3, row.attempts)
        }
    }

    @Test
    fun `404 conserva la cola y clasifica como NotFound`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_LAST_READ, lastSubsectionId = "subsec-1-a-0", lastReadAt = "2026-08-01T10:00:01.000Z"))
        h.remote.subsectionResult = RemoteResult.NotFound

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.NotFound, outcome)
        assertEquals(PendingProgressEntity.SYNC_PENDING, syncStateOf(h, 1, PendingProgressEntity.KIND_LAST_READ))
    }

    @Test
    fun `fallo permanente conserva la intencion en la cola`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))
        h.remote.sectionResult = RemoteResult.PermanentFailure("http:400")

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.PermanentFailure("http:400"), outcome)
        assertEquals(PendingProgressEntity.SYNC_PENDING, syncStateOf(h, 1, PendingProgressEntity.KIND_SECTION, "section"))
    }

    @Test
    fun `intervalo minimo no transcurrido salta sin red ni toques`() = runBlocking {
        val h = Harness()
        h.now = 100_000L
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))
        h.throttle.recordFlush(h.owner, h.now - 30_000L)

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.SkippedMinInterval, outcome)
        assertTrue(h.remote.sectionCalls.isEmpty())
        assertEquals(PendingProgressEntity.SYNC_PENDING, syncStateOf(h, 1, PendingProgressEntity.KIND_SECTION, "section"))
    }

    @Test
    fun `sin operaciones pendientes devuelve NothingPending sin red`() = runBlocking {
        val h = Harness()
        h.summary()
        assertEquals(SyncOutcome.NothingPending, h.coordinator().syncOnce(h.owner))
        assertTrue(h.remote.sectionCalls.isEmpty())
        assertTrue(h.remote.subsectionCalls.isEmpty())
    }

    @Test
    fun `IDs de subseccion invalidos en cola se filtran del wire`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "sec-1-x", desired = true))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-2-wrong-part", desired = true))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0", desired = true))

        h.coordinator().syncOnce(h.owner)

        assertEquals(1, h.remote.subsectionCalls.size)
        val patch: SubsectionProgressPatch = h.remote.subsectionCalls.single().second
        assertEquals(listOf("subsec-1-a-0"), patch.completedSubsectionIds)
    }

    @Test
    fun `un proyecto con 404 no impide sincronizar los demas`() = runBlocking {
        val h = Harness()
        val other = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        h.summary()
        h.summary(other)
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))
        h.pending.upsert(
            h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true).copy(projectId = other),
        )
        h.remote.sectionResult = RemoteResult.NotFound

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.NotFound, outcome)
        // El primer proyecto falló (404) y el segundo también; ninguno se ackn.
        assertEquals(2, h.remote.sectionCalls.size)
        assertTrue(h.pending.rows[h.owner to other].orEmpty().all { it.syncState == PendingProgressEntity.SYNC_PENDING })
    }

    @Test
    fun `sync de owner B no toca la cola de owner A`() = runBlocking {
        val h = Harness()
        val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))

        val outcome = h.coordinator().syncOnce(ownerB)

        assertEquals(SyncOutcome.NothingPending, outcome)
        assertTrue(h.remote.sectionCalls.isEmpty())
        assertNull(h.pending.rows[ownerB to h.pid])
    }

    @Test
    fun `owner invalido devuelve NoSession sin tocar nada`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))

        val outcome = h.coordinator().syncOnce("bad owner!")

        assertEquals(SyncOutcome.NoSession, outcome)
        assertTrue(h.remote.sectionCalls.isEmpty())
        assertEquals(PendingProgressEntity.SYNC_PENDING, syncStateOf(h, 1, PendingProgressEntity.KIND_SECTION, "section"))
    }

    @Test
    fun `mapping de accion del worker clasifica retry solo para reintentables`() {
        assertEquals(SyncAction.SUCCESS, SyncOutcome.Synced.action())
        assertEquals(SyncAction.SUCCESS, SyncOutcome.NothingPending.action())
        assertEquals(SyncAction.SUCCESS, SyncOutcome.SkippedMinInterval.action())
        assertEquals(SyncAction.SUCCESS, SyncOutcome.NoSession.action())
        assertEquals(SyncAction.SUCCESS, SyncOutcome.AuthRequired.action())
        assertEquals(SyncAction.SUCCESS, SyncOutcome.NotFound.action())
        assertEquals(SyncAction.SUCCESS, SyncOutcome.InvalidData.action())
        assertEquals(SyncAction.SUCCESS, SyncOutcome.Cancelled.action())
        assertEquals(SyncAction.RETRY, SyncOutcome.Retryable.action())
        // R-T07-03: el fallo permanente es terminal (sin loop de retry); la
        // fila y su estado visible se conservan, pero WorkManager no reintenta.
        assertEquals(SyncAction.SUCCESS, SyncOutcome.PermanentFailure("http:400").action())
    }

    @Test
    fun `fallo permanente es terminal y no incrementa attempts`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true, attempts = 2))
        h.remote.sectionResult = RemoteResult.PermanentFailure("http:400")

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.PermanentFailure("http:400"), outcome)
        val row = h.pending.rows[h.owner to h.pid]!!.single()
        assertEquals(PendingProgressEntity.SYNC_PENDING, row.syncState)
        assertEquals(2, row.attempts)
        assertEquals(SyncAction.SUCCESS, outcome.action())
        assertEquals(0L, h.throttle.lastFlushAtMillis(h.owner))
    }

    @Test
    fun `ACK no pisa una intencion PENDING escrita mientras el PATCH esta en vuelo`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true, updatedAt = 1_000L))
        val started = CompletableDeferred<Unit>()
        val gate = CompletableDeferred<Unit>()
        h.remote.sectionStarted = started
        h.remote.sectionGate = gate

        val job = async { h.coordinator().syncOnce(h.owner) }
        started.await() // el PATCH está en vuelo: las filas ya se leyeron
        // El usuario escribe una intención NUEVA sobre la misma PK (coalescida)
        // mientras el remoto no ha respondido.
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = false, updatedAt = 2_000L))
        gate.complete(Unit) // el remoto responde éxito
        val outcome = job.await()

        assertEquals(SyncOutcome.Synced, outcome)
        // El ACK condicional por versión no pisó la intención nueva: la fila
        // sigue PENDING con el valor nuevo y se transmitirá en la próxima pasada.
        val row = h.pending.rows[h.owner to h.pid]!!.single()
        assertEquals(PendingProgressEntity.SYNC_PENDING, row.syncState)
        assertEquals(false, row.desiredCompleted)
        assertEquals(2_000L, row.updatedAt)
    }

    @Test
    fun `ACK condicional deja ACKNOWLEDGED cuando la version no cambio`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true, updatedAt = 1_000L))

        val outcome = h.coordinator().syncOnce(h.owner)

        assertEquals(SyncOutcome.Synced, outcome)
        val row = h.pending.rows[h.owner to h.pid]!!.single()
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, row.syncState)
        assertEquals(1_000L, row.updatedAt)
    }

    @Test
    fun `last-read del batch se elige por last_read_at ISO y no por updated_at`() = runBlocking {
        val h = Harness()
        h.summary()
        // Fila A: updated_at más reciente pero last_read_at más antiguo.
        // Fila B: updated_at más antiguo pero last_read_at más reciente.
        // Se siembran directamente (misma part/tab: la PK Room solo admite una).
        h.pending.rows.getOrPut(h.owner to h.pid) { mutableListOf() }.apply {
            add(h.row(1, PendingProgressEntity.KIND_LAST_READ, lastSubsectionId = "subsec-1-a-0", lastReadAt = "2026-08-01T10:00:01.000Z", updatedAt = 9_000L))
            add(h.row(1, PendingProgressEntity.KIND_LAST_READ, lastSubsectionId = "subsec-1-b-1", lastReadAt = "2026-08-01T10:00:02.000Z", updatedAt = 1_000L))
        }

        h.coordinator().syncOnce(h.owner)

        val patch = h.remote.subsectionCalls.single().second
        assertEquals("subsec-1-b-1", patch.lastSubsectionId)
    }

    @Test
    fun `throttle es independiente por owner`() = runBlocking {
        val h = Harness()
        val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"
        val other = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        h.summary()
        h.summaries.upsert(ProjectSummaryEntity(ownerId = ownerB, projectId = other, name = "B"))
        h.pending.upsert(h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true))
        h.pending.upsert(
            h.row(1, PendingProgressEntity.KIND_SECTION, tab = "section", desired = true)
                .copy(ownerId = ownerB, projectId = other),
        )

        val coordinator = h.coordinator()
        // A transmite y registra su propio reloj.
        assertEquals(SyncOutcome.Synced, coordinator.syncOnce(h.owner))
        // B puede transmitir de inmediato: el flush de A no contamina su reloj.
        assertEquals(SyncOutcome.Synced, coordinator.syncOnce(ownerB))
        assertEquals(2, h.remote.sectionCalls.size)
    }
}

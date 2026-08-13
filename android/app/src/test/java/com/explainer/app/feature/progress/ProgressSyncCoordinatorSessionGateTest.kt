package com.explainer.app.feature.progress

import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.InMemoryPendingProgressDao
import com.explainer.app.data.local.snapshot.InMemorySnapshotDao
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * RC-01 (revisión final, HIGH): el coordinador de sync bloquea la pasada
 * cuando el owner de la cola no coincide con el owner de la sesión ACTUAL
 * (o no hay sesión). Un trabajo A que sobreviva a logout/login B nunca lee
 * filas A ni las envía con el bearer de B:
 *
 * - gate ANTES de leer la cola (inicio de la pasada y por proyecto);
 * - gate ANTES de CADA envío (logout intercalado a mitad de la pasada);
 * - la cola se CONSERVA (nada de ACK/borrado) para las filas bloqueadas.
 */
class ProgressSyncCoordinatorSessionGateTest {

    private class Harness {
        val ownerA = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
        val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"
        val pid = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f").value
        val remote = FakeProgressRemote()
        val pending = InMemoryPendingProgressDao()
        val summaries = InMemoryProjectSummaryDao()
        val snapshots = InMemorySnapshotDao()
        val throttle = ProgressThrottle()

        /** Owner de la sesión actual (null = sin sesión/inicializando/logout). */
        var sessionOwner: String? = null

        fun coordinator() = ProgressSyncCoordinator(
            remote = remote,
            pendingDao = pending,
            summaryDao = summaries,
            snapshotDao = snapshots,
            throttle = throttle,
            sessionOwner = { sessionOwner },
        )

        suspend fun summary(project: String = pid) {
            summaries.upsert(
                ProjectSummaryEntity(
                    ownerId = ownerA,
                    projectId = project,
                    name = "P",
                    remoteUpdatedAt = "2026-08-01T10:00:00.000Z",
                ),
            )
        }

        fun row(partId: Int, project: String = pid) = PendingProgressEntity(
            ownerId = ownerA,
            projectId = project,
            partId = partId,
            tab = "section",
            kindTarget = PendingProgressEntity.KIND_SECTION,
            desiredCompleted = true,
            lastSubsectionId = null,
            lastReadAt = null,
            syncState = PendingProgressEntity.SYNC_PENDING,
            attempts = 0,
            updatedAt = 1_000L,
        )

        fun rowsOf(project: String = pid): List<PendingProgressEntity> =
            pending.rows[ownerA to project].orEmpty()
    }

    @Test
    fun `sesion con owner distinto (A con sesion B) bloquea y conserva la cola`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1))
        h.sessionOwner = h.ownerB

        val outcome = h.coordinator().syncOnce(h.ownerA)

        assertEquals(SyncOutcome.NoSession, outcome)
        assertTrue("ningún envío con el bearer de B", h.remote.sectionCalls.isEmpty())
        assertTrue(h.remote.subsectionCalls.isEmpty())
        val row = h.rowsOf().single()
        assertEquals(PendingProgressEntity.SYNC_PENDING, row.syncState)
    }

    @Test
    fun `sesion nula (logout o inicializando) bloquea y conserva la cola`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1))
        h.sessionOwner = null

        val outcome = h.coordinator().syncOnce(h.ownerA)

        assertEquals(SyncOutcome.NoSession, outcome)
        assertTrue(h.remote.sectionCalls.isEmpty())
        assertTrue(h.remote.subsectionCalls.isEmpty())
        assertEquals(PendingProgressEntity.SYNC_PENDING, h.rowsOf().single().syncState)
    }

    @Test
    fun `logout intercalado entre envios corta la pasada sin envios posteriores`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1))
        h.pending.upsert(h.row(2))
        h.sessionOwner = h.ownerA
        val started = CompletableDeferred<Unit>()
        val gate = CompletableDeferred<Unit>()
        h.remote.sectionStarted = started
        h.remote.sectionGate = gate

        val job = async { h.coordinator().syncOnce(h.ownerA) }
        started.await() // PATCH de la parte 1 en vuelo (autorizado con sesión A)
        h.sessionOwner = null // logout intercalado
        gate.complete(Unit) // el remoto responde éxito al envío ya autorizado

        val outcome = job.await()

        assertEquals(SyncOutcome.NoSession, outcome)
        assertEquals("ningún envío posterior al logout", 1, h.remote.sectionCalls.size)
        // El envío autorizado ANTES del logout se confirma; la intención no
        // enviada queda intacta para el próximo login de A.
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, h.rowsOf()[0].syncState)
        assertEquals(PendingProgressEntity.SYNC_PENDING, h.rowsOf()[1].syncState)
    }

    @Test
    fun `logout intercalado entre proyectos corta antes de leer la cola del siguiente`() = runBlocking {
        val h = Harness()
        val other = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        h.summary()
        h.summary(other)
        h.pending.upsert(h.row(1))
        h.pending.upsert(h.row(1, project = other))
        h.sessionOwner = h.ownerA
        val started = CompletableDeferred<Unit>()
        val gate = CompletableDeferred<Unit>()
        h.remote.sectionStarted = started
        h.remote.sectionGate = gate

        val job = async { h.coordinator().syncOnce(h.ownerA) }
        started.await()
        h.sessionOwner = null
        gate.complete(Unit)

        val outcome = job.await()

        assertEquals(SyncOutcome.NoSession, outcome)
        assertEquals(1, h.remote.sectionCalls.size)
        assertEquals(PendingProgressEntity.SYNC_PENDING, h.rowsOf(other).single().syncState)
    }

    @Test
    fun `sesion del mismo owner transmite normal (el gate no bloquea lo legitimo)`() = runBlocking {
        val h = Harness()
        h.summary()
        h.pending.upsert(h.row(1))
        h.sessionOwner = h.ownerA

        val outcome = h.coordinator().syncOnce(h.ownerA)

        assertEquals(SyncOutcome.Synced, outcome)
        assertEquals(1, h.remote.sectionCalls.size)
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, h.rowsOf().single().syncState)
    }
}

package com.explainer.app.feature.progress

import com.explainer.app.core.model.LastSubsection
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.core.model.ReadingProgress
import com.explainer.app.data.local.db.OfflineSnapshotEntity
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.InMemoryPendingProgressDao
import com.explainer.app.data.local.snapshot.InMemorySnapshotDao
import com.explainer.app.data.local.snapshot.SnapshotStoreException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * Aceptación del repositorio de progreso optimista:
 * - Escrituras locales inmediatas y coalescidas (una fila por key, sin filas
 *   por scroll), con validación `subsec-{partId}-...` antes de encolar.
 * - last-read solo avanza con updated_at no decreciente.
 * - `observe` mezcla remoto (summary) ∪ local (snapshot) ∪ overlay con la
 *   policy T02 (unión, tombstones, last-read más reciente).
 * - `requestSync` debounce 15 s y respeto del intervalo mínimo de 60 s.
 */
class RoomReadingProgressRepositoryTest {

    private val owner = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val projectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")
    private val pid = projectId.value

    private class Harness {
        val pending = InMemoryPendingProgressDao()
        val summaries = InMemoryProjectSummaryDao()
        val snapshots = InMemorySnapshotDao()
        val scheduler = RecordingScheduler()
        var now = 1_000_000L
        val throttle = ProgressThrottle { now }

        val repo = RoomReadingProgressRepository(
            pendingDao = pending,
            summaryDao = summaries,
            snapshotDao = snapshots,
            scheduler = scheduler,
            throttle = throttle,
            nowMillis = { now },
        )
    }

    private fun iso(millis: Long): String = Instant.ofEpochMilli(millis).toString()

    @Test
    fun `setSectionCompleted persiste fila coalescida PENDING y agenda sync con debounce`() = runBlocking {
        val h = Harness()
        h.repo.setSectionCompleted(owner, projectId, partId = 2, completed = true)
        h.repo.setSectionCompleted(owner, projectId, partId = 2, completed = false)
        h.repo.setSectionCompleted(owner, projectId, partId = 2, completed = false)

        val rows = h.pending.rows[owner to pid]!!
        assertEquals(1, rows.size)
        val row = rows.single()
        assertEquals(PendingProgressEntity.KIND_SECTION, row.kindTarget)
        assertEquals(2, row.partId)
        assertEquals(false, row.desiredCompleted)
        assertEquals(PendingProgressEntity.SYNC_PENDING, row.syncState)
        assertEquals(3, h.scheduler.calls.size)
        h.scheduler.calls.forEach { assertEquals(15_000L, it.second) }
    }

    @Test
    fun `recordSubsection valida el id antes de encolar`() = runBlocking {
        val h = Harness()
        h.repo.recordSubsection(
            owner, projectId,
            SubsectionProgressEvent(partId = 1, subsectionId = "sec-1-x", completed = true),
        )
        h.repo.recordSubsection(
            owner, projectId,
            SubsectionProgressEvent(partId = 2, subsectionId = "subsec-1-a-0", completed = true),
        )
        h.repo.recordSubsection(
            owner, projectId,
            SubsectionProgressEvent(partId = 0, subsectionId = "subsec-0-a-0", completed = true),
        )

        assertTrue(h.pending.rows[owner to pid].isNullOrEmpty())
        assertTrue(h.scheduler.calls.isEmpty())
    }

    @Test
    fun `recordSubsection persiste completed y last-read en filas separadas y agenda sync`() = runBlocking {
        val h = Harness()
        h.now = 1_000_000L
        h.repo.recordSubsection(
            owner, projectId,
            SubsectionProgressEvent(
                partId = 1,
                tab = ReaderTab.EXPLANATION,
                subsectionId = "subsec-1-a-0",
                completed = true,
                isLastRead = true,
            ),
        )

        val rows = h.pending.rows[owner to pid]!!.associateBy { it.kindTarget }
        val completed = rows[PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0"]!!
        assertEquals(true, completed.desiredCompleted)
        assertEquals("explicacion", completed.tab)
        val lastRead = rows[PendingProgressEntity.KIND_LAST_READ]!!
        assertEquals("subsec-1-a-0", lastRead.lastSubsectionId)
        assertEquals(iso(1_000_000L), lastRead.lastReadAt)
        assertEquals(1_000_000L, lastRead.updatedAt)
        assertEquals(listOf(owner to 15_000L), h.scheduler.calls)
    }

    @Test
    fun `last-read coalescido solo avanza con updated_at no decreciente`() = runBlocking {
        val h = Harness()
        h.now = 1_000L
        h.repo.recordSubsection(owner, projectId, SubsectionProgressEvent(1, "subsec-1-a-0", isLastRead = true))
        h.now = 2_000L
        h.repo.recordSubsection(owner, projectId, SubsectionProgressEvent(1, "subsec-1-b-1", isLastRead = true))
        h.now = 1_500L
        h.repo.recordSubsection(owner, projectId, SubsectionProgressEvent(1, "subsec-1-c-2", isLastRead = true))

        val rows = h.pending.rows[owner to pid]!!.filter { it.kindTarget == PendingProgressEntity.KIND_LAST_READ }
        assertEquals(1, rows.size)
        assertEquals("subsec-1-b-1", rows.single().lastSubsectionId)
        assertEquals(2_000L, rows.single().updatedAt)
    }

    @Test
    fun `observe mezcla union tombstones y last-read mas reciente con prioridad pending`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(
            ProjectSummaryEntity(
                ownerId = owner, projectId = pid, name = "P",
                readingProgressJson = "{\"completed_parts\":[1],\"completed_subsections\":[\"subsec-1-a-0\"]," +
                    "\"last_subsection\":{\"part_id\":1,\"subsection_id\":\"subsec-1-a-0\",\"tab\":\"explicacion\"}," +
                    "\"last_read_at\":\"2026-08-01T10:00:01.000Z\"}",
            ),
        )
        h.snapshots.snapshots[owner to pid] = OfflineSnapshotEntity(
            ownerId = owner, projectId = pid, activeGeneration = "gen-1",
            readingProgressJson = "{\"completed_subsections\":[\"subsec-1-b-1\"]," +
                "\"last_subsection\":{\"part_id\":1,\"subsection_id\":\"subsec-1-b-1\",\"tab\":\"explicacion\"}," +
                "\"last_read_at\":\"2026-08-01T10:00:02.000Z\"}",
        )
        h.pending.upsert(
            PendingProgressEntity(
                ownerId = owner, projectId = pid, partId = 1, tab = "explicacion",
                kindTarget = PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-c-2",
                desiredCompleted = true, syncState = PendingProgressEntity.SYNC_PENDING, updatedAt = 1L,
            ),
        )
        h.pending.upsert(
            PendingProgressEntity(
                ownerId = owner, projectId = pid, partId = 1, tab = "explicacion",
                kindTarget = PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-b-1",
                desiredCompleted = false, syncState = PendingProgressEntity.SYNC_PENDING, updatedAt = 1L,
            ),
        )
        h.pending.upsert(
            PendingProgressEntity(
                ownerId = owner, projectId = pid, partId = 1, tab = "explicacion",
                kindTarget = PendingProgressEntity.KIND_LAST_READ,
                lastSubsectionId = "subsec-1-d-3", lastReadAt = "2026-08-01T10:00:03.000Z",
                updatedAt = 3L, syncState = PendingProgressEntity.SYNC_PENDING,
            ),
        )

        val progress = h.repo.observe(owner, projectId).first()

        assertEquals(setOf(1), progress.completedParts)
        // unión de completadas menos el tombstone explícito de b-1
        assertEquals(setOf("subsec-1-a-0", "subsec-1-c-2"), progress.completedSubsections)
        assertEquals(
            LastSubsection(1, "subsec-1-d-3", ReaderTab.EXPLANATION),
            progress.lastSubsection,
        )
        assertEquals("2026-08-01T10:00:03.000Z", progress.lastReadAt)
    }

    @Test
    fun `observe sin fuentes devuelve progreso vacio`() = runBlocking {
        val h = Harness()
        assertEquals(ReadingProgress(), h.repo.observe(owner, projectId).first())
    }

    @Test
    fun `requestSync respeta el intervalo minimo de 60 s tras un flush`() = runBlocking {
        val h = Harness()
        h.throttle.recordFlush(owner, h.now - 30_000L)
        h.repo.requestSync(owner)
        assertEquals(listOf(owner to 30_000L), h.scheduler.calls)

        h.scheduler.calls.clear()
        h.throttle.recordFlush(owner, h.now - 90_000L)
        h.repo.requestSync(owner)
        assertEquals(listOf(owner to 15_000L), h.scheduler.calls)
    }

    @Test
    fun `el debounce de un owner no contamina el reloj de otro`() = runBlocking {
        val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"
        val h = Harness()
        h.throttle.recordFlush(owner, h.now) // A acaba de transmitir

        h.repo.requestSync(ownerB)

        // B no espera el resto del intervalo de A: usa su propio reloj (debounce).
        assertEquals(listOf(ownerB to 15_000L), h.scheduler.calls)
    }

    @Test
    fun `last-read del overlay se elige por last_read_at parseado con desempate determinista`() = runBlocking {
        val h = Harness()
        // Fila A: updated_at más reciente pero last_read_at más antiguo.
        // Fila B: updated_at más antiguo pero last_read_at más reciente.
        // (misma part/tab; se siembran directo porque la PK Room solo admite una).
        h.pending.rows.getOrPut(owner to pid) { mutableListOf() }.apply {
            add(
                PendingProgressEntity(
                    ownerId = owner, projectId = pid, partId = 1, tab = "explicacion",
                    kindTarget = PendingProgressEntity.KIND_LAST_READ,
                    lastSubsectionId = "subsec-1-a-0", lastReadAt = "2026-08-01T10:00:01.000Z",
                    updatedAt = 9_000L, syncState = PendingProgressEntity.SYNC_PENDING,
                ),
            )
            add(
                PendingProgressEntity(
                    ownerId = owner, projectId = pid, partId = 1, tab = "explicacion",
                    kindTarget = PendingProgressEntity.KIND_LAST_READ,
                    lastSubsectionId = "subsec-1-b-1", lastReadAt = "2026-08-01T10:00:02.000Z",
                    updatedAt = 1_000L, syncState = PendingProgressEntity.SYNC_PENDING,
                ),
            )
        }

        val progress = h.repo.observe(owner, projectId).first()

        assertEquals("subsec-1-b-1", progress.lastSubsection?.subsectionId)
        assertEquals("2026-08-01T10:00:02.000Z", progress.lastReadAt)
    }

    @Test
    fun `last-read con timestamp invalido o ausente degrada sin ganar`() = runBlocking {
        val h = Harness()
        h.pending.rows.getOrPut(owner to pid) { mutableListOf() }.apply {
            add(
                PendingProgressEntity(
                    ownerId = owner, projectId = pid, partId = 1, tab = "explicacion",
                    kindTarget = PendingProgressEntity.KIND_LAST_READ,
                    lastSubsectionId = "subsec-1-a-0", lastReadAt = "not-a-date",
                    updatedAt = 9_000L, syncState = PendingProgressEntity.SYNC_PENDING,
                ),
            )
            add(
                PendingProgressEntity(
                    ownerId = owner, projectId = pid, partId = 2, tab = "recorrido",
                    kindTarget = PendingProgressEntity.KIND_LAST_READ,
                    lastSubsectionId = "subsec-2-c-2", lastReadAt = "2026-08-01T10:00:00.000Z",
                    updatedAt = 1L, syncState = PendingProgressEntity.SYNC_PENDING,
                ),
            )
        }

        val progress = h.repo.observe(owner, projectId).first()

        // La fila válida gana aunque su updated_at sea anterior.
        assertEquals("subsec-2-c-2", progress.lastSubsection?.subsectionId)
    }

    @Test
    fun `empate de last_read_at se resuelve por updated_at descendente y part_id`() = runBlocking {
        val h = Harness()
        h.pending.rows.getOrPut(owner to pid) { mutableListOf() }.apply {
            add(
                PendingProgressEntity(
                    ownerId = owner, projectId = pid, partId = 2, tab = "recorrido",
                    kindTarget = PendingProgressEntity.KIND_LAST_READ,
                    lastSubsectionId = "subsec-2-b-1", lastReadAt = "2026-08-01T10:00:00.000Z",
                    updatedAt = 1_000L, syncState = PendingProgressEntity.SYNC_PENDING,
                ),
            )
            add(
                PendingProgressEntity(
                    ownerId = owner, projectId = pid, partId = 1, tab = "explicacion",
                    kindTarget = PendingProgressEntity.KIND_LAST_READ,
                    lastSubsectionId = "subsec-1-a-0", lastReadAt = "2026-08-01T10:00:00.000Z",
                    updatedAt = 2_000L, syncState = PendingProgressEntity.SYNC_PENDING,
                ),
            )
        }

        val progress = h.repo.observe(owner, projectId).first()

        // Mismo instante: gana updated_at más reciente (subsec-1-a-0).
        assertEquals("subsec-1-a-0", progress.lastSubsection?.subsectionId)
    }

    @Test
    fun `owner invalido se rechaza antes de escribir`() {
        val h = Harness()
        assertThrows(SnapshotStoreException::class.java) {
            runBlocking { h.repo.setSectionCompleted("bad owner!", projectId, 1, true) }
        }
        assertThrows(SnapshotStoreException::class.java) {
            runBlocking { h.repo.requestSync("") }
        }
        assertTrue(h.pending.rows.isEmpty())
        assertTrue(h.scheduler.calls.isEmpty())
    }

    @Test
    fun `evento sin completar ni last-read no agenda sync`() = runBlocking {
        val h = Harness()
        h.repo.recordSubsection(
            owner, projectId,
            SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-a-0"),
        )
        assertTrue(h.pending.rows[owner to pid].isNullOrEmpty())
        assertTrue(h.scheduler.calls.isEmpty())
    }
}

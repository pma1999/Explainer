package com.explainer.app.feature.catalog

import com.explainer.app.core.model.PartContentDocument
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.db.OfflinePartEntity
import com.explainer.app.data.local.db.OfflineSnapshotEntity
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.InMemoryDownloadStateDao
import com.explainer.app.data.local.snapshot.InMemoryPendingProgressDao
import com.explainer.app.data.local.snapshot.InMemorySnapshotDao
import com.explainer.app.data.local.snapshot.RoomSnapshotStore
import com.explainer.app.data.remote.dto.PartDto
import com.explainer.app.data.remote.dto.ProjectSummaryDto
import com.explainer.app.data.remote.dto.ReadingProgressDto
import com.explainer.app.data.remote.dto.SegmentationDto
import com.explainer.app.data.remote.contract.RemoteResult
import com.explainer.app.feature.progress.FakeProgressRemote
import com.explainer.app.feature.progress.InMemoryProjectSummaryDao
import com.explainer.app.feature.progress.ProgressSyncCoordinator
import com.explainer.app.feature.progress.ProgressThrottle
import com.explainer.app.feature.progress.SyncOutcome
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlinx.serialization.json.buildJsonObject

/**
 * Aceptación del catálogo: refresh que nunca borra, merge por updated_at sin
 * reemplazo silencioso, lista combinada summary/snapshot/download con los
 * cinco estados de disponibilidad, lector offline y confirmación de filas
 * ACKNOWLEDGED cuando el remoto refleja el valor.
 */
class RoomProjectCatalogRepositoryTest {

    private val ownerA = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"
    private val p1 = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")
    private val p2 = ProjectId("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")

    private class Harness {
        val remote = FakeProgressRemote()
        val summaries = InMemoryProjectSummaryDao()
        val snapshots = InMemorySnapshotDao()
        val downloads = InMemoryDownloadStateDao()
        val pending = InMemoryPendingProgressDao()
        val store = RoomSnapshotStore(snapshots)
        var now = 1_000_000L

        val repo = RoomProjectCatalogRepository(
            remote = remote,
            projectSummaryDao = summaries,
            snapshotDao = snapshots,
            downloadStateDao = downloads,
            pendingProgressDao = pending,
            snapshotStore = store,
            clock = { now },
        )
    }

    private fun summary(
        owner: String,
        projectId: ProjectId,
        updatedAt: String = "2026-08-01T10:00:00.000Z",
        contentUpdatedAt: String = "",
        progressJson: String = "{}",
        name: String = "P",
    ) = ProjectSummaryEntity(
        ownerId = owner,
        projectId = projectId.value,
        name = name,
        status = "completed",
        remoteUpdatedAt = updatedAt,
        remoteContentUpdatedAt = contentUpdatedAt,
        readingProgressJson = progressJson,
        partIndexJson = "[{\"numero\":1,\"titulo\":\"P1\"},{\"numero\":2,\"titulo\":\"P2\"}]",
        segmentationSourceBytes = 100L,
        fetchedAt = 1L,
    )

    private fun snapshot(owner: String, projectId: ProjectId, sourceUpdatedAt: String = "2026-08-01T10:00:00.000Z") =
        OfflineSnapshotEntity(
            ownerId = owner,
            projectId = projectId.value,
            activeGeneration = "gen-1",
            name = "P",
            status = "completed",
            segmentationJson = "[{\"numero\":1,\"titulo\":\"P1\",\"contenido\":\"c\"}]",
            sourceUpdatedAt = sourceUpdatedAt,
            downloadedAt = 1L,
            totalBytes = 500L,
        )

    private fun partRow(owner: String, projectId: ProjectId, generation: String, partId: Int) =
        OfflinePartEntity(
            ownerId = owner,
            projectId = projectId.value,
            generation = generation,
            partId = partId,
            order = partId,
            title = "P$partId",
            status = "completed",
            contentJson = buildJsonObject { }.toString(),
            contentBytes = 10L,
        )

    private fun pendingRow(
        owner: String,
        projectId: ProjectId,
        partId: Int,
        kindTarget: String,
        desired: Boolean?,
        syncState: String = PendingProgressEntity.SYNC_PENDING,
        tab: String = "explicacion",
    ) = PendingProgressEntity(
        ownerId = owner,
        projectId = projectId.value,
        partId = partId,
        tab = tab,
        kindTarget = kindTarget,
        desiredCompleted = desired,
        syncState = syncState,
        updatedAt = 1L,
    )

    private fun dto(id: ProjectId, name: String, updatedAt: String, completedPart: Int? = null) = ProjectSummaryDto(
        id = id.value,
        name = name,
        status = "completed",
        segmentation = SegmentationDto(partes = listOf(PartDto(numero = 1, titulo = "P1"))),
        readingProgress = if (completedPart != null) {
            ReadingProgressDto(completedParts = listOf(completedPart))
        } else {
            ReadingProgressDto()
        },
        updatedAt = updatedAt,
    )

    // ---------------------------------------------------------------- refresh

    @Test
    fun `refresh exitoso persiste resumenes por owner`() = runBlocking {
        val h = Harness()
        h.remote.listResult = RemoteResult.Success(
            listOf(dto(p1, "A", "2026-08-01T10:00:00.000Z"), dto(p2, "B", "2026-08-01T10:00:01.000Z")),
        )

        val outcome = h.repo.refresh(ownerA)

        assertEquals(RefreshOutcome.Success(2), outcome)
        assertEquals(2, h.summaries.rows.size)
        assertEquals("A", h.summaries.rows[ownerA to p1.value]!!.name)
        assertEquals("B", h.summaries.rows[ownerA to p2.value]!!.name)
        assertEquals(1_000_000L, h.summaries.rows[ownerA to p1.value]!!.fetchedAt)
        assertTrue(h.summaries.rows.keys.none { it.first == ownerB })
    }

    @Test
    fun `refresh fallido no escribe ni borra nada`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, name = "Antes"))

        h.remote.listResult = RemoteResult.AuthRequired
        assertEquals(RefreshOutcome.AuthRequired, h.repo.refresh(ownerA))
        assertEquals("Antes", h.summaries.rows[ownerA to p1.value]!!.name)

        h.remote.listResult = RemoteResult.Retryable
        assertEquals(RefreshOutcome.Retryable, h.repo.refresh(ownerA))
        assertEquals("Antes", h.summaries.rows[ownerA to p1.value]!!.name)

        h.remote.listResult = RemoteResult.NotFound
        assertEquals(RefreshOutcome.NotFound, h.repo.refresh(ownerA))

        h.remote.listResult = RemoteResult.RateLimited
        assertEquals(RefreshOutcome.RateLimited, h.repo.refresh(ownerA))

        h.remote.listResult = RemoteResult.PermanentFailure("http:500")
        assertEquals(RefreshOutcome.PermanentFailure("http:500"), h.repo.refresh(ownerA))

        h.remote.listResult = RemoteResult.InvalidPayload("json")
        assertEquals(RefreshOutcome.InvalidPayload, h.repo.refresh(ownerA))

        assertEquals("Antes", h.summaries.rows[ownerA to p1.value]!!.name)
    }

    @Test
    fun `refresh exitoso confirma ACKNOWLEDGED y conserva PENDING y no confirmados`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, progressJson = "{\"completed_parts\":[1]}"))
        h.pending.upsert(pendingRow(ownerA, p1, 1, PendingProgressEntity.KIND_SECTION, desired = true, syncState = PendingProgressEntity.SYNC_ACKNOWLEDGED, tab = "section"))
        h.pending.upsert(pendingRow(ownerA, p1, 2, PendingProgressEntity.KIND_SECTION, desired = true, syncState = PendingProgressEntity.SYNC_ACKNOWLEDGED, tab = "section"))
        h.pending.upsert(pendingRow(ownerA, p1, 1, PendingProgressEntity.KIND_SECTION, desired = true, tab = "section"))
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "A", "2026-08-01T10:00:00.000Z", completedPart = 1)))

        h.repo.refresh(ownerA)

        val remaining = h.pending.rows[ownerA to p1.value]!!.map { it.partId to it.syncState }
        // ACKNOWLEDGED parte 1 confirmada (remoto la incluye) -> eliminada;
        // ACKNOWLEDGED parte 2 no confirmada -> conservada; PENDING nunca se toca.
        assertEquals(
            listOf(2 to PendingProgressEntity.SYNC_ACKNOWLEDGED, 1 to PendingProgressEntity.SYNC_PENDING),
            remaining,
        )
    }

    @Test
    fun `refresh salta items con id invalido y persiste los validos`() = runBlocking {
        val h = Harness()
        h.remote.listResult = RemoteResult.Success(
            listOf(
                dto(p1, "Bien", "2026-08-01T10:00:00.000Z"),
                dto(p1, "Mal", "2026-08-01T10:00:00.000Z").copy(id = "not-a-uuid"),
            ),
        )

        val outcome = h.repo.refresh(ownerA)

        assertEquals(RefreshOutcome.Success(2), outcome)
        assertEquals(1, h.summaries.rows.size)
        assertEquals("Bien", h.summaries.rows[ownerA to p1.value]!!.name)
    }

    // ------------------------- tombstone confirmado vs snapshot (R-T07-02)

    @Test
    fun `confirmar un false conserva el tombstone hasta que el snapshot lo refleje`() = runBlocking {
        val h = Harness()
        // Snapshot local STALE que aún contiene la subsección completada.
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1).copy(
            readingProgressJson = "{\"completed_subsections\":[\"subsec-1-a-0\"]}",
        )
        // El usuario pidió false; el PATCH ya fue ACK y el remoto omite la
        // subsección (lista recién persistida).
        h.pending.upsert(
            pendingRow(
                ownerA, p1, 1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0",
                desired = false, syncState = PendingProgressEntity.SYNC_ACKNOWLEDGED,
            ),
        )
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "A", "2026-08-01T10:00:00.000Z")))

        h.repo.refresh(ownerA)

        // El tombstone NO se elimina: la generación local observada aún
        // contiene el valor; sin él, la unión reintroduciría la subsección.
        val remaining = h.pending.rows[ownerA to p1.value]!!.single()
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, remaining.syncState)
        assertEquals(false, remaining.desiredCompleted)
        // Y la vista mezclada NO reintroduce la subsección (el overlay la resta).
        val item = h.repo.observeProjects(ownerA).first().single()
        assertTrue("subsec-1-a-0" !in item.readingProgress.completedSubsections)

        // La generación observada ahora refleja la ausencia (nueva descarga
        // con el progreso remoto ya corregido): el ACK puede eliminarse.
        h.snapshots.snapshots[ownerA to p1.value] =
            h.snapshots.snapshots[ownerA to p1.value]!!.copy(readingProgressJson = "{}")
        h.repo.refresh(ownerA)
        assertTrue(h.pending.rows[ownerA to p1.value].isNullOrEmpty())
    }

    @Test
    fun `confirmar un true se elimina aunque el snapshot no lo contenga`() = runBlocking {
        val h = Harness()
        // Snapshot sin la parte (el usuario completó desde la web o el
        // snapshot es anterior): eliminar el ACK no reintroduce nada.
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1)
        h.pending.upsert(
            pendingRow(ownerA, p1, 1, PendingProgressEntity.KIND_SECTION, desired = true,
                syncState = PendingProgressEntity.SYNC_ACKNOWLEDGED, tab = "section"),
        )
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "A", "2026-08-01T10:00:00.000Z", completedPart = 1)))

        h.repo.refresh(ownerA)

        assertTrue(h.pending.rows[ownerA to p1.value].isNullOrEmpty())
        // La vista sigue mostrando la parte completada (remoto ∪ snapshot).
        val item = h.repo.observeProjects(ownerA).first().single()
        assertEquals(setOf(1), item.readingProgress.completedParts)
    }

    @Test
    fun `secuencia completa PATCH a ACK y refresh confirma el tombstone sin reintroducirlo`() = runBlocking {
        val h = Harness()
        // Snapshot local STALE que aún contiene la subsección completada.
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1).copy(
            readingProgressJson = "{\"completed_subsections\":[\"subsec-1-a-0\"]}",
        )
        // El usuario desmarca la subsección (tombstone local PENDING).
        h.pending.upsert(
            pendingRow(ownerA, p1, 1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0", desired = false),
        )
        // El motor de sync comparte los MISMOS DAOs y el MISMO reloj del repo.
        val throttle = ProgressThrottle { h.now }
        val coordinator = ProgressSyncCoordinator(
            remote = h.remote,
            pendingDao = h.pending,
            summaryDao = h.summaries,
            snapshotDao = h.snapshots,
            throttle = throttle,
        )

        // 1) PATCH exitoso -> ACK: el batch transmite la anulación y la fila
        //    queda ACKNOWLEDGED por el CAS del coordinador (no pre-sembrada).
        assertEquals(SyncOutcome.Synced, coordinator.syncOnce(ownerA))
        val patch = h.remote.subsectionCalls.single().second
        assertEquals(listOf("subsec-1-a-0"), patch.uncompletedSubsectionIds)
        val acked = h.pending.rows[ownerA to p1.value]!!.single()
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, acked.syncState)
        assertEquals(false, acked.desiredCompleted)

        // 2) Refresh de catálogo: la lista remota ya NO contiene la
        //    subsección, pero el snapshot stale sí -> el tombstone se
        //    CONSERVA (tombstoneReconciledWithSnapshot) y la unión NO
        //    reintroduce el progreso.
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "A", "2026-08-01T10:00:00.000Z")))
        h.repo.refresh(ownerA)
        val retained = h.pending.rows[ownerA to p1.value]!!.single()
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, retained.syncState)
        val item = h.repo.observeProjects(ownerA).first().single()
        assertTrue("subsec-1-a-0" !in item.readingProgress.completedSubsections)

        // 3) Los commits futuros NO reenvían la anulación confirmada
        //    (ACKNOWLEDGED no se transmite; solo PENDING).
        h.now += 61_000L
        assertEquals(SyncOutcome.NothingPending, coordinator.syncOnce(ownerA))
        assertEquals(1, h.remote.subsectionCalls.size)

        // 4) La generación observada se reconcilia (nueva descarga sin el
        //    valor): el siguiente refresh elimina el ACK y el valor NO
        //    reaparece en la unión.
        h.snapshots.snapshots[ownerA to p1.value] =
            h.snapshots.snapshots[ownerA to p1.value]!!.copy(readingProgressJson = "{}")
        h.repo.refresh(ownerA)
        assertTrue(h.pending.rows[ownerA to p1.value].isNullOrEmpty())
        val after = h.repo.observeProjects(ownerA).first().single()
        assertTrue("subsec-1-a-0" !in after.readingProgress.completedSubsections)
    }

    // ---------------------------------------------- refresh condicional (R-T07-08)

    @Test
    fun `respuesta stale no reemplaza un resumen mas nuevo`() = runBlocking {
        val h = Harness()
        // T2 llega primero (respuesta reciente).
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "Nuevo", "2026-08-01T10:00:02.000Z")))
        h.repo.refresh(ownerA)
        // T1 (respuesta tardía, más antigua) llega después: no debe retroceder.
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "Viejo", "2026-08-01T10:00:01.000Z")))
        h.repo.refresh(ownerA)

        val row = h.summaries.rows[ownerA to p1.value]!!
        assertEquals("Nuevo", row.name)
        assertEquals("2026-08-01T10:00:02.000Z", row.remoteUpdatedAt)
    }

    @Test
    fun `timestamp invalido entrante no pisa un resumen valido`() = runBlocking {
        val h = Harness()
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "Sano", "2026-08-01T10:00:00.000Z")))
        h.repo.refresh(ownerA)

        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "Roto", "not-a-date")))
        h.repo.refresh(ownerA)

        val row = h.summaries.rows[ownerA to p1.value]!!
        assertEquals("Sano", row.name)
        assertEquals("2026-08-01T10:00:00.000Z", row.remoteUpdatedAt)
    }

    @Test
    fun `timestamp invalido existente se repara con una respuesta valida`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, updatedAt = "not-a-date", name = "Roto"))

        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "Sano", "2026-08-01T10:00:00.000Z")))
        h.repo.refresh(ownerA)

        val row = h.summaries.rows[ownerA to p1.value]!!
        assertEquals("Sano", row.name)
        assertEquals("2026-08-01T10:00:00.000Z", row.remoteUpdatedAt)
    }

    @Test
    fun `dos refreshes concurrentes fuera de orden convergen al resumen mas nuevo`() = runBlocking {
        val h = Harness()
        // Respuestas fuera de orden: el primer refresh (arrancó antes) recibe
        // la respuesta STALE (T1); el segundo recibe la NUEVA (T2). Las
        // barreras del fake retienen la PRIMERA lectura y la escritura de T1:
        // fuerzan la ventana TOCTOU read-read/write-write del upsert
        // condicional (R-T07-08).
        h.remote.listQueue.add(RemoteResult.Success(listOf(dto(p1, "Viejo", "2026-08-01T10:00:01.000Z"))))
        h.remote.listQueue.add(RemoteResult.Success(listOf(dto(p1, "Nuevo", "2026-08-01T10:00:02.000Z"))))
        val firstRead = CompletableDeferred<Unit>()
        val firstReadGate = CompletableDeferred<Unit>()
        val staleWrite = CompletableDeferred<Unit>()
        val staleWriteGate = CompletableDeferred<Unit>()
        h.summaries.firstSummaryRowStarted = firstRead
        h.summaries.firstSummaryRowGate = firstReadGate
        h.summaries.staleUpsertTimestamp = "2026-08-01T10:00:01.000Z"
        h.summaries.staleUpsertStarted = staleWrite
        h.summaries.staleUpsertGate = staleWriteGate

        val a = async { h.repo.refresh(ownerA) }
        val b = async { h.repo.refresh(ownerA) }

        // El primer refresh leyó la fila (ventana TOCTOU abierta): libéralo.
        withTimeout(10_000) { firstRead.await() }
        firstReadGate.complete(Unit)
        // El refresh NUEVO ya escribió; el STALE intenta escribir después
        // (respuesta tardía) y queda retenido hasta liberar su escritura.
        withTimeout(10_000) { staleWrite.await() }
        staleWriteGate.complete(Unit)

        assertEquals(RefreshOutcome.Success(1), a.await())
        assertEquals(RefreshOutcome.Success(1), b.await())
        // El resumen NUEVO gana siempre: la respuesta stale nunca retrocede
        // el merge ni hace desaparecer el badge UPDATE_POSSIBLE.
        val row = h.summaries.rows[ownerA to p1.value]!!
        assertEquals("Nuevo", row.name)
        assertEquals("2026-08-01T10:00:02.000Z", row.remoteUpdatedAt)
    }

    // ------------------------------------------- 404 remoto no disponible (R-T07-07)

    @Test
    fun `refresh 404 marca remoto no disponible sin borrar snapshot ni cola`() = runBlocking {
        val h = Harness()
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1)
        h.pending.upsert(pendingRow(ownerA, p1, 1, PendingProgressEntity.KIND_SECTION, desired = true, tab = "section"))
        h.remote.listResult = RemoteResult.NotFound

        val outcome = h.repo.refresh(ownerA)

        assertEquals(RefreshOutcome.NotFound, outcome)
        val item = h.repo.observeProjects(ownerA).first().single()
        assertEquals(true, item.remoteUnavailable)
        // El snapshot sigue utilizable y el contenido no se degrada.
        assertEquals(ProjectAvailability.OFFLINE, item.availability)
        assertEquals("gen-1", h.snapshots.snapshots[ownerA to p1.value]!!.activeGeneration)
        assertEquals(1, h.pending.rows[ownerA to p1.value]!!.size)
        // La marca es owner/project-scoped: no contamina a otros owners.
        assertTrue(h.repo.observeProjects(ownerB).first().isEmpty())

        // Un refresh exitoso posterior limpia la marca.
        h.remote.listResult = RemoteResult.Success(listOf(dto(p1, "A", "2026-08-01T10:00:00.000Z")))
        h.repo.refresh(ownerA)
        assertEquals(false, h.repo.observeProjects(ownerA).first().single().remoteUnavailable)
    }

    @Test
    fun `refresh 404 sin snapshot marca remoto no disponible conservando el resumen`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, name = "SoloRemoto"))
        h.remote.listResult = RemoteResult.NotFound

        h.repo.refresh(ownerA)

        val item = h.repo.observeProjects(ownerA).first().single()
        assertEquals(true, item.remoteUnavailable)
        assertEquals("SoloRemoto", item.name)
        assertEquals(ProjectAvailability.REMOTE_ONLY, item.availability)
    }

    // ------------------------------------------------- lista

    @Test
    fun `observeProjects combina y ordena por updated_at descendente`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, updatedAt = "2026-08-01T10:00:01.000Z", name = "Nuevo"))
        h.summaries.upsert(summary(ownerA, p2, updatedAt = "2026-08-01T10:00:00.000Z", name = "Viejo"))
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1, sourceUpdatedAt = "2026-08-01T09:00:00.000Z")

        val items = h.repo.observeProjects(ownerA).first()

        assertEquals(listOf("Nuevo", "Viejo"), items.map { it.name })
        val nuevo = items.first()
        assertEquals(p1, nuevo.projectId)
        assertEquals(2, nuevo.partCount)
        assertEquals(100L, nuevo.segmentationSourceBytes)
        assertEquals(500L, nuevo.snapshotBytes)
        assertEquals(ProjectAvailability.UPDATE_POSSIBLE, nuevo.availability)
        // El snapshot activo nunca se reemplaza: misma generación tras observar.
        assertEquals("gen-1", h.snapshots.snapshots[ownerA to p1.value]!!.activeGeneration)
    }

    @Test
    fun `estados de disponibilidad remote-only offline updating`() = runBlocking {
        val p3 = ProjectId("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff")
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, updatedAt = "2026-08-01T10:00:00.000Z", name = "SoloRemoto"))
        h.summaries.upsert(summary(ownerA, p2, updatedAt = "2026-08-01T10:00:00.000Z", name = "Offline"))
        h.snapshots.snapshots[ownerA to p2.value] = snapshot(ownerA, p2, sourceUpdatedAt = "2026-08-01T10:00:00.000Z")
        h.downloads.upsert(
            DownloadStateEntity(
                ownerId = ownerA, projectId = p2.value, workId = "w",
                state = DownloadStateEntity.STATE_DOWNLOADING,
            ),
        )
        // snapshot sin summary (la lista combina también por snapshot).
        h.snapshots.snapshots[ownerA to p3.value] = snapshot(ownerA, p3, sourceUpdatedAt = "2026-08-01T09:00:00.000Z")

        val byName = h.repo.observeProjects(ownerA).first().associateBy { it.name }

        assertEquals(ProjectAvailability.REMOTE_ONLY, byName["SoloRemoto"]!!.availability)
        assertEquals(ProjectAvailability.UPDATING, byName["Offline"]!!.availability)
        assertEquals(ProjectAvailability.OFFLINE, byName["P"]!!.availability)
    }

    @Test
    fun `progreso remoto mas nuevo con content_updated_at igual al snapshot NO produce UPDATE_POSSIBLE`() = runBlocking {
        val h = Harness()
        // Progreso de lectura avanzó `updated_at` (T+1) sin cambiar contenido:
        // `content_updated_at` (T) coincide con la versión del snapshot (T).
        h.summaries.upsert(
            summary(ownerA, p1, updatedAt = "2026-08-01T10:00:01.000Z", contentUpdatedAt = "2026-08-01T10:00:00.000Z", name = "Leido"),
        )
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1, sourceUpdatedAt = "2026-08-01T10:00:00.000Z")

        val item = h.repo.observeProjects(ownerA).first().single()

        assertEquals(ProjectAvailability.OFFLINE, item.availability)
    }

    @Test
    fun `content_updated_at remoto mas nuevo SI produce UPDATE_POSSIBLE`() = runBlocking {
        val h = Harness()
        // El contenido cambió: `content_updated_at` (T+1) supera la versión
        // del snapshot (T), aunque `updated_at` no sea el que compara.
        h.summaries.upsert(
            summary(ownerA, p1, updatedAt = "2026-08-01T10:00:01.000Z", contentUpdatedAt = "2026-08-01T10:00:01.000Z", name = "Cambio"),
        )
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1, sourceUpdatedAt = "2026-08-01T10:00:00.000Z")

        val item = h.repo.observeProjects(ownerA).first().single()

        assertEquals(ProjectAvailability.UPDATE_POSSIBLE, item.availability)
    }

    @Test
    fun `estado de descarga terminal no marca updating`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, name = "Fallida"))
        h.downloads.upsert(
            DownloadStateEntity(
                ownerId = ownerA, projectId = p1.value, workId = "w",
                state = DownloadStateEntity.STATE_FAILED,
            ),
        )
        assertEquals(
            ProjectAvailability.REMOTE_ONLY,
            h.repo.observeProjects(ownerA).first().single().availability,
        )
    }

    @Test
    fun `proyecto download-only con descarga activa aparece en la lista`() = runBlocking {
        val h = Harness()
        h.downloads.upsert(
            DownloadStateEntity(
                ownerId = ownerA, projectId = p1.value, workId = "w",
                state = DownloadStateEntity.STATE_DOWNLOADING,
            ),
        )

        val items = h.repo.observeProjects(ownerA).first()

        // Sin summary ni snapshot, el download state entra en la unión.
        assertEquals(listOf(p1), items.map { it.projectId })
        assertEquals(ProjectAvailability.UPDATING, items.single().availability)
    }

    @Test
    fun `proyecto download-only con estado terminal aparece como UNAVAILABLE`() = runBlocking {
        val h = Harness()
        h.downloads.upsert(
            DownloadStateEntity(
                ownerId = ownerA, projectId = p1.value, workId = "w",
                state = DownloadStateEntity.STATE_FAILED,
            ),
        )

        val item = h.repo.observeProjects(ownerA).first().single()

        assertEquals(ProjectAvailability.UNAVAILABLE, item.availability)
        // La unión no filtra por estado: el download terminal también se ve.
        assertEquals(p1, item.projectId)
    }

    @Test
    fun `download de owner B no entra en la union de owner A`() = runBlocking {
        val h = Harness()
        h.downloads.upsert(
            DownloadStateEntity(
                ownerId = ownerB, projectId = p1.value, workId = "w",
                state = DownloadStateEntity.STATE_DOWNLOADING,
            ),
        )

        assertTrue(h.repo.observeProjects(ownerA).first().isEmpty())
    }

    @Test
    fun `updated_at invalido degrada a epoch sin crash y ordena al final`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, updatedAt = "garbage", name = "Roto"))
        h.summaries.upsert(summary(ownerA, p2, updatedAt = "2026-08-01T10:00:00.000Z", name = "Sano"))

        val items = h.repo.observeProjects(ownerA).first()

        assertEquals(listOf("Sano", "Roto"), items.map { it.name })
        assertEquals(ProjectAvailability.REMOTE_ONLY, items.last().availability)
    }

    @Test
    fun `timestamps ISO extremos con overflow degradan sin crash en la lista`() = runBlocking {
        val h = Harness()
        // Año fuera del rango de epoch-millis: toEpochMilli() lanzaría
        // ArithmeticException si la conversión no fuera total (R-T07-06).
        h.summaries.upsert(summary(ownerA, p1, updatedAt = "-1000000000-01-01T00:00:00Z", name = "Min"))
        h.summaries.upsert(summary(ownerA, p2, updatedAt = "+1000000000-01-01T00:00:00Z", name = "Max"))

        val items = h.repo.observeProjects(ownerA).first()

        assertEquals(setOf("Min", "Max"), items.map { it.name }.toSet())
        assertEquals(2, items.size)
    }

    @Test
    fun `timestampEpochMillis es total ante overflow y parse invalido`() {
        assertEquals(0L, timestampEpochMillis("-1000000000-01-01T00:00:00Z"))
        assertEquals(0L, timestampEpochMillis("+1000000000-01-01T00:00:00Z"))
        assertEquals(0L, timestampEpochMillis("garbage"))
        assertEquals(0L, timestampEpochMillis(null))
        assertEquals(0L, timestampEpochMillis(""))
        assertTrue(timestampEpochMillis("2026-08-01T10:00:00.000Z") > 0L)
    }

    @Test
    fun `overlay optimista se superpone al progreso del item`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, name = "ConOverlay"))
        h.pending.upsert(pendingRow(ownerA, p1, 1, PendingProgressEntity.KIND_SUBSECTION_PREFIX + "subsec-1-a-0", desired = true))

        val item = h.repo.observeProjects(ownerA).first().single()

        assertEquals(setOf("subsec-1-a-0"), item.readingProgress.completedSubsections)
    }

    @Test
    fun `owner B no ve items de owner A`() = runBlocking {
        val h = Harness()
        h.summaries.upsert(summary(ownerA, p1, name = "DeA"))
        assertTrue(h.repo.observeProjects(ownerB).first().isEmpty())
    }

    // ------------------------------------------------------------ lector

    @Test
    fun `observeReaderProject es null sin snapshot y funciona offline con manifest`() = runBlocking {
        val h = Harness()
        assertNull(h.repo.observeReaderProject(ownerA, p1).first())

        h.summaries.upsert(summary(ownerA, p1, name = "Fresco", progressJson = "{\"completed_parts\":[1]}"))
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1)
        h.pending.upsert(pendingRow(ownerA, p1, 2, PendingProgressEntity.KIND_SECTION, desired = true, tab = "section"))

        val project = h.repo.observeReaderProject(ownerA, p1).first()!!

        assertEquals(p1, project.projectId)
        assertEquals("Fresco", project.name)
        assertEquals(ProjectStatus.Completed, project.status)
        assertEquals(listOf(1), project.parts.map { it.numero })
        assertEquals(setOf(1, 2), project.readingProgress.completedParts)
        assertEquals(500L, project.totalBytes)
        assertEquals("gen-1", project.activeGeneration)
    }

    @Test
    fun `loadPart lee la parte de la generacion activa sin red`() = runBlocking {
        val h = Harness()
        h.snapshots.snapshots[ownerA to p1.value] = snapshot(ownerA, p1)
        h.snapshots.parts[ownerA to p1.value] = mutableMapOf("gen-1" to mutableMapOf(1 to partRow(ownerA, p1, "gen-1", 1)))

        val doc: PartContentDocument? = h.repo.loadPart(ownerA, p1, partId = 1)

        assertEquals(1, doc?.partId)
        assertNull(h.repo.loadPart(ownerA, p1, partId = 99))
        assertNull(h.repo.loadPart(ownerB, p1, partId = 1))
    }
}

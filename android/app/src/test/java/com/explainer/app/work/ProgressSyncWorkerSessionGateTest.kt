package com.explainer.app.work

import android.app.Application
import android.content.Context
import androidx.work.ListenableWorker
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.TestListenableWorkerBuilder
import androidx.work.workDataOf
import com.explainer.app.core.model.ProjectId
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.ProjectSummaryEntity
import com.explainer.app.data.local.snapshot.InMemoryPendingProgressDao
import com.explainer.app.data.local.snapshot.InMemorySnapshotDao
import com.explainer.app.feature.progress.FakeProgressRemote
import com.explainer.app.feature.progress.InMemoryProjectSummaryDao
import com.explainer.app.feature.progress.ProgressSyncCoordinator
import com.explainer.app.feature.progress.ProgressThrottle
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * RC-01 (revisión final, HIGH): gate de sesión en el worker. El
 * [ProgressSyncWorker] recibe el owner de la sesión ACTUAL vía
 * [ProgressWorkerDeps] (mismo patrón que `authReady` en
 * [DownloadProjectWorker]) y bloquea ANTES de invocar el motor cuando no hay
 * sesión o el owner de WorkManager no coincide: un trabajo A que sobreviva a
 * logout/login B termina en success SIN leer filas A ni enviarlas con el
 * bearer de B; la cola durable queda intacta (el scheduler re-encola con el
 * owner correcto en el próximo login/reconexión).
 */
class ProgressSyncWorkerSessionGateTest {

    private val context: Application = Application()
    private val ownerA = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"
    private val pid = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f").value

    private class Harness(
        private val context: Application,
        private val ownerA: String,
        private val pid: String,
    ) {
        val remote = FakeProgressRemote()
        val pending = InMemoryPendingProgressDao()
        val summaries = InMemoryProjectSummaryDao()
        val snapshots = InMemorySnapshotDao()

        init {
            runBlocking {
                summaries.upsert(
                    ProjectSummaryEntity(
                        ownerId = ownerA,
                        projectId = pid,
                        name = "P",
                        remoteUpdatedAt = "2026-08-01T10:00:00.000Z",
                    ),
                )
                pending.upsert(
                    PendingProgressEntity(
                        ownerId = ownerA,
                        projectId = pid,
                        partId = 1,
                        tab = "section",
                        kindTarget = PendingProgressEntity.KIND_SECTION,
                        desiredCompleted = true,
                        lastSubsectionId = null,
                        lastReadAt = null,
                        syncState = PendingProgressEntity.SYNC_PENDING,
                        attempts = 0,
                        updatedAt = 1_000L,
                    ),
                )
            }
        }

        fun buildWorker(sessionOwner: () -> String?): ProgressSyncWorker {
            val coordinator = ProgressSyncCoordinator(
                remote = remote,
                pendingDao = pending,
                summaryDao = summaries,
                snapshotDao = snapshots,
                throttle = ProgressThrottle(),
                sessionOwner = sessionOwner,
            )
            val deps = ProgressWorkerDeps(
                coordinator = coordinator,
                sessionOwner = sessionOwner,
            )
            val factory = object : WorkerFactory() {
                override fun createWorker(
                    appContext: Context,
                    workerClassName: String,
                    workerParameters: WorkerParameters,
                ): ListenableWorker? = ProgressSyncWorker(appContext, workerParameters, deps)
            }
            return TestListenableWorkerBuilder.from(context, ListenableWorker::class.java)
                .setWorkerFactory(factory)
                .setInputData(workDataOf(ProgressSyncWorker.KEY_OWNER_ID to ownerA))
                .build(ProgressSyncWorker::class.java) as ProgressSyncWorker
        }
    }

    @Test
    fun `worker de A con sesion B no envia filas de A y conserva la cola`() = runBlocking {
        val h = Harness(context, ownerA, pid)

        val result = h.buildWorker(sessionOwner = { ownerB }).doWork()

        assertEquals(Result.success(), result)
        assertEquals("el motor no se ejecuta: cero envíos con el bearer de B", 0, h.remote.sectionCalls.size)
        assertEquals(0, h.remote.subsectionCalls.size)
        val row = h.pending.rows[ownerA to pid]!!.single()
        assertEquals(PendingProgressEntity.SYNC_PENDING, row.syncState)
    }

    @Test
    fun `worker sin sesion (owner nulo) no envia y conserva la cola`() = runBlocking {
        val h = Harness(context, ownerA, pid)

        val result = h.buildWorker(sessionOwner = { null }).doWork()

        assertEquals(Result.success(), result)
        assertEquals(0, h.remote.sectionCalls.size)
        assertEquals(0, h.remote.subsectionCalls.size)
        assertEquals(PendingProgressEntity.SYNC_PENDING, h.pending.rows[ownerA to pid]!!.single().syncState)
    }

    @Test
    fun `worker con sesion del mismo owner sincroniza normal`() = runBlocking {
        val h = Harness(context, ownerA, pid)

        val result = h.buildWorker(sessionOwner = { ownerA }).doWork()

        assertEquals(Result.success(), result)
        assertEquals(1, h.remote.sectionCalls.size)
        assertTrue(h.remote.subsectionCalls.isEmpty())
        assertEquals(PendingProgressEntity.SYNC_ACKNOWLEDGED, h.pending.rows[ownerA to pid]!!.single().syncState)
    }
}

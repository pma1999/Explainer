package com.explainer.app.work

import android.app.Application
import androidx.work.Data
import androidx.work.ListenableWorker
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.impl.utils.SynchronousExecutor
import androidx.work.testing.TestForegroundUpdater
import androidx.work.testing.TestListenableWorkerBuilder
import androidx.work.testing.TestProgressUpdater
import androidx.work.workDataOf
import com.explainer.app.feature.download.DownloadProjectUseCase
import com.explainer.app.feature.download.DownloadStatePersister
import com.explainer.app.feature.download.FakeRemote
import com.explainer.app.feature.download.FakeStore
import com.explainer.app.feature.download.InMemoryDownloadStateDao
import com.explainer.app.feature.download.InMemorySummaryDao
import com.explainer.app.feature.progress.FakeProgressRemote
import com.explainer.app.feature.progress.InMemoryProjectSummaryDao
import com.explainer.app.feature.progress.ProgressSyncCoordinator
import com.explainer.app.feature.progress.ProgressThrottle
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.UUID

/**
 * Custom WorkerFactory (T11): construye exactamente los dos workers con
 * dependencias inyectadas y delega cualquier clase desconocida. Los deps se
 * construyen con los fakes JVM de T06/T07 (nunca dentro de doWork).
 */
class WorkerFactoryTest {

    private val context: Application = Application()

    private fun factory(): ExplainerWorkerFactory {
        val downloadDao = InMemoryDownloadStateDao()
        val summaryDao = InMemorySummaryDao()
        val remote = FakeRemote()
        val store = FakeStore()
        val useCase = DownloadProjectUseCase(
            remote = remote,
            store = store,
            downloadDao = downloadDao,
            summaryDao = summaryDao,
            tempDirProvider = { File.createTempFile("factory", ".json") },
            diskFreeBytes = { Long.MAX_VALUE },
            sessionOwner = { "7c9e6679-7425-40de-944b-e07fc1f90ae7" },
        )
        val downloadDeps = DownloadWorkerDeps(
            useCase = useCase,
            persister = DownloadStatePersister(downloadDao),
        )
        val progressDeps = ProgressWorkerDeps(
            coordinator = ProgressSyncCoordinator(
                remote = FakeProgressRemote(),
                pendingDao = EmptyPendingProgressDao(),
                summaryDao = InMemoryProjectSummaryDao(),
                snapshotDao = EmptySnapshotDao(),
                throttle = ProgressThrottle(),
            ),
            sessionOwner = { "7c9e6679-7425-40de-944b-e07fc1f90ae7" },
        )
        return ExplainerWorkerFactory(downloadDeps, progressDeps)
    }

    @Test
    fun `factory crea el DownloadProjectWorker con dependencias`() {
        val worker = TestListenableWorkerBuilder.from(context, ListenableWorker::class.java)
            .setWorkerFactory(factory())
            .setInputData(
                workDataOf(
                    DownloadProjectWorker.KEY_OWNER_ID to "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                    DownloadProjectWorker.KEY_PROJECT_ID to "3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f",
                ),
            )
            .build(DownloadProjectWorker::class.java)
        assertTrue(worker is DownloadProjectWorker)
    }

    @Test
    fun `factory crea el ProgressSyncWorker con dependencias`() {
        val worker = TestListenableWorkerBuilder.from(context, ListenableWorker::class.java)
            .setWorkerFactory(factory())
            .setInputData(workDataOf(ProgressSyncWorker.KEY_OWNER_ID to "7c9e6679-7425-40de-944b-e07fc1f90ae7"))
            .build(ProgressSyncWorker::class.java)
        assertTrue(worker is ProgressSyncWorker)
    }

    @Test
    fun `factory delega clases desconocidas a null`() {
        val f = factory()
        val params = WorkerParameters(
            UUID.randomUUID(),
            Data.EMPTY,
            emptyList<String>(),
            WorkerParameters.RuntimeExtras(),
            0,
            0,
            SynchronousExecutor(),
            Dispatchers.Default,
            NoOpTaskExecutor(),
            f as WorkerFactory,
            TestProgressUpdater(),
            TestForegroundUpdater(),
        )
        assertNull(f.createWorker(context, "com.explainer.app.work.UnknownWorker", params))
    }
}

/** TaskExecutor sin Android (JVM): solo construye WorkerParameters. */
private class NoOpTaskExecutor : androidx.work.impl.utils.taskexecutor.TaskExecutor {
    override fun getMainThreadExecutor(): java.util.concurrent.Executor = SynchronousExecutor()
    override fun getSerialTaskExecutor(): androidx.work.impl.utils.taskexecutor.SerialExecutor =
        androidx.work.impl.utils.SerialExecutorImpl(SynchronousExecutor())
}

/** Cola de progreso vacía (el coordinador nunca se ejecuta en estos tests). */
private class EmptyPendingProgressDao : com.explainer.app.data.local.db.PendingProgressDao {
    override fun observeProject(ownerId: String, projectId: String): kotlinx.coroutines.flow.Flow<List<com.explainer.app.data.local.db.PendingProgressEntity>> =
        kotlinx.coroutines.flow.flowOf(emptyList())

    override suspend fun pendingRows(ownerId: String, projectId: String): List<com.explainer.app.data.local.db.PendingProgressEntity> = emptyList()
    override suspend fun upsert(entry: com.explainer.app.data.local.db.PendingProgressEntity) = Unit
    override suspend fun acknowledgeIfUnchanged(ownerId: String, projectId: String, partId: Int, tab: String, kindTarget: String, expectedUpdatedAt: Long): Int = 0
    override suspend fun delete(ownerId: String, projectId: String, partId: Int, tab: String, kindTarget: String) = Unit
    override suspend fun deleteProject(ownerId: String, projectId: String) = Unit
}

/** Snapshot DAO vacío (el coordinador nunca se ejecuta en estos tests). */
private class EmptySnapshotDao : com.explainer.app.data.local.db.SnapshotDao() {
    override suspend fun workRow(ownerId: String, projectId: String): com.explainer.app.data.local.db.DownloadStateEntity? = null
    override suspend fun pendingRows(ownerId: String, projectId: String): List<com.explainer.app.data.local.db.PendingProgressEntity> = emptyList()
    override suspend fun snapshotRow(ownerId: String, projectId: String): com.explainer.app.data.local.db.OfflineSnapshotEntity? = null
    override suspend fun activePartRow(ownerId: String, projectId: String, partId: Int): com.explainer.app.data.local.db.OfflinePartEntity? = null
    override suspend fun partRow(ownerId: String, projectId: String, generation: String, partId: Int): com.explainer.app.data.local.db.OfflinePartEntity? = null
    override suspend fun generationParts(ownerId: String, projectId: String, generation: String): List<com.explainer.app.data.local.db.OfflinePartEntity> = emptyList()
    override suspend fun allPartGenerations(): List<com.explainer.app.data.local.db.PartGenerationKey> = emptyList()
    override suspend fun allActiveGenerations(): List<com.explainer.app.data.local.db.ActiveGenerationRow> = emptyList()
    override suspend fun generationPartBytes(ownerId: String, projectId: String, generation: String): Long = 0L
    override fun observeSnapshots(ownerId: String): kotlinx.coroutines.flow.Flow<List<com.explainer.app.data.local.db.OfflineSnapshotEntity>> = kotlinx.coroutines.flow.flowOf(emptyList())
    override fun observeSnapshot(ownerId: String, projectId: String): kotlinx.coroutines.flow.Flow<com.explainer.app.data.local.db.OfflineSnapshotEntity?> = kotlinx.coroutines.flow.flowOf(null)
    override suspend fun insertParts(parts: List<com.explainer.app.data.local.db.OfflinePartEntity>) = Unit
    override suspend fun upsertSnapshot(snapshot: com.explainer.app.data.local.db.OfflineSnapshotEntity) = Unit
    override suspend fun deleteGenerationParts(ownerId: String, projectId: String, generation: String) = Unit
    override suspend fun deleteSnapshot(ownerId: String, projectId: String) = Unit
    override suspend fun deleteAllParts(ownerId: String, projectId: String) = Unit
    override suspend fun deleteDownloadState(ownerId: String, projectId: String) = Unit
    override suspend fun deletePendingProgress(ownerId: String, projectId: String) = Unit
}

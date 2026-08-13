package com.explainer.app.di

import com.explainer.app.data.local.db.ActiveGenerationRow
import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.db.OfflinePartEntity
import com.explainer.app.data.local.db.OfflineSnapshotEntity
import com.explainer.app.data.local.db.PartGenerationKey
import com.explainer.app.data.local.db.PendingProgressEntity
import com.explainer.app.data.local.db.SnapshotDao
import com.explainer.app.feature.download.InMemoryDownloadStateDao
import com.explainer.app.feature.download.InMemorySummaryDao
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Borrado total local (T11): "borrar todo" enumera y borra SOLO las filas
 * del owner activo (summary ∪ snapshot ∪ download), nunca las de otro
 * owner, y ejecuta el checkpoint best-effort al final. Owner inválido: no
 * toca nada.
 */
class LocalDataDeleterTest {

    private val ownerA = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"
    private val projectA1 = "3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f"
    private val projectA2 = "4e8d9c2f-1b5a-4c6d-9e3f-2a7b8c0d1e2f"
    private val projectB1 = "9f4c2a8d-7e3b-4f1a-8d5c-2b6e9a0f1c3d"

    private class Harness {
        val summaryDao = InMemorySummaryDao()
        val downloadDao = InMemoryDownloadStateDao()
        val snapshotDao = SnapshotRowsDao()
        val deleted = mutableListOf<Pair<String, String>>()
        var checkpoints = 0

        fun seed(owner: String, project: String, bytes: Long) {
            summaryDao.rows[owner to project] = com.explainer.app.data.local.db.ProjectSummaryEntity(
                ownerId = owner,
                projectId = project,
                name = "Proyecto",
                segmentationSourceBytes = bytes,
            )
            snapshotDao.rows[owner to project] = OfflineSnapshotEntity(
                ownerId = owner,
                projectId = project,
                activeGeneration = "g1",
                totalBytes = bytes,
            )
            downloadDao.rows[owner to project] = DownloadStateEntity(
                ownerId = owner,
                projectId = project,
                workId = "w1",
                state = DownloadStateEntity.STATE_SUCCEEDED,
            )
        }

        fun deleter() = LocalDataDeleter(
            summaryDao = summaryDao,
            snapshotDao = snapshotDao,
            downloadDao = downloadDao,
            deleteProject = { owner, project -> deleted.add(owner to project.value) },
            checkpoint = { checkpoints++ },
        )
    }

    @Test
    fun `borrar todo del owner A no toca las filas de B`() = runBlocking {
        val harness = Harness()
        harness.seed(ownerA, projectA1, 1024L)
        harness.seed(ownerA, projectA2, 2048L)
        harness.seed(ownerB, projectB1, 4096L)

        harness.deleter().deleteAllLocal(ownerA)

        assertEquals(
            setOf(ownerA to projectA1, ownerA to projectA2),
            harness.deleted.toSet(),
        )
        assertTrue(harness.deleted.none { it.first == ownerB })
        assertEquals(1, harness.checkpoints)
        // Las filas de B quedan intactas.
        assertEquals(4096L, harness.snapshotDao.rows[ownerB to projectB1]?.totalBytes)
    }

    @Test
    fun `owner sin filas solo ejecuta checkpoint`() = runBlocking {
        val harness = Harness()
        harness.deleter().deleteAllLocal(ownerA)
        assertTrue(harness.deleted.isEmpty())
        assertEquals(1, harness.checkpoints)
    }

    @Test
    fun `owner invalido no borra ni hace checkpoint`() = runBlocking {
        val harness = Harness()
        harness.seed(ownerA, projectA1, 1024L)
        harness.deleter().deleteAllLocal("../etc/passwd")
        assertTrue(harness.deleted.isEmpty())
        assertEquals(0, harness.checkpoints)
        assertEquals(1024L, harness.snapshotDao.rows[ownerA to projectA1]?.totalBytes)
    }

    @Test
    fun `ids no parseables se omiten sin abortar el resto`() = runBlocking {
        val harness = Harness()
        harness.seed(ownerA, projectA1, 1024L)
        harness.summaryDao.rows[ownerA to "not-a-uuid"] =
            com.explainer.app.data.local.db.ProjectSummaryEntity(ownerId = ownerA, projectId = "not-a-uuid")

        harness.deleter().deleteAllLocal(ownerA)

        assertEquals(listOf(ownerA to projectA1), harness.deleted)
        assertEquals(1, harness.checkpoints)
    }
}

/** Snapshot DAO con solo las filas de manifest (para enumerar el borrado). */
private class SnapshotRowsDao : SnapshotDao() {
    val rows = mutableMapOf<Pair<String, String>, OfflineSnapshotEntity>()

    override fun observeSnapshots(ownerId: String): Flow<List<OfflineSnapshotEntity>> =
        flowOf(rows.values.filter { it.ownerId == ownerId })

    override fun observeSnapshot(ownerId: String, projectId: String): Flow<OfflineSnapshotEntity?> =
        flowOf(rows[ownerId to projectId])

    override suspend fun workRow(ownerId: String, projectId: String): DownloadStateEntity? = null
    override suspend fun pendingRows(ownerId: String, projectId: String): List<PendingProgressEntity> = emptyList()
    override suspend fun snapshotRow(ownerId: String, projectId: String): OfflineSnapshotEntity? = rows[ownerId to projectId]
    override suspend fun activePartRow(ownerId: String, projectId: String, partId: Int): OfflinePartEntity? = null
    override suspend fun partRow(ownerId: String, projectId: String, generation: String, partId: Int): OfflinePartEntity? = null
    override suspend fun generationParts(ownerId: String, projectId: String, generation: String): List<OfflinePartEntity> = emptyList()
    override suspend fun allPartGenerations(): List<PartGenerationKey> = emptyList()
    override suspend fun allActiveGenerations(): List<ActiveGenerationRow> = emptyList()
    override suspend fun generationPartBytes(ownerId: String, projectId: String, generation: String): Long = 0L
    override suspend fun insertParts(parts: List<OfflinePartEntity>) = Unit
    override suspend fun upsertSnapshot(snapshot: OfflineSnapshotEntity) = Unit
    override suspend fun deleteGenerationParts(ownerId: String, projectId: String, generation: String) = Unit
    override suspend fun deleteSnapshot(ownerId: String, projectId: String) = Unit
    override suspend fun deleteAllParts(ownerId: String, projectId: String) = Unit
    override suspend fun deleteDownloadState(ownerId: String, projectId: String) = Unit
    override suspend fun deletePendingProgress(ownerId: String, projectId: String) = Unit
}

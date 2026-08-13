package com.explainer.app.feature.download

import com.explainer.app.data.local.db.DownloadStateEntity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadStatePersisterTest {

    private val dao = InMemoryDownloadStateDao()
    private var now = 5000L
    private val persister = DownloadStatePersister(dao) { now }

    @Test
    fun `persist updates the row for the same work id`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1", state = DownloadStateEntity.STATE_DOWNLOADING, downloadedBytes = 10L, totalBytes = 100L)

        persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Downloading(40L, 100L, SizeEstimator.verified(100L)))

        val row = dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals(DownloadStateEntity.STATE_DOWNLOADING, row.state)
        assertEquals(40L, row.downloadedBytes)
        assertEquals(100L, row.totalBytes)
        assertNull(row.errorCategory)
        assertNull(row.finishedAt)
    }

    @Test
    fun `persist never resurrects a deleted row`() = runBlocking {
        // deleteLocal borró la fila: un worker tardío no la recrea.
        persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Cancelled(TEST_PROJECT_ID))
        persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Failed(TEST_PROJECT_ID, DownloadError.Network))
        assertTrue(dao.rows.isEmpty())
    }

    @Test
    fun `persist never clobbers a newer attempt row`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w2", state = DownloadStateEntity.STATE_DOWNLOADING)

        persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Succeeded(com.explainer.app.data.local.snapshot.SnapshotDescriptor(TEST_OWNER_A, TEST_PROJECT_ID, "g", 1L, "", 0L)))

        val row = dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals("w2", row.workId)
        assertEquals(DownloadStateEntity.STATE_DOWNLOADING, row.state)
    }

    @Test
    fun `terminal states persist error category and finished timestamp`() = runBlocking {
        dao.seed(TEST_OWNER_A, workId = "w1")

        persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Failed(TEST_PROJECT_ID, DownloadError.NotEnoughSpace))
        var row = dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals(DownloadStateEntity.STATE_FAILED, row.state)
        assertEquals("not_enough_space", row.errorCategory)
        assertEquals(5000L, row.finishedAt)

        // R-T06-01: un estado terminal es FINAL para las escrituras del
        // worker — el CAS sobre estado terminal no aplica; el único escritor
        // que marca terminal es el coordinador (cancel/delete, upsert propio).
        now = 6000L
        persister.persist(TEST_OWNER_A, TEST_PROJECT_ID, "w1", DownloadState.Cancelled(TEST_PROJECT_ID))
        row = dao.rows.getValue(TEST_OWNER_A to TEST_PROJECT_ID.value)
        assertEquals(DownloadStateEntity.STATE_FAILED, row.state)
        assertEquals("not_enough_space", row.errorCategory)
        assertEquals(5000L, row.finishedAt)
    }
}

package com.explainer.app.feature.download

import com.explainer.app.data.local.db.DownloadStateEntity
import com.explainer.app.data.local.snapshot.SnapshotDescriptor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadStateMapperTest {

    private val projectId = TEST_PROJECT_ID
    private val owner = TEST_OWNER_A

    private fun entity(
        state: String = DownloadStateEntity.STATE_DOWNLOADING,
        downloaded: Long = 0L,
        total: Long? = null,
        error: String? = null,
        requestedAt: Long = 1000L,
        finishedAt: Long? = null,
    ) = DownloadStateEntity(
        ownerId = owner,
        projectId = projectId.value,
        workId = "w1",
        state = state,
        downloadedBytes = downloaded,
        totalBytes = total,
        errorCategory = error,
        requestedAt = requestedAt,
        finishedAt = finishedAt,
    )

    @Test
    fun `entity maps to each observable state`() {
        assertEquals(DownloadState.Queued(projectId, 1000L), DownloadStateMapper.fromEntity(entity(DownloadStateEntity.STATE_QUEUED), projectId))
        assertEquals(
            DownloadState.Downloading(
                50L,
                200L,
                // R-T06-08: tras reinicio, un total en curso es SIEMPRE grado
                // cabecera (conservador), nunca EXACT.
                SizeEstimate(200L, 200L, SizeConfidence.HEADER),
            ),
            DownloadStateMapper.fromEntity(entity(DownloadStateEntity.STATE_DOWNLOADING, downloaded = 50L, total = 200L), projectId),
        )
        assertEquals(DownloadState.Preparing(projectId), DownloadStateMapper.fromEntity(entity(DownloadStateEntity.STATE_PREPARING), projectId))
        assertEquals(DownloadState.Committing(projectId), DownloadStateMapper.fromEntity(entity(DownloadStateEntity.STATE_COMMITTING), projectId))
        assertEquals(DownloadState.Cancelled(projectId), DownloadStateMapper.fromEntity(entity(DownloadStateEntity.STATE_CANCELLED), projectId))
    }

    // ------------------------------------------------------------------
    // R-T06-08: reinicio con estado HEADER/EXACT (confianza durable)
    // ------------------------------------------------------------------

    @Test
    fun `restart of an in progress download represents the total conservatively as header`() {
        // La descarga en vivo llegó a EXACT (200 bytes verificados) pero el
        // proceso murió antes del commit: la fila durable solo guarda el
        // total, así que tras reinicio se degrada a grado cabecera.
        val state = DownloadStateMapper.fromEntity(
            entity(DownloadStateEntity.STATE_DOWNLOADING, downloaded = 200L, total = 200L),
            projectId,
        ) as DownloadState.Downloading
        assertEquals(SizeConfidence.HEADER, state.estimate?.confidence)
        assertEquals(SizeEstimate(200L, 200L, SizeConfidence.HEADER), state.estimate)
    }

    @Test
    fun `restart without a total has no size estimate`() {
        val state = DownloadStateMapper.fromEntity(
            entity(DownloadStateEntity.STATE_DOWNLOADING, downloaded = 50L),
            projectId,
        ) as DownloadState.Downloading
        assertEquals(50L, state.downloadedBytes)
        assertNull(state.totalBytes)
        assertNull(state.estimate)
    }

    @Test
    fun `restart after an exact completed download maps to the committed descriptor`() {
        // Caso EXACT durable: la descarga verificó los bytes y el commit
        // publicó; la observación reconstruye el descriptor del manifest.
        val descriptor = SnapshotDescriptor(owner, projectId, "gen-1", 845L, "2026-08-01T00:00:00Z", 1234L)
        val succeeded = DownloadStateMapper.fromEntity(
            entity(DownloadStateEntity.STATE_SUCCEEDED, downloaded = 845L, total = 845L),
            projectId,
            descriptor,
        ) as DownloadState.Succeeded
        assertEquals(descriptor, succeeded.descriptor)
    }

    @Test
    fun `failed maps error category through the codec`() {
        val failed = DownloadStateMapper.fromEntity(
            entity(DownloadStateEntity.STATE_FAILED, error = "not_found"),
            projectId,
        ) as DownloadState.Failed
        assertEquals(DownloadError.NotFound, failed.error)
    }

    @Test
    fun `failed without category degrades safely`() {
        val failed = DownloadStateMapper.fromEntity(
            entity(DownloadStateEntity.STATE_FAILED),
            projectId,
        ) as DownloadState.Failed
        assertEquals(DownloadError.Permanent("unknown"), failed.error)
    }

    @Test
    fun `succeeded uses the real descriptor when provided`() {
        val descriptor = SnapshotDescriptor(owner, projectId, "gen-1", 845L, "2026-08-01T00:00:00Z", 1234L)
        val succeeded = DownloadStateMapper.fromEntity(
            entity(DownloadStateEntity.STATE_SUCCEEDED, downloaded = 845L),
            projectId,
            descriptor,
        ) as DownloadState.Succeeded
        assertEquals(descriptor, succeeded.descriptor)
    }

    @Test
    fun `succeeded without manifest builds a minimal descriptor`() {
        val succeeded = DownloadStateMapper.fromEntity(
            entity(DownloadStateEntity.STATE_SUCCEEDED, downloaded = 845L, finishedAt = 99L),
            projectId,
        ) as DownloadState.Succeeded
        assertEquals("", succeeded.descriptor.generation)
        assertEquals(845L, succeeded.descriptor.totalBytes)
        assertEquals(99L, succeeded.descriptor.downloadedAt)
    }

    @Test
    fun `unknown future state degrades to local failure`() {
        val failed = DownloadStateMapper.fromEntity(entity("Future"), projectId) as DownloadState.Failed
        assertEquals(DownloadError.Local("state:Future"), failed.error)
    }

    @Test
    fun `withState writes durable fields per emitted state`() {
        val base = entity(DownloadStateEntity.STATE_DOWNLOADING, downloaded = 10L, total = 100L)

        assertEquals(
            DownloadStateEntity.STATE_QUEUED,
            base.withState(DownloadState.Queued(projectId, 5L), 2000L).state,
        )
        val downloading = base.withState(DownloadState.Downloading(40L, 100L, SizeEstimator.verified(100L)), 2000L)
        assertEquals(DownloadStateEntity.STATE_DOWNLOADING, downloading.state)
        assertEquals(40L, downloading.downloadedBytes)
        assertEquals(100L, downloading.totalBytes)

        assertEquals(DownloadStateEntity.STATE_PREPARING, base.withState(DownloadState.Preparing(projectId), 2000L).state)
        assertEquals(DownloadStateEntity.STATE_COMMITTING, base.withState(DownloadState.Committing(projectId), 2000L).state)

        val succeeded = base.withState(
            DownloadState.Succeeded(SnapshotDescriptor(owner, projectId, "g", 845L, "ts", 1234L)),
            2000L,
        )
        assertEquals(DownloadStateEntity.STATE_SUCCEEDED, succeeded.state)
        assertEquals(845L, succeeded.downloadedBytes)
        assertEquals(845L, succeeded.totalBytes)
        assertEquals(2000L, succeeded.finishedAt)

        val cancelled = base.withState(DownloadState.Cancelled(projectId), 2000L)
        assertEquals(DownloadStateEntity.STATE_CANCELLED, cancelled.state)
        assertEquals(2000L, cancelled.finishedAt)

        val failed = base.withState(DownloadState.Failed(projectId, DownloadError.NotEnoughSpace), 2000L)
        assertEquals(DownloadStateEntity.STATE_FAILED, failed.state)
        assertEquals("not_enough_space", failed.errorCategory)
        assertEquals(2000L, failed.finishedAt)
    }

    @Test
    fun `withState resets stale fields on queued and downloading`() {
        val stale = entity(
            DownloadStateEntity.STATE_CANCELLED,
            downloaded = 50L,
            total = 100L,
            error = "network",
            finishedAt = 99L,
        )
        val queued = stale.withState(DownloadState.Queued(projectId, 5L), 2000L)
        assertEquals(0L, queued.downloadedBytes)
        assertNull(queued.totalBytes)
        assertNull(queued.errorCategory)
        assertNull(queued.finishedAt)

        val downloading = stale.withState(DownloadState.Downloading(7L, null), 2000L)
        assertNull(downloading.errorCategory)
        assertNull(downloading.finishedAt)
    }

    @Test
    fun `manifest maps to a full descriptor`() {
        val manifest = com.explainer.app.data.local.snapshot.OfflineProjectManifest(
            ownerId = owner,
            projectId = projectId,
            name = "X",
            description = null,
            status = com.explainer.app.core.model.ProjectStatus.Completed,
            sourceType = "pdf",
            parts = emptyList(),
            usage = kotlinx.serialization.json.JsonObject(emptyMap()),
            readingProgress = com.explainer.app.core.model.ReadingProgress(),
            activeGeneration = "gen-9",
            sourceUpdatedAt = "2026-08-01T00:00:00Z",
            downloadedAt = 55L,
            totalBytes = 845L,
        )
        val descriptor = manifest.toDescriptor()
        assertEquals("gen-9", descriptor.generation)
        assertEquals(55L, descriptor.downloadedAt)
        assertEquals(845L, descriptor.totalBytes)
        assertTrue(descriptor.projectId == projectId)
    }
}

package com.explainer.app.feature.download

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SizeEstimatorTest {

    @Test
    fun `segmentation bytes produce 2x-6x heuristic range with 1 MiB floor`() {
        val estimate = SizeEstimator.fromSegmentation(2_000_000L)
        assertEquals(SizeConfidence.HEURISTIC, estimate.confidence)
        assertEquals(4_000_000L, estimate.lowBytes)
        assertEquals(12_000_000L, estimate.highBytes)
    }

    @Test
    fun `tiny or empty segmentation is floored to 1 MiB`() {
        val tiny = SizeEstimator.fromSegmentation(10L)
        assertEquals(SizeEstimator.FLOOR_BYTES, tiny.lowBytes)
        assertEquals(SizeEstimator.FLOOR_BYTES, tiny.highBytes)

        val empty = SizeEstimator.fromSegmentation(0L)
        assertEquals(SizeEstimator.FLOOR_BYTES, empty.lowBytes)
        assertEquals(SizeEstimator.FLOOR_BYTES, empty.highBytes)
    }

    @Test
    fun `partial floor keeps the range asymmetric when 2x is below floor`() {
        // 500 KiB de segmentation: 2x = 1000 KiB < 1 MiB, 6x = 3000 KiB > 1 MiB.
        val estimate = SizeEstimator.fromSegmentation(500L * 1024)
        assertEquals(SizeEstimator.FLOOR_BYTES, estimate.lowBytes)
        assertEquals(500L * 1024 * 6, estimate.highBytes)
    }

    @Test
    fun `huge segmentation saturates instead of overflowing`() {
        val estimate = SizeEstimator.fromSegmentation(Long.MAX_VALUE)
        assertEquals(Long.MAX_VALUE, estimate.lowBytes)
        assertEquals(Long.MAX_VALUE, estimate.highBytes)
    }

    @Test
    fun `current snapshot exact size is carried as informational`() {
        val estimate = SizeEstimator.fromSegmentation(2_000_000L, currentSnapshotBytes = 845L)
        assertEquals(845L, estimate.currentSnapshotBytes)
        assertNull(SizeEstimator.fromSegmentation(0L).currentSnapshotBytes)
    }

    @Test
    fun `content length substitutes the total as header confidence`() {
        val estimate = SizeEstimator.fromContentLength(7_000_000L)
        assertEquals(SizeConfidence.HEADER, estimate.confidence)
        assertEquals(7_000_000L, estimate.lowBytes)
        assertEquals(7_000_000L, estimate.highBytes)
    }

    @Test
    fun `verified bytes are exact confidence`() {
        val estimate = SizeEstimator.verified(3L)
        assertEquals(SizeConfidence.EXACT, estimate.confidence)
        assertEquals(3L, estimate.lowBytes)
        assertEquals(3L, estimate.highBytes)
    }
}

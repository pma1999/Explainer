package com.explainer.app.feature.download

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StorageGuardTest {

    private val mib = 1024L * 1024

    @Test
    fun `required free is 2x expected plus 32 MiB`() {
        assertEquals(StorageGuard.RESERVE_MARGIN_BYTES, StorageGuard.requiredFreeBytes(0L))
        assertEquals(2L * mib + StorageGuard.RESERVE_MARGIN_BYTES, StorageGuard.requiredFreeBytes(mib))
        assertEquals(200L * mib + StorageGuard.RESERVE_MARGIN_BYTES, StorageGuard.requiredFreeBytes(100L * mib))
    }

    @Test
    fun `required free saturates instead of overflowing`() {
        assertEquals(Long.MAX_VALUE, StorageGuard.requiredFreeBytes(Long.MAX_VALUE))
    }

    @Test
    fun `preflight passes only with the full reservation free`() {
        val expected = 100L * mib
        val required = StorageGuard.requiredFreeBytes(expected)
        assertTrue(StorageGuard.sufficientSpace(required, expected, 0L))
        assertFalse(StorageGuard.sufficientSpace(required - 1, expected, 0L))
    }

    @Test
    fun `content length recalc uses the header total instead of the heuristic`() {
        // Heurístico alto 1 MiB cabe (34 MiB libres), pero el Content-Length
        // real de 100 MiB no.
        val free = StorageGuard.requiredFreeBytes(SizeEstimator.FLOOR_BYTES)
        assertTrue(StorageGuard.sufficientSpace(free, SizeEstimator.FLOOR_BYTES, 0L))
        assertFalse(StorageGuard.sufficientSpace(free, 100L * mib, 0L))
    }

    @Test
    fun `during stream the reservation applies to remaining bytes`() {
        val expected = 100L * mib
        // Con 90 MiB ya recibidos, solo se reserva 2*10 MiB + 32 MiB.
        val remainingRequired = StorageGuard.requiredFreeBytes(10L * mib)
        assertTrue(StorageGuard.sufficientSpace(remainingRequired, expected, 90L * mib))
        assertFalse(StorageGuard.sufficientSpace(remainingRequired - 1, expected, 90L * mib))
    }

    @Test
    fun `received beyond expected only needs the margin`() {
        val expected = 10L * mib
        assertTrue(StorageGuard.sufficientSpace(StorageGuard.RESERVE_MARGIN_BYTES, expected, 12L * mib))
        assertFalse(StorageGuard.sufficientSpace(StorageGuard.RESERVE_MARGIN_BYTES - 1, expected, 12L * mib))
    }

    @Test
    fun `negative or zero expected never over-reserves`() {
        assertEquals(StorageGuard.RESERVE_MARGIN_BYTES, StorageGuard.requiredFreeBytes(-5L))
        assertTrue(StorageGuard.sufficientSpace(StorageGuard.RESERVE_MARGIN_BYTES, 0L, 0L))
    }
}

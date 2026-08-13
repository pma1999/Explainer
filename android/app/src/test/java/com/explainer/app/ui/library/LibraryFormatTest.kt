package com.explainer.app.ui.library

import java.time.Instant
import java.time.ZoneOffset
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Formateo utilitario de la biblioteca (T09): bytes con coma decimal,
 * rango estimado con unidad común, tiempo relativo y fecha absoluta.
 * Determinista (locale/zonas fijas) para tests JVM.
 */
class LibraryFormatTest {

    /** 2026-08-12T10:00:00Z, reloj fijo de los tests. */
    private val NOW: Long = Instant.parse("2026-08-12T10:00:00Z").toEpochMilli()

    private val MIB: Long = 1024L * 1024L

    // ---- Bytes ----

    @Test
    fun `bytes formatean en B KB MB GB`() {
        assertEquals("0 B", LibraryFormat.formatBytes(0L))
        assertEquals("512 B", LibraryFormat.formatBytes(512L))
        assertEquals("1,5 KB", LibraryFormat.formatBytes(1536L))
        assertEquals("12 KB", LibraryFormat.formatBytes(12L * 1024L))
        assertEquals("2,3 MB", LibraryFormat.formatBytes(2_412_544L))
        assertEquals("42 MB", LibraryFormat.formatBytes(42L * 1024L * 1024L))
        assertEquals("1,2 GB", LibraryFormat.formatBytes(1_288_490_189L))
    }

    @Test
    fun `bytes negativos degradan a cero`() {
        assertEquals("0 B", LibraryFormat.formatBytes(-5L))
    }

    // ---- Rango estimado ----

    @Test
    fun `rango con misma unidad se compacta`() {
        assertEquals("1–6 MB", LibraryFormat.formatRange(1L * MIB, 6L * MIB))
        assertEquals("2–6 MB", LibraryFormat.formatRange(2L * MIB, 6L * MIB))
    }

    @Test
    fun `rango con unidades distintas conserva ambas`() {
        assertEquals("512 KB – 2 MB", LibraryFormat.formatRange(512L * 1024L, 2L * MIB))
    }

    // ---- Tiempo relativo ----

    @Test
    fun `tiempo relativo respeta fronteras`() {
        assertEquals(RelativeTime.JustNow, LibraryFormat.relativeTime(NOW - 59_000L, NOW))
        assertEquals(RelativeTime.MinutesAgo(1), LibraryFormat.relativeTime(NOW - 60_000L, NOW))
        assertEquals(RelativeTime.MinutesAgo(59), LibraryFormat.relativeTime(NOW - 59 * 60_000L, NOW))
        assertEquals(RelativeTime.HoursAgo(1), LibraryFormat.relativeTime(NOW - 60 * 60_000L, NOW))
        assertEquals(RelativeTime.HoursAgo(23), LibraryFormat.relativeTime(NOW - 23 * 60 * 60_000L, NOW))
        assertEquals(RelativeTime.DaysAgo(1), LibraryFormat.relativeTime(NOW - 24 * 60 * 60_000L, NOW))
        assertEquals(RelativeTime.DaysAgo(6), LibraryFormat.relativeTime(NOW - 6 * 24 * 60 * 60_000L, NOW))
        assertEquals(RelativeTime.DaysAgo(7), LibraryFormat.relativeTime(NOW - 7 * 24 * 60 * 60_000L, NOW))
    }

    @Test
    fun `mas de una semana cae en fecha absoluta`() {
        val older = LibraryFormat.relativeTime(NOW - 8 * 24 * 60 * 60_000L, NOW)
        assertTrue(older is RelativeTime.Older)
        (older as RelativeTime.Older).let {
            // NOW - 8 días = 2026-08-04T10:00:00Z: la fecha absoluta del
            // timestamp antiguo (día 4), con mes abreviado español como el
            // formatDate es-ES de la web (frontend/js/dom.js).
            assertEquals(
                "4 ago",
                LibraryFormat.formatDate(
                    it.epochMillis,
                    Locale.forLanguageTag("es-ES"),
                    ZoneOffset.UTC,
                ),
            )
        }
    }

    @Test
    fun `timestamp invalido degrada a ahora mismo`() {
        assertEquals(RelativeTime.JustNow, LibraryFormat.relativeTime(0L, NOW))
    }
}

package com.explainer.app.ui.library

import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Tiempo relativo de la biblioteca (T09): la UI muestra "hace X min/h/d"
 * hasta una semana; más allá cae a fecha absoluta. Determinista: los tests
 * fijan locale y zona.
 */
sealed interface RelativeTime {
    data object JustNow : RelativeTime
    data class MinutesAgo(val minutes: Int) : RelativeTime
    data class HoursAgo(val hours: Int) : RelativeTime
    data class DaysAgo(val days: Int) : RelativeTime

    /** Más de una semana: se muestra la fecha absoluta de [epochMillis]. */
    data class Older(val epochMillis: Long) : RelativeTime
}

/**
 * Formateo utilitario de la biblioteca (T09): bytes con coma decimal,
 * rango estimado con unidad común y tiempo relativo/absoluto. Todo
 * determinista (locale/zonas fijas en tests JVM).
 */
object LibraryFormat {

    private const val BINARY_KB = 1024L
    private const val BINARY_MB = 1024L * 1024L
    private const val BINARY_GB = 1024L * 1024L * 1024L

    private const val MINUTE_MILLIS = 60_000L
    private const val HOUR_MILLIS = 60L * MINUTE_MILLIS
    private const val DAY_MILLIS = 24L * HOUR_MILLIS
    private const val WEEK_MILLIS = 7L * DAY_MILLIS

    // ---- Bytes ----

    fun formatBytes(bytes: Long): String {
        val value = bytes.coerceAtLeast(0L)
        return when {
            value < BINARY_KB -> "$value B"
            value < BINARY_MB -> formatUnit(value, BINARY_KB, "KB")
            value < BINARY_GB -> formatUnit(value, BINARY_MB, "MB")
            else -> formatUnit(value, BINARY_GB, "GB")
        }
    }

    private fun formatUnit(value: Long, unit: Long, suffix: String): String =
        "${formatUnitNumber(value, unit)} $suffix"

    private fun formatUnitNumber(value: Long, unit: Long): String =
        if (value % unit == 0L) {
            (value / unit).toString()
        } else {
            // Coma decimal explícita, independiente del locale de la JVM.
            String.format(Locale.ROOT, "%.1f", value.toDouble() / unit.toDouble())
                .replace('.', ',')
        }

    // ---- Rango estimado ----

    /**
     * Rango con unidad común compactado ("1–6 MB"); con unidades distintas
     * se conservan ambas ("512 KB – 2 MB").
     */
    fun formatRange(lowBytes: Long, highBytes: Long): String {
        val low = lowBytes.coerceAtLeast(0L)
        val high = highBytes.coerceAtLeast(0L)
        val lowUnit = unitOf(low)
        val highUnit = unitOf(high)
        return if (lowUnit == highUnit) {
            "${formatUnitNumber(low, unitBytes(lowUnit))}–${formatBytes(high)}"
        } else {
            "${formatBytes(low)} – ${formatBytes(high)}"
        }
    }

    private fun unitOf(bytes: Long): String = when {
        bytes < BINARY_KB -> "B"
        bytes < BINARY_MB -> "KB"
        bytes < BINARY_GB -> "MB"
        else -> "GB"
    }

    private fun unitBytes(unit: String): Long = when (unit) {
        "B" -> 1L
        "KB" -> BINARY_KB
        "MB" -> BINARY_MB
        else -> BINARY_GB
    }

    // ---- Tiempo relativo ----

    /**
     * Fronteras: <1 min "ahora"; <1 h minutos; <24 h horas; <=7 días días;
     * más de una semana fecha absoluta. Timestamp inválido (<=0) degrada a
     * "ahora mismo".
     */
    fun relativeTime(epochMillis: Long, nowMillis: Long): RelativeTime {
        if (epochMillis <= 0L) return RelativeTime.JustNow
        val delta = nowMillis - epochMillis
        return when {
            delta < MINUTE_MILLIS -> RelativeTime.JustNow
            delta < HOUR_MILLIS -> RelativeTime.MinutesAgo((delta / MINUTE_MILLIS).toInt())
            delta < DAY_MILLIS -> RelativeTime.HoursAgo((delta / HOUR_MILLIS).toInt())
            delta <= WEEK_MILLIS -> RelativeTime.DaysAgo((delta / DAY_MILLIS).toInt())
            else -> RelativeTime.Older(epochMillis)
        }
    }

    /** Fecha absoluta "d MMM" en el locale/zona pedidos (p. ej. "4 ago"). */
    fun formatDate(epochMillis: Long, locale: Locale, zone: ZoneOffset): String =
        DateTimeFormatter.ofPattern("d MMM", locale)
            .withZone(zone)
            .format(Instant.ofEpochMilli(epochMillis))
}

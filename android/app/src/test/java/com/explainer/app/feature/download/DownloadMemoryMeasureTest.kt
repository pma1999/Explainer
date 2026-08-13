package com.explainer.app.feature.download

import com.explainer.app.data.local.snapshot.SnapshotPreparer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Medición del pico de memoria del detalle parseado (R-T06-07, cross-task
 * T03): el body se transmite a fichero (T04), pero la preparación de T03
 * (`RoomSnapshotStore.prepare` → `source.readText` + `SnapshotPreparer` →
 * `decodeFromString<ProjectDetailDto>`) materializa el detalle COMPLETO como
 * String y árbol decodificado antes de particionarlo. Este test mide, para un
 * payload grande, el tamaño del detalle parseado (wire, String del body,
 * partes re-encodificadas) y documenta la relación pico/wire observada.
 *
 * El arreglo (parseo streaming o estrategia acotada) es decisión de
 * integración T03: NO se toca aquí; esta medición queda como nota para la
 * decisión (véase reporte T06, R-T06-07).
 */
class DownloadMemoryMeasureTest {

    @Test
    fun `prepare of a large detail keeps the parsed peak measured and bounded`() {
        val partCount = 8
        val partContentChars = 512 * 1024 // 512 KiB de contenido por parte
        val detail = buildDetailJson(partCount, partContentChars)

        val wireBytes = detail.toByteArray(Charsets.UTF_8).size
        val bodyChars = detail.length // Pico 1: el body completo como String

        val prepared = SnapshotPreparer.prepare(TEST_OWNER_A, detail)

        assertEquals(partCount, prepared.parts.size)
        // Pico 2: el detalle decodificado + la re-encodificación por parte.
        val partsJsonChars = prepared.parts.sumOf { it.contentJson.length }
        val partsBytes = prepared.parts.sumOf { it.contentBytes }

        // Modelo del pico: String del body (chars) + copia wire + árbol de
        // partes re-encodificado (chars) + bytes UTF-8 de las partes.
        val peakEstimate = bodyChars.toLong() + wireBytes + partsJsonChars + partsBytes
        val ratio = peakEstimate.toDouble() / wireBytes

        // Documenta la relación observada para la decisión de integración.
        println(
            "MEMORY-MEASURE parts=$partCount wire=${wireBytes}B bodyChars=${bodyChars} " +
                "partsJsonChars=${partsJsonChars} partsBytes=${partsBytes} " +
                "peakEstimate=${peakEstimate}B ratio=${"%.2f".format(ratio)}x",
        )

        assertTrue("el payload debe ser grande para que la medición sea relevante", wireBytes > 1_000_000)
        assertTrue(
            "pico estimado acotado (<= 8x wire); ratio observado ${"%.2f".format(ratio)}x",
            peakEstimate <= wireBytes * 8,
        )
    }

    private fun buildDetailJson(partCount: Int, partContentChars: Int): String {
        val sb = StringBuilder()
        sb.append("""{"id":"${TEST_PROJECT_ID.value}","name":"Detalle grande","status":"completed","source_type":"pdf",""")
        sb.append(""" "segmentation":{"partes":[""")
        sb.append(
            (1..partCount).joinToString(",") { n ->
                """{"numero":$n,"titulo":"Parte $n","contenido":"${"c".repeat(4096)}"}"""
            },
        )
        sb.append(""" ]},"partes_contenido":{""")
        sb.append(
            (1..partCount).joinToString(",") { n ->
                """"${n}":{"status":"completed","contenido":"${"x".repeat(partContentChars)}"}"""
            },
        )
        sb.append(""" },"updated_at":"2026-08-01T00:00:00Z"}""")
        return sb.toString()
    }
}

package com.explainer.app.ui.content.mermaid

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

/**
 * Ensamblador de trozos del PNG exportado (canal de chunks T-EXPORT): valida
 * el contrato del transporte — offsets contiguos desde 0, trozos dentro del
 * tamaño declarado, longitud total exacta y prefijo `data:image/png;base64,`
 * — y recompone el data URL completo con base64 sintético de varios MB.
 */
class MermaidPngChunkAssemblerTest {

    /** Data URL PNG sintético: prefijo + base64 de [payloadBytes] bytes. */
    private fun syntheticPngDataUrl(payloadBytes: Int): String {
        val payload = ByteArray(payloadBytes) { (it % 251).toByte() }
        return MermaidPngChunkAssembler.PNG_DATA_URL_PREFIX + Base64.getEncoder().encodeToString(payload)
    }

    private fun chunk(dataUrl: String, from: Int, chunkSize: Int): String =
        dataUrl.substring(from, minOf(from + chunkSize, dataUrl.length))

    @Test
    fun `ensambla trozos contiguos hasta la longitud declarada`() {
        val dataUrl = syntheticPngDataUrl(1_500_000) // ~2 MB de base64
        val chunkSize = 32_768
        val assembler = MermaidPngChunkAssembler("e1", dataUrl.length, chunkSize)
        var offset = 0
        while (!assembler.isComplete) {
            val c = chunk(dataUrl, offset, chunkSize)
            assertTrue(assembler.accept(c, offset))
            offset += c.length
        }
        assertEquals(dataUrl, assembler.assembledDataUrl())
        assertNull(assembler.error)
    }

    @Test
    fun `rechaza offsets duplicados o desordenados`() {
        val dataUrl = syntheticPngDataUrl(100_000)
        val assembler = MermaidPngChunkAssembler("e1", dataUrl.length, 32_768)
        assertTrue(assembler.accept(chunk(dataUrl, 0, 32_768), 0))
        assertFalse(
            "el offset anterior no puede repetirse",
            assembler.accept(chunk(dataUrl, 0, 32_768), 0),
        )
        assertNotNull(assembler.error)
        assertNull("abortado: sin data URL", assembler.assembledDataUrl())
    }

    @Test
    fun `rechaza longitud incompleta`() {
        val dataUrl = syntheticPngDataUrl(100_000)
        val assembler = MermaidPngChunkAssembler("e1", dataUrl.length, 32_768)
        assertTrue(assembler.accept(chunk(dataUrl, 0, 32_768), 0))
        assertFalse(assembler.isComplete)
        assertNull("sin la longitud total no hay data URL", assembler.assembledDataUrl())
        assertNotNull(assembler.error)
    }

    @Test
    fun `rechaza chunks que exceden la longitud declarada`() {
        val assembler = MermaidPngChunkAssembler("e1", totalLength = 10, chunkSize = 1000)
        assertFalse(assembler.accept("data:image/png;base64,abcdefghij", 0))
        assertNotNull(assembler.error)
    }

    @Test
    fun `rechaza trozos mayores que el tamano declarado`() {
        val dataUrl = syntheticPngDataUrl(50_000)
        val assembler = MermaidPngChunkAssembler("e1", dataUrl.length, 32_768)
        assertTrue(assembler.accept(chunk(dataUrl, 0, 32_768), 0))
        // Trozo con más caracteres que chunkSize.
        assertFalse(assembler.accept("data:image/png;base64," + "a".repeat(40_000), 32_768))
        assertNotNull(assembler.error)
    }

    @Test
    fun `rechaza primer chunk sin prefijo de data url png`() {
        val assembler = MermaidPngChunkAssembler("e1", totalLength = 10, chunkSize = 1000)
        assertFalse(assembler.accept("noprefix", 0))
        assertNotNull(assembler.error)
    }

    @Test
    fun `rechaza null (fin de canal) antes de completar`() {
        val dataUrl = syntheticPngDataUrl(100_000)
        val assembler = MermaidPngChunkAssembler("e1", dataUrl.length, 32_768)
        assertTrue(assembler.accept(chunk(dataUrl, 0, 32_768), 0))
        assertFalse(assembler.accept(null, 32_768))
        assertNotNull(assembler.error)
    }

    @Test
    fun `rechaza metadatos invalidos`() {
        val assembler = MermaidPngChunkAssembler("e1", totalLength = 0, chunkSize = 32_768)
        assertFalse(assembler.accept("data:image/png;base64,abc", 0))
        assertNotNull(assembler.error)
    }
}

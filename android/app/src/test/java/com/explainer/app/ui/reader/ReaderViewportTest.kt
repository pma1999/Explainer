package com.explainer.app.ui.reader

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Zona de lectura activa (T10): banda 35–45 % del viewport con selección por
 * máximo solapamiento y empate al índice menor (paridad web
 * `initSubsectionObserver`). Puro, sin Android.
 */
class ReaderViewportTest {

    private fun item(index: Int, offset: Int, size: Int = 40) =
        ReaderViewport.TrackedItem(index = index, offset = offset, size = size)

    @Test
    fun `heading dentro de la banda es el activo`() {
        // viewport 1000px → banda [350, 450]
        assertEquals(1, ReaderViewport.activeTrackedIndex(listOf(item(1, 360, 40)), viewportHeight = 1000))
    }

    @Test
    fun `heading por encima de la banda no activa`() {
        assertEquals(null, ReaderViewport.activeTrackedIndex(listOf(item(0, 300, 40)), viewportHeight = 1000))
    }

    @Test
    fun `heading por debajo de la banda no activa`() {
        assertEquals(null, ReaderViewport.activeTrackedIndex(listOf(item(2, 460, 40)), viewportHeight = 1000))
    }

    @Test
    fun `heading que cruza el borde superior de la banda cuenta como activo`() {
        // bottom = 370 > bandTop 350 → intersecta
        assertEquals(0, ReaderViewport.activeTrackedIndex(listOf(item(0, 330, 40)), viewportHeight = 1000))
    }

    @Test
    fun `mayor solapamiento gana`() {
        // A solapa [350,390] = 40px; B solapa [390,450] = 60px → gana B
        val active = ReaderViewport.activeTrackedIndex(
            listOf(item(0, 340, 60), item(1, 380, 80)),
            viewportHeight = 1000,
        )
        assertEquals(1, active)
    }

    @Test
    fun `empate de solapamiento gana el indice menor`() {
        val active = ReaderViewport.activeTrackedIndex(
            listOf(item(5, 350, 40), item(2, 410, 40)),
            viewportHeight = 1000,
        )
        assertEquals(2, active)
    }

    @Test
    fun `sin items o viewport nulo devuelve null`() {
        assertNull(ReaderViewport.activeTrackedIndex(emptyList(), viewportHeight = 1000))
        assertNull(ReaderViewport.activeTrackedIndex(listOf(item(1, 360, 40)), viewportHeight = 0))
        assertNull(ReaderViewport.activeTrackedIndex(listOf(item(1, 360, 40)), viewportHeight = -1))
    }

    @Test
    fun `banda configurable respeta el contrato 35-45`() {
        assertEquals(0.35f, ReaderViewport.BAND_TOP_RATIO, 0f)
        assertEquals(0.45f, ReaderViewport.BAND_BOTTOM_RATIO, 0f)
    }
}

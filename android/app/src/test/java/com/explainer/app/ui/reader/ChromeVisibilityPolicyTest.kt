package com.explainer.app.ui.reader

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Política de visibilidad del chrome superior (lectura-first): zona muerta
 * + histéresis, fling decidido por velocidad y guardias de contenido corto
 * y posición arriba del todo. Puro, sin Android.
 */
class ChromeVisibilityPolicyTest {

    /** Atajo con los defaults del lector: gesto sin velocidad y lista con contenido. */
    private fun decide(
        previous: ChromeVisibilityPolicy.State = ChromeVisibilityPolicy.State(),
        deltaDp: Float,
        velocityDpPerSec: Float = 0f,
        canScrollForward: Boolean = true,
        atTop: Boolean = false,
    ) = ChromeVisibilityPolicy.decide(
        previous = previous,
        deltaDp = deltaDp,
        velocityDpPerSec = velocityDpPerSec,
        canScrollForward = canScrollForward,
        atTop = atTop,
    )

    // ─── Zona muerta ────────────────────────────────────────────────────────

    @Test
    fun `delta por debajo del umbral no cambia el estado`() {
        val down = decide(deltaDp = 10f)
        assertTrue(down.visible)
        assertEquals(10f, down.accumulatedDp, 0f)

        val up = decide(deltaDp = -8f)
        assertTrue(up.visible)
        assertEquals(-8f, up.accumulatedDp, 0f)
    }

    @Test
    fun `acumulacion hacia abajo cruza el umbral y oculta`() {
        var state = decide(deltaDp = 10f)
        state = decide(state, deltaDp = 10f) // 20 < 24: zona muerta
        assertTrue(state.visible)
        state = decide(state, deltaDp = 5f) // 25 ≥ 24: oculta
        assertFalse(state.visible)
    }

    @Test
    fun `acumulacion hacia arriba cruza el umbral y muestra`() {
        var state = ChromeVisibilityPolicy.State(visible = false)
        state = decide(state, deltaDp = -10f)
        assertFalse(state.visible)
        state = decide(state, deltaDp = -8f) // -18 ≤ -16: muestra
        assertTrue(state.visible)
    }

    // ─── Histéresis ─────────────────────────────────────────────────────────

    @Test
    fun `ráfaga de rebote no toglea repetidamente`() {
        // Baja 24dp: oculta.
        var state = decide(deltaDp = 24f)
        assertFalse(state.visible)
        // Rebote corto hacia arriba: 10dp < 16dp de umbral, no muestra.
        state = decide(state, deltaDp = -10f)
        assertFalse(state.visible)
        // Vuelve a bajar: sigue oculto (nunca re-oculta lo ya oculto).
        state = decide(state, deltaDp = 20f)
        assertFalse(state.visible)
        // Sube 16dp netos desde la inversión: muestra.
        state = decide(state, deltaDp = -16f)
        assertTrue(state.visible)
    }

    @Test
    fun `invertir la direccion reinicia el acumulador de zona muerta`() {
        // 20dp hacia abajo no oculta; un rebote de 4dp hacia arriba no debe
        // arrastrar el recorrido anterior como si fueran 16dp netos.
        var state = decide(deltaDp = 20f)
        state = decide(state, deltaDp = -4f)
        assertTrue(state.visible)
        assertEquals(-4f, state.accumulatedDp, 0f)
    }

    @Test
    fun `el estado oculto se mantiene mientras la acumulacion no cruza hacia arriba`() {
        var state = ChromeVisibilityPolicy.State(visible = false, accumulatedDp = 40f)
        state = decide(state, deltaDp = 10f) // sigue bajando: sigue oculto
        assertFalse(state.visible)
        assertEquals(50f, state.accumulatedDp, 0f)
    }

    // ─── Guardias: contenido corto y arriba del todo ────────────────────────

    @Test
    fun `contenido corto mantiene el chrome siempre visible`() {
        var state = decide(deltaDp = 24f, canScrollForward = false)
        assertTrue(state.visible)
        // Ni siquiera un fling fuerte hacia abajo lo oculta.
        state = decide(state, deltaDp = 24f, velocityDpPerSec = 5000f, canScrollForward = false)
        assertTrue(state.visible)
        assertEquals(0f, state.accumulatedDp, 0f)
    }

    @Test
    fun `arriba del todo fuerza el chrome visible y limpia el acumulador`() {
        var state = ChromeVisibilityPolicy.State(visible = false, accumulatedDp = -40f)
        state = decide(state, deltaDp = 10f, atTop = true)
        assertTrue(state.visible)
        assertEquals(0f, state.accumulatedDp, 0f)
    }

    // ─── Velocidad: el fling gana a la zona muerta ──────────────────────────

    @Test
    fun `fling fuerte hacia abajo oculta de inmediato con delta pequeño`() {
        val state = decide(deltaDp = 2f, velocityDpPerSec = 3000f)
        assertFalse(state.visible)
    }

    @Test
    fun `fling fuerte hacia arriba muestra de inmediato con delta pequeño`() {
        val state = decide(
            previous = ChromeVisibilityPolicy.State(visible = false),
            deltaDp = -2f,
            velocityDpPerSec = -3000f,
        )
        assertTrue(state.visible)
    }

    @Test
    fun `velocidad moderada no gana a la zona muerta`() {
        val state = decide(deltaDp = 10f, velocityDpPerSec = 1200f)
        assertTrue(state.visible)
        assertEquals(10f, state.accumulatedDp, 0f)
    }

    @Test
    fun `velocidad nula en reposo no dispara nada`() {
        var state = decide(deltaDp = 5f)
        state = decide(state, deltaDp = 0f, velocityDpPerSec = 0f)
        assertTrue(state.visible)
        assertEquals(5f, state.accumulatedDp, 0f)
    }

    // ─── Contrato de diseño ─────────────────────────────────────────────────

    @Test
    fun `umbrales de diseño, ocultar 24dp, mostrar 16dp y flings decididos`() {
        assertEquals(24f, ChromeVisibilityPolicy.HideThresholdDp, 0f)
        assertEquals(16f, ChromeVisibilityPolicy.ShowThresholdDp, 0f)
        assertEquals(2500f, ChromeVisibilityPolicy.HideFlingVelocityDpPerSec, 0f)
        assertEquals(2000f, ChromeVisibilityPolicy.ShowFlingVelocityDpPerSec, 0f)
    }

    @Test
    fun `el estado inicial del detector es chrome visible y zona muerta vacia`() {
        val initial = ChromeVisibilityPolicy.State()
        assertTrue(initial.visible)
        assertEquals(0f, initial.accumulatedDp, 0f)
    }
}

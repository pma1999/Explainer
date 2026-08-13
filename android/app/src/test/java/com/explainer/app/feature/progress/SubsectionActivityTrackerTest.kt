package com.explainer.app.feature.progress

import com.explainer.app.core.model.ReaderTab
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Aceptación del tracker puro de actividad de subsecciones (paridad web
 * `frontend/js/main.js` setActiveSubsection/maybeMarkSubsectionRead):
 * - last-read al activar una subsección (evento inmediato).
 * - completed cuando la subsección acumula >= 3000 ms de visita al SALIR.
 * - Visitas no contiguas suman (el acumulador es por id, como en la web).
 * - Reactivar el mismo id no emite nada (sigue acumulando).
 * T10 decide qué viewport events alimentan activate/finish.
 */
class SubsectionActivityTrackerTest {

    private val tab = ReaderTab.EXPLANATION

    @Test
    fun `activate emite last-read de la nueva subseccion`() {
        val tracker = SubsectionActivityTracker()
        val events = tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 100L)
        assertEquals(
            listOf(SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-a-0", tab = tab, isLastRead = true)),
            events,
        )
    }

    @Test
    fun `cambiar de subseccion emite completed cuando acumulo 3000 ms`() {
        val tracker = SubsectionActivityTracker()
        tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 0L)
        val events = tracker.activate("subsec-1-b-1", partId = 1, tab = tab, now = 3_000L)
        assertEquals(
            listOf(
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-a-0", tab = tab, completed = true),
                SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-b-1", tab = tab, isLastRead = true),
            ),
            events,
        )
    }

    @Test
    fun `visitas no contiguas suman acumulado y completan al superar el umbral`() {
        val tracker = SubsectionActivityTracker()
        tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 0L)
        // Sale a los 1000 ms: no llega al umbral.
        var events = tracker.activate("subsec-1-b-1", partId = 1, tab = tab, now = 1_000L)
        assertEquals(
            listOf(SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-b-1", tab = tab, isLastRead = true)),
            events,
        )
        // Vuelve a "a" a los 2000: b acumula 1000 (no completa) y a lleva 1000+1000.
        events = tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 2_000L)
        assertEquals(
            listOf(SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-a-0", tab = tab, isLastRead = true)),
            events,
        )
        // finish a los 4000: a acumula 2000+2000 = 4000 >= 3000 -> completed.
        events = tracker.finish(now = 4_000L)
        assertEquals(
            listOf(SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-a-0", tab = tab, completed = true)),
            events,
        )
    }

    @Test
    fun `reactivar el mismo id no emite nada y sigue acumulando`() {
        val tracker = SubsectionActivityTracker()
        tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 0L)
        assertTrue(tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 1_000L).isEmpty())
        val events = tracker.finish(now = 3_000L)
        assertEquals(
            listOf(SubsectionProgressEvent(partId = 1, subsectionId = "subsec-1-a-0", tab = tab, completed = true)),
            events,
        )
    }

    @Test
    fun `finish antes del umbral no emite completed`() {
        val tracker = SubsectionActivityTracker()
        tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 0L)
        assertTrue(tracker.finish(now = 2_999L).isEmpty())
    }

    @Test
    fun `umbral exacto de 3000 ms completa al salir`() {
        val tracker = SubsectionActivityTracker()
        tracker.activate("subsec-1-a-0", partId = 1, tab = tab, now = 0L)
        val events = tracker.finish(now = 3_000L)
        assertEquals(1, events.size)
        assertEquals(true, events.single().completed)
    }

    @Test
    fun `finish sin subseccion activa no emite nada`() {
        val tracker = SubsectionActivityTracker()
        assertTrue(tracker.finish(now = 5_000L).isEmpty())
    }

    @Test
    fun `completed lleva el part y tab donde vivia la subseccion`() {
        val tracker = SubsectionActivityTracker()
        tracker.activate("subsec-2-a-0", partId = 2, tab = ReaderTab.WALKTHROUGH, now = 0L)
        val events = tracker.activate("subsec-3-b-0", partId = 3, tab = ReaderTab.EXPLANATION, now = 3_000L)
        val completed = events.first { it.completed == true }
        assertEquals(2, completed.partId)
        assertEquals(ReaderTab.WALKTHROUGH, completed.tab)
    }
}

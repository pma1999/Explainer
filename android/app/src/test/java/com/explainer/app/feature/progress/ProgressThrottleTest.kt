package com.explainer.app.feature.progress

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * R-T07-09: el intervalo mínimo de 60 s es un rate-limit de red separado por
 * owner (el flush de A nunca retrasa la cola de B) y no durable a propósito
 * (un reinicio del proceso solo permite un flush antes de tiempo, nunca
 * pérdida: la cola durable sigue intacta).
 */
class ProgressThrottleTest {

    @Test
    fun `el reloj del intervalo es independiente por owner`() {
        val now = 100_000L
        val throttle = ProgressThrottle { now }
        throttle.recordFlush("owner-a", now)

        assertEquals(60_000L, throttle.remainingToMinInterval("owner-a", 60_000L))
        assertEquals(0L, throttle.remainingToMinInterval("owner-b", 60_000L))
    }

    @Test
    fun `tras reinicio del proceso el throttle permite flush inmediato`() {
        val before = ProgressThrottle { 100_000L }
        before.recordFlush("owner-a", 100_000L)
        assertEquals(100_000L, before.lastFlushAtMillis("owner-a"))

        // "Reinicio": una instancia nueva no conserva el reloj (rate-limit,
        // no garantía durable; la cola Room persiste y no se pierde intención).
        val afterRestart = ProgressThrottle { 100_000L }
        assertEquals(0L, afterRestart.remainingToMinInterval("owner-a", 60_000L))
        assertEquals(0L, afterRestart.lastFlushAtMillis("owner-a"))
    }

    @Test
    fun `sin flush previo el intervalo restante es cero`() {
        val throttle = ProgressThrottle { 1_000_000L }
        assertEquals(0L, throttle.remainingToMinInterval("owner-a", 60_000L))
    }
}

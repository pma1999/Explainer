package com.explainer.app.feature.download

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProgressThrottlerTest {

    private class Clock(var now: Long = 0L) {
        fun tick(millis: Long) {
            now += millis
        }
    }

    @Test
    fun `first emission always forwards`() {
        val clock = Clock()
        val throttler = ProgressThrottler { clock.now }
        assertTrue(throttler.forward(100L))
    }

    @Test
    fun `emissions cap at 4 Hz`() {
        val clock = Clock()
        val throttler = ProgressThrottler { clock.now }
        assertTrue(throttler.forward(100L))

        clock.tick(100)
        assertFalse("antes de 250 ms no emite", throttler.forward(200L))

        clock.tick(150)
        assertTrue("a los 250 ms emite", throttler.forward(300L))

        clock.tick(249)
        assertFalse(throttler.forward(400L))

        clock.tick(1)
        assertTrue(throttler.forward(500L))
    }

    @Test
    fun `emissions cap at 256 KiB even with a frozen clock`() {
        val clock = Clock()
        val throttler = ProgressThrottler { clock.now }
        val kiB = 1024L

        assertTrue(throttler.forward(64 * kiB))
        assertFalse("192 KiB acumulados no alcanzan", throttler.forward(192 * kiB))
        assertFalse(throttler.forward(256 * kiB))
        assertTrue("256 KiB desde la última emisión", throttler.forward(320 * kiB))
    }

    @Test
    fun `time and bytes combine so either threshold forwards`() {
        val clock = Clock()
        val throttler = ProgressThrottler { clock.now }
        val kiB = 1024L

        assertTrue(throttler.forward(64 * kiB))
        clock.tick(300) // tiempo transcurrido aunque los bytes apenas crecieron
        assertTrue(throttler.forward(66 * kiB))
    }
}

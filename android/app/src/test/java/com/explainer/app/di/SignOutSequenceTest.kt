package com.explainer.app.di

import com.explainer.app.feature.download.TEST_OWNER_A
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * R-T11-02 (CRITICAL): el logout explícito es resistente a cancelación y su
 * ownership vive en el scope del CONTAINER, no en el de composición (que se
 * desmonta al publicar `SignedOut`). El lock del owner local ocurre ANTES de
 * publicar `SignedOut` y la cancelación del caller en cualquier punto de la
 * secuencia nunca lo pierde.
 */
class SignOutSequenceTest {

    private fun sequence(
        scope: CoroutineScope,
        events: MutableList<String>,
        currentOwner: () -> String? = { TEST_OWNER_A },
    ) = SignOutSequence(
        scope = scope,
        currentOwner = currentOwner,
        cancelRemoteSync = { owner -> events.add("cancel:$owner") },
        lockLocalAccess = { events.add("lock") },
        signOut = { events.add("signOut") },
    )

    @Test
    fun `secuencia completa ejecuta cancel lock y signOut en orden`() = runBlocking {
        val events = mutableListOf<String>()
        val seq = sequence(CoroutineScope(SupervisorJob() + Dispatchers.Unconfined), events)

        seq.run()

        assertEquals(listOf("cancel:$TEST_OWNER_A", "lock", "signOut"), events)
    }

    @Test
    fun `el lock ocurre antes del signOut que publica SignedOut`() = runBlocking {
        val events = mutableListOf<String>()
        val seq = sequence(CoroutineScope(SupervisorJob() + Dispatchers.Unconfined), events)

        seq.run()

        assertEquals("lock", events[1])
        assertEquals("signOut", events[2])
    }

    @Test
    fun `sin owner salta el cancel remoto pero lock y signOut ocurren`() = runBlocking {
        val events = mutableListOf<String>()
        val seq = sequence(
            CoroutineScope(SupervisorJob() + Dispatchers.Unconfined),
            events,
            currentOwner = { null },
        )

        seq.run()

        assertEquals(listOf("lock", "signOut"), events)
    }

    @Test
    fun `cancelacion del caller entre signOut y lock no pierde el lock`() = runBlocking {
        // Escenario del review: el caller vive en el scope de composición y
        // se desmonta en cuanto `signOut()` publica `SignedOut`. La secuencia
        // corre en el scope del container; el lock ya ocurrió ANTES y la
        // cancelación del caller no lo revierte.
        val events = mutableListOf<String>()
        val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val seq = sequence(appScope, events)
        lateinit var callerJob: Job

        callerJob = launch(Dispatchers.Unconfined) {
            seq.run()
        }
        // El signOut simula publicar SignedOut: la UI se desmonta y cancela
        // al caller en el punto exacto de la secuencia.
        withTimeout(2_000) {
            while (events.count { it == "signOut" } == 0) delay(1)
        }
        callerJob.cancel()
        callerJob.join()

        assertEquals(listOf("cancel:$TEST_OWNER_A", "lock", "signOut"), events)
        assertEquals(1, events.count { it == "lock" })
    }

    @Test
    fun `cancelacion del caller mientras la secuencia suspende no interrumpe el lock`() = runBlocking {
        // El caller se cancela en mitad de la secuencia (antes del lock):
        // la corrutina del container continúa y completa lock + signOut.
        val events = mutableListOf<String>()
        val started = CompletableDeferred<Unit>()
        val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val seq = SignOutSequence(
            scope = appScope,
            currentOwner = { TEST_OWNER_A },
            cancelRemoteSync = {
                started.complete(Unit)
                delay(50) // ventana de cancelación del caller
            },
            lockLocalAccess = { events.add("lock") },
            signOut = { events.add("signOut") },
        )
        val callerJob = launch(Dispatchers.Unconfined) { seq.run() }

        started.await()
        callerJob.cancel()
        callerJob.join()

        withTimeout(2_000) { while (events.isEmpty()) delay(5) }
        assertEquals(listOf("lock", "signOut"), events)
        assertEquals(1, events.count { it == "lock" })
    }
}

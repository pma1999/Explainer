package com.explainer.app.work

import androidx.work.Data
import androidx.work.ListenableWorker.Result
import androidx.work.workDataOf
import com.explainer.app.core.model.ProjectId
import com.explainer.app.feature.download.DownloadError
import com.explainer.app.feature.download.DownloadOutcome
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Política del Worker testeable en JVM (sin instanciar WorkManager): parseo
 * del input (solo IDs pequeños en `Data`) y traducción del outcome del motor
 * a `Result`.
 */
class DownloadWorkerPolicyTest {

    private val projectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f")
    private val ownerId = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    @Test
    fun `parse input reads both small keys`() {
        val input = DownloadWorkerPolicy.parseInput(
            workDataOf(
                DownloadProjectWorker.KEY_OWNER_ID to ownerId,
                DownloadProjectWorker.KEY_PROJECT_ID to projectId.value,
            ),
        )
        assertNotNull(input)
        assertEquals(ownerId, input?.ownerId)
        assertEquals(projectId, input?.projectId)
    }

    @Test
    fun `parse input rejects missing or malformed keys`() {
        assertNull(DownloadWorkerPolicy.parseInput(Data.EMPTY))
        assertNull(DownloadWorkerPolicy.parseInput(workDataOf(DownloadProjectWorker.KEY_OWNER_ID to ownerId)))
        assertNull(
            DownloadWorkerPolicy.parseInput(
                workDataOf(
                    DownloadProjectWorker.KEY_OWNER_ID to ownerId,
                    DownloadProjectWorker.KEY_PROJECT_ID to "no-es-uuid",
                ),
            ),
        )
    }

    @Test
    fun `result mapping never retries cancelled`() {
        assertEquals(Result.success(), DownloadWorkerPolicy.resultFor(DownloadOutcome.Succeeded))
        assertEquals(Result.success(), DownloadWorkerPolicy.resultFor(DownloadOutcome.Cancelled))
        assertEquals(Result.retry(), DownloadWorkerPolicy.resultFor(DownloadOutcome.Retryable))
        assertEquals(
            Result.failure(),
            DownloadWorkerPolicy.resultFor(DownloadOutcome.Failed(DownloadError.Network)),
        )
        assertEquals(
            Result.failure(),
            DownloadWorkerPolicy.resultFor(DownloadOutcome.Failed(DownloadError.AuthRequired)),
        )
    }
}

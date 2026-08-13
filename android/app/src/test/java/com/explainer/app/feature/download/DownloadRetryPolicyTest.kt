package com.explainer.app.feature.download

import com.explainer.app.data.remote.contract.RemoteResult
import org.junit.Assert.assertEquals
import org.junit.Test

class DownloadRetryPolicyTest {

    @Test
    fun `network and rate limited retry up to the fifth attempt`() {
        for (attempt in 1..4) {
            assertEquals("intento $attempt", RetryDecision.Retry, DownloadRetryPolicy.classify(RemoteResult.Retryable, attempt))
            assertEquals("intento $attempt", RetryDecision.Retry, DownloadRetryPolicy.classify(RemoteResult.RateLimited, attempt))
        }
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.Retryable, 5))
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.RateLimited, 5))
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.Retryable, 6))
    }

    @Test
    fun `cancellation never retries`() {
        assertEquals(RetryDecision.Cancel, DownloadRetryPolicy.classify(RemoteResult.Cancelled, 1))
        assertEquals(RetryDecision.Cancel, DownloadRetryPolicy.classify(RemoteResult.Cancelled, 5))
    }

    @Test
    fun `4xx permanent, 404 and auth are permanent`() {
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.PermanentFailure("http:400"), 1))
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.NotFound, 1))
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.AuthRequired, 1))
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.InvalidPayload("json"), 1))
        assertEquals(RetryDecision.GiveUp, DownloadRetryPolicy.classify(RemoteResult.Success(Unit), 1))
    }

    @Test
    fun `backoff series starts at 30 s and doubles`() {
        assertEquals(30_000L, DownloadRetryPolicy.backoffMillis(1))
        assertEquals(60_000L, DownloadRetryPolicy.backoffMillis(2))
        assertEquals(120_000L, DownloadRetryPolicy.backoffMillis(3))
        assertEquals(240_000L, DownloadRetryPolicy.backoffMillis(4))
        assertEquals(480_000L, DownloadRetryPolicy.backoffMillis(5))
    }

    @Test
    fun `backoff saturates at the cap`() {
        assertEquals(DownloadRetryPolicy.MAX_BACKOFF_MILLIS, DownloadRetryPolicy.backoffMillis(99))
        assertEquals(30_000L, DownloadRetryPolicy.backoffMillis(0))
    }
}

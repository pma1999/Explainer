package com.explainer.app.feature.download

import com.explainer.app.data.remote.contract.RemoteResult

/**
 * Clasificador puro de reintentos (global-constraints.md): red/timeout/429 y
 * 5xx ([RemoteResult.Retryable]/[RemoteResult.RateLimited]) se reintentan con
 * backoff exponencial desde 30 s y máximo cinco intentos; 400/403/4xx y 404
 * son permanentes; 401 ya refrescado ([RemoteResult.AuthRequired]) exige
 * login; cancelación nunca reintenta.
 *
 * El backoff real lo aplica WorkManager (`BackoffPolicy.EXPONENTIAL`, 30 s)
 * configurado en el request; [backoffMillis] expone la misma serie para
 * tests/información y satura para no desbordar.
 */
sealed interface RetryDecision {
    /** Reintentar (solo si `attempt < MAX_ATTEMPTS`). */
    data object Retry : RetryDecision

    /** Fallo definitivo: no hay reintento posible. */
    data object GiveUp : RetryDecision

    /** Cancelación: terminar como cancelado, sin reintento. */
    data object Cancel : RetryDecision
}

object DownloadRetryPolicy {

    /** Intentos máximos (1-based); el quinto es final. */
    const val MAX_ATTEMPTS: Int = 5

    /** Backoff inicial: 30 s (WorkManager aplica la serie exponencial). */
    const val INITIAL_BACKOFF_MILLIS: Long = 30_000L

    /** Techo de la serie (30 s * 2^7) para no desbordar. */
    const val MAX_BACKOFF_MILLIS: Long = 3_840_000L

    fun classify(result: RemoteResult<*>, attempt: Int): RetryDecision = when (result) {
        is RemoteResult.Cancelled -> RetryDecision.Cancel
        is RemoteResult.Retryable, is RemoteResult.RateLimited ->
            if (attempt in 1 until MAX_ATTEMPTS) RetryDecision.Retry else RetryDecision.GiveUp
        // AuthRequired/NotFound/InvalidPayload/PermanentFailure (y Success, no
        // invocado) son definitivos.
        else -> RetryDecision.GiveUp
    }

    /** Serie exponencial 30 s, 60 s, 120 s, ... saturada. */
    fun backoffMillis(attempt: Int): Long {
        val shift = (attempt - 1).coerceIn(0, 7)
        return minOf(MAX_BACKOFF_MILLIS, INITIAL_BACKOFF_MILLIS shl shift)
    }
}

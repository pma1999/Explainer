package com.explainer.app.feature.catalog

/**
 * Resultado tipado del refresh del catálogo (categorías seguras, sin body ni
 * JWT). Un refresh fallido o parcial NUNCA borra summaries ni snapshots.
 */
sealed interface RefreshOutcome {
    /** Lista remota procesada; `projectCount` es lo que devolvió el server. */
    data class Success(val projectCount: Int) : RefreshOutcome

    /** 401 definitivo (refresh fallido): acceso remoto inválido, datos locales intactos. */
    data object AuthRequired : RefreshOutcome

    /** 404 de la lista: remoto no disponible; catálogo local conservado. */
    data object NotFound : RefreshOutcome

    data object RateLimited : RefreshOutcome

    /** Red caída/timeout/5xx: reintentable por la UI. */
    data object Retryable : RefreshOutcome

    /** Payload no decodificable como lista. */
    data object InvalidPayload : RefreshOutcome

    data object Cancelled : RefreshOutcome

    data class PermanentFailure(val reason: String) : RefreshOutcome
}

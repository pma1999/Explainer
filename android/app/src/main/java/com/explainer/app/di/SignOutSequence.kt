package com.explainer.app.di

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * Secuencia de logout explícito resistente a cancelación (R-T11-02).
 *
 * El problema que resuelve: la UI ejecuta el logout desde el scope de
 * composición, que se desmonta en cuanto la sesión publica `SignedOut`. Si la
 * cancelación llega entre `signOut()` y el lock local, el owner queda
 * desbloqueado y "continuar offline" seguiría disponible tras un logout
 * explícito.
 *
 * Garantías:
 * - Ownership en el scope del CONTAINER: [run] lanza el trabajo en [scope] y
 *   espera con `join()`; la cancelación del caller no propaga al trabajo (el
 *   scope es independiente del de composición) y la secuencia se completa.
 * - El lock ocurre ANTES de `signOut()` (que es lo que publica `SignedOut`):
 *   incluso si una cancelación aterrizara en el punto exacto, el owner nunca
 *   queda desbloqueado tras un logout explícito.
 * - Sin owner de sesión no hay sync remota que cancelar; el lock y el
 *   sign-out se ejecutan igualmente.
 */
internal class SignOutSequence(
    private val scope: CoroutineScope,
    private val currentOwner: () -> String?,
    private val cancelRemoteSync: suspend (ownerId: String) -> Unit,
    private val lockLocalAccess: suspend () -> Unit,
    private val signOut: suspend () -> Unit,
) {
    suspend fun run() {
        scope.launch {
            currentOwner()?.let { cancelRemoteSync(it) }
            lockLocalAccess()
            signOut()
        }.join()
    }
}

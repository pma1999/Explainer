package com.explainer.app.ui.rootstate

import com.explainer.app.data.auth.SessionState

/**
 * Reducer puro del estado raíz (T11).
 *
 * Reglas de aislamiento (global-constraints.md Auth):
 * - El owner proviene únicamente de `SessionGateway`; la UI nunca lo recibe
 *   como argumento de ruta.
 * - `OfflineAvailable` entra SOLO al owner cuyo acceso local fue desbloqueado
 *   por un login exitoso previo ([LocalAccessPreferences]); una sesión
 *   conservada de otro owner degrada a [RootAppState.SignedOut] sin exponer
 *   owners dormidos.
 * - `Authenticated` siempre pasa: la sesión es válida y todo acceso local se
 *   particiona por `ownerId` en Room/WorkManager/archivos.
 * - Un logout explícito borra el flag de acceso (no los snapshots); la caída
 *   automática de red nunca se interpreta como logout.
 */
object RootAppStateReducer {

    fun reduce(session: SessionState, unlockedOwnerId: String?): RootAppState = when (session) {
        SessionState.Initializing -> RootAppState.Initializing
        SessionState.SignedOut -> RootAppState.SignedOut
        is SessionState.OfflineAvailable ->
            if (session.ownerId == unlockedOwnerId) {
                RootAppState.OfflineAvailable(session.ownerId, session.email)
            } else {
                RootAppState.SignedOut
            }

        is SessionState.Authenticated -> RootAppState.Authenticated(session.ownerId, session.email)
    }

    /**
     * Estado inicial desde la configuración pública cruda. Valida las MISMAS
     * reglas que [com.explainer.app.core.config.AppConfig] (URLs HTTPS, anon
     * key no vacía) pero sin construir el valor ni lanzar: la pantalla de
     * setup solo recibe el NOMBRE del campo, nunca la key.
     */
    fun initialFromConfig(
        supabaseUrl: String,
        anonKey: String,
        apiBaseUrl: String,
    ): RootAppState = when {
        !supabaseUrl.startsWith("https://") -> RootAppState.ConfigError(ConfigErrorField.SUPABASE_URL)
        anonKey.isBlank() -> RootAppState.ConfigError(ConfigErrorField.ANON_KEY)
        apiBaseUrl.isNotBlank() && !apiBaseUrl.startsWith("https://") ->
            RootAppState.ConfigError(ConfigErrorField.API_BASE_URL)

        else -> RootAppState.Initializing
    }

    /**
     * Decisión de destino de la raíz. [offlineUnlocked] es el flag efímero de
     * "continuar sin conexión" que el usuario confirma en el login offline;
     * se resetea en cuanto la sesión cambia (SignedOut/Authenticated).
     */
    fun navigationDecision(root: RootAppState, offlineUnlocked: Boolean): RootDestination = when (root) {
        RootAppState.Initializing -> RootDestination.Loading
        is RootAppState.ConfigError -> RootDestination.SetupError
        RootAppState.SignedOut -> RootDestination.Login
        is RootAppState.OfflineAvailable ->
            if (offlineUnlocked) RootDestination.App(root.ownerId) else RootDestination.Login

        is RootAppState.Authenticated -> RootDestination.App(root.ownerId)
    }
}

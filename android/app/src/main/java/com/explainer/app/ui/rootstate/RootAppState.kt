package com.explainer.app.ui.rootstate

/**
 * Campo de configuración ausente o inválido para la pantalla de setup
 * accionable. Solo se expone el NOMBRE público del campo, nunca el valor
 * (global-constraints.md Auth: la anon key no se imprime).
 */
enum class ConfigErrorField { SUPABASE_URL, ANON_KEY, API_BASE_URL }

/**
 * Estado raíz de la app (T11): la decisión de qué pantalla mostrar.
 *
 * - [Initializing]: esperando `awaitInitialization()` de auth (sin flash de
 *   pantalla incorrecta).
 * - [ConfigError]: configuración pública ausente/inválida: pantalla de setup
 *   accionable que nombra el campo, sin imprimir la key.
 * - [SignedOut]: sin sesión ni acceso local activo; los snapshots quedan
 *   particionados y dormidos.
 * - [OfflineAvailable]: sesión conservada (owner conocido) sin token
 *   utilizable, SOLO cuando el owner local fue desbloqueado por un login
 *   previo ([com.explainer.app.data.preferences.LocalAccessPreferences]).
 * - [Authenticated]: sesión con token utilizable; el owner de sesión
 *   particiona todo acceso local.
 *
 * El owner proviene únicamente de [com.explainer.app.data.auth.SessionGateway];
 * nunca es un argumento de ruta.
 */
sealed interface RootAppState {
    data object Initializing : RootAppState
    data class ConfigError(val field: ConfigErrorField) : RootAppState
    data object SignedOut : RootAppState
    data class OfflineAvailable(val ownerId: String, val email: String?) : RootAppState
    data class Authenticated(val ownerId: String, val email: String?) : RootAppState
}

/**
 * Destino de la raíz de composición derivado de [RootAppState] + el flag de
 * continuación offline. Función pura (testeable en JVM) que la UI usa para
 * no tener lógica de navegación dentro del Composable.
 */
sealed interface RootDestination {
    data object Loading : RootDestination
    data object SetupError : RootDestination
    data object Login : RootDestination

    /** App interior (biblioteca/lector/ajustes) con un owner de sesión. */
    data class App(val ownerId: String) : RootDestination
}

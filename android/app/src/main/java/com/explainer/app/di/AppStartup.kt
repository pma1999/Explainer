package com.explainer.app.di

import com.explainer.app.ui.rootstate.ConfigErrorField
import com.explainer.app.ui.rootstate.RootAppState
import com.explainer.app.ui.rootstate.RootAppStateReducer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Estado observable del arranque de la app (R-T11-06): `Ready` con el
 * container construido o `Broken` con el campo de configuración inválido.
 * Es un [StateFlow] para que la composición se RECOMPONGA cuando el retry
 * de la pantalla de setup reconstruye el container.
 */
sealed interface AppStartup {
    /** Composition root construido y vigente. */
    data class Ready(val container: AppContainer) : AppStartup

    /** Config inválida (o defensivo): pantalla de setup accionable. */
    data class Broken(val error: RootAppState.ConfigError) : AppStartup
}

/**
 * Controla la creación/reintento del composition root con estado observable:
 * cada intento actualiza [state] (Broken(ConfigError) → Ready(container) →
 * ...), de modo que la pantalla de setup desaparece al reintentar con la
 * config corregida, y un retry posterior cierra el container anterior antes
 * de crear el nuevo.
 *
 * Puro respecto a Android: las fuentes (BuildConfig y la factory del
 * container) se inyectan, por lo que es testeable en JVM.
 */
internal class AppStartupController(
    private val readConfig: () -> Triple<String, String, String>,
    private val createContainer: () -> AppContainer,
) {
    // Valor inicial provisional: `refresh()` (init) lo sustituye de inmediato.
    private val _state = MutableStateFlow<AppStartup>(
        AppStartup.Broken(RootAppState.ConfigError(ConfigErrorField.SUPABASE_URL)),
    )
    val state: StateFlow<AppStartup> = _state.asStateFlow()

    init {
        refresh()
    }

    /** Reintento de la pantalla de setup: cierra el container previo y recrea. */
    fun retry() {
        (_state.value as? AppStartup.Ready)?.container?.close()
        refresh()
    }

    private fun refresh() {
        val (supabaseUrl, anonKey, apiBaseUrl) = readConfig()
        val initial = RootAppStateReducer.initialFromConfig(supabaseUrl, anonKey, apiBaseUrl)
        _state.value = if (initial is RootAppState.ConfigError) {
            // Nunca se imprime la key: solo el nombre del campo.
            AppStartup.Broken(initial)
        } else {
            try {
                AppStartup.Ready(createContainer())
            } catch (_: IllegalArgumentException) {
                // Defensivo: las reglas ya se validaron arriba; si AppConfig
                // rechazara algo más, degradamos a setup error sin imprimir key.
                AppStartup.Broken(RootAppState.ConfigError(ConfigErrorField.API_BASE_URL))
            }
        }
    }
}

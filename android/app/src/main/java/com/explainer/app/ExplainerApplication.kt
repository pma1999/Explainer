package com.explainer.app

import android.app.Application
import com.explainer.app.di.AppStartup
import com.explainer.app.di.AppStartupController
import com.explainer.app.di.DefaultAppContainer
import kotlinx.coroutines.flow.StateFlow

/**
 * Application de la app (T11): posee el ÚNICO [AppContainer] del proceso.
 *
 * - Crea el container en `onCreate` con la configuración pública; si la
 *   config es inválida (nunca se imprime la key, solo el nombre del campo)
 *   el estado queda `Broken` para la pantalla de setup accionable.
 * - [startup] es un [StateFlow] COMPOSE-OBSERVABLE (R-T11-06): `retryContainer()`
 *   actualiza el estado y la composición se recomponen (la pantalla de setup
 *   desaparece al reintentar con la config corregida).
 * - WorkManager se configura UNA vez dentro de `DefaultAppContainer.create`
 *   con la custom WorkerFactory (el initializer de AndroidX Startup se
 *   elimina del manifest); este Application es el único dueño del container
 *   y lo cierra ([AppContainer.close]) con el proceso en `onTerminate`
 *   (best-effort: los procesos reales terminan sin callback; los trabajos
 *   durables de WorkManager y el almacenamiento privado sobreviven igual).
 */
class ExplainerApplication : Application() {

    private lateinit var startupController: AppStartupController

    /** Estado observable del arranque (Ready(container) | Broken(campo)). */
    val startup: StateFlow<AppStartup>
        get() = startupController.state

    override fun onCreate() {
        super.onCreate()
        startupController = AppStartupController(
            readConfig = {
                Triple(
                    BuildConfig.EXPLAINER_SUPABASE_URL,
                    BuildConfig.EXPLAINER_SUPABASE_ANON_KEY,
                    BuildConfig.EXPLAINER_API_BASE_URL,
                )
            },
            createContainer = { DefaultAppContainer.create(this) },
        )
    }

    /** Reintento de la pantalla de setup tras corregir la configuración. */
    fun retryContainer() {
        startupController.retry()
    }

    override fun onTerminate() {
        (startupController.state.value as? AppStartup.Ready)?.container?.close()
        super.onTerminate()
    }
}

package com.explainer.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.explainer.app.di.AppStartup
import com.explainer.app.ui.ExplainerApp

/**
 * Única Activity de la app (T11): delega en la raíz de composición
 * [ExplainerApp] con el [AppContainer] que posee [ExplainerApplication].
 * No inicia red ni WorkManager: el container ya esperó
 * `awaitInitialization()` y los Coordinadores viven en Application.
 *
 * El estado de arranque ([ExplainerApplication.startup]) es un StateFlow
 * COMPOSE-OBSERVABLE (R-T11-06): al pulsar "Reintentar", `retryContainer()`
 * actualiza el flujo y esta composición se recomponen con el container nuevo.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as ExplainerApplication
        setContent {
            val startup by app.startup.collectAsStateWithLifecycle()
            ExplainerApp(
                container = (startup as? AppStartup.Ready)?.container,
                configError = (startup as? AppStartup.Broken)?.error,
                onRetryConfig = app::retryContainer,
            )
        }
    }
}

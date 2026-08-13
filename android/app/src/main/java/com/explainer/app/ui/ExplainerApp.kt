package com.explainer.app.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.explainer.app.R
import com.explainer.app.di.AppContainer
import com.explainer.app.ui.components.OperationState
import com.explainer.app.ui.components.OperationStatePanel
import com.explainer.app.ui.navigation.ExplainerNavHost
import com.explainer.app.ui.rootstate.RootAppState
import com.explainer.app.ui.theme.DefaultThemeMode
import com.explainer.app.ui.theme.ExplainerTheme
import com.explainer.app.ui.theme.ThemeMode

/**
 * Única raíz de composición de la app (T11): decide la pantalla por el
 * estado raíz — sin flash de pantalla incorrecta durante `Initializing` —,
 * aplica el tema persistido (claro/oscuro/sistema desde DataStore, sin
 * recrear stores) y refresca el catálogo en foreground/resume solo con
 * sesión válida (sin polling).
 *
 * La navegación completa (Auth → Library → Reader → Settings) vive en
 * [ExplainerNavHost] (R-T11-03): tanto la pantalla de login como la app
 * interior están registradas en el grafo y las transiciones las decide el
 * estado raíz, de modo que un SignedOut (logout explícito) nunca deja
 * expuesto el owner anterior.
 */
@Composable
fun ExplainerApp(
    container: AppContainer?,
    configError: RootAppState.ConfigError?,
    onRetryConfig: () -> Unit,
) {
    if (container == null) {
        // R-T13-04: sin container no hay ThemePreferences; el bootstrap es
        // DARK explícito (nunca SYSTEM) y la superficie raíz pinta el fondo
        // del tema activo (setup error sobre papel/tinta, no sobre la ventana).
        ExplainerTheme(mode = DefaultThemeMode) {
            RootBackgroundSurface {
                SetupErrorScreen(configError = configError, onRetry = onRetryConfig)
            }
        }
        return
    }

    // T13: default DARK (identidad de la web); el valor inicial coincide con
    // el default de ThemePreferences para no destellar el tema claro en el
    // primer frame antes de que DataStore emita.
    val themeMode by container.themePreferences.themeMode
        .collectAsStateWithLifecycle(initialValue = ThemeMode.DARK)
    ExplainerTheme(mode = themeMode) {
        RootBackgroundSurface {
            val root by container.rootState.collectAsStateWithLifecycle()

            // Foreground/resume: refresh no destructivo solo con sesión/red
            // válidas; la falla conserva filas y snapshots (T07). No polling.
            val lifecycleOwner = LocalLifecycleOwner.current
            DisposableEffect(lifecycleOwner, container) {
                val observer = LifecycleEventObserver { _, event ->
                    if (event == Lifecycle.Event.ON_RESUME) container.refreshCatalogOnResume()
                }
                lifecycleOwner.lifecycle.addObserver(observer)
                onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
            }

            when (root) {
                // Esperando awaitInitialization(): carga neutral, sin flash.
                RootAppState.Initializing -> StartupLoadingScreen()

                // Defensivo: con container no nulo el estado raíz nunca es
                // ConfigError (la config se validó antes de crearlo).
                is RootAppState.ConfigError -> SetupErrorScreen(configError, onRetryConfig)

                // Auth y la app interior (Library/Reader/Settings) viven EN el
                // NavHost (R-T11-03): las cuatro rutas del plan están registradas
                // y las transiciones las decide el estado raíz.
                RootAppState.SignedOut,
                is RootAppState.OfflineAvailable,
                is RootAppState.Authenticated,
                -> ExplainerNavHost(container = container)
            }
        }
    }
}

/**
 * R-T13-01: superficie raíz edge-to-edge con el fondo del tema ACTIVO.
 * Lector, biblioteca, setup y paneles de estado son transparentes; sin esta
 * superficie el contenido quedaría sobre la ventana del sistema (tinta
 * #0d1117 fijada en themes.xml para el arranque DARK) y en LIGHT el texto
 * oscuro de lectura tendría ~1.16:1 de contraste. Usa
 * `background`/`onBackground` del tema activo (papel en LIGHT, tinta en
 * DARK), el mismo par que la ventana sigue vía SideEffect en `ExplainerTheme`.
 */
@Composable
private fun RootBackgroundSurface(content: @Composable () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
        contentColor = MaterialTheme.colorScheme.onBackground,
        content = content,
    )
}

/** Carga neutral mientras `awaitInitialization()` resuelve (sin flash). */
@Composable
private fun StartupLoadingScreen() {
    OperationStatePanel(state = OperationState.LOADING)
}

/**
 * Pantalla de setup accionable para config inválida: nombra el campo
 * público ausente (nunca imprime la key) y ofrece reintentar.
 */
@Composable
private fun SetupErrorScreen(
    configError: RootAppState.ConfigError?,
    onRetry: () -> Unit,
) {
    val fieldName = when (configError?.field) {
        com.explainer.app.ui.rootstate.ConfigErrorField.SUPABASE_URL -> "EXPLAINER_SUPABASE_URL"
        com.explainer.app.ui.rootstate.ConfigErrorField.ANON_KEY -> "EXPLAINER_SUPABASE_ANON_KEY"
        com.explainer.app.ui.rootstate.ConfigErrorField.API_BASE_URL -> "EXPLAINER_API_BASE_URL"
        null -> null
    }
    OperationStatePanel(
        state = OperationState.ERROR,
        title = stringResource(R.string.setup_error_title),
        message = if (fieldName != null) {
            stringResource(R.string.setup_error_message, fieldName)
        } else {
            stringResource(R.string.setup_error_message_generic)
        },
        actionLabel = stringResource(R.string.setup_error_retry),
        onAction = onRetry,
    )
}

package com.explainer.app.ui.auth

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.explainer.app.data.auth.SessionGateway

/**
 * Adaptador de ruta del login (T09/T11): crea el [LoginViewModel] con el
 * puerto de sesión, traduce [LoginEvent] a navegación ([onAuthenticated]) y
 * pinta la pantalla stateless. No registra NavHost: T11 lo cablea.
 */
@Composable
fun LoginRouteContent(
    gateway: SessionGateway,
    onAuthenticated: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val viewModel = remember(gateway) { LoginViewModel(scope, gateway) }

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                LoginEvent.Authenticated -> onAuthenticated()
            }
        }
    }

    val state by viewModel.uiState.collectAsStateWithLifecycle()
    LoginScreen(state = state, onAction = viewModel::onAction)
}

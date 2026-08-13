package com.explainer.app.ui.rootstate

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Decisión de navegación de la raíz (T11): cada estado raíz mapea a un único
 * destino y la continuación offline solo abre la app del owner desbloqueado;
 * los cambios de sesión resetean el flag (sin loops de navegación).
 */
class NavigationDecisionTest {

    private val owner = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

    @Test
    fun `initializing y setup error no abren la app`() {
        assertEquals(RootDestination.Loading, RootAppStateReducer.navigationDecision(RootAppState.Initializing, offlineUnlocked = true))
        assertEquals(
            RootDestination.SetupError,
            RootAppStateReducer.navigationDecision(
                RootAppState.ConfigError(ConfigErrorField.API_BASE_URL),
                offlineUnlocked = false,
            ),
        )
    }

    @Test
    fun `signed out es login aunque el flag efimero este puesto`() {
        assertEquals(RootDestination.Login, RootAppStateReducer.navigationDecision(RootAppState.SignedOut, offlineUnlocked = true))
    }

    @Test
    fun `authenticated abre la app del owner de sesion`() {
        assertEquals(
            RootDestination.App(owner),
            RootAppStateReducer.navigationDecision(
                RootAppState.Authenticated(owner, "a@b.com"),
                offlineUnlocked = false,
            ),
        )
    }

    @Test
    fun `offline abre solo tras continuar sin conexion`() {
        val offline = RootAppState.OfflineAvailable(owner, "a@b.com")
        assertEquals(RootDestination.Login, RootAppStateReducer.navigationDecision(offline, offlineUnlocked = false))
        assertEquals(RootDestination.App(owner), RootAppStateReducer.navigationDecision(offline, offlineUnlocked = true))
    }
}

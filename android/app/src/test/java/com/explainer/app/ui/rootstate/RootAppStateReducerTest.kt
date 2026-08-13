package com.explainer.app.ui.rootstate

import com.explainer.app.data.auth.SessionState
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Reducer del estado raíz de la app (T11): transiciones de sesión
 * (Initializing/SignedOut/OfflineAvailable/Authenticated), el gate de acceso
 * local (OfflineAvailable entra SOLO al owner desbloqueado tras login; un
 * SignedOut explícito no expone owners dormidos) y la decisión inicial con
 * config válida/inválida.
 */
class RootAppStateReducerTest {

    private val ownerA = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    private val ownerB = "1b2e4f6a-8c0d-4e3f-9a2b-5c6d7e8f9a0b"

    // ---- reduce(session, unlockedOwnerId) ----

    @Test
    fun `initializing se mantiene mientras auth inicia`() {
        assertEquals(
            RootAppState.Initializing,
            RootAppStateReducer.reduce(SessionState.Initializing, unlockedOwnerId = null),
        )
    }

    @Test
    fun `signed out explicito es signed out y no expone owners dormidos`() {
        assertEquals(
            RootAppState.SignedOut,
            RootAppStateReducer.reduce(SessionState.SignedOut, unlockedOwnerId = ownerA),
        )
    }

    @Test
    fun `authenticated es authenticated con owner y email`() {
        val state = RootAppStateReducer.reduce(
            SessionState.Authenticated(ownerA, "a@b.com"),
            unlockedOwnerId = null,
        )
        assertEquals(RootAppState.Authenticated(ownerA, "a@b.com"), state)
    }

    @Test
    fun `offline disponible entra solo al owner desbloqueado`() {
        val offline = SessionState.OfflineAvailable(ownerA, "a@b.com")
        assertEquals(
            RootAppState.OfflineAvailable(ownerA, "a@b.com"),
            RootAppStateReducer.reduce(offline, unlockedOwnerId = ownerA),
        )
    }

    @Test
    fun `offline disponible de otro owner degrada a signed out`() {
        val offline = SessionState.OfflineAvailable(ownerA, "a@b.com")
        assertEquals(
            RootAppState.SignedOut,
            RootAppStateReducer.reduce(offline, unlockedOwnerId = ownerB),
        )
        assertEquals(
            RootAppState.SignedOut,
            RootAppStateReducer.reduce(offline, unlockedOwnerId = null),
        )
    }

    @Test
    fun `login del owner A tras logout no expone a B y desbloquea solo a A`() {
        // B dormido: la sesión offline de B con el flag de A no entra.
        val offlineB = SessionState.OfflineAvailable(ownerB, "b@c.com")
        assertEquals(
            RootAppState.SignedOut,
            RootAppStateReducer.reduce(offlineB, unlockedOwnerId = ownerA),
        )
        // A autenticado: entra; su offline posterior con flag de A también.
        assertEquals(
            RootAppState.Authenticated(ownerA, "a@b.com"),
            RootAppStateReducer.reduce(SessionState.Authenticated(ownerA, "a@b.com"), unlockedOwnerId = ownerA),
        )
        assertEquals(
            RootAppState.OfflineAvailable(ownerA, "a@b.com"),
            RootAppStateReducer.reduce(SessionState.OfflineAvailable(ownerA, "a@b.com"), unlockedOwnerId = ownerA),
        )
    }

    // ---- initialFromConfig ----

    @Test
    fun `config valida produce initializing`() {
        assertEquals(
            RootAppState.Initializing,
            RootAppStateReducer.initialFromConfig(
                supabaseUrl = "https://x.supabase.co",
                anonKey = "anon-public-key",
                apiBaseUrl = "https://api.example.com",
            ),
        )
    }

    @Test
    fun `config invalida produce config error nombrando el campo sin valor`() {
        val error = RootAppStateReducer.initialFromConfig(
            supabaseUrl = "http://insecure",
            anonKey = "k",
            apiBaseUrl = "https://api.example.com",
        )
        assertEquals(RootAppState.ConfigError(ConfigErrorField.SUPABASE_URL), error)
    }

    @Test
    fun `anon key vacia produce config error de anon key`() {
        assertEquals(
            RootAppState.ConfigError(ConfigErrorField.ANON_KEY),
            RootAppStateReducer.initialFromConfig(
                supabaseUrl = "https://x.supabase.co",
                anonKey = "",
                apiBaseUrl = "https://api.example.com",
            ),
        )
    }

    @Test
    fun `api base invalida produce config error de api`() {
        assertEquals(
            RootAppState.ConfigError(ConfigErrorField.API_BASE_URL),
            RootAppStateReducer.initialFromConfig(
                supabaseUrl = "https://x.supabase.co",
                anonKey = "k",
                apiBaseUrl = "not-a-url",
            ),
        )
    }

}

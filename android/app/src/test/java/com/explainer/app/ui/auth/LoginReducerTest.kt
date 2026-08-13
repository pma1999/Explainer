package com.explainer.app.ui.auth

import com.explainer.app.R
import com.explainer.app.data.auth.AuthResult
import com.explainer.app.data.auth.SessionState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Reducer puro del login (T09): validación de campos, lock de carga,
 * mapeo de categorías de auth a errores user-safe y transiciones de
 * sesión (initial/offline/signed-out). Nunca loguea ni expone la
 * contraseña: el estado solo la conserva para el campo con
 * transformación visual; no hay logging en el ViewModel.
 */
class LoginReducerTest {

    private fun form(
        email: String = "a@b.com",
        password: String = "secreto",
    ) = LoginUiState.SignIn(email = email, password = password)

    // ---- Validación de campos ----

    @Test
    fun `submit con campos vacios marca errores requeridos`() {
        val state = LoginReducer.onSubmitted(LoginUiState.SignIn())
        assertEquals(LoginFieldError.REQUIRED, state.fieldErrors.email)
        assertEquals(LoginFieldError.REQUIRED, state.fieldErrors.password)
        assertFalse(state.isSubmitting)
    }

    @Test
    fun `submit con email invalido marca error de formato`() {
        val state = LoginReducer.onSubmitted(form(email = "no-es-email"))
        assertEquals(LoginFieldError.INVALID_EMAIL, state.fieldErrors.email)
        assertEquals(LoginFieldError.REQUIRED, state.fieldErrors.password)
        assertFalse(state.isSubmitting)
    }

    @Test
    fun `submit valido entra en carga y limpia errores`() {
        val state = LoginReducer.onSubmitted(form())
        assertTrue(state.isSubmitting)
        assertNull(state.fieldErrors.email)
        assertNull(state.fieldErrors.password)
        assertNull(state.formError)
    }

    @Test
    fun `segundo submit en carga no cambia el estado`() {
        val loading = LoginReducer.onSubmitted(form())
        val again = LoginReducer.onSubmitted(loading)
        assertEquals(loading, again)
    }

    @Test
    fun `editar email limpia el error de campo y el de formulario`() {
        var state = LoginReducer.onSubmitted(LoginUiState.SignIn())
        state = LoginReducer.onEmailChanged(state, "a@b.com")
        assertNull(state.fieldErrors.email)
        assertNull(state.formError)
    }

    @Test
    fun `editar contrasena limpia el error de campo`() {
        var state = LoginReducer.onSubmitted(LoginUiState.SignIn())
        state = LoginReducer.onPasswordChanged(state, "x")
        assertNull(state.fieldErrors.password)
    }

    @Test
    fun `alternar visibilidad invierte la bandera`() {
        val state = LoginReducer.onTogglePasswordVisibility(form())
        assertTrue(state.isPasswordVisible)
        assertFalse(LoginReducer.onTogglePasswordVisibility(state).isPasswordVisible)
    }

    // ---- Resultados de auth ----

    @Test
    fun `exito resetea el formulario y sale de carga`() {
        val loading = LoginReducer.onSubmitted(form())
        val state = LoginReducer.onAuthResult(loading, AuthResult.Success)
        assertEquals(LoginUiState.SignIn(), state)
        assertFalse(state.isSubmitting)
    }

    @Test
    fun `credenciales invalidas muestran error accionable`() {
        val state = LoginReducer.onAuthResult(form(), AuthResult.InvalidCredentials)
        assertEquals(LoginFormError.INVALID_CREDENTIALS, state.formError)
        assertFalse(state.isSubmitting)
    }

    @Test
    fun `red caida muestra error de red`() {
        val state = LoginReducer.onAuthResult(form(), AuthResult.NetworkUnavailable)
        assertEquals(LoginFormError.NETWORK, state.formError)
        assertFalse(state.isSubmitting)
    }

    @Test
    fun `rate limited muestra espera`() {
        val state = LoginReducer.onAuthResult(form(), AuthResult.RateLimited)
        assertEquals(LoginFormError.RATE_LIMITED, state.formError)
    }

    @Test
    fun `error de servidor y desconocido se mapean a categorias`() {
        assertEquals(LoginFormError.SERVER, LoginReducer.onAuthResult(form(), AuthResult.ServerError).formError)
        assertEquals(LoginFormError.WEAK_PASSWORD, LoginReducer.onAuthResult(form(), AuthResult.WeakPassword).formError)
        assertEquals(LoginFormError.UNKNOWN, LoginReducer.onAuthResult(form(), AuthResult.Unknown).formError)
    }

    // ---- Transiciones de sesión ----

    @Test
    fun `sesion inicial muestra carga`() {
        assertEquals(LoginUiState.Loading, LoginReducer.onSessionChanged(LoginUiState.Loading, SessionState.Initializing))
    }

    @Test
    fun `sin sesion muestra el formulario`() {
        val state = LoginReducer.onSessionChanged(LoginUiState.Loading, SessionState.SignedOut)
        assertEquals(LoginUiState.SignIn(), state)
    }

    @Test
    fun `offline disponible ofrece continuar conservando el formulario`() {
        val state = LoginReducer.onSessionChanged(
            LoginUiState.SignIn(email = "a@b.com"),
            SessionState.OfflineAvailable(ownerId = "owner-1", email = "a@b.com"),
        )
        assertTrue(state is LoginUiState.OfflineAvailable)
        state as LoginUiState.OfflineAvailable
        assertEquals("a@b.com", state.ownerEmail)
        assertEquals("a@b.com", state.form.email)
    }

    @Test
    fun `offline desde carga colapsa a formulario dentro del estado offline`() {
        val state = LoginReducer.onSessionChanged(LoginUiState.Loading, SessionState.OfflineAvailable("o", null))
        assertTrue(state is LoginUiState.OfflineAvailable)
        assertEquals(LoginUiState.SignIn(), (state as LoginUiState.OfflineAvailable).form)
    }

    @Test
    fun `sesion autenticada conserva el formulario`() {
        val before = form()
        val state = LoginReducer.onSessionChanged(before, SessionState.Authenticated("o", "a@b.com"))
        assertEquals(before, state)
    }

    @Test
    fun `offline a signed out vuelve al formulario sin rastro de owner`() {
        val offline = LoginReducer.onSessionChanged(LoginUiState.Loading, SessionState.OfflineAvailable("o", "a@b.com"))
        val state = LoginReducer.onSessionChanged(offline, SessionState.SignedOut)
        assertEquals(LoginUiState.SignIn(), state)
    }

    // ---- Labels user-safe (nunca credenciales) ----

    @Test
    fun `errores de campo mapean a strings utilitarios`() {
        assertEquals(R.string.login_email_required, LoginLabels.fieldErrorRes(LoginFieldError.REQUIRED))
        assertEquals(R.string.login_email_invalid, LoginLabels.fieldErrorRes(LoginFieldError.INVALID_EMAIL))
    }

    @Test
    fun `errores de formulario mapean a categorias accionables`() {
        assertEquals(R.string.login_error_invalid_credentials, LoginLabels.formErrorRes(LoginFormError.INVALID_CREDENTIALS))
        assertEquals(R.string.login_error_network, LoginLabels.formErrorRes(LoginFormError.NETWORK))
        assertEquals(R.string.login_error_rate_limited, LoginLabels.formErrorRes(LoginFormError.RATE_LIMITED))
        assertEquals(R.string.login_error_server, LoginLabels.formErrorRes(LoginFormError.SERVER))
        assertEquals(R.string.login_error_weak_password, LoginLabels.formErrorRes(LoginFormError.WEAK_PASSWORD))
        assertEquals(R.string.login_error_unknown, LoginLabels.formErrorRes(LoginFormError.UNKNOWN))
    }

    @Test
    fun `el estado nunca expone token ni mensajes crudos`() {
        val state = LoginReducer.onAuthResult(form(), AuthResult.InvalidCredentials)
        assertNotNull(state.formError)
        // La contraseña permanece solo como valor del campo editable.
        assertEquals("secreto", state.password)
        // No existe ninguna vía de token en el estado.
        assertFalse(LoginUiState.SignIn::class.java.declaredFields.any { it.name.contains("token", ignoreCase = true) })
    }
}

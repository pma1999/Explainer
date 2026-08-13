package com.explainer.app.ui.auth

import com.explainer.app.data.auth.AuthResult
import com.explainer.app.data.auth.SessionState

/**
 * Reducer puro del login (T09): validación de campos, lock de carga, mapeo
 * de categorías de auth a errores user-safe y transiciones de sesión.
 *
 * Nunca loguea ni expone la contraseña; el estado solo la conserva para el
 * campo editable. Las credenciales llegan al puerto exactamente como se
 * teclearon (la validación usa la forma recortada solo para decidir).
 */
internal object LoginReducer {

    private val EMAIL_REGEX = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")

    fun onEmailChanged(state: LoginUiState.SignIn, email: String): LoginUiState.SignIn =
        state.copy(
            email = email,
            fieldErrors = state.fieldErrors.copy(email = null),
            formError = null,
        )

    fun onPasswordChanged(state: LoginUiState.SignIn, password: String): LoginUiState.SignIn =
        state.copy(password = password, fieldErrors = state.fieldErrors.copy(password = null))

    fun onTogglePasswordVisibility(state: LoginUiState.SignIn): LoginUiState.SignIn =
        state.copy(isPasswordVisible = !state.isPasswordVisible)

    /**
     * Valida y entra en carga. Mientras el correo falle, la contraseña se
     * reporta como pendiente (REQUIRED): no se envía nada con un correo
     * inválido y el usuario no queda con un campo sin explicación.
     */
    fun onSubmitted(state: LoginUiState.SignIn): LoginUiState.SignIn {
        if (state.isSubmitting) return state
        val trimmedEmail = state.email.trim()
        val emailError = when {
            trimmedEmail.isEmpty() -> LoginFieldError.REQUIRED
            !EMAIL_REGEX.matches(trimmedEmail) -> LoginFieldError.INVALID_EMAIL
            else -> null
        }
        val passwordError = if (emailError != null || state.password.isBlank()) {
            LoginFieldError.REQUIRED
        } else {
            null
        }
        val errors = LoginFieldErrors(email = emailError, password = passwordError)
        return if (emailError != null || passwordError != null) {
            state.copy(isSubmitting = false, fieldErrors = errors, formError = null)
        } else {
            state.copy(isSubmitting = true, fieldErrors = LoginFieldErrors(), formError = null)
        }
    }

    /** Resultado del puerto: categoría user-safe; éxito resetea el formulario. */
    fun onAuthResult(state: LoginUiState.SignIn, result: AuthResult): LoginUiState.SignIn =
        if (result == AuthResult.Success) {
            LoginUiState.SignIn()
        } else {
            state.copy(
                isSubmitting = false,
                fieldErrors = LoginFieldErrors(),
                formError = result.toFormError(),
            )
        }

    /** Transiciones de sesión observadas del puerto. */
    fun onSessionChanged(state: LoginUiState, session: SessionState): LoginUiState = when (session) {
        is SessionState.Initializing -> LoginUiState.Loading
        is SessionState.SignedOut -> LoginUiState.SignIn()
        is SessionState.OfflineAvailable -> LoginUiState.OfflineAvailable(
            ownerEmail = session.email,
            form = (state as? LoginUiState.SignIn) ?: LoginUiState.SignIn(),
        )
        is SessionState.Authenticated -> state
    }

    private fun AuthResult.toFormError(): LoginFormError = when (this) {
        AuthResult.InvalidCredentials -> LoginFormError.INVALID_CREDENTIALS
        AuthResult.NetworkUnavailable -> LoginFormError.NETWORK
        AuthResult.RateLimited -> LoginFormError.RATE_LIMITED
        AuthResult.ServerError -> LoginFormError.SERVER
        AuthResult.WeakPassword -> LoginFormError.WEAK_PASSWORD
        AuthResult.Success, AuthResult.Unknown -> LoginFormError.UNKNOWN
    }
}

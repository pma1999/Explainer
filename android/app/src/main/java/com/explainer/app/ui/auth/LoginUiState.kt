package com.explainer.app.ui.auth

/**
 * Estado, acciones y eventos del login (T09).
 *
 * El estado es inmutable y presentacional: nunca expone tokens, mensajes
 * crudos de GoTrue ni credenciales (global-constraints.md Auth). La
 * contraseña vive solo como valor del campo editable con transformación
 * visual; no hay logging en el ViewModel.
 */
sealed interface LoginUiState {
    /** Sesión persistida en carga (`SessionState.Initializing`). */
    data object Loading : LoginUiState

    /** Formulario email/password listo para editar y enviar. */
    data class SignIn(
        val email: String = "",
        val password: String = "",
        val isPasswordVisible: Boolean = false,
        val isSubmitting: Boolean = false,
        val fieldErrors: LoginFieldErrors = LoginFieldErrors(),
        val formError: LoginFormError? = null,
    ) : LoginUiState

    /**
     * Sesión conservada sin token utilizable: se ofrece continuar a las
     * descargas del owner sin afirmar que hay conexión. El formulario se
     * conserva por si el usuario quiere reintentar el login.
     */
    data class OfflineAvailable(
        val ownerEmail: String?,
        val form: SignIn,
    ) : LoginUiState
}

/** Errores de validación de campo (copia user-safe vía [LoginLabels]). */
enum class LoginFieldError { REQUIRED, INVALID_EMAIL }

/** Categorías user-safe de error de autenticación (nunca mensajes crudos). */
enum class LoginFormError {
    INVALID_CREDENTIALS,
    NETWORK,
    RATE_LIMITED,
    SERVER,
    WEAK_PASSWORD,
    UNKNOWN,
}

data class LoginFieldErrors(
    val email: LoginFieldError? = null,
    val password: LoginFieldError? = null,
)

/** Acciones del formulario; el ViewModel las traduce a llamadas al puerto. */
sealed interface LoginAction {
    data class EmailChanged(val email: String) : LoginAction
    data class PasswordChanged(val password: String) : LoginAction
    data object TogglePasswordVisibility : LoginAction
    data object Submit : LoginAction

    /** Continuar con la sesión offline conservada (owner conocido). */
    data object ContinueOffline : LoginAction
}

/** Eventos one-shot que el host (ruta) traduce en navegación/haptics. */
sealed interface LoginEvent {
    data object Authenticated : LoginEvent
}

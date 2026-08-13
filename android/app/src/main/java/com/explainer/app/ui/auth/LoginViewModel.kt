package com.explainer.app.ui.auth

import com.explainer.app.data.auth.AuthResult
import com.explainer.app.data.auth.SessionGateway
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * ViewModel del login (T09): observa [SessionGateway], valida campos y
 * delega el signIn por el puerto (nunca Ktor/Supabase directos). No loguea
 * credenciales ni tokens: el fake de tests registra lo recibido para
 * asertar el contrato, pero aquí no hay logging.
 *
 * El bloqueo de reenvío (`submitInFlight`) es explícito y dura hasta que el
 * usuario edita un campo o cambia la sesión: en producción el puerto
 * suspende con la red, pero el contrato no depende de la latencia.
 */
class LoginViewModel(
    private val scope: CoroutineScope,
    private val gateway: SessionGateway,
) {
    private val _uiState = MutableStateFlow<LoginUiState>(LoginUiState.Loading)
    val uiState: StateFlow<LoginUiState> = _uiState

    private val _events = MutableSharedFlow<LoginEvent>(extraBufferCapacity = 8)
    val events: SharedFlow<LoginEvent> = _events

    private var submitInFlight = false

    init {
        scope.launch {
            gateway.state.collect { session ->
                _uiState.value = LoginReducer.onSessionChanged(_uiState.value, session)
            }
        }
    }

    fun onAction(action: LoginAction) {
        when (action) {
            is LoginAction.EmailChanged -> {
                submitInFlight = false
                mapSignIn { LoginReducer.onEmailChanged(it, action.email) }
            }

            is LoginAction.PasswordChanged -> {
                submitInFlight = false
                mapSignIn { LoginReducer.onPasswordChanged(it, action.password) }
            }

            LoginAction.TogglePasswordVisibility ->
                mapSignIn(LoginReducer::onTogglePasswordVisibility)

            LoginAction.Submit -> submit()

            LoginAction.ContinueOffline -> scope.launch { _events.emit(LoginEvent.Authenticated) }
        }
    }

    /** Aplica una transformación al formulario, dentro o fuera del estado offline. */
    private fun mapSignIn(transform: (LoginUiState.SignIn) -> LoginUiState.SignIn) {
        when (val current = _uiState.value) {
            is LoginUiState.SignIn -> _uiState.value = transform(current)
            is LoginUiState.OfflineAvailable -> _uiState.value = current.copy(form = transform(current.form))
            LoginUiState.Loading -> Unit
        }
    }

    private fun submit() {
        if (submitInFlight) return
        val current = _uiState.value
        val form = when (current) {
            is LoginUiState.SignIn -> current
            is LoginUiState.OfflineAvailable -> current.form
            LoginUiState.Loading -> return
        }
        val submitted = LoginReducer.onSubmitted(form)
        val hasFieldErrors =
            submitted.fieldErrors.email != null || submitted.fieldErrors.password != null
        mapSignIn { submitted }
        if (hasFieldErrors) return

        submitInFlight = true
        scope.launch {
            // Las credenciales se envían exactamente como se teclearon.
            val result = gateway.signIn(form.email, form.password)
            mapSignIn { LoginReducer.onAuthResult(submitted, result) }
            if (result == AuthResult.Success) {
                _events.emit(LoginEvent.Authenticated)
            }
        }
    }
}

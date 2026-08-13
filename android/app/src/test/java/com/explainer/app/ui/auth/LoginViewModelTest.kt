package com.explainer.app.ui.auth

import com.explainer.app.data.auth.AuthResult
import com.explainer.app.data.auth.SessionState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ViewModel de login (T09): observa [SessionGateway], valida y delega el
 * signIn por el puerto; nunca loguea credenciales ni tokens. Los tests
 * usan un scope Unconfined para que las emisiones de StateFlow/SharedFlow
 * se propaguen de forma síncrona.
 */
class LoginViewModelTest {

    private fun scope() = CoroutineScope(Dispatchers.Unconfined)

    private fun collectEvents(viewModel: LoginViewModel): MutableList<LoginEvent> {
        val emitted = mutableListOf<LoginEvent>()
        scope().launch { viewModel.events.collect { emitted.add(it) } }
        return emitted
    }

    @Test
    fun `sesion inicial se refleja como carga`() {
        val gateway = FakeSessionGateway(SessionState.Initializing)
        val viewModel = LoginViewModel(scope(), gateway)
        assertEquals(LoginUiState.Loading, viewModel.uiState.value)
    }

    @Test
    fun `sesion signed out muestra el formulario`() {
        val gateway = FakeSessionGateway(SessionState.SignedOut)
        val viewModel = LoginViewModel(scope(), gateway)
        assertEquals(LoginUiState.SignIn(), viewModel.uiState.value)
    }

    @Test
    fun `submit valido llama al gateway y emite autenticado en exito`() {
        val gateway = FakeSessionGateway(SessionState.SignedOut)
        val viewModel = LoginViewModel(scope(), gateway)
        val emitted = collectEvents(viewModel)

        viewModel.onAction(LoginAction.EmailChanged("a@b.com"))
        viewModel.onAction(LoginAction.PasswordChanged("secreto"))
        viewModel.onAction(LoginAction.Submit)

        assertEquals(listOf("a@b.com" to "secreto"), gateway.signInCalls)
        assertEquals(LoginUiState.SignIn(), viewModel.uiState.value)
        assertEquals(listOf(LoginEvent.Authenticated), emitted)
    }

    @Test
    fun `credenciales invalidas muestran error y no emiten autenticado`() {
        val gateway = FakeSessionGateway(SessionState.SignedOut).apply {
            signInResult = AuthResult.InvalidCredentials
        }
        val viewModel = LoginViewModel(scope(), gateway)
        val emitted = collectEvents(viewModel)

        viewModel.onAction(LoginAction.EmailChanged("a@b.com"))
        viewModel.onAction(LoginAction.PasswordChanged("mala"))
        viewModel.onAction(LoginAction.Submit)

        val state = viewModel.uiState.value as LoginUiState.SignIn
        assertEquals(LoginFormError.INVALID_CREDENTIALS, state.formError)
        assertFalse(state.isSubmitting)
        assertTrue(emitted.isEmpty())
    }

    @Test
    fun `red caida muestra error de red`() {
        val gateway = FakeSessionGateway(SessionState.SignedOut).apply {
            signInResult = AuthResult.NetworkUnavailable
        }
        val viewModel = LoginViewModel(scope(), gateway)

        viewModel.onAction(LoginAction.EmailChanged("a@b.com"))
        viewModel.onAction(LoginAction.PasswordChanged("secreto"))
        viewModel.onAction(LoginAction.Submit)

        val state = viewModel.uiState.value as LoginUiState.SignIn
        assertEquals(LoginFormError.NETWORK, state.formError)
    }

    @Test
    fun `submit con campos invalidos no llama al gateway`() {
        val gateway = FakeSessionGateway(SessionState.SignedOut)
        val viewModel = LoginViewModel(scope(), gateway)

        viewModel.onAction(LoginAction.Submit)

        assertTrue(gateway.signInCalls.isEmpty())
        assertTrue((viewModel.uiState.value as LoginUiState.SignIn).fieldErrors.email != null)
    }

    @Test
    fun `submit en carga no reenvia credenciales`() {
        val gateway = FakeSessionGateway(SessionState.SignedOut)
        val viewModel = LoginViewModel(scope(), gateway)

        viewModel.onAction(LoginAction.EmailChanged("a@b.com"))
        viewModel.onAction(LoginAction.PasswordChanged("secreto"))
        viewModel.onAction(LoginAction.Submit)
        viewModel.onAction(LoginAction.Submit)
        viewModel.onAction(LoginAction.Submit)

        assertEquals(1, gateway.signInCalls.size)
    }

    @Test
    fun `sesion offline ofrece continuar y emite autenticado`() {
        val gateway = FakeSessionGateway(SessionState.OfflineAvailable("owner-1", "a@b.com"))
        val viewModel = LoginViewModel(scope(), gateway)
        val emitted = collectEvents(viewModel)

        assertTrue(viewModel.uiState.value is LoginUiState.OfflineAvailable)
        viewModel.onAction(LoginAction.ContinueOffline)

        assertEquals(listOf(LoginEvent.Authenticated), emitted)
    }

    @Test
    fun `signIn recibe exactamente lo tecleado y nunca se loguea`() {
        val gateway = FakeSessionGateway(SessionState.SignedOut)
        val viewModel = LoginViewModel(scope(), gateway)

        viewModel.onAction(LoginAction.EmailChanged("  usuario@example.com "))
        viewModel.onAction(LoginAction.PasswordChanged("clave-secreta"))
        viewModel.onAction(LoginAction.Submit)

        // El fake registra lo recibido; no hay logging en el ViewModel.
        assertEquals("  usuario@example.com " to "clave-secreta", gateway.signInCalls.single())
    }
}

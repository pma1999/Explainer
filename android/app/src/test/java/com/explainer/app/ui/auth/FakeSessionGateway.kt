package com.explainer.app.ui.auth

import com.explainer.app.data.auth.AuthResult
import com.explainer.app.data.auth.RefreshResult
import com.explainer.app.data.auth.SessionGateway
import com.explainer.app.data.auth.SessionState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Doble de [SessionGateway] para tests JVM de login y biblioteca (T09):
 * estado observable controlable, signIn que devuelve [signInResult] y
 * registra las credenciales recibidas (los ViewModels jamás las loguean;
 * el fake solo las recuerda para asertar el contrato).
 */
class FakeSessionGateway(
    initial: SessionState = SessionState.Initializing,
) : SessionGateway {

    val stateFlow = MutableStateFlow(initial)
    override val state: StateFlow<SessionState> = stateFlow

    var signInResult: AuthResult = AuthResult.Success
    val signInCalls = mutableListOf<Pair<String, String>>()
    var signOutCalls: Int = 0
        private set

    override suspend fun signIn(email: String, password: String): AuthResult {
        signInCalls.add(email to password)
        return signInResult
    }

    override suspend fun signOut() {
        signOutCalls++
    }

    override suspend fun bearerTokenOrNull(): String? = null

    override suspend fun refreshOnce(): RefreshResult = RefreshResult.Success
}

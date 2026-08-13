package com.explainer.app.ui.auth

import com.explainer.app.R

/**
 * Copia textual user-safe del login (T09): cada error mapea a un string
 * accionable y sin detalles crudos (global-constraints.md Auth). Toda la
 * copy de esta feature vive en `strings_auth_library.xml`.
 */
object LoginLabels {

    fun fieldErrorRes(error: LoginFieldError): Int = when (error) {
        LoginFieldError.REQUIRED -> R.string.login_email_required
        LoginFieldError.INVALID_EMAIL -> R.string.login_email_invalid
    }

    fun formErrorRes(error: LoginFormError): Int = when (error) {
        LoginFormError.INVALID_CREDENTIALS -> R.string.login_error_invalid_credentials
        LoginFormError.NETWORK -> R.string.login_error_network
        LoginFormError.RATE_LIMITED -> R.string.login_error_rate_limited
        LoginFormError.SERVER -> R.string.login_error_server
        LoginFormError.WEAK_PASSWORD -> R.string.login_error_weak_password
        LoginFormError.UNKNOWN -> R.string.login_error_unknown
    }
}

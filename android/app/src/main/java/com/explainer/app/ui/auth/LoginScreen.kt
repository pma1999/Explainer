package com.explainer.app.ui.auth

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.components.ExplainerIcons
import com.explainer.app.ui.theme.BootstrapTheme
import com.explainer.app.ui.theme.ExplainerTheme
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.ThemeMode
import com.explainer.app.ui.theme.explainerColors

/**
 * Pantalla de login (T09), stateless: recibe [LoginUiState] inmutable y
 * emite [LoginAction]. Momento de marca: wordmark serif con acento dorado,
 * inputs con icono, errores con icono, botón primario lleno y panel offline
 * bien separado. Gestiona IME (Next/Done), visibilidad de contraseña, carga,
 * errores de campo/formulario y la continuación offline conservada.
 * Contenido desplazable con `imePadding` y ancho de formulario acotado en
 * medium/expanded: a 200 % de escala de fuente nada se corta.
 */
@Composable
fun LoginScreen(state: LoginUiState, onAction: (LoginAction) -> Unit) {
    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
        contentColor = MaterialTheme.colorScheme.onBackground,
    ) {
        when (state) {
            LoginUiState.Loading -> CheckingSession()
            is LoginUiState.SignIn -> SignInScaffold { LoginForm(state = state, onAction = onAction) }
            is LoginUiState.OfflineAvailable -> SignInScaffold {
                OfflineContinuePanel(state = state, onAction = onAction)
                HorizontalDivider()
                LoginForm(state = state.form, onAction = onAction)
            }
        }
    }
}

/** Contenedor desplazable con padding de IME para formulario y panel. */
@Composable
private fun SignInScaffold(content: @Composable () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .imePadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = LoginScreenDefaults.FormMaxWidth),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            content()
        }
    }
}

/** Carga elegante de sesión: wordmark + spinner con copy explícita. */
@Composable
private fun CheckingSession() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Wordmark()
            Spacer(Modifier.height(Spacing.Xl))
            CircularProgressIndicator(
                color = MaterialTheme.explainerColors.primary,
                modifier = Modifier.size(LoginScreenDefaults.CheckingSpinnerSize),
                strokeWidth = LoginScreenDefaults.CheckingSpinnerStroke,
            )
            Spacer(Modifier.height(Spacing.Lg))
            Text(
                text = stringResource(R.string.login_checking_session),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** Wordmark: nombre serif + regla dorada + tagline (marca sin florituras). */
@Composable
private fun Wordmark() {
    val colors = MaterialTheme.explainerColors
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = stringResource(R.string.app_name),
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Spacer(Modifier.height(Spacing.Sm))
        Box(
            modifier = Modifier
                .width(LoginScreenDefaults.WordmarkRuleWidth)
                .height(LoginScreenDefaults.WordmarkRuleHeight),
        ) {
            Surface(
                modifier = Modifier.fillMaxSize(),
                color = colors.primary,
                shape = MaterialTheme.shapes.extraSmall,
            ) {}
        }
        Spacer(Modifier.height(Spacing.Sm))
        Text(
            text = stringResource(R.string.login_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * Panel de continuación offline: ofrece acceder a las descargas del owner
 * sin afirmar que hay conexión (copia "acceso guardado", no "estás online").
 * Visualmente separado del formulario (contenedor offline + icono).
 */
@Composable
private fun OfflineContinuePanel(
    state: LoginUiState.OfflineAvailable,
    onAction: (LoginAction) -> Unit,
) {
    val colors = MaterialTheme.explainerColors
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Xl)
            .padding(top = Spacing.Xl),
        color = colors.status.offlineContainer,
        contentColor = colors.status.onOfflineContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacing.Lg),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = ExplainerIcons.CloudOff,
                    contentDescription = null,
                    tint = colors.status.onOfflineContainer,
                    modifier = Modifier.size(LoginScreenDefaults.OfflineIconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
                Text(
                    text = stringResource(R.string.login_offline_message, state.ownerEmail.orEmpty()),
                    style = MaterialTheme.typography.bodyMedium,
                    color = colors.status.onOfflineContainer,
                )
            }
            Spacer(Modifier.height(Spacing.Md))
            Button(
                onClick = { onAction(LoginAction.ContinueOffline) },
                modifier = Modifier.heightIn(min = LoginScreenDefaults.MinimumTargetSize),
            ) {
                Icon(
                    imageVector = ExplainerIcons.KeyboardArrowRight,
                    contentDescription = null,
                    modifier = Modifier.size(LoginScreenDefaults.ActionIconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
                Text(
                    text = stringResource(R.string.login_continue_offline),
                    style = MaterialTheme.typography.labelLarge,
                )
            }
        }
    }
}

@Composable
private fun LoginForm(state: LoginUiState.SignIn, onAction: (LoginAction) -> Unit) {
    val colors = MaterialTheme.explainerColors
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Xl, vertical = Spacing.Xl),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Wordmark()
        Spacer(Modifier.height(Spacing.Xl))

        OutlinedTextField(
            value = state.email,
            onValueChange = { onAction(LoginAction.EmailChanged(it)) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.login_email_label)) },
            leadingIcon = {
                Icon(
                    imageVector = ExplainerIcons.Email,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Email,
                imeAction = ImeAction.Next,
            ),
            isError = state.fieldErrors.email != null,
            supportingText = state.fieldErrors.email?.let { error ->
                { FieldErrorText(stringResource(LoginLabels.fieldErrorRes(error))) }
            },
        )
        Spacer(Modifier.height(Spacing.Md))
        OutlinedTextField(
            value = state.password,
            onValueChange = { onAction(LoginAction.PasswordChanged(it)) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.login_password_label)) },
            leadingIcon = {
                Icon(
                    imageVector = ExplainerIcons.Lock,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
            singleLine = true,
            visualTransformation = if (state.isPasswordVisible) {
                VisualTransformation.None
            } else {
                PasswordVisualTransformation()
            },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Password,
                imeAction = ImeAction.Done,
            ),
            keyboardActions = KeyboardActions(onDone = { onAction(LoginAction.Submit) }),
            isError = state.fieldErrors.password != null,
            supportingText = state.fieldErrors.password?.let { error ->
                {
                    FieldErrorText(
                        stringResource(
                            if (error == LoginFieldError.REQUIRED) {
                                R.string.login_password_required
                            } else {
                                LoginLabels.fieldErrorRes(error)
                            },
                        ),
                    )
                }
            },
            trailingIcon = {
                IconButton(
                    onClick = { onAction(LoginAction.TogglePasswordVisibility) },
                    modifier = Modifier.heightIn(min = LoginScreenDefaults.MinimumTargetSize),
                ) {
                    Icon(
                        imageVector = if (state.isPasswordVisible) {
                            ExplainerIcons.VisibilityOff
                        } else {
                            ExplainerIcons.Visibility
                        },
                        contentDescription = stringResource(
                            if (state.isPasswordVisible) R.string.login_hide_password else R.string.login_show_password,
                        ),
                    )
                }
            },
        )
        Spacer(Modifier.height(Spacing.Lg))

        state.formError?.let { error ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = ExplainerIcons.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(LoginScreenDefaults.ErrorIconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
                Text(
                    text = stringResource(LoginLabels.formErrorRes(error)),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Spacer(Modifier.height(Spacing.Lg))
        }

        Button(
            onClick = { onAction(LoginAction.Submit) },
            enabled = !state.isSubmitting,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = LoginScreenDefaults.MinimumTargetSize),
        ) {
            if (state.isSubmitting) {
                CircularProgressIndicator(
                    modifier = Modifier.size(LoginScreenDefaults.SubmitSpinnerSize),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
                Spacer(Modifier.width(Spacing.Sm))
            }
            Text(
                text = stringResource(
                    if (state.isSubmitting) R.string.login_submitting else R.string.login_submit,
                ),
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}

/** Error de campo con icono (nunca solo color). */
@Composable
private fun FieldErrorText(message: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
            imageVector = ExplainerIcons.Warning,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.error,
            modifier = Modifier.size(LoginScreenDefaults.ErrorIconSize),
        )
        Spacer(Modifier.width(Spacing.Sm))
        Text(
            text = message,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

object LoginScreenDefaults {
    /** Target táctil mínimo declarado (submit, toggle, continuar offline). */
    val MinimumTargetSize: Dp = 48.dp
    val SubmitSpinnerSize: Dp = 18.dp
    val CheckingSpinnerSize: Dp = 28.dp
    val CheckingSpinnerStroke: Dp = 3.dp
    val ErrorIconSize: Dp = 16.dp
    val ActionIconSize: Dp = 18.dp
    val OfflineIconSize: Dp = 18.dp
    val WordmarkRuleWidth: Dp = 48.dp
    val WordmarkRuleHeight: Dp = 2.dp
    val FormMaxWidth: Dp = 480.dp
}

@Preview(name = "Login form (light, compact)", widthDp = 360, heightDp = 720, showBackground = true)
@Composable
private fun LoginFormLightPreview() {
    ExplainerTheme(mode = ThemeMode.LIGHT) {
        LoginScreen(
            state = LoginUiState.SignIn(
                email = "lector@example.com",
                password = "secreto",
                isPasswordVisible = true,
            ),
            onAction = {},
        )
    }
}

@Preview(name = "Login offline (dark, expanded)", widthDp = 840, heightDp = 720, showBackground = true)
@Composable
private fun LoginOfflineDarkPreview() {
    BootstrapTheme {
        LoginScreen(
            state = LoginUiState.OfflineAvailable(
                ownerEmail = "lector@example.com",
                form = LoginUiState.SignIn(email = "lector@example.com"),
            ),
            onAction = {},
        )
    }
}

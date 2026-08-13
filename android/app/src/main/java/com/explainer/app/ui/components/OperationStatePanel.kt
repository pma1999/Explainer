package com.explainer.app.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.theme.MotionTokens
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors

/** Estado operativo representado por [OperationStatePanel]. */
enum class OperationState { LOADING, EMPTY, ERROR, OFFLINE }

/**
 * Panel de estado operativo (cargando / vacío / error / offline) con icono,
 * copia y acción explícitas, como exige global-constraints.md UX.
 * Presentacional y estático: nunca inicia red, Room ni WorkManager; el host
 * decide cuándo llamar [onAction]. El icono es decorativo (sin semántica):
 * la información viaja en el título/mensaje. Entrada con fade sutil que
 * respeta la escala de animación del sistema.
 *
 * @param state estado a representar.
 * @param title título; null usa la copia compartida del estado.
 * @param message detalle; null usa la copia compartida del estado.
 * @param actionLabel etiqueta de la acción; null y [onAction] no nulo usan
 *   la copia compartida ("Reintentar").
 * @param onAction acción opcional (p. ej. reintentar/recargar).
 * @param minHeight altura mínima del panel (contenido centrado).
 */
@Composable
fun OperationStatePanel(
    state: OperationState,
    modifier: Modifier = Modifier,
    title: String? = null,
    message: String? = null,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    minHeight: Dp = OperationStatePanelDefaults.MinHeight,
) {
    val colors = MaterialTheme.explainerColors
    val resolvedTitle = title ?: when (state) {
        OperationState.LOADING -> stringResource(R.string.state_loading_title)
        OperationState.EMPTY -> stringResource(R.string.state_empty_title)
        OperationState.ERROR -> stringResource(R.string.state_error_title)
        OperationState.OFFLINE -> stringResource(R.string.state_offline_title)
    }
    val resolvedMessage = message ?: when (state) {
        OperationState.LOADING -> stringResource(R.string.state_loading_message)
        OperationState.EMPTY -> stringResource(R.string.state_empty_message)
        OperationState.ERROR -> stringResource(R.string.state_error_message)
        OperationState.OFFLINE -> stringResource(R.string.state_offline_message)
    }
    val accent = when (state) {
        OperationState.LOADING -> colors.primary
        OperationState.EMPTY -> colors.onSurfaceVariant
        OperationState.ERROR -> colors.error
        OperationState.OFFLINE -> colors.status.offline
    }

    AnimatedVisibility(
        visible = true,
        enter = fadeIn(animationSpec = tween(MotionTokens.NormalMs)),
    ) {
        Column(
            modifier = modifier
                .fillMaxSize()
                .heightIn(min = minHeight)
                .padding(Spacing.Xxl),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            when (state) {
                OperationState.LOADING -> CircularProgressIndicator(
                    modifier = Modifier.size(OperationStatePanelDefaults.ProgressSize),
                    color = accent,
                    strokeWidth = OperationStatePanelDefaults.ProgressStroke,
                )

                OperationState.EMPTY, OperationState.ERROR, OperationState.OFFLINE ->
                    StateIcon(state = state, accent = accent)
            }
            Spacer(Modifier.height(Spacing.Lg))
            Text(
                text = resolvedTitle,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(Spacing.Sm))
            Text(
                text = resolvedMessage,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
            if (onAction != null) {
                Spacer(Modifier.height(Spacing.Xl))
                Button(
                    onClick = onAction,
                    modifier = Modifier.heightIn(min = OperationStatePanelDefaults.MinimumActionHeight),
                ) {
                    Text(
                        text = actionLabel ?: stringResource(R.string.action_retry),
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
        }
    }
}

/** Icono del estado sobre un contenedor plano (nunca gradiente). */
@Composable
private fun StateIcon(state: OperationState, accent: androidx.compose.ui.graphics.Color) {
    val icon: ImageVector = when (state) {
        OperationState.EMPTY -> ExplainerIcons.Inbox
        OperationState.ERROR -> ExplainerIcons.Error
        OperationState.OFFLINE -> ExplainerIcons.CloudOff
        OperationState.LOADING -> return // el loading usa spinner
    }
    Box(contentAlignment = Alignment.Center) {
        Surface(
            color = MaterialTheme.explainerColors.surfaceContainerHigh,
            shape = MaterialTheme.shapes.medium,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = accent,
                modifier = Modifier
                    .padding(OperationStatePanelDefaults.IconPadding)
                    .size(OperationStatePanelDefaults.IconSize),
            )
        }
    }
}

object OperationStatePanelDefaults {
    val MinHeight: Dp = 240.dp
    val ProgressSize: Dp = 32.dp
    val ProgressStroke: Dp = 3.dp
    val IconSize: Dp = 28.dp
    val IconPadding: Dp = 12.dp
    /** Target táctil mínimo declarado del botón de acción. */
    val MinimumActionHeight: Dp = 48.dp
}

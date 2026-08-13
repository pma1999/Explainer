package com.explainer.app.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors

/**
 * Sheet de confirmación para acciones destructivas/importantes (borrar
 * descarga, cerrar sesión, cancelar operación). Presentacional: los haptics
 * de confirmación los dispara el host (global-constraints.md UX), no este
 * componente. El icono (opcional) es decorativo; la semántica vive en el
 * título/mensaje.
 *
 * @param title título de la confirmación.
 * @param message detalle de la acción.
 * @param confirmLabel etiqueta del botón de confirmar.
 * @param destructive true → botón de confirmar con colores de error.
 * @param onConfirm acción de confirmación.
 * @param onDismiss cierre del sheet (fuera, atrás o "Cancelar").
 * @param icon icono decorativo opcional del encabezado (p. ej. Delete).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConfirmActionSheet(
    title: String,
    message: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    destructive: Boolean = false,
    icon: ImageVector? = null,
) {
    val colors = MaterialTheme.explainerColors
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        modifier = modifier.fillMaxWidth(),
        containerColor = MaterialTheme.colorScheme.surface,
        contentColor = MaterialTheme.colorScheme.onSurface,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.Xl)
                .padding(bottom = Spacing.Xxl),
        ) {
            if (icon != null) {
                Surface(
                    color = if (destructive) colors.errorContainer else colors.primaryContainer,
                    shape = MaterialTheme.shapes.medium,
                ) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = if (destructive) colors.onErrorContainer else colors.onPrimaryContainer,
                        modifier = Modifier
                            .padding(Spacing.Md)
                            .size(ConfirmActionSheetDefaults.IconSize),
                    )
                }
                Spacer(Modifier.height(Spacing.Lg))
            }
            Text(
                text = title,
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(Spacing.Sm))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Start,
            )
            Spacer(Modifier.height(Spacing.Xl))
            Button(
                onClick = onConfirm,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = ConfirmActionSheetDefaults.MinimumTargetSize),
                colors = if (destructive) {
                    ButtonDefaults.buttonColors(
                        containerColor = colors.error,
                        contentColor = colors.onError,
                    )
                } else {
                    ButtonDefaults.buttonColors(
                        containerColor = colors.primary,
                        contentColor = colors.onPrimary,
                    )
                },
            ) {
                Text(
                    text = confirmLabel,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            Spacer(Modifier.height(Spacing.Sm))
            TextButton(
                onClick = onDismiss,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = ConfirmActionSheetDefaults.MinimumTargetSize),
            ) {
                Text(
                    text = stringResource(R.string.action_cancel),
                    style = MaterialTheme.typography.labelLarge,
                )
            }
        }
    }
}

object ConfirmActionSheetDefaults {
    /** Target táctil mínimo declarado (confirmar/cancelar). */
    val MinimumTargetSize: Dp = 48.dp
    val IconSize: Dp = 24.dp
}

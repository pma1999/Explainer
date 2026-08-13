package com.explainer.app.ui.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.theme.ElevationTokens
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors

/**
 * Banner de estado sin conexión ("Sin conexión — mostrando proyectos
 * disponibles offline"), visible en el borde superior de biblioteca/lector.
 *
 * Copia y tratamiento del banner de la web (frontend/index.html L31-34,
 * `role="alert" aria-live="polite"`): aquí `liveRegion = Polite`. El icono
 * de nube tachada es decorativo; el texto es lo que lee TalkBack.
 *
 * @param text copia del banner (por defecto la compartida en strings.xml).
 * @param showStatusDot conserva el punto de estado junto al texto (default);
 *   con `false` se omite el marcador visual.
 * @param onDismiss acción opcional para ocultar el banner (botón "Cerrar").
 */
@Composable
fun OfflineBanner(
    modifier: Modifier = Modifier,
    text: String = stringResource(R.string.offline_banner_text),
    showStatusDot: Boolean = true,
    onDismiss: (() -> Unit)? = null,
) {
    val colors = MaterialTheme.explainerColors
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .semantics { liveRegion = LiveRegionMode.Polite },
        color = colors.status.offlineContainer,
        contentColor = colors.status.onOfflineContainer,
        tonalElevation = ElevationTokens.Level0,
    ) {
        Row(
            modifier = Modifier.padding(
                horizontal = Spacing.Lg,
                vertical = Spacing.Md,
            ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (showStatusDot) {
                Icon(
                    imageVector = ExplainerIcons.CloudOff,
                    contentDescription = null,
                    tint = colors.status.onOfflineContainer,
                    modifier = Modifier.size(OfflineBannerDefaults.IconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
            }
            Text(
                text = text,
                style = MaterialTheme.typography.bodyMedium,
                color = colors.status.onOfflineContainer,
                modifier = Modifier.weight(1f, fill = false),
            )
            if (onDismiss != null) {
                Spacer(Modifier.width(Spacing.Sm))
                TextButton(onClick = onDismiss) {
                    Text(
                        text = stringResource(R.string.action_close),
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
        }
    }
}

object OfflineBannerDefaults {
    /** Altura mínima declarada del banner (contenido + padding vertical). */
    val MinimumHeight: Dp = 48.dp
    val IconSize: Dp = 18.dp
}

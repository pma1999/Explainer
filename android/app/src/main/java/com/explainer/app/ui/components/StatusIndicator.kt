package com.explainer.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.ui.theme.ExplainerColors
import com.explainer.app.ui.theme.explainerColors

/** Tono semántico de un estado; nunca es la única vía de información. */
enum class StatusTone { SUCCESS, WARNING, ERROR, OFFLINE, NEUTRAL }

/**
 * R-T13-02: color de texto inherente del indicador para su contenedor
 * on-container (nunca el secundario genérico forzado): cada tono usa su rol
 * on-container, que garantiza AA sobre el contenedor del tono. El label del
 * banner offline vive sobre `offlineContainer`; forzar `onSurfaceVariant`
 * fallaba en LIGHT (4.25:1) y el rol on-container pasa con holgura también
 * sobre la superficie de las filas. NEUTRAL no tiene contenedor propio y usa
 * el secundario del tema.
 */
internal fun StatusTone.labelColor(colors: ExplainerColors): Color = when (this) {
    StatusTone.SUCCESS -> colors.status.onSuccessContainer
    StatusTone.WARNING -> colors.status.onWarningContainer
    StatusTone.ERROR -> colors.onErrorContainer
    StatusTone.OFFLINE -> colors.status.onOfflineContainer
    StatusTone.NEUTRAL -> colors.onSurfaceVariant
}

/**
 * Indicador de estado: punto de color + etiqueta textual.
 *
 * El significado nunca depende solo del color: el [label] siempre acompaña al
 * punto. El punto es decorativo (sin semántica); la etiqueta textual es lo que
 * lee TalkBack.
 *
 * @param tone tono semántico (mapeado a los colores del tema).
 * @param label etiqueta textual del estado (p. ej. "Descargado", "Actualizando").
 * @param showDot oculta el punto para variantes compactas; el texto persiste.
 */
@Composable
fun StatusIndicator(
    tone: StatusTone,
    label: String,
    modifier: Modifier = Modifier,
    showDot: Boolean = true,
    dotSize: Dp = StatusIndicatorDefaults.DotSize,
) {
    val colors = MaterialTheme.explainerColors
    val dotColor = when (tone) {
        StatusTone.SUCCESS -> colors.status.success
        StatusTone.WARNING -> colors.status.warning
        StatusTone.ERROR -> colors.error
        StatusTone.OFFLINE -> colors.status.offline
        StatusTone.NEUTRAL -> colors.onSurfaceVariant
    }
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(StatusIndicatorDefaults.Gap),
    ) {
        if (showDot) {
            Box(
                modifier = Modifier
                    .size(dotSize)
                    .background(color = dotColor, shape = CircleShape)
                    .clearAndSetSemantics {},
            )
        }
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            // R-T13-02: rol on-container del tono (AA sobre el contenedor
            // real), no el secundario genérico forzado.
            color = tone.labelColor(colors),
        )
    }
}

object StatusIndicatorDefaults {
    /** Target táctil mínimo declarado: el indicador no es interactivo, pero el
     *  alto de fila donde vive nunca baja de [MinimumTargets.Row]. */
    val MinimumTargetSize = 48.dp
    val DotSize = 8.dp
    val Gap = 8.dp
}

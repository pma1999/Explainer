package com.explainer.app.ui.components

import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.theme.MotionTokens
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors

/**
 * Fila de progreso de descarga/actualización con el invariante
 * "estimado vs exacto" (global-constraints.md Download): si [totalBytes] es
 * null el total es desconocido (progreso indeterminado) y la copia dice
 * "estimado"; con total exacto se muestra el porcentaje y bytes reales.
 *
 * Presentacional: el host decide estados de red/descarga; nunca inicia
 * WorkManager ni red.
 *
 * @param title nombre del proyecto.
 * @param downloadedBytes bytes recibidos (exactos).
 * @param totalBytes total conocido; null = total aún desconocido (estimado).
 * @param isEstimate true → la copia rotula la cifra como estimada.
 * @param onCancel acción de cancelación (target >= 48dp).
 * @param cancelEnabled habilita la cancelación (p. ej. tras cancelar se
 *   deshabilita y el estado "cancelado" lo muestra el host).
 */
@Composable
fun DownloadProgressRow(
    title: String,
    downloadedBytes: Long,
    totalBytes: Long?,
    modifier: Modifier = Modifier,
    isEstimate: Boolean = false,
    onCancel: (() -> Unit)? = null,
    cancelEnabled: Boolean = true,
) {
    val colors = MaterialTheme.explainerColors
    val fraction = if (totalBytes != null && totalBytes > 0L) {
        (downloadedBytes.toFloat() / totalBytes.toFloat()).coerceIn(0f, 1f)
    } else {
        null
    }
    val progressLabel = if (fraction != null) {
        val percent = (fraction * 100).toInt()
        if (isEstimate) {
            stringResource(R.string.download_progress_estimated, percent)
        } else {
            stringResource(R.string.download_progress_exact, percent)
        }
    } else {
        stringResource(R.string.download_progress_indeterminate)
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Lg, vertical = Spacing.Md)
            .animateContentSize(animationSpec = tween(MotionTokens.NormalMs)),
        verticalArrangement = Arrangement.spacedBy(Spacing.Sm),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = ExplainerIcons.Download,
                contentDescription = null,
                tint = colors.primary,
                modifier = Modifier.size(DownloadProgressRowDefaults.IconSize),
            )
            Spacer(Modifier.width(Spacing.Md))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                )
                Text(
                    text = progressLabel,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (onCancel != null) {
                TextButton(
                    onClick = onCancel,
                    enabled = cancelEnabled,
                    modifier = Modifier.heightIn(min = DownloadProgressRowDefaults.MinimumTargetSize),
                ) {
                    Text(
                        text = stringResource(R.string.action_cancel),
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
        }
        val progressLambda: (() -> Float)? = if (fraction != null) {
            { fraction }
        } else {
            null
        }
        if (progressLambda != null) {
            LinearProgressIndicator(
                progress = progressLambda,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics {
                        progressBarRangeInfo = ProgressBarRangeInfo(
                            current = downloadedBytes.toFloat(),
                            range = 0f..(totalBytes?.toFloat() ?: 1f),
                        )
                    },
                color = colors.primary,
                trackColor = colors.surfaceContainerHighest,
            )
        } else {
            // Total desconocido: barra indeterminada (sin parámetro progress).
            LinearProgressIndicator(
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics {
                        progressBarRangeInfo = ProgressBarRangeInfo(
                            current = downloadedBytes.toFloat(),
                            range = 0f..1f,
                        )
                    },
                color = colors.primary,
                trackColor = colors.surfaceContainerHighest,
            )
        }
    }
}

object DownloadProgressRowDefaults {
    /** Target táctil mínimo declarado para el botón Cancelar. */
    val MinimumTargetSize: Dp = 48.dp
    val IconSize: Dp = 18.dp
}

package com.explainer.app.ui.content

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.theme.MinimumTargets
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors
import com.explainer.app.ui.theme.readingTypography

/**
 * Mapa de recursos (tab `recursos`, T08): título, visión general, ejes
 * temáticos con sus recursos y nota de integridad. Las URLs aprobadas por
 * [SafeExternalUrlPolicy] (http/https con host válido) se ofrecen como enlace
 * externo despachando el resultado validado; cualquier otro esquema recibe
 * feedback accesible (stateDescription con el string de rechazo del
 * contrato) en lugar de omitirse silenciosamente (remediación R-T08-02).
 * Texto seleccionable, targets >= 48dp.
 */
@Composable
fun ResourcesContent(
    model: PartRenderModel,
    onLink: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    when (model) {
        is PartRenderModel.Resources -> ResourcesBody(model, onLink, modifier)
        is PartRenderModel.Missing -> PartStateContent(model, modifier)
        is PartRenderModel.AgentError -> PartStateContent(model, modifier)
        is PartRenderModel.Malformed -> PartStateContent(model, modifier)
        else -> Unit
    }
}

@Composable
private fun ResourcesBody(model: PartRenderModel.Resources, onLink: (String) -> Unit, modifier: Modifier = Modifier) {
    val colors = MaterialTheme.explainerColors
    // Feedback accesible para URLs rechazadas (remediación R-T08-02): el
    // string del contrato, anunciado por TalkBack vía stateDescription.
    val rejectedMessage = stringResource(R.string.content_link_rejected_message)
    SelectionContainer {
        Column(modifier = modifier.fillMaxWidth()) {
            Text(
                text = model.titulo ?: stringResource(R.string.content_resources_default_title),
                style = MaterialTheme.readingTypography.heading2,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.semantics { heading() },
            )
            model.visionGeneral?.let { vision ->
                Spacer(Modifier.height(Spacing.Sm))
                Text(
                    text = vision,
                    style = MaterialTheme.readingTypography.body,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }

            model.ejes.forEach { eje ->
                Spacer(Modifier.height(Spacing.Xl))
                eje.nombreEje?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.readingTypography.heading3,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.semantics { heading() },
                    )
                }
                eje.recursos.forEach { recurso ->
                    Spacer(Modifier.height(Spacing.Md))
                    Surface(
                        color = colors.surfaceContainerHigh,
                        shape = MaterialTheme.shapes.medium,
                    ) {
                        Column(modifier = Modifier.padding(Spacing.Lg)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                recurso.formato?.let { formato ->
                                    Surface(
                                        color = colors.primaryContainer,
                                        shape = MaterialTheme.shapes.small,
                                    ) {
                                        Text(
                                            text = formato,
                                            style = MaterialTheme.typography.labelMedium,
                                            color = colors.onPrimaryContainer,
                                            modifier = Modifier.padding(horizontal = Spacing.Sm, vertical = Spacing.Xs),
                                        )
                                    }
                                    Spacer(Modifier.width(Spacing.Md))
                                }
                                recurso.titulo?.let {
                                    Text(
                                        text = it,
                                        style = MaterialTheme.typography.titleMedium,
                                        color = MaterialTheme.colorScheme.onSurface,
                                    )
                                }
                            }
                            recurso.autorCreador?.let {
                                Spacer(Modifier.height(Spacing.Xs))
                                Text(
                                    text = it,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            recurso.tipoYDatos?.let {
                                Spacer(Modifier.height(Spacing.Xs))
                                Text(
                                    text = it,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            recurso.conexionConTexto?.let {
                                Spacer(Modifier.height(Spacing.Sm))
                                Text(
                                    text = it,
                                    style = MaterialTheme.readingTypography.body,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(top = Spacing.Sm),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                recurso.nivelYAccesibilidad?.let {
                                    Text(
                                        text = it,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                recurso.idioma?.let {
                                    Text(
                                        text = it,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                            recurso.nota?.let {
                                Spacer(Modifier.height(Spacing.Sm))
                                Text(
                                    text = it,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = colors.status.warning,
                                )
                            }
                            // Solo http/https se ofrecen como enlace externo
                            // (despachando el resultado validado de la
                            // política); el resto recibe feedback accesible en
                            // vez de omitirse silenciosamente.
                            val safeUrl = SafeExternalUrlPolicy.safeExternalUriStringOrNull(recurso.url)
                            if (safeUrl != null) {
                                Spacer(Modifier.height(Spacing.Md))
                                OutlinedButton(
                                    onClick = { onLink(safeUrl) },
                                    modifier = Modifier.heightIn(min = MinimumTargets.ActionButton),
                                ) {
                                    Icon(
                                        imageVector = com.explainer.app.ui.components.ExplainerIcons.OpenInNew,
                                        contentDescription = null,
                                        tint = MaterialTheme.colorScheme.primary,
                                        modifier = Modifier.size(ResourcesDefaults.ActionIconSize),
                                    )
                                    Spacer(Modifier.width(Spacing.Sm))
                                    Text(
                                        text = stringResource(R.string.content_resources_open),
                                        style = MaterialTheme.typography.labelLarge,
                                    )
                                }
                            } else {
                                recurso.url?.let { rejected ->
                                    Spacer(Modifier.height(Spacing.Md))
                                    Text(
                                        text = rejected,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = colors.status.warning,
                                        modifier = Modifier.semantics {
                                            stateDescription = rejectedMessage
                                        },
                                    )
                                }
                            }
                        }
                    }
                }
            }

            model.notaIntegridad?.let { nota ->
                Spacer(Modifier.height(Spacing.Xl))
                HorizontalDivider(color = colors.outlineVariant)
                Spacer(Modifier.height(Spacing.Lg))
                Text(
                    text = stringResource(R.string.content_resources_integrity_label),
                    style = MaterialTheme.typography.labelLarge,
                    color = colors.primary,
                )
                Text(
                    text = nota,
                    style = MaterialTheme.readingTypography.body,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

private object ResourcesDefaults {
    val ActionIconSize: Dp = 18.dp
}

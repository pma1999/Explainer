package com.explainer.app.ui.content

import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.explainer.app.R
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors
import com.explainer.app.ui.theme.readingTypography

/**
 * Recorrido anotado (tab `recorrido`, T08): entradas con ubicación/tipo,
 * cita, traducción, apuntes y anotación; síntesis de cobertura al final.
 * Paridad de labels/orden con `projectView.js renderRecorrido`. Texto
 * seleccionable y headings semánticos para TalkBack.
 */
@Composable
fun WalkthroughContent(
    model: PartRenderModel,
    modifier: Modifier = Modifier,
) {
    when (model) {
        is PartRenderModel.Walkthrough -> WalkthroughBody(model, modifier)
        is PartRenderModel.Missing -> PartStateContent(model, modifier)
        is PartRenderModel.AgentError -> PartStateContent(model, modifier)
        is PartRenderModel.Malformed -> PartStateContent(model, modifier)
        else -> Unit
    }
}

@Composable
private fun WalkthroughBody(model: PartRenderModel.Walkthrough, modifier: Modifier = Modifier) {
    val colors = MaterialTheme.explainerColors
    SelectionContainer {
        Column(modifier = modifier.fillMaxWidth()) {
            model.entries.forEachIndexed { index, entry ->
                if (index > 0) Spacer(Modifier.height(Spacing.Xl))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.weight(1f, fill = false),
                    ) {
                        // Marcador de paso: la secuencia del recorrido se lee
                        // como pasos numerados (no depende del color).
                        Surface(
                            color = colors.primaryContainer,
                            shape = MaterialTheme.shapes.small,
                        ) {
                            Text(
                                text = stringResource(R.string.content_walkthrough_step_index, index + 1),
                                style = MaterialTheme.typography.labelMedium,
                                color = colors.onPrimaryContainer,
                                modifier = Modifier.padding(horizontal = Spacing.Sm, vertical = Spacing.Xs),
                            )
                        }
                        entry.ubicacion?.let {
                            Spacer(Modifier.width(Spacing.Md))
                            Text(
                                text = it,
                                style = MaterialTheme.typography.titleSmall,
                                color = colors.primary,
                            )
                        }
                    }
                    entry.tipoEntrada?.let { tipo ->
                        val label = if (tipo == "cita_anotada") {
                            stringResource(R.string.content_walkthrough_quote_type)
                        } else {
                            stringResource(R.string.content_walkthrough_content_type)
                        }
                        Text(
                            text = label,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                entry.citaTextual?.let { cita ->
                    Spacer(Modifier.height(Spacing.Sm))
                    Text(
                        text = cita,
                        style = MaterialTheme.readingTypography.quote,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                entry.traduccion?.let { traduccion ->
                    Spacer(Modifier.height(Spacing.Md))
                    Text(
                        text = stringResource(R.string.content_walkthrough_translation_label),
                        style = MaterialTheme.typography.labelLarge,
                        color = colors.primary,
                    )
                    Text(
                        text = traduccion,
                        style = MaterialTheme.readingTypography.body,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                entry.apuntesTraductologicos?.let { apuntes ->
                    Spacer(Modifier.height(Spacing.Md))
                    Text(
                        text = apuntes,
                        style = MaterialTheme.readingTypography.body,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                entry.anotacion?.let { anotacion ->
                    Spacer(Modifier.height(Spacing.Md))
                    Text(
                        text = stringResource(R.string.content_walkthrough_annotation_label),
                        style = MaterialTheme.typography.labelLarge,
                        color = colors.primary,
                    )
                    Text(
                        text = anotacion,
                        style = MaterialTheme.readingTypography.body,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }

            model.sintesis?.let { sintesis ->
                Spacer(Modifier.height(Spacing.Xxl))
                HorizontalDivider(color = colors.outlineVariant)
                Spacer(Modifier.height(Spacing.Lg))
                Text(
                    text = stringResource(R.string.content_walkthrough_synthesis_title),
                    style = MaterialTheme.readingTypography.heading3,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.semantics { heading() },
                )
                Spacer(Modifier.height(Spacing.Sm))
                SynthesisField(R.string.content_walkthrough_sections_processed, sintesis.seccionesProcesadas)
                SynthesisField(R.string.content_walkthrough_scope, sintesis.alcance)
                SynthesisField(R.string.content_walkthrough_excluded, sintesis.contenidoExcluido)
                SynthesisField(R.string.content_walkthrough_original_language, sintesis.idiomaOriginal)
                SynthesisField(R.string.content_walkthrough_global_observations, sintesis.observacionesGlobales)
            }
        }
    }
}

@Composable
private fun SynthesisField(labelRes: Int, value: String?) {
    if (value == null) return
    Spacer(Modifier.height(Spacing.Md))
    Text(
        text = stringResource(labelRes),
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.explainerColors.primary,
    )
    Text(
        text = value,
        style = MaterialTheme.readingTypography.body,
        color = MaterialTheme.colorScheme.onSurface,
    )
}

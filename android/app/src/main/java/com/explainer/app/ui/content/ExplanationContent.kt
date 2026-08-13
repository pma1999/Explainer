package com.explainer.app.ui.content

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
 * Explicación (tab `explicacion`, T08). `_format:'markdown'` se renderiza con
 * el renderer M3 nativo; el JSON estructurado usa headings nativos (T05) y
 * el renderer Markdown para los campos que admiten markdown (paridad
 * `projectView.js renderExplainer`). Texto seleccionable, enlaces gobernados
 * por [SafeExternalUrlPolicy] y estados Missing/AgentError/Malformed
 * accesibles.
 */
@Composable
fun ExplanationContent(
    model: PartRenderModel,
    onLink: (String) -> Unit,
    onRejectedLink: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    when (model) {
        is PartRenderModel.Explanation -> when (val content = model.content) {
            is ExplanationModel.Markdown -> MarkdownBody(
                content = content.content,
                onLink = onLink,
                onRejectedLink = onRejectedLink,
                modifier = modifier,
            )

            is ExplanationModel.Structured -> StructuredExplanation(
                content = content,
                onLink = onLink,
                onRejectedLink = onRejectedLink,
                modifier = modifier,
            )
        }

        is PartRenderModel.Missing -> PartStateContent(model, modifier)
        is PartRenderModel.AgentError -> PartStateContent(model, modifier)
        is PartRenderModel.Malformed -> PartStateContent(model, modifier)
        else -> Unit // otros tabs no llegan aquí (el host enruta por forTab)
    }
}

@Composable
private fun StructuredExplanation(
    content: ExplanationModel.Structured,
    onLink: (String) -> Unit,
    onRejectedLink: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        content.introduccion?.let { intro ->
            MarkdownBody(content = intro, onLink = onLink, onRejectedLink = onRejectedLink)
            Spacer(Modifier.height(Spacing.Lg))
        }
        content.desarrollo.forEach { section ->
            Text(
                text = section.tituloSeccion,
                style = MaterialTheme.readingTypography.heading2,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier
                    .padding(top = Spacing.Md, bottom = Spacing.Sm)
                    .semantics { heading() },
            )
            section.explicacionIntroductoria?.let { intro ->
                MarkdownBody(content = intro, onLink = onLink, onRejectedLink = onRejectedLink)
                Spacer(Modifier.height(Spacing.Sm))
            }
            section.subsecciones.forEach { sub ->
                Text(
                    text = sub.tituloSubseccion,
                    style = MaterialTheme.readingTypography.heading3,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier
                        .padding(top = Spacing.Md, bottom = Spacing.Sm)
                        .semantics { heading() },
                )
                sub.explicacionDetallada?.let { detail ->
                    MarkdownBody(content = detail, onLink = onLink, onRejectedLink = onRejectedLink)
                }
            }
        }
        content.conclusion?.let { conclusion ->
            Spacer(Modifier.height(Spacing.Lg))
            // Conclusión destacada: contenedor cálido con acento dorado (nunca
            // solo color: heading semántico + label explícita).
            Surface(
                color = MaterialTheme.explainerColors.primaryContainer,
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(Spacing.Lg)) {
                    Text(
                        text = stringResource(R.string.content_explainer_conclusion_label),
                        style = MaterialTheme.readingTypography.heading3,
                        color = MaterialTheme.explainerColors.onPrimaryContainer,
                        modifier = Modifier.semantics { heading() },
                    )
                    Spacer(Modifier.height(Spacing.Sm))
                    MarkdownBody(
                        content = conclusion,
                        onLink = onLink,
                        onRejectedLink = onRejectedLink,
                    )
                }
            }
        }
        if (content.conexionesContextuales.isNotEmpty()) {
            Spacer(Modifier.height(Spacing.Xl))
            Text(
                text = stringResource(R.string.content_explainer_connections_label),
                style = MaterialTheme.readingTypography.heading2,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.semantics { heading() },
            )
            content.conexionesContextuales.forEachIndexed { index, cx ->
                Row(
                    modifier = Modifier.padding(top = Spacing.Md, bottom = Spacing.Sm),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Surface(
                        color = MaterialTheme.explainerColors.surfaceContainerHigh,
                        shape = MaterialTheme.shapes.small,
                    ) {
                        Text(
                            text = stringResource(R.string.content_explainer_connection_index, index + 1),
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.explainerColors.primary,
                            modifier = Modifier.padding(horizontal = Spacing.Sm, vertical = Spacing.Xs),
                        )
                    }
                    Spacer(Modifier.width(Spacing.Md))
                    Text(
                        text = cx.seccionTemarioRelacionada,
                        style = MaterialTheme.readingTypography.heading3,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.semantics { heading() },
                    )
                }
                cx.descripcionConexion?.let { desc ->
                    MarkdownBody(content = desc, onLink = onLink, onRejectedLink = onRejectedLink)
                }
            }
        }
    }
}

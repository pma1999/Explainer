package com.explainer.app.ui.content

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
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
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.components.ExplainerIcons
import com.explainer.app.ui.content.mermaid.RegenerateAffordance
import com.explainer.app.ui.theme.MinimumTargets
import com.explainer.app.ui.theme.MotionTokens
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors
import com.explainer.app.ui.theme.readingTypography

/**
 * Repaso activo (tab `repaso`, T08/T14): preguntas con respuesta revelada
 * bajo demanda mediante un botón accesible (label + stateDescription
 * cambiantes, paridad `projectView.js renderReview`). El reveal usa la
 * duración [MotionTokens.EmphasisMs] y no depende del movimiento: la
 * respuesta siempre es alcanzable para TalkBack y con animaciones reducidas.
 *
 * Con [onGenerate] no nulo, la ausencia ofrece el CTA de generación in-app;
 * con [onRegenerate], el contenido ofrece un affordance secundario de
 * regeneración al final del tab.
 */
@Composable
fun ReviewContent(
    model: PartRenderModel,
    modifier: Modifier = Modifier,
    onGenerate: (() -> Unit)? = null,
    onRegenerate: (() -> Unit)? = null,
) {
    when (model) {
        is PartRenderModel.Review -> ReviewBody(model, onRegenerate, modifier)
        is PartRenderModel.Missing -> PartStateContent(
            model = model,
            modifier = modifier,
            onGenerate = onGenerate,
            generateLabel = onGenerate?.let { stringResource(R.string.generation_generate_review) },
        )

        is PartRenderModel.AgentError -> PartStateContent(model, modifier)
        is PartRenderModel.Malformed -> PartStateContent(model, modifier)
        else -> Unit
    }
}

@Composable
private fun ReviewBody(
    model: PartRenderModel.Review,
    onRegenerate: (() -> Unit)?,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.explainerColors
    Column(modifier = modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = ExplainerIcons.Quiz,
                contentDescription = null,
                tint = colors.primary,
                modifier = Modifier.size(ReviewDefaults.KickerIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = stringResource(R.string.content_review_kicker),
                style = MaterialTheme.typography.labelLarge,
                color = colors.primary,
            )
        }
        Text(
            text = stringResource(R.string.content_review_title),
            style = MaterialTheme.readingTypography.heading2,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.semantics { heading() },
        )
        Text(
            text = stringResource(R.string.content_review_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        model.preguntas.forEachIndexed { index, question ->
            Spacer(Modifier.height(Spacing.Lg))
            ReviewCard(question = question, index = index)
        }

        model.nota?.let { nota ->
            Spacer(Modifier.height(Spacing.Xl))
            Surface(color = colors.surfaceContainerHigh, shape = MaterialTheme.shapes.medium) {
                Column(modifier = Modifier.padding(Spacing.Lg)) {
                    Text(
                        text = stringResource(R.string.content_review_note_label),
                        style = MaterialTheme.typography.labelLarge,
                        color = colors.primary,
                    )
                    Spacer(Modifier.height(Spacing.Xs))
                    Text(
                        text = nota,
                        style = MaterialTheme.readingTypography.body,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }

        if (onRegenerate != null) {
            Spacer(Modifier.height(Spacing.Xl))
            RegenerateAffordance(
                label = stringResource(R.string.generation_regenerate_review),
                onRegenerate = onRegenerate,
            )
        }
    }
}

@Composable
private fun ReviewCard(question: ReviewQuestion, index: Int) {
    val colors = MaterialTheme.explainerColors
    var revealed by remember { mutableStateOf(false) }
    val revealLabel = stringResource(R.string.content_review_reveal_answer)
    val hideLabel = stringResource(R.string.content_review_hide_answer)

    Surface(
        color = colors.surfaceContainerHigh,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(modifier = Modifier.padding(Spacing.Lg)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    color = colors.primaryContainer,
                    shape = MaterialTheme.shapes.small,
                ) {
                    Text(
                        text = question.numero?.let {
                            stringResource(R.string.content_review_question_label, it)
                        } ?: stringResource(R.string.content_review_question_unnumbered),
                        style = MaterialTheme.typography.labelMedium,
                        color = colors.onPrimaryContainer,
                        modifier = Modifier.padding(horizontal = Spacing.Sm, vertical = Spacing.Xs),
                    )
                }
            }
            Spacer(Modifier.height(Spacing.Sm))
            SelectionContainer {
                Text(
                    text = question.pregunta ?: "",
                    style = MaterialTheme.readingTypography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            Spacer(Modifier.height(Spacing.Md))
            Button(
                onClick = { revealed = !revealed },
                modifier = Modifier
                    .heightIn(min = MinimumTargets.ActionButton)
                    .semantics {
                        stateDescription = if (revealed) hideLabel else revealLabel
                    },
            ) {
                Icon(
                    imageVector = if (revealed) ExplainerIcons.KeyboardArrowUp else ExplainerIcons.KeyboardArrowDown,
                    contentDescription = null,
                    modifier = Modifier.size(ReviewDefaults.RevealIconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
                Text(
                    text = if (revealed) hideLabel else revealLabel,
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            // Reveal con la duración de énfasis del sistema (MotionTokens);
            // con animaciones reducidas Compose lo degrada a aparición inmediata.
            AnimatedVisibility(
                visible = revealed,
                enter = fadeIn(animationSpec = tween(MotionTokens.EmphasisMs)) +
                    slideInVertically(animationSpec = tween(MotionTokens.EmphasisMs)) { it / 8 },
                exit = fadeOut(animationSpec = tween(MotionTokens.FastMs)),
            ) {
                Column(modifier = Modifier.padding(top = Spacing.Md)) {
                    Text(
                        text = stringResource(R.string.content_review_answer_label),
                        style = MaterialTheme.typography.labelMedium,
                        color = colors.primary,
                    )
                    Spacer(Modifier.height(Spacing.Xs))
                    SelectionContainer {
                        Text(
                            text = question.respuestaRazonada ?: "",
                            style = MaterialTheme.readingTypography.body,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                    question.referencia?.let { referencia ->
                        Spacer(Modifier.height(Spacing.Sm))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = ExplainerIcons.Info,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(ReviewDefaults.RefIconSize),
                            )
                            Spacer(Modifier.width(Spacing.Sm))
                            Text(
                                text = stringResource(R.string.content_review_reference_label) + ": $referencia",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
    }
}

private object ReviewDefaults {
    val KickerIconSize = 16.dp
    val RevealIconSize = 18.dp
    val RefIconSize = 14.dp
}

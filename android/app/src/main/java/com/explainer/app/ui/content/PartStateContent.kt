package com.explainer.app.ui.content

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.ui.components.ExplainerIcons
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors

/**
 * Estados no-render de un tab (T08): ausencia, error de agente y contenido
 * malformado. Siempre accesibles (TalkBack lee título + mensaje) y nunca
 * pantalla en blanco.
 *
 * En los tabs generables (`esquema`/`repaso`, T14) la ausencia ofrece un CTA
 * prominente de generación in-app ("Generar esquema"/"Repasar esta sección")
 * en lugar de remitir a la web; el resto de tabs conservan la copia de
 * actualización de descarga.
 */
@Composable
internal fun PartStateContent(
    model: PartRenderModel.Missing,
    modifier: Modifier = Modifier,
    onGenerate: (() -> Unit)? = null,
    generateLabel: String? = null,
) {
    if (onGenerate != null) {
        MissingGenerateState(
            title = stringResource(missingTitle(model.tab)),
            message = stringResource(missingGenerateMessage(model.tab)),
            icon = missingIcon(model.tab),
            actionLabel = generateLabel ?: stringResource(missingGenerateAction(model.tab)),
            onGenerate = onGenerate,
            modifier = modifier,
        )
    } else {
        StateText(title = stringResource(missingTitle(model.tab)), message = stringResource(R.string.content_missing_generate_web), modifier = modifier)
    }
}

/**
 * Estado de tab generable sin contenido: icono de marca, título, mensaje y
 * CTA primario de generación (target >= 48dp). Centrado verticalmente para
 * que el tab nunca se sienta vacío.
 */
@Composable
private fun MissingGenerateState(
    title: String,
    message: String,
    icon: ImageVector,
    actionLabel: String,
    onGenerate: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.explainerColors
    Column(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = MissingStateDefaults.MinHeight)
            .padding(horizontal = Spacing.Xl, vertical = Spacing.Xxl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = colors.primary,
            modifier = Modifier.size(MissingStateDefaults.IconSize),
        )
        Spacer(Modifier.height(Spacing.Lg))
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
            modifier = Modifier.semantics { heading() },
        )
        Spacer(Modifier.height(Spacing.Sm))
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(Spacing.Xl))
        Button(
            onClick = onGenerate,
            modifier = Modifier.heightIn(min = MissingStateDefaults.MinimumActionHeight),
        ) {
            Text(
                text = actionLabel,
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}

@Composable
internal fun PartStateContent(
    model: PartRenderModel.AgentError,
    modifier: Modifier = Modifier,
) {
    StateText(
        title = stringResource(R.string.content_agent_error_title),
        message = model.message,
        modifier = modifier,
        errorTone = true,
    )
}

@Composable
internal fun PartStateContent(
    model: PartRenderModel.Malformed,
    modifier: Modifier = Modifier,
) {
    StateText(
        title = stringResource(R.string.content_malformed_title),
        message = model.message,
        modifier = modifier,
    )
}

@Composable
private fun StateText(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    errorTone: Boolean = false,
) {
    val colors = MaterialTheme.explainerColors
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Lg, vertical = Spacing.Xl),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = if (errorTone) colors.error else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.semantics { heading() },
        )
        Spacer(Modifier.height(Spacing.Sm))
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Start,
        )
    }
}

private fun missingTitle(tab: ReaderTab): Int = when (tab) {
    ReaderTab.EXPLANATION -> R.string.content_explanation_missing_title
    ReaderTab.WALKTHROUGH -> R.string.content_walkthrough_missing_title
    ReaderTab.RESOURCES -> R.string.content_resources_missing_title
    ReaderTab.DIAGRAM -> R.string.content_diagram_missing_title
    ReaderTab.REVIEW -> R.string.content_review_missing_title
}

private fun missingGenerateMessage(tab: ReaderTab): Int = when (tab) {
    ReaderTab.DIAGRAM -> R.string.generation_missing_diagram_message
    ReaderTab.REVIEW -> R.string.generation_missing_review_message
    else -> R.string.content_missing_generate_web
}

private fun missingGenerateAction(tab: ReaderTab): Int = when (tab) {
    ReaderTab.DIAGRAM -> R.string.generation_generate_diagram
    ReaderTab.REVIEW -> R.string.generation_generate_review
    else -> R.string.action_retry
}

private fun missingIcon(tab: ReaderTab): ImageVector = when (tab) {
    ReaderTab.EXPLANATION -> ExplainerIcons.MenuBook
    ReaderTab.WALKTHROUGH -> ExplainerIcons.Map
    ReaderTab.RESOURCES -> ExplainerIcons.Link
    ReaderTab.DIAGRAM -> ExplainerIcons.AccountTree
    ReaderTab.REVIEW -> ExplainerIcons.Quiz
}

object MissingStateDefaults {
    /** Altura mínima del estado generable para que el CTA quede visible. */
    val MinHeight: Dp = 280.dp
    val IconSize: Dp = 40.dp
    /** Target táctil mínimo declarado del CTA de generación. */
    val MinimumActionHeight: Dp = 48.dp
}

package com.explainer.app.ui.content

import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.UriHandler
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.style.TextDecoration
import com.explainer.app.ui.theme.ExplainerFonts
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors
import com.explainer.app.ui.theme.readingTypography
import com.mikepenz.markdown.model.DefaultMarkdownColors
import com.mikepenz.markdown.model.DefaultMarkdownTypography
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.model.NoOpImageTransformerImpl

/**
 * Cuerpo Markdown nativo (T08): renderer M3 `0.41.0` con la paleta y
 * tipografía de lectura de T05, texto seleccionable, bloques de código con
 * scroll horizontal (provisto por el renderer), sin image transformer (no se
 * descargan imágenes remotas de forma implícita) y enlaces gobernados por
 * [SafeExternalUrlPolicy] vía un [UriHandler] propio.
 *
 * @param onLink enlace http/https aprobado por la política (string canónico
 *   del Uri validado), para abrirlo en una app externa (lo decide el host).
 * @param onRejectedLink enlace rechazado por la política; es **obligatorio**
 *   para garantizar feedback accesible (remediación R-T08-02): el host lo
 *   convierte en p. ej. un snackbar.
 */
@Composable
fun MarkdownBody(
    content: String,
    onLink: (String) -> Unit,
    onRejectedLink: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MaterialTheme.explainerColors
    val reading = MaterialTheme.readingTypography

    val mdColors = DefaultMarkdownColors(
        text = colors.onSurface,
        codeBackground = colors.surfaceVariant,
        inlineCodeBackground = colors.surfaceVariant,
        dividerColor = colors.outlineVariant,
        tableBackground = colors.surfaceContainerHigh,
    )
    val linkStyle = TextLinkStyles(
        style = reading.body.copy(
            color = colors.primary,
            textDecoration = TextDecoration.Underline,
        ).toSpanStyle(),
    )
    // T13: colores de texto explícitos del tema (tinta/onSurface) para
    // código, citas y tablas; el renderer 0.41.0 no expone token de color de
    // código propio, así que el texto lo gobierna el estilo del tema y no la
    // herencia de LocalContentColor (determinista y AA sobre sus fondos).
    val mdTypography = DefaultMarkdownTypography(
        h1 = reading.heading1,
        h2 = reading.heading2,
        h3 = reading.heading3,
        h4 = reading.heading3.copy(fontSize = reading.heading3.fontSize * 0.95f),
        h5 = reading.heading3.copy(fontSize = reading.heading3.fontSize * 0.9f),
        h6 = reading.heading3.copy(fontSize = reading.heading3.fontSize * 0.85f),
        text = reading.body,
        code = reading.code.copy(color = colors.onSurface),
        inlineCode = reading.code.copy(color = colors.onSurface),
        quote = reading.quote.copy(color = colors.onSurface),
        paragraph = reading.body,
        ordered = reading.body,
        bullet = reading.body,
        list = reading.body,
        textLink = linkStyle,
        table = reading.body,
    )

    val safeHandler = rememberSafeUriHandler(onLink, onRejectedLink)

    CompositionLocalProvider(LocalUriHandler provides safeHandler) {
        SelectionContainer {
            Markdown(
                content = content,
                colors = mdColors,
                typography = mdTypography,
                modifier = modifier.fillMaxWidth(),
                // Sin image transformer: el contenido Markdown no descarga
                // imágenes remotas (NoOpImageTransformerImpl es el default).
                imageTransformer = NoOpImageTransformerImpl(),
                error = { fallbackModifier ->
                    // Cualquier fallo de parse degrada a texto seleccionable.
                    Column(fallbackModifier.padding(vertical = Spacing.Sm)) {
                        Text(
                            text = content,
                            style = reading.body,
                            color = colors.onSurface,
                        )
                    }
                },
            )
        }
    }
}

/** UriHandler que aplica la allowlist antes de abrir externamente. */
@Composable
private fun rememberSafeUriHandler(
    onLink: (String) -> Unit,
    onRejectedLink: (String) -> Unit,
): UriHandler = androidx.compose.runtime.remember(onLink, onRejectedLink) {
    object : UriHandler {
        override fun openUri(uri: String) = dispatchExternalLink(uri, onLink, onRejectedLink)
    }
}

/**
 * Canal de un enlace externo (T08, remediación R-T08-02/R-T08-03): el enlace
 * aprobado se despacha con el resultado validado de la política (una sola
 * pasada), nunca con el String crudo; el rechazado va al callback obligatorio
 * de feedback accesible con el valor crudo (para que el host lo muestre tal
 * cual llegó del contenido generado).
 */
internal fun dispatchExternalLink(
    url: String,
    onLink: (String) -> Unit,
    onRejectedLink: (String) -> Unit,
) {
    val safe = SafeExternalUrlPolicy.safeExternalUriStringOrNull(url)
    if (safe != null) onLink(safe) else onRejectedLink(url)
}

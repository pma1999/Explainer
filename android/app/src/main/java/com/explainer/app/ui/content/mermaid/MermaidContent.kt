package com.explainer.app.ui.content.mermaid

import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.ui.components.ExplainerIcons
import com.explainer.app.ui.content.PartRenderModel
import com.explainer.app.ui.content.PartStateContent
import com.explainer.app.ui.theme.MinimumTargets
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors
import com.explainer.app.ui.theme.readingTypography
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.compose.runtime.rememberCoroutineScope
import java.util.concurrent.atomic.AtomicInteger

/**
 * Esquema visual (tab `esquema`, T08/T14): WebView local endurecida para el
 * diagrama Mermaid (pinch zoom/pan nativo sin controles flotantes), metadatos
 * del agente (`analysis`, `reading_guide`, `synthesis_decisions`) como
 * Composables nativos con headings, y el código fuente siempre disponible,
 * seleccionable y copiable como alternativa (auto-revelado si el render
 * falla). Los estados Missing/AgentError/Malformed son accesibles y nunca
 * pantalla en blanco.
 *
 * Con [onGenerate] no nulo, la ausencia ofrece el CTA de generación in-app;
 * con [onRegenerate], el contenido generado ofrece un affordance secundario
 * de regeneración al final del tab (nunca compite con la acción principal).
 *
 * Descarga del diagrama (paridad web `_downloadSvg`/`_downloadPng`):
 * "Descargar SVG" y "Descargar PNG" usan el canal de EXPORT del wrapper:
 * el SVG se re-renderiza con tema claro fijo, dimensiones numéricas y fondo
 * blanco (nunca el `res.svg` de pantalla, que los visores externos
 * renderizaban negro/vacío) y el PNG se rasteriza en la WebView y se
 * transfiere en trozos. API 29+ escribe en Descargas vía MediaStore sin
 * permisos; API < 29 usa ACTION_CREATE_DOCUMENT (SAF). Ambas se deshabilitan
 * hasta que el render termina y durante una exportación/guardado en curso,
 * con feedback transitorio de éxito/error (rasterización, transporte y
 * guardado diferenciados).
 */
@Composable
fun MermaidContent(
    model: PartRenderModel,
    modifier: Modifier = Modifier,
    onGenerate: (() -> Unit)? = null,
    onRegenerate: (() -> Unit)? = null,
) {
    when (model) {
        is PartRenderModel.Diagram -> DiagramBody(model, onRegenerate, modifier)
        is PartRenderModel.Missing -> PartStateContent(
            model = model,
            modifier = modifier,
            onGenerate = onGenerate,
            generateLabel = onGenerate?.let { stringResource(R.string.generation_generate_diagram) },
        )

        is PartRenderModel.AgentError -> PartStateContent(model, modifier)
        is PartRenderModel.Malformed -> PartStateContent(model, modifier)
        else -> Unit
    }
}

@Composable
private fun DiagramBody(
    model: PartRenderModel.Diagram,
    onRegenerate: (() -> Unit)?,
    modifier: Modifier = Modifier,
) {
    val darkTheme = MaterialTheme.colorScheme.background.luminance() < 0.5f
    // null = render en curso; al terminar, RENDERED/FAILED/UNAVAILABLE
    // (remediación R-T08-01): timeout, página no lista, excepción de
    // evaluación o resultado nulo son fallos visibles, nunca éxito.
    var renderStatus by remember { mutableStateOf<MermaidRenderStatus?>(null) }
    var renderedSvg by remember { mutableStateOf<String?>(null) }
    var codeExpanded by remember { mutableStateOf(false) }
    // Export PNG (paridad web `_downloadPng`): un request nuevo dispara la
    // rasterización en la WebView; la UI lo resetea al recibir el resultado.
    val exportSequence = remember { AtomicInteger(0) }
    var pngExportRequest by remember { mutableStateOf<MermaidPngExportRequest?>(null) }
    var pngExporting by remember { mutableStateOf(false) }
    // Export SVG (paridad web `_downloadSvg`): un request nuevo pide al
    // wrapper el SVG NORMALIZADO del canal de export; la UI lo resetea al
    // recibir el resultado.
    var svgExportRequest by remember { mutableStateOf<MermaidSvgExportRequest?>(null) }
    var svgExporting by remember { mutableStateOf(false) }
    // Último error reportado por el wrapper en result.error, conservado
    // internamente para diagnóstico (hoy se descartaba tras el feedback).
    var exportErrorDiagnostic by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    var feedback by remember { mutableStateOf<DiagramFeedback?>(null) }
    // API < 29: ACTION_CREATE_DOCUMENT (SAF) — payload pendiente del diálogo.
    var pendingSafeSave by remember { mutableStateOf<SafeSavePayload?>(null) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val renderFailed = renderStatus != null && renderStatus != MermaidRenderStatus.RENDERED

    // SAF (API < 29, sin permisos): el usuario elige ubicación/nombre y se
    // escribe el payload pendiente sobre el Uri devuelto. Un launcher por
    // tipo MIME (el contrato fija el tipo y maneja la extensión del archivo).
    fun writePendingSave(uri: android.net.Uri?) {
        val pending = pendingSafeSave
        pendingSafeSave = null
        if (pending == null || uri == null) return // cancelado por el usuario
        scope.launch {
            saving = true
            val ok = withContext(Dispatchers.IO) {
                runCatching {
                    context.contentResolver.openOutputStream(uri)?.use { out -> out.write(pending.bytes) }
                }.isSuccess
            }
            saving = false
            feedback = if (ok) DiagramFeedback.SavedDocument else DiagramFeedback.SaveFailed
        }
    }

    val createSvgDocument = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument(MermaidDiagramSaver.SVG_MIME),
        ::writePendingSave,
    )
    val createPngDocument = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument(MermaidDiagramSaver.PNG_MIME),
        ::writePendingSave,
    )

    // El feedback de guardado/export es transitorio; se restaura solo.
    LaunchedEffect(feedback) {
        if (feedback != null) {
            delay(DiagramDefaults.SaveFeedbackMillis)
            feedback = null
        }
    }

    // Si el render falla (error, timeout, página no lista…), auto-revelar el código.
    LaunchedEffect(renderFailed) {
        if (renderFailed) codeExpanded = true
    }

    // Las descargas solo están disponibles con el diagrama renderizado y se
    // deshabilitan durante una exportación/guardado en curso (evita dobles taps).
    val downloadBusy = pngExporting || svgExporting || saving
    val downloadEnabled = renderStatus == MermaidRenderStatus.RENDERED && renderedSvg != null && !downloadBusy

    Column(modifier = modifier.fillMaxWidth()) {
        model.analysis?.let { analysis ->
            MetadataSection(
                label = stringResource(R.string.content_diagram_analysis),
                text = analysis,
            )
            Spacer(Modifier.height(Spacing.Lg))
        }

        Surface(
            color = MaterialTheme.colorScheme.surface,
            shape = MaterialTheme.shapes.medium,
        ) {
            Column {
                HardenedMermaidWebView(
                    code = model.code,
                    darkTheme = darkTheme,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 240.dp, max = 560.dp),
                    onRenderFinished = { result ->
                        renderStatus = result.renderStatus()
                        renderedSvg = result?.svg
                    },
                    pngExportRequest = pngExportRequest,
                    onPngExportFinished = { result ->
                        pngExporting = false
                        pngExportRequest = null
                        exportErrorDiagnostic = result?.error
                        val dataUrl = result?.takeIf { it.ok }?.png
                        if (dataUrl == null) {
                            // Fallo del wrapper ({ok:false}) = rasterización;
                            // null/timeout/metadatos/trozos inválidos =
                            // transporte. Feedback diferenciado.
                            feedback = if (result == null || result.transportFailure) {
                                DiagramFeedback.ExportTransportFailed
                            } else {
                                DiagramFeedback.ExportFailed
                            }
                            return@HardenedMermaidWebView
                        }
                        scope.launch {
                            val bytes = withContext(Dispatchers.IO) {
                                MermaidDiagramSaver.decodePngDataUrl(dataUrl)
                            }
                            if (bytes == null) {
                                feedback = DiagramFeedback.SaveFailed
                                return@launch
                            }
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                                saving = true
                                val ok = withContext(Dispatchers.IO) {
                                    MermaidDiagramSaver.saveToDownloads(
                                        context,
                                        MermaidDiagramSaver.PNG_FILE_NAME,
                                        MermaidDiagramSaver.PNG_MIME,
                                        bytes,
                                    )
                                }
                                saving = false
                                feedback = if (ok) {
                                    DiagramFeedback.SavedDownloads
                                } else {
                                    DiagramFeedback.SaveFailed
                                }
                            } else {
                                pendingSafeSave = SafeSavePayload(bytes)
                                createPngDocument.launch(MermaidDiagramSaver.PNG_MIME)
                            }
                        }
                    },
                    svgExportRequest = svgExportRequest,
                    onSvgExportFinished = { result ->
                        svgExporting = false
                        svgExportRequest = null
                        exportErrorDiagnostic = result?.error
                        val svg = result?.takeIf { it.ok }?.svg
                        if (svg == null) {
                            // Fallo del wrapper ({ok:false}) = normalización;
                            // null/timeout = transporte. Feedback diferenciado.
                            feedback = if (result == null) {
                                DiagramFeedback.ExportTransportFailed
                            } else {
                                DiagramFeedback.ExportFailed
                            }
                            return@HardenedMermaidWebView
                        }
                        scope.launch {
                            val bytes = svg.toByteArray(Charsets.UTF_8)
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                                saving = true
                                val ok = withContext(Dispatchers.IO) {
                                    MermaidDiagramSaver.saveToDownloads(
                                        context,
                                        MermaidDiagramSaver.SVG_FILE_NAME,
                                        MermaidDiagramSaver.SVG_MIME,
                                        bytes,
                                    )
                                }
                                saving = false
                                feedback = if (ok) {
                                    DiagramFeedback.SavedDownloads
                                } else {
                                    DiagramFeedback.SaveFailed
                                }
                            } else {
                                pendingSafeSave = SafeSavePayload(bytes)
                                createSvgDocument.launch(MermaidDiagramSaver.SVG_MIME)
                            }
                        }
                    },
                )
                Row(
                    modifier = Modifier.padding(horizontal = Spacing.Lg, vertical = Spacing.Sm),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = ExplainerIcons.OpenInFull,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(DiagramDefaults.HintIconSize),
                    )
                    Spacer(Modifier.width(Spacing.Sm))
                    Text(
                        text = stringResource(R.string.content_diagram_zoom_hint),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        // Estado accesible cuando el render no llegó a completarse.
        if (renderFailed) {
            Spacer(Modifier.height(Spacing.Sm))
            Row(
                modifier = Modifier.padding(horizontal = Spacing.Lg),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = ExplainerIcons.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.explainerColors.status.warning,
                    modifier = Modifier.size(DiagramDefaults.WarningIconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
                Text(
                    text = stringResource(R.string.content_diagram_render_failed),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.explainerColors.status.warning,
                )
            }
        }

        Spacer(Modifier.height(Spacing.Lg))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(Spacing.Sm),
            verticalArrangement = Arrangement.spacedBy(Spacing.Sm),
        ) {
            OutlinedButton(
                onClick = { codeExpanded = !codeExpanded },
                modifier = Modifier.heightIn(min = MinimumTargets.ActionButton),
            ) {
                Text(
                    text = stringResource(
                        if (codeExpanded) R.string.content_diagram_hide_code
                        else R.string.content_diagram_show_code,
                    ),
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            CopyCodeButton(code = model.code)
            DownloadSvgButton(
                enabled = downloadEnabled,
                onClick = {
                    if (svgExporting) return@DownloadSvgButton
                    // El SVG de descarga es el NORMALIZADO del canal de export
                    // (tema claro fijo, dimensiones numéricas, fondo blanco) —
                    // nunca el res.svg de pantalla, que los visores externos
                    // renderizaban negro/vacío.
                    svgExporting = true
                    svgExportRequest = MermaidSvgExportRequest(
                        exportId = "mermaid-svg-export-" + exportSequence.incrementAndGet(),
                    )
                },
            )
            DownloadPngButton(
                enabled = downloadEnabled,
                busy = pngExporting,
                onClick = {
                    if (pngExporting) return@DownloadPngButton
                    pngExporting = true
                    pngExportRequest = MermaidPngExportRequest(
                        exportId = "mermaid-export-" + exportSequence.incrementAndGet(),
                    )
                },
            )
        }
        feedback?.let { fb ->
            Spacer(Modifier.height(Spacing.Sm))
            DiagramFeedbackRow(fb)
        }
        AnimatedVisibility(visible = codeExpanded) {
            DiagramCode(model.code)
        }

        model.readingGuide?.let { guide ->
            Spacer(Modifier.height(Spacing.Lg))
            MetadataSection(
                label = stringResource(R.string.content_diagram_reading_guide),
                text = guide,
            )
        }
        model.synthesisDecisions?.let { decisions ->
            Spacer(Modifier.height(Spacing.Lg))
            MetadataSection(
                label = stringResource(R.string.content_diagram_synthesis_decisions),
                text = decisions,
            )
        }

        if (onRegenerate != null) {
            Spacer(Modifier.height(Spacing.Xl))
            RegenerateAffordance(
                label = stringResource(R.string.generation_regenerate_diagram),
                onRegenerate = onRegenerate,
            )
        }
    }
}

/** Botón de copiar el código del diagrama al portapapeles (target >= 48dp). */
@Composable
private fun CopyCodeButton(code: String) {
    @Suppress("DEPRECATION")
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    var copied by remember { mutableStateOf(false) }
    val copyLabel = stringResource(R.string.content_diagram_copy_code)
    val copiedLabel = stringResource(R.string.content_diagram_copied)
    OutlinedButton(
        onClick = {
            clipboard.setText(androidx.compose.ui.text.AnnotatedString(code))
            copied = true
            // El estado "Copiado" es transitorio; se restaura solo.
            scope.launch {
                delay(DiagramDefaults.CopyFeedbackMillis)
                copied = false
            }
        },
        modifier = Modifier.heightIn(min = MinimumTargets.ActionButton),
    ) {
        Icon(
            imageVector = ExplainerIcons.ContentCopy,
            contentDescription = null,
            modifier = Modifier.size(DiagramDefaults.ActionIconSize),
        )
        Spacer(Modifier.width(Spacing.Sm))
        Text(
            text = if (copied) copiedLabel else copyLabel,
            style = MaterialTheme.typography.labelLarge,
        )
    }
}

/** Botón "Descargar SVG" (paridad web `_downloadSvg`; target >= 48dp). */
@Composable
private fun DownloadSvgButton(enabled: Boolean, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.heightIn(min = MinimumTargets.ActionButton),
    ) {
        Icon(
            imageVector = ExplainerIcons.Download,
            contentDescription = null,
            modifier = Modifier.size(DiagramDefaults.ActionIconSize),
        )
        Spacer(Modifier.width(Spacing.Sm))
        Text(
            text = stringResource(R.string.content_diagram_download_svg),
            style = MaterialTheme.typography.labelLarge,
        )
    }
}

/** Botón "Descargar PNG" (paridad web `_downloadPng`; target >= 48dp). */
@Composable
private fun DownloadPngButton(enabled: Boolean, busy: Boolean, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.heightIn(min = MinimumTargets.ActionButton),
    ) {
        Icon(
            imageVector = ExplainerIcons.Download,
            contentDescription = null,
            modifier = Modifier.size(DiagramDefaults.ActionIconSize),
        )
        Spacer(Modifier.width(Spacing.Sm))
        Text(
            text = stringResource(
                if (busy) R.string.content_diagram_download_generating
                else R.string.content_diagram_download_png,
            ),
            style = MaterialTheme.typography.labelLarge,
        )
    }
}

/** Feedback transitorio del guardado/export del diagrama (éxito o error visible). */
private sealed interface DiagramFeedback {
    /** Guardado directo en Descargas vía MediaStore (API 29+). */
    data object SavedDownloads : DiagramFeedback

    /** Guardado vía selector de archivos (SAF, API < 29). */
    data object SavedDocument : DiagramFeedback

    /** El wrapper no pudo generar el PNG (rasterización) ni normalizar el SVG. */
    data object ExportFailed : DiagramFeedback

    /** El transporte del PNG/SVG falló (timeout, metadatos o trozos inválidos). */
    data object ExportTransportFailed : DiagramFeedback

    /** El guardado falló (MediaStore/SAF/escritura). */
    data object SaveFailed : DiagramFeedback
}

/** Payload que espera el diálogo ACTION_CREATE_DOCUMENT (API < 29). */
private data class SafeSavePayload(val bytes: ByteArray)

@Composable
private fun DiagramFeedbackRow(feedback: DiagramFeedback) {
    val failure = feedback != DiagramFeedback.SavedDownloads &&
        feedback != DiagramFeedback.SavedDocument
    val color = if (failure) {
        MaterialTheme.explainerColors.status.warning
    } else {
        MaterialTheme.explainerColors.status.success
    }
    Row(
        modifier = Modifier.padding(horizontal = Spacing.Lg),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = if (failure) ExplainerIcons.Error else ExplainerIcons.Check,
            contentDescription = null,
            tint = color,
            modifier = Modifier.size(DiagramDefaults.HintIconSize),
        )
        Spacer(Modifier.width(Spacing.Sm))
        Text(
            text = stringResource(
                when (feedback) {
                    DiagramFeedback.SavedDownloads -> R.string.content_diagram_download_saved
                    DiagramFeedback.SavedDocument -> R.string.content_diagram_download_saved_document
                    DiagramFeedback.ExportFailed -> R.string.content_diagram_export_failed
                    DiagramFeedback.ExportTransportFailed -> R.string.content_diagram_export_transport_failed
                    DiagramFeedback.SaveFailed -> R.string.content_diagram_download_failed
                },
            ),
            style = MaterialTheme.typography.bodySmall,
            color = color,
        )
    }
}

/** Affordance secundario de regeneración: discreto, nunca compite con la CTA. */
@Composable
internal fun RegenerateAffordance(
    label: String,
    onRegenerate: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OutlinedButton(
        onClick = onRegenerate,
        modifier = modifier.heightIn(min = MinimumTargets.ActionButton),
    ) {
        Icon(
            imageVector = ExplainerIcons.Refresh,
            contentDescription = null,
            modifier = Modifier.size(DiagramDefaults.ActionIconSize),
        )
        Spacer(Modifier.width(Spacing.Sm))
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
        )
    }
}

/** Código fuente seleccionable y copiable con scroll horizontal (fallback). */
@Composable
private fun DiagramCode(code: String) {
    SelectionContainer {
        Surface(
            color = MaterialTheme.explainerColors.surfaceVariant,
            shape = MaterialTheme.shapes.small,
        ) {
            Text(
                text = code,
                style = MaterialTheme.readingTypography.code,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(Spacing.Md),
            )
        }
    }
}

@Composable
private fun MetadataSection(label: String, text: String) {
    Text(
        text = label,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.explainerColors.primary,
        modifier = Modifier.semantics { heading() },
    )
    Spacer(Modifier.height(Spacing.Xs))
    SelectionContainer {
        Text(
            text = text,
            style = MaterialTheme.readingTypography.body,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

private object DiagramDefaults {
    val HintIconSize = 16.dp
    val WarningIconSize = 16.dp
    val ActionIconSize = 18.dp
    const val CopyFeedbackMillis = 2000L
    const val SaveFeedbackMillis = 2500L
}

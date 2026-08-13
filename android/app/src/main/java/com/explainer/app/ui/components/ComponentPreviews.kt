package com.explainer.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import com.explainer.app.core.model.ReaderTab
import com.explainer.app.ui.content.PartRenderModel
import com.explainer.app.ui.content.PartStateContent
import com.explainer.app.ui.content.ReviewContent
import com.explainer.app.ui.content.mermaid.RegenerateAffordance
import com.explainer.app.ui.reader.GenerationErrorBanner
import com.explainer.app.ui.reader.GenerationErrorPanel
import com.explainer.app.ui.reader.GenerationProgressPanel
import com.explainer.app.ui.theme.ExplainerTheme
import com.explainer.app.ui.theme.ThemeMode
import com.explainer.app.ui.theme.Spacing

/**
 * Previews deterministas de los componentes comunes y de los estados de
 * generación (T14): claro/oscuro explícitos, compact (360dp) y expanded
 * (840dp), y todos los estados operativos (loading/empty/error/offline/
 * downloading, generating/failed de esquema y repaso, missing con CTA).
 * Ninguna preview inicia red, Room ni WorkManager: los callbacks son no-op
 * locales. La WebView Mermaid no se compone en preview (requiere runtime).
 */

private val noOp: () -> Unit = {}

@Preview(name = "Top bar (light)", widthDp = 360, showBackground = true)
@Composable
private fun TopBarLightPreview() = TopBarSample(ThemeMode.LIGHT)

@Preview(name = "Top bar (dark, expanded)", widthDp = 840, showBackground = true)
@Composable
private fun TopBarDarkPreview() = TopBarSample(ThemeMode.DARK)

@Composable
private fun TopBarSample(mode: ThemeMode) {
    ExplainerTheme(mode = mode) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column {
                ExplainerTopBar(title = "Biblioteca", onNavigationClick = noOp)
                Spacer(Modifier.height(Spacing.Sm))
                ExplainerTopBar(title = "Lector")
            }
        }
    }
}

@Preview(name = "Status indicators (light)", widthDp = 360, showBackground = true)
@Composable
private fun StatusIndicatorLightPreview() = StatusIndicatorSample(ThemeMode.LIGHT)

@Preview(name = "Status indicators (dark)", widthDp = 360, showBackground = true)
@Composable
private fun StatusIndicatorDarkPreview() = StatusIndicatorSample(ThemeMode.DARK)

@Composable
private fun StatusIndicatorSample(mode: ThemeMode) {
    ExplainerTheme(mode = mode) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column(
                modifier = Modifier.padding(Spacing.Lg),
                verticalArrangement = Arrangement.spacedBy(Spacing.Md),
            ) {
                StatusIndicator(StatusTone.SUCCESS, "Descargado")
                StatusIndicator(StatusTone.WARNING, "Actualización disponible")
                StatusIndicator(StatusTone.ERROR, "Error al descargar")
                StatusIndicator(StatusTone.OFFLINE, "Disponible sin conexión")
                StatusIndicator(StatusTone.NEUTRAL, "Pendiente")
                StatusIndicator(StatusTone.SUCCESS, "Compacto", showDot = false)
            }
        }
    }
}

@Preview(name = "Offline banner (light)", widthDp = 360, showBackground = true)
@Composable
private fun OfflineBannerLightPreview() = OfflineBannerSample(ThemeMode.LIGHT)

@Preview(name = "Offline banner (dark, expanded)", widthDp = 840, showBackground = true)
@Composable
private fun OfflineBannerDarkPreview() = OfflineBannerSample(ThemeMode.DARK)

@Composable
private fun OfflineBannerSample(mode: ThemeMode) {
    ExplainerTheme(mode = mode) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column {
                OfflineBanner(onDismiss = noOp)
                OfflineBanner(showStatusDot = false)
            }
        }
    }
}

@Preview(name = "State panel: loading (dark)", widthDp = 360, showBackground = true)
@Composable
private fun StateLoadingDarkPreview() = StatePanelSample(ThemeMode.DARK, OperationState.LOADING)

@Preview(name = "State panel: empty (light)", widthDp = 360, showBackground = true)
@Composable
private fun StateEmptyLightPreview() = StatePanelSample(ThemeMode.LIGHT, OperationState.EMPTY)

@Preview(name = "State panel: error (light)", widthDp = 360, showBackground = true)
@Composable
private fun StateErrorLightPreview() = StatePanelSample(ThemeMode.LIGHT, OperationState.ERROR)

@Preview(name = "State panel: offline (dark)", widthDp = 360, showBackground = true)
@Composable
private fun StateOfflineDarkPreview() = StatePanelSample(ThemeMode.DARK, OperationState.OFFLINE)

@Preview(name = "State panel: empty with action (expanded)", widthDp = 840, showBackground = true)
@Composable
private fun StateEmptyActionExpandedPreview() =
    StatePanelSample(ThemeMode.LIGHT, OperationState.EMPTY, withAction = true)

@Composable
private fun StatePanelSample(mode: ThemeMode, state: OperationState, withAction: Boolean = false) {
    ExplainerTheme(mode = mode) {
        Surface(color = MaterialTheme.colorScheme.background) {
            OperationStatePanel(
                state = state,
                onAction = if (withAction) noOp else null,
            )
        }
    }
}

@Preview(name = "Download row: exact (light)", widthDp = 360, showBackground = true)
@Composable
private fun DownloadExactLightPreview() =
    DownloadSample(ThemeMode.LIGHT, total = 10_000_000L, estimate = false)

@Preview(name = "Download row: estimated (dark)", widthDp = 360, showBackground = true)
@Composable
private fun DownloadEstimatedDarkPreview() =
    DownloadSample(ThemeMode.DARK, total = 10_000_000L, estimate = true)

@Preview(name = "Download row: indeterminate (dark)", widthDp = 360, showBackground = true)
@Composable
private fun DownloadIndeterminateDarkPreview() =
    DownloadSample(ThemeMode.DARK, total = null, estimate = true)

@Preview(name = "Download row: cancelled (light)", widthDp = 360, showBackground = true)
@Composable
private fun DownloadCancelledLightPreview() =
    DownloadSample(ThemeMode.LIGHT, total = 10_000_000L, estimate = false, enabled = false)

@Composable
private fun DownloadSample(mode: ThemeMode, total: Long?, estimate: Boolean, enabled: Boolean = true) {
    ExplainerTheme(mode = mode) {
        Surface(color = MaterialTheme.colorScheme.background) {
            DownloadProgressRow(
                title = "Proyecto de ejemplo",
                downloadedBytes = 3_200_000L,
                totalBytes = total,
                isEstimate = estimate,
                onCancel = noOp,
                cancelEnabled = enabled,
            )
        }
    }
}

@Preview(name = "Confirm sheet: destructive (dark)", widthDp = 360, showBackground = true)
@Composable
private fun ConfirmSheetDarkPreview() {
    ExplainerTheme(mode = ThemeMode.DARK) {
        Surface(color = MaterialTheme.colorScheme.background) {
            ConfirmActionSheet(
                title = "¿Borrar la descarga?",
                message = "Se eliminará el contenido offline de este proyecto; " +
                    "en la web no se borra nada.",
                confirmLabel = "Borrar descarga",
                onConfirm = noOp,
                onDismiss = noOp,
                destructive = true,
                icon = ExplainerIcons.Delete,
            )
        }
    }
}

@Preview(name = "Confirm sheet (light)", widthDp = 360, showBackground = true)
@Composable
private fun ConfirmSheetLightPreview() {
    ExplainerTheme(mode = ThemeMode.LIGHT) {
        Surface(color = MaterialTheme.colorScheme.background) {
            ConfirmActionSheet(
                title = "Cerrar sesión",
                message = "Los proyectos descargados quedarán bloqueados hasta " +
                    "que vuelvas a entrar con la misma cuenta.",
                confirmLabel = "Cerrar sesión",
                onConfirm = noOp,
                onDismiss = noOp,
                destructive = false,
                icon = ExplainerIcons.Logout,
            )
        }
    }
}

@Preview(name = "Reader tabs (light)", widthDp = 360, showBackground = true)
@Composable
private fun ReaderTabsLightPreview() = ReaderTabsSample(ThemeMode.LIGHT)

@Preview(name = "Reader tabs (dark, expanded)", widthDp = 840, showBackground = true)
@Composable
private fun ReaderTabsDarkPreview() = ReaderTabsSample(ThemeMode.DARK)

@Composable
private fun ReaderTabsSample(mode: ThemeMode) {
    ExplainerTheme(mode = mode) {
        Surface(color = MaterialTheme.colorScheme.background) {
            ReaderTabStrip(
                selectedTab = "recorrido",
                onTabSelected = {},
            )
        }
    }
}

@Preview(name = "Part pane (compact)", widthDp = 360, showBackground = true)
@Composable
private fun PartPaneCompactPreview() = PartPaneSample(ThemeMode.LIGHT)

@Preview(name = "Part pane (expanded, dark)", widthDp = 840, showBackground = true)
@Composable
private fun PartPaneExpandedDarkPreview() = PartPaneSample(ThemeMode.DARK)

@Composable
private fun PartPaneSample(mode: ThemeMode) {
    ExplainerTheme(mode = mode) {
        Surface(color = MaterialTheme.colorScheme.background) {
            PartNavigationPane(
                items = listOf(
                    PartNavItem(1, "Parte 1 — Fundamentos", "Completada"),
                    PartNavItem(2, "Parte 2 — Método"),
                    PartNavItem(3, "Parte 3 — Aplicación", "En curso"),
                ),
                selectedPartId = 2,
                onPartSelected = {},
                header = "Partes",
            )
        }
    }
}

// ─── Estados de generación (T14) ─────────────────────────────────────────────

@Preview(name = "Generation: progress (dark)", widthDp = 360, showBackground = true)
@Composable
private fun GenerationProgressDarkPreview() {
    ExplainerTheme(mode = ThemeMode.DARK) {
        Surface(color = MaterialTheme.colorScheme.background) {
            GenerationProgressPanel(
                title = "Generando esquema…",
                note = "Puede tardar entre 30 y 60 segundos. Puedes seguir usando la app.",
            )
        }
    }
}

@Preview(name = "Generation: error panel (light)", widthDp = 360, showBackground = true)
@Composable
private fun GenerationErrorLightPreview() {
    ExplainerTheme(mode = ThemeMode.LIGHT) {
        Surface(color = MaterialTheme.colorScheme.background) {
            GenerationErrorPanel(
                title = "No se pudo generar el repaso",
                message = "Sin conexión o el servicio no está disponible ahora. Comprueba tu red y vuelve a intentarlo.",
                onRetry = noOp,
            )
        }
    }
}

@Preview(name = "Generation: error banner sobre contenido (dark)", widthDp = 360, showBackground = true)
@Composable
private fun GenerationErrorBannerDarkPreview() {
    ExplainerTheme(mode = ThemeMode.DARK) {
        Surface(color = MaterialTheme.colorScheme.background) {
            GenerationErrorBanner(
                message = "Sin conexión o el servicio no está disponible ahora. Comprueba tu red y vuelve a intentarlo.",
                onRetry = noOp,
                onDismiss = noOp,
            )
        }
    }
}

@Preview(name = "Generation: missing con CTA (light)", widthDp = 360, showBackground = true)
@Composable
private fun GenerationMissingCtaLightPreview() {
    ExplainerTheme(mode = ThemeMode.LIGHT) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column(modifier = Modifier.padding(Spacing.Lg)) {
                PartStateContent(
                    model = PartRenderModel.Missing(ReaderTab.DIAGRAM),
                    onGenerate = noOp,
                )
            }
        }
    }
}

@Preview(name = "Generation: repaso con regenerar (dark)", widthDp = 360, showBackground = true)
@Composable
private fun ReviewWithRegenerateDarkPreview() {
    ExplainerTheme(mode = ThemeMode.DARK) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column(modifier = Modifier.padding(Spacing.Lg)) {
                ReviewContent(
                    model = PartRenderModel.Review(
                        preguntas = listOf(
                            com.explainer.app.ui.content.ReviewQuestion(
                                numero = 1,
                                pregunta = "¿Cuál es la idea central de esta sección?",
                                respuestaRazonada = "La idea central es…",
                                referencia = "L12",
                            ),
                        ),
                        nota = "Revisa la guía de lectura para afianzar el esquema.",
                    ),
                    onRegenerate = noOp,
                )
            }
        }
    }
}

@Preview(name = "Regenerate affordance (light)", widthDp = 360, showBackground = true)
@Composable
private fun RegenerateAffordanceLightPreview() {
    ExplainerTheme(mode = ThemeMode.LIGHT) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column(modifier = Modifier.padding(Spacing.Lg)) {
                RegenerateAffordance(label = "Regenerar esquema", onRegenerate = noOp)
            }
        }
    }
}

@Preview(name = "Component gallery (dark)", widthDp = 360, showBackground = true)
@Composable
private fun ComponentGalleryDarkPreview() {
    ExplainerTheme(mode = ThemeMode.DARK) {
        Surface(color = MaterialTheme.colorScheme.background) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState()),
            ) {
                ExplainerTopBar(title = "Galería")
                OfflineBanner(showStatusDot = false)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(Spacing.Lg),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.Xl),
                ) {
                    StatusIndicator(StatusTone.SUCCESS, "Descargado")
                    StatusIndicator(StatusTone.ERROR, "Error")
                }
                DownloadProgressRow(
                    title = "Ejemplo",
                    downloadedBytes = 512_000L,
                    totalBytes = 2_000_000L,
                )
                Text(
                    text = "Los estados operativos cubren loading, empty, error, " +
                        "offline, downloading y la generación de esquema/repaso; " +
                        "nada depende solo del color.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(Spacing.Lg),
                )
            }
        }
    }
}

package com.explainer.app.ui.library

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLocale
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.core.model.ProjectId
import com.explainer.app.core.model.ProjectStatus
import com.explainer.app.feature.catalog.ProjectAvailability
import com.explainer.app.feature.download.DownloadError
import com.explainer.app.ui.components.ConfirmActionSheet
import com.explainer.app.ui.components.DownloadProgressRow
import com.explainer.app.ui.components.ExplainerIcons
import com.explainer.app.ui.components.ExplainerTopBar
import com.explainer.app.ui.components.ExplainerTopBarDefaults
import com.explainer.app.ui.components.OfflineBanner
import com.explainer.app.ui.components.OfflineBannerDefaults
import com.explainer.app.ui.components.OperationState
import com.explainer.app.ui.components.OperationStatePanel
import com.explainer.app.ui.components.StatusIndicator
import com.explainer.app.ui.theme.BootstrapTheme
import com.explainer.app.ui.theme.ExplainerTheme
import com.explainer.app.ui.theme.MinimumTargets
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.ThemeMode
import com.explainer.app.ui.theme.explainerColors
import java.time.ZoneOffset

/**
 * Pantalla de biblioteca (T09), stateless: recibe [LibraryUiState] y emite
 * [LibraryAction]. Lista con divisores y jerarquía tipográfica (no mosaico),
 * pull-to-refresh no destructivo, último sync, banner offline, mensajes
 * transitorios y sheets de confirmación (descarga/actualización y borrado
 * local). Cada fila tiene UNA acción primaria dominante (Abrir/Descargar/
 * Actualizar) y secundarias discretas; el estado de la fila nunca depende
 * solo del color. Targets >= 48 dp; filas y acciones no se cortan a 200 %.
 */
@Composable
fun ProjectLibraryScreen(state: LibraryUiState, onAction: (LibraryAction) -> Unit) {
    when (state) {
        LibraryUiState.Loading -> OperationStatePanel(state = OperationState.LOADING)

        LibraryUiState.SignedOut -> OperationStatePanel(
            state = OperationState.ERROR,
            title = stringResource(R.string.session_ended_title),
            message = stringResource(R.string.session_ended_message),
        )

        is LibraryUiState.Content -> LibraryContent(state = state, onAction = onAction)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LibraryContent(state: LibraryUiState.Content, onAction: (LibraryAction) -> Unit) {
    Column(modifier = Modifier.fillMaxSize()) {
        ExplainerTopBar(
            title = stringResource(R.string.library_title),
            action = {
                TextButton(
                    onClick = { onAction(LibraryAction.OpenSettings) },
                    modifier = Modifier.heightIn(min = ExplainerTopBarDefaults.MinimumTargetSize),
                ) {
                    Icon(
                        imageVector = ExplainerIcons.Settings,
                        contentDescription = null,
                        modifier = Modifier.size(LibraryDefaults.ActionIconSize),
                    )
                    Spacer(Modifier.width(Spacing.Xs))
                    Text(
                        text = stringResource(R.string.library_settings_action),
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            },
        )
        if (state.isOffline) {
            OfflineBanner()
        }
        state.message?.let { message ->
            MessageBanner(message = message, onDismiss = { onAction(LibraryAction.DismissMessage) })
        }
        PullToRefreshBox(
            isRefreshing = state.isRefreshing,
            onRefresh = { onAction(LibraryAction.Refresh) },
            modifier = Modifier.fillMaxSize(),
        ) {
            LazyColumn(modifier = Modifier.fillMaxSize()) {
                item(key = "sync") {
                    SyncRow(state = state, onAction = onAction)
                }
                if (state.rows.isEmpty() && !state.isRefreshing) {
                    item(key = "empty") { EmptyLibraryPanel(onRefresh = { onAction(LibraryAction.Refresh) }) }
                }
                items(state.rows, key = { it.projectId.value }) { row ->
                    ProjectRow(
                        row = row,
                        onOpen = { onAction(LibraryAction.OpenProject(row.projectId)) },
                        onDownload = { onAction(LibraryAction.Download(row.projectId)) },
                        onDelete = { onAction(LibraryAction.DeleteLocal(row.projectId)) },
                        onCancel = { onAction(LibraryAction.CancelDownload(row.projectId)) },
                    )
                    HorizontalDivider()
                }
            }
        }
        state.confirmation?.let { confirmation ->
            DownloadConfirmationSheet(
                confirmation = confirmation,
                onConfirm = { onAction(LibraryAction.ConfirmDownload(confirmation.projectId)) },
                onDismiss = { onAction(LibraryAction.DismissSheet) },
            )
        }
        state.deleteTarget?.let { target ->
            ConfirmActionSheet(
                title = stringResource(R.string.delete_title, target.name),
                message = stringResource(R.string.delete_message),
                confirmLabel = stringResource(R.string.library_delete),
                destructive = true,
                icon = ExplainerIcons.Delete,
                onConfirm = { onAction(LibraryAction.ConfirmDeleteLocal(target.projectId)) },
                onDismiss = { onAction(LibraryAction.DismissSheet) },
            )
        }
    }
}

/** Estado vacío memorable: icono, copia y acción de sincronizar. */
@Composable
private fun EmptyLibraryPanel(onRefresh: () -> Unit) {
    val colors = MaterialTheme.explainerColors
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Xl, vertical = Spacing.Xxl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = ExplainerIcons.Inbox,
            contentDescription = null,
            tint = colors.primary,
            modifier = Modifier.size(LibraryDefaults.EmptyIconSize),
        )
        Spacer(Modifier.height(Spacing.Lg))
        Text(
            text = stringResource(R.string.state_empty_title),
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(Spacing.Sm))
        Text(
            text = stringResource(R.string.state_empty_message),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(Spacing.Xl))
        Button(
            onClick = onRefresh,
            modifier = Modifier.heightIn(min = MinimumTargets.ActionButton),
        ) {
            Icon(
                imageVector = ExplainerIcons.Refresh,
                contentDescription = null,
                modifier = Modifier.size(LibraryDefaults.ActionIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = stringResource(R.string.library_sync),
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}

/** Fila de último sync + acción de sincronizar (además del pull-to-refresh). */
@Composable
private fun SyncRow(state: LibraryUiState.Content, onAction: (LibraryAction) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Lg, vertical = Spacing.Sm),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = ExplainerIcons.Storage,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(LibraryDefaults.MetaIconSize),
        )
        Spacer(Modifier.width(Spacing.Sm))
        Text(
            text = lastSyncLabel(state.lastSyncAtMillis),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        if (state.isRefreshing) {
            CircularProgressIndicator(
                modifier = Modifier.size(SyncRowDefaults.SpinnerSize),
                strokeWidth = 2.dp,
                color = MaterialTheme.explainerColors.primary,
            )
            Spacer(Modifier.width(Spacing.Sm))
        }
        TextButton(
            onClick = { onAction(LibraryAction.Refresh) },
            enabled = !state.isRefreshing,
            modifier = Modifier.heightIn(min = MinimumTargets.Touch),
        ) {
            Icon(
                imageVector = ExplainerIcons.Refresh,
                contentDescription = null,
                modifier = Modifier.size(LibraryDefaults.ActionIconSize),
            )
            Spacer(Modifier.width(Spacing.Xs))
            Text(
                text = stringResource(R.string.library_sync),
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}

private object SyncRowDefaults {
    val SpinnerSize = 16.dp
}

@Composable
private fun lastSyncLabel(lastSyncAtMillis: Long): String {
    if (lastSyncAtMillis <= 0L) return stringResource(R.string.library_never_synced)
    return stringResource(R.string.library_last_sync, relativeLabel(lastSyncAtMillis))
}

@Composable
private fun relativeLabel(epochMillis: Long): String = when (
    val relative = LibraryFormat.relativeTime(epochMillis, System.currentTimeMillis())
) {
    RelativeTime.JustNow -> stringResource(R.string.time_just_now)
    is RelativeTime.MinutesAgo ->
        pluralStringResource(R.plurals.time_minutes_ago, relative.minutes, relative.minutes)

    is RelativeTime.HoursAgo ->
        pluralStringResource(R.plurals.time_hours_ago, relative.hours, relative.hours)

    is RelativeTime.DaysAgo ->
        pluralStringResource(R.plurals.time_days_ago, relative.days, relative.days)

    is RelativeTime.Older ->
        LibraryFormat.formatDate(
            relative.epochMillis,
            LocalLocale.current.platformLocale,
            ZoneOffset.UTC,
        )
}

/** Mensaje transitorio con icono, copia accionable y cierre explícito. */
@Composable
private fun MessageBanner(message: LibraryMessage, onDismiss: () -> Unit) {
    val colors = MaterialTheme.explainerColors
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = colors.surfaceContainerHighest,
        contentColor = MaterialTheme.colorScheme.onSurface,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacing.Lg, vertical = Spacing.Sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = if (message.kind == LibraryMessageKind.DOWNLOAD_SUCCEEDED) {
                    ExplainerIcons.Check
                } else {
                    ExplainerIcons.Info
                },
                contentDescription = null,
                tint = colors.primary,
                modifier = Modifier.size(LibraryDefaults.MetaIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = messageText(message),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f),
            )
            TextButton(
                onClick = onDismiss,
                modifier = Modifier.heightIn(min = OfflineBannerDefaults.MinimumHeight),
            ) {
                Text(
                    text = stringResource(R.string.action_close),
                    style = MaterialTheme.typography.labelLarge,
                )
            }
        }
    }
}

@Composable
private fun messageText(message: LibraryMessage): String {
    val res = LibraryLabels.messageRes(message.kind)
    return if (message.kind == LibraryMessageKind.DOWNLOAD_SUCCEEDED && message.projectName != null) {
        stringResource(res, message.projectName)
    } else {
        stringResource(res)
    }
}

/**
 * Fila de proyecto: título serif, estado con icono + label, meta con iconos
 * sutiles, UNA acción primaria dominante (Abrir/Descargar/Actualizar) y
 * secundarias discretas (Borrar copia local).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ProjectRow(
    row: ProjectRowUiModel,
    onOpen: () -> Unit,
    onDownload: () -> Unit,
    onDelete: () -> Unit,
    onCancel: () -> Unit,
) {
    val colors = MaterialTheme.explainerColors
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.Lg, vertical = Spacing.Md),
    ) {
        Text(
            text = row.name,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(Spacing.Xs))
        StatusIndicator(
            tone = LibraryLabels.primaryStatusTone(row),
            label = stringResource(LibraryLabels.primaryStatusRes(row)),
        )
        Spacer(Modifier.height(Spacing.Xs))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = ExplainerIcons.FolderOpen,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(LibraryDefaults.MetaIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = metaLabel(row),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        row.downloadResult?.let { result ->
            if (result.error != null) {
                Spacer(Modifier.height(Spacing.Xs))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = ExplainerIcons.Warning,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.size(LibraryDefaults.MetaIconSize),
                    )
                    Spacer(Modifier.width(Spacing.Sm))
                    Text(
                        text = stringResource(LibraryLabels.downloadErrorRes(result.error)),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
        row.downloadProgress?.let { progress ->
            Spacer(Modifier.height(Spacing.Sm))
            DownloadProgressRow(
                title = row.name,
                downloadedBytes = progress.downloadedBytes,
                totalBytes = progress.totalBytes,
                isEstimate = progress.isEstimate,
                onCancel = onCancel,
            )
        }
        Spacer(Modifier.height(Spacing.Sm))
        // FlowRow: a 200 % de escala de fuente las acciones envuelven en vez
        // de recortarse (compact/expanded nunca cortan las acciones).
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(Spacing.Sm),
            verticalArrangement = Arrangement.spacedBy(Spacing.Sm),
        ) {
            // Acción primaria dominante de la fila.
            when {
                row.hasSnapshot && row.availability != ProjectAvailability.UPDATE_POSSIBLE -> {
                    PrimaryAction(
                        label = stringResource(R.string.library_open),
                        icon = ExplainerIcons.KeyboardArrowRight,
                        onClick = onOpen,
                    )
                }

                row.availability == ProjectAvailability.REMOTE_ONLY -> {
                    PrimaryAction(
                        label = stringResource(R.string.library_download),
                        icon = ExplainerIcons.Download,
                        onClick = onDownload,
                    )
                }

                row.availability == ProjectAvailability.UPDATE_POSSIBLE -> {
                    PrimaryAction(
                        label = stringResource(R.string.library_update),
                        icon = ExplainerIcons.Refresh,
                        onClick = onDownload,
                    )
                }
            }
            // Secundarias discretas.
            if (row.hasSnapshot && row.availability == ProjectAvailability.UPDATE_POSSIBLE) {
                SecondaryAction(
                    label = stringResource(R.string.library_open),
                    icon = ExplainerIcons.KeyboardArrowRight,
                    onClick = onOpen,
                )
            }
            if (row.hasSnapshot) {
                SecondaryAction(
                    label = stringResource(R.string.library_delete),
                    icon = ExplainerIcons.Delete,
                    onClick = onDelete,
                    destructive = true,
                )
            }
        }
    }
}

/** Acción primaria de la fila: botón lleno, dominante. */
@Composable
private fun PrimaryAction(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = Modifier.heightIn(min = MinimumTargets.Touch),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            modifier = Modifier.size(LibraryDefaults.ActionIconSize),
        )
        Spacer(Modifier.width(Spacing.Xs))
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
        )
    }
}

/** Acción secundaria de la fila: discreta, con icono. */
@Composable
private fun SecondaryAction(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
    destructive: Boolean = false,
) {
    TextButton(
        onClick = onClick,
        modifier = Modifier.heightIn(min = MinimumTargets.Touch),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (destructive) {
                MaterialTheme.explainerColors.error
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier.size(LibraryDefaults.ActionIconSize),
        )
        Spacer(Modifier.width(Spacing.Xs))
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
            color = if (destructive) {
                MaterialTheme.explainerColors.error
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
    }
}

@Composable
private fun metaLabel(row: ProjectRowUiModel): String {
    val parts = pluralStringResource(R.plurals.library_parts, row.partCount, row.partCount)
    val updated = if (row.updatedAtEpochMillis > 0L) {
        stringResource(R.string.library_meta_updated, relativeLabel(row.updatedAtEpochMillis))
    } else {
        null
    }
    val size = if (row.hasSnapshot && row.snapshotBytes > 0L) {
        stringResource(R.string.library_size_exact, LibraryFormat.formatBytes(row.snapshotBytes))
    } else {
        null
    }
    return listOfNotNull(parts, updated, size).joinToString(" · ")
}

/**
 * Sheet de confirmación de descarga/actualización: rango SIEMPRE estimado,
 * tamaño exacto actual aparte, espacio requerido y "reemplaza, no duplica".
 * Reutiliza [ConfirmActionSheet] de T05 con icono de descarga.
 */
@Composable
private fun DownloadConfirmationSheet(
    confirmation: DownloadConfirmationUiModel,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val title = if (confirmation.isUpdate) {
        stringResource(R.string.sheet_update_title, confirmation.projectName)
    } else {
        stringResource(R.string.sheet_download_title, confirmation.projectName)
    }
    val lines = buildList {
        add(
            stringResource(
                R.string.sheet_estimate,
                LibraryFormat.formatRange(confirmation.estimateLowBytes, confirmation.estimateHighBytes),
            ),
        )
        if (confirmation.isUpdate && confirmation.currentSnapshotBytes != null) {
            add(
                stringResource(
                    R.string.sheet_current_exact,
                    LibraryFormat.formatBytes(confirmation.currentSnapshotBytes),
                ),
            )
        }
        add(
            stringResource(
                R.string.sheet_required,
                LibraryFormat.formatBytes(confirmation.requiredFreeBytes),
            ),
        )
        add(stringResource(R.string.sheet_replace_copy))
    }
    ConfirmActionSheet(
        title = title,
        message = lines.joinToString("\n"),
        confirmLabel = stringResource(
            if (confirmation.isUpdate) R.string.library_update else R.string.library_download,
        ),
        icon = if (confirmation.isUpdate) ExplainerIcons.Refresh else ExplainerIcons.Download,
        onConfirm = onConfirm,
        onDismiss = onDismiss,
    )
}

private object LibraryDefaults {
    val ActionIconSize = 18.dp
    val MetaIconSize = 14.dp
    val EmptyIconSize = 40.dp
}

// ---- Previews (estáticas; ninguna inicia red/Room/WorkManager) ----

private val previewNoOp: () -> Unit = {}

private val previewRow = ProjectRowUiModel(
    projectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f"),
    name = "Historia de Roma: de la República al Imperio",
    status = ProjectStatus.Completed,
    availability = ProjectAvailability.OFFLINE,
    hasSnapshot = true,
    snapshotBytes = 4_194_304L,
    updatedAtEpochMillis = 1_752_000_000_000L,
    partCount = 7,
)

@Preview(name = "Library list (light, compact)", widthDp = 360, heightDp = 800, showBackground = true)
@Composable
private fun LibraryListLightPreview() {
    ExplainerTheme(mode = ThemeMode.LIGHT) {
        ProjectLibraryScreen(
            state = LibraryUiState.Content(
                rows = listOf(
                    previewRow,
                    previewRow.copy(
                        name = "Termodinámica para ingenieros",
                        availability = ProjectAvailability.UPDATE_POSSIBLE,
                        snapshotBytes = 2_097_152L,
                    ),
                    previewRow.copy(
                        name = "Álgebra lineal y aplicaciones",
                        availability = ProjectAvailability.REMOTE_ONLY,
                        hasSnapshot = false,
                        snapshotBytes = 0L,
                        status = ProjectStatus.Processing,
                    ),
                ),
                isOffline = false,
                isRefreshing = false,
                lastSyncAtMillis = System.currentTimeMillis() - 5 * 60_000L,
                message = null,
                confirmation = null,
                deleteTarget = null,
            ),
            onAction = {},
        )
    }
}

@Preview(name = "Library offline (dark, expanded)", widthDp = 840, heightDp = 800, showBackground = true)
@Composable
private fun LibraryOfflineDarkPreview() {
    BootstrapTheme {
        ProjectLibraryScreen(
            state = LibraryUiState.Content(
                rows = listOf(
                    previewRow.copy(
                        downloadProgress = DownloadProgressUi(
                            downloadedBytes = 512L * 1024L,
                            totalBytes = null,
                            isEstimate = true,
                        ),
                    ),
                ),
                isOffline = true,
                isRefreshing = false,
                lastSyncAtMillis = 0L,
                message = LibraryMessage(LibraryMessageKind.DOWNLOAD_SUCCEEDED, "Historia de Roma"),
                confirmation = null,
                deleteTarget = null,
            ),
            onAction = {},
        )
    }
}

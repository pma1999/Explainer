package com.explainer.app.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.explainer.app.R
import com.explainer.app.core.model.ProjectId
import com.explainer.app.ui.components.ConfirmActionSheet
import com.explainer.app.ui.components.ExplainerIcons
import com.explainer.app.ui.components.ExplainerTopBar
import com.explainer.app.ui.components.OperationState
import com.explainer.app.ui.components.OperationStatePanel
import com.explainer.app.ui.library.LibraryFormat
import com.explainer.app.ui.theme.ExplainerColors
import com.explainer.app.ui.theme.ExplainerTheme
import com.explainer.app.ui.theme.MinimumTargets
import com.explainer.app.ui.theme.Spacing
import com.explainer.app.ui.theme.explainerColors
import com.explainer.app.ui.theme.ThemeMode

/**
 * Pantalla de Ajustes (T11), stateless: recibe [SettingsUiState] inmutable y
 * emite [SettingsAction]. Tema claro/oscuro/sistema con preview visual por
 * fila, identidad local no secreta y almacenamiento (bytes lógicos por
 * proyecto offline) con borrado individual/total SIEMPRE confirmado. Las
 * acciones destructivas tienen jerarquía clara (icono + color de error +
 * confirmación explícita). Contenido desplazable: a 200 % de escala de
 * fuente nada se corta; targets >= [SettingsScreenDefaults.MinimumTargetSize].
 */
@Composable
fun SettingsScreen(
    state: SettingsUiState,
    onAction: (SettingsAction) -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
        contentColor = MaterialTheme.colorScheme.onBackground,
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            ExplainerTopBar(
                title = stringResource(R.string.settings_title),
                onNavigationClick = { onAction(SettingsAction.Back) },
            )
            when (state) {
                SettingsUiState.Loading -> OperationStatePanel(state = OperationState.LOADING)
                SettingsUiState.SignedOut -> OperationStatePanel(
                    state = OperationState.ERROR,
                    title = stringResource(R.string.session_ended_title),
                    message = stringResource(R.string.session_ended_message),
                )

                is SettingsUiState.Content -> ContentColumn(state = state, onAction = onAction)
            }
        }
    }

    if (state is SettingsUiState.Content && state.confirmation != null) {
        val confirmation = state.confirmation
        val projectName = (confirmation as? SettingsConfirmation.DeleteProject)
            ?.let { target ->
                state.storageRows.firstOrNull { it.projectId == target.projectId }?.name
            }
        // R-T11-07: el título de borrado de proyecto exige %1$s — el nombre
        // se pasa con el overload formateado; sin nombre no hay argumento.
        val title = SettingsLabels.confirmationTitle(confirmation, projectName)
        ConfirmActionSheet(
            title = if (title.arg != null) {
                stringResource(title.res, title.arg)
            } else {
                stringResource(title.res)
            },
            message = stringResource(SettingsLabels.confirmationMessageRes(confirmation)),
            confirmLabel = stringResource(SettingsLabels.confirmationLabelRes(confirmation)),
            destructive = true,
            icon = when (confirmation) {
                SettingsConfirmation.SignOut -> ExplainerIcons.Logout
                SettingsConfirmation.DeleteAll -> ExplainerIcons.Delete
                is SettingsConfirmation.DeleteProject -> ExplainerIcons.Delete
            },
            onConfirm = {
                when (confirmation) {
                    SettingsConfirmation.SignOut -> onAction(SettingsAction.ConfirmSignOut)
                    SettingsConfirmation.DeleteAll -> onAction(SettingsAction.ConfirmDeleteAll)
                    is SettingsConfirmation.DeleteProject ->
                        onAction(SettingsAction.ConfirmDeleteProject(confirmation.projectId))
                }
            },
            onDismiss = { onAction(SettingsAction.DismissConfirm) },
        )
    }
}

@Composable
private fun ContentColumn(state: SettingsUiState.Content, onAction: (SettingsAction) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = Spacing.Xl),
    ) {
        SectionHeader(stringResource(R.string.settings_theme_section))
        ThemeMode.entries.forEach { mode ->
            ThemeRow(
                mode = mode,
                selected = state.themeMode == mode,
                onClick = { onAction(SettingsAction.SetThemeMode(mode)) },
            )
        }

        Spacer(Modifier.height(Spacing.Lg))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Spacer(Modifier.height(Spacing.Lg))

        SectionHeader(stringResource(R.string.settings_account_section))
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = Spacing.Sm),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = ExplainerIcons.Email,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(SettingsDefaults.MetaIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = state.ownerEmail ?: stringResource(R.string.settings_account_email_hidden),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        TextButton(
            onClick = { onAction(SettingsAction.RequestSignOut) },
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = SettingsScreenDefaults.MinimumTargetSize),
        ) {
            Icon(
                imageVector = ExplainerIcons.Logout,
                contentDescription = null,
                tint = MaterialTheme.explainerColors.error,
                modifier = Modifier.size(SettingsDefaults.ActionIconSize),
            )
            Spacer(Modifier.width(Spacing.Sm))
            Text(
                text = stringResource(R.string.settings_sign_out),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.explainerColors.error,
            )
        }

        Spacer(Modifier.height(Spacing.Lg))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Spacer(Modifier.height(Spacing.Lg))

        SectionHeader(stringResource(R.string.settings_storage_section))
        if (state.storageRows.isEmpty()) {
            Text(
                text = stringResource(R.string.settings_storage_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = Spacing.Sm),
            )
        } else {
            state.storageRows.forEach { row ->
                StorageRow(row = row, onDelete = { onAction(SettingsAction.RequestDeleteProject(row.projectId)) })
            }
            Spacer(Modifier.height(Spacing.Sm))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = Spacing.Sm),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = ExplainerIcons.Storage,
                    contentDescription = null,
                    tint = MaterialTheme.explainerColors.primary,
                    modifier = Modifier.size(SettingsDefaults.MetaIconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
                Text(
                    text = stringResource(R.string.settings_storage_total, LibraryFormat.formatBytes(state.totalBytes)),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
            TextButton(
                onClick = { onAction(SettingsAction.RequestDeleteAll) },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = SettingsScreenDefaults.MinimumTargetSize),
            ) {
                Icon(
                    imageVector = ExplainerIcons.Delete,
                    contentDescription = null,
                    tint = MaterialTheme.explainerColors.error,
                    modifier = Modifier.size(SettingsDefaults.ActionIconSize),
                )
                Spacer(Modifier.width(Spacing.Sm))
                Text(
                    text = stringResource(R.string.settings_delete_all),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.explainerColors.error,
                )
            }
        }
        Spacer(Modifier.height(Spacing.Xxl))
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.onSurface,
        modifier = Modifier.padding(vertical = Spacing.Sm),
    )
}

/** Fila de tema: radio + preview visual de la paleta + label. */
@Composable
private fun ThemeRow(mode: ThemeMode, selected: Boolean, onClick: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = SettingsScreenDefaults.MinimumTargetSize)
            .clickable(onClick = onClick)
            .padding(horizontal = Spacing.Sm),
    ) {
        RadioButton(
            selected = selected,
            onClick = onClick,
            modifier = Modifier.heightIn(min = SettingsScreenDefaults.MinimumTargetSize),
        )
        Spacer(Modifier.width(Spacing.Md))
        ThemeSwatch(mode = mode)
        Spacer(Modifier.width(Spacing.Md))
        Text(
            text = stringResource(SettingsLabels.themeModeLabelRes(mode)),
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

/**
 * Miniatura de la paleta del modo (planos, sin gradientes): papel/tinta con
 * una línea de texto y una línea del acento dorado; SYSTEM muestra las dos
 * mitades. Decorativa: la selección viaja en el radio y el label.
 */
@Composable
private fun ThemeSwatch(mode: ThemeMode) {
    Box(
        modifier = Modifier
            .size(SettingsDefaults.SwatchWidth, SettingsDefaults.SwatchHeight)
            .clip(RoundedCornerShape(SettingsDefaults.SwatchCorner))
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        when (mode) {
            ThemeMode.LIGHT -> PaletteSwatch(ExplainerColors.Light)
            ThemeMode.DARK -> PaletteSwatch(ExplainerColors.Dark)
            ThemeMode.SYSTEM -> Row(modifier = Modifier.fillMaxSize()) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight(),
                ) {
                    PaletteSwatch(ExplainerColors.Light, modifier = Modifier.fillMaxSize())
                }
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight(),
                ) {
                    PaletteSwatch(ExplainerColors.Dark, modifier = Modifier.fillMaxSize())
                }
            }
        }
    }
}

@Composable
private fun PaletteSwatch(colors: ExplainerColors, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(SettingsDefaults.SwatchCorner))
            .background(colors.background)
            .padding(horizontal = Spacing.Sm, vertical = Spacing.Xs),
        verticalArrangement = Arrangement.Center,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(SettingsDefaults.SwatchBarHeight)
                .clip(RoundedCornerShape(SettingsDefaults.SwatchBarCorner))
                .background(colors.onSurface),
        )
        Spacer(Modifier.height(Spacing.Xs))
        Box(
            modifier = Modifier
                .fillMaxWidth(SettingsDefaults.SwatchAccentFraction)
                .height(SettingsDefaults.SwatchBarHeight)
                .clip(RoundedCornerShape(SettingsDefaults.SwatchBarCorner))
                .background(colors.primary),
        )
    }
}

@Composable
private fun StorageRow(row: StorageRowUi, onDelete: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = SettingsScreenDefaults.MinimumTargetSize),
    ) {
        Icon(
            imageVector = ExplainerIcons.FolderOpen,
            contentDescription = null,
            tint = MaterialTheme.explainerColors.primary,
            modifier = Modifier.size(SettingsDefaults.MetaIconSize),
        )
        Spacer(Modifier.width(Spacing.Md))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = row.name,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
            )
            Text(
                text = LibraryFormat.formatBytes(row.bytes),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        TextButton(
            onClick = onDelete,
            modifier = Modifier.heightIn(min = SettingsScreenDefaults.MinimumTargetSize),
        ) {
            Icon(
                imageVector = ExplainerIcons.Delete,
                contentDescription = null,
                tint = MaterialTheme.explainerColors.error,
                modifier = Modifier.size(SettingsDefaults.ActionIconSize),
            )
            Spacer(Modifier.width(Spacing.Xs))
            Text(
                text = stringResource(R.string.settings_delete_project),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.explainerColors.error,
            )
        }
    }
}

object SettingsScreenDefaults {
    /** Target táctil mínimo declarado (filas y botones de Ajustes). */
    val MinimumTargetSize: Dp = MinimumTargets.Touch
}

private object SettingsDefaults {
    val ActionIconSize = 18.dp
    val MetaIconSize = 16.dp
    val SwatchWidth = 44.dp
    val SwatchHeight = 30.dp
    val SwatchCorner = 6.dp
    val SwatchBarHeight = 4.dp
    val SwatchBarCorner = 2.dp
    val SwatchAccentFraction = 0.6f
}

@Preview
@Composable
private fun SettingsScreenPreview() {
    ExplainerTheme {
        SettingsScreen(
            state = SettingsUiState.Content(
                themeMode = ThemeMode.SYSTEM,
                ownerEmail = "lectora@example.com",
                storageRows = listOf(
                    StorageRowUi(
                        projectId = ProjectId("3f2b8c1e-9a4d-4f6b-8c2e-1d5a7b9c0e3f"),
                        name = "Proyecto de prueba",
                        bytes = 3_145_728L,
                    ),
                ),
                totalBytes = 3_145_728L,
                confirmation = null,
            ),
            onAction = {},
        )
    }
}
